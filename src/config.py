# -*- coding: utf-8 -*-
"""配置常量。所有阈值、调色板、叶型线型映射等集中管理。"""
import os

# 项目根目录（src/config.py 上两层）
# 供 global_config.py 等模块计算 输入数据/输出/config/ 等绝对路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 应用版本
APP_VERSION = 'v0.2.03'

# TI 计算
WINDOW_MIN = 10           # 滑动窗口（分钟）
STEP_MIN = 10             # 滑动步长（分钟）
VALID_RATIO = 0.9         # 窗口有效率阈值
MIN_MEAN_SPEED = 0.5      # 平均风速低于此值(m/s)不算TI

# 聚合阈值
MONTH_DAY_THRESHOLD = 5   # 月均所需最少天数
WEEK_DAY_THRESHOLD = 5    # 周均所需最少天数

# 风速 bin 分析
BIN_WIDTH = 1.0           # bin 宽度 (m/s)，中心取整数（9.5~10.5 → 10）
MIN_BIN_COUNT = 10        # 每个 bin 至少多少个窗口才计算 P90

# 风速清洗
DIFF_THRESHOLD = 10       # 前后秒差阈值
MIN_SPEED = 0             # 物理下限
MAX_SPEED = 50            # 物理上限
MISSING_MARK = -999       # 缺测标记

# 文件
SKIP_FILES = {'空气密度统计数据.xlsx'}
ENCODINGS = ('gbk', 'utf-8', 'utf-8-sig', 'gb18030')

# 绘图
PALETTE = ['#5B8FF9', '#5AD8A6', '#F6BD16', '#E86452',
           '#6DC8EC', '#945FB9', '#FF9845']
DPI = 200

# 叶型 → 线型映射支持
# 名称 → matplotlib linestyle(字符串或 dashes 元组)，宽度独立控制（见 LINE_WIDTHS）
# ls 既可以是字符串 ('-', '--', '-.', ':') 也可以是 dashes 元组 (0, (on, off, ...))
LINESTYLE_OPTIONS = {
    '实线':       '-',
    '密虚线':     (0, (3, 2)),
    '稀虚线':     (0, (10, 4)),
    '点划线':     (0, (8, 3, 1, 3)),
    '双点划线':   (0, (8, 3, 1, 3, 1, 3)),
    '点线':       (0, (1, 2)),
}
DEFAULT_LINESTYLE = '-'
# 线宽选项（独立于线型，UI 上单独选）
LINE_WIDTHS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
DEFAULT_LINEWIDTH = 2.0
# 透明度选项（独立于线型/线宽，UI 上单独选）
ALPHA_OPTIONS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
DEFAULT_ALPHA = 1.0
# 未填叶型的机组在 blade_styles 中的键
UNSPECIFIED_BLADE_KEY = '(未指定)'
