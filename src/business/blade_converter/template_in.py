#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
模板.in文件处理模块

处理aeroinfo.in, pcoeffs.in, spcurve.in, steadyop.in, modal.in文件的修改
"""

import re
from pathlib import Path
import pandas as pd


def update_template_files(template_folder, focus2blade_file):
    """更新模板文件夹中的所有.in文件

    Args:
        template_folder: 模板文件夹路径
        focus2blade_file: focus2blade.xlsx文件路径

    Returns:
        dict: {文件名: 备份文件路径}， 失败返回None
    """
    try:
        template_folder = Path(template_folder)
        focus2blade_file = Path(focus2blade_file)

        # 读取focus2blade数据
        df_focus2blade = pd.read_excel(focus2blade_file)

        # 备份字典
        backup_files = {}

        # 处理aeroinfo.in
        aeroinfo_file = template_folder / "aeroinfo.in"
        if aeroinfo_file.exists():
            backup = _backup_file(aeroinfo_file)
            backup_files['aeroinfo.in'] = backup
            _update_aeroinfo_file(aeroinfo_file, df_focus2blade)

        # 处理pcoeffs.in
        pcoeffs_file = template_folder / "pcoeffs.in"
        if pcoeffs_file.exists():
            backup = _backup_file(pcoeffs_file)
            backup_files['pcoeffs.in'] = backup
            _update_pcoeffs_file(pcoeffs_file, df_focus2blade)

        # 处理spcurve.in
        spcurve_file = template_folder / "spcurve.in"
        if spcurve_file.exists():
            backup = _backup_file(spcurve_file)
            backup_files['spcurve.in'] = backup
            _update_spcurve_file(spcurve_file, df_focus2blade)

        # 处理steadyop.in
        steadyop_file = template_folder / "steadyop.in"
        if steadyop_file.exists():
            backup = _backup_file(steadyop_file)
            backup_files['steadyop.in'] = backup
            _update_steadyop_file(steadyop_file, df_focus2blade)

        # 处理modal.in
        modal_file = template_folder / "modal.in"
        if modal_file.exists():
            backup = _backup_file(modal_file)
            backup_files['modal.in'] = backup
            _update_modal_file(modal_file, df_focus2blade)

        return backup_files

    except Exception as e:
        raise Exception(f"更新模板文件失败: {str(e)}")


def _backup_file(file_path):
    """备份文件

    Args:
        file_path: 文件路径

    Returns:
        Path: 备份文件路径
    """
    backup_path = file_path.parent / f"{file_path.stem}_backup{file_path.suffix}"
    import shutil
    shutil.copy2(file_path, backup_path)
    return backup_path


def _generate_expanded_data(data_list):
    """生成扩展的数据列表（首尾不重复，中间重复一次）

    Args:
        data_list: 原始数据列表

    Returns:
        list: 扩展后的数据列表
    """
    if len(data_list) <= 2:
        # 如果只有1-2个数据，直接返回不重复
        return data_list

    result = []

    # 第一个数据不重复
    result.append(data_list[0])

    # 中间数据重复一次
    for i in range(1, len(data_list) - 1):
        result.append(data_list[i])
        result.append(data_list[i])

    # 最后一个数据不重复
    result.append(data_list[-1])

    return result


def _update_aeroinfo_file(file_path, df_focus2blade):
    """更新aeroinfo.in文件

    修改字段：REF_X, REF_Y, CE_X, CE_Y
    """
    from .bc_config import PRJ_FIELD_MAPPING

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 字段映射：in文件中的列名 -> focus2blade中的列名
    field_mapping = {
        'REF_X': PRJ_FIELD_MAPPING['REF_X'],
        'REF_Y': PRJ_FIELD_MAPPING['REF_Y'],
        'CE_X': PRJ_FIELD_MAPPING['CE_X'],
        'CE_Y': PRJ_FIELD_MAPPING['CE_Y'],
    }

    # 更新每一行
    for field_name, focus2blade_col in field_mapping.items():
        content = _update_field_line(content, field_name, df_focus2blade[focus2blade_col].tolist())

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def _update_pcoeffs_file(file_path, df_focus2blade):
    """更新pcoeffs.in文件

    修改字段：REF_X, REF_Y, CE_X, CE_Y
    """
    from .bc_config import PRJ_FIELD_MAPPING

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 字段映射
    field_mapping = {
        'REF_X': PRJ_FIELD_MAPPING['REF_X'],
        'REF_Y': PRJ_FIELD_MAPPING['REF_Y'],
        'CE_X': PRJ_FIELD_MAPPING['CE_X'],
        'CE_Y': PRJ_FIELD_MAPPING['CE_Y'],
    }

    # 更新每一行
    for field_name, focus2blade_col in field_mapping.items():
        content = _update_field_line(content, field_name, df_focus2blade[focus2blade_col].tolist())

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def _update_spcurve_file(file_path, df_focus2blade):
    """更新spcurve.in文件

    修改字段：REF_X, REF_Y, CE_X, CE_Y
    """
    from .bc_config import PRJ_FIELD_MAPPING

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 字段映射
    field_mapping = {
        'REF_X': PRJ_FIELD_MAPPING['REF_X'],
        'REF_Y': PRJ_FIELD_MAPPING['REF_Y'],
        'CE_X': PRJ_FIELD_MAPPING['CE_X'],
        'CE_Y': PRJ_FIELD_MAPPING['CE_Y'],
    }

    # 更新每一行
    for field_name, focus2blade_col in field_mapping.items():
        content = _update_field_line(content, field_name, df_focus2blade[focus2blade_col].tolist())

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def _update_steadyop_file(file_path, df_focus2blade):
    """更新steadyop.in文件

    修改所有17个字段（与prj文件相同）
    """
    from .bc_config import PRJ_FIELD_MAPPING

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 更新每一行
    for field_name, focus2blade_col in PRJ_FIELD_MAPPING.items():
        content = _update_field_line(content, field_name, df_focus2blade[focus2blade_col].tolist())

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def _update_modal_file(file_path, df_focus2blade):
    """更新modal.in文件

    修改所有17个字段（与steadyop文件相同）
    """
    from .bc_config import PRJ_FIELD_MAPPING

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 更新每一行
    for field_name, focus2blade_col in PRJ_FIELD_MAPPING.items():
        content = _update_field_line(content, field_name, df_focus2blade[focus2blade_col].tolist())

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def _update_field_line(content, field_name, data_list):
    """更新文件中的特定字段行

    Args:
        content: 文件内容
        field_name: 字段名称（如 REF_X）
        data_list: 数据列表（从focus2blade读取）

    Returns:
        str: 更新后的文件内容
    """
    # 生成扩展的数据（首尾不重复，中间重复）
    expanded_data = _generate_expanded_data(data_list)

    # 查找字段行
    # 格式：REF_X ...
    pattern = rf'^{field_name}\s+.+$'

    lines = content.split('\n')
    updated_lines = []

    for line in lines:
        if re.match(pattern, line, re.IGNORECASE):
            # 找到字段行，替换数据
            # 保持原有格式，只替换数据部分
            parts = line.split()
            if len(parts) > 1:
                # 保留字段名
                new_line = field_name

                # 添加数据（科学计数法格式）
                for value in expanded_data:
                    new_line += f" {value:.6e}"

                updated_lines.append(new_line)
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    return '\n'.join(updated_lines)
