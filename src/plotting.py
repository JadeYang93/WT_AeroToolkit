# -*- coding: utf-8 -*-
"""绘图：日/周/月时间序列、P90 风速bin分布、月度湍流曲线。

本模块在导入时配置 matplotlib 后端与中文字体，须在 pyplot 被其他模块使用前
完成（pipeline/main 通过本模块间接初始化）。
"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config import (
    PALETTE, DPI,
    LINESTYLE_OPTIONS, DEFAULT_LINESTYLE, DEFAULT_LINEWIDTH, DEFAULT_ALPHA,
    UNSPECIFIED_BLADE_KEY,
)

matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
matplotlib.rcParams['axes.unicode_minus'] = False


# ================================================================
# 叶型 → 线型 辅助
# ================================================================
def resolve_turbine_linestyle(turbine, turbine_blades, blade_styles):
    """根据机组号解析其在图中应使用的线型 + 宽度 + 透明度。

    Args:
        turbine: 机组号(int)
        turbine_blades: dict {机组号: 叶型名}，可为 None 或缺键
        blade_styles: dict {叶型名: (线型名称, 宽度, 透明度)} 或兼容老格式：
                      - (线型名称, 宽度)         二元组（透明度默认 1.0）
                      - 线型名称字符串            （宽度/透明度都用默认）
    Returns:
        dict {'ls': matplotlib linestyle, 'lw': 宽度(float), 'alpha': 透明度(float)}
    """
    if not turbine_blades or not blade_styles:
        return {'ls': DEFAULT_LINESTYLE, 'lw': DEFAULT_LINEWIDTH, 'alpha': DEFAULT_ALPHA}
    blade = turbine_blades.get(turbine, '')
    key = blade if blade else UNSPECIFIED_BLADE_KEY
    spec = blade_styles.get(key)
    if spec is None:
        return {'ls': DEFAULT_LINESTYLE, 'lw': DEFAULT_LINEWIDTH, 'alpha': DEFAULT_ALPHA}
    # 新格式 v2: spec = (ls_name, width, alpha)
    if isinstance(spec, (list, tuple)) and len(spec) == 3:
        ls_name, width, alpha = spec
        ls = LINESTYLE_OPTIONS.get(ls_name, DEFAULT_LINESTYLE)
        try:
            lw = float(width)
        except (TypeError, ValueError):
            lw = DEFAULT_LINEWIDTH
        try:
            al = float(alpha)
        except (TypeError, ValueError):
            al = DEFAULT_ALPHA
        return {'ls': ls, 'lw': lw, 'alpha': al}
    # 新格式 v1: spec = (ls_name, width)
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        ls_name, width = spec
        ls = LINESTYLE_OPTIONS.get(ls_name, DEFAULT_LINESTYLE)
        try:
            lw = float(width)
        except (TypeError, ValueError):
            lw = DEFAULT_LINEWIDTH
        return {'ls': ls, 'lw': lw, 'alpha': DEFAULT_ALPHA}
    # 兼容老格式 spec = 线型名称字符串
    return {'ls': LINESTYLE_OPTIONS.get(spec, DEFAULT_LINESTYLE),
            'lw': DEFAULT_LINEWIDTH,
            'alpha': DEFAULT_ALPHA}


def format_turbine_label(turbine, turbine_blades):
    """生成图例标签:'#10号机组' 或 '#10号机组 (叶型A)'。

    未填叶型时仅显示机组号。
    """
    base = f'#{turbine}号机组'
    if not turbine_blades:
        return base
    blade = turbine_blades.get(turbine, '')
    if not blade:
        return base
    return f'{base} ({blade})'


# ================================================================
# 绘图
# ================================================================
METRICS_INFO = {
    'wind_speed': ('风速', 'm/s'),
    'ti': ('湍流度', 'TI'),
    'density': ('空气密度', 'kg/m3'),
}


def _add_summary_table(ax, rows, col_labels, max_rows_per_block=12, max_blocks=3):
    """在 ax 右上角加汇总表格。

    rows: [[c1, c2], ...] 行数据
    col_labels: [列名1, 列名2]
    深钢蓝表头 + 白字 + 斑马纹。

    多列布局：当行数 > ``max_rows_per_block`` 时，自动横向切到 ``max_blocks`` 块
    （每块 2 列），最多容纳 ``max_rows_per_block × max_blocks`` 行。多块时压缩列宽、
    缩字号，保证不挤占绘图区。
    """
    if not rows:
        return
    # 1. 切块：每块最多 max_rows_per_block 行，最多 max_blocks 块（超出的尾部丢弃）
    blocks = []
    for i in range(0, len(rows), max_rows_per_block):
        if len(blocks) >= max_blocks:
            break
        blocks.append(rows[i:i + max_rows_per_block])
    n_blocks = len(blocks)
    max_block_rows = max(len(b) for b in blocks)

    # 2. 合并成一张大表：行 = max_block_rows + 1（表头），列 = 2 * n_blocks
    n_cols = 2 * n_blocks
    n_total_rows = max_block_rows + 1
    cell_text = [[''] * n_cols for _ in range(n_total_rows)]
    for b in range(n_blocks):
        cell_text[0][b * 2] = col_labels[0]
        cell_text[0][b * 2 + 1] = col_labels[1]
    for b, block in enumerate(blocks):
        for r, row in enumerate(block):
            cell_text[r + 1][b * 2] = row[0]
            cell_text[r + 1][b * 2 + 1] = row[1]

    # 3. 列宽：单块保留原默认；多块整体压缩、每块内 label 列稍宽于 value 列
    if n_blocks == 1:
        col_widths = [0.22, 0.14]
    else:
        # 总宽随块数收缩（避免挤掉绘图区）；label : value ≈ 6 : 4
        total_w = 0.36 * n_blocks * 0.82
        per_block = total_w / n_blocks
        col_widths = []
        for _ in range(n_blocks):
            col_widths.append(per_block * 0.6)
            col_widths.append(per_block * 0.4)

    # 4. 建表（不用 colLabels，把表头塞进 cellText 第一行统一上色）
    tbl = ax.table(cellText=cell_text,
                   loc='upper right',
                   cellLoc='center',
                   colWidths=col_widths)
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10 if n_blocks == 1 else 9)
    tbl.scale(1, 1.5)

    # 5. 上色：表头深钢蓝、行斑马纹、空单元格淡化（无边框）
    for r in range(n_total_rows):
        for c in range(n_cols):
            cell = tbl[r, c]
            txt = cell_text[r][c]
            if r == 0:
                if txt:
                    cell.set_facecolor('#1e3a5f')
                    cell.set_text_props(color='white', weight='bold')
                else:
                    cell.set_facecolor('white')
                    cell.set_edgecolor('white')
            else:
                if not txt:
                    cell.set_facecolor('white')
                    cell.set_edgecolor('white')
                else:
                    cell.set_edgecolor('#cbd5e1')
                    if r % 2 == 0:
                        cell.set_facecolor('#f1f5f9')


def _clamp_ti_yaxis(ax, bin_df, percentile=95, buffer=0.15):
    """截断 P90 湍流度曲线的 Y 轴上限，避免极端值压扁其他机组细节。

    默认规则：取所有 bin 数据的 P95，再乘以 1.15 作为 Y 轴上限。
    若数据点很少（<10 个有效值）或最大值本来就不超过 P95*1.15，则不截断。
    截断后超出上限的点会自然被 matplotlib 裁剪，但曲线"撞顶"形态仍可见。
    """
    vals = bin_df.values.flatten()
    vals = vals[~np.isnan(vals)]
    if len(vals) < 10:
        return
    p = float(np.percentile(vals, percentile))
    if p <= 0:
        return
    y_top = p * (1.0 + buffer)
    cur_top = ax.get_ylim()[1]
    if cur_top <= y_top:
        return
    ax.set_ylim(top=y_top)


def _value_at_bin(series, target_bin=10.0):
    """从 series (index=bin_center) 取最接近 target_bin 的 bin 对应值。

    bin_center 通常按整数对齐（5, 6, ..., 10, 11），10.0 会精确命中；
    若数据缺 10.0（如 bin_width=0.5 时只有 9.5/10.5），退化为最近邻。
    """
    if series is None or series.empty:
        return None
    if target_bin in series.index:
        return series[target_bin]
    idx = np.abs(series.index - target_bin).argmin()
    return series.iloc[idx]


def _distinct_colors(n):
    """根据元素数量返回足够区分的颜色列表，避免机组数 > PALETTE 长度时颜色循环重复。

    策略：
      n ≤ 7   → 用 PALETTE 品牌色（与软件主题一致）
      7 < n ≤ 20 → tab20 高对比离散调色板（20 色任意两色差异明显）
      n > 20  → tab20 循环（极端情况兜底，配合线型可进一步区分）
    """
    if n <= len(PALETTE):
        return list(PALETTE[:n])
    cmap = plt.cm.tab20
    return [cmap(i % 20) for i in range(n)]


def plot_timeseries_curve(df, x_col, y_col, title, xlabel, ylabel,
                          out_fname, out_dir, highlight_turbines=None,
                          is_weekly=False, show_labels=True,
                          turbine_blades=None, blade_styles=None):
    """通用日/周时间序列曲线（x为日期类型）。

    Args:
        highlight_turbines: iterable of int 或 None（不高亮）
        show_labels: 是否在数据点旁标注数值（日曲线点多建议关掉）
        turbine_blades: dict {机组号: 叶型名}，用于线型/图例
        blade_styles: dict {叶型名: 线型名称}，与 turbine_blades 配合
    """
    df = df.dropna(subset=[y_col]).copy()
    if df.empty:
        return False
    fig, ax = plt.subplots(figsize=(18, 8) if is_weekly else (16, 8))
    turbines = sorted(df['turbine'].unique())
    colors = _distinct_colors(len(turbines))
    has_hl = bool(highlight_turbines)
    for i, t in enumerate(turbines):
        sub = df[df['turbine'] == t].sort_values(x_col)
        color = colors[i]
        is_hl = has_hl and t in highlight_turbines
        alpha = 1.0 if (is_hl or not has_hl) else 0.3
        style = resolve_turbine_linestyle(t, turbine_blades, blade_styles)
        ls = style['ls']
        # 高亮/无高亮场景放大基础线宽；有高亮但本条非高亮 → 压细
        hl_factor = 1.4 if (is_hl or not has_hl) else 0.5
        lw = style['lw'] * hl_factor
        lbl = format_turbine_label(t, turbine_blades) + (' [高亮]' if is_hl else '')
        ax.plot(sub[x_col], sub[y_col], linestyle=ls, marker='o',
                color=color, label=lbl,
                linewidth=lw, alpha=alpha, markersize=3)
        if show_labels and (is_hl or not has_hl):
            for _, row in sub.iterrows():
                ax.text(row[x_col], row[y_col] + 0.001, f'{row[y_col]:.4f}',
                        ha='center', va='bottom', fontsize=7)
    ax.set_xlabel(xlabel, fontsize=13)
    ax.set_ylabel(ylabel, fontsize=13)
    ax.set_title(title, fontsize=16, fontweight='bold')
    ax.legend(title='机组', fontsize=9, title_fontsize=10, loc='upper left', ncol=2)
    ax.grid(axis='both', alpha=0.3)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate(rotation=45 if is_weekly else 30)
    plt.tight_layout()
    out_path = os.path.join(out_dir, out_fname)
    fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    return True


def plot_monthly_curve(df_monthly, metric_col, out_dir, highlight_turbines=None,
                       turbine_blades=None, blade_styles=None):
    """月度曲线：x用数值索引保证月份按时间顺序。

    Args:
        highlight_turbines: iterable of int 或 None（不高亮）
        turbine_blades: dict {机组号: 叶型名}
        blade_styles: dict {叶型名: 线型名称}
    """
    cn_name, unit = METRICS_INFO[metric_col]
    df = df_monthly.dropna(subset=[metric_col]).copy()
    if df.empty:
        return False
    months_sorted = sorted(df['month'].unique())
    m2idx = {m: i for i, m in enumerate(months_sorted)}
    df['month_idx'] = df['month'].map(m2idx)

    fig, ax = plt.subplots(figsize=(16, 8))
    turbines = sorted(df['turbine'].unique())
    colors = _distinct_colors(len(turbines))
    has_hl = bool(highlight_turbines)
    for i, t in enumerate(turbines):
        sub = df[df['turbine'] == t].sort_values('month_idx')
        color = colors[i]
        is_hl = has_hl and t in highlight_turbines
        alpha = 1.0 if (is_hl or not has_hl) else 0.3
        style = resolve_turbine_linestyle(t, turbine_blades, blade_styles)
        ls = style['ls']
        base_alpha = style['alpha']
        hl_factor = 1.4 if (is_hl or not has_hl) else 0.5
        lw = style['lw'] * hl_factor
        alpha = base_alpha if (is_hl or not has_hl) else base_alpha * 0.3
        lbl = format_turbine_label(t, turbine_blades) + (' [高亮]' if is_hl else '')
        ax.plot(sub['month_idx'], sub[metric_col], linestyle=ls, marker='o',
                color=color,
                label=lbl, linewidth=lw, alpha=alpha, markersize=4)
        if is_hl or not has_hl:
            for _, row in sub.iterrows():
                ax.text(row['month_idx'], row[metric_col] + 0.001,
                        f'{row[metric_col]:.4f}',
                        ha='center', va='bottom', fontsize=8)
    ax.set_xticks(range(len(months_sorted)))
    ax.set_xticklabels([str(m) for m in months_sorted], rotation=30, fontsize=10)
    ax.set_xlabel('月份', fontsize=13)
    ax.set_ylabel(f'月平均{cn_name} ({unit})', fontsize=13)
    ax.set_title(f'各机组月平均{cn_name}变化曲线', fontsize=16, fontweight='bold')
    ax.legend(title='机组', fontsize=9, title_fontsize=10, loc='upper left', ncol=2)
    ax.grid(axis='both', alpha=0.3)

    # 右上角汇总表：第一列月份，第二列该月所有机组的平均值
    month_avg_rows = []
    for m in months_sorted:
        val = df.loc[df['month'] == m, metric_col].mean(skipna=True)
        if pd.isna(val):
            month_avg_rows.append([str(m), '-'])
        else:
            month_avg_rows.append([str(m), f'{val:.4f}'])
    _add_summary_table(ax, month_avg_rows, ['月份', f'风机平均{cn_name}'])
    plt.tight_layout()
    out_path = os.path.join(out_dir, f'月平均{cn_name}曲线.png')
    fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    return True


def plot_ti_bin_curve(bin_df, out_dir, highlight_turbines=None,
                      title_suffix='', fname_suffix='', count_df=None,
                      turbine_blades=None, blade_styles=None):
    """湍流度-风速分布曲线（P90）。

    X 轴 = 风速 bin 中心 (m/s)，Y 轴 = P90 湍流度，每机组一条线。
    Args:
        bin_df: compute_ti_p90_by_bin 返回的 DataFrame（index=bin_center, columns=turbine）
        highlight_turbines: iterable of int 或 None
        title_suffix: 标题后缀（如 ' (2026-04)'）
        fname_suffix: 文件名后缀（如 '_2026-04'）
        count_df: pd.DataFrame (index=bin_center, columns=turbine, values=count) 或 None。
            给出时在曲线下方添加分组柱状图，显示每个 bin × 机组 的有效窗口数；
            颜色与上方曲线一一对应。None 时只画 P90 曲线（兼容旧行为）。
        turbine_blades: dict {机组号: 叶型名}
        blade_styles: dict {叶型名: 线型名称}
    """
    if bin_df is None or bin_df.empty:
        return False
    has_count = count_df is not None and not count_df.empty

    if has_count:
        fig, (ax, ax_bar) = plt.subplots(
            2, 1, figsize=(16, 10),
            gridspec_kw={'height_ratios': [3, 1], 'hspace': 0.08},
            sharex=True, constrained_layout=True)
    else:
        fig, ax = plt.subplots(figsize=(16, 8), constrained_layout=True)

    # 上方：P90 曲线
    turbines = sorted(bin_df.columns)
    colors = _distinct_colors(len(turbines))
    has_hl = bool(highlight_turbines)
    summary_rows = []
    for i, t in enumerate(turbines):
        sub = bin_df[t].dropna().sort_index()
        if sub.empty:
            continue
        color = colors[i]
        is_hl = has_hl and t in highlight_turbines
        alpha = 1.0 if (is_hl or not has_hl) else 0.3
        style = resolve_turbine_linestyle(t, turbine_blades, blade_styles)
        ls = style['ls']
        base_alpha = style['alpha']
        hl_factor = 1.4 if (is_hl or not has_hl) else 0.5
        lw = style['lw'] * hl_factor
        alpha = base_alpha if (is_hl or not has_hl) else base_alpha * 0.3
        lbl = format_turbine_label(t, turbine_blades) + (' [高亮]' if is_hl else '')
        ax.plot(sub.index, sub.values, linestyle=ls, marker='o',
                color=color, label=lbl,
                linewidth=lw, alpha=alpha, markersize=4)
        v10 = _value_at_bin(sub, 10.0)
        summary_rows.append([f'#{int(t)}号', f'{v10:.3f}' if v10 is not None else '-'])
    _add_summary_table(ax, summary_rows, ['机组', 'P90@10m/s'])
    ax.set_ylabel('P90 湍流度', fontsize=13)
    ax.set_title(f'各机组湍流度-风速分布曲线 (P90){title_suffix}',
                 fontsize=16, fontweight='bold')
    ax.legend(title='机组', fontsize=9, title_fontsize=10, loc='upper left', ncol=2)
    ax.grid(axis='both', alpha=0.3)

    # Y 轴上限：用所有 bin 数据的 P95 + 15% buffer 截断。
    # 某些机组在低风速段 P90 可能异常高（如尾流/地形扰动），不截断会把
    # 整个 Y 轴拉高，导致其他机组的细节变化被压扁看不清。
    # 截断后曲线"撞顶"仍可见，但低湍流区域的差异更明显。
    _clamp_ti_yaxis(ax, bin_df)

    if has_count:
        # 下方：分组柱状图，每 bin 内每机组一根柱，颜色与曲线对应
        all_bins = sorted(set(bin_df.index.dropna()) | set(count_df.index.dropna()))
        turbines_c = sorted(count_df.columns)
        n_t = max(len(turbines_c), 1)
        width = 0.8 / n_t
        for i, t in enumerate(turbines_c):
            xs, ys = [], []
            for b in all_bins:
                if b in count_df.index and not pd.isna(count_df.loc[b, t]):
                    xs.append(b + (i - (n_t - 1) / 2) * width)
                    ys.append(int(count_df.loc[b, t]))
            if not xs:
                continue
            color = colors[i]
            ax_bar.bar(xs, ys, width, color=color, alpha=0.75,
                       align='center', label=f'#{t}号机组')
            # 柱顶标数值（数据量适中时才标，避免过密）
            if len(all_bins) * n_t <= 70:
                for x, y in zip(xs, ys):
                    ax_bar.text(x, y, str(y), ha='center', va='bottom', fontsize=11, fontweight='bold')
        ax_bar.set_xticks(list(all_bins))
        ax_bar.set_xticklabels([str(int(b)) for b in all_bins])
        ax_bar.set_xlabel('风速 bin 中心 (m/s)', fontsize=13)
        ax_bar.set_ylabel('有效窗口数', fontsize=11)
        ax_bar.grid(axis='y', alpha=0.3)
    else:
        ax.set_xlabel('风速 (m/s)', fontsize=13)

    out_path = os.path.join(out_dir, f'湍流度-风速分布P90曲线{fname_suffix}.png')
    fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    return True


def plot_ti_p90_per_turbine(p90_by_turbine, out_dir, highlight_turbines=None,
                            turbine_blades=None, count_by_turbine=None):
    """每机组一张 P90 TI-风速bin 分布曲线：每月份一条线。

    X 轴 = 风速 bin 中心 (m/s)，Y 轴 = P90 湍流度，每条线 = 一个月份。
    与 plot_ti_bin_curve 互补：那个是「同月份不同机组」的 P90 分布，
    本函数是「同机组不同月份」的 P90 分布对比。
    颜色：月数 ≤ 7 时用 PALETTE；> 7 时用 tab20 离散调色板（>20 再叠加线型），
    避免颜色循环重复。
    Args:
        p90_by_turbine: compute_ti_p90_by_turbine_month 返回的 dict
        highlight_turbines: 此图每张只一个机组，参数保留但不影响绘图
        turbine_blades: dict {机组号: 叶型名}，叶型信息附在标题中
        count_by_turbine: compute_ti_count_by_turbine_month 返回的 dict；给出时
            在曲线下方添加分组柱状图，显示每个 bin × 月份 的有效窗口数；
            颜色与上方月份曲线一一对应。None 时只画 P90 曲线（兼容旧行为）。
    Returns:
        生成的图数量
    """
    if not p90_by_turbine:
        return 0
    count = 0
    for turbine, pivot in p90_by_turbine.items():
        if pivot is None or pivot.empty:
            continue
        months_sorted = sorted(pivot.columns)
        n = len(months_sorted)
        # 颜色策略：
        #   N ≤ 7   → PALETTE
        #   7 < N ≤ 20 → tab20 高对比度离散调色板（任意两色差异明显）
        #   N > 20  → tab20 循环 + 线型变化（实线/虚线/点划/点）叠加区分
        if n <= len(PALETTE):
            colors = list(PALETTE[:n])
            linestyles = ['-'] * n
        else:
            cmap = plt.cm.tab20
            colors = [cmap(i % 20) for i in range(n)]
            ls_list = ['-', '--', '-.', ':']
            linestyles = [ls_list[(i // 20) % len(ls_list)] for i in range(n)]

        count_pivot = (count_by_turbine or {}).get(turbine)
        has_count = count_pivot is not None and not count_pivot.empty

        if has_count:
            fig, (ax, ax_bar) = plt.subplots(
                2, 1, figsize=(16, 10),
                gridspec_kw={'height_ratios': [3, 1], 'hspace': 0.08},
                sharex=True, constrained_layout=True)
        else:
            fig, ax = plt.subplots(figsize=(16, 8), constrained_layout=True)

        # 上方：P90 曲线（每月份一条）
        month_summary_rows = []
        for i, mk in enumerate(months_sorted):
            sub = pivot[mk].dropna().sort_index()
            if sub.empty:
                continue
            ax.plot(sub.index, sub.values, marker='o', linestyle=linestyles[i],
                    color=colors[i], label=mk,
                    linewidth=2.0, alpha=1.0, markersize=4)
            v10 = _value_at_bin(sub, 10.0)
            month_summary_rows.append([str(mk), f'{v10:.3f}' if v10 is not None else '-'])
        _add_summary_table(ax, month_summary_rows, ['月份', 'P90@10m/s'])
        ax.set_ylabel('P90 湍流度', fontsize=13)
        blade_suffix = ''
        if turbine_blades and turbine_blades.get(turbine):
            blade_suffix = f' [叶型: {turbine_blades[turbine]}]'
        ax.set_title(f'#{int(turbine)}号机组{blade_suffix}湍流度-风速分布曲线 (P90, 按月对比)',
                     fontsize=16, fontweight='bold')
        ax.legend(title='月份', fontsize=9, title_fontsize=10,
                  loc='upper left', ncol=2)
        ax.grid(axis='both', alpha=0.3)

        if has_count:
            # 下方：分组柱状图，每 bin 内每月份一根柱，颜色与上方曲线一一对应
            all_bins = sorted(set(pivot.index.dropna()) | set(count_pivot.index.dropna()))
            width = 0.8 / max(n, 1)
            bar_labels = 0
            for i, mk in enumerate(months_sorted):
                if mk not in count_pivot.columns:
                    continue
                xs, ys = [], []
                for b in all_bins:
                    if b in count_pivot.index and not pd.isna(count_pivot.loc[b, mk]):
                        xs.append(b + (i - (n - 1) / 2) * width)
                        ys.append(int(count_pivot.loc[b, mk]))
                if not xs:
                    continue
                ax_bar.bar(xs, ys, width, color=colors[i], alpha=0.75,
                           align='center', label=mk)
                bar_labels += len(xs)
            # 柱顶标数值（数据量适中时才标，避免过密）
            if bar_labels <= 70:
                for i, mk in enumerate(months_sorted):
                    if mk not in count_pivot.columns:
                        continue
                    for b in all_bins:
                        if b in count_pivot.index and not pd.isna(count_pivot.loc[b, mk]):
                            x = b + (i - (n - 1) / 2) * width
                            y = int(count_pivot.loc[b, mk])
                            ax_bar.text(x, y, str(y), ha='center', va='bottom', fontsize=11, fontweight='bold')
            ax_bar.set_xticks(list(all_bins))
            ax_bar.set_xticklabels([str(int(b)) for b in all_bins])
            ax_bar.set_xlabel('风速 bin 中心 (m/s)', fontsize=13)
            ax_bar.set_ylabel('有效窗口数', fontsize=11)
            ax_bar.grid(axis='y', alpha=0.3)
        else:
            ax.set_xlabel('风速 (m/s)', fontsize=13)

        out_path = os.path.join(out_dir, f'机组{int(turbine)}号湍流度-风速分布P90曲线.png')
        fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
        plt.close(fig)
        count += 1
    return count


def plot_monthly_ti_bin_timeseries(df_ti, out_dir, highlight_turbines=None,
                                   turbine_blades=None, blade_styles=None):
    """月度 bin 级 TI 时间序列：每个 bin 出一张图。

    X 轴 = 月份，Y 轴 = TI 值，每机组一条线。
    Args:
        df_ti: read_monthly_ti_file 返回的 DataFrame（含 turbine, month, bin_center, ti）
        turbine_blades: dict {机组号: 叶型名}
        blade_styles: dict {叶型名: 线型名称}
    Returns:
        生成的图数量
    """
    if df_ti is None or df_ti.empty:
        return 0
    has_hl = bool(highlight_turbines)
    count = 0
    for bin_center, grp in df_ti.groupby('bin_center'):
        pivot = grp.pivot_table(index='month', columns='turbine', values='ti', aggfunc='mean')
        pivot = pivot.sort_index()
        if pivot.empty:
            continue
        months_sorted = list(pivot.index)
        m2idx = {m: i for i, m in enumerate(months_sorted)}

        fig, ax = plt.subplots(figsize=(max(14, len(months_sorted) * 0.8), 8))
        turbines = sorted(pivot.columns)
        colors = _distinct_colors(len(turbines))
        ti_summary_rows = []
        for i, t in enumerate(turbines):
            sub = pivot[t].dropna()
            if sub.empty:
                continue
            color = colors[i]
            is_hl = has_hl and t in highlight_turbines
            alpha = 1.0 if (is_hl or not has_hl) else 0.3
            style = resolve_turbine_linestyle(t, turbine_blades, blade_styles)
            ls = style['ls']
            hl_factor = 1.4 if (is_hl or not has_hl) else 0.5
            lw = style['lw'] * hl_factor
            lbl = format_turbine_label(t, turbine_blades) + (' [高亮]' if is_hl else '')
            xs = [m2idx[m] for m in sub.index]
            ax.plot(xs, sub.values, linestyle=ls, marker='o',
                    color=color, label=lbl,
                    linewidth=lw, alpha=alpha, markersize=4)
            ti_summary_rows.append([f'#{int(t)}号', f'{sub.mean():.3f}'])
        _add_summary_table(ax, ti_summary_rows, ['机组', f'平均TI@{int(bin_center)}m/s'])
        ax.set_xticks(range(len(months_sorted)))
        ax.set_xticklabels([str(m) for m in months_sorted], rotation=30, fontsize=9)
        ax.set_xlabel('月份', fontsize=13)
        ax.set_ylabel('湍流度', fontsize=13)
        ax.set_title(f'各机组月度{int(bin_center)}m/s湍流度变化曲线', fontsize=16, fontweight='bold')
        ax.legend(title='机组', fontsize=9, title_fontsize=10, loc='upper left', ncol=2)
        ax.grid(axis='both', alpha=0.3)
        # 同 plot_ti_bin_curve：截断 Y 轴上限避免极端机组压扁其他曲线
        _clamp_ti_yaxis(ax, pivot)
        plt.tight_layout()
        out_path = os.path.join(out_dir, f'月度{int(bin_center)}ms湍流度曲线.png')
        fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
        plt.close(fig)
        count += 1
    return count


def plot_monthly_ti_bin_cross_year(df_ti, out_dir):
    """跨年同月对比图：每个风速 bin 一张图，X 轴 1-12 月，每年一条曲线。

    与 ``plot_monthly_ti_bin_timeseries`` 互补：那张是「同 bin 看不同机组 / 时间序列」，
    本张是「同 bin 看不同年份的同月均值」，便于回答「今年 1 月比去年 1 月更湍流吗？」。

    跨机组简单平均（每个 (年, 月) 一个 TI 均值），仅当数据跨 ≥2 年时生成。

    Args:
        df_ti: read_monthly_ti_file 返回的 DataFrame（含 turbine, month, bin_center, ti）

    Returns:
        生成的图数量（只有 1 年数据时返回 0）
    """
    if df_ti is None or df_ti.empty:
        return 0
    # 顶层判断：整体只有 1 年 → 直接跳过，省得每个 bin 都白算一遍
    years_all = pd.Series(df_ti['month'].dt.year.unique())
    if len(years_all) < 2:
        return 0

    count = 0
    for bin_center, grp in df_ti.groupby('bin_center'):
        years = sorted(grp['month'].dt.year.unique())
        if len(years) < 2:
            continue  # 该 bin 只有 1 年数据，跳过

        # 每年一条曲线：跨机组平均，X 轴 = 月-of-year (1-12)
        year_curves = {}
        for y in years:
            sub = grp[grp['month'].dt.year == y].copy()
            sub['_moy'] = sub['month'].dt.month
            moy_mean = sub.groupby('_moy')['ti'].mean()
            year_curves[y] = moy_mean

        fig, ax = plt.subplots(figsize=(12, 7))
        colors = _distinct_colors(len(year_curves))
        summary_rows = []
        for i, y in enumerate(years):
            curve = year_curves[y]
            xs = list(curve.index)
            ys = list(curve.values)
            ax.plot(xs, ys, '-o', color=colors[i],
                    label=f'{y} 年', linewidth=2.2, alpha=0.9, markersize=7)
            summary_rows.append([f'{y} 年', f'{curve.mean():.3f}'])

        _add_summary_table(ax, summary_rows, ['年份', f'年均TI@{int(bin_center)}m/s'])
        ax.set_xticks(range(1, 13))
        ax.set_xticklabels([f'{m}月' for m in range(1, 13)], fontsize=10)
        ax.set_xlabel('月份', fontsize=13)
        ax.set_ylabel('湍流度', fontsize=13)
        ax.set_title(
            f'月度{int(bin_center)}m/s 湍流度跨年对比（{years[0]}–{years[-1]}，{len(years)} 年）',
            fontsize=15, fontweight='bold',
        )
        ax.legend(title='年份', fontsize=10, title_fontsize=11, loc='upper left')
        ax.grid(axis='both', alpha=0.3)
        ax.set_xlim(0.5, 12.5)
        plt.tight_layout()
        out_path = os.path.join(out_dir, f'月度{int(bin_center)}ms湍流度跨年对比.png')
        fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
        plt.close(fig)
        count += 1
    return count


def plot_monthly_ti_per_turbine_timeseries(df_ti, out_dir, turbine_blades=None):
    """单个机组的月度 TI 时间序列：每个机组一张图，每个风速 bin 一条线。

    X 轴 = 月份，Y 轴 = TI 值，每条线代表一个风速 bin。
    与 plot_monthly_ti_bin_timeseries 互补：那张是"同 bin 看不同机组"，
    本张是"同机组看不同 bin"。
    Args:
        df_ti: read_monthly_ti_file 返回的 DataFrame
        turbine_blades: dict {机组号: 叶型名}，叶型信息附在标题中
    Returns:
        生成的图数量
    """
    if df_ti is None or df_ti.empty:
        return 0
    count = 0
    for turbine, grp in df_ti.groupby('turbine'):
        pivot = grp.pivot_table(index='month', columns='bin_center',
                                values='ti', aggfunc='mean')
        pivot = pivot.sort_index()
        if pivot.empty:
            continue
        months_sorted = list(pivot.index)
        m2idx = {m: i for i, m in enumerate(months_sorted)}
        bins_sorted = sorted(pivot.columns)
        bin_colors = _distinct_colors(len(bins_sorted))

        fig, ax = plt.subplots(figsize=(max(14, len(months_sorted) * 0.8), 8))
        # bin → 该 bin 各月份 TI 均值，方便按月份汇总
        month_to_vals = {m: [] for m in months_sorted}
        # pivot 行=月份, 列=bin_center
        bin10_series = pivot[10.0] if 10.0 in pivot.columns else None
        if bin10_series is None and len(pivot.columns) > 0:
            # 无精确 10.0 bin 时，找最接近 10 的 bin
            closest_bc = pivot.columns[(np.abs(pivot.columns - 10.0)).argmin()]
            bin10_series = pivot[closest_bc]
        for i, bc in enumerate(bins_sorted):
            sub = pivot[bc].dropna()
            if sub.empty:
                continue
            color = bin_colors[i]
            xs = [m2idx[m] for m in sub.index]
            ax.plot(xs, sub.values, '-o', color=color,
                    label=f'{int(bc)} m/s', linewidth=2.0, alpha=1.0, markersize=4)
            for m, v in sub.items():
                month_to_vals[m].append(v)
        month_summary_rows = []
        for m in months_sorted:
            v10 = bin10_series.get(m) if bin10_series is not None else None
            if v10 is not None and not pd.isna(v10):
                month_summary_rows.append([str(m), f'{v10:.3f}'])
            else:
                # 该月缺 10m/s 数据 → 退化为所有 bin 均值
                vals = month_to_vals[m]
                if vals:
                    month_summary_rows.append([str(m), f'{sum(vals)/len(vals):.3f}*'])
        _add_summary_table(ax, month_summary_rows, ['月份', 'TI@10m/s'])
        ax.set_xticks(range(len(months_sorted)))
        ax.set_xticklabels([str(m) for m in months_sorted], rotation=30, fontsize=9)
        ax.set_xlabel('月份', fontsize=13)
        ax.set_ylabel('湍流度', fontsize=13)
        blade_suffix = ''
        if turbine_blades and turbine_blades.get(turbine):
            blade_suffix = f' [叶型: {turbine_blades[turbine]}]'
        ax.set_title(f'#{int(turbine)}号机组{blade_suffix}月度湍流度变化曲线(按风速bin)',
                     fontsize=16, fontweight='bold')
        ax.legend(title='风速bin', fontsize=9, title_fontsize=10,
                  loc='upper left', ncol=2)
        ax.grid(axis='both', alpha=0.3)
        plt.tight_layout()
        out_path = os.path.join(out_dir, f'机组{int(turbine)}号月度湍流度曲线.png')
        fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
        plt.close(fig)
        count += 1
    return count


# ================================================================
# 跨风场对比
# ================================================================
FARM_METRIC_INFO = {
    'wind_speed': ('风速', 'm/s'),
    'density': ('密度', 'kg/m3'),
}


def plot_farm_compare(farm_monthly, metric, out_dir):
    """画风场月均对比图：X=月份，每风场一条线。

    Args:
        farm_monthly: dict[farm_name, DataFrame]，DataFrame index=月份(Period),
                      columns 含 metric 列
        metric: 'wind_speed' or 'density'
        out_dir: 输出目录
    Returns:
        bool: 是否成功生成图（全空 / 全 NaN 时 False）
    """
    cn_name, unit = FARM_METRIC_INFO[metric]
    # 过滤掉没有该 metric 列或全 NaN 的风场
    farms_sorted = sorted(farm_monthly.keys())
    series_by_farm = {}
    all_months_set = set()
    for name in farms_sorted:
        df = farm_monthly[name]
        if metric not in df.columns:
            continue
        s = df[metric].dropna()
        if s.empty:
            continue
        series_by_farm[name] = s
        all_months_set.update(s.index.tolist())
    if not series_by_farm:
        return False
    # 月份并集排序，建立数值索引
    months_sorted = sorted(all_months_set)
    m2idx = {m: i for i, m in enumerate(months_sorted)}

    fig, ax = plt.subplots(figsize=(max(14, len(months_sorted) * 0.9), 8))
    farm_names = list(series_by_farm.keys())
    colors = _distinct_colors(len(farm_names))
    # 风场数 ≤ 12 时显示数据点标注；> 12 时图过密，省略避免重叠
    show_labels = len(farm_names) <= 12
    summary_rows = []
    for i, name in enumerate(farm_names):
        s = series_by_farm[name]
        xs = [m2idx[m] for m in s.index]
        ax.plot(xs, s.values, '-o', color=colors[i],
                label=name, linewidth=2.0, alpha=0.95, markersize=5)
        # 数据点标注（值标签）
        if show_labels:
            for m, v in s.items():
                ax.text(m2idx[m], v + 0.001, f'{v:.3f}',
                        ha='center', va='bottom', fontsize=8, color=colors[i])
        # 汇总表行：风场名 + 全期均值
        summary_rows.append([name, f'{s.mean():.3f}'])

    _add_summary_table(ax, summary_rows, ['风场', '全期均值'])
    ax.set_xticks(range(len(months_sorted)))
    ax.set_xticklabels([str(m) for m in months_sorted], rotation=30, fontsize=10)
    ax.set_xlabel('月份', fontsize=13)
    ax.set_ylabel(f'月均{cn_name} ({unit})', fontsize=13)
    ax.set_title(f'各风场月均{cn_name}对比', fontsize=16, fontweight='bold')
    ax.legend(title='风场', fontsize=10, title_fontsize=11,
              loc='upper left', ncol=2)
    ax.grid(axis='both', alpha=0.3)
    plt.tight_layout()
    out_path = os.path.join(out_dir, f'风场月均{cn_name}对比.png')
    fig.savefig(out_path, dpi=DPI, bbox_inches='tight')
    plt.close(fig)
    return True
