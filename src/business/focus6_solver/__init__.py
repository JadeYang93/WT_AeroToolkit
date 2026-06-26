# -*- coding: utf-8 -*-
"""FOCUS6 子包（v0.3.0 从 blade_converter 拆出，独立成模块）。

提供两个 QThread 子类：
- Focus6SolverThread：执行单个求解器功能（farob/frbex/载荷转换）
- OneClickRunThread：串行执行多步 FOCUS6 计算（一键运行）

均为 QThread + pyqtSignal 的"业务+线程"耦合实现（与原项目一致），
不做进一步解耦；UI 面板只负责构造 params dict 与启动线程。
"""
from .solver_focus6 import Focus6SolverThread
from .solver_one_click import OneClickRunThread

__all__ = ['Focus6SolverThread', 'OneClickRunThread']
