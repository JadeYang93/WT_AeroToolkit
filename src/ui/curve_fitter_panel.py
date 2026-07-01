# -*- coding: utf-8 -*-
"""曲线拟合面板（QWidget 子类）。

从 pyqt_curve_fitter11.py 提取，UI 与业务分离：
  - 业务逻辑：src/curve_fitter/curve_fit.py（parse_data / generate_curve / calculate_interpolation）
  - 本文件：只负责 PyQt5 UI + matplotlib 画布

UI 结构：
  - 模块 banner
  - CurveFitterWidget：
      * 左：matplotlib 画布（原始点 + 拟合曲线 + 插值点叠加）
      * 右：数据输入 + 拟合参数 + 插值 + 操作按钮
"""
import os
from datetime import datetime

import numpy as np
import pandas as pd

from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QFont, QGuiApplication, QTextCursor, QTextCharFormat, QColor, QKeySequence
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QCheckBox,
    QDoubleSpinBox, QSpinBox, QPlainTextEdit, QTextEdit,
    QMessageBox, QGroupBox, QTabWidget,
    QSplitter, QFrame, QSizePolicy, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu,
    QShortcut,
)

# matplotlib 嵌入式画布（import plotting 触发中文字体配置）
import core.plotting as plotting  # noqa: F401
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from global_config import config_center
from business.curve_fitter import (
    parse_data, generate_curve, calculate_interpolation, MAX_ROWS,
)
from ui.segmented_fitter_widget import SegmentedFitterWidget


# 拟合方法下拉项 → curve_fitter 内部 key
_METHOD_ITEMS = [
    ('B 样条', 'spline'),
    ('三次样条', 'cubic'),
    ('Akima', 'akima'),
    ('PCHIP', 'pchip'),
    ('多项式', 'poly'),
]

# 绘图颜色循环（与原项目一致）
_PLOT_COLORS = ['b', 'r', 'g', 'm', 'c', 'y', 'k', 'orange', 'purple', 'brown']

# 命中测试容差（像素），与 segmented_fitter_widget.py 一致
_DRAG_TOL_PX = 8
# 选中点高亮颜色（金色描边）
_HIGHLIGHT_COLOR = 'gold'


class CurveFitterWidget(QWidget):
    """曲线拟合主功能 widget。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # v0.3.12: 弹窗改为内部日志栏（位于右侧参数面板底部）
        # 先占位为 no-op，_build_ui 创建 log_view 后切换为 self._write_log
        self._log = lambda msg, level='info': None
        # 运行时状态
        self.data = None              # ndarray (n_rows, n_cols)
        self.column_labels = []       # ["X", "Y1", ...]
        self.num_y_columns = 0
        self.fit_results = {}         # {key: y_new ndarray}
        self.fit_x_new = None         # ndarray
        self.interpolate_x = None     # list[float]
        self.interpolate_y_list = []  # list[ndarray]
        self.interpolate_scatters = []  # matplotlib 散点句柄
        # 实时拟合防抖定时器：spin_smooth / spin_poly_deg / method_combo 变化时
        # 只在停顿 300ms 后触发一次重拟合（避免连续调参时每帧都重算）
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(300)
        self._fit_timer.timeout.connect(lambda: self._on_fit(silent=True))
        # 点交互编辑状态：每 Y 列独立（key = 列索引，0-based）
        # value = {
        #     'hidden': set[int],                      # 隐藏的原始行号（删除进等待区）
        #     'moved':  dict[int, tuple[float,float]], # {orig_row: (new_x, new_y)}
        # }
        self.edits_by_col: dict = {}
        # 当前选中的点：(col_idx, orig_row)；None 表示未选中
        self._selected = None
        # 正在拖动的点（同 _selected 格式）
        self._dragging = None
        # 命中测试辅助：每次 _plot_data_and_fit 重建
        # list of (col_idx, orig_row, current_x, current_y)
        self._visible_points = []
        # 永久隐藏（清空等待区后，点不再可还原也不可见）
        self._permanent_hidden: dict = {}
        # 是否显示散点（toggle）
        self._show_points = True
        # 框选模式（rubber band）状态
        self._rubber_mode = False            # toggle：是否处于框选模式
        self._rubber_active = False          # 正在拖动画框
        self._rubber_patch = None            # matplotlib Rectangle 句柄
        self._rubber_start = None            # (x_data, y_data) 起点
        # 多选集合：{(col_idx, orig_row), ...}；单击外部或 Escape 清空
        self._selected_multi: set = set()
        # 基线快照：固定一份拟合曲线作为对比基准
        # 结构：{'method': str, 'x_new': {col: ndarray}, 'y_new': {col: ndarray}, 'visible': bool}
        self._baseline: dict | None = None
        # 视图失效标志：True 时 _plot_data_and_fit 允许 auto-fit；False 时保持当前 xlim/ylim
        # 解析/清空 → True；其余重绘（拖动/删除/拟合）→ False
        self._view_invalid = True
        # 撤销栈：每次破坏性编辑前压栈 edits_by_col 深拷贝；最多 5 步
        self._undo_stack: list = []
        self._undo_max = 5
        # 拖动起始快照标志（拖动整体算一步，按下时压栈一次）
        self._drag_snapshot_pushed = False
        self._build_ui()

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        body = QSplitter(Qt.Horizontal)

        # ---- 左：画布 + 右：等待区（QSplitter 并列）----
        plot_split = QSplitter(Qt.Horizontal)
        plot_split.setChildrenCollapsible(False)

        # 左：曲线视图
        plot_box = QGroupBox('曲线视图')
        plot_box.setObjectName('gb_data')
        plot_lay = QVBoxLayout(plot_box)
        plot_lay.setContentsMargins(8, 6, 8, 6)
        # 顶部工具行：显示列选择 + 显示点开关 + 框选模式 + 基线工具
        plot_tool_row = QHBoxLayout()
        plot_tool_row.setSpacing(8)
        plot_tool_row.addWidget(QLabel('显示列:'))
        self.col_combo = QComboBox()
        self.col_combo.setMinimumWidth(120)
        self.col_combo.addItem('全部 Y 列')
        self.col_combo.currentIndexChanged.connect(self._on_column_changed)
        plot_tool_row.addWidget(self.col_combo)
        # 显示点开关
        self.show_points_chk = QCheckBox('显示点')
        self.show_points_chk.setChecked(True)
        self.show_points_chk.setToolTip('取消则只画拟合曲线，不画散点')
        self.show_points_chk.stateChanged.connect(self._on_show_points_changed)
        plot_tool_row.addWidget(self.show_points_chk)
        plot_tool_row.addSpacing(8)
        # 框选模式
        self.rubber_btn = QPushButton('⬚ 框选')
        self.rubber_btn.setCheckable(True)
        self.rubber_btn.setToolTip(
            '框选模式：\n'
            '• 按住 Ctrl（或 Shift）+ 拖动 = 临时框选（松开按键即结束）；\n'
            '• 或点本按钮切换为常驻框选模式；\n'
            '框选后 Delete 键 / 右键菜单可批量删除。'
        )
        self.rubber_btn.toggled.connect(self._on_rubber_mode_toggled)
        plot_tool_row.addWidget(self.rubber_btn)
        # 撤销
        self.undo_btn = QPushButton(f'↶ 撤销 (0/{self._undo_max})')
        self.undo_btn.setEnabled(False)
        self.undo_btn.setToolTip('撤销上一步编辑（点编辑 / 拖动 / 批量删除 / 还原）。快捷键 Ctrl+Z')
        self.undo_btn.clicked.connect(self._on_undo)
        plot_tool_row.addWidget(self.undo_btn)
        plot_tool_row.addSpacing(8)
        # 基线工具
        self.baseline_pin_btn = QPushButton('📌 固定基线')
        self.baseline_pin_btn.setToolTip('把当前拟合曲线保存为基线（灰色虚线显示），后续编辑点后可对比变化')
        self.baseline_pin_btn.clicked.connect(self._on_pin_baseline)
        plot_tool_row.addWidget(self.baseline_pin_btn)
        self.baseline_show_chk = QCheckBox('显示基线')
        self.baseline_show_chk.setChecked(True)
        self.baseline_show_chk.setEnabled(False)
        self.baseline_show_chk.stateChanged.connect(self._on_baseline_visibility_changed)
        plot_tool_row.addWidget(self.baseline_show_chk)
        self.baseline_clear_btn = QPushButton('🗑 清除基线')
        self.baseline_clear_btn.setEnabled(False)
        self.baseline_clear_btn.clicked.connect(self._on_clear_baseline)
        plot_tool_row.addWidget(self.baseline_clear_btn)
        plot_tool_row.addStretch()
        plot_lay.addLayout(plot_tool_row)
        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        plot_lay.addWidget(self.canvas)
        self.toolbar = NavigationToolbar(self.canvas, self)
        plot_lay.addWidget(self.toolbar)

        # 右：等待区（已删除点的还原入口）
        waiting_box = QGroupBox('等待区 (0)')
        waiting_box.setObjectName('gb_data')
        waiting_box.setMinimumWidth(240)
        wl = QVBoxLayout(waiting_box)
        wl.setContentsMargins(8, 6, 8, 6)
        wl.setSpacing(4)
        from ui.help_button import add_help_to_groupbox
        add_help_to_groupbox(
            waiting_box,
            title='等待区说明',
            text=(
                '<b>等待区</b>：保存所有被删除的点。<br><br>'
                '• <b>还原</b>：选中行后点「↩ 还原」，或双击行即可恢复该点；<br>'
                '• <b>全部还原</b>：恢复所有列的全部删除点；<br>'
                '• <b>清空</b>：永久删除（不可撤销）；<br>'
                '• 表格支持 Ctrl 多选；<br>'
                '• 删除/移动只影响当前列，不污染其他列。'
            ),
        )
        self.waiting_table = QTableWidget()
        self.waiting_table.setColumnCount(3)
        self.waiting_table.setHorizontalHeaderLabels(['列', '原值 (X, Y)', '修改后 (X, Y)'])
        # 列宽策略：列窄、原值/修改后各占一半
        hdr = self.waiting_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        self.waiting_table.verticalHeader().setVisible(False)
        self.waiting_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.waiting_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.waiting_table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.waiting_table.cellDoubleClicked.connect(self._on_waiting_double_click)
        wl.addWidget(self.waiting_table, 1)
        wbtns = QHBoxLayout()
        wbtns.setSpacing(4)
        self.restore_sel_btn = QPushButton('↩ 还原')
        self.restore_sel_btn.setToolTip('还原选中行（可多选）')
        self.restore_sel_btn.clicked.connect(self._on_restore_selected)
        self.restore_all_btn = QPushButton('↩ 全部')
        self.restore_all_btn.setToolTip('还原所有列的所有删除点')
        self.restore_all_btn.clicked.connect(self._restore_all)
        self.clear_wait_btn = QPushButton('🗑 清空')
        self.clear_wait_btn.setToolTip('永久清空等待区（不可还原）')
        self.clear_wait_btn.clicked.connect(self._on_clear_waiting)
        wbtns.addWidget(self.restore_sel_btn)
        wbtns.addWidget(self.restore_all_btn)
        wbtns.addWidget(self.clear_wait_btn)
        wl.addLayout(wbtns)

        plot_split.addWidget(plot_box)
        plot_split.addWidget(waiting_box)
        plot_split.setSizes([460, 280])
        plot_split.setStretchFactor(0, 1)
        plot_split.setStretchFactor(1, 0)
        body.addWidget(plot_split)

        # ---- 右：参数 + 操作 ----
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        # 1) 数据输入
        grp_data = QGroupBox('数据输入')
        gd = QVBoxLayout(grp_data)
        gd.setContentsMargins(8, 6, 8, 6)
        btn_row = QHBoxLayout()
        load_btn = QPushButton('📂 载入文件')
        load_btn.clicked.connect(self._on_load_file)
        parse_btn = QPushButton('⚙ 解析')
        parse_btn.clicked.connect(self._on_parse)
        clear_btn = QPushButton('🗑 清除')
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(load_btn)
        btn_row.addWidget(parse_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        gd.addLayout(btn_row)
        gd.addWidget(QLabel('数据（第 1 列 X，其余列 Y，空白 / # 跳过）:'))
        self.data_edit = QPlainTextEdit()
        self.data_edit.setPlaceholderText('粘贴多列数据，或点「载入文件」读取 txt/csv')
        self.data_edit.setMaximumHeight(160)
        gd.addWidget(self.data_edit, 1)
        right_lay.addWidget(grp_data)

        # 2) 拟合参数
        grp_fit = QGroupBox('拟合参数')
        gf = QGridLayout(grp_fit)
        gf.setContentsMargins(8, 6, 8, 6)
        gf.addWidget(QLabel('方法:'), 0, 0)
        self.method_combo = QComboBox()
        for label, _key in _METHOD_ITEMS:
            self.method_combo.addItem(label)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        gf.addWidget(self.method_combo, 0, 1)
        gf.addWidget(QLabel('平滑因子 s:'), 1, 0)
        self.spin_smooth = QDoubleSpinBox()
        self.spin_smooth.setRange(0.0, 1e8)
        self.spin_smooth.setDecimals(3)
        self.spin_smooth.setSingleStep(0.1)
        self.spin_smooth.setValue(0.0)
        # 实时预览：调整平滑因子 → 防抖后自动重拟合
        self.spin_smooth.valueChanged.connect(self._fit_timer.start)
        gf.addWidget(self.spin_smooth, 1, 1)
        gf.addWidget(QLabel('多项式阶数:'), 2, 0)
        self.spin_poly_deg = QSpinBox()
        self.spin_poly_deg.setRange(1, 12)
        self.spin_poly_deg.setValue(3)
        # 实时预览：调整阶数 → 防抖后自动重拟合
        self.spin_poly_deg.valueChanged.connect(self._fit_timer.start)
        gf.addWidget(self.spin_poly_deg, 2, 1)
        fit_btn = QPushButton('▶ 生成拟合曲线')
        fit_btn.setObjectName('primaryBtn')
        fit_btn.setMinimumHeight(40)
        fit_btn.clicked.connect(self._on_fit)
        gf.addWidget(fit_btn, 3, 0, 1, 2)
        right_lay.addWidget(grp_fit)

        # 3) 插值（左右分布：X 输入 1/3 + 结果 2/3）
        grp_interp = QGroupBox('插值')
        gi = QHBoxLayout(grp_interp)
        gi.setContentsMargins(8, 6, 8, 6)
        gi.setSpacing(6)
        # 左 1/3：X 输入 + 操作按钮
        left_box = QVBoxLayout()
        left_box.setSpacing(4)
        left_box.addWidget(QLabel('插值 X（每行一个）:'))
        self.interp_edit = QPlainTextEdit()
        self.interp_edit.setPlaceholderText('输入需要求值的 X 坐标，每行一个')
        left_box.addWidget(self.interp_edit, 1)
        interp_row = QHBoxLayout()
        interp_btn = QPushButton('计算插值')
        interp_btn.clicked.connect(self._on_interp)
        self.show_interp_chk = QCheckBox('显示插值点')
        self.show_interp_chk.stateChanged.connect(self._on_show_interp_changed)
        interp_row.addWidget(interp_btn)
        interp_row.addWidget(self.show_interp_chk)
        interp_row.addStretch()
        left_box.addLayout(interp_row)
        # 右 2/3：结果
        right_box = QVBoxLayout()
        right_box.setSpacing(4)
        right_box.addWidget(QLabel('插值结果:'))
        self.interp_result = QTextEdit()
        self.interp_result.setReadOnly(True)
        right_box.addWidget(self.interp_result, 1)
        gi.addLayout(left_box, 1)
        gi.addLayout(right_box, 2)
        right_lay.addWidget(grp_interp)

        # 4) 运行日志（v0.3.12: 替换原"保存"按钮 —— 解析/拟合/插值状态写这里）
        grp_log = QGroupBox('运行日志')
        gl = QVBoxLayout(grp_log)
        gl.setContentsMargins(8, 6, 8, 6)
        gl.setSpacing(4)
        from ui.help_button import add_help_to_groupbox
        add_help_to_groupbox(
            grp_log,
            title='运行日志说明',
            text=(
                '<b>运行日志</b>：解析 / 拟合 / 插值的运行情况都写在这里。<br><br>'
                '• v0.3.12 起不再弹窗，所有状态信息汇总在日志栏；<br>'
                '• 颜色含义：<b>绿</b> = 成功 · <b>橙</b> = 警告 · <b>红</b> = 错误；<br>'
                '• 点「🗑 清空」可清除日志内容。'
            ),
        )
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addStretch()
        clear_btn = QPushButton('🗑 清空')
        clear_btn.clicked.connect(lambda: self.log_view.clear())
        head.addWidget(clear_btn)
        gl.addLayout(head)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setObjectName('logView')
        self.log_view.setFixedHeight(120)
        mono = QFont('Consolas')
        mono.setStyleHint(QFont.Monospace)
        self.log_view.setFont(mono)
        gl.addWidget(self.log_view, 1)
        right_lay.addWidget(grp_log, 1)
        right_lay.addStretch()

        # 日志回调切换为内部 _write_log（依赖 self.log_view，须在创建后绑定）
        self._log = self._write_log

        # 右侧栏包 QScrollArea：窗口高度不够时 4 个 GroupBox 可滚动，避免被裁剪
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 关键：splitter 默认用 child 的 sizeHint 当 min size，scrollarea 会被撑到
        # 内容自然高，没法缩小 → 滚动条永远不出现。设 minimumHeight=0 让它能被压扁
        right.setMinimumHeight(0)
        right_scroll.setMinimumHeight(0)

        body.addWidget(right_scroll)
        body.setSizes([620, 380])
        outer.addWidget(body, 3)

        self._init_plot()
        # 画布交互：点选中 / 右键删除 / 拖动 / 框选 / 键盘删除
        self.canvas.mpl_connect('button_press_event',   self._on_point_press)
        self.canvas.mpl_connect('motion_notify_event',  self._on_point_motion)
        self.canvas.mpl_connect('button_release_event', self._on_point_release)
        self.canvas.mpl_connect('key_press_event',      self._on_canvas_key)
        # widget 级 Ctrl+Z 撤销（不要求画布聚焦）
        QShortcut(QKeySequence('Ctrl+Z'), self, activated=self._on_undo)

    def _init_plot(self):
        self.ax.set_xlabel('X')
        self.ax.set_ylabel('Y')
        self.ax.set_title('曲线拟合')
        self.ax.grid(True, alpha=0.3)
        self.fig.tight_layout()
        self.canvas.draw()

    # ------------------------------------------------------------
    # 业务
    # ------------------------------------------------------------
    def _on_load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择数据文件', '', '文本 (*.txt *.csv *.dat);;所有文件 (*.*)'
        )
        if not path:
            return
        try:
            # 多编码回退（与原项目一致）
            text = None
            for enc in ('utf-8', 'latin-1', 'utf-16', 'gbk', 'cp936', 'gb2312', 'big5'):
                try:
                    with open(path, 'r', encoding=enc) as f:
                        text = f.read()
                    break
                except (UnicodeDecodeError, OSError):
                    continue
            if text is None:
                # 最后回退 chardet
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
        text = self.data_edit.toPlainText()
        if not text.strip():
            self._log('解析失败：数据为空', 'warning')
            return
        try:
            data, labels = parse_data(text, max_rows=MAX_ROWS)
        except Exception as e:
            self._log(f'解析失败：{e}', 'error')
            return
        self.data = data
        self.column_labels = labels
        self.num_y_columns = data.shape[1] - 1
        self.fit_results = {}
        self.fit_x_new = None
        self.interpolate_x = None
        self.interpolate_y_list = []
        # 清空编辑状态（重新解析数据 = 全新开始）
        self.edits_by_col = {}
        self._permanent_hidden = {}
        self._selected = None
        self._dragging = None
        self._visible_points = []
        self._selected_multi.clear()
        self._baseline = None
        self._view_invalid = True  # 新数据 → 下次绘图 auto-fit
        self._undo_stack.clear()
        self._drag_snapshot_pushed = False
        self._sync_undo_btn()
        # 基线控件重置
        self.baseline_show_chk.setEnabled(False)
        self.baseline_clear_btn.setEnabled(False)
        self.baseline_show_chk.setChecked(True)
        # 重置列下拉
        self.col_combo.blockSignals(True)
        self.col_combo.clear()
        self.col_combo.addItem('全部 Y 列')
        for i in range(self.num_y_columns):
            self.col_combo.addItem(f'Y{i+1}')
        self.col_combo.blockSignals(False)
        self.col_combo.setCurrentIndex(0)
        # 重置插值结果
        self.interp_result.clear()
        self._plot_data_and_fit()
        self._log(
            f'全段拟合：解析完成，共 {data.shape[0]} 行 × {data.shape[1]} 列',
            'success',
        )

    def _on_fit(self, silent=False):
        """执行拟合。silent=True 时失败静默（实时预览模式，不打扰用户调参）。

        v0.3.22: 改为 per-column 拟合——每列用各自 _effective_xy 返回的
        (xs, ys)，跳过该列被删除的点 + 应用移动过的点。
        fit_x_new 改为 dict {col: ndarray}，因为每列 X 范围可能不同。
        """
        if self.data is None:
            if not silent:
                self._log('拟合失败：请先解析数据', 'warning')
            return
        method_key = _METHOD_ITEMS[self.method_combo.currentIndex()][1]
        smooth = self.spin_smooth.value()
        poly_deg = self.spin_poly_deg.value()
        self.fit_results = {}
        self.fit_x_new = {}  # 改为 dict
        ok_cols = 0
        for col in range(self.num_y_columns):
            xs, ys, _ = self._effective_xy(col)
            if len(xs) < 2:
                if not silent:
                    self._log(f'Y{col+1} 跳过：可见点数 {len(xs)} < 2', 'warning')
                continue
            try:
                single = generate_curve(
                    xs, ys.reshape(-1, 1),
                    method=method_key, smooth=smooth,
                    poly_deg=poly_deg, n_points=500,
                )
            except Exception as e:
                if not silent:
                    self._log(f'Y{col+1} 拟合失败：{e}', 'error')
                continue
            # single 返回 {'{method}_y1': arr}，重映射到当前列号
            self.fit_results[f'{method_key}_y{col+1}'] = single[f'{method_key}_y1']
            self.fit_x_new[col] = np.linspace(float(xs.min()), float(xs.max()), 500)
            ok_cols += 1
        if ok_cols == 0:
            if not silent:
                self._log('拟合失败：所有列拟合均失败', 'warning')
            return
        self._plot_data_and_fit()
        if not silent:
            label = _METHOD_ITEMS[self.method_combo.currentIndex()][0]
            self._log(
                f'全段拟合：{label} 拟合完成，{ok_cols} 列出图',
                'success',
            )

    def _on_clear(self):
        self.data = None
        self.column_labels = []
        self.num_y_columns = 0
        self.fit_results = {}
        self.fit_x_new = None
        self.interpolate_x = None
        self.interpolate_y_list = []
        self.interpolate_scatters = []
        # 清空编辑状态
        self.edits_by_col = {}
        self._permanent_hidden = {}
        self._selected = None
        self._dragging = None
        self._visible_points = []
        self._selected_multi.clear()
        self._baseline = None
        self._view_invalid = True  # 清空 → 下次绘图 auto-fit
        self._undo_stack.clear()
        self._drag_snapshot_pushed = False
        self._sync_undo_btn()
        # 基线控件重置
        self.baseline_show_chk.setEnabled(False)
        self.baseline_clear_btn.setEnabled(False)
        self.baseline_show_chk.setChecked(True)
        self.data_edit.clear()
        self.interp_edit.clear()
        self.interp_result.clear()
        self.col_combo.blockSignals(True)
        self.col_combo.clear()
        self.col_combo.addItem('全部 Y 列')
        self.col_combo.blockSignals(False)
        self._refresh_waiting_table()
        self.ax.clear()
        self._init_plot()

    def _on_interp(self):
        if not self.fit_results:
            self._log('插值失败：请先生成拟合曲线', 'warning')
            return
        content = self.interp_edit.toPlainText()
        if not content.strip():
            self._log('插值失败：请先输入插值 X', 'warning')
            return
        # 解析 x 列表
        x_targets = []
        for line in content.strip().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            try:
                x_targets.append(float(parts[0].replace(',', '')))
            except (ValueError, IndexError):
                continue
        if not x_targets:
            self._log('插值失败：未解析到有效 X', 'warning')
            return
        method_key = _METHOD_ITEMS[self.method_combo.currentIndex()][1]
        smooth = self.spin_smooth.value()
        poly_deg = self.spin_poly_deg.value()
        ys = []
        for ci in range(self.num_y_columns):
            xs_eff, ys_eff, _ = self._effective_xy(ci)
            if len(xs_eff) < 2:
                ys.append(np.full(len(x_targets), np.nan))
                continue
            try:
                yv = calculate_interpolation(
                    xs_eff, ys_eff, x_targets,
                    method=method_key, smooth=smooth, poly_deg=poly_deg,
                )
            except Exception:
                yv = np.full(len(x_targets), np.nan)
            ys.append(yv)
        self.interpolate_x = x_targets
        self.interpolate_y_list = ys
        # 表格输出
        if self.num_y_columns == 1:
            header = 'X\tY'
        else:
            header = 'X\t' + '\t'.join(f'Y{i+1}' for i in range(self.num_y_columns))
        lines = [header]
        for i, xv in enumerate(x_targets):
            row = [f'{xv:.6f}']
            for j in range(self.num_y_columns):
                yv = ys[j][i]
                row.append('N/A' if np.isnan(yv) else f'{yv:.6f}')
            lines.append('\t'.join(row))
        self.interp_result.setPlainText('\n'.join(lines))
        if self.show_interp_chk.isChecked():
            self._plot_interpolation_points()
        self._log(
            f'全段拟合：插值完成，{len(x_targets)} 个 X × {self.num_y_columns} 列',
            'success',
        )

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

    # ------------------------------------------------------------
    # UI 事件
    # ------------------------------------------------------------
    def _on_method_changed(self, _idx):
        method_key = _METHOD_ITEMS[self.method_combo.currentIndex()][1]
        # 平滑因子只在 B 样条启用，多项式阶数只在 poly 启用
        self.spin_smooth.setEnabled(method_key == 'spline')
        self.spin_poly_deg.setEnabled(method_key == 'poly')
        # 方法切换也触发实时重拟合（已 parse 过数据才有效，否则 timer 触发时 silent 跳过）
        self._fit_timer.start()

    def _on_column_changed(self, _idx):
        # 切列时清空选中（避免跨列高亮残留）
        self._selected = None
        self._plot_data_and_fit()
        if self.show_interp_chk.isChecked() and self.interpolate_x is not None:
            self._plot_interpolation_points()

    def _on_show_interp_changed(self, _state):
        if self.interpolate_x is None:
            return
        if self.show_interp_chk.isChecked():
            self._plot_interpolation_points()
        else:
            for sc in self.interpolate_scatters:
                try:
                    sc.remove()
                except Exception:
                    pass
            self.interpolate_scatters = []
            self.ax.legend()
            self.canvas.draw()

    # ------------------------------------------------------------
    # 绘图
    # ------------------------------------------------------------
    def _columns_to_show(self):
        idx = self.col_combo.currentIndex()
        if idx <= 0:
            return list(range(self.num_y_columns))
        return [idx - 1]

    def _plot_data_and_fit(self):
        # 保留用户的缩放/平移视图（除非解析新数据/清空，由 _view_invalid 标记）
        preserve_view = (not self._view_invalid) and self.ax.has_data()
        old_xlim = self.ax.get_xlim() if preserve_view else None
        old_ylim = self.ax.get_ylim() if preserve_view else None
        self.ax.clear()
        method_key = _METHOD_ITEMS[self.method_combo.currentIndex()][1]
        cols = self._columns_to_show()
        # 基线（最先画，置于底层；灰色虚线）
        if (self._baseline is not None and self._baseline.get('visible', True)
                and self._baseline.get('x_new')):
            base_method = self._baseline.get('method', '')
            base_x = self._baseline['x_new']
            base_y = self._baseline['y_new']
            for i in cols:
                xb = base_x.get(i)
                yb = base_y.get(i)
                if xb is None or yb is None:
                    continue
                label = f'Y{i+1} 基线' if self.num_y_columns > 1 else '基线'
                self.ax.plot(xb, yb, '--',
                             color='#9aa0a6', linewidth=1.5, alpha=0.75,
                             label=label, zorder=4)
        # 原始散点（应用编辑：跳过 hidden/permanent，应用 moved）
        if self.data is not None and self._show_points:
            for i in cols:
                xs, ys, _rows = self._effective_xy(i)
                if len(xs) == 0:
                    continue
                color = _PLOT_COLORS[i % len(_PLOT_COLORS)]
                label = f'Y{i+1}' if self.num_y_columns > 1 else '原始'
                self.ax.plot(xs, ys, marker='o', linestyle='None',
                             color=color, markersize=5, label=label)
        # 拟合曲线（per-column x_new；fit_x_new 改为 dict {col: arr}）
        if self.fit_results and self.fit_x_new:
            for i in cols:
                key = f'{method_key}_y{i+1}'
                y_new = self.fit_results.get(key)
                x_new = self.fit_x_new.get(i) if isinstance(self.fit_x_new, dict) else self.fit_x_new
                if y_new is None or x_new is None:
                    continue
                color = _PLOT_COLORS[i % len(_PLOT_COLORS)]
                label = f'Y{i+1} 拟合' if self.num_y_columns > 1 else '拟合'
                self.ax.plot(x_new, y_new, '-',
                             color=color, linewidth=2, label=label)
        # 多选高亮（金色描边；批量删除的目标）
        if self._selected_multi and self.data is not None:
            for sel_col, sel_row in self._selected_multi:
                if sel_col in cols:
                    try:
                        x_sel, y_sel = self._current_xy(sel_col, sel_row)
                    except Exception:
                        continue
                    self.ax.plot([x_sel], [y_sel], 'o',
                                 markersize=10, markerfacecolor='none',
                                 markeredgecolor=_HIGHLIGHT_COLOR,
                                 markeredgewidth=2.0, alpha=0.85, zorder=11)
        # 单选高亮（金色描边大圆）
        if self._selected is not None:
            sel_col, sel_row = self._selected
            if sel_col in cols:
                x_sel, y_sel = self._current_xy(sel_col, sel_row)
                self.ax.plot([x_sel], [y_sel], 'o',
                             markersize=12, markerfacecolor='none',
                             markeredgecolor=_HIGHLIGHT_COLOR,
                             markeredgewidth=2.5, zorder=12)
        self.ax.set_xlabel('X')
        self.ax.set_ylabel('Y')
        self.ax.set_title('曲线拟合')
        self.ax.grid(True, alpha=0.3)
        if self.data is not None or self.fit_results:
            self.ax.legend()
        # 恢复用户的缩放/平移视图
        if old_xlim is not None and old_ylim is not None:
            try:
                self.ax.set_xlim(old_xlim)
                self.ax.set_ylim(old_ylim)
            except Exception:
                pass
        else:
            self.fig.tight_layout()
        # 视图已生效，后续重绘默认保持
        self._view_invalid = False
        self.canvas.draw()
        # 重置插值散点（ax.clear 已销毁）
        self.interpolate_scatters = []
        # 重建命中测试用 _visible_points
        self._refresh_visible_points()

    def _plot_interpolation_points(self):
        if self.interpolate_x is None or not self.interpolate_y_list:
            return
        # 清除旧的
        for sc in self.interpolate_scatters:
            try:
                sc.remove()
            except Exception:
                pass
        self.interpolate_scatters = []
        cols = self._columns_to_show()
        xs = np.array(self.interpolate_x)
        for i in cols:
            yv = self.interpolate_y_list[i]
            mask = ~np.isnan(yv)
            if not np.any(mask):
                continue
            color = _PLOT_COLORS[i % len(_PLOT_COLORS)]
            label = f'Y{i+1} 插值' if self.num_y_columns > 1 else '插值'
            sc = self.ax.scatter(
                xs[mask], yv[mask],
                color=color, marker='*', s=150,
                label=label, alpha=0.9,
                edgecolors='black', linewidths=1.0, zorder=10,
            )
            self.interpolate_scatters.append(sc)
        self.ax.legend()
        self.canvas.draw()

    # ============================================================
    # 点交互编辑（选中 / 右键删除 / 拖动 / 等待区还原）
    # ============================================================
    def _ensure_edits(self, col):
        """惰性创建 edits_by_col[col]，返回该列的编辑 dict。"""
        if col not in self.edits_by_col:
            self.edits_by_col[col] = {'hidden': set(), 'moved': {}}
        return self.edits_by_col[col]

    # ---------- 撤销栈 ----------
    def _push_undo_snapshot(self):
        """把当前 edits_by_col 深拷贝压入撤销栈（最多 _undo_max 步）。"""
        import copy as _copy
        snap = _copy.deepcopy(self.edits_by_col)
        self._undo_stack.append(snap)
        if len(self._undo_stack) > self._undo_max:
            self._undo_stack.pop(0)
        self._sync_undo_btn()

    def _sync_undo_btn(self):
        """同步撤销按钮文案 / enabled 状态。"""
        n = len(self._undo_stack)
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setText(f'↶ 撤销 ({n}/{self._undo_max})')
            self.undo_btn.setEnabled(n > 0)

    def _on_undo(self):
        """撤销上一步编辑：用栈顶快照替换当前 edits_by_col。"""
        if not self._undo_stack:
            return
        self.edits_by_col = self._undo_stack.pop()
        # 清理与该状态脱节的选中
        self._selected = None
        self._selected_multi.clear()
        self._sync_undo_btn()
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()
        self._log(f'已撤销，栈中剩余 {len(self._undo_stack)} 步', 'info')

    def _effective_xy(self, col):
        """返回 (xs, ys, orig_rows)：跳过 hidden + permanent_hidden，应用 moved。"""
        if self.data is None:
            return np.array([]), np.array([]), np.array([], dtype=int)
        n = self.data.shape[0]
        edits = self._ensure_edits(col)
        hidden = edits['hidden']
        permanent = self._permanent_hidden.get(col, set()) if hasattr(self, '_permanent_hidden') else set()
        moved = edits['moved']
        xs, ys, rows = [], [], []
        for r in range(n):
            if r in hidden or r in permanent:
                continue
            if r in moved:
                nx, ny = moved[r]
            else:
                nx, ny = float(self.data[r, 0]), float(self.data[r, col + 1])
            xs.append(nx); ys.append(ny); rows.append(r)
        return np.array(xs), np.array(ys), np.array(rows, dtype=int)

    def _current_xy(self, col, orig_row):
        """返回某点当前 (x, y)（应用 moved 或原始）。"""
        edits = self._ensure_edits(col)
        if orig_row in edits['moved']:
            return edits['moved'][orig_row]
        return (float(self.data[orig_row, 0]),
                float(self.data[orig_row, col + 1]))

    def _clamp_x_for_drag(self, col, orig_row, new_x):
        """clamp X 到邻居之间（保持严格递增）。"""
        if self.data is None:
            return new_x
        eps = 1e-6
        edits = self._ensure_edits(col)
        hidden, moved = edits['hidden'], edits['moved']
        visible = []
        for r in range(self.data.shape[0]):
            if r in hidden:
                continue
            x = moved[r][0] if r in moved else float(self.data[r, 0])
            visible.append((r, x))
        visible.sort(key=lambda v: v[1])
        try:
            idx = next(i for i, (r, _) in enumerate(visible) if r == orig_row)
        except StopIteration:
            return new_x
        lo = visible[idx - 1][1] + eps if idx > 0 else -np.inf
        hi = visible[idx + 1][1] - eps if idx < len(visible) - 1 else np.inf
        if lo < hi:
            return float(max(lo, min(hi, new_x)))
        return new_x  # 邻居挤死了，X 不动

    def _pick_point(self, event):
        """命中测试：返回 (col, orig_row) 或 None。"""
        if event.xdata is None or event.ydata is None:
            return None
        if not self._visible_points:
            return None
        event_px = self.ax.transData.transform((event.xdata, event.ydata))
        best = None
        best_dist = _DRAG_TOL_PX
        for col, row, x, y in self._visible_points:
            px = self.ax.transData.transform((x, y))
            d = np.hypot(px[0] - event_px[0], px[1] - event_px[1])
            if d < best_dist:
                best_dist = d
                best = (col, row)
        return best

    def _refresh_visible_points(self):
        """根据 col_combo 当前选择，重建 _visible_points。

        在 _plot_data_and_fit 末尾调用；命中测试读它。
        """
        self._visible_points = []
        if self.data is None:
            return
        for col in self._columns_to_show():
            xs, ys, rows = self._effective_xy(col)
            for x, y, r in zip(xs, ys, rows):
                self._visible_points.append((col, int(r), float(x), float(y)))

    def _on_point_press(self, event):
        if event.inaxes is not self.ax or self.data is None:
            return
        # 框选触发：toggle 模式 / Ctrl 按住 / Shift 按住 → 启动 rubber band
        mods = QGuiApplication.queryKeyboardModifiers()
        ctrl_held = bool(mods & Qt.ControlModifier)
        shift_held = bool(mods & Qt.ShiftModifier)
        rubber_trigger = self._rubber_mode or ctrl_held or shift_held
        if event.button == 1 and rubber_trigger:
            # 但若点中了一个点，仍优先拖动该点（除非 toggle 常驻模式）
            hit = self._pick_point(event)
            if hit is not None and not self._rubber_mode:
                self._selected = hit
                self._dragging = hit
                self._selected_multi.clear()
                self._plot_data_and_fit()
                return
            self._rubber_active = True
            self._rubber_start = (float(event.xdata), float(event.ydata))
            self._rubber_patch = None
            return
        if event.button == 1:  # 左键：选中 + 开始拖
            hit = self._pick_point(event)
            if hit is not None:
                # 拖动前压栈一次（整段拖动算一步撤销）
                if not self._drag_snapshot_pushed:
                    self._push_undo_snapshot()
                    self._drag_snapshot_pushed = True
                self._selected = hit
                self._dragging = hit
                # 单选清空多选
                self._selected_multi.clear()
                self._plot_data_and_fit()  # 重画高亮
            else:
                # 点空白：清空所有选中
                if self._selected is not None or self._selected_multi:
                    self._selected = None
                    self._selected_multi.clear()
                    self._plot_data_and_fit()
        elif event.button == 3:  # 右键：菜单
            hit = self._pick_point(event)
            if hit is not None:
                self._selected = hit
                self._plot_data_and_fit()
            self._show_context_menu(event)

    def _on_point_motion(self, event):
        # 框选：更新矩形
        if self._rubber_active and self._rubber_start is not None:
            if event.xdata is None or event.ydata is None:
                return
            x0, y0 = self._rubber_start
            x1, y1 = float(event.xdata), float(event.ydata)
            if self._rubber_patch is None:
                from matplotlib.patches import Rectangle as _Rect
                self._rubber_patch = _Rect(
                    (min(x0, x1), min(y0, y1)),
                    abs(x1 - x0), abs(y1 - y0),
                    linewidth=1.2, edgecolor='#2563eb',
                    facecolor='#3b82f6', alpha=0.15, zorder=15,
                )
                self.ax.add_patch(self._rubber_patch)
            else:
                self._rubber_patch.set_xy((min(x0, x1), min(y0, y1)))
                self._rubber_patch.set_width(abs(x1 - x0))
                self._rubber_patch.set_height(abs(y1 - y0))
            self.canvas.draw_idle()
            return
        if self._dragging is None:
            return
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        col, row = self._dragging
        new_x = self._clamp_x_for_drag(col, row, float(event.xdata))
        new_y = float(event.ydata)
        self._ensure_edits(col)['moved'][row] = (new_x, new_y)
        # 立即重画散点（含拖动位置），拟合曲线保留旧的（防抖）
        self._plot_data_and_fit()
        # 触发防抖重拟合
        self._fit_timer.start()

    def _on_point_release(self, event):
        # 拖动结束：重置快照标志
        self._drag_snapshot_pushed = False
        # 框选结束：计算矩形内的点 → 加入多选集合
        if self._rubber_active:
            self._rubber_active = False
            start = self._rubber_start
            self._rubber_start = None
            # 移除矩形
            if self._rubber_patch is not None:
                try:
                    self._rubber_patch.remove()
                except Exception:
                    pass
                self._rubber_patch = None
            if start is None or event.xdata is None or event.ydata is None:
                self.canvas.draw_idle()
                return
            x0, y0 = start
            x1, y1 = float(event.xdata), float(event.ydata)
            xmin, xmax = min(x0, x1), max(x0, x1)
            ymin, ymax = min(y0, y1), max(y0, y1)
            # 命中测试：所有 visible_points 中数据坐标落在矩形内的
            newly = set()
            for col, r, x, y in self._visible_points:
                if xmin <= x <= xmax and ymin <= y <= ymax:
                    newly.add((col, r))
            if newly:
                # 累加到多选（不清空旧选择 → 支持多次框选累加）
                self._selected_multi |= newly
                # 单选清空（避免两种选中并存造成视觉混乱）
                self._selected = None
                self._log(f'框选命中 {len(newly)} 个点（累计 {len(self._selected_multi)} 个）', 'info')
            else:
                self._log('框选未命中任何点', 'info')
            self._plot_data_and_fit()
            return
        self._dragging = None

    def _show_context_menu(self, event):
        menu = QMenu(self)
        # 多选优先：批量删除
        if self._selected_multi:
            n = len(self._selected_multi)
            act_batch = menu.addAction(f'🗑 删除 {n} 个选中点')
            act_batch.triggered.connect(self._delete_selected_multi)
            act_clear_sel = menu.addAction('✖ 清除多选')
            act_clear_sel.triggered.connect(self._clear_multi_selection)
            menu.addSeparator()
        if self._selected is not None:
            col, row = self._selected
            x_curr, y_curr = self._current_xy(col, row)
            label_col = f'Y{col+1}' if self.num_y_columns > 1 else '此点'
            act_del = menu.addAction(f'🗑 删除选中点 ({label_col}, x={x_curr:g})')
            act_del.triggered.connect(lambda _, c=col, r=row: self._delete_point(c, r))
        menu.addSeparator()
        n_hidden = sum(len(self.edits_by_col.get(c, {}).get('hidden', ()))
                       for c in range(self.num_y_columns))
        act_restore = menu.addAction(f'↩ 还原全部 ({n_hidden} 点)' if n_hidden else '↩ 还原全部')
        act_restore.triggered.connect(self._restore_all)
        if n_hidden:
            act_clear = menu.addAction('🗑 清空等待区（永久删除）')
            act_clear.triggered.connect(self._on_clear_waiting)
        act_reset = menu.addAction('↺ 重置当前列编辑（清移动 + 还原删除）')
        act_reset.triggered.connect(self._reset_current_col_edits)
        # 在鼠标屏幕位置弹出
        menu.exec_(self.canvas.mapToGlobal(QPoint(int(event.x), int(event.y))))

    def _delete_point(self, col, row):
        """删除点 → 进等待区。"""
        edits = self._ensure_edits(col)
        # 防御：至少保留 2 个可见点（否则无法拟合）
        n_visible = self.data.shape[0] - len(edits['hidden'])
        if n_visible <= 2:
            self._log(f'删除失败：Y{col+1} 仅剩 {n_visible} 个可见点（至少保留 2 个用于拟合）', 'warning')
            return
        self._push_undo_snapshot()
        edits['hidden'].add(row)
        if self._selected == (col, row):
            self._selected = None
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()

    def _delete_selected_multi(self):
        """批量删除多选集合中的点（跳过列内点数不足的）。"""
        if not self._selected_multi:
            return
        self._push_undo_snapshot()
        # 按 col 分组
        by_col: dict[int, list[int]] = {}
        for col, r in self._selected_multi:
            by_col.setdefault(col, []).append(r)
        ok, skip = 0, 0
        for col, rows in by_col.items():
            edits = self._ensure_edits(col)
            n_visible = self.data.shape[0] - len(edits['hidden'])
            # 该列还能删几个（保证至少剩 2 个）
            can_del = max(0, n_visible - 2)
            for r in rows:
                if can_del <= 0:
                    skip += 1
                    continue
                edits['hidden'].add(r)
                can_del -= 1
                ok += 1
        self._selected_multi.clear()
        self._selected = None
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()
        msg = f'批量删除 {ok} 个点'
        if skip:
            msg += f'（跳过 {skip} 个：列内点数不足）'
        self._log(msg, 'info')

    def _clear_multi_selection(self):
        """清空多选集合（不删除）。"""
        if self._selected_multi:
            self._selected_multi.clear()
            self._plot_data_and_fit()

    def _on_canvas_key(self, event):
        """画布键盘事件：Delete 批量删除、Escape 清空选择、Ctrl+Z 撤销。"""
        if event.key == 'delete':
            if self._selected_multi:
                self._delete_selected_multi()
            elif self._selected is not None:
                col, row = self._selected
                self._delete_point(col, row)
        elif event.key in ('ctrl+z', 'ctrl+Z'):
            self._on_undo()
        elif event.key == 'escape':
            changed = bool(self._selected_multi) or self._selected is not None
            self._selected_multi.clear()
            self._selected = None
            if changed:
                self._plot_data_and_fit()

    def _on_show_points_changed(self, state):
        """显示点 checkbox 切换。"""
        self._show_points = bool(state)
        self._plot_data_and_fit()

    def _on_rubber_mode_toggled(self, checked):
        """框选模式开关。"""
        self._rubber_mode = bool(checked)
        if self._rubber_mode:
            self.rubber_btn.setText('✓ 框选')
            self._log('已开启框选模式：拖动鼠标画矩形；Delete 键或右键批量删除', 'info')
        else:
            self.rubber_btn.setText('⬚ 框选')

    # ---------- 基线快照 ----------
    def _on_pin_baseline(self):
        """把当前拟合结果保存为基线。"""
        if not self.fit_results or not self.fit_x_new:
            self._log('请先生成拟合曲线，再固定基线', 'warning')
            return
        method_key = _METHOD_ITEMS[self.method_combo.currentIndex()][1]
        x_new_dict, y_new_dict = {}, {}
        for col in range(self.num_y_columns):
            key = f'{method_key}_y{col+1}'
            y_new = self.fit_results.get(key)
            x_new = (self.fit_x_new.get(col)
                     if isinstance(self.fit_x_new, dict)
                     else self.fit_x_new)
            if y_new is None or x_new is None:
                continue
            x_new_dict[col] = np.array(x_new, copy=True)
            y_new_dict[col] = np.array(y_new, copy=True)
        if not x_new_dict:
            self._log('没有可固定的拟合曲线', 'warning')
            return
        self._baseline = {
            'method': method_key,
            'x_new': x_new_dict,
            'y_new': y_new_dict,
            'visible': True,
        }
        self.baseline_show_chk.setEnabled(True)
        self.baseline_clear_btn.setEnabled(True)
        self.baseline_show_chk.setChecked(True)
        self._log(f'已固定基线（方法={method_key}，{len(x_new_dict)} 列）。后续编辑可见对比。', 'info')
        self._plot_data_and_fit()

    def _on_clear_baseline(self):
        """清除基线。"""
        if self._baseline is None:
            return
        self._baseline = None
        self.baseline_show_chk.setEnabled(False)
        self.baseline_clear_btn.setEnabled(False)
        self._log('已清除基线', 'info')
        self._plot_data_and_fit()

    def _on_baseline_visibility_changed(self, state):
        """切换基线显隐。"""
        if self._baseline is None:
            return
        self._baseline['visible'] = bool(state)
        self._plot_data_and_fit()

    def _restore_point(self, col, row):
        """从等待区还原单点（仅清 hidden，保留 moved）。"""
        self._push_undo_snapshot()
        edits = self._ensure_edits(col)
        edits['hidden'].discard(row)
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()

    def _restore_all(self):
        """还原所有列的所有删除点。"""
        self._push_undo_snapshot()
        for col in range(self.num_y_columns):
            self._ensure_edits(col)['hidden'].clear()
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()

    def _on_restore_selected(self):
        """从等待区表选中行还原（支持多选）。"""
        rows = sorted({idx.row() for idx in self.waiting_table.selectedIndexes()})
        if not rows:
            self._log('请先在等待区表选中一行', 'warning')
            return
        self._push_undo_snapshot()
        targets = []  # (col, orig_row)
        for r in rows:
            item = self.waiting_table.item(r, 0)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            if data is not None:
                targets.append(data)
        for col, orig_row in targets:
            self._ensure_edits(col)['hidden'].discard(orig_row)
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()
        if targets:
            self._log(f'已从等待区还原 {len(targets)} 个点', 'info')

    def _on_waiting_double_click(self, row, _col):
        """双击等待区行 → 还原该点（直接读 UserRole，行号无关）。"""
        item = self.waiting_table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if data is None:
            return
        col, orig_row = data
        self._restore_point(col, orig_row)

    def _on_clear_waiting(self):
        """永久清空等待区：把 hidden 行的 moved 也清掉，hidden 保留为「已永久删除」标记。

        简化语义：清空等待区 = 把这些点的删除变为「永久」（清掉 hidden 标记的同时，
        也清掉 moved，并视作这些点从未存在）。

        实现上：直接清空所有 hidden + 对应 moved；下次画图时这些点不会回来，
        也不再出现在等待区表里。
        """
        # 注意：这里没法真"删除"原始数据 self.data 的行（多列共享）；
        # 语义采用：清空等待区 = 把 hidden 标记永久化（点不再可见，也不在等待区）。
        # 但 hidden 一旦清空，点就回来了。所以正确做法是把 hidden 转为"永久隐藏"。
        # 简化：弹确认对话框，用户确认后清掉 hidden 标记（点会回来——这与"清空"语义冲突）。
        # 最干净：保留 hidden 标记，但不显示在等待区表里。需要额外"永久隐藏"集合。
        # 折中实现：把 hidden 移到 _permanent_hidden。
        if not hasattr(self, '_permanent_hidden'):
            self._permanent_hidden = {c: set() for c in range(self.num_y_columns)}
        reply = QMessageBox.question(
            self, '清空等待区',
            '将永久删除等待区中的所有点（无法还原）。确认？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._push_undo_snapshot()
        for col in range(self.num_y_columns):
            edits = self._ensure_edits(col)
            self._permanent_hidden.setdefault(col, set()).update(edits['hidden'])
            edits['hidden'].clear()
            # 同时清掉这些行的 moved（无意义了）
            for r in list(edits['moved'].keys()):
                if r in self._permanent_hidden[col]:
                    del edits['moved'][r]
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()

    def _reset_current_col_edits(self):
        """重置当前 col_combo 所选列的编辑（清 hidden + 清 moved）。"""
        self._push_undo_snapshot()
        idx = self.col_combo.currentIndex()
        if idx <= 0:
            # 全部列模式：重置所有列
            for col in range(self.num_y_columns):
                self._ensure_edits(col)['hidden'].clear()
                self._ensure_edits(col)['moved'].clear()
        else:
            col = idx - 1
            self._ensure_edits(col)['hidden'].clear()
            self._ensure_edits(col)['moved'].clear()
        if hasattr(self, '_permanent_hidden'):
            for col in list(self._permanent_hidden.keys()):
                self._permanent_hidden[col].clear()
        self._selected = None
        self._refresh_waiting_table()
        self._plot_data_and_fit()
        self._fit_timer.start()

    def _refresh_waiting_table(self):
        """重建等待区表格 + 更新标题计数。

        每行 3 列：[列标签, 原值(X, Y), 修改后(X, Y)]。
        列单元格挂 UserRole=(col, orig_row)，使还原逻辑不再依赖行号映射。
        """
        t = self.waiting_table
        t.blockSignals(True)
        t.setRowCount(0)
        total = 0
        if self.data is not None:
            for col in range(self.num_y_columns):
                edits = self.edits_by_col.get(col, {'hidden': set(), 'moved': {}})
                for row in sorted(edits['hidden']):
                    x_orig = float(self.data[row, 0])
                    y_orig = float(self.data[row, col + 1])
                    if row in edits['moved']:
                        x_curr, y_curr = edits['moved'][row]
                    else:
                        x_curr, y_curr = x_orig, y_orig
                    moved_flag = row in edits['moved']
                    r = t.rowCount()
                    t.insertRow(r)
                    col_item = QTableWidgetItem(f'Y{col+1}')
                    col_item.setData(Qt.UserRole, (col, row))
                    # 数值保留小数点后 3 位有效数字
                    orig_item = QTableWidgetItem(f'{x_orig:.3f}, {y_orig:.3f}')
                    orig_item.setData(Qt.UserRole, (col, row))
                    curr_text = (f'{x_curr:.3f}, {y_curr:.3f}'
                                 if moved_flag else '— 未修改 —')
                    curr_item = QTableWidgetItem(curr_text)
                    curr_item.setData(Qt.UserRole, (col, row))
                    if moved_flag:
                        # 修改过的点用斜体灰字提示
                        from PyQt5.QtGui import QFont as _QF
                        f = _QF(); f.setItalic(True)
                        curr_item.setFont(f)
                        curr_item.setForeground(QColor('#0a7f3f'))
                    t.setItem(r, 0, col_item)
                    t.setItem(r, 1, orig_item)
                    t.setItem(r, 2, curr_item)
                    total += 1
        t.blockSignals(False)
        # 更新标题
        waiting_box = t.parent()
        if isinstance(waiting_box, QGroupBox):
            waiting_box.setTitle(f'等待区 ({total})')


# ============================================================
# 主面板
# ============================================================

class CurveFitterPanel(QWidget):
    MODULE_ID = 'curve_fitter'
    DEFAULT_INPUT_SUBDIR = 'curve_fitter'
    DEFAULT_OUTPUT_SUBDIR = 'curve_fitter'

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

        # v0.3.12: 每个 Tab 内自带日志栏（位于右侧参数面板底部）。
        # 全段拟合 Tab 移除"保存"按钮（导出功能移交分段复用 Tab）。
        self.tabs = QTabWidget()
        # 页签铺满栏宽 + 选中色块，与 catia_modeling 面板风格对齐
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.setStyleSheet(self._tab_qss())
        self.curve_widget = CurveFitterWidget()
        self.tabs.addTab(self.curve_widget, '📈  全段拟合')
        # 分段复用 widget 需要拿到 shape_design 的 STAGE-1 输出目录作为默认定位
        shape_paths = config_center.get_paths('shape_design')
        stage1_default_dir = os.path.join(shape_paths.get('output', ''), 'stage1')
        self.seg_widget = SegmentedFitterWidget(
            default_xlsx_dir=stage1_default_dir,
            default_output_dir=self.out_dir,
        )
        self.tabs.addTab(self.seg_widget, '✂  分段复用 (C2)')
        outer.addWidget(self.tabs, 1)

    def _tab_qss(self):
        """子 Tab 样式：深钢蓝底 + 选中天蓝实心，对齐 catia_modeling / 主导航风格。"""
        return """
        QTabBar { background: #1e3a5f; }
        QTabBar::tab {
            background: #1e3a5f;
            color: #94a3b8;
            font-size: 14px;
            font-weight: 600;
            padding: 16px 28px;
            margin: 0;
            border: none;
            border-left: 1px solid #2d4a6f;
        }
        QTabBar::tab:first { border-left: none; }
        QTabBar::tab:selected {
            background: #0ea5e9;
            color: #ffffff;
            font-weight: bold;
        }
        QTabBar::tab:hover:!selected {
            background: #234870;
            color: #ffffff;
        }
        QTabWidget::pane {
            border: 1px solid #e5e7eb;
            border-top: none;
            background: #ffffff;
        }
        """

    def _build_banner(self):
        banner = QWidget()
        banner.setObjectName('moduleBanner')
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(4)
        title = QLabel('曲线拟合')
        title.setObjectName('moduleTitle')
        title.setAlignment(Qt.AlignCenter)
        tf = QFont('YouSheBiaoTiHei', 16)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        title.setFont(tf)
        sub = QLabel('C U R V E   F I T T E R')
        sub.setObjectName('moduleSubtitle')
        sub.setAlignment(Qt.AlignCenter)
        sf = QFont('Consolas', 8)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        sf.setBold(True)
        sub.setFont(sf)
        bl.addWidget(title)
        bl.addWidget(sub)
        return banner
