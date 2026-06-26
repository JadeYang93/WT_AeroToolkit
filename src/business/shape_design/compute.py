"""Core geometry generation for MATLAB P7 shape design."""

from __future__ import annotations

import numpy as np

from .models import AirfoilProfileSet, ShapeDesignInput, ShapeDesignOptions, ShapeDesignResult


def _interp_profile(x: np.ndarray, y: np.ndarray, x_new: np.ndarray, order: int) -> np.ndarray:
    """Interpolate like MATLAB spapi(2/3) where practical."""

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    x_new = np.asarray(x_new, dtype=float)
    sorter = np.argsort(x)
    x_sorted = x[sorter]
    y_sorted = y[sorter]
    unique_x, unique_idx = np.unique(x_sorted, return_index=True)
    unique_y = y_sorted[unique_idx]
    if len(unique_x) < 3 or order <= 2:
        return np.interp(x_new, unique_x, unique_y)
    try:
        from scipy.interpolate import make_interp_spline

        spline = make_interp_spline(unique_x, unique_y, k=2)
        return np.asarray(spline(x_new), dtype=float)
    except Exception:
        return np.interp(x_new, unique_x, unique_y)


def _sample_geo(geo: np.ndarray, sections: np.ndarray) -> np.ndarray:
    span = geo[:, 0]
    chord = _interp_profile(span, geo[:, 1], sections, order=2)
    twist = _interp_profile(span, geo[:, 2], sections, order=3)
    thickness = _interp_profile(span, geo[:, 3], sections, order=2)
    pitchaxis = _interp_profile(span, geo[:, 4], sections, order=2)
    preb = _interp_profile(span, geo[:, 5], sections, order=3)
    return np.column_stack([sections, chord, twist, thickness, pitchaxis, preb])


def _build_bladed_geo(geo: np.ndarray) -> np.ndarray:
    end = float(geo[-1, 0])
    root = np.arange(0.0, 2.0 + 0.5, 0.5)
    middle = np.arange(3.0, min(30.0, end) + 1.0, 1.0)
    tip_base = np.arange(31.0, max(31.0, end - 1.0), 2.0)
    tip = np.array([end - 0.8, end - 0.6, end - 0.4, end - 0.2, end], dtype=float)
    sections = np.concatenate([root, middle, tip_base, tip])
    sections = np.unique(sections[(sections >= geo[0, 0]) & (sections <= end)])
    return _sample_geo(geo, sections)


def _interpolate_airfoils(profiles: AirfoilProfileSet, target_thickness: np.ndarray) -> np.ndarray:
    std_thick = np.asarray(profiles.thickness, dtype=float)
    std_y = np.asarray(profiles.y, dtype=float)
    y_foil = np.zeros((len(profiles.x), len(target_thickness)), dtype=float)

    for col, rtx in enumerate(target_thickness):
        # Match the original MATLAB branch structure exactly:
        # - first interval uses foil 1 and 2 when rtx >= thickness(2)
        # - inner intervals use k and k+1
        # - if no interval matches, keep the preallocated zeros
        for idx in range(1, len(std_thick) - 1):
            if rtx >= std_thick[1]:
                denom = std_thick[0] - std_thick[1]
                ratio = (rtx - std_thick[1]) / denom if abs(denom) > 1e-12 else 0.0
                y_foil[:, col] = ratio * (std_y[:, 0] - std_y[:, 1]) + std_y[:, 1]
            elif rtx < std_thick[idx] and rtx >= std_thick[idx + 1]:
                denom = std_thick[idx] - std_thick[idx + 1]
                ratio = (rtx - std_thick[idx + 1]) / denom if abs(denom) > 1e-12 else 0.0
                y_foil[:, col] = ratio * (std_y[:, idx] - std_y[:, idx + 1]) + std_y[:, idx + 1]
    return y_foil


def _standard_points(x: np.ndarray, y_foil: np.ndarray) -> np.ndarray:
    n_points, n_sections = y_foil.shape
    mid = n_points // 2
    std_points = np.zeros((n_points + 2, 2 * n_sections), dtype=float)
    std_x = np.concatenate([[1.0], x[:mid], [0.0], x[mid + 1 :], [1.0]])

    for idx in range(n_sections):
        std_y = np.concatenate([[0.0], y_foil[:mid, idx], [0.0], y_foil[mid + 1 :, idx], [0.0]])
        std_points[:, 2 * idx] = std_x
        std_points[:, 2 * idx + 1] = std_y
    return std_points


def _build_real_points(
    profile_x: np.ndarray,
    y_foil: np.ndarray,
    sampled_geo: np.ndarray,
    sweep: np.ndarray | None = None,
) -> tuple:
    x_span = sampled_geo[:, 0]
    chord = sampled_geo[:, 1]
    twist = sampled_geo[:, 2]
    pitchaxis = sampled_geo[:, 4]
    preb = sampled_geo[:, 5]
    sweep = np.zeros_like(x_span) if sweep is None else np.asarray(sweep, dtype=float)

    n_points = len(profile_x)
    n_sections = len(x_span)
    real_x = np.zeros((n_points, n_sections), dtype=float)
    real_y = np.zeros((n_points, n_sections), dtype=float)
    real_z = np.zeros((n_points, n_sections), dtype=float)
    b_x = np.zeros_like(real_x)
    b_y = np.zeros_like(real_y)

    for idx in range(n_sections):
        b_x[:, idx] = chord[idx] * (profile_x - pitchaxis[idx] / 100.0)
        b_y[:, idx] = y_foil[:, idx] * chord[idx]
        rad = np.deg2rad(twist[idx])
        t_x = b_x[:, idx] * np.cos(rad) - b_y[:, idx] * np.sin(rad)
        t_y = b_x[:, idx] * np.sin(rad) + b_y[:, idx] * np.cos(rad)
        real_x[:, idx] = -(t_x + sweep[idx]) * 1000.0
        real_y[:, idx] = (t_y + preb[idx]) * 1000.0
        real_z[:, idx] = x_span[idx] * 1000.0

    real_points = np.zeros((n_points, 3 * n_sections), dtype=float)
    for idx in range(n_sections):
        real_points[:, 3 * idx : 3 * idx + 3] = np.column_stack(
            [real_x[:, idx], real_y[:, idx], real_z[:, idx]]
        )

    return b_x, b_y, real_x, real_y, real_z, real_points


def build_result_from_airfoil_points(
    sampled_geo: np.ndarray,
    profile_x: np.ndarray,
    y_foil: np.ndarray,
    standard_points: np.ndarray,
    source_geo: np.ndarray | None = None,
    bladed_geo: np.ndarray | None = None,
    sweep: np.ndarray | None = None,
    station_labels: list[str] | None = None,
) -> ShapeDesignResult:
    """Build a normal result object from already prepared section airfoils."""

    sampled_geo = np.asarray(sampled_geo, dtype=float)
    profile_x = np.asarray(profile_x, dtype=float)
    y_foil = np.asarray(y_foil, dtype=float)
    standard_points = np.asarray(standard_points, dtype=float)
    source_geo = sampled_geo if source_geo is None else np.asarray(source_geo, dtype=float)
    bladed_geo = sampled_geo if bladed_geo is None else np.asarray(bladed_geo, dtype=float)

    b_x, b_y, real_x, real_y, real_z, real_points = _build_real_points(profile_x, y_foil, sampled_geo, sweep)
    tail_distribution = _tail_distribution(profile_x, y_foil, sampled_geo, b_x, b_y)
    return ShapeDesignResult(
        source_geo=source_geo,
        sampled_geo=sampled_geo,
        bladed_geo=bladed_geo,
        section_airfoils=y_foil,
        standard_points=standard_points,
        real_points=real_points,
        real_x=real_x,
        real_y=real_y,
        real_z=real_z,
        tail_distribution=tail_distribution,
        sweep=None if sweep is None else np.asarray(sweep, dtype=float),
        station_labels=station_labels,
    )


def _tail_distribution(profile_x: np.ndarray, y_foil: np.ndarray, sampled_geo: np.ndarray, b_x, b_y) -> np.ndarray:
    n_sections = sampled_geo.shape[0]
    tail = np.zeros((n_sections, 5), dtype=float)
    for idx in range(n_sections):
        rel = np.hypot(profile_x[0] - profile_x[-1], y_foil[0, idx] - y_foil[-1, idx])
        actual = np.hypot(b_x[0, idx] - b_x[-1, idx], b_y[0, idx] - b_y[-1, idx]) * 1000.0
        tail[idx] = [
            sampled_geo[idx, 0],
            rel,
            actual,
            b_y[0, idx] * 1000.0,
            b_y[-1, idx] * 1000.0,
        ]
    return tail


def build_shape_design(data: ShapeDesignInput, options: ShapeDesignOptions | None = None) -> ShapeDesignResult:
    """Compute blade shape design data from GEO and airfoil profiles."""

    options = options or ShapeDesignOptions()
    geo = np.asarray(data.geo, dtype=float)
    if geo.ndim != 2 or geo.shape[1] < 7:
        raise ValueError(
            "geo must have 7 columns: span, chord, twist, thickness, pitchaxis, prebend, sweep"
        )

    if options.interpolation_mode != "direct":
        raise NotImplementedError("Only direct airfoil interpolation is implemented; xfoil mode is reserved.")
    if options.tail_correction_enabled or options.thick_correction_enabled:
        raise NotImplementedError("XFOIL-based tail/thickness correction is reserved for the external xfoil workflow.")

    # sweep 列（geo 第 7 列），用 spapi(3) 风格样条插值到目标 sections（与预弯同阶）
    span_geo = geo[:, 0]
    sweep_col = geo[:, 6]
    sections_full = geo[:, 0] if options.use_original_sections or data.sections is None else np.asarray(data.sections, dtype=float)
    sections_full = sections_full[(sections_full >= geo[0, 0]) & (sections_full <= geo[-1, 0])]
    sweep_sampled = _interp_profile(span_geo, sweep_col, sections_full, order=3)

    geo = geo[:, :6]
    sections = geo[:, 0] if options.use_original_sections or data.sections is None else np.asarray(data.sections, dtype=float)
    sections = sections[(sections >= geo[0, 0]) & (sections <= geo[-1, 0])]
    sampled_geo = _sample_geo(geo, sections)
    bladed_geo = _build_bladed_geo(geo)
    y_foil = _interpolate_airfoils(data.profiles, sampled_geo[:, 3])
    std_points = _standard_points(data.profiles.x, y_foil)
    return build_result_from_airfoil_points(
        sampled_geo=sampled_geo,
        profile_x=data.profiles.x,
        y_foil=y_foil,
        standard_points=std_points,
        source_geo=geo,
        bladed_geo=bladed_geo,
        sweep=sweep_sampled,
    )
