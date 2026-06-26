"""
curve_fit.py - Curve Fitter 业务逻辑（纯算法，无 PyQt5 / matplotlib）

从 pyqt_curve_fitter11.py 的 ``PyQtCurveFitter`` 类中提取核心算法，
包含数据解析、多方法曲线拟合和插值计算。

支持的拟合方法：
    - 'spline' : B 样条 (UnivariateSpline + splrep/splev)
    - 'cubic'  : 三次样条 (CubicSpline)
    - 'akima'  : Akima 插值 (Akima1DInterpolator)
    - 'pchip'  : PCHIP 插值 (PchipInterpolator)
    - 'poly'   : 多项式拟合 (np.polyfit / np.poly1d)
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

import numpy as np
from scipy.interpolate import (
    UnivariateSpline,
    CubicSpline,
    Akima1DInterpolator,
    PchipInterpolator,
)
from scipy.interpolate import splrep, splev

__all__ = [
    "parse_data",
    "generate_curve",
    "calculate_interpolation",
    "MAX_ROWS",
]

#: 最大允许数据行数（与源码一致）
MAX_ROWS: int = 10000


# ---------------------------------------------------------------------------
# 数据解析
# ---------------------------------------------------------------------------

def parse_data(
    text: str,
    max_rows: int = MAX_ROWS,
) -> Tuple[np.ndarray, List[str]]:
    """解析多列文本数据。

    将用户粘贴 / 从文件读入的文本解析成二维 ``numpy`` 数组。
    第 1 列为 X，后续列为 Y1, Y2, ... Yn。

    解析规则（与原始 GUI 行为一致）：

    * 以 ``#`` 开头的行视为注释，跳过。
    * 空行跳过。
    * 每行用正则 ``\\s+`` 分割（兼容空格 / Tab / 逗号写入后的空白）。
    * 数值中的英文逗号千位分隔符会被删除（``replace(',', '')``）。
    * BOM 字符 ``\\ufeff`` 会被移除。
    * 列数必须一致，否则该行跳过。

    Parameters
    ----------
    text : str
        原始文本内容。
    max_rows : int, optional
        最大允许的有效数据行数，默认 :data:`MAX_ROWS`。

    Returns
    -------
    data : np.ndarray
        形状 ``(n_rows, n_cols)`` 的二维数组，``n_cols >= 2``。
    column_labels : list[str]
        列标签，如 ``["X", "Y1", "Y2"]``。

    Raises
    ------
    ValueError
        数据为空、行数超限或有效行不足时抛出。
    """
    # 移除 BOM
    if text.startswith("\ufeff"):
        text = text[1:]

    if not text.strip():
        raise ValueError("输入数据为空")

    lines = text.strip().split("\n")
    # 统计有效行
    effective_lines = [
        ln for ln in lines if ln.strip() and not ln.strip().startswith("#")
    ]
    num_lines = len(effective_lines)

    if num_lines > max_rows:
        raise ValueError(
            f"数据行数({num_lines})超过最大限制({max_rows})，请减少数据量或分批处理"
        )

    data: List[List[float]] = []
    error_lines: List[str] = []
    num_cols_expected: int | None = None

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue

        # 正则按任意空白字符分割
        parts = re.split(r"\s+", line)
        if len(parts) >= 2:
            try:
                row: List[float] = []
                for part in parts:
                    part_clean = part.strip().replace(",", "")
                    val = float(part_clean)
                    row.append(val)

                if num_cols_expected is None:
                    num_cols_expected = len(row)
                elif len(row) != num_cols_expected:
                    error_lines.append(str(i))
                    continue

                data.append(row)
            except ValueError:
                error_lines.append(str(i))
                continue
        else:
            error_lines.append(str(i))
            continue

    if not data:
        raise ValueError("未解析到有效数据")

    arr = np.array(data)
    _, num_cols = arr.shape

    if num_cols < 2:
        raise ValueError("数据至少需要2列（1个x列和至少1个y列）")

    labels = ["X"] + [f"Y{i+1}" for i in range(num_cols - 1)]
    return arr, labels


# ---------------------------------------------------------------------------
# 曲线拟合
# ---------------------------------------------------------------------------

def generate_curve(
    x: np.ndarray,
    y_cols: np.ndarray,
    method: str,
    smooth: float = 0.0,
    poly_deg: int = 3,
    n_points: int = 1000,
) -> Dict[str, np.ndarray]:
    """对一列 X 和一至多列 Y 执行曲线拟合，返回拟合曲线。

    内部会先对 X 排序，再根据 ``method`` 选择对应的 scipy 插值器。
    拟合结果用 ``n_points`` 个均匀采样点表示。

    Parameters
    ----------
    x : np.ndarray, shape (n,)
        一维 X 数据（无需排序，函数内部会排序）。
    y_cols : np.ndarray
        Y 数据，可以是 ``(n,)`` 或 ``(n, k)``。
        单列时使用一维数组即可；多列时第二维对应第 i 条曲线。
    method : str
        拟合方法，取值之一：
        ``'spline'`` / ``'cubic'`` / ``'akima'`` / ``'pchip'`` / ``'poly'``。
    smooth : float, default 0.0
        B 样条平滑因子 ``s``，仅 ``method='spline'`` 时使用。
        ``s=0`` 精确插值；``s>0`` 平滑度递增。
    poly_deg : int, default 3
        多项式阶数，仅 ``method='poly'`` 时使用。
    n_points : int, default 1000
        拟合曲线的采样点数。当原始数据 > 1000 点时，源码会自动降至 500；
        此参数允许调用方显式指定，默认与源码一致。

    Returns
    -------
    dict[str, np.ndarray]
        键格式 ``"{method}_y{col_index}"`` （单列时为 ``"{method}_y1"``），
        值为形状 ``(n_points,)`` 的拟合曲线 Y 值数组。
        拟合失败的列不会出现在返回字典中。

    Raises
    ------
    ValueError
        ``method`` 不在支持列表时抛出。
    """
    valid_methods = {"spline", "cubic", "akima", "pchip", "poly"}
    if method not in valid_methods:
        raise ValueError(
            f"不支持的插值方法 '{method}'，可选: {sorted(valid_methods)}"
        )

    x = np.asarray(x, dtype=float).ravel()
    y_2d = np.atleast_2d(np.asarray(y_cols, dtype=float))
    if y_2d.shape[0] == 1 and y_2d.shape[1] != x.shape[0]:
        # 用户传入 (n, k) 形式
        y_2d = y_2d.T
    if y_2d.shape[0] != x.shape[0]:
        # 尝试转置
        if y_2d.shape[1] == x.shape[0]:
            y_2d = y_2d.T
        else:
            raise ValueError(
                f"y_cols 行数({y_2d.shape[0]}) 与 x 长度({x.shape[0]}) 不匹配"
            )

    n_y_cols = y_2d.shape[1]

    # X 排序
    sorted_indices = np.argsort(x)
    sorted_x = x[sorted_indices]

    # 大数据量时减少采样点（与源码逻辑一致）
    n_data = len(sorted_x)
    interp_points = 500 if n_data > 1000 else n_points

    x_new = np.linspace(sorted_x.min(), sorted_x.max(), interp_points)
    results: Dict[str, np.ndarray] = {}

    for col_idx in range(n_y_cols):
        sorted_y = y_2d[sorted_indices, col_idx]

        try:
            if method == "spline":
                spline = UnivariateSpline(sorted_x, sorted_y, s=smooth)
            elif method == "cubic":
                spline = CubicSpline(sorted_x, sorted_y)
            elif method == "akima":
                spline = Akima1DInterpolator(sorted_x, sorted_y)
            elif method == "pchip":
                spline = PchipInterpolator(sorted_x, sorted_y)
            elif method == "poly":
                coeffs = np.polyfit(sorted_x, sorted_y, poly_deg)
                spline = np.poly1d(coeffs)
            else:
                continue

            y_new = np.asarray(spline(x_new), dtype=float)
            key = f"{method}_y{col_idx + 1}"
            results[key] = y_new
        except Exception:
            # 拟合失败的列跳过
            continue

    return results


# ---------------------------------------------------------------------------
# 插值计算
# ---------------------------------------------------------------------------

def calculate_interpolation(
    x_orig: np.ndarray,
    y_fit: np.ndarray,
    x_targets: List[float],
    method: str = "spline",
    smooth: float = 0.0,
    poly_deg: int = 3,
) -> np.ndarray:
    """在用户指定的 X 位置对已拟合的曲线求值。

    此函数会基于 ``(x_orig, y_fit)`` 重新构建插值器，
    然后在 ``x_targets`` 上求值。

    Parameters
    ----------
    x_orig : np.ndarray, shape (n,)
        原始 X 数据。
    y_fit : np.ndarray, shape (n,)
        原始 Y 数据（与 ``x_orig`` 对应，来自同一列）。
    x_targets : list[float]
        需要求值的 X 坐标列表。
    method : str, default 'spline'
        拟合方法，与 :func:`generate_curve` 相同。
    smooth : float, default 0.0
        B 样条平滑因子（仅 ``method='spline'``）。
    poly_deg : int, default 3
        多项式阶数（仅 ``method='poly'``）。

    Returns
    -------
    np.ndarray, shape (len(x_targets),)
        插值结果，拟合失败的位置返回 ``NaN``。
    """
    targets = np.asarray(x_targets, dtype=float)
    x = np.asarray(x_orig, dtype=float).ravel()
    y = np.asarray(y_fit, dtype=float).ravel()

    if len(x) < 2:
        return np.full(len(targets), np.nan)

    # 排序
    order = np.argsort(x)
    sx, sy = x[order], y[order]

    try:
        if method == "spline":
            spline = UnivariateSpline(sx, sy, s=smooth)
        elif method == "cubic":
            spline = CubicSpline(sx, sy)
        elif method == "akima":
            spline = Akima1DInterpolator(sx, sy)
        elif method == "pchip":
            spline = PchipInterpolator(sx, sy)
        elif method == "poly":
            coeffs = np.polyfit(sx, sy, poly_deg)
            spline = np.poly1d(coeffs)
        else:
            return np.full(len(targets), np.nan)

        result = np.asarray(spline(targets), dtype=float)
        return result
    except Exception:
        return np.full(len(targets), np.nan)
