"""
prebend.py - 预弯度计算业务逻辑（纯算法，无 PyQt5 / matplotlib）

从 pyqt_curve_fitter11.py 的 ``PrebendWidget`` 类中提取三种预弯模式的核心算法：
    - 幂函数 (Power)
    - B 样条 (B-spline)
    - 约束 B 样条 (Constrained B-spline)

同时提供默认常量和默认展向位置数组。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np
from scipy.interpolate import PchipInterpolator, BSpline, make_interp_spline

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
]

# ---------------------------------------------------------------------------
# 默认常量（与源码 PrebendWidget 内部一致）
# ---------------------------------------------------------------------------

#: 默认叶尖预弯值 (m)
DEFAULT_TIP_PB: float = -5.57

#: 默认幂指数 gamma
DEFAULT_GAMMA: float = 1.75

#: 默认起始位置比例 (z/R)
DEFAULT_Z_START_RATIO: float = 0.35

#: 默认连续性
DEFAULT_CONTINUITY: str = "C1"

#: 连续性对应的最小 gamma 值
GAMMA_MIN: dict[str, float] = {"C0": 1.0, "C1": 2.0, "C2": 3.0}

#: B 样条模式默认控制点 (z/R, prebend_m)
DEFAULT_CTRL: List[Tuple[float, float]] = [
    (0.35, 0.00),
    (0.50, 0.00),
    (0.65, -3.00),
    (0.80, -4.50),
    (0.90, -5.20),
    (1.00, -5.57),
]

#: 默认展向位置数组：从 0.0 到 80.0m，共 54 个值
DEFAULT_Z_SPAN: np.ndarray = np.linspace(0.0, 80.0, 54)


# ---------------------------------------------------------------------------
# 幂函数模式
# ---------------------------------------------------------------------------

def compute_prebend_power(
    z_span: np.ndarray,
    tip_pb: float = DEFAULT_TIP_PB,
    z_start_ratio: float = DEFAULT_Z_START_RATIO,
    z_end: float | None = None,
    gamma: float = DEFAULT_GAMMA,
) -> np.ndarray:
    """幂函数预弯计算。

    公式::

        z_tip  = z_span[-1]          (或显式传入 z_end)
        z_start = z_start_ratio * z_tip

        对于 z > z_start:
            prebend = ((z - z_start) / (z_tip - z_start)) ** gamma * tip_pb
        对于 z <= z_start:
            prebend = 0

    Parameters
    ----------
    z_span : np.ndarray
        展向位置数组（单位 m），要求至少 2 个点且末尾元素为叶尖。
    tip_pb : float, default DEFAULT_TIP_PB (-5.57)
        叶尖预弯值 (m)。
    z_start_ratio : float, default DEFAULT_Z_START_RATIO (0.35)
        预弯起始位置占叶尖的比例。
    z_end : float, optional
        显式指定叶尖位置。``None`` 时取 ``z_span[-1]``。
        当展向数组不含叶尖时使用此参数。
    gamma : float, default DEFAULT_GAMMA (1.75)
        幂指数。

    Returns
    -------
    np.ndarray
        与 ``z_span`` 等长的预弯值数组。
    """
    z_span = np.asarray(z_span, dtype=float)
    z_tip = float(z_end) if z_end is not None else float(z_span[-1])
    z_start = z_start_ratio * z_tip

    prebend = np.zeros_like(z_span)
    mask = z_span > z_start
    if np.any(mask):
        prebend[mask] = (
            (z_span[mask] - z_start) / (z_tip - z_start)
        ) ** gamma * tip_pb
    return prebend


# ---------------------------------------------------------------------------
# B 样条模式
# ---------------------------------------------------------------------------

def _build_bspline_with_continuity(
    ctrl_x_nd: Sequence[float],
    ctrl_y: Sequence[float],
    continuity: str = "C1",
) -> Tuple[List[float], List[float]]:
    """在起始控制点处重复以控制连续性。

    与源码 ``PrebendWidget._build_bspline_with_continuity`` 完全一致。

    Parameters
    ----------
    ctrl_x_nd : sequence of float
        归一化控制点 X (z/R, 0~1)。
    ctrl_y : sequence of float
        控制点 Y (prebend m)。
    continuity : str
        ``'C0'`` / ``'C1'`` / ``'C2'``。

    Returns
    -------
    ext_x, ext_y : list[float], list[float]
        扩展后的控制点坐标。
    """
    n_repeat = {"C0": 0, "C1": 1, "C2": 2}.get(continuity, 1)
    x0, y0 = ctrl_x_nd[0], ctrl_y[0]
    ext_x = [x0] * (1 + n_repeat) + list(ctrl_x_nd[1:])
    ext_y = [y0] * (1 + n_repeat) + list(ctrl_y[1:])
    return ext_x, ext_y


def compute_prebend_bspline(
    control_points: Sequence[Tuple[float, float]],
    z_span: np.ndarray,
    continuity: str = "C1",
    z_end: float | None = None,
) -> np.ndarray:
    """B 样条预弯计算。

    流程（与源码 ``PrebendWidget.compute_prebend_bspline`` 一致）：

    1. 根据连续性在起始控制点重复若干次。
    2. 过滤 NaN / 非有限值。
    3. 如果控制点不足以构造 B 样条 (n < 2)，返回全零。
    4. 如果点数 < 需要的阶数，回退到 PCHIP。
    5. 否则构造 BSpline，在密集参数域采样得到 (x_curve, y_curve)，
       再用 PCHIP 将 y 关于 x(绝对米) 插值到 z_span。
    6. 在起始控制点之前的位置，预弯置零。

    Parameters
    ----------
    control_points : sequence of (float, float)
        控制点列表，每个元素为 ``(z/R, prebend_m)``，
        z/R 取值 0~1。
    z_span : np.ndarray
        展向位置数组 (m)。
    continuity : str, default 'C1'
        起始控制点连续性约束。
    z_end : float, optional
        显式指定叶尖位置 (m)，``None`` 时取 ``z_span[-1]``。

    Returns
    -------
    np.ndarray
        预弯值数组，与 ``z_span`` 等长。
    """
    z_span = np.asarray(z_span, dtype=float)
    z_tip = float(z_end) if z_end is not None else float(z_span[-1])

    ctrl_x_nd = [float(p[0]) for p in control_points]
    ctrl_y = [float(p[1]) for p in control_points]

    if len(ctrl_x_nd) < 2:
        return np.zeros_like(z_span)

    ctrl_x_nd, ctrl_y = _build_bspline_with_continuity(
        ctrl_x_nd, ctrl_y, continuity
    )
    ctrl_x_nd = np.asarray(ctrl_x_nd, dtype=float)
    ctrl_y = np.asarray(ctrl_y, dtype=float)

    valid = np.isfinite(ctrl_x_nd) & np.isfinite(ctrl_y)
    ctrl_x_nd = ctrl_x_nd[valid]
    ctrl_y = ctrl_y[valid]

    if len(ctrl_x_nd) < 2:
        return np.zeros_like(z_span)

    n = min(4, len(ctrl_x_nd))
    p = n - 1

    # 点数不足以构造 B 样条 → 回退 PCHIP
    if len(ctrl_x_nd) < n:
        x_abs = ctrl_x_nd * z_tip
        if np.any(np.diff(x_abs) <= 0):
            x_abs = np.linspace(np.min(x_abs), np.max(x_abs), len(x_abs))
        interp = PchipInterpolator(x_abs, ctrl_y, extrapolate=True)
        return interp(z_span)

    # 构造节点向量
    interior_count = len(ctrl_x_nd) - p - 1
    if interior_count > 0:
        interior = np.linspace(0.0, 1.0, interior_count + 2)[1:-1]
    else:
        interior = np.array([])
    t = np.concatenate((np.zeros(p + 1), interior, np.ones(p + 1)))

    ctrl_pts = np.column_stack((ctrl_x_nd, ctrl_y))
    spline = BSpline(t, ctrl_pts, p, extrapolate=False)

    u_min, u_max = t[p], t[-p - 1]
    u_dense = np.linspace(u_min, u_max, max(400, 10 * len(ctrl_x_nd)))
    pts = spline(u_dense)

    x_curve = pts[:, 0] * z_tip
    y_curve = pts[:, 1]

    order = np.argsort(x_curve)
    x_s, y_s = x_curve[order], y_curve[order]
    keep = np.concatenate(([True], np.diff(x_s) > 1e-6))
    x_s, y_s = x_s[keep], y_s[keep]

    if len(x_s) >= 2:
        interp = PchipInterpolator(x_s, y_s)
        prebend = interp(z_span)
        prebend = np.where(np.isfinite(prebend), prebend, 0.0)
    else:
        prebend = np.zeros_like(z_span)

    # 起始控制点之前置零
    first_z = ctrl_x_nd[0] * z_tip
    prebend[z_span < first_z] = 0.0
    return prebend


# ---------------------------------------------------------------------------
# 约束 B 样条模式
# ---------------------------------------------------------------------------

def compute_prebend_constrained(
    fixed_points: Sequence[Tuple[float, float, float]],
    user_points: Sequence[Tuple[float, float]],
    z_span: np.ndarray,
    z_start_ratio: float = DEFAULT_Z_START_RATIO,
    z_end: float | None = None,
) -> np.ndarray:
    """约束 B 样条预弯计算。

    与源码 ``PrebendWidget._update_plot`` 中 constrained 分支逻辑一致：

    1. 合并起始点、固定点、用户点和叶尖点（按 z/R 排序）。
    2. 如果总点数 >= 4，阶数 k=3；否则 k = 点数 - 1。
    3. 去重保证严格递增。
    4. 使用 ``make_interp_spline`` 插值；失败时回退到 PCHIP。
    5. 在 z_start 之前的位置置零。

    Parameters
    ----------
    fixed_points : sequence of (z/R, prebend_m, z_abs_m)
        固定约束点（从解析文本中提取的带预弯值的点）。
        每个三元组为归一化 z/R、预弯值、绝对 z 坐标。
    user_points : sequence of (z/R, prebend_m)
        用户可拖拽的控制点。
    z_span : np.ndarray
        展向位置数组 (m)。
    z_start_ratio : float, default DEFAULT_Z_START_RATIO
        起始位置比例，此值之前预弯为零。
    z_end : float, optional
        显式叶尖位置 (m)，``None`` 时取 ``z_span[-1]``。

    Returns
    -------
    np.ndarray
        预弯值数组。
    """
    z_span = np.asarray(z_span, dtype=float)
    z_tip = float(z_end) if z_end is not None else float(z_span[-1])

    # 合并控制点（与源码 _get_constrained_merged 一致）
    merged: list[dict] = []
    merged.append({"x": z_start_ratio, "y": 0.0, "type": "start"})
    for fp in fixed_points:
        merged.append({"x": float(fp[0]), "y": float(fp[1]), "type": "fixed"})
    for up in user_points:
        merged.append({"x": float(up[0]), "y": float(up[1]), "type": "user"})
    tip_y = float(fixed_points[-1][1]) if fixed_points else 0.0
    merged.append({"x": 1.0, "y": tip_y, "type": "tip"})
    merged.sort(key=lambda pt: pt["x"])

    x_abs = np.array([pt["x"] * z_tip for pt in merged])
    y_abs = np.array([pt["y"] for pt in merged])

    if len(x_abs) >= 4:
        k = 3
    elif len(x_abs) >= 2:
        k = len(x_abs) - 1
    else:
        return np.zeros_like(z_span)

    # 去重保证严格递增
    if np.any(np.diff(x_abs) <= 0):
        keep = [0]
        for j in range(1, len(x_abs)):
            if x_abs[j] > x_abs[keep[-1]] + 1e-6:
                keep.append(j)
        x_abs = x_abs[keep]
        y_abs = y_abs[keep]

    try:
        spline = make_interp_spline(x_abs, y_abs, k=k)
        prebend = spline(z_span)
        prebend = np.where(np.isfinite(prebend), prebend, 0.0)
    except Exception:
        interp = PchipInterpolator(x_abs, y_abs)
        prebend = interp(z_span)
        prebend = np.where(np.isfinite(prebend), prebend, 0.0)

    z_start_abs = z_start_ratio * z_tip
    prebend[z_span < z_start_abs] = 0.0
    return prebend
