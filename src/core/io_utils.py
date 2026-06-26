# -*- coding: utf-8 -*-
"""文件名解析、目录扫描、列头识别、CSV/XLSX 读取（支持 .gz 压缩）。"""
import os
import re
import gzip
from io import BytesIO
import pandas as pd

from config import SKIP_FILES, ENCODINGS


# CSV 解析引擎：优先 pyarrow（2-3x 更快，C 层零拷贝），不可用时回退默认 C engine
try:
    import pyarrow  # noqa: F401
    _CSV_ENGINE = 'pyarrow'
except ImportError:
    _CSV_ENGINE = None


# ================================================================
# 文件名解析与扫描
# ================================================================
# 扩展名支持 .gz 压缩：csv.gz / xlsx.gz（xlsx 本身已是 zip，再套 gz 节省有限，
# 但现场数据归档常见统一打 gz 包，故一并支持）
FILENAME_PATTERN = re.compile(
    r'^(.+?)_(\d+)_(.+?)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.(csv(?:\.gz)?|xlsx(?:\.gz)?)$'
)


def parse_filename(fname):
    """解析文件名。

    Returns:
        tuple (farm, turbine:int, date_str, ext) 或 None（不匹配时）
    """
    m = FILENAME_PATTERN.match(fname)
    if not m:
        return None
    return m.group(1), int(m.group(2)), m.group(4), m.group(6)


def scan_data_files(data_dir):
    """扫描目录下符合命名规则的数据文件。

    Returns:
        list of dict: [{fname, farm, turbine, date_str, ext}, ...]
    """
    results = []
    try:
        names = sorted(os.listdir(data_dir))
    except OSError:
        return results
    for fname in names:
        if fname in SKIP_FILES:
            continue
        parsed = parse_filename(fname)
        if not parsed:
            continue
        farm, turbine, date_str, ext = parsed
        results.append({
            'fname': fname,
            'farm': farm,
            'turbine': turbine,
            'date_str': date_str,
            'ext': ext,
        })
    return results


# ================================================================
# 月度湍流预计算文件
# ================================================================
def scan_monthly_ti_files(data_dir, pattern='月度湍流'):
    """扫描目录下的月度湍流预计算文件（文件名含指定关键字）。

    Args:
        data_dir: 扫描目录
        pattern: 文件名子串匹配关键字。默认「月度湍流」。未来不同模块有不同命名约定时
                 可由各自面板传入不同 pattern。

    Returns:
        list of str: 文件名列表
    """
    results = []
    try:
        names = sorted(os.listdir(data_dir))
    except OSError:
        return results
    for fname in names:
        if fname in SKIP_FILES:
            continue
        if fname.startswith('~$'):
            continue
        if not (fname.endswith('.xlsx') or fname.endswith('.xlsx.gz')):
            continue
        if pattern in fname:
            results.append(fname)
    return results


def _find_col_by_keyword(df, keywords):
    """按关键字匹配列名，返回第一个匹配的列名。"""
    for c in df.columns:
        cl = str(c).lower()
        for kw in keywords:
            if kw.lower() in cl:
                return c
    return None


def read_monthly_ti_file(fpath):
    """读取月度湍流文件，解析为标准格式。支持 .xlsx 和 .xlsx.gz。

    Returns:
        pd.DataFrame: columns = [turbine(int), month(Period), bin_center(int), ti(float), count(int)]
    """
    if fpath.endswith('.gz'):
        # pd.read_excel 不支持 compression 参数，先解 gzip 到内存再读
        with gzip.open(fpath, 'rb') as f:
            df = pd.read_excel(BytesIO(f.read()))
    else:
        df = pd.read_excel(fpath)
    col_turbine = _find_col_by_keyword(df, ['机位', '机组', '涡轮'])
    col_month = _find_col_by_keyword(df, ['月'])
    col_bin = _find_col_by_keyword(df, ['风速', 'bin', '标签'])
    col_ti = _find_col_by_keyword(df, ['数值', '湍流'])
    col_count = _find_col_by_keyword(df, ['样本', '数据量', '数量', 'count'])

    if not all([col_turbine, col_month, col_bin, col_ti]):
        return pd.DataFrame()

    result = pd.DataFrame()
    result['turbine'] = pd.to_numeric(df[col_turbine], errors='coerce').astype('Int64')
    result['month'] = pd.to_datetime(df[col_month]).dt.to_period('M')
    result['bin_center'] = pd.to_numeric(df[col_bin], errors='coerce').astype('Int64')
    result['ti'] = pd.to_numeric(df[col_ti], errors='coerce')
    if col_count:
        result['count'] = pd.to_numeric(df[col_count], errors='coerce').fillna(0).astype(int)
    else:
        result['count'] = 1
    return result.dropna(subset=['turbine', 'ti', 'bin_center'])


def get_monthly_ti_summary(data_dir):
    """扫描月度湍流文件，返回机组/月份汇总（供 GUI 显示扫描结果用）。

    Returns:
        dict: {'turbines': set[int], 'months': sorted list[pd.Period], 'files': list[str]}
    """
    turbines = set()
    months = set()
    files = scan_monthly_ti_files(data_dir)
    for fname in files:
        try:
            df = read_monthly_ti_file(os.path.join(data_dir, fname))
            if df.empty:
                continue
            turbines.update(df['turbine'].dropna().astype(int).unique())
            months.update(df['month'].dropna().unique())
        except Exception:
            continue
    return {
        'turbines': turbines,
        'months': sorted(months),
        'files': files,
    }


# ================================================================
# 列识别与文件读取
# ================================================================
def detect_columns(df):
    """按列名关键字识别 时间/风速/密度 列。

    Returns:
        dict: {'time': col_or_None, 'wind': col_or_None, 'density': col_or_None}
    """
    result = {'time': None, 'wind': None, 'density': None}
    for c in df.columns:
        cl = str(c).lower()
        if result['time'] is None and any(k in cl for k in ('时间', 'time', '日期', 'date')):
            result['time'] = c
        if result['wind'] is None and any(k in cl for k in ('风速', 'wind')):
            result['wind'] = c
        if result['density'] is None and any(k in cl for k in ('密度', 'density')):
            result['density'] = c
    return result


def read_data_file(fpath, ext):
    """读取 CSV/XLSX（支持 .gz 压缩），CSV 自动尝试多种编码。

    Args:
        fpath: 文件路径（.csv / .csv.gz / .xlsx / .xlsx.gz）
        ext: 文件扩展名（'csv' / 'csv.gz' / 'xlsx' / 'xlsx.gz'）

    Raises:
        ValueError: 编码无法识别
        Exception: 其他读取错误
    """
    if ext.startswith('xlsx'):
        # .xlsx.gz：read_excel 不接受 compression，需先解 gzip
        if ext.endswith('.gz'):
            with gzip.open(fpath, 'rb') as f:
                return pd.read_excel(BytesIO(f.read()))
        return pd.read_excel(fpath)
    # CSV（含 .csv.gz）：compression='infer' 让 pandas 按后缀自动解 gzip；
    # engine 优先 pyarrow（比默认 C engine 快 2-3 倍），未装时回退
    for enc in ENCODINGS:
        try:
            return pd.read_csv(fpath, encoding=enc, compression='infer',
                               engine=_CSV_ENGINE)
        except UnicodeDecodeError:
            continue
    raise ValueError(f'无法识别编码: {fpath}')


# ================================================================
# 多风场对比（wind_farm_compare）
# ================================================================
# 与 export.py 输出的 Excel 文件名保持一致，作为风场对比模块的输入契约
EXCEL_FILENAME = '风场统计数据.xlsx'


def scan_farm_dirs(parent_dir):
    """扫描多风场对比的输入目录，列出每个风场子目录。

    每个子目录视为一个风场，要求里面存在 风场统计数据.xlsx（由 wind_farm 模块生成）。

    Args:
        parent_dir: 输入根目录，形如 .../输入数据/wind_farm_compare/
    Returns:
        list[dict]: [{
            'name': str (风场名 = 子目录名),
            'dir': str (子目录绝对路径),
            'excel_path': str or None (xlsx 路径，缺失则 None),
            'has_excel': bool,
        }, ...]，按子目录名排序。
    """
    results = []
    try:
        names = sorted(os.listdir(parent_dir))
    except OSError:
        return results
    for name in names:
        full = os.path.join(parent_dir, name)
        if not os.path.isdir(full):
            continue
        # 跳过隐藏目录（.开头，常见于 macOS / 临时目录）
        if name.startswith('.'):
            continue
        excel_path = os.path.join(full, EXCEL_FILENAME)
        results.append({
            'name': name,
            'dir': full,
            'excel_path': excel_path if os.path.exists(excel_path) else None,
            'has_excel': os.path.exists(excel_path),
        })
    return results


def read_data_file_detected(fpath, ext):
    """读 CSV/XLSX 并返回 (df, detected_cols)，CSV 启用 sniff+usecols 优化。

    优化逻辑：先用默认 C engine 以 nrows=0 读表头（~3ms），detect_columns
    找出 时间/风速/密度 列后，再用 pyarrow + usecols 只读这些列（3x 加速）。
    秒级 SCADA 数据通常只有 2-3 列有效，其余是辅助列，跳过它们能省 60-70% IO。

    Returns:
        (df, cols_dict): cols_dict 形如 {'time':..., 'wind':..., 'density':...}，
        缺列对应位置为 None；调用方无需再 detect_columns 一次。
    Raises:
        ValueError: 编码无法识别
    """
    if ext.startswith('xlsx'):
        if ext.endswith('.gz'):
            with gzip.open(fpath, 'rb') as f:
                df = pd.read_excel(BytesIO(f.read()))
        else:
            df = pd.read_excel(fpath)
        return df, detect_columns(df)

    # CSV：先用 C engine sniff 表头（pyarrow 不支持 nrows=0）
    header_df = None
    chosen_enc = None
    for enc in ENCODINGS:
        try:
            header_df = pd.read_csv(fpath, encoding=enc, compression='infer', nrows=0)
            chosen_enc = enc
            break
        except UnicodeDecodeError:
            continue
    if header_df is None:
        raise ValueError(f'无法识别编码: {fpath}')

    cols = detect_columns(header_df)
    needed = [c for c in (cols['time'], cols['wind'], cols['density']) if c]
    # 找到有效列且少于总列数 → usecols 只读这些（pyarrow + usecols ~3x 快于全读）
    if needed and len(needed) < len(header_df.columns):
        df = pd.read_csv(fpath, encoding=chosen_enc, compression='infer',
                         engine=_CSV_ENGINE, usecols=needed)
    else:
        df = pd.read_csv(fpath, encoding=chosen_enc, compression='infer',
                         engine=_CSV_ENGINE)
    return df, cols
