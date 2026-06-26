# -*- coding: utf-8 -*-
"""失速评估面板（BaseWorkerPanel 子类）。

业务逻辑见 ``src/stall_assessment/core.py``。

UI 结构（方案 A 左右双栏 + 底部执行栏）：
  - 模块 banner（由基类提供）
  - 左栏：
      · 标准翼型表（QTableWidget，两列：相对厚度 / 失速攻角，可增删行）
      · 展向分布输入（粘贴文本框 + 载入 CSV/xlsx 按钮）
  - 右栏：
      · 上：插值校核图（标准点 + PCHIP 插值曲线）
      · 下：展向分布图（r/R ↔ 失速攻角）
      · 结果表（运行后填入，可复制）
  - 底部执行栏（运行 / 打开目录 / 进度 / 日志，由基类提供）
"""
import os
import sys
import traceback

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPlainTextEdit, QTextEdit, QSplitter, QSizePolicy,
)

# matplotlib 嵌入式画布（导入 plotting 触发 Agg 后端 + 中文字体配置，
# 必须在 pyplot 被使用前完成 —— 与 load_estimation_panel 同模式）
import core.plotting as plotting  # noqa: F401
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from tools.base_module_panel import BaseWorkerPanel
from business.stall_assessment import (
    parse_span_text, parse_span_file,
    interpolate, save_csv, plot_check, plot_span,
)


# 默认标准翼型示例（厚度, 失速攻角°）—— 用户可自由增删
DEFAULT_PROFILE = [
    (0.18, 12.5),
    (0.21, 13.5),
    (0.25, 14.5),
    (0.30, 15.5),
    (0.40, 17.0),
    (0.60, 18.5),
    (1.00, 20.0),
]

# 默认展向分布示例（r/R, 相对厚度）—— 提示用户格式，可清空
DEFAULT_SPAN = """r/R, t/c
0.00, 1.00
0.10, 0.85
0.20, 0.60
0.30, 0.45
0.40, 0.35
0.50, 0.30
0.60, 0.27
0.70, 0.25
0.80, 0.22
0.90, 0.20
1.00, 0.18
"""


# ============================================================
# 后台 Worker
# ============================================================
class StallAssessmentWorker(QThread):
    """读标准表 + 展向分布 → PCHIP 插值 → 写 CSV。

    在 UI 线程外完成计算（数据量小，主要耗时在 CSV 落盘）。
    """
    progress = pyqtSignal(int, str)

    def __init__(self, profile, positions, thickness, output_dir):
        super().__init__()
        # profile: (N,2) ndarray; positions/thickness: 1D ndarray
        self.profile = profile
        self.positions = positions
        self.thickness = thickness
        self.output_dir = output_dir
        # 输出（供主线程取回画图）
        self.span_alpha = None
        self.error = None

    def run(self):
        try:
            self.progress.emit(10, f'标准翼型点：{self.profile.shape[0]} 个')
            self.progress.emit(20, f'展向分布：{self.positions.size} 站')
            self.progress.emit(50, '执行 PCHIP 保形插值...')
            span_alpha = interpolate(
                self.profile[:, 0], self.profile[:, 1], self.thickness,
            )
            self.span_alpha = span_alpha
            self.progress.emit(75, f'写入输出目录：{self.output_dir}')
            out_path = save_csv(self.positions, self.thickness,
                                span_alpha, self.output_dir)
            self.progress.emit(100, '=== 完成 ===')
            self.progress.emit(100, f'  • {os.path.basename(out_path)}')
        except Exception as e:
            self.error = traceback.format_exc()
            self.progress.emit(100, f'[错误] {e}')


# ============================================================
# 主面板
# ============================================================
class StallAssessmentPanel(BaseWorkerPanel):
    MODULE_ID = 'stall_assessment'
    DEFAULT_INPUT_SUBDIR = 'stall_assessment'
    DEFAULT_OUTPUT_SUBDIR = 'stall_assessment'
    MODULE_TITLE = '失速评估'
    MODULE_SUBTITLE = 'S T A L L   A S S E S S M E N T'
    RUN_BUTTON_TEXT = '▶  计算失速攻角'

    def __init__(self):
        self._worker = None
        # 上一次成功结果（供画图复用）
        self._result = None  # dict: profile/positions/thickness/span_alpha
        super().__init__()
        # 基类创建了 run_btn 但未自动连接点击信号，这里连上
        self.run_btn.clicked.connect(self._on_run)

    # ------------------------------------------------------------
    # 主体内容（基类会自动追加 exec_bar）
    # ------------------------------------------------------------
    def _build_main_content(self):
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)

        # === 左栏：输入 ===
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(12, 12, 8, 12)
        left_lay.setSpacing(8)
        left_lay.addWidget(self._build_profile_group())
        left_lay.addWidget(self._build_span_group(), 1)

        # === 右栏：图 + 结果表 ===
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 12, 12, 12)
        right_lay.setSpacing(8)
        right_lay.addWidget(self._build_plot_group(), 1)
        right_lay.addWidget(self._build_result_group(), 1)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([460, 700])
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        wrap = QWidget()
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.addWidget(split, 1)
        return wrap

    # ---------- 标准翼型表 ----------
    def _build_profile_group(self):
        box = QGroupBox('标准翼型表（相对厚度, 失速攻角°）')
        box.setObjectName('gb_data')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(2)
        self.profile_table.setHorizontalHeaderLabels(['相对厚度', '失速攻角 (°)'])
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.profile_table.verticalHeader().setVisible(False)
        self._populate_profile(DEFAULT_PROFILE)
        lay.addWidget(self.profile_table)

        row = QHBoxLayout()
        add_btn = QPushButton('+ 添加')
        add_btn.clicked.connect(self._on_profile_add)
        del_btn = QPushButton('− 删除')
        del_btn.clicked.connect(self._on_profile_del)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addStretch()
        lay.addLayout(row)
        return box

    # ---------- 展向分布输入 ----------
    def _build_span_group(self):
        box = QGroupBox('展向分布（展向位置, 相对厚度）')
        box.setObjectName('gb_data')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        hint = QLabel('每行「展向位置, 相对厚度」，首行可带标题；或从文件载入：')
        hint.setStyleSheet('color: #888;')
        lay.addWidget(hint)

        self.span_edit = QPlainTextEdit()
        self.span_edit.setPlainText(DEFAULT_SPAN)
        lay.addWidget(self.span_edit, 1)

        row = QHBoxLayout()
        load_btn = QPushButton('📂 载入 CSV/xlsx')
        load_btn.clicked.connect(self._on_load_file)
        clear_btn = QPushButton('清空')
        clear_btn.clicked.connect(lambda: self.span_edit.clear())
        row.addWidget(load_btn)
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)
        return box

    # ---------- 画图区 ----------
    def _build_plot_group(self):
        box = QGroupBox('图')
        box.setObjectName('gb_data')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        self.fig = Figure(figsize=(7, 5), dpi=100)
        self.ax_check = self.fig.add_subplot(211)
        self.ax_span = self.fig.add_subplot(212)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.canvas, 1)
        self._refresh_plot_placeholder()
        return box

    # ---------- 结果表 ----------
    def _build_result_group(self):
        box = QGroupBox('结果（可复制）')
        box.setObjectName('gb_data')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(
            ['展向位置 (r/R)', '相对厚度', '失速攻角 (°)'])
        self.result_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_table.verticalHeader().setVisible(False)
        lay.addWidget(self.result_table, 1)

        row = QHBoxLayout()
        copy_btn = QPushButton('📋 复制结果')
        copy_btn.clicked.connect(self._on_copy_result)
        row.addWidget(copy_btn)
        row.addStretch()
        lay.addLayout(row)
        return box

    # ============================================================
    # 槽
    # ============================================================
    def _populate_profile(self, pts):
        """用 (厚度, 攻角) 列表填标准翼型表。"""
        t = self.profile_table
        t.setRowCount(len(pts))
        for r, (th, al) in enumerate(pts):
            t.setItem(r, 0, QTableWidgetItem(f'{th:g}'))
            t.setItem(r, 1, QTableWidgetItem(f'{al:g}'))

    def _on_profile_add(self):
        t = self.profile_table
        r = t.rowCount()
        t.insertRow(r)
        t.setItem(r, 0, QTableWidgetItem('0.30'))
        t.setItem(r, 1, QTableWidgetItem('15.0'))

    def _on_profile_del(self):
        t = self.profile_table
        rows = sorted({idx.row() for idx in t.selectedIndexes()}, reverse=True)
        if not rows:
            r = t.rowCount() - 1
            if r >= 0:
                t.removeRow(r)
        else:
            for r in rows:
                t.removeRow(r)

    def _on_load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '载入展向分布', self.input_dir,
            '数据文件 (*.csv *.txt *.xlsx *.xls);;所有文件 (*.*)',
        )
        if not path:
            return
        try:
            positions, thickness = parse_span_file(path)
        except Exception as e:
            self.log_area.append(f'⚠ 载入失败：{e}')
            return
        # 回填到文本框（带表头）
        lines = ['r/R, t/c']
        for p, th in zip(positions, thickness):
            lines.append(f'{p:.6g}, {th:.6g}')
        self.span_edit.setPlainText('\n'.join(lines))
        self.log_area.append(f'✓ 已载入 {positions.size} 行：{path}')

    def _read_profile(self):
        """从标准表读 (N, 2) ndarray。返回 None 表示无有效行。"""
        t = self.profile_table
        pts = []
        for r in range(t.rowCount()):
            item0, item1 = t.item(r, 0), t.item(r, 1)
            if item0 is None or item1 is None:
                continue
            try:
                a = float(item0.text())
                b = float(item1.text())
            except ValueError:
                continue
            pts.append((a, b))
        return pts

    def _on_run(self):
        # 1. 读标准表
        pts = self._read_profile()
        if not pts or len(pts) < 2:
            self.log_area.append('⚠ 标准翼型表至少需要 2 个有效行。')
            return
        import numpy as np
        profile = np.array(pts, dtype=float)

        # 2. 读展向分布
        text = self.span_edit.toPlainText().strip()
        if not text:
            self.log_area.append('⚠ 展向分布为空，请粘贴数据或载入文件。')
            return
        try:
            positions, thickness = parse_span_text(text)
        except Exception as e:
            self.log_area.append(f'⚠ 展向分布解析失败：{e}')
            return

        # 3. 启动 Worker
        self.log_area.clear()
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.run_btn.setText('计算中...')
        self.open_btn.setEnabled(False)

        self._worker = StallAssessmentWorker(
            profile, positions, thickness, self.out_dir,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(lambda: self._on_finished(profile, positions, thickness))
        self._worker.start()

    def _on_finished(self, profile, positions, thickness):
        self.run_btn.setEnabled(True)
        self.run_btn.setText(self.RUN_BUTTON_TEXT)
        if self._worker.error:
            return  # 错误信息已由 progress 写入日志
        span_alpha = self._worker.span_alpha
        if span_alpha is None:
            return

        # 缓存结果
        import numpy as np
        self._result = {
            'profile': profile,
            'positions': positions,
            'thickness': thickness,
            'span_alpha': np.asarray(span_alpha),
        }
        # 填结果表
        self.result_table.setRowCount(positions.size)
        for i in range(positions.size):
            self.result_table.setItem(i, 0, QTableWidgetItem(f'{positions[i]:.6g}'))
            self.result_table.setItem(i, 1, QTableWidgetItem(f'{thickness[i]:.6g}'))
            self.result_table.setItem(i, 2, QTableWidgetItem(f'{span_alpha[i]:.4f}'))
        # 刷新画图
        self._refresh_plot()
        self.open_btn.setEnabled(True)

    def _on_copy_result(self):
        if self._result is None:
            return
        import numpy as np
        positions = self._result['positions']
        thickness = self._result['thickness']
        span_alpha = self._result['span_alpha']
        lines = ['span_position,relative_thickness,stall_alpha_deg']
        for i in range(positions.size):
            lines.append(f'{positions[i]:.6g},{thickness[i]:.6g},{span_alpha[i]:.4f}')
        QApplication_clipboard('\n'.join(lines))
        self.log_area.append(f'✓ 已复制 {positions.size} 行到剪贴板')

    # ============================================================
    # 画布
    # ============================================================
    def _refresh_plot_placeholder(self):
        for ax in (self.ax_check, self.ax_span):
            ax.clear()
            ax.text(0.5, 0.5, '点击「计算失速攻角」开始',
                    ha='center', va='center', fontsize=12,
                    transform=ax.transAxes)
            ax.set_axis_off()
        self.fig.tight_layout()
        self.canvas.draw()

    def _refresh_plot(self):
        if self._result is None:
            return
        self.ax_check.clear()
        self.ax_span.clear()
        plot_check(self.ax_check,
                   self._result['profile'][:, 0],
                   self._result['profile'][:, 1],
                   self._result['thickness'],
                   self._result['span_alpha'])
        plot_span(self.ax_span,
                  self._result['positions'],
                  self._result['span_alpha'])
        self.fig.tight_layout()
        self.canvas.draw()


# Qt 已在顶部导入（Qt.Horizontal 供 QSplitter 使用）。


def QApplication_clipboard(text):
    """跨平台写剪贴板（避免在模块顶部 import QApplication 的副作用）。"""
    from PyQt5.QtWidgets import QApplication
    QApplication.clipboard().setText(text)
