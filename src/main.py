# -*- coding: utf-8 -*-
"""气动组工具箱 - 入口。

ToolShell（顶层 QMainWindow）：左侧深钢蓝导航栏（顶部品牌 banner + 工具列表 +
底部版本号）+ 右侧白底内容区。QSS 全部在 QApplication 级集中管理（pyqt6 规范）。

当前注册 1 个工具：风场数据统计（WindFarmStatsPanel）。
未来加新工具：在 tools/ 下新建 xxx_panel.py + 在下方 TOOLS 加一行。
"""
import sys
import os
import ctypes

# Windows 任务栏图标：必须显式设置 AppUserModelID，否则任务栏会显示 pythonw.exe 的默认图标。
# 必须在 QApplication 实例化之前调用。
if sys.platform == 'win32':
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('aerotoolkit.windfarm.1')

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase, QIcon, QPixmap, QColor, QBrush
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QListWidget, QStackedWidget, QPushButton, QSplashScreen,
)

from config import APP_VERSION, PROJECT_ROOT
from global_config import activity_hub
from ui.wind_farm_panel import WindFarmStatsPanel
from ui.wind_farm_compare_panel import WindFarmComparePanel
from ui.shape_design_panel import ShapeDesignPanel
from ui.blade_converter_panel import BladeConverterPanel
from ui.focus6_solver_panel import Focus6SolverPanel
from ui.load_estimation_panel import LoadEstimationPanel
from ui.stall_assessment_panel import StallAssessmentPanel
from ui.curve_fitter_panel import CurveFitterPanel
from ui.prebend_design_panel import PrebendDesignPanel
from ui.catia_modeling_panel import CatiaModelingPanel
from path_migration import migrate_legacy_paths, migrate_extras_between_modules
from settings_dialog import SettingsDialog
from help_viewer import HelpDialog


# 工具注册表：(导航栏显示名, 面板类)。顺序决定导航栏从上到下的顺序。
TOOLS = [
    ('🌬  风场数据统计', WindFarmStatsPanel),
    ('⚖  风场对比', WindFarmComparePanel),
    ('✈  叶片形状输出', ShapeDesignPanel),
    ('🔧  叶片结构套件', BladeConverterPanel),
    ('🎯  FOCUS6', Focus6SolverPanel),
    ('📊  载荷预估', LoadEstimationPanel),
    ('📏  失速评估', StallAssessmentPanel),
    ('📈  曲线拟合', CurveFitterPanel),
    ('📐  预弯设计', PrebendDesignPanel),
    ('🛠  3D 造型', CatiaModelingPanel),
]


# 工程仪表盘主题 QSS —— 深钢蓝 #1e3a5f + 气流青 #0ea5e9
# 设计原则：白底高对比工作区 + 深色导航 + 等宽数据字体（贴合 SCADA 工程感）
APP_STYLE = """
/* ===== 基础 ===== */
QWidget {
    color: #1f2937;
    font-family: 'Microsoft YaHei', '微软雅黑', sans-serif;
    font-size: 13px;
}
QMainWindow {
    background-color: #f5f6f8;
}
QWidget#contentWrap {
    background-color: #f5f6f8;
}

/* ===== 顶部菜单栏 ===== */
QMenuBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e5e7eb;
    color: #1f2937;
    padding: 2px 4px;
    font-size: 13px;
}
QMenuBar::item {
    background-color: transparent;
    padding: 6px 14px;
    border-radius: 3px;
}
QMenuBar::item:selected {
    background-color: #e0f2fe;
    color: #0369a1;
}
QMenuBar::item:pressed {
    background-color: #0ea5e9;
    color: #ffffff;
}
QMenu {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 28px 6px 18px;
    border-radius: 3px;
}
QMenu::item:selected {
    background-color: #0ea5e9;
    color: #ffffff;
}
QMenu::separator {
    height: 1px;
    background: #e5e7eb;
    margin: 4px 8px;
}

/* ===== 导航栏容器（深钢蓝）===== */
QWidget#navContainer {
    background-color: #1e3a5f;
}

/* ===== 顶部品牌 banner ===== */
QLabel#brandTitle {
    color: #ffffff;
    font-size: 15px;
    font-weight: bold;
    padding: 20px 16px 2px 16px;
    background-color: transparent;
}
QLabel#brandSubtitle {
    color: #7dd3fc;
    font-size: 10px;
    padding: 0 16px 14px 16px;
    background-color: transparent;
}

/* ===== 导航列表 ===== */
QListWidget#navList {
    background-color: #1e3a5f;
    border: none;
    outline: none;
    font-size: 15px;
    padding: 8px 0;
}
QListWidget#navList::item {
    padding: 18px 20px;
    color: #94a3b8;
    border-left: 4px solid transparent;
}
QListWidget#navList::item:selected {
    background-color: #0ea5e9;
    color: #ffffff;
    font-weight: bold;
    border-left: 4px solid #7dd3fc;
}
QListWidget#navList::item:hover {
    background-color: #234870;
    color: #ffffff;
}

/* ===== 底部版本号 ===== */
QLabel#versionLabel {
    color: #64748b;
    font-size: 11px;
    padding: 10px 16px;
    background-color: #172a45;
    border-top: 1px solid #2d4a6f;
}

/* ===== 导航栏底部「⚙ 设置」按钮 ===== */
QPushButton#navSettingsBtn {
    background-color: transparent;
    border: none;
    border-top: 1px solid #2d4a6f;
    color: #cbd5e1;
    text-align: left;
    padding: 12px 18px;
    font-size: 13px;
}
QPushButton#navSettingsBtn:hover {
    background-color: #234870;
    color: #ffffff;
}
QPushButton#navSettingsBtn:pressed {
    background-color: #0ea5e9;
    color: #ffffff;
}

/* ===== 模块顶部 banner（深钢蓝整条填充 + 白色居中标题，呼应导航栏品牌色）===== */
QWidget#moduleBanner {
    background-color: #1e3a5f;
    border: none;
    border-radius: 6px;
}
QLabel#moduleTitle {
    color: #ffffff;
    background-color: transparent;
    padding: 0;
    font-size: 22px;
    font-family: 'YouSheBiaoTiHei';
}
QLabel#moduleSubtitle {
    color: #7dd3fc;
    background-color: transparent;
    padding: 0;
    font-size: 10px;
    font-weight: bold;
    font-family: 'Consolas', 'Cascadia Code', 'Courier New', monospace;
}

/* ===== GroupBox 白卡片 ===== */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e5e7eb;
    border-left: 4px solid #1e3a5f;   /* 统一深钢蓝左边条 */
    border-radius: 6px;
    margin-top: 10px;
    padding: 14px 12px 8px 12px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 2px 10px;
    background-color: #1e3a5f;        /* 统一深钢蓝徽章底 */
    color: #ffffff;
    border-radius: 4px;
    font-weight: bold;
    font-size: 12px;
}

/* ===== 次要按钮（描边）===== */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 6px 14px;
    color: #374151;
}
QPushButton:hover {
    border-color: #0ea5e9;
    color: #0ea5e9;
}
QPushButton:pressed {
    background-color: #f0f9ff;
}
/* 主按钮（气流青→深钢蓝横向渐变，呼应导航栏 + 顶 banner 的品牌色组合）*/
QPushButton#primaryBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 #0ea5e9, stop:1 #1e3a5f);
    border: none;
    border-radius: 6px;
    color: #ffffff;
    font-weight: bold;
    font-size: 15px;
    padding: 12px 28px;
}
QPushButton#primaryBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 #38bdf8, stop:1 #2d4a6f);
}
QPushButton#primaryBtn:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                      stop:0 #0284c7, stop:1 #172a45);
}
/* 运行中（disabled）浅灰底，避免渐变在禁用态看起来像可用 */
QPushButton#primaryBtn:disabled {
    background-color: #cbd5e1;
    color: rgba(255, 255, 255, 200);
}

/* 次级 CTA（深钢蓝填充）—— 呼应导航栏品牌色，与主按钮橙形成冷暖对比 */
QPushButton#secondaryBtn {
    background-color: #1e3a5f;
    border: none;
    border-radius: 6px;
    color: #ffffff;
    font-weight: bold;
    font-size: 13px;
    padding: 8px 18px;
}
QPushButton#secondaryBtn:hover {
    background-color: #2d4a6f;
}
QPushButton#secondaryBtn:pressed {
    background-color: #172a45;
}
QPushButton#secondaryBtn:disabled {
    background-color: #cbd5e1;
    color: rgba(255, 255, 255, 200);
}

/* ===== 输入控件 ===== */
QComboBox, QSpinBox, QDateEdit {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 4px 8px;
    color: #1f2937;
    min-height: 22px;
}
QComboBox:focus, QSpinBox:focus, QDateEdit:focus {
    border: 1px solid #0ea5e9;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox::down-arrow {
    image: url({assets_dir}/combo-arrow.svg);
    width: 14px;
    height: 14px;
}
QSpinBox::up-button, QDateEdit::up-button {
    width: 20px;
}
QSpinBox::down-button, QDateEdit::down-button {
    width: 20px;
}
QSpinBox::up-arrow, QDateEdit::up-arrow {
    image: url({assets_dir}/spin-up.svg);
    width: 12px;
    height: 12px;
}
QSpinBox::down-arrow, QDateEdit::down-arrow {
    image: url({assets_dir}/spin-down.svg);
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    border: 1px solid #cbd5e1;
    selection-background-color: #0ea5e9;
    selection-color: #ffffff;
    outline: none;
}

/* ===== 表格（深钢蓝表头 + 斑马纹）===== */
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f1f5f9;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    gridline-color: #eef2f7;
    color: #1f2937;
}
QTableWidget::item {
    padding: 4px 6px;
}
QTableWidget::item:selected {
    background-color: #e0f2fe;
    color: #1f2937;
}
QHeaderView::section {
    background-color: #1e3a5f;
    color: #ffffff;
    padding: 6px 8px;
    border: none;
    font-weight: bold;
}

/* ===== 进度条（气流青）===== */
QProgressBar {
    background-color: #e5e7eb;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: #1f2937;
    min-height: 18px;
    max-height: 18px;
}
QProgressBar::chunk {
    background-color: #0ea5e9;
    border-radius: 4px;
}

/* ===== 流水线 Stepper（叶片形状输出模块 banner 下方）===== */
QWidget#stepperBar {
    background-color: #ffffff;
    border-bottom: 1px solid #e5e7eb;
}
QPushButton#stepperNode {
    background-color: #f1f5f9;
    color: #64748b;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    text-align: left;
    min-height: 22px;
}
QPushButton#stepperNode:hover {
    background-color: #e0f2fe;
    border-color: #0ea5e9;
    color: #0369a1;
}
/* 当前阶段：深钢蓝填充 + 白字 + 加粗，呼应 banner 品牌色 */
QPushButton#stepperNode[current=true] {
    background-color: #1e3a5f;
    color: #ffffff;
    border: 1px solid #1e3a5f;
    font-weight: bold;
}
QPushButton#stepperNode[current=true]:hover {
    background-color: #2d4a6f;
}
/* 节点之间的连线 */
QFrame#stepperLine {
    background-color: #cbd5e1;
    margin: 0 4px;
}

/* ===== 日志区（等宽 + 浅终端感）===== */
QTextEdit#logArea {
    background-color: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    color: #1f2937;
    font-family: 'Consolas', 'Cascadia Code', 'Courier New', monospace;
    font-size: 12px;
    padding: 6px;
}

/* ===== 复选框 ===== */
QCheckBox {
    color: #374151;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1.5px solid #94a3b8;
    border-radius: 3px;
    background-color: #ffffff;
}
QCheckBox::indicator:hover {
    border: 1.5px solid #0ea5e9;
    background-color: #f0f9ff;
}
QCheckBox::indicator:checked {
    background-color: #0ea5e9;
    border: 1.5px solid #0284c7;
    image: url('__CHECK_SVG__/check.svg');
}
QCheckBox::indicator:checked:hover {
    background-color: #0284c7;
    border: 1.5px solid #0369a1;
}
QCheckBox::indicator:disabled {
    background-color: #e5e7eb;
    border-color: #cbd5e1;
}

/* ===== 提示/状态标签 ===== */
QLabel#hintLabel {
    color: #6b7280;
    font-size: 11px;
}
QLabel#statusLabel {
    color: #6b7280;
    font-size: 12px;
}

/* ===== 底部执行栏（常驻，与滚动区分隔）===== */
QWidget#execBar {
    background-color: #ffffff;
    border-top: 1px solid #e5e7eb;
}

/* ===== 滚动条 ===== */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #cbd5e1;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #94a3b8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
"""


class MainWindow(QMainWindow):
    """工具集壳：左侧深钢蓝导航 + 右侧白底内容区。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'气动组工具箱 {APP_VERSION}')
        # 屏幕自适应：窗口不超过屏幕可用区域，保证底部执行栏始终可见
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(
            min(1280, screen.width() - 20),
            min(720, screen.height() - 80),  # 给标题栏 + 边距留足空间，避免 DPI 缩放下窗口底部被截断
        )

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧导航容器（深钢蓝）
        nav_widget = QWidget()
        nav_widget.setObjectName('navContainer')
        nav_widget.setFixedWidth(172)
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        # 顶部品牌 banner（signature：中英对照，工程仪表盘语汇）
        brand_title = QLabel('气动组工具箱')
        brand_title.setObjectName('brandTitle')
        brand_subtitle = QLabel('AERO TOOLKIT')
        brand_subtitle.setObjectName('brandSubtitle')

        # 导航列表
        self.nav_list = QListWidget()
        self.nav_list.setObjectName('navList')
        # 字体美化：Microsoft YaHei + 字距加宽（呼应顶部 banner 工程仪表盘风）
        nav_font = QFont('Microsoft YaHei', 11)
        nav_font.setBold(True)
        self.nav_list.setFont(nav_font)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)

        # 底部「⚙ 设置」按钮：弹出路径设置对话框
        self.settings_btn = QPushButton('⚙  设置')
        self.settings_btn.setObjectName('navSettingsBtn')
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._on_settings_clicked)

        # 底部版本号
        self.version_label = QLabel(f'版本 {APP_VERSION}')
        self.version_label.setObjectName('versionLabel')

        nav_layout.addWidget(brand_title)
        nav_layout.addWidget(brand_subtitle)
        nav_layout.addWidget(self.nav_list, 1)
        nav_layout.addWidget(self.settings_btn, 0)
        nav_layout.addWidget(self.version_label, 0)

        # 右侧内容区（浅灰底，留边距让白卡片呼吸）
        content_wrap = QWidget()
        content_wrap.setObjectName('contentWrap')
        content_layout = QHBoxLayout(content_wrap)
        content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_stack = QStackedWidget()
        content_layout.addWidget(self.content_stack)

        # 按 TOOLS 顺序实例化每个面板
        for name, panel_cls in TOOLS:
            panel = panel_cls()
            self.nav_list.addItem(name)
            self.content_stack.addWidget(panel)

        layout.addWidget(nav_widget)
        layout.addWidget(content_wrap, 1)
        self.setCentralWidget(central)

        if self.nav_list.count() > 0:
            self.nav_list.setCurrentRow(0)

        self._build_menu()

        # 缓存导航栏原始名字（剥离运行状态前缀用），监听模块运行状态变化
        self._nav_original_names = [name for name, _ in TOOLS]
        activity_hub.running_changed.connect(self._on_module_running)

    def _on_module_running(self, module_id, running):
        """模块运行状态变化 → 在左侧 nav_list 加视觉提示。

        running=True：行文字加 ● 前缀 + 半透明气流青背景
        running=False：恢复（注意 selected 状态由 QSS 接管，setForeground/Background 只在
        未选中时显现；运行中的模块在它自己的 tab 上时看到 selected 高亮，切到其他 tab
        才能看到背景色提示）。
        """
        # 找到 module_id 对应的 nav 索引
        nav_idx = None
        for i, (_, panel_cls) in enumerate(TOOLS):
            if getattr(panel_cls, 'MODULE_ID', None) == module_id:
                nav_idx = i
                break
        if nav_idx is None:
            return
        item = self.nav_list.item(nav_idx)
        if item is None:
            return
        name = self._nav_original_names[nav_idx]
        if running:
            item.setText(f'●  {name}')
            # 半透明气流青背景（rgba，~31% alpha），与 QSS ::item:selected 选中色区分
            item.setBackground(QBrush(QColor(14, 165, 233, 80)))
        else:
            item.setText(name)
            # 恢复透明（QSS ::item 默认色 #1e3a5f 由导航容器提供）
            item.setBackground(QBrush(QColor(0, 0, 0, 0)))

    def showEvent(self, event):
        """首次显示时绑定 screenChanged —— windowHandle() 在 show 之前为 None，
        必须在这里才能拿到 QWindow 接收 screenChanged 信号。"""
        super().showEvent(event)
        wh = self.windowHandle()
        if wh is not None and not getattr(self, '_screen_chg_bound', False):
            wh.screenChanged.connect(self._on_screen_changed)
            self._screen_chg_bound = True

    def _on_screen_changed(self, new_screen):
        """跨屏拖动后：把窗口 clamp 到新屏的可用工作区。

        原问题：从 2560×1600 拖到 1920×1080，窗口尺寸不更新，导致底部/侧边溢出屏幕。
        本槽：min(当前尺寸, 新屏可用区-边距)，并把窗口左上角挪进新屏内。"""
        if new_screen is None:
            return
        avail = new_screen.availableGeometry()
        margin = 20  # 屏幕边缘留 20px 缝隙，避免贴边看不见
        new_w = min(self.width(), avail.width() - margin)
        new_h = min(self.height(), avail.height() - margin)
        # 当前左上角若已在新屏可用区外，挪到屏内
        new_x = max(avail.left(), min(self.x(), avail.right() - new_w))
        new_y = max(avail.top(), min(self.y(), avail.bottom() - new_h))
        self.setGeometry(new_x, new_y, new_w, new_h)

    def _build_menu(self):
        """构建顶部菜单栏。当前只有「帮助」菜单，列出每个模块的帮助 + 关于。"""
        mb = self.menuBar()
        help_menu = mb.addMenu('帮助(&H)')

        # 每个模块一条帮助项，key 取 panel_cls.MODULE_ID
        # CATIA(3D 造型) 模块额外带「分步说明」二级子菜单
        for display_name, panel_cls in TOOLS:
            module_id = getattr(panel_cls, 'MODULE_ID', None)
            if not module_id:
                continue
            if module_id == 'catia_modeling':
                # 顶层「3D 造型 帮助」(打开总览) + 二级「分步说明」子菜单
                top_menu = help_menu.addMenu(f'{display_name} 帮助')
                act_overview = top_menu.addAction('模块总览')
                act_overview.triggered.connect(
                    lambda _=False, mid=module_id, dn=display_name:
                        self._show_help(mid, f'{dn} — 帮助')
                )
                top_menu.addSeparator()
                stages_menu = top_menu.addMenu('分步说明')
                for stage_key, stage_title in (
                    ('catia_modeling_stage1', '步骤① 构建截面'),
                    ('catia_modeling_stage2', '步骤② 重采样光顺'),
                    ('catia_modeling_stage3', '步骤③ 生成曲面'),
                ):
                    act_stage = stages_menu.addAction(stage_title)
                    act_stage.triggered.connect(
                        lambda _=False, k=stage_key, t=stage_title:
                            self._show_help(k, f'3D 造型 · {t} — 说明')
                    )
            else:
                act = help_menu.addAction(f'{display_name} 帮助')
                act.triggered.connect(
                    lambda _=False, mid=module_id, dn=display_name:
                        self._show_help(mid, f'{dn} — 帮助')
                )

        help_menu.addSeparator()

        # 风场失效分析 SOP（独立于具体模块的流程文档）
        act_sop = help_menu.addAction('风场失效分析 SOP')
        act_sop.triggered.connect(
            lambda: self._show_help('failure_analysis_sop', '风场失效分析 SOP — 帮助')
        )

        act_about = help_menu.addAction('关于工具箱')
        act_about.triggered.connect(
            lambda: self._show_help('about', '关于 — 气动组工具箱')
        )

    def _show_help(self, key, title):
        """弹出 Markdown 帮助对话框（模态）。"""
        dlg = HelpDialog(key, title=title, parent=self)
        dlg.exec_()

    def _on_nav_changed(self, row):
        if 0 <= row < self.content_stack.count():
            self.content_stack.setCurrentIndex(row)

    def _on_settings_clicked(self):
        """打开路径设置对话框。保存后 ConfigCenter 会广播 paths_changed，
        各面板自行的 _on_paths_changed slot 会刷新显示并重新扫描。"""
        dlg = SettingsDialog(self)
        dlg.exec_()


def main():
    # 高 DPI 支持：必须在 QApplication 实例化之前设置。
    # 启用后 QSS 里的 13px / 15px 等会被视为「逻辑像素」(DIP)，
    # Qt 按系统 DPI 缩放因子（100% / 125% / 150% / 200%）自动放大字号与布局，
    # 解决跨显示器（主屏 4K+150%、副屏 1080p+100%）字体大小不一致的问题。
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # DPI 因子取整策略：PassThrough 保留小数（如 1.25/1.5），最精确
    # （PyQt5 5.14+ 才有此 API，低版本会被忽略）
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass

    app = QApplication(sys.argv)

    # 应用图标：窗口标题栏 + 任务栏。
    # Windows 任务栏对 PNG 图标支持不完整（标题栏能显示但任务栏常回退到 Python 默认图标），
    # 必须提供多尺寸 .ico（16/24/32/48/64/128/256）让 Windows 按场景挑合适尺寸。
    # QIcon 直接加载 .ico 时 Qt 会自动按目标尺寸挑最合适的 layer。
    src_dir = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(src_dir, '_assets', 'icon.ico')
    png_path = os.path.join(src_dir, '_assets', 'icon.png')
    icon_path = ico_path if os.path.exists(ico_path) else png_path
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        app.setWindowIcon(QIcon())

    # 启动 splash：显示图标 + 等待字体加载/迁移完成。
    # splash 用 PNG 原图缩放到一半（约 627×627）—— 清晰度足够，又不会占满屏幕
    splash = None
    if os.path.exists(png_path):
        splash_pix = QPixmap(png_path).scaled(
            627, 627, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        splash = QSplashScreen(splash_pix)
        splash.show()
        app.processEvents()   # 让 splash 立即渲染出来，否则白屏

    # 显式加载标题/导航字体。Qt 默认字体扫描在 offscreen/打包环境下可能漏掉用户目录装的字体，
    # addApplicationFont 保证 family 一定能找到；找不到则 fallback 到默认中文字体。
    for fp in [r'C:\Windows\Fonts\YouSheBiaoTiHei-2 1.ttf',   # 优设标题黑（标题）
               r'C:\Windows\Fonts\msyhbd.ttc']:                # 微软雅黑 Bold（导航）
        if os.path.exists(fp):
            QFontDatabase.addApplicationFont(fp)

    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_assets')
    assets_dir = assets_dir.replace('\\', '/')   # QSS url 用正斜杠
    # check.svg 已并入 _assets/，__CHECK_SVG__ 与 {assets_dir} 共用同一目录
    style = APP_STYLE.replace('{assets_dir}', assets_dir).replace('__CHECK_SVG__', assets_dir)
    app.setStyleSheet(style)

    # 首启迁移：把旧散落在 输入数据/ 顶层的文件移到 输入数据/{module}/ 子目录
    # 必须在 MainWindow 实例化前跑（panel 构造时会 register_module 写 .paths.json）
    modules = [(cls.MODULE_ID, cls.DEFAULT_INPUT_SUBDIR, cls.DEFAULT_OUTPUT_SUBDIR)
               for _, cls in TOOLS]
    migrate_legacy_paths(modules)
    # 跨模块 extras 迁移：v0.3.0 把 modules_path 从 blade_converter 迁到 focus6_solver
    # 仅当目标模块 extras 为空且源有值时复制（一次性，不删源）
    migrate_extras_between_modules('blade_converter', 'focus6_solver', 'modules_path')

    win = MainWindow()
    win.show()

    # 等主窗口显示完毕再关 splash，避免中间露出空白
    if splash is not None:
        splash.finish(win)

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
