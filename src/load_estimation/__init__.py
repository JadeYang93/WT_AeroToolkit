# -*- coding: utf-8 -*-
"""载荷预估模块：基准稳态/动态载荷多项式拟合 + 新工况预测。

业务逻辑子包（无 PyQt5 依赖）。UI 面板见 `src/tools/load_estimation_panel.py`。
源项目：F:/python/载荷信息读取/load_estimation.py（已剥离）。

公共 API:
    load_data(xlsx_path)         → 读 3 个 sheet 为 ndarray dict
    fit_loads(data, n)           → 6 阶多项式拟合 + 新工况预测
    save_results(results, out_dir) → 写 result.csv / coefficients.csv + 8 张 PNG
    plot_result(ax, results, kind, name) → 在已给 matplotlib Axes 上画单张图
"""
from .core import (
    N_ORDER,
    COMPONENTS,
    VIEW_OPTIONS,
    load_data,
    fit_loads,
    save_results,
    plot_result,
)

__all__ = [
    'N_ORDER',
    'COMPONENTS',
    'VIEW_OPTIONS',
    'load_data',
    'fit_loads',
    'save_results',
    'plot_result',
]
