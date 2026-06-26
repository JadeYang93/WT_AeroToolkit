# -*- coding: utf-8 -*-
"""blade_converter 业务子包。

集中叶片结构套件的纯业务逻辑（解耦 PyQt）：
- ``bc_config``: 常量、异常类、字段映射
- ``conversion``: blade_db → focus2blade 核心算法（WISDEM 插值）
- ``prj_processor``: PRJ 字段读写
- ``template_in``: aeroinfo.in / pcoeffs.in / spcurve.in / steadyop.in / modal.in 模板处理
- ``txt_excel``: blade_geometry.mac ↔ blade_data.xlsx 双向转换（纯函数版）
- ``solver_worker``: FOCUS6（保留 QThread，供 panel 直接用）

UI 面板见 ``tools/blade_converter_panel.py``。
求解器 .exe 路径走 ConfigCenter extras（见 ``global_config.py``）。
"""
