# -*- coding: utf-8 -*-
"""CATIA 叶片建模业务子包。

对外公共 API（后续 task 逐步导出）：
    CatiaContext          连接 + 文档句柄封装
    SectionParams         步骤①参数
    build_sections        步骤①函数
    ResampleParams        步骤②参数
    resample_and_smooth   步骤②函数
    LoftParams            步骤③参数
    build_loft_surface    步骤③函数
"""
