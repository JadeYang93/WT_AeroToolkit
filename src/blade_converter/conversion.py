#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
转换模块

提供blade_db到focus2blade的转换功能（WISDEM 插值算法）
"""

import pandas as pd
import numpy as np
import re
from pathlib import Path


def compute_principal_inerties(Ixx, Iyy, Ixy):
    """
    计算主惯性矩和主方向角

    参考WISDEM中的惯性矩阵特征值分解方法
    """
    I_avg = (Ixx + Iyy) / 2.0
    I_diff = (Ixx - Iyy) / 2.0
    I_disc = np.sqrt(I_diff**2 + Ixy**2)

    I1 = I_avg + I_disc
    I2 = I_avg - I_disc

    phi = np.arctan2(Ixy, I_diff) / 2.0

    return I1, I2, phi


def compute_section_properties_blade_db(df_blade):
    """
    从blade_db数据计算截面属性

    参考WISDEM的rotor_elasticity.py中的方法
    """
    props = {}

    # 基本几何参数
    props['r'] = df_blade['R. radius'].values  # mm
    props['chord'] = df_blade['Chord length'].values  # mm
    props['twist_aero'] = df_blade['Chord angle'].values  # rad
    props['thickness'] = (df_blade['Chord thickness'].values /
                          df_blade['Chord length'].values * 100)  # %

    # 弹性中心位置 (Tension Center)
    props['x_ec'] = df_blade['Zx_E'].values  # mm
    props['y_ec'] = df_blade['Zy_E'].values  # mm

    # 质心位置 (Center of Mass)
    props['x_cg'] = df_blade['ctr_grav_flat'].values  # mm
    props['y_cg'] = df_blade['ctr_grav_edge'].values  # mm

    # 剪切中心位置 (Shear Center)
    props['x_sc'] = df_blade['shear_ctr_flat'].values  # mm
    props['y_sc'] = df_blade['shear_ctr_edge'].values  # mm

    # 局部位置 (相对于弦长)
    props['x_ec_local'] = df_blade['el_ctr_flat'].values / df_blade['Chord length'].values * 100  # %
    props['x_cg_local'] = df_blade['ctr_grav_flat'].values / df_blade['Chord length'].values * 100  # %
    props['x_sc_local'] = df_blade['shear_ctr_flat'].values / df_blade['Chord length'].values * 100  # %

    # Y方向的局部位置（占位，稍后使用变桨轴线计算）
    props['y_ec_for_local'] = df_blade['el_ctr_edge'].values
    props['y_ec_local'] = np.zeros_like(props['r'])  # 占位，稍后计算

    props['y_cg_for_local'] = df_blade['ctr_grav_edge'].values
    props['y_cg_local'] = np.zeros_like(props['r'])  # 占位，稍后计算

    props['y_sc_for_local'] = df_blade['shear_ctr_edge'].values
    props['y_sc_local'] = np.zeros_like(props['r'])  # 占位，稍后计算

    # 质量属性
    props['mass_per_len'] = df_blade['Mass_per_L'].values  # kg/mm

    # 质量惯性矩
    Ixx_rho = df_blade['Ixx_Z*Ro'].values  # kg*mm
    Iyy_rho = df_blade['Iyy_Z*Ro'].values  # kg*mm
    Ixy_rho = df_blade['Ixy_Z*Ro'].values  # kg*mm

    # 计算主质量惯性矩
    I1_rho, I2_rho, phi_rho = compute_principal_inerties(Ixx_rho, Iyy_rho, Ixy_rho)

    # 极惯性矩 (质量加权)
    props['rhoJ'] = df_blade['Ip*Ro'].values  # kg*mm

    # 回转半径比
    with np.errstate(invalid='ignore'):
        props['radius_gyration'] = np.sqrt(I2_rho / I1_rho)
        props['radius_gyration_princ'] = np.sqrt(I1_rho / I2_rho)

    # 质量轴方向角
    props['twist_mass'] = np.rad2deg(phi_rho)  # deg

    # 弯曲刚度
    EI_flat = df_blade['EI_flat'].values  # N*mm^2
    EI_edge = df_blade['EI_edge'].values  # N*mm^2

    props['EI_flap'] = EI_flat  # N*mm^2
    props['EI_edge'] = EI_edge  # N*mm^2

    # 主方向弯曲刚度
    I1_E = df_blade['I1*E'].values  # N*mm^2
    I2_E = df_blade['I2*E'].values  # N*mm^2

    props['EI_flap_princ'] = I2_E  # N*mm^2
    props['EI_edge_princ'] = I1_E  # N*mm^2

    # 结构扭转角
    props['twist_struct'] = np.rad2deg(df_blade['Phi_E'].values)  # deg

    # 扭转刚度
    props['GJ'] = df_blade['St'].values  # N*mm^2

    # 轴向刚度
    props['EA'] = df_blade['Area*E'].values  # N

    # 剪切刚度
    if 'shear_GA_11' in df_blade.columns and 'shear_GA_22' in df_blade.columns:
        props['GA_edge'] = df_blade['shear_GA_11'].values  # N
        props['GA_flap'] = df_blade['shear_GA_22'].values  # N
        props['GA_edge_princ'] = df_blade['shear_GA_11'].values  # N
        props['GA_flap_princ'] = df_blade['shear_GA_22'].values  # N
    else:
        props['GA_edge'] = props['EA'] * 0.1  # N (估算)
        props['GA_flap'] = props['EA'] * 0.1  # N (估算)
        props['GA_edge_princ'] = props['GA_edge']
        props['GA_flap_princ'] = props['GA_flap']

    return props


def interpolate_to_target_sections(props_blade, target_r_m):
    """
    插值到目标截面位置

    使用线性插值方法
    """
    props_interp = {}

    # blade_db的半径位置 (mm)
    source_r_mm = props_blade['r']

    # 从小到大排序
    sort_idx = np.argsort(source_r_mm)
    source_r_sorted = source_r_mm[sort_idx]

    # 目标位置 (mm)
    target_r_mm = np.array(target_r_m) * 1000.0

    # 对每个属性进行插值
    for key, values in props_blade.items():
        values_sorted = values[sort_idx]
        values_interp = np.interp(target_r_mm, source_r_sorted, values_sorted)
        props_interp[key] = values_interp

    return props_interp


def create_focus2blade_dataframe(props_interp, target_distances_m):
    """
    创建focus2blade格式的DataFrame
    """
    data = {
        'Distance along blade': target_distances_m,  # m
        'Chord': props_interp['chord'] / 1000.0,  # mm -> m
        'Aerodynamic Twist': 90.0 - np.rad2deg(props_interp['twist_aero']),
        'Thickness': props_interp['thickness'],  # %
        'Neutral axis (x)': props_interp['x_ec'] / 1000.0,  # mm -> m
        'Neutral axis (y)': props_interp['y_ec'] / 1000.0,  # mm -> m
        'Neutral axis, local (x?)': props_interp['x_ec_local'],  # %
        'Neutral axis, local (y?)': props_interp['y_ec_local'],  # %
        'Centre of mass (x?)': props_interp['x_cg_local'],  # %
        'Centre of mass (y?)': props_interp['y_cg_local'],  # %
        'Mass per unit length': props_interp['mass_per_len'] * 1000.0,  # kg/mm -> kg/m
        'Polar inertia per unit length': props_interp['rhoJ'] * 0.001,  # kg*mm -> kg*m
        'Radii of gyration ratio': props_interp['radius_gyration'],
        'Radii of gyration ratio (princ.)': props_interp['radius_gyration_princ'],
        'Mass axis orientation': props_interp['twist_mass'],  # deg
        'Flapwise stiffness': props_interp['EI_flap'] * 1e-6,  # N*mm^2 -> N*m^2
        'Edgewise stiffness': props_interp['EI_edge'] * 1e-6,  # N*mm^2 -> N*m^2
        'Flapwise stiffness (princ.)': props_interp['EI_flap_princ'] * 1e-6,
        'Edgewise stiffness (princ.)': props_interp['EI_edge_princ'] * 1e-6,
        'Structural twist': -props_interp['twist_struct'],  # deg
        'Torsional stiffness': props_interp['GJ'] * 1e-6,  # N*mm^2 -> N*m^2
        'Axial stiffness': props_interp['EA'],  # N
        'Shear centre (x?)': props_interp['x_sc_local'],  # %
        'Shear centre (y?)': props_interp['y_sc_local'],  # %
        'Stiff_sh_flap': props_interp['GA_flap'],  # N
        'Stiff_sh_edge': props_interp['GA_edge'],  # N
        'Stiff_sh_flap(princ.)': props_interp['GA_flap_princ'],  # N
        'Stiff_sh_edge(princ.)': props_interp['GA_edge_princ'],  # N
    }

    return pd.DataFrame(data)


def blade_db_to_focus2blade_wisdem(blade_db_file, output_file, mac_file):
    """将blade_db文件转换为focus2blade格式

    Args:
        blade_db_file: blade_db文件路径（.xls或.xlsx）
        output_file: 输出文件路径（focus2blade.xlsx）
        mac_file: mac文件路径（必须），用于提取变桨中心数据

    Returns:
        bool: 成功返回True，失败返回False
    """
    try:
        # 1. 检查mac文件参数
        if not mac_file:
            raise Exception("未提供mac文件参数")

        mac_file_path = Path(mac_file)
        if not mac_file_path.exists():
            raise Exception(f"mac文件不存在: {mac_file}")

        # 2. 读取blade_db文件
        if str(blade_db_file).endswith('.xls'):
            df_blade = pd.read_excel(blade_db_file, engine='xlrd')
        else:
            df_blade = pd.read_excel(blade_db_file, engine='openpyxl')

        # 3. 从mac文件提取变桨中心数据
        pitch_data = _extract_pitch_data_from_mac(mac_file)
        if not pitch_data:
            raise Exception("从mac文件提取变桨中心数据失败")

        # 4. 使用mac文件中的变桨中心数据
        target_distances_m = sorted(pitch_data.keys())
        pitch_axis = [pitch_data[pos] for pos in target_distances_m]

        # 5. 计算blade_db的截面属性
        props_blade = compute_section_properties_blade_db(df_blade)

        # 6. 插值到目标截面位置
        props_interp = interpolate_to_target_sections(props_blade, target_distances_m)

        # 7. 计算局部坐标
        props_interp['y_ec_local'] = pitch_axis + props_interp['y_ec_for_local'] / props_interp['chord'] * 100
        props_interp['y_cg_local'] = pitch_axis + props_interp['y_cg_for_local'] / props_interp['chord'] * 100
        props_interp['y_sc_local'] = pitch_axis + props_interp['y_sc_for_local'] / props_interp['chord'] * 100

        # 8. 创建输出DataFrame
        df_output = create_focus2blade_dataframe(props_interp, target_distances_m)

        # 9. 保存输出文件
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        df_output_copy = df_output.fillna("NAN")

        with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
            pd.DataFrame([df_output_copy.columns.tolist()]).to_excel(
                writer, index=False, header=False, startrow=0
            )
            df_output_copy.to_excel(
                writer, index=False, header=False, startrow=2
            )

        return True

    except Exception as e:
        print(f"转换失败: {str(e)}")
        import traceback
        print(f"详细错误:\n{traceback.format_exc()}")
        return False


def _extract_pitch_data_from_mac(mac_file):
    """从mac文件中提取DEF SHAPE数据"""
    try:
        pitch_data = {}

        with open(mac_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        pattern = r'DEF\s+SHAPE\s+(\S+)\s+([\d.]+)'
        matches = re.findall(pattern, content, re.IGNORECASE)

        for match in matches:
            shape_name = match[0]
            pitch_position = float(match[1])

            position_match = re.search(r'[\d.]+', shape_name)
            if position_match:
                position_m = float(position_match.group())
                pitch_data[position_m] = pitch_position

        if not pitch_data:
            return None

        return pitch_data

    except Exception as e:
        print(f"从mac文件提取变桨中心数据失败: {str(e)}")
        return None
