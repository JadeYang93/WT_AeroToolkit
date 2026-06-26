"""Data contracts for the standalone shape design module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class AirfoilProfileSet:
    """Standard airfoil coordinate family.

    Attributes
    ----------
    x:
        Common normalized x coordinates, shape ``(n_points,)``.
    y:
        Normalized y coordinates for each standard thickness,
        shape ``(n_points, n_foils)``.
    thickness:
        Standard relative thickness values in descending order,
        shape ``(n_foils,)``.
    source_dir:
        Optional directory used to load the profiles.
    """

    x: np.ndarray
    y: np.ndarray
    thickness: np.ndarray
    source_dir: Path | None = None


@dataclass(frozen=True)
class ShapeDesignInput:
    """Inputs required by MATLAB P7 shape design."""

    geo: np.ndarray
    profiles: AirfoilProfileSet
    sections: np.ndarray | None = None
    tail_table: np.ndarray | None = None


@dataclass(frozen=True)
class ShapeDesignOptions:
    """Runtime options for shape design generation."""

    use_original_sections: bool = True
    interpolation_mode: str = "direct"
    tail_correction_enabled: bool = False
    thick_correction_enabled: bool = False
    tail_factor: float = 0.5
    export_airfoil_points: bool = True
    export_3d_points: bool = True
    export_geometry: bool = True
    export_tail: bool = True
    export_focus: bool = True
    export_step_points: bool = False
    export_bladed: bool = False


@dataclass(frozen=True)
class ShapeDesignResult:
    """Computed output data before writing files."""

    source_geo: np.ndarray
    sampled_geo: np.ndarray
    bladed_geo: np.ndarray
    section_airfoils: np.ndarray
    standard_points: np.ndarray
    real_points: np.ndarray
    real_x: np.ndarray
    real_y: np.ndarray
    real_z: np.ndarray
    tail_distribution: np.ndarray
    sweep: np.ndarray | None = None
    station_labels: list[str] | None = None
