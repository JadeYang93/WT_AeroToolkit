#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
blade_geometry.mac ↔ Excel 双向转换（纯函数版，剥离 QThread）

提供两个入口函数：
- ``convert_txt_to_excel(input_file, output_file, logger=None, open_output_folder=False)``
- ``convert_excel_to_txt(input_file, output_file, logger=None, open_output_folder=False)``

``logger`` 是可选的回调，签名 ``logger(msg: str) -> None``。
不传时静默执行。UI 层用这个回调把进度送到日志面板。
"""

import re
import subprocess
import platform
from pathlib import Path

import pandas as pd

from .bc_config import LOG_SEPARATOR
from .format_width import format_field, normalize_number_str


def _emit(logger, msg):
    """安全调用 logger 回调；None 时静默。"""
    if logger is not None:
        try:
            logger(msg)
        except Exception:
            pass


def _maybe_open_folder(output_path, logger):
    """跨平台打开输出文件夹（可选）。"""
    output_folder = Path(output_path).parent
    if platform.system() == 'Windows':
        subprocess.run(['explorer', str(output_folder)])
    elif platform.system() == 'Darwin':
        subprocess.run(['open', str(output_folder)])
    else:
        subprocess.run(['xdg-open', str(output_folder)])
    _emit(logger, f"\n已打开输出文件夹: {output_folder}")


def convert_txt_to_excel(input_file, output_file, logger=None, open_output_folder=False):
    """blade_geometry.mac → Excel 转换。

    Args:
        input_file: 输入 .mac 文件路径
        output_file: 输出 .xlsx 文件路径
        logger: 可选的日志回调 ``logger(msg: str)``
        open_output_folder: 是否完成后打开输出文件夹

    Returns:
        bool: 成功 True，失败 False（异常已记录到 logger）
    """
    try:
        _emit(logger, LOG_SEPARATOR)
        _emit(logger, "开始转换：blade_geometry.mac → Excel")

        # 1. 读取txt文件
        _emit(logger, "\n1. 读取 blade_geometry.mac...")
        txt_path = Path(input_file)
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        _emit(logger, f"   ✓ 读取了 {len(lines)} 行")

        # 2. 解析DEF PARA
        _emit(logger, "\n2. 解析 DEF PARA...")
        para_data = []
        for line in lines:
            s = line.strip()
            if s.startswith("DEF PARA"):
                parts = re.split(r"\s+", s)
                kv = parts[-1]
                if "=" in kv:
                    k, v = kv.split("=")
                    para_data.append([k.strip(), v.strip()])
        df_para = pd.DataFrame(para_data, columns=["Parameter", "Value"])
        _emit(logger, f"   ✓ 解析了 {len(para_data)} 个参数")

        # 3. 解析DEF SHAPE + POINTS
        _emit(logger, "\n3. 解析 DEF SHAPE + POINTS...")
        shape_point_groups = {}
        shape_centers = {}  # 存储center信息
        current_shape = None

        for line in lines:
            s = line.strip()
            if not s:
                continue

            if s.startswith("DEF SHAPE"):
                parts = re.split(r"\s+", s)
                shape_name = parts[2]
                cx = parts[3]
                cy = parts[4]
                current_shape = shape_name
                shape_centers[shape_name] = (cx, cy)
                shape_point_groups[shape_name] = []

            elif s.startswith("POINTS") and current_shape is not None:
                parts = re.split(r"\s+", s)
                x = float(parts[1])
                y = float(parts[2])
                shape_point_groups[current_shape].append((x, y))

            elif s.startswith("END SHAPE"):
                current_shape = None

        # 按列重组数据
        dfs_list = []
        for shape_name, points in shape_point_groups.items():
            df_single = pd.DataFrame({
                f"{shape_name}": [p[0] for p in points],  # X数据
                "Y": [p[1] for p in points]                # Y数据
            })
            dfs_list.append(df_single)

        df_final = pd.concat(dfs_list, axis=1, ignore_index=False)
        _emit(logger, f"   ✓ 解析了 {len(shape_point_groups)} 个形状")

        # 4. 解析PLACE SHAPE
        _emit(logger, "\n4. 解析 PLACE SHAPE...")
        place_list = []
        current_place = None

        for line in lines:
            s = line.strip()

            if s.startswith("PLACE SHAPE"):
                parts = re.split(r"\s+", s)
                shape_name = parts[2]
                current_place = {
                    "ShapeName": shape_name,
                    "Zpos": parts[3]
                }
                if shape_name in shape_centers:
                    current_place["CenterX"] = shape_centers[shape_name][0]
                    current_place["CenterY"] = shape_centers[shape_name][1]

            elif s.upper().startswith("ROTATION") and current_place:
                current_place["Rotation"] = s.replace("Rotation", "").replace("ROTATION", "").replace('/DG', '').strip()

            elif s.upper().startswith("TRANSLATION") and current_place:
                parts = re.split(r'\s+', s)
                for i, part in enumerate(parts):
                    if i > 0 and part.replace('.', '').replace('-', '').replace('e', '').replace('E', '').replace('+', '').isdigit():
                        current_place['TranslationX'] = part
                        current_place['TranslationY'] = parts[i+1] if i+1 < len(parts) else '0'
                        break

            elif s.upper().startswith("SCALE FACTORS") and current_place:
                parts = re.split(r'\s+', s)
                numeric_values = []
                for i, part in enumerate(parts):
                    test_part = part.replace('.', '').replace('-', '').replace('e', '').replace('E', '').replace('+', '')
                    if test_part.isdigit() and test_part != '':
                        numeric_values.append(part)
                        if len(numeric_values) == 2:
                            break
                if len(numeric_values) >= 2:
                    current_place['ScaleFactorsX'] = numeric_values[0]
                    current_place['ScaleFactorsY'] = numeric_values[1]
                elif len(numeric_values) == 1:
                    current_place['ScaleFactorsX'] = numeric_values[0]
                    current_place['ScaleFactorsY'] = numeric_values[0]

            elif s.startswith("END PLACE") and current_place:
                place_list.append(current_place)
                current_place = None

        df_place = pd.DataFrame(place_list)
        _emit(logger, f"   ✓ 解析了 {len(place_list)} 个放置定义")

        # 5. 解析DEF MATERIAL
        _emit(logger, "\n5. 解析 DEF MATERIAL...")
        material_list = []
        current_mat = None

        for line in lines:
            s = line.strip()

            if s.startswith("DEF MATERIAL"):
                parts = re.split(r"\s+", s)
                current_mat = {"MaterialName": parts[2]}

            elif s.startswith("END MATERIAL"):
                material_list.append(current_mat)
                current_mat = None

            elif current_mat and len(s.split()) >= 2:
                parts = re.split(r"\s+", s)
                key = ' '.join(parts[:-1])
                value = parts[-1]
                current_mat[key] = value

        df_material = pd.DataFrame(material_list)
        _emit(logger, f"   ✓ 解析了 {len(material_list)} 个材料")

        # 6. 解析DEF S-N LINE
        _emit(logger, "\n6. 解析 DEF S-N LINE...")
        S_N_list = []
        S_N_Line = {}
        for line in lines:
            s = line.strip()
            if s.startswith("DEF S-N LINE"):
                parts = re.split(r"\s+", s)
                S_N_Line['Name'] = parts[-1]
            elif s.startswith("LINE"):
                parts = re.split(r"\s+", s)
                S_N_Line['Description'] = parts[-1]
            elif s.startswith("END DEF S-N LINE"):
                S_N_list.append(S_N_Line)
                S_N_Line = {}
        df_S_N_Line = pd.DataFrame(S_N_list)
        _emit(logger, f"   ✓ 解析了 {len(S_N_list)} 个S-N线")

        # 7. 解析DEF LINE
        _emit(logger, "\n7. 解析 DEF LINE...")
        line_list = []
        current_line = None
        points = {}

        for line in lines:
            s = line.strip()

            if s.startswith("DEF LINE"):
                parts = re.split(r"\s+", s)
                current_line = {
                    "LineName": parts[2],
                    "SurfType": parts[3],
                    "Angle": parts[4],
                    "Param1": parts[5],
                    "Param2": parts[6],
                    "Param3": parts[7]
                }
                line_list.append(current_line.copy())

            elif s.startswith(("point", 'point/P')) and len(re.split(r'\s+', s)) >= 5:
                parts = re.split(r'\s+', s)
                if parts[0] == 'point':
                    points['PointRadialPosition'] = parts[1]
                    points['PointChordFraction'] = parts[2]
                    points['PointChordvalue'] = parts[3]
                    points['PointCircumferential'] = parts[4]
                    points['PointYValue'] = parts[5] if len(parts) >= 6 else ''
                elif parts[0] == 'point/P':
                    points['PointRadialPosition'] = f"{parts[1]}/P"
                    points['PointChordFraction'] = f"{parts[2]}/P"
                    points['PointChordvalue'] = f"{parts[3]}/P"
                    points['PointCircumferential'] = f"{parts[4]}/P"
                    points['PointYValue'] = f"{parts[5]}/P" if len(parts) >= 6 else ''
                line_list.append(points)
                points = {}

            elif s.startswith("END DEF LINE"):
                current_line = None

        df_line = pd.DataFrame(line_list)
        _emit(logger, f"   ✓ 解析了 {len([l for l in line_list if 'LineName' in l])} 条线")

        # 8. 解析DEF SECTION
        _emit(logger, "\n8. 解析 DEF SECTION...")
        section_list = []
        current_section_points = []
        section_point = {}
        current_sec = None
        in_comment = False
        in_process_if = False
        process_if_condition = None

        for line in lines:
            s = line.strip()

            if s.startswith('PROCESS IF'):
                in_process_if = True
                parts = re.split(r'\s+', s, maxsplit=2)
                if len(parts) >= 3:
                    process_if_condition = parts[2]
                elif len(parts) == 2:
                    process_if_condition = parts[1]
                continue
            elif s.startswith('END PROCESS IF'):
                in_process_if = False
                process_if_condition = None
                continue

            if s.startswith('MATERIAL'):
                parts = re.split(r'\s+', s)
                current_sec = {'MaterialName': parts[1]}
            elif s.startswith('COMMENT'):
                in_comment = True
                temp_comment = []
                if current_sec is None:
                    current_sec = {}
            elif s.startswith('END OF COMMENT'):
                in_comment = False
                if temp_comment:
                    current_sec['Description'] = temp_comment[0]
            elif in_comment:
                temp_comment.append(s)
            elif s.startswith('DEF SECTION'):
                current_section_points = []
                parts = re.split(r'\s+', s)

                if len(parts) >= 5:
                    current_sec['Name'] = parts[2]
                    current_sec['SectionType'] = parts[3]
                    current_sec['SectionNum'] = parts[4]
                elif len(parts) >= 4:
                    combined_with_param = parts[2]
                    section_types = ['SKIN/Oo', 'SKIN/Oi', 'SKIN/Mo', 'SKIN/Mi', 'SKIN/Io', 'SKIN/Ii', 'STIFFENER', 'MASS']
                    section_types_sorted = sorted(section_types, key=len, reverse=True)

                    section_type_found = None
                    for st in section_types_sorted:
                        if st in combined_with_param:
                            section_type_found = st
                            name_part = combined_with_param.split(st)[0]
                            current_sec['Name'] = name_part
                            current_sec['SectionType'] = st
                            current_sec['SectionNum'] = parts[3]
                            break

                    if section_type_found is None:
                        current_sec['Name'] = combined_with_param
                        current_sec['SectionType'] = ''
                        current_sec['SectionNum'] = parts[3]
                else:
                    current_sec['Name'] = parts[2] if len(parts) > 2 else ''
                    current_sec['SectionType'] = ''
                    current_sec['SectionNum'] = ''

                if in_process_if and process_if_condition:
                    current_sec['ProcessCondition'] = process_if_condition

            elif s.startswith('lines'):
                parts = re.split(r'\s+', s)
                current_sec['Line1'] = parts[1]
                current_sec['Line2'] = parts[2]

            elif s.startswith('point') and len(re.split(r'\s+', s)) != 6:
                parts = re.split(r'\s+', s)

                if len(parts) >= 3:
                    section_point['pointX'] = parts[1]
                    section_point['layer'] = parts[2]
                elif len(parts) == 2:
                    compact_value = parts[1]
                    split_pos = -1
                    for i in range(1, len(compact_value)):
                        candidate_pos = compact_value[:i]
                        candidate_layer = compact_value[i:]
                        if re.match(r'^\d+$', candidate_pos):
                            if re.match(r'^\d+\.?\d*[Ee][+-]?\d+$', candidate_layer):
                                split_pos = i

                    if split_pos > 0:
                        section_point['pointX'] = compact_value[:split_pos]
                        section_point['layer'] = compact_value[split_pos:]
                    else:
                        section_point['pointX'] = compact_value
                        section_point['layer'] = ''

                current_section_points.append(section_point.copy())
                section_point = {}

            elif s.startswith('END DEF SECTION'):
                section_list.append(current_sec)
                section_list.extend(current_section_points)
                current_section_points = []
                current_sec = None

        df_section = pd.DataFrame(section_list)

        # 确保所有必需的列都存在
        required_columns = ['Name', 'Description', 'MaterialName', 'SectionType', 'SectionNum',
                            'Line1', 'Line2', 'pointX', 'layer', 'ProcessCondition']
        for col in required_columns:
            if col not in df_section.columns:
                df_section[col] = ''

        df_section = df_section[required_columns]

        section_count = len(df_section[df_section['Name'].notna() | df_section['Description'].notna()])
        _emit(logger, f"   ✓ 解析了 {section_count} 个截面")

        # 9. 保存到Excel
        _emit(logger, "\n9. 保存到 Excel...")
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df_para.to_excel(writer, sheet_name="Parameters", index=False)
            df_final.to_excel(writer, index=False, sheet_name='shape_points')
            df_place.to_excel(writer, sheet_name="PlaceShapes", index=False)
            df_material.to_excel(writer, sheet_name="Materials", index=False)
            df_S_N_Line.to_excel(writer, sheet_name='S_N Lines', index=False)
            df_line.to_excel(writer, sheet_name="Line", index=False)
            df_section.to_excel(writer, sheet_name="Sections", index=False)

        _emit(logger, f"   ✓ 文件保存成功: {output_path}")

        if open_output_folder:
            _maybe_open_folder(output_path, logger)

        _emit(logger, LOG_SEPARATOR)
        _emit(logger, "转换成功完成！")
        _emit(logger, LOG_SEPARATOR)
        return True

    except Exception as e:
        _emit(logger, f"\n{LOG_SEPARATOR}")
        _emit(logger, f"错误: 转换失败 - {str(e)}")
        _emit(logger, f"{LOG_SEPARATOR}")
        import traceback
        _emit(logger, f"详细错误信息:\n{traceback.format_exc()}")
        return False


def convert_excel_to_txt(input_file, output_file, logger=None, open_output_folder=False):
    """Excel → blade_geometry.mac 转换。

    Args:
        input_file: 输入 .xlsx 文件路径（由 ``convert_txt_to_excel`` 生成）
        output_file: 输出 .mac 文件路径
        logger: 可选的日志回调
        open_output_folder: 是否完成后打开输出文件夹

    Returns:
        bool: 成功 True，失败 False
    """
    def try_convert(value, target_type=float):
        """尝试转换值，如果是文本参数名则保留原样"""
        try:
            return target_type(value)
        except (ValueError, TypeError):
            return str(value).strip()

    try:
        _emit(logger, LOG_SEPARATOR)
        _emit(logger, "开始转换：Excel → blade_geometry.mac")

        # 1. 读取Excel
        _emit(logger, "\n1. 读取 Excel 文件...")
        excel_path = Path(input_file)

        df_para = pd.read_excel(excel_path, sheet_name="Parameters")
        df_shape = pd.read_excel(excel_path, sheet_name="shape_points")
        df_place = pd.read_excel(excel_path, sheet_name="PlaceShapes")
        df_material = pd.read_excel(excel_path, sheet_name="Materials")
        df_S_N_line = pd.read_excel(excel_path, sheet_name="S_N Lines")
        df_line = pd.read_excel(excel_path, sheet_name="Line")
        df_section = pd.read_excel(excel_path, sheet_name="Sections")

        # 验证PlaceShapes表是否包含CenterX和CenterY列
        if "CenterX" not in df_place.columns or "CenterY" not in df_place.columns:
            raise ValueError(
                "PlaceShapes表缺少CenterX或CenterY列。\n"
                "请使用新版本工具重新生成Excel文件。"
            )

        _emit(logger, f"   ✓ Parameters: {len(df_para)} 行")
        _emit(logger, f"   ✓ shape_points: {len(df_shape)} 行")
        _emit(logger, f"   ✓ PlaceShapes: {len(df_place)} 行")
        _emit(logger, f"   ✓ Materials: {len(df_material)} 行")
        _emit(logger, f"   ✓ S_N Lines: {len(df_S_N_line)} 行")
        _emit(logger, f"   ✓ Line: {len(df_line)} 行")
        _emit(logger, f"   ✓ Sections: {len(df_section)} 行")

        # 2. 写入txt文件
        _emit(logger, "\n2. 生成 blade_geometry.mac...")
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            # DEF PARA
            _emit(logger, "   生成 DEF PARA...")
            for _, row in df_para.iterrows():
                f.write(f"DEF PARA,    {row['Parameter']}={row['Value']}\n")
            f.write("COMMENT\n\nEND OF COMMENT\n")

            # DEF SHAPE
            _emit(logger, "   生成 DEF SHAPE...")
            cols = df_shape.columns.tolist()
            i = 0
            while i < len(cols):
                shape_name = cols[i]
                ycol = cols[i + 1]

                sub = df_shape[[shape_name, ycol]].dropna(how="all")

                place_row = df_place[df_place["ShapeName"] == shape_name]
                if place_row.empty:
                    raise ValueError(f"PlaceShapes表中找不到形状'{shape_name}'的center信息")
                cx = place_row.iloc[0]["CenterX"]
                cy = place_row.iloc[0]["CenterY"]

                f.write(f"DEF SHAPE {shape_name:<10}{cx:<10}{cy:<10}\n")

                for k in range(0, len(sub)):
                    x = sub.iloc[k, 0]
                    y = sub.iloc[k, 1]
                    if pd.isna(x):
                        continue

                    x_val = x
                    y_val = y

                    try:
                        x_float = float(x)
                        if x_float == int(x_float):
                            x_val = str(int(x_float))
                        else:
                            x_val = f"{x_float:g}"
                            if 'e' in x_val:
                                x_val = x_val.upper().replace('e', 'E')
                    except (ValueError, TypeError):
                        x_val = str(x)

                    try:
                        y_float = float(y)
                        if y_float == int(y_float):
                            y_val = str(int(y_float))
                        else:
                            y_val = f"{y_float:g}"
                            if 'e' in y_val:
                                y_val = y_val.upper().replace('e', 'E')
                    except (ValueError, TypeError):
                        y_val = str(y)

                    f.write(f" POINTS             {x_val:<10}{y_val:<10}\n")

                f.write("END SHAPE/C\n")
                i += 2

            # PLACE SHAPE
            _emit(logger, "   生成 PLACE SHAPE...")
            total_length = 30
            for _, r in df_place.iterrows():
                f.write(f"PLACE SHAPE {r['ShapeName']}{r['Zpos']:>{total_length - 12 - len(r['ShapeName'])}}\n")
                f.write(f"Rotation            /DG {r['Rotation']}\n")
                f.write(f"TRANSLATION        {r['TranslationX']:>10}{r['TranslationY']:>10}\n")
                f.write(f"Scale factors{r['ScaleFactorsX']:>{total_length - 13}}{r['ScaleFactorsY']:>{40 - total_length}}\n")
                f.write("END PLACE\n")

            # BL-AXIS
            f.write("DEF BL-AXIS OFF\n")
            f.write("END DEF BL-AXIS\n")
            f.write("COMMENT\n\nEND OF COMMENT\n")

            # DEF MATERIAL
            _emit(logger, "   生成 DEF MATERIAL...")
            for _, r in df_material.iterrows():
                f.write(f"DEF MATERIAL {r['MaterialName']}\n")

                tau_value = None
                thickness_factor_value = None

                for k, v in r.items():
                    if k == "MaterialName":
                        continue
                    if pd.isna(v):
                        continue
                    if k == 'TAU':
                        tau_value = v
                        continue
                    if k == 'Thickness_factor' or k == 'thickness_factor':
                        thickness_factor_value = v
                        continue
                    if k == 'Fiber':
                        f.write(f"Fiber angle         {v}\n")
                    else:
                        f.write(f"{k:<20}                {v}\n")

                if tau_value is not None:
                    f.write(f"{'TAU':<20}                {tau_value}\n")
                if thickness_factor_value is not None:
                    f.write(f"{'Thickness_factor':<20}                {thickness_factor_value}\n")

                f.write("END MATERIAL DEF\n\nCOMMENT\n\nEND OF COMMENT\n")

            # DEF S-N LINE
            _emit(logger, "   生成 DEF S-N LINE...")
            for _, r in df_S_N_line.iterrows():
                f.write(f"DEF S-N LINE {r['Name']}\n")
                f.write((f"LINE  :             {r['Description']}\n"))
                f.write("END DEF S-N LINE\n")

            # DEF LINE
            _emit(logger, "   生成 DEF LINE...")
            i = 0
            while i < len(df_line):
                row = df_line.iloc[i]
                if not pd.isna(row['LineName']):
                    f.write("COMMENT\n\nEND OF COMMENT\n")
                    angle = try_convert(row['Angle'], int)
                    param1 = try_convert(row['Param1'], int)
                    param2 = try_convert(row['Param2'], int)
                    param3 = try_convert(row['Param3'], int)
                    f.write(f"DEF LINE {row['LineName']:>{17 - 9}}   {row['SurfType']}{angle:>{60 - 20 - len(row['SurfType'])}}           {param1} {param2} {param3}\n")
                    i += 1

                    while i < len(df_line) and pd.isna(df_line.iloc[i]['LineName']):
                        r2 = df_line.iloc[i]
                        if '/P' in str(r2['PointRadialPosition']):
                            PointChordFraction_val = r2['PointChordFraction'].replace('/P', '').strip()
                            try:
                                PointChordFraction_float = float(PointChordFraction_val)
                                if PointChordFraction_float == int(PointChordFraction_float):
                                    PointChordFraction = str(int(PointChordFraction_float))
                                else:
                                    PointChordFraction = f"{PointChordFraction_float:g}"
                                    if 'e' in PointChordFraction:
                                        PointChordFraction = PointChordFraction.upper().replace('e', 'E')
                            except (ValueError, TypeError):
                                PointChordFraction = PointChordFraction_val
                            try:
                                PointChordvalue_raw = r2['PointChordvalue'].replace('/P', '').strip()
                                if any(c.isalpha() for c in PointChordvalue_raw):
                                    PointChordvalue_str = PointChordvalue_raw
                                else:
                                    PointChordvalue = float(PointChordvalue_raw)
                                    if PointChordvalue == int(PointChordvalue):
                                        PointChordvalue_str = str(int(PointChordvalue))
                                    else:
                                        PointChordvalue_str = f"{PointChordvalue:g}"
                                        if 'e' in PointChordvalue_str:
                                            PointChordvalue_str = PointChordvalue_str.upper().replace('e', 'E')
                            except (ValueError, TypeError):
                                PointChordvalue_str = r2['PointChordvalue'].replace('/P', '').strip()
                            point_y_val = r2['PointYValue']
                            has_point_y = not (pd.isna(point_y_val) or str(point_y_val).strip() == '' or str(point_y_val).strip() == 'nan')
                            if has_point_y:
                                f.write(f" point/P"
                                        f"{format_field(r2['PointRadialPosition'].replace('/P', '').strip(), 12)}"
                                        f"{format_field(PointChordFraction, 10)}"
                                        f"{format_field(PointChordvalue_str, 10)}"
                                        f"{format_field(r2['PointCircumferential'].replace('/P', '').strip(), 10)}"
                                        f"{format_field(str(point_y_val).replace('/P', '').strip(), 10)}\n")
                            else:
                                f.write(f" point/P"
                                        f"{format_field(r2['PointRadialPosition'].replace('/P', '').strip(), 12)}"
                                        f"{format_field(PointChordFraction, 10)}"
                                        f"{format_field(PointChordvalue_str, 10)}"
                                        f"{format_field(r2['PointCircumferential'].replace('/P', '').strip(), 10)}\n")
                        else:
                            chord_frac_val = str(r2['PointChordFraction'])
                            try:
                                chord_frac_float = float(chord_frac_val)
                                if chord_frac_float == int(chord_frac_float):
                                    if chord_frac_val == '1':
                                        chord_frac = int(chord_frac_float)
                                    else:
                                        chord_frac = str(int(chord_frac_float))
                                else:
                                    chord_frac = f"{chord_frac_float:g}"
                                    if 'e' in chord_frac:
                                        chord_frac = chord_frac.upper().replace('e', 'E')
                            except (ValueError, TypeError):
                                chord_frac = try_convert(r2['PointChordFraction'])
                            point_y_val = r2['PointYValue']
                            has_point_y = not (pd.isna(point_y_val) or str(point_y_val).strip() == '' or str(point_y_val).strip() == 'nan')
                            if has_point_y:
                                f.write(f" point"
                                        f"{format_field(r2['PointRadialPosition'], 14)}"
                                        f"{format_field(chord_frac, 10)}"
                                        f"{format_field(r2['PointChordvalue'], 10)}"
                                        f"{format_field(r2['PointCircumferential'], 10)}"
                                        f"{format_field(r2['PointYValue'], 10)}\n")
                            else:
                                f.write(f" point"
                                        f"{format_field(r2['PointRadialPosition'], 14)}"
                                        f"{format_field(chord_frac, 10)}"
                                        f"{format_field(r2['PointChordvalue'], 10)}"
                                        f"{format_field(r2['PointCircumferential'], 10)}\n")

                        i += 1
                    f.write("END DEF LINE\n")
                else:
                    i += 1

            # DEF SECTION
            _emit(logger, "   生成 DEF SECTION...")
            i = 0
            section_count = 0
            total_sections = df_section['Name'].notna().sum() + df_section['Description'].notna().sum()

            while i < len(df_section):
                row = df_section.iloc[i]

                if not pd.isna(row['Name']) and pd.isna(row['Description']):
                    section_count += 1
                    if section_count % 50 == 0:
                        _emit(logger, f"     进度: {section_count}/{total_sections} sections...")

                    section_type_full = str(row['SectionType']) if not pd.isna(row['SectionType']) else ''
                    base_type = section_type_full.split()[0] if section_type_full else ''
                    section_num = str(int(float(row['SectionNum']))) if not pd.isna(row.get('SectionNum')) and str(row.get('SectionNum', '')).strip() not in ('', 'nan') else '4'
                    name = str(row['Name']) if not pd.isna(row['Name']) else ''

                    process_cond = str(row['ProcessCondition']) if not pd.isna(row['ProcessCondition']) else None

                    if process_cond:
                        f.write(f"PROCESS IF {process_cond}\n")
                        f.write(f"COMMENT\n\nEND OF COMMENT\n")
                    else:
                        f.write("COMMENT\n\nEND OF COMMENT\n")

                    if base_type != 'MASS':
                        f.write(f"MATERIAL {row['MaterialName']}\n")

                    if base_type in ['STIFFENER', 'MASS']:
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")
                    elif base_type.startswith('SKIN/'):
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")
                    else:
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")

                    if base_type != 'MASS':
                        f.write(f" lines              {row['Line1']:<10}{row['Line2']}\n")
                    i += 1

                    while i < len(df_section) and pd.isna(df_section.iloc[i, 0]) and pd.isna(df_section.iloc[i, 1]):
                        r2 = df_section.iloc[i]
                        layer_val = r2['layer']
                        if not pd.isna(layer_val):
                            try:
                                layer_val_float = float(layer_val)
                                if layer_val_float == int(layer_val_float):
                                    layer_str = str(int(layer_val_float))
                                else:
                                    layer_str = f"{layer_val_float:g}"
                                    if 'e' in layer_str:
                                        layer_str = layer_str.upper().replace('e', 'E')
                            except (ValueError, TypeError):
                                layer_str = str(layer_val)
                        else:
                            layer_str = str(layer_val)
                        pointx_str = normalize_number_str(r2['pointX'])
                        f.write(f" point{format_field(pointx_str, 14)}{format_field(layer_str, 10)}\n")
                        i += 1
                    f.write("END DEF SECTION\n")

                    if process_cond:
                        f.write("END PROCESS IF\n")

                elif not pd.isna(row['Description']) and pd.isna(row['Name']):
                    section_count += 1
                    if section_count % 50 == 0:
                        _emit(logger, f"     进度: {section_count}/{total_sections} sections...")

                    process_cond = str(row['ProcessCondition']) if not pd.isna(row['ProcessCondition']) else None

                    if process_cond:
                        f.write("END DEF SECTION\n")
                        f.write(f"PROCESS IF {process_cond}\n")
                        f.write(f"COMMENT\n\nEND OF COMMENT\n")
                    else:
                        f.write(f"COMMENT\n{row['Description']}\nEND OF COMMENT\n")

                    section_type_full = str(row['SectionType']) if not pd.isna(row['SectionType']) else ''
                    base_type = section_type_full.split()[0] if section_type_full else ''
                    section_num = str(int(float(row['SectionNum']))) if not pd.isna(row.get('SectionNum')) and str(row.get('SectionNum', '')).strip() not in ('', 'nan') else '4'
                    name = str(row['Name']) if not pd.isna(row['Name']) else ''

                    if base_type in ['STIFFENER', 'MASS']:
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")
                    elif base_type.startswith('SKIN/'):
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")
                    else:
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")

                    if base_type != 'MASS':
                        f.write(f" lines              {row['Line1']:<10}{row['Line2']}\n")

                    i += 1

                    while i < len(df_section) and pd.isna(df_section.iloc[i, 1]) and pd.isna(df_section.iloc[i, 0]):
                        r2 = df_section.iloc[i]
                        layer_val = r2['layer']
                        if not pd.isna(layer_val):
                            try:
                                layer_val_float = float(layer_val)
                                if layer_val_float == int(layer_val_float):
                                    layer_str = str(int(layer_val_float))
                                else:
                                    layer_str = f"{layer_val_float:g}"
                                    if 'e' in layer_str:
                                        layer_str = layer_str.upper().replace('e', 'E')
                            except (ValueError, TypeError):
                                layer_str = str(layer_val)
                        else:
                            layer_str = str(layer_val)
                        pointx_str = normalize_number_str(r2['pointX'])
                        f.write(f" point{format_field(pointx_str, 14)}{format_field(layer_str, 10)}\n")
                        i += 1
                    f.write("END DEF SECTION\n")

                    if process_cond:
                        f.write("END PROCESS IF\n")

                elif not pd.isna(row['Name']) and not pd.isna(row['Description']):
                    section_count += 1
                    if section_count % 50 == 0:
                        _emit(logger, f"     进度: {section_count}/{total_sections} sections...")

                    process_cond = str(row['ProcessCondition']) if not pd.isna(row['ProcessCondition']) else None

                    if process_cond:
                        f.write("END DEF SECTION\n")
                        f.write(f"PROCESS IF {process_cond}\n")
                        f.write(f"COMMENT\n\nEND OF COMMENT\n")
                    else:
                        f.write(f"COMMENT\n{row['Description']}\nEND OF COMMENT\n")

                    section_type_full = str(row['SectionType']) if not pd.isna(row['SectionType']) else ''
                    base_type = section_type_full.split()[0] if section_type_full else ''
                    section_num = str(int(float(row['SectionNum']))) if not pd.isna(row.get('SectionNum')) and str(row.get('SectionNum', '')).strip() not in ('', 'nan') else '4'
                    name = str(row['Name']) if not pd.isna(row['Name']) else ''

                    if base_type in ['STIFFENER', 'MASS']:
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")
                    elif base_type.startswith('SKIN/'):
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")
                    else:
                        f.write(f"DEF SECTION {name:<8}{base_type:<51}{section_num}\n")

                    if base_type != 'MASS':
                        f.write(f" lines              {row['Line1']:<10}{row['Line2']}\n")

                    i += 1

                    while i < len(df_section) and pd.isna(df_section.iloc[i, 0]) and pd.isna(df_section.iloc[i, 1]):
                        r2 = df_section.iloc[i]
                        layer_val = r2['layer']
                        if not pd.isna(layer_val):
                            try:
                                layer_val_float = float(layer_val)
                                if layer_val_float == int(layer_val_float):
                                    layer_str = str(int(layer_val_float))
                                else:
                                    layer_str = f"{layer_val_float:g}"
                                    if 'e' in layer_str:
                                        layer_str = layer_str.upper().replace('e', 'E')
                            except (ValueError, TypeError):
                                layer_str = str(layer_val)
                        else:
                            layer_str = str(layer_val)
                        pointx_str = normalize_number_str(r2['pointX'])
                        f.write(f" point{format_field(pointx_str, 14)}{format_field(layer_str, 10)}\n")
                        i += 1
                    f.write("END DEF SECTION\n")

                    if process_cond:
                        f.write("END PROCESS IF\n")
                else:
                    i += 1

        _emit(logger, f"   ✓ 文件保存成功: {output_path}")

        if open_output_folder:
            _maybe_open_folder(output_path, logger)

        _emit(logger, LOG_SEPARATOR)
        _emit(logger, "转换成功完成！")
        _emit(logger, LOG_SEPARATOR)
        return True

    except Exception as e:
        _emit(logger, f"\n{LOG_SEPARATOR}")
        _emit(logger, f"错误: 转换失败 - {str(e)}")
        _emit(logger, f"{LOG_SEPARATOR}")
        import traceback
        _emit(logger, f"详细错误信息:\n{traceback.format_exc()}")
        return False
