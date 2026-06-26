# -*- coding: utf-8 -*-
"""共享基础设施层：数据读写 / 绘图 / 导出。

本包收编原先散落在 src/ 顶层的 io_utils.py / plotting.py / export.py。
为兼容旧调用方，通过 ``__init__.py`` 重新导出全部公开符号，
调用方既可用 ``import core.plotting as plotting``，也可 ``from core import plot_xxx``。

重要：plotting 在导入时配置 matplotlib 后端与中文字体，须在 pyplot 被其他模块
使用前完成（与原顶层 plotting.py 行为一致）。
"""
from .io_utils import *  # noqa: F401,F403
from .plotting import *  # noqa: F401,F403
from .export import *  # noqa: F401,F403
