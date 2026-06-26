"""
prebend_design - 叶片预弯度计算纯算法包

三种参数化模式：
- 幂函数（Power）：tip_pb + z_start_ratio + gamma 经验公式
- B 样条（Bspline）：控制点 + 连续阶
- 约束 B 样条（Constrained）：固定点 + 用户点 + 起始位置比

无 PyQt5 / matplotlib 依赖，UI 在 src/tools/prebend_design_panel.py。

公共 API
--------
compute_prebend_power(z_span, tip_pb, z_start_ratio, z_end, gamma) -> ndarray
compute_prebend_bspline(control_points, z_span, continuity, z_end) -> ndarray
compute_prebend_constrained(fixed_points, user_points, z_span, z_start_ratio, z_end) -> ndarray
"""

from .prebend import (
    DEFAULT_TIP_PB,
    DEFAULT_GAMMA,
    DEFAULT_Z_START_RATIO,
    DEFAULT_CONTINUITY,
    DEFAULT_CTRL,
    DEFAULT_Z_SPAN,
    GAMMA_MIN,
    compute_prebend_power,
    compute_prebend_bspline,
    compute_prebend_constrained,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_TIP_PB",
    "DEFAULT_GAMMA",
    "DEFAULT_Z_START_RATIO",
    "DEFAULT_CONTINUITY",
    "DEFAULT_CTRL",
    "DEFAULT_Z_SPAN",
    "GAMMA_MIN",
    "compute_prebend_power",
    "compute_prebend_bspline",
    "compute_prebend_constrained",
    "__version__",
]
