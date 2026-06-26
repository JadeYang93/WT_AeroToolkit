# -*- coding: utf-8 -*-
"""叶片结构套件面板（QWidget 子类）。

3 个 Tab 流水线（沿用 shape_design_panel 的隐藏 tabBar + stepper 模式）：
  - TAB-1：blade_db.xlsx + .mac → focus2blade.xlsx（WISDEM 插值）
  - TAB-2：focus2blade.xlsx → 更新 .prj（字段映射）
  - TAB-3：blade_geometry.mac ↔ blade_data.xlsx 双向转换

FOCUS6（farob/frbex/应变/叶尖挠度/一键运行）已迁移到独立的
`focus6_solver` 模块（参见 tools/focus6_solver_panel.py）。
输入/输出路径走 ConfigCenter。
"""
import os
import sys
import traceback
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QCheckBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox,
    QLineEdit, QTabWidget, QRadioButton, QButtonGroup,
    QScrollArea, QFrame, QSizePolicy, QComboBox,
)

from global_config import config_center

from business.blade_converter.bc_config import (
    DEFAULT_BLADE_DB_FILE, DEFAULT_OUTPUT_FILE, DEFAULT_MAC_FILE,
    DEFAULT_TXT_INPUT_FILE,
    DEFAULT_EXCEL_INPUT_FILE,
    SOLVER_FAROB, SOLVER_FRBEX,
)
from business.blade_converter.conversion import blade_db_to_focus2blade_wisdem
from business.blade_converter.prj_processor import PRJFileProcessor
from business.blade_converter.txt_excel import (
    convert_txt_to_excel, convert_excel_to_txt,
)


# ============================================================
# Worker 线程
# ============================================================

class ConverterTab1Worker(QThread):
    """TAB-1：blade_db.xlsx + .mac → focus2blade.xlsx。"""
    progress = pyqtSignal(int, str)

    def __init__(self, blade_db_path, output_path, mac_path, solver_type):
        super().__init__()
        self.blade_db_path = blade_db_path
        self.output_path = output_path
        self.mac_path = mac_path
        self.solver_type = solver_type
        self.result = None

    def run(self):
        try:
            self._log(5, f'读取 blade_db: {self.blade_db_path}')
            self._log(10, f'读取 mac（提供变桨中心）: {self.mac_path}')
            self._log(30, 'WISDEM 插值计算中...')
            ok = blade_db_to_focus2blade_wisdem(
                self.blade_db_path, self.output_path, self.mac_path,
            )
            if not ok:
                raise RuntimeError('blade_db_to_focus2blade_wisdem 返回 False')
            # solver_type 后缀（farob/frbex），与原项目一致
            final_path = Path(self.output_path)
            if self.solver_type:
                final_path = final_path.with_name(
                    f'{final_path.stem}_{self.solver_type}{final_path.suffix}'
                )
                if final_path != Path(self.output_path) and Path(self.output_path).exists():
                    Path(self.output_path).rename(final_path)
            self._log(100, '=== TAB-1 完成 ===')
            self._log(100, f'输出: {final_path}')
            self.result = {'output': str(final_path)}
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    def _log(self, p, m):
        self.progress.emit(p, m)


class ConverterTab2Worker(QThread):
    """TAB-2：focus2blade.xlsx → 更新 .prj。"""
    progress = pyqtSignal(int, str)

    def __init__(self, prj_file, focus2blade_file, output_prj_file, backup_prj=True):
        super().__init__()
        self.prj_file = prj_file
        self.focus2blade_file = focus2blade_file
        self.output_prj_file = output_prj_file
        self.backup_prj = backup_prj
        self.result = None

    def run(self):
        import pandas as pd
        import shutil
        try:
            self._log(10, f'读取 PRJ: {self.prj_file}')
            prj_content = PRJFileProcessor.read_prj_file(self.prj_file)
            self._log(30, f'读取 focus2blade: {self.focus2blade_file}')
            df_focus2blade = pd.read_excel(self.focus2blade_file)

            # NaN 校验
            nan_cols = [c for c in df_focus2blade.columns
                        if df_focus2blade[c].isna().any()]
            if nan_cols:
                raise ValueError(
                    f'focus2blade.xlsx 含 NaN，无法更新 PRJ。问题列: {nan_cols}'
                )

            self._log(60, '字段映射更新中...')
            updated = PRJFileProcessor.update_prj_file(prj_content, df_focus2blade)

            Path(self.output_prj_file).parent.mkdir(parents=True, exist_ok=True)
            if self.backup_prj:
                src = Path(self.prj_file)
                if src.exists():
                    backup = src.with_suffix('.prj.backup')
                    shutil.copy2(src, backup)
                    self._log(75, f'已备份: {backup.name}')

            with open(self.output_prj_file, 'w', encoding='utf-8') as f:
                f.write(updated)
            self._log(100, '=== TAB-2 完成 ===')
            self._log(100, f'输出: {self.output_prj_file}')
            self.result = {'output': self.output_prj_file}
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    def _log(self, p, m):
        self.progress.emit(p, m)


class ConverterTab3Worker(QThread):
    """TAB-3：blade_geometry.mac ↔ blade_data.xlsx 双向转换。"""
    progress = pyqtSignal(int, str)

    def __init__(self, direction, input_file, output_file):
        super().__init__()
        self.direction = direction  # 'txt_to_excel' or 'excel_to_txt'
        self.input_file = input_file
        self.output_file = output_file
        self.result = None

    def run(self):
        try:
            logger = lambda m: self._log(50, m)
            if self.direction == 'txt_to_excel':
                self._log(10, '方向: mac → xlsx')
                ok = convert_txt_to_excel(
                    self.input_file, self.output_file, logger=logger,
                )
            else:
                self._log(10, '方向: xlsx → mac')
                ok = convert_excel_to_txt(
                    self.input_file, self.output_file, logger=logger,
                )
            if not ok:
                raise RuntimeError('转换失败（见日志）')
            self._log(100, '=== TAB-3 完成 ===')
            self._log(100, f'输出: {self.output_file}')
            self.result = {'output': self.output_file}
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    def _log(self, p, m):
        self.progress.emit(p, m)


# ============================================================
# CompactScrollArea（与 shape_design_panel 同实现）
# ============================================================

class CompactScrollArea(QScrollArea):
    """QScrollArea 子类：重写 minimumSizeHint，让其在 layout 中能压缩到任意高度。"""

    def sizeHint(self):
        return QSize(0, 0)

    def minimumSizeHint(self):
        return QSize(0, 0)


# ============================================================
# 主面板
# ============================================================

class BladeConverterPanel(QWidget):
    MODULE_ID = 'blade_converter'
    DEFAULT_INPUT_SUBDIR = 'blade_converter'
    DEFAULT_OUTPUT_SUBDIR = 'blade_converter'

    _TAB_STEPS = (
        # (tab_key, tab_index, 编号, 简称, 全称)
        # 三个功能相互独立，编号字段保留给数据键使用，UI 上不再显示
        ('tab1', 0, '', 'blade_db 转换', 'TAB-1'),
        ('tab2', 1, '', 'PRJ 更新',     'TAB-2'),
        ('tab3', 2, '', 'xlsx ↔ mac',  'TAB-3'),
    )

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

        # 流水线状态（用于 stepper 反馈）
        self._stage_states = {k: 'pending' for k, *_ in self._TAB_STEPS}

        self._build_ui()
        self.setMinimumHeight(0)
        self.setMinimumSize(0, 0)

    # ---------- 路径变更 ----------
    def _on_paths_changed(self, module_id):
        if module_id and module_id != self.MODULE_ID:
            return
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        if hasattr(self, 'tabs'):
            self._sync_path_edits()

    def _sync_path_edits(self):
        """路径变更后把默认子目录同步到 UI（仅当编辑框为空或仍是旧 default 时）。"""
        defaults = self._default_paths()
        # TAB-1
        if hasattr(self, 'tab1_blade_db_edit'):
            for edit, key in [
                (self.tab1_blade_db_edit, 'tab1_blade_db'),
                (self.tab1_mac_edit, 'tab1_mac'),
                (self.tab1_output_edit, 'tab1_output'),
            ]:
                cur = edit.text().strip()
                if not cur:
                    edit.setText(defaults[key])
        # TAB-2
        if hasattr(self, 'tab2_prj_edit'):
            for edit, key in [
                (self.tab2_prj_edit, 'tab2_prj'),
                (self.tab2_focus2blade_edit, 'tab2_focus2blade'),
                (self.tab2_output_edit, 'tab2_output'),
            ]:
                cur = edit.text().strip()
                if not cur:
                    edit.setText(defaults[key])
        # TAB-3
        if hasattr(self, 'tab3_input_edit'):
            for edit, key in [
                (self.tab3_input_edit, 'tab3_input'),
                (self.tab3_output_edit, 'tab3_output'),
            ]:
                cur = edit.text().strip()
                if not cur:
                    edit.setText(defaults[key])

    def _default_paths(self):
        in_dir = Path(self.input_dir)
        out_dir = Path(self.out_dir)
        return {
            # TAB-1
            'tab1_blade_db': str(in_dir / DEFAULT_BLADE_DB_FILE),
            'tab1_mac': str(in_dir / DEFAULT_MAC_FILE),
            'tab1_output': str(out_dir / 'focus2blade' / DEFAULT_OUTPUT_FILE),
            # TAB-2
            'tab2_prj': str(in_dir / 'blade.prj'),
            'tab2_focus2blade': str(out_dir / 'focus2blade' / DEFAULT_OUTPUT_FILE),
            'tab2_output': str(out_dir / 'prj_update' / 'blade_updated.prj'),
            # TAB-3：默认 mac → Excel，输出 = 输入 stem + _trans + 目标扩展名
            'tab3_input': str(in_dir / DEFAULT_TXT_INPUT_FILE),
            'tab3_output': str(out_dir / 'txt_excel' / f'{Path(DEFAULT_TXT_INPUT_FILE).stem}_trans.xlsx'),
        }

    # ---------- UI 构建 ----------
    def _build_ui(self):
        defaults = self._default_paths()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # === 顶部 banner ===
        banner = QWidget()
        banner.setObjectName('moduleBanner')
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(4)
        title = QLabel('叶片结构套件')
        title.setObjectName('moduleTitle')
        title.setAlignment(Qt.AlignCenter)
        tf = QFont('YouSheBiaoTiHei', 16)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        title.setFont(tf)
        sub = QLabel('B L A D E   S T R U C T U R E   C O N V E R T E R')
        sub.setObjectName('moduleSubtitle')
        sub.setAlignment(Qt.AlignCenter)
        sf = QFont('Consolas', 8)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        sf.setBold(True)
        sub.setFont(sf)
        bl.addWidget(title)
        bl.addWidget(sub)
        outer.addWidget(banner)

        # === 流水线 stepper ===
        outer.addWidget(self._build_stepper())

        # === 选项卡 ===
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tab1(defaults), '  TAB-1 - blade_db 转换  ')
        self.tabs.addTab(self._build_tab2(defaults), '  TAB-2 - PRJ 更新  ')
        self.tabs.addTab(self._build_tab3(defaults), '  TAB-3 - xlsx ↔ mac  ')
        self.tabs.tabBar().setVisible(False)
        self.tabs.setStyleSheet('QTabWidget::pane { border: none; }')
        self.tabs.currentChanged.connect(lambda _idx: self._update_stepper_state())
        outer.addWidget(self.tabs, 1)
        self._update_stepper_state()

    # ----- 流水线 Stepper -----
    def _build_stepper(self):
        wrap = QWidget()
        wrap.setObjectName('stepperBar')
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap.setFixedHeight(64)

        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(0)

        self._stepper_nodes = {}
        self._stepper_lines = []
        for i, (key, idx, num, label, full) in enumerate(self._TAB_STEPS):
            # 三个功能平级：按钮文字只显示功能简称，不带 1/2/3 编号
            node_text = f'  {label}' if not num else f'  {num}  {label}'
            node = QPushButton(node_text)
            node.setObjectName('stepperNode')
            node.setCursor(Qt.PointingHandCursor)
            node.setToolTip(f'{full} — 点击切到该功能')
            node.setProperty('stageKey', key)
            node.clicked.connect(self._on_stepper_click)
            layout.addWidget(node, 1)
            self._stepper_nodes[key] = node

            if i < len(self._TAB_STEPS) - 1:
                line = QFrame()
                line.setObjectName('stepperLine')
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                layout.addWidget(line, 1)
                self._stepper_lines.append(line)

        return wrap

    def _on_stepper_click(self):
        sender = self.sender()
        key = sender.property('stageKey')
        if key is None:
            return
        for tab_key, idx, *_ in self._TAB_STEPS:
            if tab_key == key:
                self.tabs.setCurrentIndex(idx)
                return

    def _update_stepper_state(self):
        if not hasattr(self, '_stepper_nodes'):
            return
        current_idx = self.tabs.currentIndex()
        current_key = self._TAB_STEPS[current_idx][0]
        for key, *_ in self._TAB_STEPS:
            node = self._stepper_nodes.get(key)
            if node is None:
                continue
            node.setProperty('current', 'true' if key == current_key else None)
            node.style().unpolish(node)
            node.style().polish(node)

    def _mark_stage_completed(self, key):
        self._stage_states[key] = 'completed'
        self._update_stepper_state()

    # ----- TAB-1: blade_db 转换 -----
    def _build_tab1(self, defaults):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        box = QGroupBox('输入/输出')
        box.setObjectName('gb_data')
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        grid.addWidget(QLabel('blade_db 文件:'), 0, 0)
        self.tab1_blade_db_edit = QLineEdit(defaults['tab1_blade_db'])
        grid.addWidget(self.tab1_blade_db_edit, 0, 1)
        grid.addWidget(self._browse_btn(self.tab1_blade_db_edit, 'file'), 0, 2)

        grid.addWidget(QLabel('mac 文件（变桨中心）:'), 1, 0)
        self.tab1_mac_edit = QLineEdit(defaults['tab1_mac'])
        grid.addWidget(self.tab1_mac_edit, 1, 1)
        grid.addWidget(self._browse_btn(self.tab1_mac_edit, 'file'), 1, 2)

        grid.addWidget(QLabel('输出 focus2blade:'), 2, 0)
        self.tab1_output_edit = QLineEdit(defaults['tab1_output'])
        grid.addWidget(self.tab1_output_edit, 2, 1)
        grid.addWidget(self._browse_btn(self.tab1_output_edit, 'file'), 2, 2)

        grid.addWidget(QLabel('求解器类型:'), 3, 0)
        self.tab1_solver_combo = QComboBox()
        self.tab1_solver_combo.addItem('farob', SOLVER_FAROB)
        self.tab1_solver_combo.addItem('frbex', SOLVER_FRBEX)
        self.tab1_solver_combo.setCurrentIndex(1)  # 默认 frbex
        self.tab1_solver_combo.setToolTip('影响输出文件名后缀（_farob / _frbex）')
        grid.addWidget(self.tab1_solver_combo, 3, 1)

        grid.setColumnStretch(1, 1)
        v.addWidget(box)

        info = QGroupBox('说明')
        info_layout = QVBoxLayout(info)
        info_label = QLabel(
            '• 输入：blade_db.xlsx（叶片截面属性数据库）+ .mac（提供变桨中心位置）\n'
            '• 输出：focus2blade.xlsx（FOCUS6 标准格式）\n'
            '• 算法：参考 WISDEM 的截面属性插值（线性 + 主惯性矩分解）\n'
            '• 求解器类型只影响输出文件名后缀，不影响计算内容'
        )
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label)
        v.addWidget(info)

        v.addStretch()
        v.addWidget(self._build_exec_bar(
            stage='tab1',
            run_text='运行 TAB-1',
            run_slot=self._on_run_tab1,
            open_dir_getter=lambda: Path(self.tab1_output_edit.text()).parent,
        ))
        return page

    # ----- TAB-2: PRJ 更新 -----
    def _build_tab2(self, defaults):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        box = QGroupBox('输入/输出')
        box.setObjectName('gb_data')
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        grid.addWidget(QLabel('PRJ 文件:'), 0, 0)
        self.tab2_prj_edit = QLineEdit(defaults['tab2_prj'])
        grid.addWidget(self.tab2_prj_edit, 0, 1)
        grid.addWidget(self._browse_btn(self.tab2_prj_edit, 'file'), 0, 2)

        grid.addWidget(QLabel('focus2blade.xlsx:'), 1, 0)
        self.tab2_focus2blade_edit = QLineEdit(defaults['tab2_focus2blade'])
        grid.addWidget(self.tab2_focus2blade_edit, 1, 1)
        grid.addWidget(self._browse_btn(self.tab2_focus2blade_edit, 'file'), 1, 2)

        grid.addWidget(QLabel('输出 PRJ:'), 2, 0)
        self.tab2_output_edit = QLineEdit(defaults['tab2_output'])
        grid.addWidget(self.tab2_output_edit, 2, 1)
        grid.addWidget(self._browse_btn(self.tab2_output_edit, 'file'), 2, 2)

        self.tab2_backup_cb = QCheckBox('运行前备份原 PRJ（.prj.backup）')
        self.tab2_backup_cb.setChecked(True)
        grid.addWidget(self.tab2_backup_cb, 3, 0, 1, 3)

        grid.setColumnStretch(1, 1)
        v.addWidget(box)

        info = QGroupBox('说明')
        info_layout = QVBoxLayout(info)
        info_label = QLabel(
            '• 把 focus2blade.xlsx 的 17 个字段（弹性轴、质心、刚度等）写入 .prj\n'
            '• 字段映射：REF_X / CE_X / MASS / EIFLAP / GJ / EA / CS_X 等\n'
            '• DIST 截面位置不一致会警告（0.001 m 容差），但不会终止更新\n'
            '• 输出文件可以与源文件相同（原地更新）；也可指定新路径避免污染原文件'
        )
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label)
        v.addWidget(info)

        v.addStretch()
        v.addWidget(self._build_exec_bar(
            stage='tab2',
            run_text='运行 TAB-2',
            run_slot=self._on_run_tab2,
            open_dir_getter=lambda: Path(self.tab2_output_edit.text()).parent,
        ))
        return page

    # ----- TAB-3: Excel ↔ txt -----
    def _build_tab3(self, defaults):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        box = QGroupBox('输入/输出')
        box.setObjectName('gb_data')
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        grid.addWidget(QLabel('转换方向:'), 0, 0)
        self.tab3_dir_group = QButtonGroup(self)
        self.tab3_rb_txt_to_xlsx = QRadioButton('mac → xlsx')
        self.tab3_rb_xlsx_to_txt = QRadioButton('xlsx → mac')
        self.tab3_rb_txt_to_xlsx.setChecked(True)
        self.tab3_dir_group.addButton(self.tab3_rb_txt_to_xlsx, 0)
        self.tab3_dir_group.addButton(self.tab3_rb_xlsx_to_txt, 1)
        dir_wrap = QWidget()
        dir_layout = QHBoxLayout(dir_wrap)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(12)
        dir_layout.addWidget(self.tab3_rb_txt_to_xlsx)
        dir_layout.addWidget(self.tab3_rb_xlsx_to_txt)
        dir_layout.addStretch()
        grid.addWidget(dir_wrap, 0, 1, 1, 2)
        # 切换方向时同步默认文件名（两个 RadioButton 都要连，
        # 因为 checked 变化的按钮才会触发 toggled(True)，另一个触发 toggled(False)）
        self.tab3_rb_txt_to_xlsx.toggled.connect(self._on_tab3_direction_change)
        self.tab3_rb_xlsx_to_txt.toggled.connect(self._on_tab3_direction_change)

        grid.addWidget(QLabel('输入文件:'), 1, 0)
        self.tab3_input_edit = QLineEdit(defaults['tab3_input'])
        # 输入改变时自动同步输出文件（stem + 扩展名按方向切换）
        self.tab3_input_edit.textChanged.connect(self._on_tab3_input_change)
        grid.addWidget(self.tab3_input_edit, 1, 1)
        grid.addWidget(self._browse_btn(self.tab3_input_edit, 'file'), 1, 2)

        grid.addWidget(QLabel('输出文件:'), 2, 0)
        self.tab3_output_edit = QLineEdit(defaults['tab3_output'])
        grid.addWidget(self.tab3_output_edit, 2, 1)
        grid.addWidget(self._browse_btn(self.tab3_output_edit, 'file'), 2, 2)

        grid.setColumnStretch(1, 1)
        v.addWidget(box)

        info = QGroupBox('说明')
        info_layout = QVBoxLayout(info)
        self.tab3_info_label = QLabel()
        self.tab3_info_label.setWordWrap(True)
        info_layout.addWidget(self.tab3_info_label)
        v.addWidget(info)
        self._update_tab3_info_text()

        v.addStretch()
        v.addWidget(self._build_exec_bar(
            stage='tab3',
            run_text='运行 TAB-3',
            run_slot=self._on_run_tab3,
            open_dir_getter=lambda: Path(self.tab3_output_edit.text()).parent,
        ))
        return page

    def _on_tab3_direction_change(self, checked):
        if not checked:
            return
        # 方向切换：若输入为空则回填默认，然后强制同步输出扩展名
        in_dir = Path(self.input_dir)
        if self.tab3_rb_txt_to_xlsx.isChecked():
            default_in_name = DEFAULT_TXT_INPUT_FILE
        else:
            default_in_name = DEFAULT_EXCEL_INPUT_FILE
        if not self.tab3_input_edit.text().strip():
            self.tab3_input_edit.setText(str(in_dir / default_in_name))
        # 强制同步输出（方向变了，扩展名必须跟着变，不保留旧扩展名）
        self._sync_tab3_output(force=True)
        self._update_tab3_info_text()

    def _on_tab3_input_change(self, _text: str):
        """输入文件改变（用户输入或浏览选择）→ 同步输出 stem + 扩展名。"""
        self._sync_tab3_output(force=False)

    def _sync_tab3_output(self, force: bool):
        """根据当前输入与方向，刷新输出文件路径。

        - force=False（输入变化）：保留输出目录与「_trans」约定，更新 stem + 扩展名
        - force=True（方向切换）：扩展名必须切到目标格式，即使用户改过也覆盖
        """
        in_text = self.tab3_input_edit.text().strip()
        if not in_text:
            return
        in_path = Path(in_text)
        if not in_path.stem:
            return
        if self.tab3_rb_txt_to_xlsx.isChecked():
            target_ext = '.xlsx'
        else:
            target_ext = '.mac'
        # 输出目录：保留当前输出字段的父目录；首次落到 txt_excel/
        cur_out = self.tab3_output_edit.text().strip()
        if cur_out:
            out_dir = Path(cur_out).parent
        else:
            out_dir = Path(self.out_dir) / 'txt_excel'
        new_out = out_dir / f'{in_path.stem}_trans{target_ext}'
        new_out_str = str(new_out)
        # force=True: 方向切换必须覆盖扩展名
        # force=False: 输入变化也覆盖（用户明确说「不要我手动修改」）
        if new_out_str != cur_out:
            self.tab3_output_edit.setText(new_out_str)

    def _update_tab3_info_text(self):
        if self.tab3_rb_txt_to_xlsx.isChecked():
            txt = (
                '• 方向：blade_geometry.mac → blade_data.xlsx\n'
                '• 解析 mac 中的 DEF PARA / DEF SHAPE / POINTS / PLACE SHAPE / DEF MATERIAL / DEF S-N LINE / DEF LINE / DEF SECTION\n'
                '• 输出 7 个 sheet：Parameters / shape_points / PlaceShapes / Materials / S_N Lines / Line / Sections'
            )
        else:
            txt = (
                '• 方向：blade_data.xlsx → blade_geometry.mac\n'
                '• 要求 xlsx 由 TAB-3 正向转换生成（PlaceShapes 必须含 CenterX / CenterY）\n'
                '• 输出与原 mac 等价的文本格式（缩进/对齐尽量保留）'
            )
        self.tab3_info_label.setText(txt)

    # ----- 通用：浏览按钮 -----
    def _browse_btn(self, target_edit, kind):
        btn = QPushButton('...')
        btn.setMaximumWidth(40)
        btn.clicked.connect(lambda: self._choose_path(target_edit, kind))
        return btn

    def _choose_path(self, target_edit, kind):
        current = target_edit.text()
        if kind == 'file':
            start_dir = str(Path(current).parent) if current else self.input_dir
            path, _ = QFileDialog.getOpenFileName(self, '选择文件', start_dir)
        else:
            start_dir = current or self.input_dir
            path = QFileDialog.getExistingDirectory(self, '选择目录', start_dir)
        if path:
            target_edit.setText(path)

    # ----- 通用：执行栏（复用 shape_design_panel 模式）-----
    def _build_exec_bar(self, stage, run_text, run_slot, open_dir_getter, extra_btns=None):
        wrap = QWidget()
        wrap.setObjectName('execBar')
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap.setFixedHeight(220)

        bar = QHBoxLayout(wrap)
        bar.setContentsMargins(2, 8, 2, 2)
        bar.setSpacing(10)

        # 左侧
        left_wrap = QWidget()
        left_wrap.setFixedWidth(320)
        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        run_btn = QPushButton(run_text)
        run_btn.setMinimumHeight(40)
        run_btn.setObjectName('primaryBtn')
        run_btn.setCursor(Qt.PointingHandCursor)
        run_btn.clicked.connect(run_slot)
        open_btn = QPushButton('📂  打开目录')
        open_btn.setObjectName('secondaryBtn')
        open_btn.setMinimumHeight(36)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setEnabled(False)
        open_btn.clicked.connect(lambda: self._open_dir(open_dir_getter()))
        progress = QProgressBar()
        progress.setValue(0)
        progress.setTextVisible(True)
        left_layout.addWidget(run_btn)
        left_layout.addWidget(open_btn)
        for key, label, slot in (extra_btns or []):
            extra = QPushButton(label)
            extra.setMinimumHeight(36)
            extra.setEnabled(False)
            extra.clicked.connect(slot)
            left_layout.addWidget(extra)
            setattr(self, f'_extra_btn_{stage}_{key}', extra)
        left_layout.addWidget(progress)
        left_layout.addStretch()

        # 右侧日志
        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(QLabel('日志:'))
        log_area = QTextEdit()
        log_area.setReadOnly(True)
        log_area.setObjectName('logArea')
        right_layout.addWidget(log_area, 1)

        bar.addWidget(left_wrap, 0)
        bar.addWidget(right_wrap, 1)

        setattr(self, f'{stage}_run_btn', run_btn)
        setattr(self, f'{stage}_open_btn', open_btn)
        setattr(self, f'{stage}_progress', progress)
        setattr(self, f'{stage}_log', log_area)
        return wrap

    # ----- 通用：日志 -----
    def _log(self, stage, msg):
        log_area = getattr(self, f'{stage}_log')
        log_area.append(msg)
        log_area.verticalScrollBar().setValue(
            log_area.verticalScrollBar().maximum()
        )

    def _set_running(self, stage, running):
        run_btn = getattr(self, f'{stage}_run_btn')
        if running:
            if not hasattr(self, '_run_btn_text_cache'):
                self._run_btn_text_cache = {}
            self._run_btn_text_cache.setdefault(stage, run_btn.text())
            run_btn.setEnabled(False)
            run_btn.setText('运行中...')
        else:
            run_btn.setEnabled(True)
            cached = getattr(self, '_run_btn_text_cache', {}).get(stage)
            if cached:
                run_btn.setText(cached)

    def _open_dir(self, path):
        try:
            path = Path(path)
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform == 'win32':
                os.startfile(str(path))
            elif sys.platform == 'darwin':
                import subprocess as _sp
                _sp.run(['open', str(path)], check=False)
            else:
                import subprocess as _sp
                _sp.run(['xdg-open', str(path)], check=False)
        except Exception as exc:
            QMessageBox.warning(self, '打开失败', str(exc))

    # ============================================================
    # TAB-1 执行
    # ============================================================
    def _on_run_tab1(self):
        blade_db = self.tab1_blade_db_edit.text().strip()
        mac = self.tab1_mac_edit.text().strip()
        output = self.tab1_output_edit.text().strip()
        solver_type = self.tab1_solver_combo.currentData()

        if not blade_db or not Path(blade_db).exists():
            QMessageBox.warning(self, '缺少 blade_db', f'文件不存在：{blade_db}')
            return
        if not mac or not Path(mac).exists():
            QMessageBox.warning(self, '缺少 mac', f'文件不存在：{mac}')
            return
        if not output:
            QMessageBox.warning(self, '缺少输出路径', '请指定输出 focus2blade 路径')
            return

        self.tab1_log.clear()
        self.tab1_progress.setValue(0)
        self._set_running('tab1', True)
        self.tab1_open_btn.setEnabled(False)

        self._log('tab1', f'输入 blade_db: {blade_db}')
        self._log('tab1', f'输入 mac: {mac}')
        self._log('tab1', f'输出: {output}')
        self._log('tab1', f'求解器类型: {solver_type}')
        self._log('tab1', '---')

        self._tab1_worker = ConverterTab1Worker(blade_db, output, mac, solver_type)
        self._tab1_worker.progress.connect(self._on_tab1_progress)
        self._tab1_worker.finished.connect(self._on_tab1_finished)
        self._tab1_worker.start()

    def _on_tab1_progress(self, percent, msg):
        self.tab1_progress.setValue(percent)
        self._log('tab1', msg)

    def _on_tab1_finished(self):
        self._set_running('tab1', False)
        res = self._tab1_worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'TAB-1 出错', res['error'])
        else:
            self.tab1_open_btn.setEnabled(True)
            self._mark_stage_completed('tab1')

    # ============================================================
    # TAB-2 执行
    # ============================================================
    def _on_run_tab2(self):
        prj_file = self.tab2_prj_edit.text().strip()
        focus2blade = self.tab2_focus2blade_edit.text().strip()
        output = self.tab2_output_edit.text().strip()
        backup = self.tab2_backup_cb.isChecked()

        if not prj_file or not Path(prj_file).exists():
            QMessageBox.warning(self, '缺少 PRJ', f'文件不存在：{prj_file}')
            return
        if not focus2blade or not Path(focus2blade).exists():
            QMessageBox.warning(self, '缺少 focus2blade', f'文件不存在：{focus2blade}')
            return
        if not output:
            QMessageBox.warning(self, '缺少输出路径', '请指定输出 PRJ 路径')
            return

        self.tab2_log.clear()
        self.tab2_progress.setValue(0)
        self._set_running('tab2', True)
        self.tab2_open_btn.setEnabled(False)

        self._log('tab2', f'输入 PRJ: {prj_file}')
        self._log('tab2', f'输入 focus2blade: {focus2blade}')
        self._log('tab2', f'输出: {output}')
        self._log('tab2', f'备份: {"是" if backup else "否"}')
        self._log('tab2', '---')

        self._tab2_worker = ConverterTab2Worker(prj_file, focus2blade, output, backup)
        self._tab2_worker.progress.connect(self._on_tab2_progress)
        self._tab2_worker.finished.connect(self._on_tab2_finished)
        self._tab2_worker.start()

    def _on_tab2_progress(self, percent, msg):
        self.tab2_progress.setValue(percent)
        self._log('tab2', msg)

    def _on_tab2_finished(self):
        self._set_running('tab2', False)
        res = self._tab2_worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'TAB-2 出错', res['error'])
        else:
            self.tab2_open_btn.setEnabled(True)
            self._mark_stage_completed('tab2')

    # ============================================================
    # TAB-3 执行
    # ============================================================
    def _on_run_tab3(self):
        input_file = self.tab3_input_edit.text().strip()
        output_file = self.tab3_output_edit.text().strip()
        direction = 'txt_to_excel' if self.tab3_rb_txt_to_xlsx.isChecked() else 'excel_to_txt'

        if not input_file or not Path(input_file).exists():
            QMessageBox.warning(self, '缺少输入文件', f'文件不存在：{input_file}')
            return
        if not output_file:
            QMessageBox.warning(self, '缺少输出路径', '请指定输出文件路径')
            return

        self.tab3_log.clear()
        self.tab3_progress.setValue(0)
        self._set_running('tab3', True)
        self.tab3_open_btn.setEnabled(False)

        self._log('tab3', f'方向: {direction}')
        self._log('tab3', f'输入: {input_file}')
        self._log('tab3', f'输出: {output_file}')
        self._log('tab3', '---')

        self._tab3_worker = ConverterTab3Worker(direction, input_file, output_file)
        self._tab3_worker.progress.connect(self._on_tab3_progress)
        self._tab3_worker.finished.connect(self._on_tab3_finished)
        self._tab3_worker.start()

    def _on_tab3_progress(self, percent, msg):
        self.tab3_progress.setValue(percent)
        self._log('tab3', msg)

    def _on_tab3_finished(self):
        self._set_running('tab3', False)
        res = self._tab3_worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'TAB-3 出错', res['error'])
        else:
            self.tab3_open_btn.setEnabled(True)
            self._mark_stage_completed('tab3')
