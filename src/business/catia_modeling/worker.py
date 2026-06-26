# -*- coding: utf-8 -*-
"""CATIA 建模 Worker（QThread）。

三个步骤共用一个 Worker 类，通过 step 参数区分。
在子线程内新建 CatiaContext（COM 对象不跨线程缓存），跑完即释放。

信号:
    progress(int, str)   进度百分比 + 日志消息（仅用于真实更新百分比时）
    log_msg(str)         纯日志消息（不更新进度条百分比，避免归零闪烁）
    finished_ok(str)     成功（摘要文本）
    finished_err(str)    失败（错误文本）

注意: 三步骤函数内部的 progress_cb 回调（逐截面/逐曲线的细粒度消息）
      通过 log_msg 发出，不触碰进度条百分比；百分比只在连接/开始/完成
      等关键节点由本 Worker 显式 emit，避免 QProgressBar.setValue(-1) 归零。
"""
from PyQt5.QtCore import QThread, pyqtSignal

from .exceptions import CatiaModelError


class CatiaModelingWorker(QThread):
    """三步骤通用 Worker。

    Args:
        step: 'sections' | 'resample' | 'loft'
        params: 对应步骤的 dataclass（SectionParams/ResampleParams/LoftParams）
    """

    progress = pyqtSignal(int, str)
    log_msg = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(self, step, params):
        super().__init__()
        self.step = step
        self.params = params

    def run(self):
        try:
            # COM 初始化（子线程需 CoInitialize）
            import pythoncom
            pythoncom.CoInitialize()
            try:
                self._run_impl()
            finally:
                pythoncom.CoUninitialize()
        except CatiaModelError as e:
            self.finished_err.emit(str(e))
        except Exception as e:
            import traceback
            self.finished_err.emit(
                f'未预期错误: {e}\n{traceback.format_exc()}')

    def _run_impl(self):
        from .context import CatiaContext
        self.progress.emit(5, '连接 CATIA...')
        ctx = CatiaContext()  # 失败抛 CatiaNotRunningError 等

        # 各步骤函数的 progress_cb 回调（细粒度逐截面消息）走纯日志通道
        def cb(msg):
            self.log_msg.emit(msg)

        self.progress.emit(15, f'开始执行步骤 [{self.step}]')
        if self.step == 'sections':
            from .sections import build_sections
            result = build_sections(ctx, self.params, cb)
            total = self.params.num_groups
            built = result['sections_built']
            summary = (f'构建截面完成: {built}/{total} 成功'
                       f'{f"，失败 {len(result["failed_groups"])} 组" if result["failed_groups"] else ""}')
            self.progress.emit(100, f'=== {summary} ===')
            self.finished_ok.emit(summary)
        elif self.step == 'resample':
            from .resample import resample_and_smooth
            result = resample_and_smooth(ctx, self.params, cb)
            proc = result['curves_processed']
            summary = f'重采样光顺完成: {proc} 条曲线'
            self.progress.emit(100, f'=== {summary} ===')
            self.finished_ok.emit(summary)
        elif self.step == 'loft':
            from .loft import build_loft_surface
            result = build_loft_surface(ctx, self.params, cb)
            summary = f'多截面曲面生成: {result["section_count"]} 个截面 → {result["surface_name"]}'
            self.progress.emit(100, f'=== {summary} ===')
            self.finished_ok.emit(summary)
        else:
            self.finished_err.emit(f'未知步骤: {self.step}')
