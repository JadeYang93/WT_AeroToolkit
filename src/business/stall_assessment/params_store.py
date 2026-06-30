# -*- coding: utf-8 -*-
"""失速评估输入参数的 JSON 持久化。

记住用户上次填入的全部输入（标准翼型表 / 展向分布 / 最大攻角分布 / VG 安装段），
下次打开面板时自动恢复，避免重复填写。

存储位置: <PROJECT_ROOT>/配置/stall_assessment_inputs.json
格式: {
    "profile": [[t, alpha_std, alpha_vg_or_None], ...],
    "span_text": "0.0, 100\n0.1, 85\n...",
    "aoa_text": "0.0, 0\n0.1, 5\n...",
    "vg_segments": [[zs, ze], ...]
}

容错: 文件缺失/损坏 → 返回 None（面板用代码里的默认值）。
"""
import json
import os
import tempfile

from config import PROJECT_ROOT


def _config_path():
    """返回 JSON 存储路径。<PROJECT_ROOT>/配置/stall_assessment_inputs.json"""
    return os.path.join(PROJECT_ROOT, '配置', 'stall_assessment_inputs.json')


def load_inputs():
    """读取上次保存的输入。文件缺失/损坏 → 返回 None（调用方用默认值）。"""
    path = _config_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_inputs(inputs):
    """原子写入输入参数。先写临时文件再 rename，避免中途崩溃损坏。

    Args:
        inputs: dict，键为 profile / span_text / aoa_text / vg_segments。
    """
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 原子写: 同目录临时文件 → os.replace
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(suffix='.json', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(inputs, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
