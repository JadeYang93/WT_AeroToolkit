# -*- coding: utf-8 -*-
"""主流程编排：run() 与 _run_monthly_ti()。

依赖 io_utils / processing / ti_bin / plotting / export 全部下游模块，
是整个数据流水线的协调层。被 main.py 调用。
"""
import os
import pandas as pd

from io_utils import (
    scan_data_files, scan_monthly_ti_files, read_monthly_ti_file,
)
from processing import (
    compute_daily_stats, aggregate_weekly, aggregate_monthly,
)
from ti_bin import (
    compute_ti_p90_by_bin, compute_ti_bin_count,
    compute_ti_p90_by_turbine_month, compute_ti_count_by_turbine_month,
)
from plotting import (
    METRICS_INFO,
    plot_timeseries_curve, plot_monthly_curve,
    plot_ti_bin_curve, plot_ti_p90_per_turbine,
    plot_monthly_ti_bin_timeseries, plot_monthly_ti_per_turbine_timeseries,
)
from export import export_excel


# ================================================================
# 主流程入口
# ================================================================
def _run_monthly_ti(data_dir, out_dir, highlight_turbines=None,
                    include_turbines=None, start_date=None, end_date=None,
                    progress_callback=None, log=None,
                    turbine_blades=None, blade_styles=None):
    """月度湍流预计算文件处理路径（与秒级原始数据完全隔离）。

    流程：
      扫描月度湍流文件 → 读取 → 按机组/日期过滤 → 每个 bin 出一张月度时间序列图 → Excel
    Returns:
        dict: {'plots': int, 'excel': str|None, 'error': str|None}
    """
    if log is None:
        def log(p, m):
            if progress_callback:
                progress_callback(p, m)

    if not os.path.isdir(data_dir):
        return {'plots': 0, 'excel': None, 'error': f'输入目录不存在: {data_dir}'}
    os.makedirs(out_dir, exist_ok=True)

    log(0, f'开始扫描 {data_dir}（月度湍流表模式）')
    monthly_ti_files = scan_monthly_ti_files(data_dir)
    if not monthly_ti_files:
        return {'plots': 0, 'excel': None, 'error': '未找到月度湍流文件（文件名需含「月度湍流」）'}

    filter_msgs = []
    if include_turbines is not None:
        filter_msgs.append(f"机组={sorted(include_turbines)}")
    if start_date is not None or end_date is not None:
        sd = start_date.strftime('%Y-%m-%d') if start_date is not None else '不限'
        ed = end_date.strftime('%Y-%m-%d') if end_date is not None else '不限'
        filter_msgs.append(f"日期={sd}~{ed}")
    if filter_msgs:
        log(None, '  过滤条件: ' + ', '.join(filter_msgs))

    log(5, f'读取 {len(monthly_ti_files)} 个月度湍流文件...')
    ti_dfs = []
    for i, fname in enumerate(monthly_ti_files):
        try:
            df_mt = read_monthly_ti_file(os.path.join(data_dir, fname))
            if not df_mt.empty:
                ti_dfs.append(df_mt)
                log((i + 1) * 50 // len(monthly_ti_files),
                    f'  读取 {fname}: {len(df_mt)} 条记录')
        except Exception as e:
            log(None, f'  [警告] {fname}: {e}')

    if not ti_dfs:
        return {'plots': 0, 'excel': None, 'error': '月度湍流文件全部读取失败'}

    df_ti = pd.concat(ti_dfs, ignore_index=True)

    # 过滤机组
    if include_turbines is not None:
        df_ti = df_ti[df_ti['turbine'].isin(include_turbines)]
    # 过滤日期（month 为 Period，用 start_time 比较）
    if start_date is not None:
        df_ti = df_ti[df_ti['month'].dt.start_time >= start_date]
    if end_date is not None:
        df_ti = df_ti[df_ti['month'].dt.start_time <= end_date]

    if df_ti.empty:
        return {'plots': 0, 'excel': None, 'error': '过滤后无月度湍流数据'}

    log(60, '生成图表...')
    # 视图1：每个风速 bin 一张图，横轴月份，每机组一条线
    plot_count = plot_monthly_ti_bin_timeseries(df_ti, out_dir, highlight_turbines,
                                               turbine_blades=turbine_blades,
                                               blade_styles=blade_styles)
    for bc in sorted(df_ti['bin_center'].unique()):
        log(None, f'  已生成 月度{int(bc)}ms湍流度曲线.png')
    # 视图2：每个机组一张图，横轴月份，每风速 bin 一条线
    plot_count += plot_monthly_ti_per_turbine_timeseries(df_ti, out_dir,
                                                        turbine_blades=turbine_blades)
    for t in sorted(df_ti['turbine'].unique()):
        log(None, f'  已生成 机组{int(t)}号月度湍流度曲线.png')

    log(90, '导出 Excel...')
    excel_path = export_excel(out_dir, pd.DataFrame(), pd.DataFrame(),
                              pd.DataFrame(), ti_bin_sheets=None,
                              df_monthly_ti=df_ti)

    log(100, f'完成！生成 {plot_count} 张图 + Excel: {excel_path}')
    return {'plots': plot_count, 'excel': excel_path, 'error': None}


def run(data_dir, out_dir, metrics, granularities,
        highlight_turbines=None, include_turbines=None,
        ti_params=None, cache_path=None,
        start_date=None, end_date=None,
        data_type='raw', progress_callback=None,
        turbine_blades=None, blade_styles=None):
    """工具主入口。

    Args:
        data_dir: 输入文件夹
        out_dir: 输出文件夹
        metrics: list, 元素 ∈ {'wind_speed', 'ti', 'density'}
        granularities: list, 元素 ∈ {'daily', 'weekly', 'monthly'}
        highlight_turbines: list of int 或 None（不高亮）
        include_turbines: list of int 或 None（None=全部机组参与）
        ti_params: dict 或 None；可含 window_min/step_min/valid_ratio
        cache_path: 缓存文件路径或 None
        start_date/end_date: pd.Timestamp 或 None；按文件名日期过滤（含端点）
        data_type: 'raw'(默认,秒级原始数据) 或 'monthly_ti'(月度湍流预计算表)
        progress_callback: fn(percent:int|None, msg:str)
        turbine_blades: dict {机组号: 叶型名}，可选；用于绘图线型/图例区分
        blade_styles: dict {叶型名: 线型名称}，可选；与 turbine_blades 配合
    Returns:
        dict: {'plots': int, 'excel': str|None, 'error': str|None}
    """
    def log(p, m):
        if progress_callback:
            progress_callback(p, m)

    # 月度湍流表模式：走独立处理路径，不与秒级数据混合
    if data_type == 'monthly_ti':
        return _run_monthly_ti(data_dir, out_dir,
                               highlight_turbines=highlight_turbines,
                               include_turbines=include_turbines,
                               start_date=start_date, end_date=end_date,
                               progress_callback=progress_callback, log=log,
                               turbine_blades=turbine_blades,
                               blade_styles=blade_styles)

    if not os.path.isdir(data_dir):
        return {'plots': 0, 'excel': None, 'error': f'输入目录不存在: {data_dir}'}
    os.makedirs(out_dir, exist_ok=True)

    log(0, f'开始扫描 {data_dir}（秒级原始数据模式）')
    files = scan_data_files(data_dir)
    if not files:
        return {'plots': 0, 'excel': None, 'error': '输入目录无有效数据文件'}

    # 显示日期/机组过滤信息
    filter_msgs = []
    if include_turbines is not None:
        filter_msgs.append(f"机组={sorted(include_turbines)}")
    if start_date is not None or end_date is not None:
        sd = start_date.strftime('%Y-%m-%d') if start_date is not None else '不限'
        ed = end_date.strftime('%Y-%m-%d') if end_date is not None else '不限'
        filter_msgs.append(f"日期={sd}~{ed}")
    if filter_msgs:
        log(None, '  过滤条件: ' + ', '.join(filter_msgs))

    log(5, f'找到 {len(files)} 个文件，开始日级统计...')
    df_daily, ti_bin_data = compute_daily_stats(
        data_dir, progress_callback, include_turbines,
        ti_params=ti_params, cache_path=cache_path,
        start_date=start_date, end_date=end_date
    )
    if df_daily.empty:
        return {'plots': 0, 'excel': None, 'error': '所有文件均无法处理'}

    log(55, '聚合周/月数据...')
    df_weekly = aggregate_weekly(df_daily) if 'weekly' in granularities else pd.DataFrame()
    df_monthly = aggregate_monthly(df_daily) if 'monthly' in granularities else pd.DataFrame()

    # 风速 bin P90 湍流度（全期 + 月度 + 周度）
    ti_bin_all = compute_ti_p90_by_bin(ti_bin_data) if 'ti' in metrics else pd.DataFrame()
    ti_bin_by_month = (compute_ti_p90_by_bin(ti_bin_data, period='month')
                       if 'ti' in metrics and 'monthly' in granularities else {})
    ti_bin_by_week = (compute_ti_p90_by_bin(ti_bin_data, period='week')
                      if 'ti' in metrics and 'weekly' in granularities else {})

    # 每个 bin × 机组 的有效窗口数（与 P90 同分组，但不过滤 min_count）
    ti_count_all = compute_ti_bin_count(ti_bin_data) if 'ti' in metrics else pd.DataFrame()
    ti_count_by_month = (compute_ti_bin_count(ti_bin_data, period='month')
                         if 'ti' in metrics and 'monthly' in granularities else {})
    ti_count_by_week = (compute_ti_bin_count(ti_bin_data, period='week')
                        if 'ti' in metrics and 'weekly' in granularities else {})

    log(70, '生成图表...')
    plot_count = 0
    for metric in metrics:
        if metric not in df_daily.columns:
            log(None, f'  [提示] 输入数据无 {metric} 列，跳过该指标')
            continue
        cn_name, unit = METRICS_INFO[metric]

        if 'daily' in granularities:
            ok = plot_timeseries_curve(
                df_daily, 'date', metric,
                f'各机组日平均{cn_name}变化曲线', '日期',
                f'日平均{cn_name} ({unit})',
                f'日平均{cn_name}曲线.png', out_dir, highlight_turbines,
                show_labels=False,
                turbine_blades=turbine_blades, blade_styles=blade_styles
            )
            if ok:
                plot_count += 1
                log(None, f'  已生成 日平均{cn_name}曲线.png')

        if 'weekly' in granularities and not df_weekly.empty and metric in df_weekly.columns:
            ok = plot_timeseries_curve(
                df_weekly, 'week_start', metric,
                f'各机组周平均{cn_name}变化曲线', '周起始日期',
                f'周平均{cn_name} ({unit})',
                f'周平均{cn_name}曲线.png', out_dir, highlight_turbines,
                is_weekly=True,
                turbine_blades=turbine_blades, blade_styles=blade_styles
            )
            if ok:
                plot_count += 1
                log(None, f'  已生成 周平均{cn_name}曲线.png')

        if 'monthly' in granularities and not df_monthly.empty and metric in df_monthly.columns:
            ok = plot_monthly_curve(df_monthly, metric, out_dir, highlight_turbines,
                                   turbine_blades=turbine_blades,
                                   blade_styles=blade_styles)
            if ok:
                plot_count += 1
                log(None, f'  已生成 月平均{cn_name}曲线.png')

        # 风速 bin P90 湍流度分布曲线（仅湍流度指标）
        if metric == 'ti':
            # 全期
            if not ti_bin_all.empty:
                ok = plot_ti_bin_curve(ti_bin_all, out_dir, highlight_turbines,
                                       count_df=ti_count_all,
                                       turbine_blades=turbine_blades,
                                       blade_styles=blade_styles)
                if ok:
                    plot_count += 1
                    log(None, '  已生成 湍流度-风速分布P90曲线.png')
            # 月度
            for mkey, bdf in sorted(ti_bin_by_month.items()):
                ok = plot_ti_bin_curve(bdf, out_dir, highlight_turbines,
                                       title_suffix=f' ({mkey})', fname_suffix=f'_{mkey}',
                                       count_df=ti_count_by_month.get(mkey),
                                       turbine_blades=turbine_blades,
                                       blade_styles=blade_styles)
                if ok:
                    plot_count += 1
                    log(None, f'  已生成 湍流度-风速分布P90曲线_{mkey}.png')
            # 周度
            for wkey, bdf in sorted(ti_bin_by_week.items()):
                ok = plot_ti_bin_curve(bdf, out_dir, highlight_turbines,
                                       title_suffix=f' (周起始 {wkey})',
                                       fname_suffix=f'_周{wkey}',
                                       count_df=ti_count_by_week.get(wkey),
                                       turbine_blades=turbine_blades,
                                       blade_styles=blade_styles)
                if ok:
                    plot_count += 1
                    log(None, f'  已生成 湍流度-风速分布P90曲线_周{wkey}.png')

        # 每机组一张：X=风速bin, 每月份一条 P90 TI 曲线（基于秒级数据，需勾选 ti + monthly）
        if metric == 'ti' and 'monthly' in granularities:
            p90_by_turb = compute_ti_p90_by_turbine_month(ti_bin_data)
            count_by_turb = compute_ti_count_by_turbine_month(ti_bin_data)
            n_pt = plot_ti_p90_per_turbine(p90_by_turb, out_dir, highlight_turbines,
                                          turbine_blades=turbine_blades,
                                          count_by_turbine=count_by_turb)
            plot_count += n_pt
            for t in sorted(p90_by_turb.keys()):
                log(None, f'  已生成 机组{int(t)}号湍流度-风速分布P90曲线.png')

    log(90, '导出 Excel...')
    # 收集所有 bin sheet 数据 {sheet标签: DataFrame}
    ti_bin_sheets = {}
    if 'ti' in metrics:
        if not ti_bin_all.empty:
            ti_bin_sheets['全期'] = ti_bin_all
        for mkey, bdf in sorted(ti_bin_by_month.items()):
            ti_bin_sheets[f'月度_{mkey}'] = bdf
        for wkey, bdf in sorted(ti_bin_by_week.items()):
            ti_bin_sheets[f'周度_{wkey}'] = bdf

    excel_path = export_excel(out_dir, df_daily, df_weekly, df_monthly,
                              ti_bin_sheets, None)

    log(100, f'完成！生成 {plot_count} 张图 + Excel: {excel_path}')
    return {'plots': plot_count, 'excel': excel_path, 'error': None}
