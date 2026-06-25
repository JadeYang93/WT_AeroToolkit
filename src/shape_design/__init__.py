"""Standalone blade shape design module.

封装在气动组工具箱下，业务代码与 PyQt 解耦。XFOIL 默认路径固定指向
``src/_bin/xfoil.exe``（由 ``correction.py`` 计算）。
"""

from .compute import build_result_from_airfoil_points, build_shape_design
from .correction import (
    apply_pchip_te_continuity,
    apply_te_correction,
    build_result_from_corrected_files,
    prepare_correction_inputs,
    run_airfoil_correction,
)
from .exporters import export_shape_design, write_focus_file, write_step_points_file
from .loaders import load_airfoil_profiles, load_shape_design_input
from .models import (
    AirfoilProfileSet,
    ShapeDesignInput,
    ShapeDesignOptions,
    ShapeDesignResult,
)

__all__ = [
    "AirfoilProfileSet",
    "ShapeDesignInput",
    "ShapeDesignOptions",
    "ShapeDesignResult",
    "apply_pchip_te_continuity",
    "apply_te_correction",
    "build_shape_design",
    "build_result_from_airfoil_points",
    "build_result_from_corrected_files",
    "export_shape_design",
    "load_airfoil_profiles",
    "load_shape_design_input",
    "prepare_correction_inputs",
    "run_airfoil_correction",
    "write_focus_file",
    "write_step_points_file",
]
