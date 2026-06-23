# -*- coding: utf-8 -*-
"""P90 湍流度-风速bin 分布、有效窗口数统计。"""
import pandas as pd

from config import MIN_BIN_COUNT


def compute_ti_p90_by_bin(ti_bin_data, min_count=None, period=None):
    """按风速 bin 计算各机组的 P90 湍流度。

    Args:
        ti_bin_data: list[dict]，每项含 {'turbine', 'date', 'mean_speed', 'ti'}
        min_count: 每个 bin 至少多少个窗口，None=用默认 MIN_BIN_COUNT
        period: None=全期一个结果; 'month'=按月分组; 'week'=按周分组
    Returns:
        period=None 时: pd.DataFrame (index=bin_center, columns=turbine)
        period='month'/'week' 时: dict {period_label(str): pd.DataFrame}
    """
    if not ti_bin_data:
        return pd.DataFrame() if period is None else {}
    mc = min_count if min_count is not None else MIN_BIN_COUNT
    df = pd.DataFrame(ti_bin_data)
    df = df.dropna(subset=['ti', 'mean_speed'])
    df = df[(df['mean_speed'] > 0) & (df['ti'] > 0)]
    if df.empty:
        return pd.DataFrame() if period is None else {}
    # bin 中心取整数（9.5~10.5 → 10）
    df['bin_center'] = df['mean_speed'].round().astype(int)

    # 时间分组标签
    if period == 'month':
        df['period_key'] = df['date'].dt.to_period('M').astype(str)
    elif period == 'week':
        week_start = df['date'] - pd.to_timedelta(df['date'].dt.weekday, unit='D')
        df['period_key'] = week_start.dt.strftime('%Y-%m-%d')
    else:
        df['period_key'] = 'all'

    result = {}
    for pkey, pgrp in df.groupby('period_key'):
        records = []
        for (turbine, bin_center), grp in pgrp.groupby(['turbine', 'bin_center']):
            if len(grp) < mc:
                continue
            records.append({
                'turbine': turbine,
                'bin_center': bin_center,
                'p90': float(grp['ti'].quantile(0.9)),
            })
        if records:
            rdf = pd.DataFrame(records)
            result[pkey] = rdf.pivot(index='bin_center', columns='turbine', values='p90')

    if period is None:
        return result.get('all', pd.DataFrame())
    return result


def compute_ti_bin_count(ti_bin_data, period=None):
    """统计每个 (风速bin, 机组) [× 时段] 的有效窗口样本数。

    与 compute_ti_p90_by_bin 用同样的分组规则，但**不应用 min_count 过滤**，
    以便完整展示各 bin 的有效数据量（数据量过少的 bin 不会出现在 P90 图中，
    但在 count 图中会显示为低柱，提示数据稀疏）。
    Args:
        ti_bin_data: list[dict]，每项含 {'turbine', 'date', 'mean_speed', 'ti'}
        period: None=全期一个结果; 'month'=按月; 'week'=按周
    Returns:
        period=None: pd.DataFrame (index=bin_center, columns=turbine, values=count)
        period='month'/'week': dict[period_label(str), pd.DataFrame]
    """
    if not ti_bin_data:
        return pd.DataFrame() if period is None else {}
    df = pd.DataFrame(ti_bin_data)
    df = df.dropna(subset=['ti', 'mean_speed'])
    df = df[(df['mean_speed'] > 0) & (df['ti'] > 0)]
    if df.empty:
        return pd.DataFrame() if period is None else {}
    df['bin_center'] = df['mean_speed'].round().astype(int)

    if period == 'month':
        df['period_key'] = df['date'].dt.to_period('M').astype(str)
    elif period == 'week':
        week_start = df['date'] - pd.to_timedelta(df['date'].dt.weekday, unit='D')
        df['period_key'] = week_start.dt.strftime('%Y-%m-%d')
    else:
        df['period_key'] = 'all'

    result = {}
    for pkey, pgrp in df.groupby('period_key'):
        cnt = (pgrp.groupby(['turbine', 'bin_center']).size()
               .reset_index(name='count'))
        if cnt.empty:
            continue
        result[pkey] = cnt.pivot(index='bin_center',
                                 columns='turbine', values='count')
    if period is None:
        return result.get('all', pd.DataFrame())
    return result


def compute_ti_p90_by_turbine_month(ti_bin_data, min_count=None):
    """按 (机组, 月份, 风速bin) 计算 P90 TI（基于秒级数据滑窗得到的窗口级 TI）。

    与 compute_ti_p90_by_bin(period='month') 返回的结构互补：
    那个返回 {月份: DataFrame(bin × 机组)}，本函数返回 {机组: DataFrame(bin × 月份)}，
    便于绘制「每机组一张图、X=风速bin、每月份一条线」的 P90 分布曲线。
    Args:
        ti_bin_data: list[dict]，每项含 {'turbine', 'date', 'mean_speed', 'ti'}
        min_count: 每个 (机组,月份,bin) 至少多少个窗口，None=MIN_BIN_COUNT
    Returns:
        dict: {turbine(int): DataFrame}，DataFrame.index=bin_center(int),
              columns=month(str, 'YYYY-MM'), values=P90 TI
    """
    if not ti_bin_data:
        return {}
    mc = min_count if min_count is not None else MIN_BIN_COUNT
    df = pd.DataFrame(ti_bin_data)
    df = df.dropna(subset=['ti', 'mean_speed'])
    df = df[(df['mean_speed'] > 0) & (df['ti'] > 0)]
    if df.empty:
        return {}
    df['bin_center'] = df['mean_speed'].round().astype(int)
    df['month_key'] = df['date'].dt.to_period('M').astype(str)

    result = {}
    for turbine, tgrp in df.groupby('turbine'):
        records = []
        for (mkey, bin_center), grp in tgrp.groupby(['month_key', 'bin_center']):
            if len(grp) < mc:
                continue
            records.append({
                'month_key': mkey,
                'bin_center': bin_center,
                'p90': float(grp['ti'].quantile(0.9)),
            })
        if not records:
            continue
        rdf = pd.DataFrame(records)
        result[turbine] = rdf.pivot(index='bin_center',
                                    columns='month_key', values='p90')
    return result


def compute_ti_count_by_turbine_month(ti_bin_data):
    """按 (机组, 月份, 风速bin) 统计有效窗口数。

    与 compute_ti_p90_by_turbine_month 用同样的过滤与分组规则，但**不应用
    min_count 过滤**，以便完整展示各 bin 的有效数据量（数据量过少的 bin 不会
    出现在 P90 曲线中，但在 count 柱状图中会显示为低柱，提示数据稀疏）。
    Args:
        ti_bin_data: list[dict]，每项含 {'turbine', 'date', 'mean_speed', 'ti'}
    Returns:
        dict: {turbine(int): DataFrame}，DataFrame.index=bin_center(int),
              columns=month(str, 'YYYY-MM'), values=count(int)
    """
    if not ti_bin_data:
        return {}
    df = pd.DataFrame(ti_bin_data)
    df = df.dropna(subset=['ti', 'mean_speed'])
    df = df[(df['mean_speed'] > 0) & (df['ti'] > 0)]
    if df.empty:
        return {}
    df['bin_center'] = df['mean_speed'].round().astype(int)
    df['month_key'] = df['date'].dt.to_period('M').astype(str)

    result = {}
    for turbine, tgrp in df.groupby('turbine'):
        cnt = (tgrp.groupby(['month_key', 'bin_center']).size()
               .reset_index(name='count'))
        if cnt.empty:
            continue
        result[turbine] = cnt.pivot(index='bin_center',
                                    columns='month_key', values='count')
    return result
