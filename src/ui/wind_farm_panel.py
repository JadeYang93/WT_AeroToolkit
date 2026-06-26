# -*- coding: utf-8 -*-
"""风场数据统计面板（QWidget 子类，由原 MainWindow 改造）。

作为「气动组工具箱」ToolShell 的右侧第一个面板。本文件不含入口 main()，
入口在 src/main.py 的 ToolShell 中。
"""
import os
import sys
import subprocess
import pandas as pd
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate, QSize
from PyQt5.QtGui import QColor, QPixmap, QIcon, QPainter, QPen, QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QCheckBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpinBox, QDateEdit, QComboBox, QScrollArea, QFrame, QSizePolicy
)
from business.wind_farm import run
from core.io_utils import get_monthly_ti_summary, scan_data_files
from config import (
    WINDOW_MIN, STEP_MIN, VALID_RATIO,
    UNSPECIFIED_BLADE_KEY, LINESTYLE_OPTIONS, LINE_WIDTHS, DEFAULT_LINEWIDTH,
    ALPHA_OPTIONS, DEFAULT_ALPHA,
)
from global_config import config_center
from ui.base_module_panel import BaseWorkerPanel


class StatsWorker(QThread):
    """后台统计线程。"""
    progress = pyqtSignal(int, str)   # (percent, message)

    def __init__(self, data_dir, out_dir, metrics, granularities,
                 highlight_turbines, include_turbines, ti_params, cache_path,
                 start_date=None, end_date=None, data_type='raw',
                 turbine_blades=None, blade_styles=None):
        super().__init__()
        self.data_dir = data_dir
        self.out_dir = out_dir
        self.metrics = metrics
        self.granularities = granularities
        self.highlight_turbines = highlight_turbines
        self.include_turbines = include_turbines
        self.ti_params = ti_params
        self.cache_path = cache_path
        self.start_date = start_date
        self.end_date = end_date
        self.data_type = data_type
        self.turbine_blades = turbine_blades or {}
        self.blade_styles = blade_styles or {}
        self.result = None

    def run(self):
        self.result = run(
            self.data_dir, self.out_dir,
            self.metrics, self.granularities,
            highlight_turbines=self.highlight_turbines,
            include_turbines=self.include_turbines,
            ti_params=self.ti_params,
            cache_path=self.cache_path,
            start_date=self.start_date,
            end_date=self.end_date,
            data_type=self.data_type,
            progress_callback=lambda p, m: self.progress.emit(p if p is not None else -1, m),
            turbine_blades=self.turbine_blades,
            blade_styles=self.blade_styles,
        )


class CompactScrollArea(QScrollArea):
    """QScrollArea 子类：重写 minimumSizeHint，让其在 layout 中能压缩到任意高度。

    原生 QScrollArea.minimumSizeHint 会透传内部 widget 高度，导致 panel 的
    minimumSizeHint 锁死，在高 DPI / 小屏下把常驻执行栏挤出可视区。
    """

    def sizeHint(self):
        return QSize(0, 0)

    def minimumSizeHint(self):
        return QSize(0, 0)


class ClickableCheckTable(QTableWidget):
    """整格可点击切换 checkbox 的 QTableWidget。

    Qt 默认行为：只有点中 checkbox 本身（约 14×14 像素）才切换，
    点格子其他空白区域不响应——窄列下用户要点好几次才能命中。
    本子类重写 mousePressEvent：左键点中带 ItemIsUserCheckable flag 的格子
    任意位置都切换 checkbox 状态。双击 / 编辑按键仍走原逻辑。
    """

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None and (item.flags() & Qt.ItemIsUserCheckable):
                new_state = (Qt.Unchecked if item.checkState() == Qt.Checked
                             else Qt.Checked)
                item.setCheckState(new_state)
                return   # 不调 super，避免触发编辑/选中
        super().mousePressEvent(event)


def _make_linestyle_icon(ls, fixed_lw=2.0):
    """用 QPainter 画一段线型预览图，作为 QComboBox 下拉项的 QIcon。

    ls: matplotlib linestyle 字符串 ('-'/'--'/'-.'/':') 或 dashes 元组 (0, (on, off, ...))
    fixed_lw: 图标内的固定线宽（实际宽度由独立的宽度列控制，这里只是示意）
    返回 QIcon。
    """
    pm = QPixmap(90, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor('#1e3a5f'))
    pen.setWidthF(fixed_lw)
    if isinstance(ls, str):
        qt_map = {
            '-':   Qt.SolidLine,
            '--':  Qt.DashLine,
            '-.':  Qt.DashDotLine,
            ':':   Qt.DotLine,
        }
        pen.setStyle(qt_map.get(ls, Qt.SolidLine))
    else:
        # matplotlib dashes tuple: (offset, (on, off, on, off, ...))
        pen.setStyle(Qt.CustomDashLine)
        pattern = ls[1] if isinstance(ls, tuple) else ls
        pen.setDashPattern([max(float(x), 1.0) for x in pattern])
    p.setPen(pen)
    p.drawLine(6, 9, 84, 9)
    p.end()
    return QIcon(pm)


class WindFarmStatsPanel(BaseWorkerPanel):
    # 模块自描述：声明 MODULE_ID + 默认子目录，ConfigCenter 用它注册路径
    MODULE_ID = 'wind_farm'
    DEFAULT_INPUT_SUBDIR = 'wind_farm'   # 相对 项目根/输入数据/
    DEFAULT_OUTPUT_SUBDIR = 'wind_farm'  # 相对 项目根/输出/
    # banner 显示（基类 _build_banner 用）
    MODULE_TITLE = '风场数据统计'
    MODULE_SUBTITLE = 'W I N D   F A R M   S T A T I S T I C S'
    # 执行栏按钮文字（基类 _build_exec_bar 用）
    RUN_BUTTON_TEXT = '开始统计'
    OPEN_BUTTON_TEXT = '📂  打开输出'

    @property
    def data_dir(self):
        """wind_farm 特殊命名：data_dir 是基类 input_dir 的别名。"""
        return self.input_dir

    @property
    def cache_path(self):
        """缓存文件路径：输出目录下 .cache.pkl。跟随 out_dir 自动更新。"""
        return os.path.join(self.out_dir, '.cache.pkl')

    def __init__(self):
        # data_type 必须在基类 __init__（会调 _build_body→_build_main_content）之前设好，
        # 因为 _build_main_content 内的 _on_data_type_changed 等会读它
        self.data_type = 'raw'   # 'raw' (秒级原始数据) 或 'monthly_ti' (月度湍流表)
        super().__init__()  # 基类 __init__: register_module + get_paths + _build_body
        # 基类已经创建好 run_btn，连到本类的 _on_start
        self.run_btn.clicked.connect(self._on_start)
        # 启动时不自动扫描，需用户手动点击「扫描」按钮后才加载机组列表
        self.scan_status.setText('请点击「扫描」按钮加载数据文件列表')

    def _on_paths_changed_extra(self):
        """基类已更新 input_dir/out_dir；本类只需同步 UI。"""
        if hasattr(self, 'folder_label'):
            self.folder_label.setText(self.data_dir)
            # 触发扫描，让用户立刻看到新目录里的机组
            self._on_scan()

    def _build_main_content(self):
        """主体内容：滚动区 + 双列卡片（机组配置 / 计算参数）。

        基类 _build_body 调用本方法并把返回的 widget 加到 outer_layout，
        然后基类自动追加 exec_bar。banner 也由基类负责。
        """
        # 内容包滚动区：窗口高度不足时（机组选择/叶型映射等内容较多）可滚动查看，避免底部被裁剪
        self._scroll = CompactScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        # 关键：用 Ignored 策略让 layout 完全忽略 scroll 的 sizeHint/minimumSizeHint，
        # 否则 QScrollArea 的 minimumSizeHint 会透传内部双列卡片高度（~426px），
        # 叠加 exec_bar 180px = 606px，把窗口高度锁死，在小屏/高 DPI 下 exec_bar 被挤出可视区
        self._scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._scroll.setMinimumHeight(0)
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        columns = QHBoxLayout()
        columns.setSpacing(8)
        columns.setContentsMargins(2, 2, 2, 2)
        # 左右两列：用 QWidget 包一层，配合 QSizePolicy.Ignored 让 QHBoxLayout 忽略 sizeHint，
        # 否则 stretch factor 只分额外空间、sizeHint 大的一方仍会挤占对方（机组表格列多时尤其明显）
        left_widget = QWidget()
        left_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        left_widget.setMinimumWidth(0)
        left_col = QVBoxLayout(left_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(6)
        right_widget = QWidget()
        right_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        right_widget.setMinimumWidth(0)
        right_col = QVBoxLayout(right_widget)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(6)
        columns.addWidget(left_widget, 1)
        columns.addWidget(right_widget, 1)
        outer.addLayout(columns)
        layout = left_col  # 默认加到左列

        # === 文件夹选择 ===
        folder_box = QGroupBox('数据源')
        folder_box.setObjectName('gb_data')
        folder_layout = QVBoxLayout(folder_box)
        # 第0行：数据类型选择
        row0 = QHBoxLayout()
        row0.addWidget(QLabel('数据类型:'))
        self.combo_data_type = QComboBox()
        self.combo_data_type.addItem('秒级原始数据', userData='raw')
        self.combo_data_type.addItem('月度湍流表', userData='monthly_ti')
        self.combo_data_type.currentIndexChanged.connect(self._on_data_type_changed)
        row0.addWidget(self.combo_data_type)
        row0.addStretch()
        folder_layout.addLayout(row0)
        # 第一行：路径 + 扫描按钮 + 浏览按钮
        row1 = QHBoxLayout()
        self.folder_label = QLabel(self.data_dir)
        self.folder_label.setMinimumWidth(300)
        scan_btn = QPushButton('扫描')
        scan_btn.setMinimumWidth(80)
        scan_btn.clicked.connect(self._on_scan)
        browse_btn = QPushButton('浏览...')
        browse_btn.setMinimumWidth(80)
        browse_btn.setToolTip('仅本次会话生效，不持久化。\n永久修改路径请点左侧导航栏底部的「⚙ 设置」。')
        browse_btn.clicked.connect(self._on_browse)
        row1.addWidget(self.folder_label, 1)
        row1.addWidget(scan_btn)
        row1.addWidget(browse_btn)
        folder_layout.addLayout(row1)
        # 第二行：扫描结果状态（机组号过多时自动换行，避免横向撑宽 GroupBox）
        self.scan_status = QLabel('（未扫描）')
        self.scan_status.setObjectName('statusLabel')
        self.scan_status.setWordWrap(True)
        self.scan_status.setMinimumWidth(0)
        folder_layout.addWidget(self.scan_status)
        layout.addWidget(folder_box)

        # === ② 统计内容（指标 + 粒度）===
        content_box = QGroupBox('统计内容')
        content_box.setObjectName('gb_stats')
        content_grid = QGridLayout(content_box)
        content_grid.setHorizontalSpacing(8)
        content_grid.setVerticalSpacing(6)
        content_grid.setContentsMargins(0, 0, 0, 0)
        content_grid.addWidget(QLabel('指标:'), 0, 0)
        metric_widget = QWidget()
        metric_layout = QHBoxLayout(metric_widget)
        self.cb_wind = QCheckBox('风速')
        self.cb_ti = QCheckBox('湍流度')
        self.cb_density = QCheckBox('密度')
        for cb in (self.cb_wind, self.cb_ti, self.cb_density):
            cb.setChecked(True)
            metric_layout.addWidget(cb)
        metric_layout.addStretch()
        content_grid.addWidget(metric_widget, 0, 1)
        content_grid.addWidget(QLabel('粒度:'), 1, 0)
        gran_widget = QWidget()
        gran_layout = QHBoxLayout(gran_widget)
        self.cb_daily = QCheckBox('日')
        self.cb_weekly = QCheckBox('周')
        self.cb_monthly = QCheckBox('月')
        self.cb_daily.setChecked(True)
        self.cb_monthly.setChecked(True)
        for cb in (self.cb_daily, self.cb_weekly, self.cb_monthly):
            gran_layout.addWidget(cb)
        gran_layout.addStretch()
        content_grid.addWidget(gran_widget, 1, 1)
        layout.addWidget(content_box)

        # === ③ 机组配置（机组表格 + 叶型映射）===
        turbine_box = QGroupBox('机组配置')
        turbine_box.setObjectName('gb_turbines')
        turbine_layout = QVBoxLayout(turbine_box)
        turbine_layout.setSpacing(6)
        # 包含/高亮 列批量按钮
        btn_row = QHBoxLayout()
        btn_row.addWidget(QLabel('包含:'))
        btn_inc_all = QPushButton('全选')
        btn_inc_none = QPushButton('全不选')
        btn_inc_all.clicked.connect(lambda: self._set_table_col(1, True))
        btn_inc_none.clicked.connect(lambda: self._set_table_col(1, False))
        btn_row.addWidget(btn_inc_all)
        btn_row.addWidget(btn_inc_none)
        btn_row.addSpacing(20)
        btn_row.addWidget(QLabel('高亮:'))
        btn_hl_all = QPushButton('全选')
        btn_hl_none = QPushButton('全不选')
        btn_hl_all.clicked.connect(lambda: self._set_table_col(2, True))
        btn_hl_none.clicked.connect(lambda: self._set_table_col(2, False))
        btn_row.addWidget(btn_hl_all)
        btn_row.addWidget(btn_hl_none)
        btn_row.addStretch()
        turbine_layout.addLayout(btn_row)
        # 机组表格（包含/高亮/叶型）—— 整格可点击切换 checkbox 的自定义子类
        self.table_turbines = ClickableCheckTable()
        self.table_turbines.setColumnCount(4)
        self.table_turbines.setHorizontalHeaderLabels(['机组号', '包含', '高亮', '叶型 ✎'])
        self.table_turbines.verticalHeader().setVisible(False)
        self.table_turbines.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        self.table_turbines.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_turbines.setFocusPolicy(Qt.NoFocus)
        header = self.table_turbines.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        # 列宽从 60 加到 90：原宽度下 checkbox 居中后实际命中区域过窄，难点中
        self.table_turbines.setColumnWidth(1, 90)
        self.table_turbines.setColumnWidth(2, 90)
        self.table_turbines.setMinimumHeight(100)
        self.table_turbines.setAlternatingRowColors(True)
        turbine_layout.addWidget(self.table_turbines, 3)
        # 叶型 → 线型 映射
        blade_row = QHBoxLayout()
        blade_row.addWidget(QLabel('叶型线型映射:'))
        btn_refresh_blade = QPushButton('刷新')
        btn_refresh_blade.setFixedWidth(60)
        btn_refresh_blade.setToolTip('扫描机组表格中的叶型文本，生成下方映射表行')
        btn_refresh_blade.clicked.connect(self._refresh_blade_styles)
        blade_row.addWidget(btn_refresh_blade)
        blade_row.addStretch()
        turbine_layout.addLayout(blade_row)
        self.table_blades = QTableWidget()
        self.table_blades.setColumnCount(4)
        self.table_blades.setHorizontalHeaderLabels(['叶型', '线型', '线宽', '透明度'])
        self.table_blades.verticalHeader().setVisible(False)
        self.table_blades.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_blades.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_blades.setFocusPolicy(Qt.NoFocus)
        bheader = self.table_blades.horizontalHeader()
        bheader.setSectionResizeMode(0, QHeaderView.Stretch)
        bheader.setSectionResizeMode(1, QHeaderView.Stretch)
        bheader.setSectionResizeMode(2, QHeaderView.Stretch)
        bheader.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_blades.setMinimumHeight(60)
        self.table_blades.setAlternatingRowColors(True)
        turbine_layout.addWidget(self.table_blades, 1)
        right_col.addWidget(turbine_box)

        # === ④ 计算参数（湍流度参数 + 日期范围）===
        params_box = QGroupBox('计算参数')
        params_box.setObjectName('gb_params')
        params_layout = QVBoxLayout(params_box)
        params_layout.setSpacing(8)
        # 湍流度参数行（整组随"湍流度"指标启用/禁用）
        self.ti_param_wrap = QWidget()
        ti_row = QHBoxLayout(self.ti_param_wrap)
        ti_row.setContentsMargins(0, 0, 0, 0)
        ti_row.addWidget(QLabel('湍流度  窗口(分):'))
        self.spin_window = QSpinBox()
        self.spin_window.setRange(1, 60)
        self.spin_window.setValue(WINDOW_MIN)
        ti_row.addWidget(self.spin_window)
        ti_row.addSpacing(12)
        ti_row.addWidget(QLabel('步长(分):'))
        self.spin_step = QSpinBox()
        self.spin_step.setRange(1, 30)
        self.spin_step.setValue(STEP_MIN)
        ti_row.addWidget(self.spin_step)
        ti_row.addSpacing(12)
        ti_row.addWidget(QLabel('有效率(%):'))
        self.spin_ratio = QSpinBox()
        self.spin_ratio.setRange(0, 100)
        self.spin_ratio.setValue(int(VALID_RATIO * 100))
        ti_row.addWidget(self.spin_ratio)
        ti_row.addStretch()
        params_layout.addWidget(self.ti_param_wrap)
        # 湍流度指标勾选联动：不选湍流度时参数自动禁用
        self.cb_ti.toggled.connect(self.ti_param_wrap.setEnabled)
        # 日期范围行
        date_row = QHBoxLayout()
        date_row.setContentsMargins(0, 0, 0, 0)
        date_row.addWidget(QLabel('日期范围:'))
        self.cb_all_dates = QCheckBox('全部')
        self.cb_all_dates.setChecked(True)
        self.cb_all_dates.stateChanged.connect(self._on_toggle_dates)
        date_row.addWidget(self.cb_all_dates)
        date_row.addSpacing(12)
        date_row.addWidget(QLabel('起始:'))
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDate(QDate.currentDate().addMonths(-1))
        self.date_start.setEnabled(False)
        date_row.addWidget(self.date_start)
        date_row.addSpacing(8)
        date_row.addWidget(QLabel('结束:'))
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDate(QDate.currentDate())
        self.date_end.setEnabled(False)
        date_row.addWidget(self.date_end)
        date_row.addStretch()
        params_layout.addLayout(date_row)
        layout.addWidget(params_box)
        left_col.addStretch()  # 左列底部留白，顶部对齐

        # 装入滚动区（上方参数配置）
        self._scroll.setWidget(inner)
        return self._scroll

    def _set_table_col(self, col, checked):
        """批量勾选/取消机组表格中指定列的所有项。"""
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.table_turbines.rowCount()):
            item = self.table_turbines.item(row, col)
            if item is not None:
                item.setCheckState(state)

    def _collect_checked_turbines(self, col):
        """收集表格中指定列被勾选的机组号列表（按行顺序）。"""
        result = []
        for row in range(self.table_turbines.rowCount()):
            name_item = self.table_turbines.item(row, 0)
            check_item = self.table_turbines.item(row, col)
            if name_item is None or check_item is None:
                continue
            if check_item.checkState() == Qt.Checked:
                result.append(name_item.data(Qt.UserRole))
        return result

    def _refresh_turbine_lists(self):
        """扫描当前文件夹，刷新机组表格。

        根据 self.data_type 决定扫描对象：
          - 'raw': 原始秒级数据文件（文件名正则）
          - 'monthly_ti': 月度湍流预计算文件（文件名含「月度湍流」）
        切换文件夹/数据类型/手动扫描时保留已勾选状态与叶型文本（若机组仍存在）。
        Returns: (scan_info, turbines) — scan_info 含日期范围信息，供状态显示用
        """
        # 记录之前的勾选与叶型
        prev_inc = set(self._collect_checked_turbines(1))
        prev_hl = set(self._collect_checked_turbines(2))
        prev_blades = self._collect_turbine_blades()

        scan_info = {}
        try:
            if self.data_type == 'monthly_ti':
                summary = get_monthly_ti_summary(self.data_dir)
                turbines = sorted(summary['turbines'])
                scan_info = {
                    'file_count': len(summary['files']),
                    'months': summary['months'],
                }
            else:
                files = scan_data_files(self.data_dir)
                turbines = sorted({f['turbine'] for f in files})
                scan_info = {
                    'file_count': len(files),
                    'files': files,
                }
        except Exception:
            turbines = []
            scan_info = {'file_count': 0}
        first_run = self.table_turbines.rowCount() == 0

        # 重建表格
        self.table_turbines.setRowCount(len(turbines))
        check_flags = Qt.ItemIsUserCheckable | Qt.ItemIsEnabled
        name_flags = Qt.ItemIsEnabled    # 机组号列不可编辑
        blade_flags = Qt.ItemIsEnabled | Qt.ItemIsEditable | Qt.ItemIsSelectable
        for row, t in enumerate(turbines):
            # 机组号
            name_item = QTableWidgetItem(f'#{t}号机组')
            name_item.setData(Qt.UserRole, t)
            name_item.setTextAlignment(Qt.AlignCenter)
            name_item.setFlags(name_flags)
            self.table_turbines.setItem(row, 0, name_item)

            # 包含列（默认全选 / 保留勾选）
            inc_item = QTableWidgetItem()
            inc_item.setFlags(check_flags)
            inc_item.setCheckState(Qt.Checked if (first_run or t in prev_inc) else Qt.Unchecked)
            self.table_turbines.setItem(row, 1, inc_item)

            # 高亮列（默认不勾 / 保留勾选）
            hl_item = QTableWidgetItem()
            hl_item.setFlags(check_flags)
            hl_item.setCheckState(Qt.Checked if t in prev_hl else Qt.Unchecked)
            self.table_turbines.setItem(row, 2, hl_item)

            # 叶型列（保留之前填写文本，可编辑）—— 浅琥珀底色 + 空时占位提示，强化"此处可输入"
            blade_text = prev_blades.get(t, '')
            blade_item = QTableWidgetItem(blade_text if blade_text else '(双击填叶型)')
            blade_item.setFlags(blade_flags)
            blade_item.setTextAlignment(Qt.AlignCenter)
            if blade_text:
                blade_item.setBackground(QColor('#fef3c7'))   # 已填：浅琥珀
                blade_item.setForeground(QColor('#92400e'))
            else:
                blade_item.setBackground(QColor('#fffbeb'))   # 空：更淡的米黄
                blade_item.setForeground(QColor('#9ca3af'))   # 占位文字灰色
            self.table_turbines.setItem(row, 3, blade_item)

        # 同步刷新叶型线型映射表（保留已选线型）
        self._refresh_blade_styles()
        return scan_info, turbines

    def _collect_turbine_blades(self):
        """收集机组表格中已填写的叶型文本。Returns: {机组号: 叶型名(非空)}"""
        result = {}
        for row in range(self.table_turbines.rowCount()):
            name_item = self.table_turbines.item(row, 0)
            blade_item = self.table_turbines.item(row, 3)
            if name_item is None or blade_item is None:
                continue
            txt = blade_item.text().strip()
            if txt and not txt.startswith('('):   # 跳过 '(双击填叶型)' 占位
                result[name_item.data(Qt.UserRole)] = txt
        return result

    def _refresh_blade_styles(self):
        """根据机组表格中已填写的叶型，刷新叶型线型映射表。

        - 收集 unique 叶型文本；若存在未填叶型的机组，额外加入「(未指定)」行
        - 保留用户已选线型（若该叶型仍存在）
        """
        # 先收集已选 (线型名, 宽度, 透明度)
        prev_styles = {}
        for row in range(self.table_blades.rowCount()):
            name_item = self.table_blades.item(row, 0)
            ls_combo = self.table_blades.cellWidget(row, 1)
            w_combo = self.table_blades.cellWidget(row, 2)
            a_combo = self.table_blades.cellWidget(row, 3)
            if name_item is None or ls_combo is None:
                continue
            width = None
            if w_combo is not None:
                try:
                    width = float(w_combo.currentText())
                except (ValueError, TypeError):
                    pass
            alpha = None
            if a_combo is not None:
                try:
                    alpha = float(a_combo.currentText())
                except (ValueError, TypeError):
                    pass
            # 兼容老格式（仅线型名）和新格式 (线型名, 宽度[, 透明度])
            prev_styles[name_item.text()] = (ls_combo.currentText(), width, alpha)

        # 收集叶型名(按出现顺序去重)
        blades_seen = []
        seen_set = set()
        any_unfilled = False
        for row in range(self.table_turbines.rowCount()):
            blade_item = self.table_turbines.item(row, 3)
            if blade_item is None:
                continue
            txt = blade_item.text().strip()
            if txt and not txt.startswith('('):   # 跳过 '(双击填叶型)' 占位
                if txt not in seen_set:
                    seen_set.add(txt)
                    blades_seen.append(txt)
            else:
                any_unfilled = True
        if any_unfilled:
            blades_seen.append(UNSPECIFIED_BLADE_KEY)

        # 重建映射表（4 列：叶型 / 线型 / 宽度 / 透明度）
        self.table_blades.setRowCount(len(blades_seen))
        options = list(LINESTYLE_OPTIONS.keys())
        width_strs = [str(w) for w in LINE_WIDTHS]
        alpha_strs = [f'{a:g}' for a in ALPHA_OPTIONS]
        for row, blade in enumerate(blades_seen):
            name_item = QTableWidgetItem(blade)
            name_item.setFlags(Qt.ItemIsEnabled)
            name_item.setTextAlignment(Qt.AlignCenter)
            self.table_blades.setItem(row, 0, name_item)

            # 线型 combo（icon + 名称）
            ls_combo = QComboBox()
            ls_combo.setIconSize(QSize(48, 12))
            for name in options:
                ls_combo.addItem(_make_linestyle_icon(LINESTYLE_OPTIONS[name]), name)
            default_ls_idx = min(row, len(options) - 1)
            chosen = prev_styles.get(blade)
            chosen_ls = chosen[0] if isinstance(chosen, tuple) else chosen
            if chosen_ls in options:
                ls_combo.setCurrentText(chosen_ls)
            else:
                ls_combo.setCurrentIndex(default_ls_idx)
            self.table_blades.setCellWidget(row, 1, ls_combo)

            # 宽度 combo（数字）
            w_combo = QComboBox()
            w_combo.addItems(width_strs)
            chosen_w = chosen[1] if (isinstance(chosen, tuple) and len(chosen) > 1 and chosen[1] is not None) else None
            if chosen_w is not None and f'{chosen_w:g}' in width_strs:
                w_combo.setCurrentText(f'{chosen_w:g}')
            else:
                w_combo.setCurrentText(str(DEFAULT_LINEWIDTH))
            self.table_blades.setCellWidget(row, 2, w_combo)

            # 透明度 combo（数字）
            a_combo = QComboBox()
            a_combo.addItems(alpha_strs)
            chosen_a = chosen[2] if (isinstance(chosen, tuple) and len(chosen) > 2 and chosen[2] is not None) else None
            if chosen_a is not None and f'{chosen_a:g}' in alpha_strs:
                a_combo.setCurrentText(f'{chosen_a:g}')
            else:
                a_combo.setCurrentText(f'{DEFAULT_ALPHA:g}')
            self.table_blades.setCellWidget(row, 3, a_combo)

    def _collect_blade_styles(self):
        """从叶型线型映射表收集 {叶型名: (线型名, 宽度, 透明度)}。"""
        result = {}
        for row in range(self.table_blades.rowCount()):
            name_item = self.table_blades.item(row, 0)
            ls_combo = self.table_blades.cellWidget(row, 1)
            w_combo = self.table_blades.cellWidget(row, 2)
            a_combo = self.table_blades.cellWidget(row, 3)
            if name_item is None or ls_combo is None or w_combo is None:
                continue
            ls_name = ls_combo.currentText()
            try:
                width = float(w_combo.currentText())
            except (ValueError, TypeError):
                width = DEFAULT_LINEWIDTH
            if a_combo is None:
                alpha = DEFAULT_ALPHA
            else:
                try:
                    alpha = float(a_combo.currentText())
                except (ValueError, TypeError):
                    alpha = DEFAULT_ALPHA
            result[name_item.text()] = (ls_name, width, alpha)
        return result

    def _update_scan_status(self, scan_info, turbines):
        """更新扫描状态标签 + 根据扫描结果刷新日期范围限制。

        根据 self.data_type 解释 scan_info。
        """
        file_count = scan_info.get('file_count', 0)
        if file_count == 0:
            self.scan_status.setText(
                '未找到符合命名规则的月度湍流文件' if self.data_type == 'monthly_ti'
                else '未找到符合命名规则的数据文件'
            )
            self.scan_status.setStyleSheet('color: #D32F2F;')
            return

        date_range_str = ''
        if self.data_type == 'monthly_ti':
            months = scan_info.get('months', [])
            if months:
                date_range_str = f"{months[0]} ~ {months[-1]}"
                # Period → QDate 边界
                q_start = QDate(months[0].year, months[0].month, 1)
                last = months[-1]
                last_day = (last.to_timestamp() + pd.offsets.MonthEnd(0)).day
                q_end = QDate(last.year, last.month, last_day)
                self.date_start.setMinimumDate(q_start)
                self.date_start.setMaximumDate(q_end)
                self.date_end.setMinimumDate(q_start)
                self.date_end.setMaximumDate(q_end)
                self.date_start.setDate(q_start)
                self.date_end.setDate(q_end)
            parts = [f'找到 {file_count} 个月度湍流文件']
            parts.append(f'{len(turbines)} 个机组 (机组号: {", ".join(f"#{t}" for t in turbines)})')
            if date_range_str:
                parts.append(f'月份: {date_range_str}')
        else:
            files = scan_info.get('files', [])
            dates = sorted({pd.Timestamp(f['date_str']) for f in files})
            if dates:
                date_range_str = (
                    f"{dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}"
                )
                q_start = QDate(dates[0].year, dates[0].month, dates[0].day)
                q_end = QDate(dates[-1].year, dates[-1].month, dates[-1].day)
                self.date_start.setMinimumDate(q_start)
                self.date_start.setMaximumDate(q_end)
                self.date_end.setMinimumDate(q_start)
                self.date_end.setMaximumDate(q_end)
                self.date_start.setDate(q_start)
                self.date_end.setDate(q_end)
            parts = [f'找到 {file_count} 个原始数据文件']
            parts.append(f'{len(turbines)} 个机组 (机组号: {", ".join(f"#{t}" for t in turbines)})')
            if date_range_str:
                parts.append(f'日期: {date_range_str}')

        self.scan_status.setText('，'.join(parts))
        self.scan_status.setStyleSheet('color: #2E7D32;')  # 绿色

    def _on_toggle_dates(self):
        """切换"全部日期"勾选时启用/禁用日期选择。"""
        enabled = not self.cb_all_dates.isChecked()
        self.date_start.setEnabled(enabled)
        self.date_end.setEnabled(enabled)

    def _on_scan(self):
        """手动扫描按钮：刷新机组列表 + 显示扫描结果。"""
        scan_info, turbines = self._refresh_turbine_lists()
        self._update_scan_status(scan_info, turbines)

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(self, '选择数据文件夹', self.data_dir)
        if d:
            self.data_dir = d
            self.folder_label.setText(d)
            scan_info, turbines = self._refresh_turbine_lists()
            self._update_scan_status(scan_info, turbines)

    def _on_data_type_changed(self):
        """切换数据类型时：更新 self.data_type + 重新扫描。"""
        self.data_type = self.combo_data_type.currentData()
        scan_info, turbines = self._refresh_turbine_lists()
        self._update_scan_status(scan_info, turbines)

    def _log(self, msg):
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    def _on_start(self):
        # 月度湍流表模式：只输出月度 TI 时间序列，与指标/粒度勾选无关
        is_monthly_ti = (self.data_type == 'monthly_ti')

        # 收集选项
        metrics = []
        if self.cb_wind.isChecked():
            metrics.append('wind_speed')
        if self.cb_ti.isChecked():
            metrics.append('ti')
        if self.cb_density.isChecked():
            metrics.append('density')

        granularities = []
        if self.cb_daily.isChecked():
            granularities.append('daily')
        if self.cb_weekly.isChecked():
            granularities.append('weekly')
        if self.cb_monthly.isChecked():
            granularities.append('monthly')

        if not is_monthly_ti:
            if not metrics:
                QMessageBox.warning(self, '提示', '请至少勾选一个指标')
                return
            if not granularities:
                QMessageBox.warning(self, '提示', '请至少勾选一个粒度')
                return

        # 未扫描时表格为空，引导用户先扫描
        if self.table_turbines.rowCount() == 0:
            QMessageBox.warning(self, '提示', '请先点击「扫描」按钮加载数据文件')
            return

        # 包含机组（必须至少选一个）
        include = self._collect_checked_turbines(1)
        if not include:
            QMessageBox.warning(self, '提示', '请至少勾选一个包含机组')
            return
        include = include if include else None

        # 高亮机组
        highlight = self._collect_checked_turbines(2)
        highlight = highlight if highlight else None

        # 叶型：先同步刷新映射表（保证用户没点刷新也能用最新填写值），再收集
        self._refresh_blade_styles()
        turbine_blades = self._collect_turbine_blades()
        blade_styles = self._collect_blade_styles()

        # TI 参数
        ti_params = {
            'window_min': self.spin_window.value(),
            'step_min': self.spin_step.value(),
            'valid_ratio': self.spin_ratio.value() / 100.0,
        }

        # 日期范围
        if self.cb_all_dates.isChecked():
            start_date = None
            end_date = None
        else:
            qd = self.date_start.date()
            start_date = pd.Timestamp(year=qd.year(), month=qd.month(), day=qd.day())
            qd = self.date_end.date()
            end_date = pd.Timestamp(year=qd.year(), month=qd.month(), day=qd.day())

        # 清空日志与进度
        self.log_area.clear()
        self.progress.setValue(0)
        self.run_btn.setEnabled(False)
        self.run_btn.setText('运行中...')
        self.open_btn.setEnabled(False)   # 运行中禁用，避免误点
        mode_str = '月度湍流表' if is_monthly_ti else '秒级原始数据'
        self._log(f'模式: {mode_str}')
        self._log(f'输入: {self.data_dir}')
        self._log(f'输出: {self.out_dir}')
        inc_str = [f'#{t}' for t in include] if include else '无'
        hl_str = [f'#{t}' for t in highlight] if highlight else '无'
        if not is_monthly_ti:
            self._log(f'指标: {metrics}  粒度: {granularities}')
        self._log(f'包含机组: {inc_str}   高亮机组: {hl_str}')
        if turbine_blades:
            blade_str = ', '.join(f'#{t}={b}' for t, b in sorted(turbine_blades.items()))
            self._log(f'叶型: {blade_str}')
            style_str = ', '.join(f'{k}→{v}' for k, v in blade_styles.items() if k != UNSPECIFIED_BLADE_KEY)
            if style_str:
                self._log(f'线型映射: {style_str}')
        date_str = '全部' if start_date is None else f'{start_date.date()} ~ {end_date.date()}'
        self._log(f'日期范围: {date_str}')
        if not is_monthly_ti:
            self._log(f"TI参数: 窗口={ti_params['window_min']}min  步长={ti_params['step_min']}min  有效率={ti_params['valid_ratio']:.0%}")
        self._log('---')

        # 启动线程
        self.worker = StatsWorker(
            self.data_dir, self.out_dir, metrics, granularities,
            highlight, include, ti_params, self.cache_path,
            start_date, end_date, self.data_type,
            turbine_blades=turbine_blades, blade_styles=blade_styles,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, percent, msg):
        if percent >= 0:
            self.progress.setValue(percent)
        self._log(msg)

    def _on_finished(self):
        self.run_btn.setEnabled(True)
        self.run_btn.setText('开始统计')
        result = self.worker.result
        if result and result.get('error'):
            self._log(f'[错误] {result["error"]}')
            QMessageBox.critical(self, '错误', result['error'])
            self.open_btn.setEnabled(False)
        else:
            self._log('=== 完成 ===')
            self._log(f"生成图表: {result['plots']} 张")
            self._log(f"Excel: {result['excel']}")
            # 成功后启用「打开输出」，让用户能一键跳到结果目录
            self.open_btn.setEnabled(True)
            self.open_btn.setToolTip(
                f'在系统资源管理器中打开：\n{self.out_dir}'
            )

    def _on_open_output(self):
        """跨平台打开当前输出目录到系统资源管理器。"""
        path = self.out_dir
        if not path:
            QMessageBox.warning(self, '提示', '输出目录尚未配置')
            return
        if not os.path.isdir(path):
            # pipeline 理论上会 makedirs，但保险起见再判一次
            QMessageBox.warning(self, '提示', f'输出目录不存在：\n{path}')
            return
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', path], check=False)
            else:
                subprocess.run(['xdg-open', path], check=False)
        except Exception as e:
            QMessageBox.warning(self, '打开失败', f'{e}')


