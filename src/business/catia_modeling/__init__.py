# -*- coding: utf-8 -*-
"""CATIA 叶片建模业务子包。

对外公共 API:
    CatiaContext, CatiaModelError 及各子异常
    SectionParams, build_sections
    ResampleParams, resample_and_smooth
    LoftParams, build_loft_surface
    load_params, save_params
"""
from .exceptions import (
    CatiaModelError, CatiaNotRunningError, NoActiveDocumentError,
    WrongDocumentTypeError, GeoSetNotFoundError, PointNamingError,
)
from .params_store import load_params, save_params
from .context import CatiaContext
from .sections import SectionParams, build_sections
from .resample import ResampleParams, resample_and_smooth
from .loft import LoftParams, build_loft_surface

__all__ = [
    'CatiaContext', 'CatiaModelError', 'CatiaNotRunningError',
    'NoActiveDocumentError', 'WrongDocumentTypeError',
    'GeoSetNotFoundError', 'PointNamingError',
    'load_params', 'save_params',
    'SectionParams', 'build_sections',
    'ResampleParams', 'resample_and_smooth',
    'LoftParams', 'build_loft_surface',
]
