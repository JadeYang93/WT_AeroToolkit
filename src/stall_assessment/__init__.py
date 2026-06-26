# -*- coding: utf-8 -*-
"""失速评估模块：由标准翼型（相对厚度→失速攻角）PCHIP 插值出失速攻角展向分布。

业务逻辑子包（无 PyQt5 依赖）。UI 面板见 ``src/tools/stall_assessment_panel.py``。

公共 API:
    parse_span_text(text)                   → 文本粘贴 → (positions, thickness)
    parse_span_file(path)                   → CSV/xlsx → (positions, thickness)
    interpolate(thickness, alpha, span_t)   → PCHIP 插值 → 展向失速攻角
    save_csv(positions, thickness, alpha, out_dir) → 写三列 CSV
    plot_check(ax, ...)                     → 校核图（标准点 + 插值曲线）
    plot_span(ax, positions, alpha)         → 展向分布图
"""
from .core import (
    parse_span_text,
    parse_span_file,
    interpolate,
    save_csv,
    plot_check,
    plot_span,
)

__all__ = [
    'parse_span_text',
    'parse_span_file',
    'interpolate',
    'save_csv',
    'plot_check',
    'plot_span',
]
