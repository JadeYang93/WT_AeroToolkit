# -*- coding: utf-8 -*-
"""blade_converter 配置常量（从原项目 src/config.py 迁移，重命名避免与工具箱 config.py 冲突）。

所有阈值、字段映射、求解器常量、单位定义等集中管理。
路径相关常量（如 ``DEFAULT_MODULES_PATH``）保留作兜底默认值；
运行时由 ``BladeConverterPanel`` 从 ``ConfigCenter.extras`` 读取覆盖。
"""
import re

# =============================================================================
# 自定义异常类
# =============================================================================

class ConversionError(Exception):
    """转换过程基础异常"""
    pass


class FileValidationError(ConversionError):
    """文件验证异常"""
    pass


class DataParsingError(ConversionError):
    """数据解析异常"""
    pass


class DataValidationError(ConversionError):
    """数据验证异常"""
    pass


# =============================================================================
# 配置类
# =============================================================================

class ConversionConfig:
    """转换配置类：集中管理列映射和阈值"""

    # focus2blade输出列到参考文件的列索引映射
    COLUMN_MAPPING = {
        'Distance along blade': 0,
        'Chord': 1,
        'Twist angle': 2,
        'Mass per unit length': 3,
        'Flapwise stiffness': 4,
        'Edgewise stiffness': 5,
        'Polar inertia per unit length': 6,
        'Structural twist': 7,
        'Torsional stiffness': 8,
        'Stiff_sh_flap': 9,
        'Stiff_sh_edge': 10,
        'x_ec_local': 11,
        'y_ec_local': 12,
        'x_cg_local': 13,
        'y_cg_local': 14,
        'x_sh_local': 15,
        'y_sh_local': 16,
    }

    # 偏差阈值（用于对比报告）
    DEVIATION_EXCELLENT = 0.1  # %
    DEVIATION_GOOD = 1.0       # %
    DEVIATION_FAIR = 5.0       # %

    # 关键参数列（用于简要对比）
    KEY_COLUMNS = [
        'Chord', 'Mass per unit length', 'Flapwise stiffness',
        'Edgewise stiffness', 'y_ec_local', 'Torsional stiffness'
    ]


class PRJFieldMapping:
    """PRJ文件字段映射配置"""

    # .prj字段 -> focus2blade.xlsx列名 的映射
    FIELD_MAPPING = {
        'REF_X': 'Neutral axis (x)',
        'REF_Y': 'Neutral axis (y)',
        'CE_X': 'Neutral axis, local (x?)',
        'CE_Y': 'Neutral axis, local (y?)',
        'CM_X': 'Centre of mass (x?)',
        'CM_Y': 'Centre of mass (y?)',
        'MASS': 'Mass per unit length',
        'SINER': 'Polar inertia per unit length',
        'RGRATIO': 'Radii of gyration ratio',
        'BETA_M': 'Mass axis orientation',
        'EIFLAP': 'Flapwise stiffness (princ.)',
        'EIEDGE': 'Edgewise stiffness (princ.)',
        'BETA_S': 'Structural twist',
        'GJ': 'Torsional stiffness',
        'EA': 'Axial stiffness',
        'CS_X': 'Shear centre (x?)',
        'CS_Y': 'Shear centre (y?)',
    }


# =============================================================================
# 文件路径常量（默认值；运行时由 ConfigCenter extras 覆盖）
# =============================================================================

# 默认文件名
DEFAULT_BLADE_DB_FILE = "blade_db.xlsx"
DEFAULT_OUTPUT_FILE = "focus2blade.xlsx"
DEFAULT_PITCH_FILE = "变桨中心.xlsx"

# 输出文件夹（历史命名，仅 conversion_thread 引用）
OUTPUT_FOLDER = "file_oup"

# 求解器类型对应的默认blade_db文件名
DEFAULT_BLADE_DB_FRBEX = "blade_db_frbex.xlsx"
DEFAULT_BLADE_DB_FAROB = "blade_db_farob.xlsx"

# blade_geometry转换相关
DEFAULT_TXT_INPUT_FILE = "blade_geometry.mac"
DEFAULT_EXCEL_OUTPUT_FILE = "blade_data.xlsx"
DEFAULT_EXCEL_INPUT_FILE = "blade_data.xlsx"
DEFAULT_TXT_OUTPUT_FILE = "blade_geometry_new.mac"

# FOCUS6求解器相关（兜底默认值；实际由 ConfigCenter extras 提供）
DEFAULT_MODULES_PATH = r"C:\Program Files (x86)\ECN_WMC\FOCUS6.3\Modules"
DEFAULT_MAC_FILE = "blade_geometry.mac"

# =============================================================================
# FOCUS6求解器常量
# =============================================================================

SOLVER_FAROB = "farob"
SOLVER_FRBEX = "frbex"

# 计算功能列表
FUNCTION_READ_MAC = "读取mac文件"
FUNCTION_PARSE_MAC = "解析mac文件"
FUNCTION_FREQUENCY = "频率计算"
FUNCTION_TIP_DEFLECTION = "叶尖挠度计算"
FUNCTION_STRAIN = "应变计算"
FUNCTION_WEIGHT = "重量计算"
FUNCTION_LOAD_CONVERSION = "载荷转化"

# 功能名称到文件夹名称的映射（使用英文文件夹名）
FUNCTION_FOLDER_NAMES = {
    FUNCTION_READ_MAC: "ReadMac",
    FUNCTION_PARSE_MAC: "ParseMac",
    FUNCTION_FREQUENCY: "CalcEigenFrequency",
    FUNCTION_TIP_DEFLECTION: "CalcTipDeflection",
    FUNCTION_STRAIN: "CalcStrain",
    FUNCTION_WEIGHT: "CalcGravity",
    FUNCTION_LOAD_CONVERSION: "LoadConversion"
}

# Frbex求解器默认参数
FRBEX_DEFAULT_DRMX = 250  # 默认drmx值

# =============================================================================
# 输出单位定义（28列单位）
# =============================================================================

FOCUS2BLADE_UNITS = [
    '[m]', '[m]', '[deg]', '[%]', '[m]', '[m]', '[%]', '[%]', '[%]', '[%]',
    '[kg/m]', '[kgm]', '[-]', '[-]', '[deg]', '[Nm^2]', '[Nm^2]', '[Nm^2]',
    '[Nm^2]', '[deg]', '[Nm^2]', '[N]', '[%]', '[%]', '[N]', '[N]', '[N]', '[N]'
]

# =============================================================================
# 日志格式常量
# =============================================================================

LOG_SEPARATOR = "=" * 80
LOG_SEPARATOR_WIDE = "=" * 100
LOG_SEPARATOR_SHORT = "-" * 80

# =============================================================================
# 验证阈值
# =============================================================================

MAX_BLADE_LENGTH = 200.0  # 叶片长度上限（米）
MIN_DATA_ROWS = 2  # 最少数据行数

# =============================================================================
# 偏差阈值（用于对比报告）
# =============================================================================

DEVIATION_EXCELLENT = 0.1  # %
DEVIATION_GOOD = 1.0       # %
DEVIATION_FAIR = 5.0       # %

# =============================================================================
# 关键参数列（用于简要对比）
# =============================================================================

KEY_COLUMNS = [
    'Chord', 'Mass per unit length', 'Flapwise stiffness',
    'Edgewise stiffness', 'y_ec_local', 'Torsional stiffness'
]

# =============================================================================
# focus2blade输出列到参考文件的列索引映射
# =============================================================================

COLUMN_MAPPING = {
    'Distance along blade': 0,
    'Chord': 1,
    'Twist angle': 2,
    'Mass per unit length': 3,
    'Flapwise stiffness': 4,
    'Edgewise stiffness': 5,
    'Polar inertia per unit length': 6,
    'Structural twist': 7,
    'Torsional stiffness': 8,
    'Stiff_sh_flap': 9,
    'Stiff_sh_edge': 10,
    'x_ec_local': 11,
    'y_ec_local': 12,
    'x_cg_local': 13,
    'y_cg_local': 14,
    'x_sh_local': 15,
    'y_sh_local': 16,
}

# =============================================================================
# PRJ 文件字段映射配置
# =============================================================================

PRJ_FIELD_MAPPING = {
    'REF_X': 'Neutral axis (x)',
    'REF_Y': 'Neutral axis (y)',
    'CE_X': 'Neutral axis, local (x?)',
    'CE_Y': 'Neutral axis, local (y?)',
    'CM_X': 'Centre of mass (x?)',
    'CM_Y': 'Centre of mass (y?)',
    'MASS': 'Mass per unit length',
    'SINER': 'Polar inertia per unit length',
    'RGRATIO': 'Radii of gyration ratio',
    'BETA_M': 'Mass axis orientation',
    'EIFLAP': 'Flapwise stiffness (princ.)',
    'EIEDGE': 'Edgewise stiffness (princ.)',
    'BETA_S': 'Structural twist',
    'GJ': 'Torsional stiffness',
    'EA': 'Axial stiffness',
    'CS_X': 'Shear centre (x?)',
    'CS_Y': 'Shear centre (y?)',
}
