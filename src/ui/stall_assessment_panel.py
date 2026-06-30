# -*- coding: utf-8 -*-
"""失速评估面板（BaseWorkerPanel 子类）。

业务逻辑见 ``src/stall_assessment/core.py``。

UI 结构（方案 A 左右双栏 + 底部执行栏）：
  - 模块 banner（由基类提供）
  - 左栏（2×2 网格）：
      · 标准翼型表（QTableWidget，三列：相对厚度 / 标失速攻角 / VG 失速攻角，可增删行）
      · VG 安装范围表（QTableWidget，三列：标准厚度下拉 / VG 起 z / VG 止 z，可增删行）
      · 展向分布输入（粘贴文本框 + 载入 CSV/xlsx 按钮）
      · 攻角分布输入（粘贴文本框 + 载入 CSV/xlsx 按钮）
  - 右栏：
      · 展向分布图（r/R ↔ 失速攻角，含 VG 安装段阴影 + 段边界竖虚线）
      · 工具行：显示相对厚度开关 / 📋 复制结果 / 💾 保存图片
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

from ui.base_module_panel import BaseWorkerPanel
from business.stall_assessment import (
    parse_span_text, parse_span_file, normalize_positions,
    interpolate, save_csv, plot_span,
    find_intersections, plot_span_compare,
    compute_alpha_span,
)
from business.stall_assessment.params_store import load_inputs, save_inputs


# 默认标准翼型示例（厚度%, 标失速攻角°, VG 失速攻角° or None）
# —— 用户可自由增删；VG 列空 = 该厚度无 VG 变体
DEFAULT_PROFILE = [
    (18, 15.5, None),
    (21, 12.0, None),
    (25, 12.0, None),
    (30, 13.0, 16.0),
    (40, 10.0, 13.5),
    (100, 0.0, None),
]

# 默认展向分布示例（r/R, 相对厚度%）—— 提示用户格式，可清空
DEFAULT_SPAN = """0.00, 100
0.10, 85
0.20, 60
0.30, 45
0.40, 35
0.50, 30
0.60, 27
0.70, 25
0.80, 22
0.90, 20
1.00, 18
"""

# 默认最大攻角分布示例（r/R, 攻角°）—— 用户可清空
DEFAULT_AOA = """0.00, 0.0
0.10, 5.0
0.20, 7.0
0.30, 8.5
0.40, 9.5
0.50, 10.0
0.60, 10.5
0.70, 11.0
0.80, 12.0
0.90, 13.5
1.00, 15.0
"""


# ============================================================
# 后台 Worker
# ============================================================
class StallAssessmentWorker(QThread):
    """读标准表 + VG 配置 + 展向分布 → 计算展向失速攻角 → 写 CSV。

    在 UI 线程外完成计算（数据量小，主要耗时在 CSV 落盘）。
    无 VG 配置时 compute_alpha_span 自动退化为 PCHIP 兼容路径。
    """
    progress = pyqtSignal(int, str)

    def __init__(self, std_thickness, std_alpha_std, std_alpha_vg,
                 vg_segments,
                 positions, thickness, aoa_positions, aoa,
                 output_dir):
        super().__init__()
        self.std_thickness = std_thickness       # 1D ndarray 标准厚度
        self.std_alpha_std = std_alpha_std       # 1D ndarray 标失速攻角
        self.std_alpha_vg = std_alpha_vg         # dict {thickness: alpha_vg} or None
        self.vg_segments = vg_segments           # list[(t, zs, ze)] or None
        self.positions = positions
        self.thickness = thickness
        self.aoa_positions = aoa_positions
        self.aoa = aoa
        self.output_dir = output_dir
        # 输出（供主线程取回画图）
        self.span_alpha = None
        self.vg_active = None
        self.crossings = None
        self.error = None

    def run(self):
        try:
            self.progress.emit(10, f'标准翼型点：{self.std_thickness.size} 个')
            self.progress.emit(20, f'展向分布：{self.positions.size} 站')
            self.progress.emit(40, f'最大攻角分布：{self.aoa_positions.size} 站')
            n_vg = len(self.vg_segments) if self.vg_segments else 0
            self.progress.emit(50, f'VG 安装段：{n_vg} 段')
            # VG 诊断：打印 VG 攻角字典 + 各标准厚度点的 VG 身份
            if self.std_alpha_vg:
                vg_info = ', '.join(f't={t:g}→{a:g}°'
                                    for t, a in self.std_alpha_vg.items())
                self.progress.emit(52, f'  VG 攻角配置：{vg_info}')
                seg_str = ', '.join(f'[{zs:g},{ze:g}]'
                                    for _, zs, ze in self.vg_segments)
                self.progress.emit(52, f'  VG 段：{seg_str}')
                # 打印每个标准厚度点的展向位置 z_t 与 VG 身份判定（诊断用）
                import numpy as _np
                from scipy.interpolate import PchipInterpolator as _PCH
                _order = _np.argsort(self.thickness)
                _t_asc = self.thickness[_order]
                _z_asc = self.positions[_order]
                _keep = _np.concatenate(([True], _np.diff(_t_asc) != 0))
                _f = _PCH(_t_asc[_keep], _z_asc[_keep])
                _t_lo, _t_hi = float(_t_asc.min()), float(_t_asc.max())
                for _t in self.std_thickness:
                    _zt = float(_f(min(max(float(_t), _t_lo), _t_hi)))
                    _in = any(zs-1e-9 <= _zt <= ze+1e-9
                              for _, zs, ze in self.vg_segments)
                    _has_vg = float(_t) in self.std_alpha_vg
                    _use = 'VG' if (_in and _has_vg) else '标'
                    self.progress.emit(52,
                        f'  t={_t:g} → z_t={_zt:.3f}  在VG段={_in}  用{_use}攻角')
            else:
                self.progress.emit(52, '  未读到 VG 攻角（标准表 VG 列空）→ 走 PCHIP')
            self.progress.emit(55, '执行展向失速攻角计算（含 VG 逻辑）...')
            span_alpha, vg_active = compute_alpha_span(
                self.positions, self.thickness,
                self.std_thickness, self.std_alpha_std,
                std_alpha_vg=self.std_alpha_vg,
                vg_segments=self.vg_segments,
            )
            self.span_alpha = span_alpha
            self.vg_active = vg_active

            self.progress.emit(70, '求失速角/攻角交点...')
            self.crossings = find_intersections(
                self.positions, span_alpha, self.aoa_positions, self.aoa,
            )
            if self.crossings:
                pts = ', '.join(f'{c:.3f}' for c in self.crossings)
                self.progress.emit(75, f'相交点 r/R = {pts}')
            else:
                self.progress.emit(75, '无相交点（全展向均未失速 / 均已失速）')

            self.progress.emit(85, f'写入输出目录：{self.output_dir}')
            out_path = save_csv(self.positions, self.thickness,
                                span_alpha, self.output_dir,
                                vg_active=vg_active)
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
        self._result = None  # dict: std_thickness/std_alpha_std/...
        super().__init__()
        # 基类创建了 run_btn 但未自动连接点击信号，这里连上
        self.run_btn.clicked.connect(self._on_run)
        # 恢复上次保存的输入
        self._restore_inputs()

    # ------------------------------------------------------------
    # 主体内容（基类会自动追加 exec_bar）
    # ------------------------------------------------------------
    def _build_main_content(self):
        # 总布局：左（2×2 网格） | 右（画图区）
        outer_split = QSplitter(Qt.Horizontal)
        outer_split.setChildrenCollapsible(False)

        # === 左：2×2 网格 ===
        #   行0: 标准翼型表 | VG 安装范围表
        #   行1: 展向分布   | 攻角分布
        left = QWidget()
        left.setMinimumWidth(0)  # 允许 QSplitter 压缩，否则 sizeHint 主导比例
        left.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        grid = QGridLayout(left)
        grid.setContentsMargins(12, 12, 8, 12)
        grid.setSpacing(8)
        grid.addWidget(self._build_profile_group(), 0, 0)
        grid.addWidget(self._build_vg_group(), 0, 1)
        grid.addWidget(self._build_span_group(), 1, 0)
        grid.addWidget(self._build_aoa_group(), 1, 1)
        # 两列等宽、两行等高：清零最小列宽，强制 stretch 决定最终宽度
        grid.setColumnMinimumWidth(0, 0)
        grid.setColumnMinimumWidth(1, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        # === 右：画图区 ===
        right = QWidget()
        right.setMinimumWidth(0)  # 同上
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 12, 12, 12)
        right_lay.setSpacing(8)
        right_lay.addWidget(self._build_plot_group(), 1)

        outer_split.addWidget(left)
        outer_split.addWidget(right)
        # 关键：先用 setSizes 给出初始 2:3，再用 setStretchFactor 保证拉伸时仍按 2:3 分配
        # QSplitter 的 setStretchFactor 处理的是 "额外空间" 的分配，
        # 必须配合 widget 的 minimumWidth=0 才不会被 sizeHint 反制
        outer_split.setSizes([400, 600])
        outer_split.setStretchFactor(0, 2)
        outer_split.setStretchFactor(1, 3)
        # 防止用户拖到过窄：保留交互可调性，但下限为 200px
        outer_split.setChildrenCollapsible(False)

        # profile_table 已填充（vg_table 此时已创建）

        # 挂预览信号（所有输入改动 → 防抖重算 + 重绘）
        self._connect_preview_signals()

        wrap = QWidget()
        wrap_lay = QVBoxLayout(wrap)
        wrap_lay.setContentsMargins(0, 0, 0, 0)
        wrap_lay.addWidget(outer_split, 1)
        return wrap

    # ---------- 标准翼型表 ----------
    def _build_profile_group(self):
        box = QGroupBox('标准翼型表')
        box.setObjectName('gb_data')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        self.profile_table = QTableWidget()
        self.profile_table.setColumnCount(3)
        self.profile_table.setHorizontalHeaderLabels(
            ['相对厚度', '标失速攻角 (°)', 'VG 失速攻角 (°)'])
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.profile_table.verticalHeader().setVisible(False)
        self._populate_profile(DEFAULT_PROFILE)
        # 标准表内容变化时刷新 VG 表的下拉选项
        self.profile_table.cellChanged.connect(self._on_profile_cell_changed)
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
        box = QGroupBox('展向分布')
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

    # ---------- 攻角分布输入 ----------
    def _build_aoa_group(self):
        box = QGroupBox('攻角分布')
        box.setObjectName('gb_data')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        hint = QLabel('每行「展向位置, 最大攻角°」，首行可带标题；或从文件载入：')
        hint.setStyleSheet('color: #888;')
        lay.addWidget(hint)

        self.aoa_edit = QPlainTextEdit()
        self.aoa_edit.setPlainText(DEFAULT_AOA)
        lay.addWidget(self.aoa_edit, 1)

        row = QHBoxLayout()
        load_btn = QPushButton('📂 载入 CSV/xlsx')
        load_btn.clicked.connect(lambda: self._on_load_file(self.aoa_edit))
        clear_btn = QPushButton('清空')
        clear_btn.clicked.connect(lambda: self.aoa_edit.clear())
        row.addWidget(load_btn)
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)
        return box

    # ---------- VG 安装范围表（新增） ----------
    def _build_vg_group(self):
        box = QGroupBox('VG 安装范围表（可选）')
        box.setObjectName('gb_data')
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        hint = QLabel('每行一组 VG 安装段：VG 起/止 z (r/R)。'
                      '空表 = 不使用 VG（走 PCHIP）。')
        hint.setStyleSheet('color: #888;')
        lay.addWidget(hint)

        self.vg_table = QTableWidget()
        self.vg_table.setColumnCount(2)
        self.vg_table.setHorizontalHeaderLabels(
            ['VG 起 z (r/R)', 'VG 止 z (r/R)'])
        self.vg_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.vg_table.verticalHeader().setVisible(False)
        lay.addWidget(self.vg_table)

        row = QHBoxLayout()
        add_btn = QPushButton('+ 添加')
        add_btn.clicked.connect(self._on_vg_add)
        del_btn = QPushButton('− 删除')
        del_btn.clicked.connect(self._on_vg_del)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
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

        # 工具行：SOP + 显示相对厚度开关 + 复制结果 + 保存图片
        tool_row = QHBoxLayout()
        from PyQt5.QtWidgets import QCheckBox
        sop_btn = QPushButton('📖 失速评估 SOP')
        sop_btn.setObjectName('secondaryBtn')
        sop_btn.setCursor(Qt.PointingHandCursor)
        sop_btn.clicked.connect(self._show_sop_dialog)
        tool_row.addWidget(sop_btn)
        self.show_thickness_cb = QCheckBox('显示相对厚度')
        self.show_thickness_cb.setChecked(True)
        self.show_thickness_cb.toggled.connect(
            lambda: self._refresh_plot() if self._result is not None else None)
        tool_row.addWidget(self.show_thickness_cb)
        tool_row.addStretch()
        copy_btn = QPushButton('📋 复制结果')
        copy_btn.clicked.connect(self._on_copy_result)
        tool_row.addWidget(copy_btn)
        save_btn = QPushButton('💾 保存图片')
        save_btn.clicked.connect(self._on_save_figure)
        tool_row.addWidget(save_btn)
        lay.addLayout(tool_row)

        self.fig = Figure(figsize=(7, 5), dpi=100)
        self.ax_span = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.canvas, 1)
        # 启用相交点标注的鼠标拖动（拖文字框，交点本身不动）
        self._enable_annotation_drag()
        self._refresh_plot_placeholder()
        return box

    # ---------- 失速评估 SOP（外部工具取攻角分布的标准流程） ----------
    SOP_STEPS = [
        ('1', 'pcoeffs 计算',
         '在 Bladed 中运行 pcoeffs 计算，得到各风速下的功率系数。'),
        ('2', 'control k_opt 更新',
         '更新最优控制增益 k_opt（变量桨距增益），保证后续稳态计算的桨距角跟踪最优。'),
        ('3', 'steadyop → Calculation Output → Aerodynamic Information → First Blade',
         '在 steadyop（稳态计算）中，将 Calculation Output 的 Aerodynamic Information 输出项设为 First Blade，确保输出第一片叶片的气动信息。'),
        ('4', 'data view → steadyop → Summary Info → Electrical Power → 找额定功率对应风速 −0.1',
         '在 Data View 中查看 steadyop 的 Summary Info，找到 Electrical Power 等于额定功率对应的风速；该风速减 0.1 m/s 通常就是攻角最大的风速（可在 ±0.1° 桨距角下对比攻角以验证）。'),
        ('5', 'steadyop → Blade 1 Information → Angle of Attack → 对应风速下的攻角分布',
         '在 steadyop 的 Blade 1 Information 中取 Angle of Attack，导出"上一步定位的风速"对应的沿展向攻角分布。'),
        ('6', '标准翼型失速攻角 + 相对厚度插值 + 与最大攻角对比（本模块）',
         '将"标准翼型表（相对厚度 → 失速攻角）"填入左上表，配入展向厚度分布（中部）与第 5 步得到的攻角分布，点击「计算失速攻角」——本模块自动按相对厚度插值求出各站失速攻角，并与最大攻角对比、标注失速起始位置。'),
    ]

    def _show_sop_dialog(self):
        """弹出失速评估 SOP 对话框。"""
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QDialogButtonBox,
                                     QTableWidget, QTableWidgetItem, QAbstractItemView)
        dlg = QDialog(self)
        dlg.setWindowTitle('失速评估 SOP')
        dlg.setMinimumSize(720, 420)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(14, 12, 14, 10)
        v.setSpacing(8)

        head = QLabel(
            '<b>失速评估标准操作流程</b><br>'
            '<span style="color:#666;">前 5 步在 Bladed 中完成，'
            '用于拿到"最大攻角沿展向分布"；第 6 步回到本模块完成插值与对比。</span>')
        head.setWordWrap(True)
        v.addWidget(head)

        tbl = QTableWidget(len(self.SOP_STEPS), 3)
        tbl.setHorizontalHeaderLabels(['#', '操作', '说明'])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for i, (num, op, desc) in enumerate(self.SOP_STEPS):
            tbl.setItem(i, 0, QTableWidgetItem(num))
            tbl.setItem(i, 1, QTableWidgetItem(op))
            tbl.setItem(i, 2, QTableWidgetItem(desc))
            # 第 6 步（本模块）标蓝
            if num == '6':
                for c in range(3):
                    f = tbl.item(i, c).font()
                    f.setBold(True)
                    tbl.item(i, c).setFont(f)
        v.addWidget(tbl, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)
        dlg.exec_()

    def _enable_annotation_drag(self):
        """让 ax 上的 Annotation 可用鼠标拖动。"""
        self._drag_ann = None  # 正在拖的标注

        def on_pick(event):
            artist = event.artist
            # matplotlib Annotation 是 Text 子类，带 get_xy 等
            if hasattr(artist, 'get_xy') and hasattr(artist, 'set_position'):
                self._drag_ann = artist
            return True

        def on_motion(event):
            if self._drag_ann is None or event.xdata is None or event.ydata is None:
                return
            ann = self._drag_ann
            # 切换到数据坐标定位（offset points 模式下 set_position 语义不同）
            ann.set_position((event.xdata, event.ydata))
            ann.xyann = (event.xdata, event.ydata)
            self.canvas.draw_idle()

        def on_release(event):
            self._drag_ann = None

        self.canvas.mpl_connect('pick_event', on_pick)
        self.canvas.mpl_connect('motion_notify_event', on_motion)
        self.canvas.mpl_connect('button_release_event', on_release)

    # ---------- 结果表 ----------
    # 注：结果栏已移除（用户要求），VG 安装范围表移到原结果栏位置（0,1）。
    # 结果数据仍在 _result 中缓存，供画图 + 「📋 复制结果」使用，复制按钮
    # 放到画图工具行（见 _build_plot_group）。

    # ============================================================
    # 标准表 / VG 表 槽
    # ============================================================
    def _populate_profile(self, pts):
        """用 (厚度, 标攻角, VG攻角 or None) 列表填标准翼型表。"""
        t = self.profile_table
        t.blockSignals(True)
        t.setRowCount(len(pts))
        for r, row_data in enumerate(pts):
            th, al = row_data[0], row_data[1]
            vg = row_data[2] if len(row_data) > 2 else None
            t.setItem(r, 0, QTableWidgetItem(f'{th:g}'))
            t.setItem(r, 1, QTableWidgetItem(f'{al:g}'))
            t.setItem(r, 2, QTableWidgetItem('' if vg is None else f'{vg:g}'))
        t.blockSignals(False)

    def _on_profile_cell_changed(self, *_):
        """标准表任意单元格改动 → 触发预览重算。"""
        pass  # 预览由 _connect_preview_signals 统一驱动

    def _on_profile_add(self):
        t = self.profile_table
        t.blockSignals(True)
        r = t.rowCount()
        t.insertRow(r)
        t.setItem(r, 0, QTableWidgetItem('30'))
        t.setItem(r, 1, QTableWidgetItem('15.0'))
        t.setItem(r, 2, QTableWidgetItem(''))  # VG 默认空
        t.blockSignals(False)

    def _on_profile_del(self):
        t = self.profile_table
        t.blockSignals(True)
        rows = sorted({idx.row() for idx in t.selectedIndexes()}, reverse=True)
        if not rows:
            r = t.rowCount() - 1
            if r >= 0:
                t.removeRow(r)
        else:
            for r in rows:
                t.removeRow(r)
        t.blockSignals(False)

    def _read_profile(self):
        """从标准表读 list[(厚度, 标攻角, VG攻角 or None)]。返回 None 表示无有效行。"""
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
            # VG 列可空
            item2 = t.item(r, 2)
            vg = None
            if item2 is not None:
                txt = item2.text().strip()
                if txt:
                    try:
                        vg = float(txt)
                    except ValueError:
                        pass
            pts.append((a, b, vg))
        return pts

    # ---------- VG 表 ----------
    def _on_vg_add(self):
        t = self.vg_table
        r = t.rowCount()
        t.insertRow(r)
        # 默认 z 范围 0~1
        t.setItem(r, 0, QTableWidgetItem('0.0'))
        t.setItem(r, 1, QTableWidgetItem('1.0'))

    def _on_vg_del(self):
        t = self.vg_table
        rows = sorted({idx.row() for idx in t.selectedIndexes()}, reverse=True)
        if not rows:
            r = t.rowCount() - 1
            if r >= 0:
                t.removeRow(r)
        else:
            for r in rows:
                t.removeRow(r)

    def _read_vg_segments(self):
        """从 VG 安装表读 [(thickness, z_start, z_end), ...]。

        thickness 字段占位填 0（当前算法按 z 判定，不使用 thickness）。
        返回 list（可能为空，表示无 VG，触发 PCHIP 兼容路径）。
        """
        t = self.vg_table
        segs = []
        for r in range(t.rowCount()):
            item0 = t.item(r, 0)
            item1 = t.item(r, 1)
            if item0 is None or item1 is None:
                continue
            zs_txt = item0.text().strip()
            ze_txt = item1.text().strip()
            if not zs_txt or not ze_txt:
                continue
            try:
                zs = float(zs_txt)
                ze = float(ze_txt)
            except ValueError:
                continue
            if ze < zs:
                zs, ze = ze, zs
            segs.append((0.0, zs, ze))  # thickness 占位，算法不用
        return segs

    def _on_load_file(self, target_edit=None):
        """载入两列数据文件回填到文本框。target_edit 默认 span_edit。"""
        if target_edit is None:
            target_edit = self.span_edit
        path, _ = QFileDialog.getOpenFileName(
            self, '载入数据', self.input_dir,
            '数据文件 (*.csv *.txt *.xlsx *.xls);;所有文件 (*.*)',
        )
        if not path:
            return
        try:
            positions, values = parse_span_file(path)
        except Exception as e:
            self.log_area.append(f'⚠ 载入失败：{e}')
            return
        # 回填到文本框（无表头）
        lines = []
        for p, v in zip(positions, values):
            lines.append(f'{p:.6g}, {v:.6g}')
        target_edit.setPlainText('\n'.join(lines))
        self.log_area.append(f'✓ 已载入 {positions.size} 行：{path}')

    # ============================================================
    # 预览（输入变化时防抖重算 + 重绘，不写 CSV）
    # ============================================================
    def _connect_preview_signals(self):
        """挂所有输入信号到防抖预览。必须在所有控件创建完后调用。"""
        from PyQt5.QtCore import QTimer
        if not hasattr(self, '_preview_timer'):
            self._preview_timer = QTimer(self)
            self._preview_timer.setSingleShot(True)
            self._preview_timer.setInterval(300)
            self._preview_timer.timeout.connect(self._compute_preview)
        # 标准表 / VG 表 / 文本框 任何改动 → 防抖预览
        self.profile_table.cellChanged.connect(self._schedule_preview)
        self.vg_table.cellChanged.connect(self._schedule_preview)
        self.span_edit.textChanged.connect(self._schedule_preview)
        self.aoa_edit.textChanged.connect(self._schedule_preview)

    def _schedule_preview(self, *_):
        """输入变化 → 防抖 300ms 后跑预览。"""
        # timer 在 _connect_preview_signals 里惰性创建
        self._preview_timer.start()

    def _compute_preview(self):
        """预览：读输入 + 同步跑算法 + 缓存 self._result + 重绘。

        - 不写 CSV、不写日志、不禁用按钮（轻量级，让用户即时看到效果）
        - 输入非法（行数不足、解析失败）→ 静默返回，保留旧预览
        - 任何异常都吞掉，避免输入编辑过程中弹错
        """
        import numpy as np
        try:
            # 1. 标准表
            pts = self._read_profile()
            if not pts or len(pts) < 2:
                return
            std_thickness = np.array([p[0] for p in pts], dtype=float)
            std_alpha_std = np.array([p[1] for p in pts], dtype=float)
            std_alpha_vg = {float(p[0]): float(p[2]) for p in pts if p[2] is not None}
            if not std_alpha_vg:
                std_alpha_vg = None

            # 2. VG 段
            vg_segments = self._read_vg_segments()

            # 3. 展向分布
            text = self.span_edit.toPlainText().strip()
            if not text:
                return
            positions, thickness = parse_span_text(text)
            positions, _ = normalize_positions(positions)

            # 4. 攻角分布
            text_aoa = self.aoa_edit.toPlainText().strip()
            if not text_aoa:
                return
            aoa_positions, aoa = parse_span_text(text_aoa)
            aoa_positions, _ = normalize_positions(aoa_positions)

            # 5. 同步算
            span_alpha, vg_active = compute_alpha_span(
                positions, thickness, std_thickness, std_alpha_std,
                std_alpha_vg=std_alpha_vg, vg_segments=vg_segments,
            )
            crossings = find_intersections(
                positions, span_alpha, aoa_positions, aoa)
        except Exception:
            return  # 预览阶段静默

        # 6. 缓存 + 重绘
        self._result = {
            'std_thickness': std_thickness,
            'std_alpha_std': std_alpha_std,
            'std_alpha_vg': std_alpha_vg,
            'vg_segments': vg_segments,
            'vg_active': np.asarray(vg_active, dtype=bool),
            'positions': positions,
            'thickness': thickness,
            'span_alpha': np.asarray(span_alpha),
            'aoa_positions': aoa_positions,
            'aoa': aoa,
            'crossings': crossings or [],
        }
        self._refresh_plot()

    # ============================================================
    # 输入持久化（记忆上次填入的数据）
    # ============================================================
    def _restore_inputs(self):
        """启动时从 配置/stall_assessment_inputs.json 恢复上次的输入。"""
        data = load_inputs()
        if data is None:
            return  # 无存档，用代码里的默认值
        try:
            # 标准翼型表
            profile = data.get('profile')
            if isinstance(profile, list) and profile:
                t = self.profile_table
                t.setRowCount(len(profile))
                for r, row in enumerate(profile):
                    # row = [t, alpha_std, alpha_vg_or_None]
                    t.setItem(r, 0, QTableWidgetItem(f'{row[0]:g}'))
                    t.setItem(r, 1, QTableWidgetItem(f'{row[1]:g}'))
                    vg = row[2] if len(row) > 2 and row[2] is not None else ''
                    t.setItem(r, 2, QTableWidgetItem(f'{vg:g}' if vg != '' else ''))
            # 展向分布 / 最大攻角分布
            span_text = data.get('span_text')
            if isinstance(span_text, str) and span_text:
                self.span_edit.setPlainText(span_text)
            aoa_text = data.get('aoa_text')
            if isinstance(aoa_text, str) and aoa_text:
                self.aoa_edit.setPlainText(aoa_text)
            # VG 安装段
            vg_segs = data.get('vg_segments')
            if isinstance(vg_segs, list) and vg_segs:
                t = self.vg_table
                t.setRowCount(len(vg_segs))
                for r, seg in enumerate(vg_segs):
                    t.setItem(r, 0, QTableWidgetItem(f'{seg[0]:g}'))
                    t.setItem(r, 1, QTableWidgetItem(f'{seg[1]:g}'))
        except Exception:
            pass  # 恢复失败不影响启动，用默认值

    def _persist_inputs(self):
        """把当前输入保存到 配置/stall_assessment_inputs.json。"""
        try:
            # 标准表 → [[t, alpha_std, alpha_vg_or_None], ...]
            profile = []
            for r in range(self.profile_table.rowCount()):
                items = [self.profile_table.item(r, c) for c in range(3)]
                if items[0] is None or items[1] is None:
                    continue
                try:
                    t = float(items[0].text())
                    a = float(items[1].text())
                except ValueError:
                    continue
                vg = None
                if items[2] is not None:
                    txt = items[2].text().strip()
                    if txt:
                        try:
                            vg = float(txt)
                        except ValueError:
                            pass
                profile.append([t, a, vg])
            # VG 段 → [[zs, ze], ...]
            vg_segs = []
            for r in range(self.vg_table.rowCount()):
                i0, i1 = self.vg_table.item(r, 0), self.vg_table.item(r, 1)
                if i0 is None or i1 is None:
                    continue
                try:
                    zs, ze = float(i0.text()), float(i1.text())
                except ValueError:
                    continue
                vg_segs.append([zs, ze])
            save_inputs({
                'profile': profile,
                'span_text': self.span_edit.toPlainText(),
                'aoa_text': self.aoa_edit.toPlainText(),
                'vg_segments': vg_segs,
            })
        except Exception:
            pass  # 保存失败静默，不影响使用

    # ============================================================
    # 运行
    # ============================================================
    def _on_run(self):
        import numpy as np
        # 1. 读标准表
        pts = self._read_profile()
        if not pts or len(pts) < 2:
            self.log_area.append('⚠ 标准翼型表至少需要 2 个有效行。')
            return
        std_thickness = np.array([p[0] for p in pts], dtype=float)
        std_alpha_std = np.array([p[1] for p in pts], dtype=float)
        # VG 字典：thickness → alpha_vg（VG 列非空子集）
        std_alpha_vg = {float(p[0]): float(p[2]) for p in pts if p[2] is not None}
        if not std_alpha_vg:
            std_alpha_vg = None

        # 2. 读 VG 安装表
        vg_segments = self._read_vg_segments()

        # 3. 读展向分布
        text = self.span_edit.toPlainText().strip()
        if not text:
            self.log_area.append('⚠ 展向分布为空，请粘贴数据或载入文件。')
            return
        try:
            positions, thickness = parse_span_text(text)
        except Exception as e:
            self.log_area.append(f'⚠ 展向分布解析失败：{e}')
            return
        # 展向位置无量纲化（若输入的是实际位置，最大值 > 1 则归一化）
        positions, span_norm = normalize_positions(positions)

        # 4. 读攻角分布
        text_aoa = self.aoa_edit.toPlainText().strip()
        if not text_aoa:
            self.log_area.append('⚠ 攻角分布为空，请粘贴数据或载入文件。')
            return
        try:
            aoa_positions, aoa = parse_span_text(text_aoa)
        except Exception as e:
            self.log_area.append(f'⚠ 攻角分布解析失败：{e}')
            return
        # 攻角分布展向位置同样无量纲化
        aoa_positions, aoa_norm = normalize_positions(aoa_positions)

        # 5. 启动 Worker
        self.log_area.clear()
        if span_norm:
            self.log_area.append('ℹ 展向分布：检测到实际展向位置，已自动转为无量纲 r/R')
        if aoa_norm:
            self.log_area.append('ℹ 攻角分布：检测到实际展向位置，已自动转为无量纲 r/R')
        if std_alpha_vg and vg_segments:
            self.log_area.append(f'ℹ VG 模式：{len(vg_segments)} 段 VG 安装生效')
        else:
            self.log_area.append('ℹ 未配置 VG → 走 PCHIP 兼容路径')
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.run_btn.setText('计算中...')
        self.open_btn.setEnabled(False)
        # 启动计算前先持久化输入（校验已通过，输入是有意义的）
        self._persist_inputs()

        self._worker = StallAssessmentWorker(
            std_thickness, std_alpha_std, std_alpha_vg, vg_segments,
            positions, thickness, aoa_positions, aoa, self.out_dir,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(
            lambda: self._on_finished(std_thickness, std_alpha_std,
                                       std_alpha_vg, vg_segments,
                                       positions, thickness,
                                       aoa_positions, aoa))
        self._worker.start()

    def _on_finished(self, std_thickness, std_alpha_std, std_alpha_vg,
                      vg_segments,
                      positions, thickness, aoa_positions, aoa):
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
            'std_thickness': std_thickness,
            'std_alpha_std': std_alpha_std,
            'std_alpha_vg': std_alpha_vg,
            'vg_segments': vg_segments,
            'vg_active': np.asarray(self._worker.vg_active, dtype=bool),
            'positions': positions,
            'thickness': thickness,
            'span_alpha': np.asarray(span_alpha),
            'aoa_positions': aoa_positions,
            'aoa': aoa,
            'crossings': self._worker.crossings or [],
        }
        # 结果栏已移除（用户要求），不再填表；结果数据留在 _result 供画图 + 复制
        # 刷新画图（双曲线 + 相交点 + VG 阴影/边界）
        self._refresh_plot()
        self.open_btn.setEnabled(True)

    def _on_copy_result(self):
        if self._result is None:
            return
        positions = self._result['positions']
        thickness = self._result['thickness']
        span_alpha = self._result['span_alpha']
        vg_active = self._result.get('vg_active')
        has_vg = vg_active is not None and bool(vg_active.any())
        if has_vg:
            lines = ['span_position,relative_thickness,stall_alpha_deg,vg_active']
            for i in range(positions.size):
                lines.append(f'{positions[i]:.6g},{thickness[i]:.6g},'
                             f'{span_alpha[i]:.4f},{int(bool(vg_active[i]))}')
        else:
            lines = ['span_position,relative_thickness,stall_alpha_deg']
            for i in range(positions.size):
                lines.append(f'{positions[i]:.6g},{thickness[i]:.6g},{span_alpha[i]:.4f}')
        QApplication_clipboard('\n'.join(lines))
        self.log_area.append(f'✓ 已复制 {positions.size} 行到剪贴板')

    # ============================================================
    # 画布
    # ============================================================
    def _refresh_plot_placeholder(self):
        self.ax_span.clear()
        self.ax_span.text(0.5, 0.5, '点击「计算失速攻角」开始',
                          ha='center', va='center', fontsize=12,
                          transform=self.ax_span.transAxes)
        self.ax_span.set_axis_off()
        self.fig.tight_layout()
        self.canvas.draw()

    def _refresh_plot(self):
        if self._result is None:
            return
        # 移除上次可能创建的右轴（twinx），避免取消勾选后右轴残留
        for ax in list(self.fig.axes):
            if ax is not self.ax_span:
                self.fig.delaxes(ax)
        self.ax_span.clear()

        # VG 安装区域阴影 + 段边界竖虚线（在 plot_span_compare 之前画，
        # 后续曲线压在阴影上方）
        vg_segments = self._result.get('vg_segments') or []
        if vg_segments:
            for i, (th, zs, ze) in enumerate(vg_segments):
                # 第一段加图例条目，其余段无 label（避免重复）
                self.ax_span.axvspan(zs, ze, alpha=0.18, color='#FCE4D6',
                                     zorder=0,
                                     label=('VG 安装区域' if i == 0 else None))
            # 段边界去重竖虚线
            bounds_set = set()
            for _, zs, ze in vg_segments:
                bounds_set.add(round(zs, 9))
                bounds_set.add(round(ze, 9))
            bounds = sorted(bounds_set)
            for i, z in enumerate(bounds):
                self.ax_span.axvline(z, linestyle=':', color='#888',
                                     linewidth=1.0, zorder=1,
                                     label=('VG 边界' if i == 0 else None))

        plot_span_compare(
            self.ax_span,
            self._result['positions'], self._result['span_alpha'],
            self._result['aoa_positions'], self._result['aoa'],
            crossings=self._result.get('crossings'),
            span_pos=self._result['positions'],
            span_thickness=self._result['thickness'],
            std_thickness=self._result['std_thickness'],
            show_thickness=self.show_thickness_cb.isChecked(),
        )
        self.fig.tight_layout()
        self.canvas.draw()

    def _on_save_figure(self):
        """保存当前画布为 PNG。未计算时提示。"""
        if self._result is None:
            self.log_area.append('⚠ 请先计算，再保存图片。')
            return
        default_name = 'stall_assessment.png'
        path, _ = QFileDialog.getSaveFileName(
            self, '保存图片', str(os.path.join(self.out_dir, default_name)),
            'PNG 图片 (*.png);;所有文件 (*.*)',
        )
        if not path:
            return
        try:
            # 导出用宽图比例（横轴 > 纵轴），不影响 GUI 画布显示
            orig_size = self.fig.get_size_inches()
            self.fig.set_size_inches(10, 4.5)
            self.fig.savefig(path, dpi=200, bbox_inches='tight')
            # 恢复 GUI 画布尺寸
            self.fig.set_size_inches(orig_size)
            self.canvas.draw()
            self.log_area.append(f'✓ 图片已保存：{path}')
        except Exception as e:
            self.log_area.append(f'⚠ 保存失败：{e}')


# Qt 已在顶部导入（Qt.Horizontal 供 QSplitter 使用）。


def QApplication_clipboard(text):
    """跨平台写剪贴板（避免在模块顶部 import QApplication 的副作用）。"""
    from PyQt5.QtWidgets import QApplication
    QApplication.clipboard().setText(text)
