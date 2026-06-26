# -*- coding: utf-8 -*-
"""叶片预弯度设计面板（QWidget 子类）。

从 curve_fitter_panel.py 的 PrebendTab 剥离（v0.2.13 起，预弯设计独立成模块）。
业务逻辑见 src/prebend_design/（prebend.py）。

UI 结构：
  - 模块 banner
  - PrebendDesignWidget：2 种模式（幂函数 / B 样条）+
    matplotlib 画布 + 参数表 + z_span 输入 + 复制/保存
"""
import os
import sys

import numpy as np
import pandas as pd

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QGuiApplication
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QComboBox,
    QDoubleSpinBox, QPlainTextEdit, QTextEdit,
    QMessageBox, QGroupBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QFrame, QSizePolicy,
)

# matplotlib 嵌入式画布（import plotting 触发中文字体配置）
import core.plotting as plotting  # noqa: F401
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from global_config import config_center
from business.prebend_design import (
    DEFAULT_TIP_PB, DEFAULT_GAMMA, DEFAULT_Z_START_RATIO,
    DEFAULT_CONTINUITY, DEFAULT_CTRL, DEFAULT_Z_SPAN, GAMMA_MIN,
    compute_prebend_power, compute_prebend_bspline,
)


# ============================================================
# 工具函数（与 curve_fitter_panel 共享语义，但独立维护避免跨文件耦合）
# ============================================================

def _format_float_array(arr, precision=6):
    """numpy array → 多行字符串（每行一个浮点数）。"""
    return '\n'.join(f'{v:.{precision}f}' for v in arr)


def _parse_float_lines(text):
    """从多行文本解析浮点数列表（空行 / 注释行跳过）。"""
    out = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            out.append(float(line.replace(',', '')))
        except ValueError:
            continue
    return out


def _parse_ctrl_table(table: QTableWidget):
    """从 QTableWidget 读 (z_ratio, prebend_m) 控制点列表。"""
    pts = []
    for r in range(table.rowCount()):
        z_item = table.item(r, 0)
        pb_item = table.item(r, 1)
        if z_item is None or pb_item is None:
            continue
        zs, ps = z_item.text().strip(), pb_item.text().strip()
        if not zs or not ps:
            continue
        try:
            pts.append((float(zs), float(ps)))
        except ValueError:
            continue
    return pts


# ============================================================
# 预弯设计 Widget（原 PrebendTab）
# ============================================================

class PrebendDesignWidget(QWidget):
    """两种预弯度模式：幂函数 / B 样条（v0.3.06 起删除约束 B 样条）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 控制点拖拽状态（B 样条模式专用）
        self._drag_idx = None       # 当前拖拽的控制点索引；None = 未拖拽
        self._curve_line = None     # matplotlib Line2D：预弯曲线
        self._ctrl_line = None      # matplotlib Line2D：控制点散点
        self._highlight_line = None # matplotlib Line2D：拖动/悬停高亮（大号空心圆）
        self._hover_idx = None      # 当前悬停的控制点索引（未按下时用于手形 cursor）
        self._cached_z_end = 80.0   # 最近一次计算的 z_span 末点（用于 z_ratio↔画布像素换算）
        # z_span 输入防抖定时器：用户连续输入时只在停顿后刷新一次
        self._span_timer = QTimer(self)
        self._span_timer.setSingleShot(True)
        self._span_timer.setInterval(400)
        self._span_timer.timeout.connect(lambda: self._refresh_plot(silent=True))
        self._build_ui()
        self._refresh_plot()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # 模式切换
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel('模式:'))
        self.mode_power = QPushButton('幂函数')
        self.mode_power.setCheckable(True)
        self.mode_power.setChecked(True)
        self.mode_power.clicked.connect(lambda: self._switch_mode('power'))
        self.mode_bspline = QPushButton('B 样条')
        self.mode_bspline.setCheckable(True)
        self.mode_bspline.clicked.connect(lambda: self._switch_mode('bspline'))
        for b in (self.mode_power, self.mode_bspline):
            mode_row.addWidget(b)
        mode_row.addStretch()
        outer.addLayout(mode_row)

        # 主体：左画布 + 右参数
        body_split = QSplitter(Qt.Horizontal)

        # 左：matplotlib
        plot_box = QGroupBox('预弯分布')
        plot_box.setObjectName('gb_data')
        plot_lay = QVBoxLayout(plot_box)
        plot_lay.setContentsMargins(8, 6, 8, 6)
        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        plot_lay.addWidget(self.canvas)
        self.toolbar = NavigationToolbar(self.canvas, self)
        plot_lay.addWidget(self.toolbar)
        body_split.addWidget(plot_box)

        # 右：参数 + 控制点表（v0.3.14: 限制最大宽度 ~550px，让右栏在宽屏下保持约 1/3 占比）
        right_box = QWidget()
        right_box.setMaximumWidth(550)
        right_lay = QVBoxLayout(right_box)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        # 1) 幂函数参数
        self.grp_power = QGroupBox('幂函数参数')
        gp = QGridLayout(self.grp_power)
        gp.setContentsMargins(8, 6, 8, 6)
        gp.addWidget(QLabel('叶尖预弯 tip_pb (m):'), 0, 0)
        self.spin_tip_pb = QDoubleSpinBox()
        self.spin_tip_pb.setRange(-100, 100)
        self.spin_tip_pb.setDecimals(3)
        self.spin_tip_pb.setValue(DEFAULT_TIP_PB)
        gp.addWidget(self.spin_tip_pb, 0, 1)
        gp.addWidget(QLabel('起始位置比 z/R:'), 1, 0)
        self.spin_zr = QDoubleSpinBox()
        self.spin_zr.setRange(0.0, 1.0)
        self.spin_zr.setDecimals(3)
        self.spin_zr.setSingleStep(0.05)
        self.spin_zr.setValue(DEFAULT_Z_START_RATIO)
        gp.addWidget(self.spin_zr, 1, 1)
        gp.addWidget(QLabel('幂指数 γ:'), 2, 0)
        self.spin_gamma = QDoubleSpinBox()
        self.spin_gamma.setRange(0.1, 10.0)
        self.spin_gamma.setDecimals(3)
        self.spin_gamma.setSingleStep(0.05)
        self.spin_gamma.setValue(DEFAULT_GAMMA)
        gp.addWidget(self.spin_gamma, 2, 1)
        gp.setColumnStretch(1, 1)
        right_lay.addWidget(self.grp_power)

        # 2) B 样条参数（v0.3.12 起与 grp_power 互斥显示，不再共享）
        self.grp_bspline = QGroupBox('B 样条参数')
        gb = QVBoxLayout(self.grp_bspline)
        gb.setContentsMargins(8, 6, 8, 6)
        cont_row = QHBoxLayout()
        cont_row.addWidget(QLabel('连续性:'))
        self.cont_combo = QComboBox()
        self.cont_combo.addItems(['C0', 'C1', 'C2'])
        self.cont_combo.setCurrentText(DEFAULT_CONTINUITY)
        cont_row.addWidget(self.cont_combo)
        cont_row.addStretch()
        gb.addLayout(cont_row)
        gb.addWidget(QLabel('控制点 (z/R, prebend_m):'))
        self.ctrl_table = QTableWidget()
        self.ctrl_table.setColumnCount(2)
        self.ctrl_table.setHorizontalHeaderLabels(['z/R', 'prebend (m)'])
        self.ctrl_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ctrl_table.verticalHeader().setVisible(False)
        self._populate_ctrl_table(DEFAULT_CTRL)
        gb.addWidget(self.ctrl_table, 1)
        ctrl_btn_row = QHBoxLayout()
        add_btn = QPushButton('+ 添加')
        add_btn.clicked.connect(lambda: self._on_ctrl_add(self.ctrl_table))
        del_btn = QPushButton('− 删除')
        del_btn.clicked.connect(lambda: self._on_ctrl_del(self.ctrl_table))
        ctrl_btn_row.addWidget(add_btn)
        ctrl_btn_row.addWidget(del_btn)
        ctrl_btn_row.addStretch()
        gb.addLayout(ctrl_btn_row)
        right_lay.addWidget(self.grp_bspline)

        # 3) 展向位置 + 复制/保存 + 结果预览（与参数栏上下堆叠，两模式都可见）
        # v0.3.14: span_box 内部改为左右两栏 —— 左 span_edit 输入 / 右 result_preview + 按钮
        span_box = QGroupBox('展向位置 z_span (m) 与结果')
        span_box.setObjectName('gb_data')
        span_lay = QHBoxLayout(span_box)
        span_lay.setContentsMargins(8, 6, 8, 6)
        span_lay.setSpacing(6)
        # 左栏：z_span 输入
        left_col = QVBoxLayout()
        left_col.setSpacing(2)
        left_col.addWidget(QLabel('z_span:'))
        self.span_edit = QPlainTextEdit()
        self.span_edit.setPlainText(_format_float_array(DEFAULT_Z_SPAN, 2))
        left_col.addWidget(self.span_edit, 1)
        span_lay.addLayout(left_col, 2)
        # 右栏：结果预览 + 按钮（按钮在底部）
        right_col = QVBoxLayout()
        right_col.setSpacing(2)
        self.result_preview = QTextEdit()
        self.result_preview.setReadOnly(True)
        self.result_preview.setPlaceholderText('计算后显示：z_span → prebend 表')
        right_col.addWidget(self.result_preview, 1)
        btn_row2 = QHBoxLayout()
        copy_btn = QPushButton('📋 复制结果')
        copy_btn.clicked.connect(self._on_copy_result)
        save_btn = QPushButton('💾 保存 CSV')
        save_btn.clicked.connect(self._on_save_result)
        btn_row2.addWidget(copy_btn)
        btn_row2.addWidget(save_btn)
        right_col.addLayout(btn_row2)
        span_lay.addLayout(right_col, 1)
        right_lay.addWidget(span_box)

        # 关键：末尾加 stretch，单模式显示时 GroupBox 保持自然高度、顶对齐
        # 不会被垂直拉伸成"3 个 spinbox 均分整栏"的视觉
        right_lay.addStretch()

        body_split.addWidget(right_box)
        # v0.3.14: 右栏占 ~1/3 宽（左 2 : 右 1）
        body_split.setSizes([700, 350])
        body_split.setStretchFactor(0, 2)
        body_split.setStretchFactor(1, 1)
        outer.addWidget(body_split, 3)

        # 初始只显示 power 参数组
        self._switch_mode('power')

        # matplotlib 控制点拖动事件（仅 B 样条模式响应）
        self.canvas.mpl_connect('button_press_event', self._on_mpl_press)
        self.canvas.mpl_connect('motion_notify_event', self._on_mpl_motion)
        self.canvas.mpl_connect('button_release_event', self._on_mpl_release)
        # 表格 ↔ 画布双向同步：用户手动改表格 → 画布跟随
        self.ctrl_table.cellChanged.connect(self._on_ctrl_table_edited)
        # 参数实时预览：调 spinbox / combo → 立即刷新（silent 模式，无弹窗）
        self.spin_tip_pb.valueChanged.connect(self._refresh_plot_live)
        self.spin_zr.valueChanged.connect(self._refresh_plot_live)
        self.spin_gamma.valueChanged.connect(self._refresh_plot_live)
        self.cont_combo.currentIndexChanged.connect(self._refresh_plot_live)
        # z_span 输入用防抖（避免每敲一个字符就重画）
        self.span_edit.textChanged.connect(self._span_timer.start)

    def _refresh_plot_live(self, *_args):
        """实时刷新（silent 模式，失败不弹窗，不打扰用户调参）。

        B-spline 模式下同步两端锚点：
        - idx 0：(spin_zr, 0)    ← z_start_ratio 跟随，Y=0 固定
        - idx -1：(1.0, tip_pb)  ← X=1.0 固定（叶尖），Y 跟 spin_tip_pb
        - idx 1..n-2：完全自由（v0.3.06 起不再锁定 Y=0）
        """
        if self._current_mode() == 'bspline' and self.ctrl_table.rowCount() > 0:
            zr = self.spin_zr.value()
            tip_pb = self.spin_tip_pb.value()
            n = self.ctrl_table.rowCount()
            self.ctrl_table.blockSignals(True)
            # idx 0：同步 spin_zr
            self.ctrl_table.setItem(0, 0, QTableWidgetItem(f'{zr:.4f}'))
            self.ctrl_table.setItem(0, 1, QTableWidgetItem('0.0000'))
            # idx -1：X=1.0 强制，Y 同步 spin_tip_pb（仅当至少 3 行，避免与 idx 0 规则冲突）
            if n >= 3:
                self.ctrl_table.setItem(n - 1, 0, QTableWidgetItem('1.0000'))
                self.ctrl_table.setItem(n - 1, 1, QTableWidgetItem(f'{tip_pb:.4f}'))
            self.ctrl_table.blockSignals(False)
        self._refresh_plot(silent=True)

    def _on_ctrl_table_edited(self, row, col):
        """用户在 QTableWidget 里改了控制点 → 重画。

        B-spline 模式下的额外约束：
        - row 0 col 0 (z/R)：同步到 spin_zr（双向绑定第一个控制点的 X 与 z_start_ratio）
        - row 0 col 1 (prebend)：强制为 0（第一个控制点 y=0 固定）
        - 最后一行 col 0 (z/R)：强制为 1.0000（叶尖锚点 x=1.0 固定）
        - 最后一行 col 1 (prebend)：同步到 spin_tip_pb（双向绑定最后一个控制点的 Y 与叶尖预弯）
        - 其他行（含 row 1）：自由编辑（v0.3.06 起 row 1 不再强制 y=0）
        拖动时 blockSignals 会屏蔽本回调。
        """
        sender = self.sender()
        if (self._current_mode() == 'bspline'
                and sender is self.ctrl_table):
            n = self.ctrl_table.rowCount()
            is_last = (n >= 3 and row == n - 1)
            if row == 0 and col == 0:
                # 同步 z/R → spin_zr
                item = self.ctrl_table.item(0, 0)
                if item:
                    try:
                        zr = float(item.text().strip())
                        self.spin_zr.blockSignals(True)
                        self.spin_zr.setValue(zr)
                        self.spin_zr.blockSignals(False)
                    except ValueError:
                        pass
            elif row == 0 and col == 1:
                # 强制 y=0（row 0）
                self.ctrl_table.blockSignals(True)
                self.ctrl_table.setItem(0, 1, QTableWidgetItem('0.0000'))
                self.ctrl_table.blockSignals(False)
            elif is_last and col == 0:
                # 强制 x=1.0
                self.ctrl_table.blockSignals(True)
                self.ctrl_table.setItem(row, 0, QTableWidgetItem('1.0000'))
                self.ctrl_table.blockSignals(False)
            elif is_last and col == 1:
                # 同步 prebend → spin_tip_pb
                item = self.ctrl_table.item(row, 1)
                if item:
                    try:
                        pb = float(item.text().strip())
                        self.spin_tip_pb.blockSignals(True)
                        self.spin_tip_pb.setValue(pb)
                        self.spin_tip_pb.blockSignals(False)
                    except ValueError:
                        pass
        self._refresh_plot(silent=True)

    def _populate_ctrl_table(self, pts, table=None):
        """填表。table=None 用 self.ctrl_table。"""
        if table is None:
            table = self.ctrl_table
        table.setRowCount(len(pts))
        for r, (z, pb) in enumerate(pts):
            table.setItem(r, 0, QTableWidgetItem(f'{z:.4f}'))
            table.setItem(r, 1, QTableWidgetItem(f'{pb:.4f}'))

    def _on_ctrl_add(self, table=None):
        if table is None:
            table = self.ctrl_table
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QTableWidgetItem('0.5000'))
        table.setItem(r, 1, QTableWidgetItem('0.0000'))
        # 增删行不触发 cellChanged，需手动刷新预览
        # bspline 模式：若新行落在 idx 0/1，会被 Y=0 规则覆盖（_refresh_plot 内部处理）
        self._refresh_plot(silent=True)

    def _on_ctrl_del(self, table=None):
        if table is None:
            table = self.ctrl_table
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        if not rows:
            r = table.rowCount() - 1
            if r >= 0:
                table.removeRow(r)
        else:
            for r in rows:
                table.removeRow(r)
        # 增删行不触发 cellChanged，需手动刷新预览
        # 若删到 < 2 行，_compute 抛 ValueError，silent 模式下静默跳过重画
        # （画布保留上一次曲线，避免误显空白；用户继续加回 ≥2 行后自动恢复）
        self._refresh_plot(silent=True)

    def _switch_mode(self, mode):
        self.mode_power.setChecked(mode == 'power')
        self.mode_bspline.setChecked(mode == 'bspline')
        # v0.3.12: 参数栏独立互斥显示，不再共享 grp_power
        # - 幂函数模式：grp_power 可见，grp_bspline 隐藏
        # - B 样条模式：grp_bspline 可见，grp_power 隐藏
        # tip_pb / z_start_ratio 仍作为 B 样条首末控制点的 anchor，
        # 但用户在 B 样条模式下通过控制点表（idx 0 X / idx -1 Y）间接调整，
        # _on_ctrl_table_edited 会双向同步到 spinbox
        self.grp_power.setVisible(mode == 'power')
        self.grp_bspline.setVisible(mode == 'bspline')
        # 切换模式后立即刷新预览：让 B 样条模式的控制点散点立刻显示，
        # 而不是停留在上一个模式的纯曲线视图
        self._refresh_plot(silent=True)

    def _current_mode(self):
        if self.mode_bspline.isChecked():
            return 'bspline'
        return 'power'

    # ----- 计算 -----
    def _compute(self):
        z_span = np.array(_parse_float_lines(self.span_edit.toPlainText()))
        if len(z_span) < 2:
            z_span = DEFAULT_Z_SPAN.copy()
        mode = self._current_mode()
        if mode == 'power':
            y = compute_prebend_power(
                z_span,
                tip_pb=self.spin_tip_pb.value(),
                z_start_ratio=self.spin_zr.value(),
                gamma=self.spin_gamma.value(),
            )
        elif mode == 'bspline':
            pts = _parse_ctrl_table(self.ctrl_table)
            if len(pts) < 2:
                raise ValueError('B 样条至少需要 2 个控制点')
            # idx 0：起点 (z_start, 0)，Y=0 固定，仅 X 可调
            # idx 1..n-2：自由控制点（v0.3.06 起放开，原本 Y=0 锁定）
            # idx -1：叶尖锚点 (1.0, tip_pb)，仅 Y 可调（仅当至少 3 个点时应用）
            pts[0] = (pts[0][0], 0.0)
            if len(pts) >= 3:
                pts[-1] = (1.0, pts[-1][1])
            y = compute_prebend_bspline(
                pts, z_span, continuity=self.cont_combo.currentText(),
            )
        return z_span, y

    def _refresh_plot(self, silent=False):
        try:
            z_span, y = self._compute()
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, '计算失败', str(e))
            return
        self._cached_z_end = float(z_span[-1]) if len(z_span) else self._cached_z_end
        self.ax.clear()
        # axes.clear() 让旧 Line2D 失效，重置引用（拖动高亮也会在 _refresh_plot_dragging 中按需重建）
        self._curve_line = None
        self._ctrl_line = None
        self._highlight_line = None
        self._curve_line, = self.ax.plot(z_span, y, 'b-', linewidth=2, label='prebend')
        # 控制点叠加
        mode = self._current_mode()
        if mode == 'bspline':
            pts = _parse_ctrl_table(self.ctrl_table)
            if pts:
                # idx 0：Y=0 固定；idx -1：X=1.0 固定（与 _compute 一致）
                # idx 1..n-2：完全自由（v0.3.06 起不再锁定 Y=0）
                pts = [(pts[0][0], 0.0)] + list(pts[1:])
                if len(pts) >= 3:
                    pts[-1] = (1.0, pts[-1][1])
                cz = [p[0] * self._cached_z_end for p in pts]
                cy = [p[1] for p in pts]
                # 中间控制点：红色圆（可任意拖动）。首点画绿色方块、末点画蓝色三角覆盖
                self._ctrl_line, = self.ax.plot(
                    cz, cy, 'ro', markersize=10,
                    markerfacecolor='r', markeredgecolor='k',
                    label='控制点（可拖动）',
                )
                # 第一个控制点：绿色方块（y=0 固定，仅 X 可调）
                if len(pts) >= 1:
                    self.ax.plot(
                        cz[0], cy[0], 'gs', markersize=12,
                        markerfacecolor='g', markeredgecolor='k',
                        label='根段锚点 (y=0, 仅 X 可调)',
                    )
                # 最后一个控制点：蓝色三角（x=1.0 固定，仅 Y 可调）
                if len(pts) >= 3:
                    self.ax.plot(
                        cz[-1], cy[-1], 'b^', markersize=13,
                        markerfacecolor='b', markeredgecolor='k',
                        label='叶尖锚点 (x=1.0, 仅 Y 可调)',
                    )
            else:
                self._ctrl_line = None
        else:
            self._ctrl_line = None
        self.ax.set_xlabel('z_span (m)')
        self.ax.set_ylabel('prebend (m)')
        self.ax.set_title(f'预弯分布 ({mode})')
        # Y 轴范围固定：以 tip_pb 为锚，避免拖动控制点时 Y 轴跟随跳动
        tip_pb = self.spin_tip_pb.value()
        if tip_pb >= 0:
            self.ax.set_ylim(-abs(tip_pb) * 0.15 - 0.5, tip_pb * 1.2 + 0.5)
        else:
            self.ax.set_ylim(tip_pb * 1.2 - 0.5, abs(tip_pb) * 0.15 + 0.5)
        self.ax.legend()
        self.ax.grid(True, alpha=0.3)
        self.fig.tight_layout()
        self.canvas.draw()
        # 预览
        lines = ['z_span\tprebend']
        for zs, pv in zip(z_span, y):
            lines.append(f'{zs:.4f}\t{pv:.4f}')
        self.result_preview.setPlainText('\n'.join(lines))

    # ------------------------------------------------------------
    # matplotlib 控制点拖动（B 样条模式）
    # ------------------------------------------------------------
    _DRAG_THRESHOLD_PX = 20  # 命中半径（像素）—— v0.3.07 从 12 提高到 20，让中间控制点更容易命中

    def _on_mpl_press(self, event):
        """鼠标按下：判断是否命中某个控制点；双击则添加新控制点。"""
        if self._current_mode() != 'bspline':
            return
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        if event.button != 1:  # 只响应左键
            return
        # 双击：在对应展向位置插入新控制点（Y 投影到当前曲线）
        if event.dblclick:
            # 取消首击可能已启动的拖拽，避免插入同时被拖动
            self._drag_idx = None
            self._on_mpl_double_click(event)
            return
        idx = self._nearest_ctrl_idx(event)
        if idx is not None:
            self._drag_idx = idx
            # 命中即设手形 cursor（视觉反馈：你抓住了控制点）
            try:
                from PyQt5.QtGui import QGuiApplication
                from PyQt5.QtCore import Qt
                QGuiApplication.setOverrideCursor(Qt.ClosedHandCursor)
            except Exception:
                pass

    def _on_mpl_double_click(self, event):
        """双击预览图：在对应展向位置插入新控制点。

        - 新控制点 X = 双击位置的 z/R
        - 新控制点 Y = 双击位置 X 在当前拟合曲线上投影的 Y（np.interp）
        - 插入后按 X 升序排序；首点强制 Y=0（根段锚点规则）
        - 若新点落在 idx 0 位置，其 Y 会被规则强制为 0
        """
        try:
            z_span, y_curve = self._compute()
        except Exception:
            return
        x_data = float(event.xdata)
        new_z_ratio = x_data / max(1e-6, self._cached_z_end)
        new_z_ratio = max(0.0, min(1.0, new_z_ratio))
        # 投影 Y：当前曲线上 x_data 处的值（使新控制点初始落在曲线上，不改变形状）
        new_pb = float(np.interp(x_data, z_span, y_curve))
        pts = _parse_ctrl_table(self.ctrl_table)
        pts.append((new_z_ratio, new_pb))
        pts.sort(key=lambda p: p[0])
        # 强制首点 Y=0 + 末点 X=1.0（根段/叶尖锚点规则）
        if len(pts) >= 1:
            pts[0] = (pts[0][0], 0.0)
        if len(pts) >= 3:
            pts[-1] = (1.0, pts[-1][1])
        # 回填表格（屏蔽信号避免触发 cellChanged → _refresh_plot 递归）
        self.ctrl_table.blockSignals(True)
        self._populate_ctrl_table(pts)
        self.ctrl_table.blockSignals(False)
        # 第一个控制点的 X 始终同步到 spin_zr
        self.spin_zr.blockSignals(True)
        self.spin_zr.setValue(pts[0][0])
        self.spin_zr.blockSignals(False)
        self._refresh_plot(silent=True)

    def _on_mpl_motion(self, event):
        """鼠标移动：拖拽中则实时更新控制点 + 表格 + 画布。

        - idx 0（起点）：y=0 固定，只能调整 x（z/R），同步到 spin_zr
        - idx 1（第二点）：y 保持原值不变，仅调整 x（v0.3.08 起，匹配共模设计约束）
        - idx -1（叶尖）：x=1.0 固定，只能调整 y（prebend），同步到 spin_tip_pb
        - 其他中间控制点：x、y 都可自由调整
        """
        # 悬停检测（未按下时）：变手形 cursor 给用户提前反馈命中范围
        # 让用户在按下前就知道自己能否命中某个控制点
        if self._drag_idx is None:
            if (event.inaxes is self.ax
                    and event.xdata is not None and event.ydata is not None):
                hover_idx = self._nearest_ctrl_idx(event)
                if hover_idx != self._hover_idx:
                    self._hover_idx = hover_idx
                    try:
                        from PyQt5.QtGui import QGuiApplication
                        from PyQt5.QtCore import Qt
                        if hover_idx is not None:
                            QGuiApplication.setOverrideCursor(Qt.OpenHandCursor)
                        else:
                            QGuiApplication.restoreOverrideCursor()
                    except Exception:
                        pass
            return
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        n = self.ctrl_table.rowCount()
        is_last_drag = (n >= 3 and self._drag_idx == n - 1)
        # 画布数据坐标 → 归一化 z/R + prebend(m)
        new_z_ratio = event.xdata / max(1e-6, self._cached_z_end)
        new_z_ratio = max(0.0, min(1.0, new_z_ratio))
        if self._drag_idx == 0:
            # 第一个控制点：y=0 固定，仅更新 x；同步 spin_zr
            new_pb = 0.0
            self.spin_zr.blockSignals(True)
            self.spin_zr.setValue(new_z_ratio)
            self.spin_zr.blockSignals(False)
        elif is_last_drag:
            # 最后一个控制点：x=1.0 固定，仅更新 y；同步 spin_tip_pb
            new_z_ratio = 1.0
            new_pb = float(event.ydata)
            self.spin_tip_pb.blockSignals(True)
            self.spin_tip_pb.setValue(new_pb)
            self.spin_tip_pb.blockSignals(False)
        else:
            # idx 1（第二点）：y 保持原值，仅调整 x（v0.3.08：匹配共模设计约束）
            cur_item = self.ctrl_table.item(self._drag_idx, 1)
            new_pb = float(cur_item.text()) if cur_item is not None else 0.0
            # 其他中间控制点：完全自由
            if self._drag_idx != 1:
                new_pb = float(event.ydata)
        # 更新表格（blockSignals 防止触发 cellChanged → _refresh_plot 的递归重画）
        self.ctrl_table.blockSignals(True)
        self.ctrl_table.setItem(self._drag_idx, 0, QTableWidgetItem(f'{new_z_ratio:.4f}'))
        self.ctrl_table.setItem(self._drag_idx, 1, QTableWidgetItem(f'{new_pb:.4f}'))
        self.ctrl_table.blockSignals(False)
        # 拖动中的轻量重画（不清空 axes，只更新两条 Line2D 的数据）
        self._refresh_plot_dragging()

    def _on_mpl_release(self, _event):
        """鼠标释放：结束拖拽，并触发一次完整重画（恢复 legend / title 等）。"""
        # 无论是否在拖动，都恢复 cursor（防止异常路径下卡在手形）
        try:
            from PyQt5.QtGui import QGuiApplication
            QGuiApplication.restoreOverrideCursor()
        except Exception:
            pass
        if self._drag_idx is None:
            return
        self._drag_idx = None
        self._refresh_plot()

    def _nearest_ctrl_idx(self, event):
        """找距离 event 最近的控制点索引（像素距离），超出阈值返回 None。"""
        pts = _parse_ctrl_table(self.ctrl_table)
        if not pts:
            return None
        best_idx = None
        best_dist = 1e9
        for i, (zr, pb) in enumerate(pts):
            cx = zr * self._cached_z_end
            cy = pb
            # 数据坐标 → 显示像素坐标（与 event.x/event.y 同一参考系）
            px, py = self.ax.transData.transform((cx, cy))
            d = ((px - event.x) ** 2 + (py - event.y) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_idx = i
        if best_idx is not None and best_dist <= self._DRAG_THRESHOLD_PX:
            return best_idx
        return None

    def _refresh_plot_dragging(self):
        """拖动中的轻量重画：保留 axes（含 Y 轴范围），只更新曲线 + 控制点 Line2D 数据。

        关键：不调用 relim/autoscale_view，Y 轴范围保持 _refresh_plot 设定的锚定值
        （以 tip_pb 为参考），避免拖动时 Y 轴跟随跳动。
        """
        try:
            z_span, y = self._compute()
        except Exception:
            return
        self._cached_z_end = float(z_span[-1]) if len(z_span) else self._cached_z_end
        if self._curve_line is not None:
            self._curve_line.set_data(z_span, y)
        pts = _parse_ctrl_table(self.ctrl_table)
        if pts:
            # 与 _refresh_plot 一致：强制首点 y=0 + 末点 x=1.0
            pts = [(pts[0][0], 0.0)] + list(pts[1:])
            if len(pts) >= 3:
                pts[-1] = (1.0, pts[-1][1])
        if self._ctrl_line is not None and pts:
            cz = [p[0] * self._cached_z_end for p in pts]
            cy = [p[1] for p in pts]
            self._ctrl_line.set_data(cz, cy)
        # 拖动高亮：被拖的控制点上叠一个大号空心黄圆，作为视觉反馈
        # 让用户立即看到自己命中了哪个 idx（v0.3.07 新增）
        if self._drag_idx is not None and pts and 0 <= self._drag_idx < len(pts):
            hp = pts[self._drag_idx]
            hx = [hp[0] * self._cached_z_end]
            hy = [hp[1]]
            if self._highlight_line is None:
                self._highlight_line, = self.ax.plot(
                    hx, hy, 'o', markersize=16,
                    markerfacecolor='none',
                    markeredgecolor='yellow',
                    markeredgewidth=2.5,
                    zorder=10,
                )
            else:
                self._highlight_line.set_data(hx, hy)
        elif self._highlight_line is not None:
            # 没在拖动：隐藏高亮
            self._highlight_line.set_data([], [])
        # Y 轴不跟随：保持 _refresh_plot 中设定的范围
        self.canvas.draw_idle()
        # 预览表同步
        lines = ['z_span\tprebend']
        for zs, pv in zip(z_span, y):
            lines.append(f'{zs:.4f}\t{pv:.4f}')
        self.result_preview.setPlainText('\n'.join(lines))

    def _on_copy_result(self):
        try:
            z_span, y = self._compute()
        except Exception as e:
            QMessageBox.warning(self, '计算失败', str(e))
            return
        text = 'z_span,prebend\n' + '\n'.join(
            f'{zs:.4f},{pv:.4f}' for zs, pv in zip(z_span, y)
        )
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, '已复制', f'共 {len(z_span)} 行写入剪贴板')

    def _on_save_result(self):
        try:
            z_span, y = self._compute()
        except Exception as e:
            QMessageBox.warning(self, '计算失败', str(e))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '保存预弯结果', 'prebend.csv', 'CSV (*.csv);;所有文件 (*.*)'
        )
        if not path:
            return
        df = pd.DataFrame({'z_span': z_span, 'prebend': y})
        df.to_csv(path, index=False, float_format='%.6f')
        QMessageBox.information(self, '已保存', f'结果写入：\n{path}')


# ============================================================
# 主面板
# ============================================================

class PrebendDesignPanel(QWidget):
    MODULE_ID = 'prebend_design'
    DEFAULT_INPUT_SUBDIR = 'prebend_design'
    DEFAULT_OUTPUT_SUBDIR = 'prebend_design'

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
        self._build_ui()
        self.setMinimumHeight(0)
        self.setMinimumSize(0, 0)

    def _on_paths_changed(self, module_id):
        if module_id and module_id != self.MODULE_ID:
            return
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_banner())
        outer.addWidget(PrebendDesignWidget(), 1)

    def _build_banner(self):
        banner = QWidget()
        banner.setObjectName('moduleBanner')
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(4)
        title = QLabel('预弯设计')
        title.setObjectName('moduleTitle')
        title.setAlignment(Qt.AlignCenter)
        tf = QFont('YouSheBiaoTiHei', 16)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        title.setFont(tf)
        sub = QLabel('P R E B E N D   D E S I G N')
        sub.setObjectName('moduleSubtitle')
        sub.setAlignment(Qt.AlignCenter)
        sf = QFont('Consolas', 8)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        sf.setBold(True)
        sub.setFont(sf)
        bl.addWidget(title)
        bl.addWidget(sub)
        return banner
