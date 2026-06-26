# -*- coding: utf-8 -*-
"""CATIA 建模参数的 JSON 持久化。

独立于 ConfigCenter（后者为路径字段设计，带路径校验，不适合存数值参数）。

存储位置: <PROJECT_ROOT>/配置/catia_modeling_params.json
格式: {"sections": {...}, "resample": {...}, "loft": {...}, "input": {...}, "ui": {...}}

容错: 文件缺失/损坏 → 返回全默认值（不抛异常）。
"""
import json
import os
import tempfile

from config import PROJECT_ROOT

# 默认参数（与设计文档 3.5 表一致；几何集名统一 Z_* 体系默认串联）
DEFAULTS = {
    'sections': {
        'num_groups': 96,
        'start_group': 1,
        'smooth_thresholds': [4, 3, 2, 1],
        'points_per_section': 400,
        'le_point_num': 200,
        'te_point1_num': 1,
        'te_point399_num': 399,
        'tangency_threshold': 0.5,
        'correction_mode': 3,
        'spline_set': 'Z_Splines',
        'smooth_set': 'Z_Smooths',
        'plane_set': 'Z_Planes',
        'edge_set': 'Z_Edges',
        'te_set': 'Z_TrailingEdges',
    },
    'resample': {
        'source_set': 'Z_Smooths',
        'num_points': 149,
        'smooth_max_deviation': 1.0,
        'tangency_threshold': 0.5,
        'correction_mode': 3,
        'point_set': 'Z_ResamplePoints',
        'original_set': 'Z_OriginalSpline',
        'smooth_set': 'Z_ResampleSmooth',
    },
    'loft': {
        'source_set': 'Z_ResampleSmooth',
        'section_coupling': 1,
        'relimitation': 1,
        'canonical_detection': 2,
    },
    'input': {
        'stp_path': '',
    },
}


def _config_path():
    """返回 JSON 存储路径。<PROJECT_ROOT>/配置/catia_modeling_params.json

    PROJECT_ROOT 通过相对本文件向上回溯定位（src/catia_modeling/ → 项目根）。
    """
    # PROJECT_ROOT 由 config.py 统一定义，避免数层数反推
    return os.path.join(PROJECT_ROOT, '配置', 'catia_modeling_params.json')


def _deep_merge(base, override):
    """递归合并: override 的值覆盖 base，base 提供缺省键。"""
    result = {}
    for key, val in base.items():
        if isinstance(val, dict) and isinstance(override.get(key), dict):
            result[key] = _deep_merge(val, override[key])
        else:
            result[key] = override.get(key, val)
    # 保留 override 里 base 没有的键（向前兼容旧配置）
    for key in override:
        if key not in base:
            result[key] = override[key]
    return result


def load_params():
    """读取参数。文件缺失/损坏 → 返回全默认值的副本。"""
    path = _config_path()
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULTS))  # 深拷贝
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return json.loads(json.dumps(DEFAULTS))
        return _deep_merge(DEFAULTS, data)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULTS))


def save_params(params):
    """原子写入参数。先写临时文件再 rename，避免中途崩溃损坏。

    若传入 params 缺少某些键，用 DEFAULTS 补齐后写盘。
    """
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    full = _deep_merge(DEFAULTS, params)
    # 原子写: 同目录临时文件 → os.replace
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(suffix='.json', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(full, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
