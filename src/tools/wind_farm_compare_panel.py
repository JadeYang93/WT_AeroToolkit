# -*- coding: utf-8 -*-
"""风场对比面板（QWidget 子类）。

跨风场月均风速/密度对比，数据来源是每个风场子目录下的 风场统计数据.xlsx（由
wind_farm 模块生成）。UI 沿用 wind_farm_panel 的深钢蓝 banner + 左右双列 + 底部
执行栏 + 左右日志模式。
"""
import os
import sys
import subprocess
import pandas as pd
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate, QSize
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QCheckBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox,
    QDateEdit, QScrollArea, QFrame, QSizePolicy,
)
from wind_farm_compare import run_compare
from io_utils import scan_farm_dirs, EXCEL_FILENAME
from global_config import config_center


class FarmCompareWorker(QThread):
    """后台统计线程：跟 wind_farm_panel.StatsWorker 同模式。"""
    progress = pyqtSignal(int, str)

    def __init__(self, input_dir, out_dir, metrics, start_date, end_date):
        super().__init__()
        self.input_dir = input_dir
        self.out_dir = out_dir
        self.metrics = metrics
        self.start_date = start_date
        self.end_date = end_date
        self.result = None

    def run(self):
        self.result = run_compare(
            self.input_dir, self.out_dir, self.metrics,
            start_date=self.start_date, end_date=self.end_date,
            progress_callback=lambda p, m: self.progress.emit(p if p is not None else -1, m),
        )


class CompactScrollArea(QScrollArea):
    """QScrollArea 子类：重写 minimumSizeHint，让其在 layout 中能压缩到任意高度。

    与 wind_farm_panel 同名类一致实现，避免跨模块导入 UI 控件耦合。
    """

    def sizeHint(self):
        return QSize(0, 0)

    def minimumSizeHint(self):
        return QSize(0, 0)


class WindFarmComparePanel(QWidget):
    MODULE_ID = 'wind_farm_compare'
    DEFAULT_INPUT_SUBDIR = 'wind_farm_compare'
    DEFAULT_OUTPUT_SUBDIR = 'wind_farm_compare'

    def __init__(self):
        super().__init__()
        config_center.register_module(
            self.MODULE_ID, self.DEFAULT_INPUT_SUBDIR, self.DEFAULT_OUTPUT_SUBDIR)
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']

        config_center.paths_changed.connect(self._on_paths_changed)

        self._build_ui()
        self.setMinimumHeight(0)
        self.setMinimumSize(0, 0)
        self.scan_status.setText('请点击「扫描」按钮加载风场列表')

    def _on_paths_changed(self, module_id):
        """全局路径变更 slot。"""
        if module_id and module_id != self.MODULE_ID:
            return
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        if hasattr(self, 'folder_label'):
            self.folder_label.setText(self.input_dir)
            self._on_scan()

    def _build_ui(self):
        # === 滚动区 ===
        self._scroll = CompactScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._scroll.setMinimumHeight(0)
        inner = QWidget()
        outer = QVBoxLayout(inner)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # === 模块顶部 banner ===
        banner = QWidget()
        banner.setObjectName('moduleBanner')
        banner_layout = QVBoxLayout(banner)
        banner_layout.setContentsMargins(16, 14, 16, 14)
        banner_layout.setSpacing(4)
        self.module_title = QLabel('风场对比')
        self.module_title.setObjectName('moduleTitle')
        self.module_title.setAlignment(Qt.AlignCenter)
        title_font = QFont('YouSheBiaoTiHei', 16)
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        self.module_title.setFont(title_font)
        self.module_subtitle = QLabel('F A R M   C O M P A R I S O N')
        self.module_subtitle.setObjectName('moduleSubtitle')
        self.module_subtitle.setAlignment(Qt.AlignCenter)
        sub_font = QFont('Consolas', 8)
        sub_font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        sub_font.setBold(True)
        self.module_subtitle.setFont(sub_font)
        banner_layout.addWidget(self.module_title)
        banner_layout.addWidget(self.module_subtitle)
        outer.addWidget(banner)

        columns = QHBoxLayout()
        columns.setSpacing(8)
        columns.setContentsMargins(2, 2, 2, 2)
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
        layout = left_col

        # === 数据源 ===
        folder_box = QGroupBox('数据源')
        folder_box.setObjectName('gb_data')
        folder_layout = QVBoxLayout(folder_box)
        row1 = QHBoxLayout()
        self.folder_label = QLabel(self.input_dir)
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
        self.scan_status = QLabel('（未扫描）')
        self.scan_status.setObjectName('statusLabel')
        self.scan_status.setWordWrap(True)
        self.scan_status.setMinimumWidth(0)
        folder_layout.addWidget(self.scan_status)
        # 输入目录结构提示
        hint_label = QLabel(
            f'输入目录约定：每个子目录 = 一个风场，需含 {EXCEL_FILENAME}（由「风场数据统计」模块生成）'
        )
        hint_label.setObjectName('hintLabel')
        hint_label.setWordWrap(True)
        folder_layout.addWidget(hint_label)
        layout.addWidget(folder_box)

        # === 参数（指标 + 日期范围）===
        params_box = QGroupBox('参数')
        params_box.setObjectName('gb_params')
        params_layout = QVBoxLayout(params_box)
        params_layout.setSpacing(8)
        # 指标行
        metric_row = QHBoxLayout()
        metric_row.addWidget(QLabel('对比指标:'))
        self.cb_wind = QCheckBox('风速')
        self.cb_density = QCheckBox('密度')
        self.cb_wind.setChecked(True)
        self.cb_density.setChecked(True)
        metric_row.addWidget(self.cb_wind)
        metric_row.addWidget(self.cb_density)
        metric_row.addStretch()
        params_layout.addLayout(metric_row)
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
        left_col.addStretch()

        # 右列保留空白（与 wind_farm_panel 视觉对称；缺数据时由日志提示，不在 UI 上预置引导）
        right_col.addStretch()

        self._scroll.setWidget(inner)

        # === 底部执行栏 ===
        bottom = QWidget()
        bottom.setObjectName('execBar')
        bottom.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        bottom.setMinimumHeight(180)
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(2, 8, 2, 2)
        bottom_layout.setSpacing(10)

        left_wrap = QWidget()
        left_wrap.setFixedWidth(320)
        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        self.start_btn = QPushButton('开始统计')
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setObjectName('primaryBtn')
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self._on_start)
        self.open_output_btn = QPushButton('📂  打开输出')
        self.open_output_btn.setObjectName('secondaryBtn')
        self.open_output_btn.setMinimumHeight(36)
        self.open_output_btn.setCursor(Qt.PointingHandCursor)
        self.open_output_btn.setToolTip('在系统资源管理器中打开当前输出目录\n（运行成功后可用）')
        self.open_output_btn.setEnabled(False)
        self.open_output_btn.clicked.connect(self._on_open_output)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        left_layout.addWidget(self.start_btn)
        left_layout.addWidget(self.open_output_btn)
        left_layout.addWidget(self.progress_bar)
        left_layout.addStretch()

        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(QLabel('日志:'))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setObjectName('logArea')
        right_layout.addWidget(self.log_area, 1)

        bottom_layout.addWidget(left_wrap, 0)
        bottom_layout.addWidget(right_wrap, 1)

        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(0)
        wrap.addWidget(self._scroll, 1)
        wrap.addWidget(bottom, 0)

    def _log(self, msg):
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    def _on_scan(self):
        """扫描输入目录下的风场子目录，显示风场名 + Excel 是否就绪。"""
        farms = scan_farm_dirs(self.input_dir)
        if not farms:
            self.scan_status.setText(
                f'未找到任何子目录。请在 {self.input_dir} 下为每个风场建一个子目录，'
                f'并放入 {EXCEL_FILENAME}'
            )
            self.scan_status.setStyleSheet('color: #D32F2F;')
            return
        valid = [f for f in farms if f['has_excel']]
        missing = [f for f in farms if not f['has_excel']]
        # 缺 Excel 的风场用红色单独列出
        parts = [f'找到 {len(farms)} 个风场（{len(valid)} 个就绪）']
        if valid:
            parts.append('就绪: ' + '、'.join(f['name'] for f in valid))
        if missing:
            parts.append('缺 Excel: ' + '、'.join(f['name'] for f in missing))
        self.scan_status.setText('　|　'.join(parts))
        # 有任何风场未就绪 → 橙色；全就绪 → 绿色
        if missing:
            self.scan_status.setStyleSheet('color: #EF6C00;')
        else:
            self.scan_status.setStyleSheet('color: #2E7D32;')

    def _on_browse(self):
        d = QFileDialog.getExistingDirectory(self, '选择风场对比输入目录', self.input_dir)
        if d:
            self.input_dir = d
            self.folder_label.setText(d)
            self._on_scan()

    def _on_toggle_dates(self):
        enabled = not self.cb_all_dates.isChecked()
        self.date_start.setEnabled(enabled)
        self.date_end.setEnabled(enabled)

    def _on_start(self):
        # 收集选项
        metrics = []
        if self.cb_wind.isChecked():
            metrics.append('wind_speed')
        if self.cb_density.isChecked():
            metrics.append('density')
        if not metrics:
            QMessageBox.warning(self, '提示', '请至少勾选一个对比指标')
            return

        # 检查风场就绪状态（不强制要求扫描过，扫描结果是事实）
        farms = scan_farm_dirs(self.input_dir)
        valid = [f for f in farms if f['has_excel']]
        if not valid:
            QMessageBox.warning(
                self, '提示',
                f'输入目录下没有就绪的风场（每个子目录需含 {EXCEL_FILENAME}）。\n'
                f'请先在「风场数据统计」模块为各风场跑一次。'
            )
            return

        # 日期范围（Period）
        if self.cb_all_dates.isChecked():
            start_date = None
            end_date = None
        else:
            qd = self.date_start.date()
            start_date = pd.Period(year=qd.year(), month=qd.month(), freq='M')
            qd = self.date_end.date()
            end_date = pd.Period(year=qd.year(), month=qd.month(), freq='M')

        # 清空日志与进度
        self.log_area.clear()
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.start_btn.setText('运行中...')
        self.open_output_btn.setEnabled(False)
        self._log(f'输入: {self.input_dir}')
        self._log(f'输出: {self.out_dir}')
        self._log(f'指标: {metrics}')
        date_str = '全部' if start_date is None else f'{start_date} ~ {end_date}'
        self._log(f'日期范围: {date_str}')
        self._log('---')

        self.worker = FarmCompareWorker(
            self.input_dir, self.out_dir, metrics, start_date, end_date,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_progress(self, percent, msg):
        if percent >= 0:
            self.progress_bar.setValue(percent)
        self._log(msg)

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.start_btn.setText('开始统计')
        result = self.worker.result
        if result and result.get('error'):
            self._log(f'[错误] {result["error"]}')
            QMessageBox.critical(self, '错误', result['error'])
            self.open_output_btn.setEnabled(False)
        else:
            self._log('=== 完成 ===')
            self._log(f"生成图表: {result['plots']} 张")
            self._log(f"Excel: {result['excel']}")
            self.open_output_btn.setEnabled(True)
            self.open_output_btn.setToolTip(
                f'在系统资源管理器中打开：\n{self.out_dir}'
            )

    def _on_open_output(self):
        """跨平台打开当前输出目录。"""
        path = self.out_dir
        if not path:
            QMessageBox.warning(self, '提示', '输出目录尚未配置')
            return
        if not os.path.isdir(path):
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
