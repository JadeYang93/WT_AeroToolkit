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

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QGuiApplication, QTextCursor, QTextCharFormat, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QComboBox, QCheckBox,
    QDoubleSpinBox, QSpinBox, QPlainTextEdit, QTextEdit,
    QMessageBox, QGroupBox, QTabWidget,
    QSplitter, QFrame, QSizePolicy, QScrollArea,
)

# matplotlib 嵌入式画布（import plotting 触发中文字体配置）
import plotting  # noqa: F401
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from global_config import config_center
from curve_fitter import (
    parse_data, generate_curve, calculate_interpolation, MAX_ROWS,
)
from tools.segmented_fitter_widget import SegmentedFitterWidget


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
        self._build_ui()

    # ------------------------------------------------------------
    # UI
    # ------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        body = QSplitter(Qt.Horizontal)

        # ---- 左：画布 ----
        plot_box = QGroupBox('曲线视图')
        plot_box.setObjectName('gb_data')
        plot_lay = QVBoxLayout(plot_box)
        plot_lay.setContentsMargins(8, 6, 8, 6)
        # 顶部工具行：显示列选择（从「数据输入」迁移到画布左上角）
        plot_tool_row = QHBoxLayout()
        plot_tool_row.setSpacing(6)
        plot_tool_row.addWidget(QLabel('显示列:'))
        self.col_combo = QComboBox()
        self.col_combo.setMinimumWidth(140)
        self.col_combo.addItem('全部 Y 列')
        self.col_combo.currentIndexChanged.connect(self._on_column_changed)
        plot_tool_row.addWidget(self.col_combo)
        plot_tool_row.addStretch()
        plot_lay.addLayout(plot_tool_row)
        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        plot_lay.addWidget(self.canvas)
        self.toolbar = NavigationToolbar(self.canvas, self)
        plot_lay.addWidget(self.toolbar)
        body.addWidget(plot_box)

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
        head = QHBoxLayout()
        head.setSpacing(6)
        tip = QLabel('解析 / 拟合 / 插值的运行情况都写在这里（不再弹窗）')
        tip.setStyleSheet('color: #666; font-size: 11px;')
        head.addWidget(tip)
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
        """执行拟合。silent=True 时失败静默（实时预览模式，不打扰用户调参）。"""
        if self.data is None:
            if not silent:
                self._log('拟合失败：请先解析数据', 'warning')
            return
        method_key = _METHOD_ITEMS[self.method_combo.currentIndex()][1]
        smooth = self.spin_smooth.value()
        poly_deg = self.spin_poly_deg.value()
        x = self.data[:, 0]
        y_cols = self.data[:, 1:]
        try:
            results = generate_curve(
                x, y_cols, method=method_key,
                smooth=smooth, poly_deg=poly_deg,
                n_points=1000,
            )
        except Exception as e:
            if not silent:
                self._log(f'拟合失败：{e}', 'error')
            return
        if not results:
            if not silent:
                self._log('拟合失败：所有列拟合均失败', 'warning')
            return
        self.fit_results = results
        # 拟合曲线对应的 x_new（从 generate_curve 的内部逻辑无法直接拿到，这里重算一遍）
        sx = np.sort(x)
        n_points = 500 if len(sx) > 1000 else 1000
        self.fit_x_new = np.linspace(sx.min(), sx.max(), n_points)
        self._plot_data_and_fit()
        if not silent:
            label = _METHOD_ITEMS[self.method_combo.currentIndex()][0]
            self._log(
                f'全段拟合：{label} 拟合完成，{len(results)} 列出图',
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
        self.data_edit.clear()
        self.interp_edit.clear()
        self.interp_result.clear()
        self.col_combo.blockSignals(True)
        self.col_combo.clear()
        self.col_combo.addItem('全部 Y 列')
        self.col_combo.blockSignals(False)
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
        x_orig = self.data[:, 0]
        y_cols = self.data[:, 1:]
        ys = []
        for ci in range(self.num_y_columns):
            y_fit = y_cols[:, ci]
            try:
                yv = calculate_interpolation(
                    x_orig, y_fit, x_targets,
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
        self.ax.clear()
        method_key = _METHOD_ITEMS[self.method_combo.currentIndex()][1]
        cols = self._columns_to_show()
        # 原始散点
        if self.data is not None:
            x = self.data[:, 0]
            for i in cols:
                y = self.data[:, i + 1]
                color = _PLOT_COLORS[i % len(_PLOT_COLORS)]
                label = f'Y{i+1}' if self.num_y_columns > 1 else '原始'
                self.ax.plot(x, y, marker='o', linestyle='None',
                             color=color, markersize=5, label=label)
        # 拟合曲线
        if self.fit_results and self.fit_x_new is not None:
            for i in cols:
                key = f'{method_key}_y{i+1}'
                y_new = self.fit_results.get(key)
                if y_new is None:
                    continue
                color = _PLOT_COLORS[i % len(_PLOT_COLORS)]
                label = f'Y{i+1} 拟合' if self.num_y_columns > 1 else '拟合'
                self.ax.plot(self.fit_x_new, y_new, '-',
                             color=color, linewidth=2, label=label)
        self.ax.set_xlabel('X')
        self.ax.set_ylabel('Y')
        self.ax.set_title('曲线拟合')
        self.ax.grid(True, alpha=0.3)
        if self.data is not None or self.fit_results:
            self.ax.legend()
        self.fig.tight_layout()
        self.canvas.draw()
        # 重置插值散点（ax.clear 已销毁）
        self.interpolate_scatters = []

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
