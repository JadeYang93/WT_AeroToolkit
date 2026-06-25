"""
curve_fitter - 多列数据曲线拟合 + 插值纯算法包

从 pyqt_curve_fitter11.py 提取，无 PyQt5 / matplotlib 依赖。

子模块
------
curve_fit     : 多列数据解析、多方法曲线拟合（样条/Akima/PCHIP/多项式）、任意 X 插值
segmented_fit : 分段复用 B 样条拟合（内段锁定 + 外段拟合 + 分段点 C2 连续）

公共 API
--------
parse_data(text, max_rows=10000) -> (data, column_labels)
generate_curve(x, y_cols, method, smooth, poly_deg, n_points) -> dict
calculate_interpolation(x_orig, y_fit, x_targets, method, smooth, poly_deg) -> ndarray

fit_outer_segment(inner_x, inner_y, ctrl_x, ctrl_y, ...) -> SegmentedFitResult
read_geo_column(xlsx_path, column_name) -> (span_ratio, values)
merge_and_export(result, output_path, columns=...) -> abs_path

预弯度相关功能已剥离到独立的 `prebend_design` 子包。
"""

from .curve_fit import (
    parse_data,
    generate_curve,
    calculate_interpolation,
    MAX_ROWS,
)
from .segmented_fit import (
    SegmentedFitResult,
    fit_outer_segment,
    make_default_outer_ctrl,
    merge_and_export,
    read_geo_column,
    SegmentedMiddleFitResult,
    fit_middle_segment,
    make_default_middle_ctrl,
)

__version__ = "0.3.0"

__all__ = [
    # curve_fit
    "parse_data",
    "generate_curve",
    "calculate_interpolation",
    "MAX_ROWS",
    # segmented_fit（单分段点，v0.2 起保留）
    "SegmentedFitResult",
    "fit_outer_segment",
    "make_default_outer_ctrl",
    "merge_and_export",
    "read_geo_column",
    # segmented_fit（双分段点，v0.3.09 起新增）
    "SegmentedMiddleFitResult",
    "fit_middle_segment",
    "make_default_middle_ctrl",
    "__version__",
]

