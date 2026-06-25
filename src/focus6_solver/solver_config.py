# -*- coding: utf-8 -*-
"""FOCUS6 子包配置常量。

从 blade_converter/bc_config.py 拆出，仅保留求解器（farob/frbex）相关的：
- 求解器类型与默认参数
- 7 种计算功能常量 + 文件夹名映射
- 兜底默认路径（DEFAULT_MODULES_PATH，实际由 ConfigCenter extras 覆盖）
- 日志分隔线常量

让 focus6_solver 子包自包含，不跨包引用 blade_converter.bc_config。
"""

# =============================================================================
# 文件路径常量（默认值；运行时由 ConfigCenter extras 覆盖）
# =============================================================================

# FOCUS6 相关（兜底默认值；实际由 ConfigCenter extras 提供）
DEFAULT_MODULES_PATH = r"C:\Program Files (x86)\ECN_WMC\FOCUS6.3\Modules"
DEFAULT_MAC_FILE = "blade_geometry.mac"

# =============================================================================
# FOCUS6 常量
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
# 日志格式常量
# =============================================================================

LOG_SEPARATOR = "=" * 80
