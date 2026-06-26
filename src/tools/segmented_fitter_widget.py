# -*- coding: utf-8 -*-
"""分段复用拟合 widget（曲线拟合模块 Tab 2）。

左段 [0, R1]：锁定原数据（来自 STAGE-1 几何表或 CSV）。
中段 [R1, R2]：用 B 样条拟合用户控制点，在两个分段点处强制双端 C2 连续。
右段 [R2, 1]：锁定原数据（R2=1.0 时无右段，退化为单分段点）。

算法在 ``src/curve_fitter/segmented_fit.py``，本文件只负责 UI + matplotlib 交互。
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import numpy as np

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextOption, QTextCursor, QTextCharFormat, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QPushButton, QLabel, QFileDialog,
    QDoubleSpinBox, QSpinBox, QMessageBox, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QFrame, QSizePolicy, QPlainTextEdit, QTextEdit,
)

# matplotlib 嵌入（import plotting 触发中文字体配置）
import core.plotting as plotting  # noqa: F401
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.lines import Line2D

from business.curve_fitter import (
    merge_and_export,
    fit_middle_segment, make_default_middle_ctrl,
)


# 拖动命中半径（数据坐标，会动态换算）
_DRAG_TOL_PX = 8


class SegmentedFitterWidget(QWidget):
    """分段复用拟合：左段锁定 + 中段 B 样条拟合 + 双端 C2 连续。"""

    def __init__(self, default_xlsx_dir: str = '', default_output_dir: str = '',
                 log_callback=None, parent=None):
        super().__init__(parent)
        self._xlsx_dir = default_xlsx_dir
        self._output_dir = default_output_dir
        # v0.3.12: 弹窗改为日志写入。外部未传 callback 时用内部 _write_log（绑定时延后到 UI 创建完）
        self._external_log = log_callback
        self._log = log_callback or (lambda msg, level='info': None)

        # 运行时状态
        self.span_ratio: np.ndarray | None = None   # 归一化展向 [0..1]
        self.values: np.ndarray | None = None       # 原始 Y 值
        self.source_label: str = ''                  # 显示用：「Prebend」/「CSV: xxx.csv」
        self.last_result = None                      # SegmentedFitResult

        # 中段控制点（X 等距由 R1/R2+点数生成；Y 用户可编辑/拖动；v0.3.10 起 X 也可拖）
        self.ctrl_x: np.ndarray | None = None
        self.ctrl_y: np.ndarray | None = None

        # 拖动状态
        self._dragging_idx: int | None = None

        # 防抖：参数 spinbox / 表格连续改动时，停 200ms 才重拟合
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(200)
        self._fit_timer.timeout.connect(self._refresh_plot)

        self._build_ui()

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_ui(self):
        """布局对齐 Tab 1（全段拟合）：左画布 + 右侧参数栏（含数据输入）。

        - 左：整个画布（QGroupBox '分段拟合预览'）
        - 右：QScrollArea 包「数据输入 + 分段与拟合 + 中段控制点表 + 状态 + 输出」
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        body = QSplitter(Qt.Horizontal)

        # ---- 左：画布 ----
        plot_box = QGroupBox('分段拟合预览')
        plot_box.setObjectName('gb_data')
        plot_lay = QVBoxLayout(plot_box)
        plot_lay.setContentsMargins(8, 6, 8, 6)
        self.fig, self.ax = self._make_figure()
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setParent(self)
        plot_lay.addWidget(self.canvas, 1)
        self.hint_label = QLabel('请先加载数据')
        self.hint_label.setStyleSheet('color: #888; padding: 4px;')
        plot_lay.addWidget(self.hint_label)
        body.addWidget(plot_box)

        # ---- 右：数据输入 + 参数 + 控制点表 + 状态 + 输出 ----
        body.addWidget(self._build_param_panel())
        body.setSizes([620, 380])
        body.setStretchFactor(0, 3)
        body.setStretchFactor(1, 2)
        outer.addWidget(body, 1)

        self._connect_canvas()

    def _make_figure(self):
        fig = Figure(figsize=(7, 5), dpi=100)
        ax = fig.add_subplot(111)
        ax.set_xlabel('归一化展向 (r/R)')
        ax.set_ylabel('值')
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig, ax

    def _build_data_input(self):
        """数据输入区：QPlainTextEdit + 载入文件 / 解析 / 清除 三按钮。

        v0.3.11 起对齐 Tab 1（全段拟合）的交互模式：
        点「📂 载入文件」选 txt/csv → 文本进 QPlainTextEdit → 点「⚙ 解析」提取 (X, Y)。
        用户也可直接粘贴两列数据进编辑框。
        """
        box = QGroupBox('数据输入')
        box.setObjectName('gb_data')
        outer = QVBoxLayout(box)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(6)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.load_btn = QPushButton('📂 载入文件')
        self.load_btn.clicked.connect(self._on_load_file)
        self.parse_btn = QPushButton('⚙ 解析')
        self.parse_btn.setObjectName('primaryBtn')
        self.parse_btn.clicked.connect(self._on_parse)
        self.clear_btn = QPushButton('🗑 清除')
        self.clear_btn.clicked.connect(self._on_clear_data)
        btn_row.addWidget(self.load_btn)
        btn_row.addWidget(self.parse_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        outer.addWidget(QLabel('数据（第 1 列 X 展向位置，第 2 列 Y 值；空白 / # 跳过）：'))
        self.data_edit = QPlainTextEdit()
        self.data_edit.setPlaceholderText(
            '粘贴两列数据，或点「📂 载入文件」读取 txt/csv。\n'
            'X 会自动归一化到 [0, 1] 作为 r/R。'
        )
        self.data_edit.setMaximumHeight(160)
        # v0.3.12: 强制 widgetWidth 换行，长行不撑大水平 sizeHint（解析后右栏宽度抖动根因）
        self.data_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.data_edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        outer.addWidget(self.data_edit, 1)
        return box

    def _build_param_panel(self):
        wrap = QWidget()
        outer_lay = QVBoxLayout(wrap)
        outer_lay.setContentsMargins(0, 0, 0, 0)
        outer_lay.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)
        v = QVBoxLayout(inner)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # ---- 数据输入（v0.3.11 起从顶部挪到右侧栏顶部）----
        v.addWidget(self._build_data_input())

        # ---- 分段与拟合参数 ----
        fit_box = QGroupBox('分段与拟合')
        fit_box.setObjectName('gb_data')
        gf = QGridLayout(fit_box)
        gf.setContentsMargins(10, 8, 10, 8)
        gf.setSpacing(6)

        gf.addWidget(QLabel('分段点 R1 (r/R):'), 0, 0)
        self.split_spin = QDoubleSpinBox()
        self.split_spin.setRange(0.10, 0.95)
        self.split_spin.setSingleStep(0.01)
        self.split_spin.setDecimals(2)
        self.split_spin.setValue(0.50)
        self.split_spin.setToolTip('左复用段 [0, R1] 锁定原数据；中段 [R1, R2] 可重设')
        self.split_spin.valueChanged.connect(self._on_split1_changed)
        gf.addWidget(self.split_spin, 0, 1)

        gf.addWidget(QLabel('分段点 R2 (r/R):'), 1, 0)
        self.split_spin2 = QDoubleSpinBox()
        self.split_spin2.setRange(0.15, 1.00)
        self.split_spin2.setSingleStep(0.01)
        self.split_spin2.setDecimals(2)
        self.split_spin2.setValue(0.70)
        self.split_spin2.setToolTip(
            '右复用段 [R2, 1] 锁定原数据。\n'
            'R2 = 1.00 时退化为单分段点（无右复用段，仅 [0, R1] + [R1, 1]）。'
        )
        self.split_spin2.valueChanged.connect(self._on_split2_changed)
        gf.addWidget(self.split_spin2, 1, 1)

        gf.addWidget(QLabel('连续性:'), 2, 0)
        self.cont_label = QLabel('C2 (双端二阶导连续)')
        self.cont_label.setStyleSheet('color: #0ea5e9; font-weight: bold;')
        gf.addWidget(self.cont_label, 2, 1)

        gf.addWidget(QLabel('B 样条阶数 k:'), 3, 0)
        self.k_spin = QSpinBox()
        self.k_spin.setRange(5, 7)
        self.k_spin.setValue(5)
        self.k_spin.setToolTip(
            '阶数 k=5 五次样条（双端 C2 最低要求，左 2 + 右 2 = 4 = k-1）。\n'
            '增大 k 拟合更平滑但需更多控制点。'
        )
        self.k_spin.valueChanged.connect(self._on_param_changed)
        gf.addWidget(self.k_spin, 3, 1)

        gf.addWidget(QLabel('中段控制点数:'), 4, 0)
        self.nctrl_spin = QSpinBox()
        self.nctrl_spin.setRange(5, 15)
        self.nctrl_spin.setValue(5)
        self.nctrl_spin.setToolTip('中段控制点数量（不含 R1/R2 端点）。变化时 Y 会从旧点线性重采样到新点数')
        self.nctrl_spin.valueChanged.connect(self._on_nctrl_changed)
        gf.addWidget(self.nctrl_spin, 4, 1)

        v.addWidget(fit_box)

        # ---- 控制点表 ----
        ctrl_box = QGroupBox('中段控制点（拖动画布红点 / 编辑表格）')
        ctrl_box.setObjectName('gb_data')
        cv = QVBoxLayout(ctrl_box)
        cv.setContentsMargins(10, 8, 10, 8)
        cv.setSpacing(6)

        self.ctrl_table = QTableWidget(0, 2)
        self.ctrl_table.setHorizontalHeaderLabels(['X (r/R)', 'Y'])
        self.ctrl_table.verticalHeader().setVisible(False)
        self.ctrl_table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.ctrl_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.ctrl_table.setFocusPolicy(Qt.StrongFocus)
        self.ctrl_table.itemDoubleClicked.connect(self._on_table_edit_begin)
        self.ctrl_table.itemChanged.connect(self._on_table_item_changed)
        hdr = self.ctrl_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        cv.addWidget(self.ctrl_table)

        tip_lbl = QLabel('提示：画布上拖动红点可同时调整 X、Y（X 自动避开邻居和 R1/R2 边界）。也可双击表格精确编辑。')
        tip_lbl.setWordWrap(True)
        tip_lbl.setStyleSheet('color: #888; font-size: 11px;')
        cv.addWidget(tip_lbl)

        v.addWidget(ctrl_box, 1)

        # ---- 分段点状态 ----
        self.status_label = QLabel('分段点处：—')
        self.status_label.setStyleSheet('padding: 4px; background: #f5f5f5;')
        v.addWidget(self.status_label)

        # ---- 输出 ----
        out_box = QGroupBox('输出')
        out_box.setObjectName('gb_data')
        ov = QHBoxLayout(out_box)
        ov.setContentsMargins(10, 6, 10, 6)
        self.export_btn = QPushButton('💾 导出合并曲线 CSV')
        self.export_btn.setObjectName('primaryBtn')
        self.export_btn.setToolTip('导出左段 + 中段 + 右段的合并曲线到 CSV')
        self.export_btn.clicked.connect(self._on_export)
        ov.addWidget(self.export_btn)
        v.addWidget(out_box)

        # ---- 运行日志（v0.3.12: 解析/导出状态写这里，不再弹窗）----
        log_box = QGroupBox('运行日志')
        log_box.setObjectName('gb_data')
        lv = QVBoxLayout(log_box)
        lv.setContentsMargins(10, 6, 10, 6)
        lv.setSpacing(4)
        log_head = QHBoxLayout()
        log_head.setSpacing(6)
        log_tip = QLabel('解析 / 导出的运行情况都写在这里（不再弹窗）')
        log_tip.setStyleSheet('color: #666; font-size: 11px;')
        log_head.addWidget(log_tip)
        log_head.addStretch()
        log_clear = QPushButton('🗑 清空')
        log_clear.clicked.connect(lambda: self.log_view.clear())
        log_head.addWidget(log_clear)
        lv.addLayout(log_head)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName('logView')
        self.log_view.setFixedHeight(120)
        log_mono = QFont('Consolas')
        log_mono.setStyleHint(QFont.Monospace)
        self.log_view.setFont(log_mono)
        lv.addWidget(self.log_view, 1)
        v.addWidget(log_box, 1)

        v.addStretch()

        # 外部未传 log_callback 时，绑定内部 _write_log（依赖 self.log_view，创建后切换）
        if self._external_log is None:
            self._log = self._write_log
        outer_lay.addWidget(scroll)
        # 关键：splitter 默认用 child 的 sizeHint 当 min size，scrollarea 会被撑到
        # 内容自然高，没法缩小 → 滚动条永远不出现。设 minimumHeight=0 让它能被压扁
        inner.setMinimumHeight(0)
        scroll.setMinimumHeight(0)
        wrap.setMinimumHeight(0)
        # v0.3.12: 横向 sizeHint 也忽略，避免 data_edit 解析后 sizeHint 变化导致
        # splitter 重新分配宽度（用户反馈"解析后右栏变窄、按钮被截断"）
        wrap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        inner.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        return wrap

    # ============================================================
    # 数据输入：载入文件 / 解析 / 清除（对齐 Tab 1 模式）
    # ============================================================
    def _on_load_file(self):
        """选 txt/csv 文件，把文本读进 data_edit（不解析）。"""
        path, _ = QFileDialog.getOpenFileName(
            self, '选择数据文件',
            self._xlsx_dir or '',
            '文本 (*.txt *.csv *.dat);;所有文件 (*.*)'
        )
        if not path:
            return
        try:
            text = None
            for enc in ('utf-8', 'latin-1', 'utf-16', 'gbk', 'cp936', 'gb2312', 'big5'):
                try:
                    with open(path, 'r', encoding=enc) as f:
                        text = f.read()
                    break
                except (UnicodeDecodeError, OSError):
                    continue
            if text is None:
                try:
                    import chardet
                    with open(path, 'rb') as f:
                        raw = f.read()
                    enc = chardet.detect(raw).get('encoding') or 'utf-8'
                    text = raw.decode(enc, errors='replace')
                except Exception:
                    text = ''
            self.data_edit.setPlainText(text)
        except Exception as e:
            self._log(f'读取文件失败：{e}', 'error')

    def _on_parse(self):
        """解析 data_edit 文本：第 1 列 X（归一化到 [0,1]），第 2 列 Y。"""
        text = self.data_edit.toPlainText()
        if not text.strip():
            self._log('解析失败：数据为空', 'warning')
            return
        # 解析两列（沿用 curve_fitter.parse_data 的多列、空白、注释处理）
        try:
            from business.curve_fitter import parse_data, MAX_ROWS
            data, _labels = parse_data(text, max_rows=MAX_ROWS)
        except Exception as e:
            self._log(f'解析失败：{e}', 'error')
            return
        if data.shape[1] < 2:
            self._log('解析失败：至少需要两列（X, Y）', 'warning')
            return
        xs = data[:, 0].astype(float)
        ys = data[:, 1].astype(float)
        # X 归一化到 [0, 1]（r/R）。按 min/max 缩放，避免数据逆序导致出错
        x_min, x_max = float(xs.min()), float(xs.max())
        if x_max - x_min < 1e-12:
            self._log('解析失败：X 列全部相等，无法归一化', 'warning')
            return
        # 强制升序（分段拟合要求 span_ratio 单调递增）
        order = np.argsort(xs, kind='stable')
        xs = xs[order]
        ys = ys[order]
        self.span_ratio = (xs - x_min) / (x_max - x_min)
        self.values = ys
        self.source_label = '解析数据'
        # 初始化中段控制点 Y（贴合原曲线）
        self._init_middle_ctrl_from_data()
        self.hint_label.setText(
            f'已解析 {len(self.span_ratio)} 点 — X 归一化到 [0, 1]'
        )
        self.hint_label.setStyleSheet('color: #888; padding: 4px;')
        self._log(f'分段复用：解析完成，共 {len(self.span_ratio)} 点', 'success')
        self._refresh_plot()

    def _on_clear_data(self):
        """清除数据 + 编辑框 + 拟合结果，回到初始状态。"""
        self.span_ratio = None
        self.values = None
        self.source_label = ''
        self.last_result = None
        self.ctrl_x = None
        self.ctrl_y = None
        self.data_edit.clear()
        self.ctrl_table.setRowCount(0)
        self.status_label.setText('分段点处：—')
        self.hint_label.setText('请先加载数据')
        self.hint_label.setStyleSheet('color: #888; padding: 4px;')
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('归一化展向 (r/R)')
        self.ax.set_ylabel('值')
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _init_middle_ctrl_from_data(self):
        """根据当前 R1/R2 + 控制点数，从原始数据生成中段控制点。

        控制点 Y = 原始曲线在 ctrl_x 处的值（np.interp），让初始状态贴合原曲线。
        """
        if self.values is None:
            return
        # _resample_ctrl_for_split_change 已经实现了"基于原曲线插值"逻辑，直接复用
        self._resample_ctrl_for_split_change()

    # ============================================================
    # 参数变化
    # ============================================================
    def _enforce_split_order(self):
        """保证 R1 < R2 - 0.05（最小中段宽度 0.05）。

        调用方在 spinbox valueChanged 时先调此方法，再触发重拟合。
        返回 True 表示发生过调整（信号已被 block，调用方需自行触发重拟合）。
        """
        r1 = self.split_spin.value()
        r2 = self.split_spin2.value()
        adjusted = False
        if r2 <= r1 + 0.05:
            # 把 R2 推到 R1 + 0.05（优先调 R2，保留用户刚改的 R1）
            new_r2 = min(1.0, r1 + 0.05)
            self.split_spin2.blockSignals(True)
            self.split_spin2.setValue(new_r2)
            self.split_spin2.blockSignals(False)
            adjusted = True
        return adjusted

    def _on_split1_changed(self):
        """R1 变化：必要时强制 R2 = R1 + 0.05，然后重采样中段控制点。"""
        self._enforce_split_order()
        self._resample_ctrl_for_split_change()
        self._fit_timer.start()

    def _on_split2_changed(self):
        """R2 变化：必要时强制 R1 = R2 - 0.05，然后重采样中段控制点。"""
        # 反向强制：R1 太接近 R2 时往下推
        r1 = self.split_spin.value()
        r2 = self.split_spin2.value()
        if r1 >= r2 - 0.05:
            new_r1 = max(0.10, r2 - 0.05)
            self.split_spin.blockSignals(True)
            self.split_spin.setValue(new_r1)
            self.split_spin.blockSignals(False)
        self._resample_ctrl_for_split_change()
        self._fit_timer.start()

    def _resample_ctrl_for_split_change(self):
        """R1/R2 变化后，把旧控制点 (x, y) 重采样到新的 [R1, R2] 内等距 X 分布。

        Y 用 np.interp 从旧 (x, y) 插值；如果旧 X 不在新范围内，先 projection 到原曲线。
        """
        if self.values is None or self.span_ratio is None:
            return
        r1 = self.split_spin.value()
        r2 = self.split_spin2.value()
        # 端点 Y hint
        left_mask = self.span_ratio <= r1
        r1_y = float(self.values[left_mask][-1]) if left_mask.any() else float(self.values[0])
        if r2 >= 1.0:
            r2_y_hint = float(self.values[-1])
        else:
            right_mask = self.span_ratio >= r2
            r2_y_hint = float(self.values[right_mask][0]) if right_mask.any() else float(self.values[-1])
        new_x, _ = make_default_middle_ctrl(
            r1_x=r1, r2_x=r2, r1_y=r1_y, r2_y_hint=r2_y_hint,
            n_points=self.nctrl_spin.value(),
        )
        # 把控制点 Y 重采样到原曲线上的对应 X（更直观：用户看到的是原曲线形状）
        if len(new_x) > 0:
            new_y = np.interp(new_x, self.span_ratio, self.values)
        else:
            new_y = np.array([])
        self.ctrl_x, self.ctrl_y = new_x, new_y
        self._populate_table()

    def _on_param_changed(self):
        """阶数 k 变化：直接重画（控制点不变）。"""
        self._fit_timer.start()

    def _on_nctrl_changed(self):
        """中段控制点数变化：把旧 Y 重采样到新点数。"""
        if self.values is None or self.span_ratio is None:
            self._fit_timer.start()
            return
        # 用 _resample_ctrl_for_split_change 的逻辑（基于原曲线插值）
        self._resample_ctrl_for_split_change()
        self._fit_timer.start()

    # ============================================================
    # 控制点表
    # ============================================================
    def _populate_table(self):
        """把 ctrl_x / ctrl_y 填到表格（blockSignals 避免触发 itemChanged）。"""
        if self.ctrl_x is None:
            return
        self.ctrl_table.blockSignals(True)
        self.ctrl_table.setRowCount(len(self.ctrl_x))
        for i, (x, y) in enumerate(zip(self.ctrl_x, self.ctrl_y)):
            x_item = QTableWidgetItem(f'{x:.4f}')
            y_item = QTableWidgetItem(f'{y:.6g}')
            x_item.setData(Qt.UserRole, float(x))
            y_item.setData(Qt.UserRole, float(y))
            self.ctrl_table.setItem(i, 0, x_item)
            self.ctrl_table.setItem(i, 1, y_item)
        self.ctrl_table.blockSignals(False)

    def _on_table_edit_begin(self, item):
        # 占位：目前不需要特殊处理，表格原生编辑即可
        pass

    def _on_table_item_changed(self, item):
        """表格被编辑：同步到 ctrl_x / ctrl_y，重画（防抖）。"""
        row = item.row()
        col = item.column()
        if self.ctrl_x is None or row >= len(self.ctrl_x):
            return
        try:
            val = float(item.text())
        except ValueError:
            return  # 非法输入忽略，保留旧值（不强制回写避免打断编辑）
        if col == 0:
            # X 编辑：必须保持严格递增 + 在 (R1, R2) 开区间内
            new_x = self.ctrl_x.copy()
            new_x[row] = val
            r1 = self.split_spin.value()
            r2 = self.split_spin2.value()
            if val <= r1 or val >= r2:
                return
            if not np.all(np.diff(new_x) > 0):
                return
            self.ctrl_x = new_x
        else:
            new_y = self.ctrl_y.copy()
            new_y[row] = val
            self.ctrl_y = new_y
        self._fit_timer.start()

    # ============================================================
    # 画布交互（拖动控制点）
    # ============================================================
    def _connect_canvas(self):
        self.canvas.mpl_connect('button_press_event', self._on_press)
        self.canvas.mpl_connect('motion_notify_event', self._on_motion)
        self.canvas.mpl_connect('button_release_event', self._on_release)

    def _on_press(self, event):
        if event.inaxes is not self.ax or self.ctrl_x is None:
            return
        if event.button != 1:  # 仅左键
            return
        # 命中测试：把控制点位置转 display 坐标比距离
        idx = self._pick_control_point(event)
        if idx is not None:
            self._dragging_idx = idx

    def _on_motion(self, event):
        if self._dragging_idx is None or event.inaxes is not self.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        idx = self._dragging_idx
        new_x = float(event.xdata)
        new_y = float(event.ydata)
        # X 约束：必须在 (R1, R2) 开区间内 + 与邻居保持严格递增
        # v0.3.10 起放开 X 拖动（原先锁定等距）
        r1 = self.split_spin.value()
        r2 = self.split_spin2.value()
        eps = 1e-4
        lo = r1 + eps
        hi = r2 - eps
        if idx > 0:
            lo = max(lo, float(self.ctrl_x[idx - 1]) + eps)
        if idx < len(self.ctrl_x) - 1:
            hi = min(hi, float(self.ctrl_x[idx + 1]) - eps)
        # clamp 到合法范围（lo > hi 时不动 X，只动 Y）
        if lo < hi:
            new_x = max(lo, min(hi, new_x))
            self.ctrl_x[idx] = new_x
        self.ctrl_y[idx] = new_y
        # 同步表格 + 重画
        self._populate_table()
        self._refresh_plot()

    def _on_release(self, event):
        self._dragging_idx = None

    def _pick_control_point(self, event):
        """返回命中的控制点 index，无命中返回 None。"""
        if self.ctrl_x is None:
            return None
        # display 坐标距离判断
        event_px = self.ax.transData.transform((event.xdata, event.ydata))
        best_idx, best_dist = None, _DRAG_TOL_PX
        for i, (x, y) in enumerate(zip(self.ctrl_x, self.ctrl_y)):
            px = self.ax.transData.transform((x, y))
            d = np.hypot(px[0] - event_px[0], px[1] - event_px[1])
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    # ============================================================
    # 拟合 + 画图
    # ============================================================
    def _refresh_plot(self):
        """重算拟合 + 重画。"""
        if self.values is None or self.ctrl_x is None:
            return
        r1 = self.split_spin.value()
        r2 = self.split_spin2.value()
        k = self.k_spin.value()

        # 切左段
        left_mask = self.span_ratio <= r1
        if left_mask.sum() < 4:
            self.hint_label.setText(
                f'左段点数过少（{left_mask.sum()}），请降低 R1'
            )
            self.hint_label.setStyleSheet('color: #d97706; padding: 4px;')
            return
        left_x = self.span_ratio[left_mask]
        left_y = self.values[left_mask]

        # 切右段（R2 < 1.0 时启用；R2 = 1.0 时无右段）
        if r2 < 1.0 - 1e-6:
            right_mask = self.span_ratio >= r2
            if right_mask.sum() < 4:
                self.hint_label.setText(
                    f'右段点数过少（{right_mask.sum()}），请提高 R2'
                )
                self.hint_label.setStyleSheet('color: #d97706; padding: 4px;')
                return
            right_x = self.span_ratio[right_mask]
            right_y = self.values[right_mask]
        else:
            right_x = None
            right_y = None

        try:
            self.last_result = fit_middle_segment(
                left_x, left_y,
                right_x, right_y,
                self.ctrl_x, self.ctrl_y,
                continuity='C2', k=k,
            )
        except ValueError as e:
            self.hint_label.setText(f'拟合失败：{e}')
            self.hint_label.setStyleSheet('color: #e86452; padding: 4px;')
            self.ax.clear()
            self.canvas.draw_idle()
            return

        self._draw(self.last_result)
        self.hint_label.setText(
            f'已加载 {len(self.span_ratio)} 点 — {self.source_label}'
        )
        self.hint_label.setStyleSheet('color: #888; padding: 4px;')

    def _draw(self, res):
        self.ax.clear()
        self.ax.grid(True, alpha=0.3)
        self.ax.set_xlabel('归一化展向 (r/R)')
        self.ax.set_ylabel('值')

        # 左复用段（灰实线）
        self.ax.plot(res.left_x, res.left_y, color='#888', lw=2.2,
                     label='左复用段（锁定）', zorder=3)
        # 右复用段（灰实线，仅 has_right）
        if res.has_right:
            self.ax.plot(res.right_x, res.right_y, color='#888', lw=2.2,
                         label='右复用段（锁定）', zorder=3)

        # 中段拟合（蓝实线）
        self.ax.plot(res.middle_x, res.middle_y, color='#1e3a5f', lw=2.0,
                     label='中段拟合 (双端 C2)', zorder=4)

        # 中段控制点（红圆，X/Y 都可拖）—— 仅 ctrl_x/y，不含 R1/R2 端点
        self.ax.scatter(self.ctrl_x, self.ctrl_y,
                        color='#e86452', s=80, zorder=6,
                        edgecolors='black', linewidths=1.0,
                        label='中段控制点（X/Y 都可拖）')

        # 两个分段点（黑色 X 标记）
        self.ax.scatter([res.r1_x], [res.r1_y],
                        marker='X', color='#444', s=100, zorder=7,
                        label=f'R1 = {res.r1_x:.2f}')
        if res.has_right:
            self.ax.scatter([res.r2_x], [res.r2_y],
                            marker='X', color='#444', s=100, zorder=7,
                            label=f'R2 = {res.r2_x:.2f}')

        # 两条分段点竖虚线（R1, R2）
        self.ax.axvline(res.r1_x, color='#0ea5e9', ls='--', lw=1.0,
                        alpha=0.6, zorder=2)
        if res.has_right:
            self.ax.axvline(res.r2_x, color='#0ea5e9', ls='--', lw=1.0,
                            alpha=0.6, zorder=2)

        self.ax.legend(loc='best', fontsize=9)
        self.fig.tight_layout()
        self.canvas.draw_idle()

        # 状态标签（双段格式）
        if res.has_right:
            self.status_label.setText(
                f"R1={res.r1_x:.2f}: y={res.r1_y:.4g}, "
                f"y'={res.r1_dy:.4g}, y''={res.r1_ddy:.4g}  |  "
                f"R2={res.r2_x:.2f}: y={res.r2_y:.4g}, "
                f"y'={res.r2_dy:.4g}, y''={res.r2_ddy:.4g}  "
                f"（左/右段端部局部样条估计，作为中段 C2 约束）"
            )
        else:
            # 退化情形：只显示 R1 约束 + R2（叶尖）自由
            self.status_label.setText(
                f"R1={res.r1_x:.2f}: y={res.r1_y:.4g}, "
                f"y'={res.r1_dy:.4g}, y''={res.r1_ddy:.4g}  |  "
                f"R2=1.00（退化，叶尖自由）"
            )

    # ============================================================
    # 导出
    # ============================================================
    def _on_export(self):
        if self.last_result is None:
            self._log('导出失败：请先加载数据并完成拟合', 'warning')
            return
        default_name = self._default_export_name()
        default_path = os.path.join(self._output_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, '导出合并曲线 CSV', default_path, 'CSV 文件 (*.csv)'
        )
        if not path:
            return
        try:
            abs_path = merge_and_export(self.last_result, path)
        except Exception as e:
            self._log(f'导出失败：{e}', 'error')
            return
        msg = (
            f'分段复用：导出成功 → {abs_path}（'
            f'左段 {len(self.last_result.left_x)} + '
            f'中段 {len(self.last_result.middle_x)}'
            + (f' + 右段 {len(self.last_result.right_x)}' if self.last_result.has_right else '')
            + f' = 共 {len(self.last_result.full_x)} 行）'
        )
        self._log(msg, 'success')

    def _default_export_name(self) -> str:
        ts = datetime.now().strftime('%Y%m%d-%H%M%S')
        return f'segmented_fit_{ts}.csv'

    def _write_log(self, msg: str, level: str = 'info'):
        """写入内部日志栏（位于右侧参数面板底部）。

        level ∈ {'info', 'success', 'warning', 'error'}，
        分别对应黑 / 绿 / 橙 / 红色文本，前缀 [HH:MM:SS]。
        """
        colors = {
            'info':    '#374151',
            'success': '#15803d',
            'warning': '#b45309',
            'error':   '#b91c1c',
        }
        labels = {
            'info':    'INFO',
            'success': ' OK ',
            'warning': 'WARN',
            'error':   'ERR ',
        }
        ts = datetime.now().strftime('%H:%M:%S')
        color = colors.get(level, '#374151')
        label = labels.get(level, 'INFO')
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(f'[{ts}] [{label}] {msg}\n')
        self.log_view.setTextCursor(cursor)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())
