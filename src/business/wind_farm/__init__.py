# -*- coding: utf-8 -*-
"""风场统计业务子包：主流程编排 + 数据处理 + TI bin 分析 + 风场对比。

收编原先散落在 src/ 顶层的 pipeline.py / processing.py / ti_bin.py /
wind_farm_compare.py(→ compare.py)。

公共 API:
    run(...)              → 风场数据统计主流程
    run_compare(...)      → 风场对比主流程
    read_farm_monthly, METRIC_COLUMN → 对比辅助
"""
from .pipeline import run
from .compare import run_compare, read_farm_monthly, METRIC_COLUMN

__all__ = ['run', 'run_compare', 'read_farm_monthly', 'METRIC_COLUMN']
