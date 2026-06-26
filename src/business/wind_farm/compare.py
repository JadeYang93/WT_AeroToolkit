# -*- coding: utf-8 -*-
"""跨风场月均对比业务逻辑（wind_farm_compare 模块）。

数据来源：每个风场子目录下的 风场统计数据.xlsx（由 wind_farm 模块生成）。
聚合策略：风场整体 = 该风场所有机组的月均再求简单平均（跨机组）。
"""
import os
import pandas as pd

from core.io_utils import scan_farm_dirs, EXCEL_FILENAME
from core.plotting import plot_farm_compare
from core.export import export_compare_excel


# 指标 → 月均 sheet 候选名（兼容 export.py 默认输出 + 用户可能手改成「月平均」前缀）
SHEET_CANDIDATES = {
    'wind_speed': ['月均风速', '月平均风速'],
    'density': ['月均密度', '月平均密度'],
}

# 指标 → 月平均列名（export.py: f'{gran}平均{cn_name}' → '月平均风速' / '月平均密度'）
METRIC_COLUMN = {
    'wind_speed': '月平均风速',
    'density': '月平均密度',
}


def _find_sheet(xf, metric):
    """从 ExcelFile 中按候选名找第一个存在的 sheet。Returns: sheet 名 or None。"""
    for name in SHEET_CANDIDATES[metric]:
        if name in xf.sheet_names:
            return name
    return None


def read_farm_monthly(excel_path, metrics):
    """读取单个风场的月均 sheet，返回按月份聚合的风场级月均。

    Args:
        excel_path: 风场统计数据.xlsx 路径
        metrics: list, 元素 ∈ {'wind_speed', 'density'}
    Returns:
        (df, missing) 或 (None, [])
          df: pd.DataFrame, index=月份(pd.Period), columns=[metric_col, ...],
              values=风场级月均(跨机组简单平均)
          missing: list[str], 缺失/为空的 sheet 描述（用于日志提示用户去 wind_farm 重跑）
        返回 (None, []) 表示 Excel 完全无法读取。
    """
    try:
        with pd.ExcelFile(excel_path) as xf:
            result_cols = {}
            missing_sheets = []
            for metric in metrics:
                sheet = _find_sheet(xf, metric)
                if sheet is None:
                    missing_sheets.append(SHEET_CANDIDATES[metric][0])
                    continue
                df = xf.parse(sheet)
                # 找到 月平均 列；列名严格匹配 export.py 的输出
                col = METRIC_COLUMN[metric]
                if col not in df.columns:
                    missing_sheets.append(f'{sheet}/{col}')
                    continue
                # 月份列：export.py 写出时是 'YYYY-MM' 字符串，转 Period
                month_col = '月份' if '月份' in df.columns else None
                if month_col is None:
                    missing_sheets.append(f'{sheet}/月份列缺失')
                    continue
                # Period 转换：失败的行丢掉
                ts = pd.to_datetime(df[month_col], errors='coerce')
                periods = ts.dt.to_period('M')
                valid = ~periods.isna() & df[col].notna()
                if not valid.any():
                    missing_sheets.append(f'{sheet}/无有效行')
                    continue
                # 跨机组简单平均：groupby 月份
                monthly_mean = (
                    df.loc[valid].assign(_m=periods[valid].values)
                    .groupby('_m')[col].mean()
                )
                result_cols[metric] = monthly_mean
            if not result_cols:
                return None, missing_sheets
            # 合并到一张表（按月份 outer join，保留各自的有效月份）
            out = pd.DataFrame(result_cols)
            out.index.name = 'month'
            return out, missing_sheets
    except Exception:
        return None, []


def run_compare(input_dir, out_dir, metrics,
                start_date=None, end_date=None,
                progress_callback=None):
    """跨风场月均对比主流程。

    Args:
        input_dir: 输入根目录，每个子目录 = 一个风场
        out_dir: 输出目录
        metrics: list ∈ {'wind_speed', 'density'}
        start_date/end_date: pd.Period('M') 或 None；按月份过滤（含端点）
        progress_callback: fn(percent:int|None, msg:str)
    Returns:
        dict: {'plots': int, 'excel': str|None, 'error': str|None}
    """
    def log(p, m):
        if progress_callback:
            progress_callback(p, m)

    if not os.path.isdir(input_dir):
        return {'plots': 0, 'excel': None, 'error': f'输入目录不存在: {input_dir}'}
    os.makedirs(out_dir, exist_ok=True)

    # 1. 扫描所有风场子目录
    log(0, f'开始扫描 {input_dir}')
    farms = scan_farm_dirs(input_dir)
    valid_farms = [f for f in farms if f['has_excel']]
    if farms and not valid_farms:
        msg_dirs = '、'.join(f['name'] for f in farms[:5])
        return {
            'plots': 0, 'excel': None,
            'error': f'找到 {len(farms)} 个子目录但均缺 {EXCEL_FILENAME}：{msg_dirs}'
                     f'{"..." if len(farms) > 5 else ""}，请先在 wind_farm 模块跑一次生成',
        }
    if not valid_farms:
        return {
            'plots': 0, 'excel': None,
            'error': f'未找到含 {EXCEL_FILENAME} 的子目录，请先在 wind_farm 模块跑一次',
        }

    # 2. 警告缺失 Excel 的子目录
    for f in farms:
        if not f['has_excel']:
            log(None, f'  [警告] 风场 {f["name"]} 缺 {EXCEL_FILENAME}，跳过')

    # 3. 读取每个风场的月均
    farm_monthly = {}
    n = len(valid_farms)
    for i, farm in enumerate(valid_farms):
        ret = read_farm_monthly(farm['excel_path'], metrics)
        if ret is None:
            log(None, f'  [警告] 风场 {farm["name"]} Excel 读取失败，跳过')
            continue
        df, missing = ret
        if df is None or df.empty:
            # 月均 sheet 全部缺失或为空 → 最常见原因是 wind_farm 跑时没勾「月」粒度
            log(None, f'  [警告] 风场 {farm["name"]} 月均 sheet 缺失或为空，跳过')
            if missing:
                log(None, f'           缺：{", ".join(missing)}')
            log(None, f'           请去「风场数据统计」模块勾选「月」粒度重跑该风场')
            continue
        farm_monthly[farm['name']] = df
        if missing:
            # 部分指标 sheet 缺失（例如只生成了月均风速，没生成月均密度）
            log(None, f'  [提示] 风场 {farm["name"]} 部分指标缺失：{", ".join(missing)}')
        log((i + 1) * 50 // n, f'  [{i + 1}/{n}] {farm["name"]}：{len(df)} 个月')

    if not farm_monthly:
        return {
            'plots': 0, 'excel': None,
            'error': '所有风场的月均 sheet 均缺失或为空。'
                     '请确认各风场的 风场统计数据.xlsx 是在「风场数据统计」模块勾选「月」粒度时生成的',
        }

    # 4. 日期过滤（按 Period 比较）
    if start_date is not None or end_date is not None:
        sd = pd.Period(start_date, freq='M') if start_date is not None else None
        ed = pd.Period(end_date, freq='M') if end_date is not None else None
        for name, df in farm_monthly.items():
            mask = pd.Series(True, index=df.index)
            if sd is not None:
                mask &= df.index >= sd
            if ed is not None:
                mask &= df.index <= ed
            farm_monthly[name] = df[mask]

    # 5. 绘图：每个 metric 一张图
    log(60, '--- 生成对比图 ---')
    plots = 0
    for metric in metrics:
        if plot_farm_compare(farm_monthly, metric, out_dir):
            plots += 1
            log(60 + plots * 10, f'  ✓ {METRIC_COLUMN[metric]} 对比图')

    # 6. 导出 Excel
    log(85, '--- 导出汇总 Excel ---')
    excel_path = export_compare_excel(out_dir, farm_monthly, metrics)
    log(100, f'  ✓ {os.path.basename(excel_path)}')

    return {'plots': plots, 'excel': excel_path, 'error': None}
