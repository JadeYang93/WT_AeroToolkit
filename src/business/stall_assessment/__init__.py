# -*- coding: utf-8 -*-
"""失速评估模块：由标准翼型（相对厚度→失速攻角）插值出失速攻角展向分布，
并与用户给定的实际攻角分布对比，标出失速发生位置（两曲线交点）。

业务逻辑子包（无 PyQt5 依赖）。UI 面板见 ``src/ui/stall_assessment_panel.py``。

公共 API:
    parse_span_text(text)                   → 文本粘贴 → (positions, thickness)
    parse_span_file(path)                   → CSV/xlsx → (positions, thickness)
    interpolate(thickness, alpha, span_t)   → PCHIP 插值 → 展向失速攻角（兼容路径）
    compute_alpha_span(...)                 → 带 VG 支持的展向插值
    save_csv(positions, thickness, alpha, out_dir, vg_active=None) → 写 CSV
    find_intersections(sp, sa, ap, a)       → 失速角/实际攻角两曲线交点
    plot_span_compare(ax, ...)              → 双曲线对比图 + 交点标注
"""
from .core import (
    parse_span_text,
    parse_span_file,
    normalize_positions,
    interpolate,
    compute_alpha_span,
    find_thickness_interval,
    pick_alpha,
    save_csv,
    plot_check,
    plot_span,
    find_intersections,
    plot_span_compare,
)

__all__ = [
    'parse_span_text',
    'parse_span_file',
    'normalize_positions',
    'interpolate',
    'compute_alpha_span',
    'find_thickness_interval',
    'pick_alpha',
    'save_csv',
    'plot_check',
    'plot_span',
    'find_intersections',
    'plot_span_compare',
]
