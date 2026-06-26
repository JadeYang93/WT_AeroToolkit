"""segmented_fit.py - 分段复用 B 样条拟合。

内段（[0, split_ratio]）锁定原数据不动；外段（[split_ratio, 1]）用控制点
+ B 样条重新拟合；在分段点处通过 ``bc_type`` 把内段末点的导数传给外段，
自然满足 C1 / C2 连续性。

典型用途：在叶片形状输出（shape_design）的 STAGE-1 几何参数基础上，
保留内段（如 0–0.7R）原值不变，只重设计外段（0.7R–叶尖）。适用于
预弯、后掠、弦长、扭角等任何沿展向的曲线。

纯算法，无 PyQt / matplotlib 依赖。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.interpolate import BSpline, CubicSpline, make_interp_spline


__all__ = [
    "SegmentedFitResult",
    "fit_outer_segment",
    "read_geo_column",
    "merge_and_export",
    "SegmentedMiddleFitResult",
    "fit_middle_segment",
    "make_default_middle_ctrl",
]


Continuity = Literal["C1", "C2"]


@dataclass(frozen=True)
class SegmentedFitResult:
    """分段拟合输出。

    Attributes
    ----------
    inner_x, inner_y : ndarray
        内段原数据（含末点 = 分段点），未做任何修改。
    outer_x, outer_y : ndarray
        外段采样点（不含分段点本身，避免与内段末点重叠）。
    full_x, full_y : ndarray
        合并曲线 = concat(inner, outer)，可直接导出。
    split_x : float
        分段点 X 值（= inner_x[-1]）。
    split_y : float
        分段点 Y 值（= inner_y[-1]）。
    dy_lock, ddy_lock : float
        分段点处的一阶 / 二阶导数（从内段末尾若干点局部样条求得），
        作为外段拟合的左端约束。
    continuity : 'C1' | 'C2'
        实际使用的连续性约束。
    spline : BSpline
        外段样条对象，可继续求值 / 求导。
    """

    inner_x: np.ndarray
    inner_y: np.ndarray
    outer_x: np.ndarray
    outer_y: np.ndarray
    full_x: np.ndarray
    full_y: np.ndarray
    split_x: float
    split_y: float
    dy_lock: float
    ddy_lock: float
    continuity: Continuity
    spline: BSpline


def _endpoint_derivatives(x_tail: np.ndarray, y_tail: np.ndarray, at_x: float) -> tuple[float, float]:
    """取内段末尾若干点拟合三次样条，求 at_x 处的一阶 / 二阶导。

    用局部样条而不是整体求导，避开内段中段的噪声 / 抖动，让分段点处的
    导数估计更稳定（只反映"靠近分段点这一小段"的走势）。

    Parameters
    ----------
    x_tail, y_tail : ndarray
        内段末尾约 6–10 个点（调用方切片传入）。
    at_x : float
        求导位置，通常 = x_tail[-1]。
    """
    cs = CubicSpline(x_tail, y_tail)
    return float(cs(at_x, 1)), float(cs(at_x, 2))


def fit_outer_segment(
    inner_x: np.ndarray,
    inner_y: np.ndarray,
    ctrl_x: np.ndarray,
    ctrl_y: np.ndarray,
    continuity: Continuity = "C2",
    k: int = 3,
    tail_points: int = 8,
    outer_resolution: int | None = None,
) -> SegmentedFitResult:
    """外段 B 样条拟合，在内段末点强制连续性。

    Parameters
    ----------
    inner_x, inner_y : ndarray
        内段原数据（必须单调递增、长度 ≥ 4）。末点 = 分段点。
    ctrl_x, ctrl_y : ndarray
        外段控制点（**不含**分段点，本函数会自动前置 ``inner`` 末点作为起点）。
        ``ctrl_x`` 必须严格递增，且所有元素 > ``inner_x[-1]``。
    continuity : 'C1' | 'C2'
        C1：只匹配一阶导；C2：同时匹配一阶 + 二阶导。默认 C2。
    k : int
        B 样条阶数，默认 3（三次）。``continuity='C2'`` 时建议 ``k≥3``。
    tail_points : int
        求分段点处导数时，取内段末尾多少点参与局部样条拟合。默认 8。
    outer_resolution : int | None
        外段采样密度（点数）。None 时自动取 ``max(80, len(ctrl) * 15)``。

    Returns
    -------
    SegmentedFitResult

    Raises
    ------
    ValueError
        内段点数过少 / 控制点数少于阶数 / 控制点 X 非严格递增 / 控制点
        越过分段点。
    """
    inner_x = np.asarray(inner_x, dtype=float)
    inner_y = np.asarray(inner_y, dtype=float)
    ctrl_x = np.asarray(ctrl_x, dtype=float)
    ctrl_y = np.asarray(ctrl_y, dtype=float)

    if inner_x.ndim != 1 or len(inner_x) < 4:
        raise ValueError(f"内段点数过少（{len(inner_x)}），至少 4 个")
    if not np.all(np.diff(inner_x) > 0):
        raise ValueError("内段 X 必须严格递增")
    if len(ctrl_x) < k:
        raise ValueError(f"外段控制点数（{len(ctrl_x)}）少于阶数 k={k}")
    if continuity not in ("C1", "C2"):
        raise ValueError(f"continuity 必须是 'C1' 或 'C2'，得到 {continuity!r}")
    if continuity == "C2" and k < 3:
        raise ValueError("C2 连续性要求 B 样条阶数 k ≥ 3")

    split_x = float(inner_x[-1])
    split_y = float(inner_y[-1])

    # 控制点必须严格递增且位于分段点右侧
    full_ctrl_x = np.concatenate([[split_x], ctrl_x])
    full_ctrl_y = np.concatenate([[split_y], ctrl_y])
    if not np.all(np.diff(full_ctrl_x) > 0):
        raise ValueError(
            "外段控制点 X 必须严格递增，且全部大于分段点 "
            f"({split_x:.6g})"
        )

    # 1. 求分段点处的导数（局部样条）
    n_tail = min(tail_points, len(inner_x))
    dy_lock, ddy_lock = _endpoint_derivatives(
        inner_x[-n_tail:], inner_y[-n_tail:], split_x
    )

    # 2. 构造 make_interp_spline 的边界约束。
    #    scipy 要求 len(left) + len(right) == k - 1（None 表示 0 个）：
    #      - C2（左端 2 个：dy + ddy）→ 右端 None（外段叶尖完全自由）
    #      - C1（左端 1 个：dy）→ 右端 [(2, 0)]（自然边界，二阶导 = 0）
    if continuity == "C2":
        left_bc = [(1, dy_lock), (2, ddy_lock)]
        right_bc = None
    else:  # C1
        left_bc = [(1, dy_lock)]
        right_bc = [(2, 0.0)]
    bc_type = (left_bc, right_bc)

    # 3. 外段 B 样条拟合
    spline = make_interp_spline(full_ctrl_x, full_ctrl_y, k=k, bc_type=bc_type)

    # 4. 外段采样（不含分段点本身，避免与内段末点重叠）
    if outer_resolution is None:
        outer_resolution = max(80, len(full_ctrl_x) * 15)
    outer_x = np.linspace(split_x, full_ctrl_x[-1], outer_resolution)[1:]
    outer_y = spline(outer_x)

    # 5. 合并（分段点只出现一次，用内段原值）
    full_x = np.concatenate([inner_x, outer_x])
    full_y = np.concatenate([inner_y, outer_y])

    return SegmentedFitResult(
        inner_x=inner_x,
        inner_y=inner_y,
        outer_x=outer_x,
        outer_y=outer_y,
        full_x=full_x,
        full_y=full_y,
        split_x=split_x,
        split_y=split_y,
        dy_lock=dy_lock,
        ddy_lock=ddy_lock,
        continuity=continuity,
        spline=spline,
    )


def make_default_outer_ctrl(
    split_x: float,
    tip_x: float,
    split_y: float,
    tip_y_hint: float | None,
    n_points: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """生成外段初始控制点（等距 X，Y 从分段点线性过渡到叶尖）。

    UI 初始化 / 控制点数变化时用。第一点就是分段点（fit_outer_segment
    内部会自动前置），这里返回的是**不含**分段点的外段控制点。

    Parameters
    ----------
    split_x, tip_x : float
        分段点与叶尖的 X 值。
    split_y : float
        分段点 Y（来自内段末点）。
    tip_y_hint : float | None
        叶尖 Y 的目标值。None 时取 ``split_y``（外段水平）。
    n_points : int
        外段控制点数（不含分段点），默认 5。
    """
    if n_points < 2:
        raise ValueError("外段控制点数至少 2")
    tip_y_hint = float(split_y) if tip_y_hint is None else float(tip_y_hint)
    # 控制点 X 在 (split_x, tip_x] 内等距分布
    ctrl_x = np.linspace(split_x, tip_x, n_points + 1)[1:]
    # Y 线性插值
    ctrl_y = np.linspace(split_y, tip_y_hint, n_points + 1)[1:]
    return ctrl_x, ctrl_y


def read_geo_column(xlsx_path, column_name: str) -> tuple[np.ndarray, np.ndarray]:
    """从 STAGE-1 的 blade_aero_geometry.xlsx 读 (Span, column) 两列。

    Parameters
    ----------
    xlsx_path : str | Path
        Excel 路径。默认指向 ``输出/shape_design/stage1/blade_aero_geometry.xlsx``。
    column_name : str
        Y 列名。常见取值：``'Prebend'`` / ``'Sweep'`` / ``'Chord'`` /
        ``'Twist'`` / ``'Th%'`` / ``'PitchAxis'`` / ``'RealThick'``。

    Returns
    -------
    (span_ratio, values) : (ndarray, ndarray)
        ``span_ratio`` 归一化到 [0, 1]（除以最大 Span）。
    """
    import pandas as pd

    df = pd.read_excel(xlsx_path)
    if "Span" not in df.columns:
        raise ValueError(f"Excel 缺少 Span 列：{xlsx_path}")
    if column_name not in df.columns:
        avail = [c for c in df.columns if c != "Span"]
        raise ValueError(
            f"Excel 缺少 {column_name} 列；可用列：{avail}。文件：{xlsx_path}"
        )
    span = df["Span"].to_numpy(dtype=float)
    y = df[column_name].to_numpy(dtype=float)
    if len(span) == 0:
        raise ValueError(f"Excel 无数据行：{xlsx_path}")
    span_max = float(span[-1])
    if span_max <= 0:
        raise ValueError(f"Span 末点非正（{span_max}），无法归一化")
    return span / span_max, y


def merge_and_export(
    result: SegmentedFitResult,
    output_path,
    columns: tuple[str, str] = ("span_ratio", "value"),
) -> str:
    """把合并曲线（内段 + 外段）导出为 CSV（UTF-8 BOM，Excel 友好）。

    Parameters
    ----------
    result : SegmentedFitResult
        ``fit_outer_segment`` 的返回值。
    output_path : str | Path
        输出 CSV 路径。
    columns : (str, str)
        CSV 两列的列名，默认 ``('span_ratio', 'value')``。

    Returns
    -------
    str
        实际写入的绝对路径。
    """
    import os
    import pandas as pd

    df = pd.DataFrame({columns[0]: result.full_x, columns[1]: result.full_y})
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


# ============================================================
# 双分段点（中段重设）—— v0.3.09 新增
# ============================================================

@dataclass(frozen=True)
class SegmentedMiddleFitResult:
    """双分段点拟合输出（左复用段 + 中段重设 + 右复用段）。

    Attributes
    ----------
    left_x, left_y : ndarray
        左复用段原数据（含末点 = R1）。
    middle_x, middle_y : ndarray
        中段拟合采样点（不含 R1/R2 端点，避免与左右段端点重叠）。
    right_x, right_y : ndarray
        右复用段原数据（含首点 = R2）；``has_right=False`` 时为空数组。
    full_x, full_y : ndarray
        合并曲线 = concat(left, middle, right)，可直接导出。
    r1_x, r1_y, r1_dy, r1_ddy : float
        R1 分段点处的 X / Y / 一阶导 / 二阶导（来自左段末尾局部样条估计，
        作为中段左端 C2 约束）。
    r2_x, r2_y, r2_dy, r2_ddy : float
        R2 分段点处的 X / Y / 一阶导 / 二阶导。``has_right=True`` 时来自右段
        开头局部样条估计（作为中段右端 C2 约束）；``has_right=False`` 时
        ``r2_dy/ddy`` 来自中段样条自身右端（无约束）。
    has_right : bool
        True = 双端 C2（有右复用段）；False = 退化情形（R2=1.0，单端 C2）。
    continuity : 'C1' | 'C2'
        实际使用的连续性约束（两端同时适用）。
    k : int
        B 样条阶数（双端 C2 要求 k≥5）。
    spline : BSpline
        中段样条对象，可继续求值 / 求导。
    """

    left_x: np.ndarray
    left_y: np.ndarray
    middle_x: np.ndarray
    middle_y: np.ndarray
    right_x: np.ndarray
    right_y: np.ndarray
    full_x: np.ndarray
    full_y: np.ndarray
    r1_x: float
    r1_y: float
    r1_dy: float
    r1_ddy: float
    r2_x: float
    r2_y: float
    r2_dy: float
    r2_ddy: float
    has_right: bool
    continuity: Continuity
    k: int
    spline: BSpline


def fit_middle_segment(
    left_x: np.ndarray,
    left_y: np.ndarray,
    right_x: np.ndarray | None,
    right_y: np.ndarray | None,
    ctrl_x: np.ndarray,
    ctrl_y: np.ndarray,
    continuity: Continuity = "C2",
    k: int = 5,
    tail_points: int = 8,
    middle_resolution: int | None = None,
) -> SegmentedMiddleFitResult:
    """双端 C2 的中段 B 样条拟合。

    三段结构：``[0, R1]`` 左复用 + ``[R1, R2]`` 中段重设 + ``[R2, 1]`` 右复用。

    Parameters
    ----------
    left_x, left_y : ndarray
        左复用段原数据（必须单调递增、长度 ≥ 4）。末点 = R1。
    right_x, right_y : ndarray or None
        右复用段原数据（必须单调递增、长度 ≥ 4）。首点 = R2。
        传 None 或空数组 → 退化情形（R2 = 1.0，单端 C2，无右段）。
    ctrl_x, ctrl_y : ndarray
        中段控制点。``ctrl_x`` 必须严格递增，且所有元素在 ``(R1, R2)`` 开区间内
        （不含端点，端点由左右复用段自动锁定）。
    continuity : 'C1' | 'C2'
        两端同时适用的连续性约束。C2 要求 ``k ≥ 5``（双端共 4 个约束 = k-1）；
        C1 要求 ``k ≥ 3``（双端共 2 个约束 = k-1）。
    k : int
        B 样条阶数。双端 C2 默认 5；双端 C1 可降到 3。
    tail_points : int
        求分段点处导数时，取左/右段端部多少点参与局部样条拟合。默认 8。
    middle_resolution : int | None
        中段采样密度（点数）。None 时自动取 ``max(80, len(ctrl) * 15)``。

    Returns
    -------
    SegmentedMiddleFitResult

    Raises
    ------
    ValueError
        左段点数过少 / 右段点数过少（启用时）/ 控制点数少于阶数 /
        控制点 X 非严格递增 / 控制点不在 (R1, R2) 开区间内 / R2 ≤ R1。
    """
    left_x = np.asarray(left_x, dtype=float)
    left_y = np.asarray(left_y, dtype=float)
    ctrl_x = np.asarray(ctrl_x, dtype=float)
    ctrl_y = np.asarray(ctrl_y, dtype=float)

    # 右段可选
    has_right = (
        right_x is not None and right_y is not None
        and len(right_x) > 0 and len(right_y) > 0
    )
    if has_right:
        right_x = np.asarray(right_x, dtype=float)
        right_y = np.asarray(right_y, dtype=float)

    # ---- 输入校验 ----
    if left_x.ndim != 1 or len(left_x) < 4:
        raise ValueError(f"左段点数过少（{len(left_x)}），至少 4 个")
    if not np.all(np.diff(left_x) > 0):
        raise ValueError("左段 X 必须严格递增")
    if has_right:
        if right_x.ndim != 1 or len(right_x) < 4:
            raise ValueError(f"右段点数过少（{len(right_x)}），至少 4 个")
        if not np.all(np.diff(right_x) > 0):
            raise ValueError("右段 X 必须严格递增")
    if len(ctrl_x) < k:
        raise ValueError(f"中段控制点数（{len(ctrl_x)}）少于阶数 k={k}")
    if continuity not in ("C1", "C2"):
        raise ValueError(f"continuity 必须是 'C1' 或 'C2'，得到 {continuity!r}")
    # 阶数要求：双端约束总数 = 2*C = k-1，故 C1→k≥3，C2→k≥5
    required_k = 5 if continuity == "C2" else 3
    if k < required_k:
        raise ValueError(
            f"{continuity} 双端连续性要求 B 样条阶数 k ≥ {required_k}，得到 k={k}"
        )

    r1_x = float(left_x[-1])
    r1_y = float(left_y[-1])

    if has_right:
        r2_x = float(right_x[0])
        r2_y = float(right_y[0])
        if r2_x <= r1_x:
            raise ValueError(f"R2 ({r2_x}) 必须大于 R1 ({r1_x})")
    else:
        # 退化情形：R2 = ctrl 末点或 1.0（取控制点末点 + 一点点，用于采样）
        r2_x = float(ctrl_x[-1]) if len(ctrl_x) else 1.0
        r2_y = float(ctrl_y[-1]) if len(ctrl_y) else 0.0

    # 控制点必须严格递增 + 落在 (R1, R2) 开区间内
    if not np.all(np.diff(ctrl_x) > 0):
        raise ValueError("中段控制点 X 必须严格递增")
    if np.any(ctrl_x <= r1_x) or (has_right and np.any(ctrl_x >= r2_x)):
        raise ValueError(
            f"中段控制点 X 必须全部在 ({r1_x}, {r2_x}) 开区间内"
        )

    # ---- 1. 求两个分段点处的导数（局部三次样条） ----
    n_tail = min(tail_points, len(left_x))
    r1_dy, r1_ddy = _endpoint_derivatives(
        left_x[-n_tail:], left_y[-n_tail:], r1_x
    )

    if has_right:
        n_head = min(tail_points, len(right_x))
        # CubicSpline 支持任意点求导，直接传右段开头 n_head 个点 + 求首点处导数
        r2_dy, r2_ddy = _endpoint_derivatives(
            right_x[:n_head], right_y[:n_head], r2_x
        )
    else:
        # 退化情形：右端不约束（下方 bc_type 用 None）
        r2_dy = 0.0
        r2_ddy = 0.0

    # ---- 2. 构造 make_interp_spline 的边界约束 ----
    #    scipy 要求 len(left) + len(right) == k - 1（不是 ≤）
    #      - C2 双端：左 2 + 右 2 = 4 → k = 5 ✓
    #      - C2 退化（无右段）：左 2 + 右 (k-3) 个零导数 = k-1
    #        右端的零导数约束（二阶/三阶/...）= "自然边界"近似
    #      - C1 双端：左 1 + 右 1 = 2 → k = 3 ✓
    #      - C1 退化：左 1 + 右 (k-2) 个零导数 = k-1
    if continuity == "C2":
        left_bc = [(1, r1_dy), (2, r1_ddy)]
        if has_right:
            right_bc = [(1, r2_dy), (2, r2_ddy)]
        else:
            # 退化：右端补 (k-3) 个零导数（k=5 时 [(2,0),(3,0)]）
            # range(2, k-1) = [2, 3, ..., k-2]，共 k-3 个
            right_bc = [(i, 0.0) for i in range(2, k - 1)]
            if not right_bc:
                right_bc = None  # k=3 时 range(2,2) 为空，让 scipy 用 not-a-knot
    else:  # C1
        left_bc = [(1, r1_dy)]
        if has_right:
            right_bc = [(1, r2_dy)]
        else:
            # 退化：右端补 (k-2) 个零导数
            right_bc = [(i, 0.0) for i in range(2, k)]
            if not right_bc:
                right_bc = None
    bc_type = (left_bc, right_bc)

    # ---- 3. 中段 B 样条拟合 ----
    # 完整控制点 = [R1] + ctrl + ([R2] 若 has_right)
    if has_right:
        full_ctrl_x = np.concatenate([[r1_x], ctrl_x, [r2_x]])
        full_ctrl_y = np.concatenate([[r1_y], ctrl_y, [r2_y]])
    else:
        full_ctrl_x = np.concatenate([[r1_x], ctrl_x])
        full_ctrl_y = np.concatenate([[r1_y], ctrl_y])

    spline = make_interp_spline(full_ctrl_x, full_ctrl_y, k=k, bc_type=bc_type)

    # ---- 4. 中段采样（不含 R1/R2 端点，避免与左右段重叠） ----
    if middle_resolution is None:
        middle_resolution = max(80, len(full_ctrl_x) * 15)
    # has_right: (R1, R2) 开区间采样；退化: (R1, full_ctrl_x[-1]] 半开
    if has_right:
        middle_x = np.linspace(r1_x, r2_x, middle_resolution)[1:-1]
    else:
        middle_x = np.linspace(r1_x, full_ctrl_x[-1], middle_resolution)[1:]
    middle_y = spline(middle_x)

    # ---- 5. 合并三段 ----
    pieces_x = [left_x, middle_x]
    pieces_y = [left_y, middle_y]
    if has_right:
        pieces_x.append(right_x)
        pieces_y.append(right_y)
    full_x = np.concatenate(pieces_x)
    full_y = np.concatenate(pieces_y)

    # 退化情形：把中段右端实际的 y'/y'' 填回 r2_dy/ddy（来自 spline 自身，供 UI 展示）
    if not has_right and len(full_ctrl_x) >= 2:
        r2_x_real = float(full_ctrl_x[-1])
        r2_y_real = float(full_ctrl_y[-1])
        r2_dy = float(spline(r2_x_real, 1))
        r2_ddy = float(spline(r2_x_real, 2))
        # 退化情形下 r2_x/y 用控制点末点（即原叶尖），UI 上显示"自由端"
        r2_x = r2_x_real
        r2_y = r2_y_real

    return SegmentedMiddleFitResult(
        left_x=left_x,
        left_y=left_y,
        middle_x=middle_x,
        middle_y=middle_y,
        right_x=(right_x if has_right else np.array([], dtype=float)),
        right_y=(right_y if has_right else np.array([], dtype=float)),
        full_x=full_x,
        full_y=full_y,
        r1_x=r1_x,
        r1_y=r1_y,
        r1_dy=r1_dy,
        r1_ddy=r1_ddy,
        r2_x=r2_x,
        r2_y=r2_y,
        r2_dy=r2_dy,
        r2_ddy=r2_ddy,
        has_right=has_right,
        continuity=continuity,
        k=k,
        spline=spline,
    )


def make_default_middle_ctrl(
    r1_x: float,
    r2_x: float,
    r1_y: float,
    r2_y_hint: float | None,
    n_points: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """生成中段初始控制点（等距 X，Y 从 R1 线性过渡到 R2）。

    返回的 **不含** R1/R2 端点（端点由 ``fit_middle_segment`` 内部前置/后置）。

    Parameters
    ----------
    r1_x, r2_x : float
        R1 与 R2 的 X 值。要求 ``r2_x > r1_x``。
    r1_y : float
        R1 处 Y（锁定，来自左段末点）。
    r2_y_hint : float or None
        R2 处 Y 目标值。None 时取 ``r1_y``（中段水平）。
    n_points : int
        中段控制点数（不含 R1/R2 端点），默认 5。最少 2。
    """
    if n_points < 2:
        raise ValueError("中段控制点数至少 2")
    if r2_x <= r1_x:
        raise ValueError(f"r2_x ({r2_x}) 必须大于 r1_x ({r1_x})")
    r2_y_hint = float(r1_y) if r2_y_hint is None else float(r2_y_hint)
    # 在 (r1_x, r2_x) 内 n_points 等距分布（不含端点）
    # linspace(r1, r2, n+1)[1:] 会包含 r2，不行；用 linspace(r1, r2, n+2)[1:-1]
    ctrl_x = np.linspace(r1_x, r2_x, n_points + 2)[1:-1]
    # Y 在 [r1_y, r2_y_hint] 之间线性插值（端点不返回，但用于斜率）
    full_y = np.linspace(r1_y, r2_y_hint, n_points + 2)
    ctrl_y = full_y[1:-1]
    return ctrl_x, ctrl_y
