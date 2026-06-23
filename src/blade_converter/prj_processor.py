#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PRJ文件处理模块

提供PRJ文件的读取、解析和更新功能
"""

import re

from .bc_config import PRJ_FIELD_MAPPING


class PRJFileProcessor:
    """PRJ文件处理器"""

    @staticmethod
    def read_prj_file(file_path):
        """读取PRJ文件内容"""
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    @staticmethod
    def parse_field_line(line):
        """
        解析PRJ文件中的数据行
        格式：FIELDNAME\tvalue1, value2, value3, ...
        返回：(字段名, 值列表)
        """
        # 使用正则表达式匹配
        match = re.match(r'^([A-Z_]+)\s+(.+)$', line.strip())
        if match:
            field_name = match.group(1)
            values_str = match.group(2)
            # 解析数值列表
            values = [v.strip() for v in values_str.split(',')]
            return field_name, values
        return None, None

    @staticmethod
    def duplicate_values(values):
        """
        将每个数值重复一次
        例如：[1.0, 2.0, 3.0] -> [1.0, 1.0, 2.0, 2.0, 3.0, 3.0]
        """
        result = []
        for v in values:
            result.append(v)
            result.append(v)
        return result

    @staticmethod
    def format_values(values):
        """格式化数值列表为字符串"""
        # 过滤掉NaN
        filtered_values = [str(v) if str(v) != 'nan' else '0' for v in values]
        return ', '.join(filtered_values)

    @staticmethod
    def update_prj_file(prj_content, df_focus2blade, field_mapping=PRJ_FIELD_MAPPING):
        """
        更新PRJ文件内容

        Args:
            prj_content: PRJ文件内容
            df_focus2blade: focus2blade.xlsx数据的DataFrame（包含列名和单位行）
            field_mapping: 字段映射配置

        Returns:
            更新后的PRJ文件内容

        Note:
            focus2blade.xlsx格式：
            - 第1行：列名
            - 第2行：单位
            - 第3行开始：数据（从这一行开始读取）
        """
        lines = prj_content.split('\n')
        updated_lines = []

        for line in lines:
            field_name, values = PRJFileProcessor.parse_field_line(line)

            if field_name and field_name in field_mapping:
                # 获取对应的focus2blade列名
                column_name = field_mapping[field_name]

                if column_name in df_focus2blade.columns:
                    # 获取数据列（从第3行开始，即跳过前两行）
                    # df_focus2blade[2:] 表示从第3行开始读取
                    data_values = df_focus2blade[column_name].iloc[2:].values

                    # 将每个数值重复一次
                    duplicated_values = PRJFileProcessor.duplicate_values(data_values)

                    # 格式化数值
                    formatted_values = PRJFileProcessor.format_values(duplicated_values)

                    # 构建新行
                    new_line = f"{field_name}\t {formatted_values}"
                    updated_lines.append(new_line)
                else:
                    # 列不存在，保持原行
                    updated_lines.append(line)
            else:
                # 不是目标字段，保持原行
                updated_lines.append(line)

        return '\n'.join(updated_lines)
