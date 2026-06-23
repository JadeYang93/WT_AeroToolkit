# -*- coding: utf-8 -*-
"""Excel 多 sheet 导出。"""
import os
import pandas as pd


def export_excel(out_dir, df_daily, df_weekly, df_monthly,
                 ti_bin_sheets=None, df_monthly_ti=None):
    """导出多sheet Excel：sheet名 = {日/周/月}均{指标}。

    Args:
        ti_bin_sheets: dict {sheet标签: DataFrame}，风速 bin P90 TI 分布（可选）
        df_monthly_ti: 月度湍流预计算文件数据 DataFrame（可选）
    Returns:
        输出文件路径
    """
    path = os.path.join(out_dir, '风场统计数据.xlsx')
    metric_names = {'wind_speed': '风速', 'ti': '湍流度', 'density': '密度'}

    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for metric_col, cn_name in metric_names.items():
            for gran, df, x_col in [
                ('日', df_daily, 'date'),
                ('周', df_weekly, 'week_start'),
                ('月', df_monthly, 'month'),
            ]:
                if df is None or df.empty or metric_col not in df.columns:
                    continue
                df_out = df[['turbine', x_col, metric_col, 'day_count']].copy()
                df_out.columns = ['机组号', '日期' if gran == '日' else
                                  ('周起始' if gran == '周' else '月份'),
                                  f'{gran}平均{cn_name}', '数据天数']
                # 日期格式化
                date_col = df_out.columns[1]
                if gran == '月':
                    df_out[date_col] = df_out[date_col].astype(str)
                else:
                    df_out[date_col] = pd.to_datetime(df_out[date_col]).dt.strftime('%Y-%m-%d')
                sheet_name = f'{gran}均{cn_name}'[:31]  # Excel限制31字符
                df_out.to_excel(writer, sheet_name=sheet_name, index=False)
        # 风速 bin P90 TI 分布（全期 + 月度 + 周度）
        if ti_bin_sheets:
            for label, bdf in ti_bin_sheets.items():
                if bdf is None or bdf.empty:
                    continue
                bin_out = bdf.copy()
                bin_out.index.name = '风速bin中心(m/s)'
                bin_out.columns = [f'#{c}号机组' for c in bin_out.columns]
                sheet_name = f'P90TI-{label}'[:31]  # Excel限制31字符
                bin_out.to_excel(writer, sheet_name=sheet_name)
        # 月度湍流预计算数据
        if df_monthly_ti is not None and not df_monthly_ti.empty:
            mti_out = df_monthly_ti.copy()
            mti_out['turbine'] = mti_out['turbine'].astype(int)
            mti_out['month'] = mti_out['month'].astype(str)
            mti_out['bin_center'] = mti_out['bin_center'].astype(int)
            mti_out.columns = ['机组号', '月份', '风速bin(m/s)', '湍流度', '数据量']
            mti_out.to_excel(writer, sheet_name='月度bin湍流度', index=False)
    return path


# ================================================================
# 跨风场对比
# ================================================================
FARM_METRIC_CN = {
    'wind_speed': '风速',
    'density': '密度',
}


def export_compare_excel(out_dir, farm_monthly, metrics):
    """导出风场对比汇总 Excel。

    每个 metric 一个 sheet：行=月份，列=风场名，值=该风场该月均值（跨机组简单平均）。

    Args:
        out_dir: 输出目录
        farm_monthly: dict[farm_name, DataFrame]，DataFrame index=月份(Period)，
                      columns 包含 metrics 对应列
        metrics: list ∈ {'wind_speed', 'density'}
    Returns:
        输出文件路径
    """
    path = os.path.join(out_dir, '风场对比汇总.xlsx')
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for metric in metrics:
            # 构造 pivot:每风场一列，行=月份并集
            data = {}
            for name in sorted(farm_monthly.keys()):
                df = farm_monthly[name]
                if metric in df.columns:
                    s = df[metric].dropna()
                    if not s.empty:
                        data[name] = s
            if not data:
                continue
            pivot = pd.DataFrame(data)
            # 按月份排序（Period 可比），转字符串便于 Excel 展示
            pivot = pivot.sort_index()
            pivot.index = pivot.index.astype(str)
            pivot.index.name = '月份'
            cn_name = FARM_METRIC_CN.get(metric, metric)
            sheet_name = f'月均{cn_name}对比'[:31]   # Excel sheet 限 31 字符
            pivot.to_excel(writer, sheet_name=sheet_name)
    return path
