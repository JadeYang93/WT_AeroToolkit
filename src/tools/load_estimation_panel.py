# -*- coding: utf-8 -*-
"""载荷预估面板（QWidget 子类）。

源项目 F:/python/载荷信息读取/load_estimation_gui.py（Tkinter）已重写为 PyQt5。
业务逻辑见 src/load_estimation/core.py。

UI 结构：
  - 模块 banner（标题 + 副标题）
  - 输入/输出 GroupBox（输入 xlsx 选择 + 输出目录显示）
  - 拟合曲线 GroupBox（matplotlib 画布 + 视图下拉 + 上一张/下一张）
  - 底部执行栏（运行 + 打开目录 + 进度 + 日志）
"""
import os
import sys
import subprocess
import traceback
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QProgressBar,
    QTextEdit, QMessageBox, QGroupBox, QLineEdit, QComboBox,
    QFrame, QSizePolicy,
)

# matplotlib 嵌入式画布
# 重要：导入 plotting 触发 matplotlib.use('Agg') + 中文字体配置，
# 必须在 pyplot 被使用前完成（与 shape_design_panel 同模式）
import core.plotting as plotting  # noqa: F401
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from global_config import config_center
from business.load_estimation import (
    load_data, fit_loads, save_results, plot_result,
    VIEW_OPTIONS, COMPONENTS,
)


# ============================================================
# 后台 Worker
# ============================================================

class LoadEstimationWorker(QThread):
    """读 Excel → 多项式拟合 → 写 CSV + PNG。

    在 UI 线程外完成所有耗时操作（openpyxl 读 + numpy 拟合 + matplotlib 渲染 8 张 PNG）。
    """
    progress = pyqtSignal(int, str)

    def __init__(self, input_xlsx, output_dir):
        super().__init__()
        self.input_xlsx = input_xlsx
        self.output_dir = output_dir
        self.results = None
        self.error = None

    def run(self):
        try:
            self.progress.emit(5, f'读取数据：{self.input_xlsx}')
            data = load_data(self.input_xlsx)
            self.progress.emit(30, f'  • baseLineSteady: {data["base_steady"].shape[0]} 行')
            self.progress.emit(35, f'  • baselineDynamic: {data["base_dynamic"].shape[0]} 行')
            self.progress.emit(40, f'  • newSteady: {data["new_steady"].shape[0]} 行')

            self.progress.emit(55, '执行 6 阶多项式拟合...')
            self.results = fit_loads(data)

            self.progress.emit(70, f'写入输出目录：{self.output_dir}')
            save_results(self.results, self.output_dir)

            self.progress.emit(100, '=== 拟合完成 ===')
            self.progress.emit(100, '  • result.csv')
            self.progress.emit(100, '  • coefficients.csv')
            self.progress.emit(100, '  • figure_baseline_*.png × 4')
            self.progress.emit(100, '  • figure_new_*.png × 4')
        except Exception as e:
            self.error = traceback.format_exc()
            self.progress.emit(100, f'[错误] {e}')


# ============================================================
# 主面板
# ============================================================

class LoadEstimationPanel(QWidget):
    MODULE_ID = 'load_estimation'
    DEFAULT_INPUT_SUBDIR = 'load_estimation'
    DEFAULT_OUTPUT_SUBDIR = 'load_estimation'
    DEFAULT_INPUT_FILENAME = 'load_data.xlsx'

    def __init__(self):
        super().__init__()
        config_center.register_module(
            self.MODULE_ID,
            self.DEFAULT_INPUT_SUBDIR,
            self.DEFAULT_OUTPUT_SUBDIR,
        )
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']

        config_center.paths_changed.connect(self._on_paths_changed)

        self._worker = None
        self._results = None   # 拟合结果 dict（供画布复用）

        self._build_ui()
        self._refresh_plot_placeholder()
        self.setMinimumHeight(0)
        self.setMinimumSize(0, 0)

    # ---------- 路径变更 ----------
    def _on_paths_changed(self, module_id):
        if module_id and module_id != self.MODULE_ID:
            return
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        if hasattr(self, 'input_edit'):
            cur = self.input_edit.text().strip()
            if not cur or not os.path.isabs(cur):
                # 相对路径或空 → 跟随新 input_dir
                self.input_edit.setText(self._default_input_path())

    def _default_input_path(self):
        return str(Path(self.input_dir) / self.DEFAULT_INPUT_FILENAME)

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # === banner ===
        outer.addWidget(self._build_banner())

        # === 主体 ===
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)

        # 输入/输出
        body_layout.addWidget(self._build_io_group())

        # 拟合曲线查看
        body_layout.addWidget(self._build_plot_group(), 1)

        # 执行栏
        body_layout.addWidget(self._build_exec_bar())

        outer.addWidget(body, 1)

    def _build_banner(self):
        banner = QWidget()
        banner.setObjectName('moduleBanner')
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(4)
        title = QLabel('载荷预估')
        title.setObjectName('moduleTitle')
        title.setAlignment(Qt.AlignCenter)
        tf = QFont('YouSheBiaoTiHei', 16)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        title.setFont(tf)
        sub = QLabel('L O A D   E S T I M A T I O N')
        sub.setObjectName('moduleSubtitle')
        sub.setAlignment(Qt.AlignCenter)
        sf = QFont('Consolas', 8)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        sf.setBold(True)
        sub.setFont(sf)
        bl.addWidget(title)
        bl.addWidget(sub)
        return banner

    def _build_io_group(self):
        box = QGroupBox('输入 / 输出')
        box.setObjectName('gb_data')
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        # 输入 xlsx
        grid.addWidget(QLabel('数据文件:'), 0, 0)
        self.input_edit = QLineEdit(self._default_input_path())
        grid.addWidget(self.input_edit, 0, 1)
        browse_btn = QPushButton('...')
        browse_btn.setMaximumWidth(40)
        browse_btn.clicked.connect(self._on_browse_input)
        grid.addWidget(browse_btn, 0, 2)

        # 输出目录（只读，走 ConfigCenter）
        grid.addWidget(QLabel('输出目录:'), 1, 0)
        self.output_edit = QLineEdit(self.out_dir)
        self.output_edit.setReadOnly(True)
        grid.addWidget(self.output_edit, 1, 1, 1, 2)

        grid.setColumnStretch(1, 1)
        return box

    def _build_plot_group(self):
        box = QGroupBox('拟合曲线')
        box.setObjectName('gb_data')
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # 控制行：下拉 + 上一张/下一张
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        ctrl.addWidget(QLabel('视图:'))
        self.view_combo = QComboBox()
        for opt in VIEW_OPTIONS:
            self.view_combo.addItem(opt)
        self.view_combo.setEnabled(False)
        self.view_combo.currentIndexChanged.connect(self._on_view_changed)
        ctrl.addWidget(self.view_combo, 1)

        self.prev_btn = QPushButton('◀ 上一张')
        self.prev_btn.setEnabled(False)
        self.prev_btn.clicked.connect(self._on_prev_view)
        ctrl.addWidget(self.prev_btn)

        self.next_btn = QPushButton('下一张 ▶')
        self.next_btn.setEnabled(False)
        self.next_btn.clicked.connect(self._on_next_view)
        ctrl.addWidget(self.next_btn)

        layout.addLayout(ctrl)

        # matplotlib 画布
        self.fig = Figure(figsize=(10, 4.5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.canvas, 1)

        return box

    def _build_exec_bar(self):
        wrap = QWidget()
        wrap.setObjectName('execBar')
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap.setFixedHeight(180)

        bar = QHBoxLayout(wrap)
        bar.setContentsMargins(2, 8, 2, 2)
        bar.setSpacing(10)

        # 左侧
        left_wrap = QWidget()
        left_wrap.setFixedWidth(320)
        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.run_btn = QPushButton('运行拟合')
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setObjectName('primaryBtn')
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self._on_run)
        left_layout.addWidget(self.run_btn)

        self.open_btn = QPushButton('📂  打开输出目录')
        self.open_btn.setObjectName('secondaryBtn')
        self.open_btn.setMinimumHeight(36)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._on_open_output)
        left_layout.addWidget(self.open_btn)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        left_layout.addWidget(self.progress)
        left_layout.addStretch()

        # 右侧日志
        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(QLabel('日志:'))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setObjectName('logArea')
        right_layout.addWidget(self.log_area, 1)

        bar.addWidget(left_wrap, 0)
        bar.addWidget(right_wrap, 1)
        return wrap

    # ============================================================
    # 槽
    # ============================================================
    def _on_browse_input(self):
        start = self.input_edit.text() or self.input_dir
        start_dir = str(Path(start).parent) if start else self.input_dir
        path, _ = QFileDialog.getOpenFileName(
            self, '选择数据文件', start_dir, 'Excel 文件 (*.xlsx);;所有文件 (*.*)'
        )
        if path:
            self.input_edit.setText(path)

    def _on_run(self):
        input_path = self.input_edit.text().strip()
        if not input_path or not Path(input_path).exists():
            QMessageBox.warning(self, '文件不存在',
                                f'请检查数据文件：\n{input_path}')
            return
        # 重置 UI
        self.log_area.clear()
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.run_btn.setText('运行中...')
        self.view_combo.setEnabled(False)
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.open_btn.setEnabled(False)

        self._worker = LoadEstimationWorker(input_path, self.out_dir)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, percent, msg):
        if percent >= 0:
            self.progress.setValue(percent)
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    def _on_finished(self):
        self.run_btn.setEnabled(True)
        self.run_btn.setText('运行拟合')
        if self._worker.error:
            QMessageBox.critical(self, '拟合失败', self._worker.error)
            return
        self._results = self._worker.results
        if self._results is None:
            return
        # 启用查看控件
        self.view_combo.setEnabled(True)
        self.prev_btn.setEnabled(True)
        self.next_btn.setEnabled(True)
        self.open_btn.setEnabled(True)
        self._refresh_plot()

    def _on_open_output(self):
        out = Path(self.out_dir)
        if not out.exists():
            out.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith('win'):
            os.startfile(str(out))
        else:
            subprocess.Popen(['xdg-open', str(out)])

    # ----- 画布 -----
    def _refresh_plot_placeholder(self):
        self.ax.clear()
        self.ax.text(
            0.5, 0.5, '点击「运行拟合」开始',
            ha='center', va='center', fontsize=14, transform=self.ax.transAxes,
        )
        self.ax.set_axis_off()
        self.fig.tight_layout()
        self.canvas.draw()

    def _refresh_plot(self):
        if self._results is None:
            return
        view = self.view_combo.currentText()
        kind, name = view.split('-')
        self.ax.clear()
        plot_result(self.ax, self._results, kind, name)
        self.fig.tight_layout()
        self.canvas.draw()

    def _on_view_changed(self, _idx):
        self._refresh_plot()

    def _on_prev_view(self):
        idx = self.view_combo.currentIndex()
        self.view_combo.setCurrentIndex((idx - 1) % self.view_combo.count())

    def _on_next_view(self):
        idx = self.view_combo.currentIndex()
        self.view_combo.setCurrentIndex((idx + 1) % self.view_combo.count())
