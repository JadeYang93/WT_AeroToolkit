# -*- coding: utf-8 -*-
"""风速清洗、TI 滑窗计算、日级统计（并行+缓存）、周/月聚合。"""
import os
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd

from config import (
    WINDOW_MIN, STEP_MIN, VALID_RATIO, MIN_MEAN_SPEED,
    MONTH_DAY_THRESHOLD, WEEK_DAY_THRESHOLD,
    DIFF_THRESHOLD, MIN_SPEED, MAX_SPEED, MISSING_MARK,
)
from core.io_utils import scan_data_files, read_data_file, read_data_file_detected, detect_columns


# ================================================================
# 风速清洗与TI计算
# ================================================================
def clean_wind_speed(ws):
    """风速清洗4步：缺测、尖刺、负值、超量程。

    Args:
        ws: array-like of float
    Returns:
        np.ndarray with np.nan for removed points
    """
    ws_clean = np.array(ws, dtype=float).copy()
    ws_clean[ws_clean <= MISSING_MARK] = np.nan
    diff = np.abs(np.diff(ws_clean, prepend=ws_clean[0]))
    ws_clean[diff > DIFF_THRESHOLD] = np.nan
    ws_clean[ws_clean < MIN_SPEED] = np.nan
    ws_clean[ws_clean > MAX_SPEED] = np.nan
    return ws_clean


def compute_ti_sliding(ws_clean, window_min=None, step_min=None, valid_ratio=None):
    """滑动窗口计算 TI 序列（向量化实现）。

    用 np.lib.stride_tricks.sliding_window_view 一次性构造所有窗口的
    (n_windows, window_sec) 二维矩阵，把原 Python 逐窗口循环替换成单次
    numpy 沿 axis=1 的聚合。算法语义、输出顺序与原循环版完全一致，
    但大文件下快 10-50 倍（避免每窗口 4 次 Python↔C 调用）。

    Args:
        ws_clean: 已清洗的风速数组（秒级）
        window_min: 滑动窗口（分钟），None=用默认 WINDOW_MIN
        step_min: 滑动步长（分钟），None=用默认 STEP_MIN
        valid_ratio: 窗口有效率阈值，None=用默认 VALID_RATIO
    Returns:
        (ti_arr, mean_speed_arr): 每个窗口的 TI 值和平均风速（无效为 np.nan）
    """
    w = window_min if window_min is not None else WINDOW_MIN
    s = step_min if step_min is not None else STEP_MIN
    v = valid_ratio if valid_ratio is not None else VALID_RATIO
    window_sec = w * 60
    step_sec = s * 60
    total = len(ws_clean)
    if total < window_sec:
        return np.array([]), np.array([])

    # sliding_window_view 返回 (total - window_sec + 1, window_sec) 的零拷贝视图，
    # 按 step_sec 抽样即得到所有滑动窗口（与原循环 start=0,step_sec,2*step_sec... 等价）
    all_windows = np.lib.stride_tricks.sliding_window_view(ws_clean, window_sec)
    windows = all_windows[::step_sec]
    n_windows = windows.shape[0]

    # 每窗口的有效（非 NaN）样本数
    valid_counts = np.sum(~np.isnan(windows), axis=1)
    valid_mask = valid_counts >= v * window_sec

    ti_arr = np.full(n_windows, np.nan)
    ms_arr = np.full(n_windows, np.nan)
    if valid_mask.any():
        vw = windows[valid_mask]
        with np.errstate(invalid='ignore', divide='ignore'):
            u_mean = np.nanmean(vw, axis=1)
            u_std = np.nanstd(vw, axis=1, ddof=1)
        ms_arr[valid_mask] = u_mean
        # 风速阈值：u_mean > MIN_MEAN_SPEED 才计算 TI，否则置 NaN（与原逻辑一致）
        speed_ok = u_mean > MIN_MEAN_SPEED
        ti_arr[valid_mask] = np.where(speed_ok, u_std / u_mean, np.nan)

    return ti_arr, ms_arr

# ================================================================
# 日级统计（并行 + 缓存）
# ================================================================
CACHE_VERSION = 4   # 缓存格式版本（清理逻辑或TI算法变更时递增）


def _compute_one_file(fpath, ext, turbine, date_str, ti_params):
    """单文件处理：读取、识别列、计算指标。线程安全。

    使用 read_data_file_detected 走 sniff+usecols 优化路径（CSV 只读
    时间/风速/密度 列，pyarrow 引擎 + usecols 比全读快约 3 倍）。

    Args:
        ti_params: dict, 可含 'window_min'/'step_min'/'valid_ratio'
    Returns:
        record dict 或 None（读取失败/无时间列时）
    """
    try:
        df, cols = read_data_file_detected(fpath, ext)
    except Exception:
        return None

    if cols['time'] is None:
        return None

    record = {
        'date': pd.Timestamp(date_str),
        'turbine': turbine,
        'day_count': 1,
    }

    # 风速 + TI
    if cols['wind'] is not None:
        ws = df[cols['wind']].values
        ws_clean = clean_wind_speed(ws)
        valid_ws = ws_clean[~np.isnan(ws_clean)]
        if len(valid_ws) > 0:
            record['wind_speed'] = float(np.mean(valid_ws))
            record['wind_count'] = int(len(valid_ws))
            ti_arr, ms_arr = compute_ti_sliding(
                ws_clean,
                window_min=ti_params.get('window_min'),
                step_min=ti_params.get('step_min'),
                valid_ratio=ti_params.get('valid_ratio'),
            )
            if ti_arr.size > 0:
                valid_mask = ~np.isnan(ti_arr)
                valid_ti = ti_arr[valid_mask]
                if len(valid_ti) > 0:
                    record['ti'] = float(np.mean(valid_ti))
                    record['ti_count'] = int(len(valid_ti))
                    # 保留窗口级 (mean_speed, ti) 供风速 bin 分析
                    record['ti_windows'] = list(zip(
                        ms_arr[valid_mask].tolist(),
                        valid_ti.tolist()
                    ))

    # 密度
    if cols['density'] is not None:
        den = pd.to_numeric(df[cols['density']], errors='coerce').values
        valid_den = den[~np.isnan(den)]
        if len(valid_den) > 0:
            record['density'] = float(np.mean(valid_den))
            record['density_count'] = int(len(valid_den))

    return record


def _file_cache_key(fpath, fname, ti_params):
    """生成文件缓存键：(文件名, mtime, size, TI参数) 的 tuple。"""
    try:
        st = os.stat(fpath)
        mtime = int(st.st_mtime)
        size = int(st.st_size)
    except OSError:
        mtime = 0
        size = 0
    return (
        fname, mtime, size,
        ti_params.get('window_min', WINDOW_MIN),
        ti_params.get('step_min', STEP_MIN),
        ti_params.get('valid_ratio', VALID_RATIO),
        CACHE_VERSION,
    )


def compute_daily_stats(data_dir, progress_callback=None, include_turbines=None,
                        ti_params=None, cache_path=None, max_workers=None,
                        start_date=None, end_date=None):
    """处理输入目录下所有文件，计算每文件(=每天)的统计量。

    Args:
        data_dir: 输入文件夹路径
        progress_callback: 可选 fn(percent:int|None, msg:str)
        include_turbines: list[int] 或 None；若给出，只处理这些机组
        ti_params: dict 或 None；可含 window_min/step_min/valid_ratio
        cache_path: pickle 缓存文件路径；None=不缓存
        max_workers: 并行线程数；None=自动（min(8, CPU数)）
        start_date/end_date: pd.Timestamp 或 None；按文件名日期过滤（含端点）
    Returns:
        (df_daily, ti_bin_data): df_daily 为日级统计 DataFrame；
        ti_bin_data 为 list[dict]，每项 {'turbine', 'date', 'mean_speed', 'ti'}，
        供风速 bin 分析使用（无风速数据的文件不含 ti_windows）。
    """
    files = scan_data_files(data_dir)
    if include_turbines is not None:
        files = [f for f in files if f['turbine'] in include_turbines]
    # 日期过滤
    if start_date is not None or end_date is not None:
        filtered = []
        for f in files:
            try:
                d = pd.Timestamp(f['date_str'])
            except Exception:
                continue
            if start_date is not None and d < start_date:
                continue
            if end_date is not None and d > end_date:
                continue
            filtered.append(f)
        files = filtered
    total = len(files)
    if total == 0:
        return pd.DataFrame(), []

    ti_params = ti_params or {}

    # 加载缓存
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as fp:
                cache_data = pickle.load(fp)
            if isinstance(cache_data, dict) and cache_data.get('version') == CACHE_VERSION:
                cache = cache_data.get('entries', {})
        except Exception:
            cache = {}

    # 分流：命中缓存的 vs 需要计算的
    to_compute = []
    cached_records = {}   # fname -> record
    for f in files:
        fpath = os.path.join(data_dir, f['fname'])
        key = _file_cache_key(fpath, f['fname'], ti_params)
        if key in cache:
            cached_records[f['fname']] = cache[key]
        else:
            to_compute.append((f, fpath, key))

    if progress_callback and cached_records:
        progress_callback(None, f'  [缓存] 命中 {len(cached_records)}/{total} 个文件，跳过读取')

    # 并行计算未命中部分
    new_records = {}      # fname -> record
    if to_compute:
        if max_workers is None:
            # TI 计算已向量化（numpy 在 C 层释放 GIL），CSV 解析也在 C 层释放 GIL，
            # 因此线程能真正并行 I/O + 计算；放宽到 2×CPU（上限 16）以压满多核
            max_workers = min(16, (os.cpu_count() or 4) * 2)
        completed = len(cached_records)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {
                ex.submit(_compute_one_file, fpath, f['ext'], f['turbine'], f['date_str'], ti_params): (f, key)
                for f, fpath, key in to_compute
            }
            for future in as_completed(futures):
                f, key = futures[future]
                completed += 1
                if progress_callback:
                    progress_callback(
                        completed * 50 // total,
                        f'  [{completed}/{total}] {f["fname"]}'
                    )
                try:
                    record = future.result()
                except Exception as e:
                    if progress_callback:
                        progress_callback(None, f'  [警告] {f["fname"]}: {e}')
                    continue
                if record is None:
                    if progress_callback:
                        progress_callback(None, f'  [警告] {f["fname"]} 无法处理（读取失败或无时间列）')
                    continue
                new_records[f['fname']] = record
                cache[key] = record

    # 写回缓存
    if cache_path and to_compute:
        try:
            with open(cache_path, 'wb') as fp:
                pickle.dump({'version': CACHE_VERSION, 'entries': cache}, fp)
        except Exception:
            pass

    # 按原文件顺序合并，同时提取窗口级 TI 数据用于 bin 分析
    all_records = []
    ti_bin_data = []
    for f in files:
        rec = cached_records.get(f['fname']) or new_records.get(f['fname'])
        if rec is None:
            continue
        all_records.append(rec)
        windows = rec.get('ti_windows')
        if windows:
            turbine = rec['turbine']
            date = rec['date']
            for ms, ti in windows:
                ti_bin_data.append({
                    'turbine': turbine, 'date': date,
                    'mean_speed': ms, 'ti': ti,
                })

    return pd.DataFrame(all_records), ti_bin_data

# ================================================================
# 周/月聚合
# ================================================================
METRIC_COLS = ('wind_speed', 'ti', 'density')


def aggregate_weekly(df_daily):
    """按ISO周聚合。week_start = 该周周一日期。

    每机组每周需≥WEEK_DAY_THRESHOLD天才计入。
    """
    if df_daily.empty:
        return pd.DataFrame()
    df = df_daily.copy()
    df['week_start'] = df['date'] - pd.to_timedelta(df['date'].dt.weekday, unit='D')
    records = []
    for (turbine, week_start), grp in df.groupby(['turbine', 'week_start']):
        if len(grp) < WEEK_DAY_THRESHOLD:
            continue
        row = {'turbine': turbine, 'week_start': week_start, 'day_count': len(grp)}
        for c in METRIC_COLS:
            if c in grp.columns:
                vals = grp[c].dropna()
                if len(vals) > 0:
                    row[c] = float(vals.mean())
        records.append(row)
    return pd.DataFrame(records)


def aggregate_monthly(df_daily):
    """按月聚合。month 为 Period('M')。

    每机组每月需≥MONTH_DAY_THRESHOLD天才计入。
    """
    if df_daily.empty:
        return pd.DataFrame()
    df = df_daily.copy()
    df['month'] = df['date'].dt.to_period('M')
    records = []
    for (turbine, month), grp in df.groupby(['turbine', 'month']):
        if len(grp) < MONTH_DAY_THRESHOLD:
            continue
        row = {'turbine': turbine, 'month': month, 'day_count': len(grp)}
        for c in METRIC_COLS:
            if c in grp.columns:
                vals = grp[c].dropna()
                if len(vals) > 0:
                    row[c] = float(vals.mean())
        records.append(row)
    return pd.DataFrame(records)
