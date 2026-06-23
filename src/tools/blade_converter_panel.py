# -*- coding: utf-8 -*-
"""叶片结构套件面板（QWidget 子类）。

4 个 Tab 流水线（沿用 shape_output_panel 的隐藏 tabBar + stepper 模式）：
  - TAB-1：blade_db.xlsx + .mac → focus2blade.xlsx（WISDEM 插值）
  - TAB-2：focus2blade.xlsx → 更新 .prj（字段映射）
  - TAB-3：blade_geometry.mac ↔ blade_data.xlsx 双向转换
  - TAB-4：FOCUS6 求解器（farob/frbex/应变/叶尖挠度/一键运行）

输入/输出路径走 ConfigCenter；FOCUS6 Modules 目录走 ConfigCenter extras（modules_path），
内含 farob/ frbex/ utils/ 等子目录，TAB-4 按所选求解器类型自动选用。
首次使用需先到「⚙ 设置」配置 Modules 目录，否则 TAB-4 会被禁用并提示。
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

from blade_converter.bc_config import (
    DEFAULT_BLADE_DB_FILE, DEFAULT_OUTPUT_FILE, DEFAULT_MAC_FILE,
    DEFAULT_TXT_INPUT_FILE,
    DEFAULT_EXCEL_INPUT_FILE,
    SOLVER_FAROB, SOLVER_FRBEX,
    FUNCTION_READ_MAC, FUNCTION_PARSE_MAC, FUNCTION_FREQUENCY,
    FUNCTION_TIP_DEFLECTION, FUNCTION_STRAIN, FUNCTION_WEIGHT,
    FUNCTION_LOAD_CONVERSION,
    FRBEX_DEFAULT_DRMX,
)
from blade_converter.conversion import blade_db_to_focus2blade_wisdem
from blade_converter.prj_processor import PRJFileProcessor
from blade_converter.txt_excel import (
    convert_txt_to_excel, convert_excel_to_txt,
)
from blade_converter.solver_focus6 import Focus6SolverThread
from blade_converter.solver_one_click import OneClickRunThread


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
                self._log(10, '方向: mac → Excel')
                ok = convert_txt_to_excel(
                    self.input_file, self.output_file, logger=logger,
                )
            else:
                self._log(10, '方向: Excel → mac')
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


class ConverterTab4Worker(QThread):
    """TAB-4：FOCUS6 求解器调用（支持一键运行）。

    内部直接复用原项目的 ``Focus6SolverThread`` / ``OneClickRunThread`` QThread 类，
    但由于 QThread 不能嵌套 start，这里改成在 run() 里直接调用其方法（同步执行）。
    """
    progress = pyqtSignal(int, str)

    def __init__(self, params, one_click=False):
        super().__init__()
        self.params = params
        self.one_click = one_click
        self.result = None

    def run(self):
        try:
            if self.one_click:
                self._log(10, '一键运行模式（并行 6 步）')
                runner = OneClickRunThread(self.params, summarize_only=False)
                # 把 OneClickRunThread 的信号转发到本 Worker 的信号
                runner.log_signal.connect(lambda m: self._log(50, m))
                runner.progress_signal.connect(
                    lambda cur, total: self._log(
                        10 + int(80 * cur / max(1, total)), f'步骤 {cur}/{total}'
                    )
                )
                # 直接在当前线程里跑（OneClickRunThread.run 是普通函数）
                runner.run()
            else:
                self._log(10, f"单求解器: {self.params.get('function')}")
                solver = Focus6SolverThread(self.params, skip_prepare=False, generate_csv=True)
                solver.log_signal.connect(lambda m: self._log(50, m))
                solver.progress_signal.connect(
                    lambda cur, total: self._log(
                        10 + int(80 * cur / max(1, total)), f'步骤 {cur}/{total}'
                    )
                )
                solver.run()
            self._log(100, '=== TAB-4 完成 ===')
            self.result = {'output': self.params.get('sum_folder', '')}
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    def _log(self, p, m):
        self.progress.emit(p, m)


# ============================================================
# CompactScrollArea（与 shape_output_panel 同实现）
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
    EXTRA_KEYS = ['modules_path']

    _TAB_STEPS = (
        # (tab_key, tab_index, 编号, 简称, 全称)
        ('tab1', 0, '1', 'blade_db 转换', 'TAB-1'),
        ('tab2', 1, '2', 'PRJ 更新',     'TAB-2'),
        ('tab3', 2, '3', 'Excel ↔ mac',  'TAB-3'),
        ('tab4', 3, '4', 'FOCUS6 求解器', 'TAB-4'),
    )

    def __init__(self):
        super().__init__()
        config_center.register_module(
            self.MODULE_ID,
            self.DEFAULT_INPUT_SUBDIR,
            self.DEFAULT_OUTPUT_SUBDIR,
            extra_keys=self.EXTRA_KEYS,
        )
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        self.solver_paths = {k: paths.get(k, '') for k in self.EXTRA_KEYS}

        # 触发老配置自动迁移（farob_exe → modules_path），
        # 保证随后打开「⚙ 设置」也能立刻看到 modules_path 已填好
        self._resolve_modules_path()
        # 迁移可能更新了 self.solver_paths，这里再读一次保证 UI 一致
        paths = config_center.get_paths(self.MODULE_ID)
        self.solver_paths = {k: paths.get(k, '') for k in self.EXTRA_KEYS}

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
        self.solver_paths = {k: paths.get(k, '') for k in self.EXTRA_KEYS}
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
        # TAB-4
        if hasattr(self, 'tab4_mac_edit'):
            for edit, key in [
                (self.tab4_mac_edit, 'tab4_mac'),
                (self.tab4_sum_edit, 'tab4_sum'),
                (self.tab4_load_edit, 'tab4_load'),
                (self.tab4_zspan_edit, 'tab4_zspan'),
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
            # TAB-4
            'tab4_mac': str(in_dir / DEFAULT_MAC_FILE),
            'tab4_sum': str(out_dir / 'solver_work'),
            'tab4_load': '',   # 7 列格式：x/fx/fy/fz/mx/my/mz；仅应变/挠度/载荷转化需要
            'tab4_zspan': '',  # 可选：留空则从 mac 的 PLACE SHAPE 自动推算
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
        self.tabs.addTab(self._build_tab3(defaults), '  TAB-3 - Excel ↔ mac  ')
        self.tabs.addTab(self._build_tab4(defaults), '  TAB-4 - FOCUS6 求解器  ')
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
            node = QPushButton(f'  {num}  {label}')
            node.setObjectName('stepperNode')
            node.setCursor(Qt.PointingHandCursor)
            node.setToolTip(f'{full} — 点击切到该阶段')
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
        self.tab3_rb_txt_to_xlsx = QRadioButton('mac → Excel  (blade_geometry.mac → blade_data.xlsx)')
        self.tab3_rb_xlsx_to_txt = QRadioButton('Excel → mac  (blade_data.xlsx → blade_geometry_new.mac)')
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
        # 切换方向时同步默认文件名
        self.tab3_rb_txt_to_xlsx.toggled.connect(self._on_tab3_direction_change)

        grid.addWidget(QLabel('输入文件:'), 1, 0)
        self.tab3_input_edit = QLineEdit(defaults['tab3_input'])
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
        # 方向切换：根据当前输入文件 stem 推导输出（输入名 + _trans + 目标扩展名）
        in_dir = Path(self.input_dir)
        out_dir = Path(self.out_dir)
        if self.tab3_rb_txt_to_xlsx.isChecked():
            # mac → Excel：输入默认 .mac，输出默认 .xlsx
            default_in_name = DEFAULT_TXT_INPUT_FILE
            target_ext = '.xlsx'
        else:
            # Excel → mac：输入默认 .xlsx，输出默认 .mac
            default_in_name = DEFAULT_EXCEL_INPUT_FILE
            target_ext = '.mac'
        # 输入为空 → 回填默认输入
        if not self.tab3_input_edit.text().strip():
            self.tab3_input_edit.setText(str(in_dir / default_in_name))
        # 用当前输入 stem 推导输出（同名 + _trans + 目标扩展名）
        in_path = Path(self.tab3_input_edit.text().strip())
        if in_path.stem:
            out_path = out_dir / 'txt_excel' / f'{in_path.stem}_trans{target_ext}'
            # 仅当输出为空时才覆盖（避免清掉用户手改的路径）
            if not self.tab3_output_edit.text().strip():
                self.tab3_output_edit.setText(str(out_path))
        self._update_tab3_info_text()

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
                '• 要求 Excel 由 TAB-3 正向转换生成（PlaceShapes 必须含 CenterX / CenterY）\n'
                '• 输出与原 mac 等价的文本格式（缩进/对齐尽量保留）'
            )
        self.tab3_info_label.setText(txt)

    # ----- TAB-4: FOCUS6 求解器 -----
    def _build_tab4(self, defaults):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # 求解器路径提示
        solver_box = QGroupBox('FOCUS6 Modules 目录（在「⚙ 设置」里配置）')
        solver_box.setObjectName('gb_solver')
        solver_layout = QGridLayout(solver_box)
        solver_layout.setContentsMargins(10, 8, 10, 8)
        solver_layout.setSpacing(6)
        self.tab4_solver_labels = {}
        lbl_modules = QLabel(self.solver_paths.get('modules_path', '') or '(未配置)')
        lbl_modules.setWordWrap(True)
        lbl_modules.setStyleSheet('color: #666;')
        self.tab4_solver_labels['modules_path'] = lbl_modules
        solver_layout.addWidget(QLabel('Modules 目录:'), 0, 0)
        solver_layout.addWidget(lbl_modules, 0, 1)
        hint_lbl = QLabel('内含 farob/ frbex/ utils/ 等子目录；具体用哪个求解器由下方「求解器类型」决定。')
        hint_lbl.setStyleSheet('color: #999; font-size: 11px;')
        solver_layout.addWidget(hint_lbl, 1, 0, 1, 2)
        solver_layout.setColumnStretch(1, 1)
        v.addWidget(solver_box)

        # 输入配置
        box = QGroupBox('输入/输出')
        box.setObjectName('gb_data')
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        grid.addWidget(QLabel('mac 文件:'), 0, 0)
        self.tab4_mac_edit = QLineEdit(defaults['tab4_mac'])
        grid.addWidget(self.tab4_mac_edit, 0, 1)
        grid.addWidget(self._browse_btn(self.tab4_mac_edit, 'file'), 0, 2)

        grid.addWidget(QLabel('工作目录（SUM）:'), 1, 0)
        self.tab4_sum_edit = QLineEdit(defaults['tab4_sum'])
        grid.addWidget(self.tab4_sum_edit, 1, 1)
        grid.addWidget(self._browse_btn(self.tab4_sum_edit, 'dir'), 1, 2)

        # 载荷文件行（封装为单独 widget，便于整行显隐）
        self.tab4_load_row = QWidget()
        load_row_lay = QHBoxLayout(self.tab4_load_row)
        load_row_lay.setContentsMargins(0, 0, 0, 0)
        load_row_lay.setSpacing(6)
        load_row_lay.addWidget(QLabel('载荷文件 (可选):'))
        self.tab4_load_edit = QLineEdit(defaults['tab4_load'])
        self.tab4_load_edit.setPlaceholderText('7 列格式 x/fx/fy/fz/mx/my/mz（应变/挠度/载荷转化需要）')
        load_row_lay.addWidget(self.tab4_load_edit, 1)
        load_row_lay.addWidget(self._browse_btn(self.tab4_load_edit, 'file'))
        grid.addWidget(self.tab4_load_row, 2, 0, 1, 3)

        # ZSPAN 文件行（同样封装）
        self.tab4_zspan_row = QWidget()
        zspan_row_lay = QHBoxLayout(self.tab4_zspan_row)
        zspan_row_lay.setContentsMargins(0, 0, 0, 0)
        zspan_row_lay.setSpacing(6)
        zspan_row_lay.addWidget(QLabel('ZSPAN 文件 (可选):'))
        self.tab4_zspan_edit = QLineEdit(defaults['tab4_zspan'])
        self.tab4_zspan_edit.setPlaceholderText('留空则从 mac 的 PLACE SHAPE 自动读取')
        zspan_row_lay.addWidget(self.tab4_zspan_edit, 1)
        zspan_row_lay.addWidget(self._browse_btn(self.tab4_zspan_edit, 'file'))
        grid.addWidget(self.tab4_zspan_row, 3, 0, 1, 3)

        grid.setColumnStretch(1, 1)
        v.addWidget(box)

        # 运行选项
        opts = QWidget()
        opts_layout = QHBoxLayout(opts)
        opts_layout.setContentsMargins(0, 0, 0, 0)
        opts_layout.setSpacing(8)

        mode_box = QGroupBox('运行模式')
        mode_layout = QVBoxLayout(mode_box)
        self.tab4_mode_group = QButtonGroup(self)
        self.tab4_rb_single = QRadioButton('单求解器（下方选定功能）')
        self.tab4_rb_one_click = QRadioButton('一键运行（并行执行所有步骤）')
        self.tab4_rb_single.setChecked(True)
        self.tab4_mode_group.addButton(self.tab4_rb_single, 0)
        self.tab4_mode_group.addButton(self.tab4_rb_one_click, 1)
        mode_layout.addWidget(self.tab4_rb_single)
        mode_layout.addWidget(self.tab4_rb_one_click)
        mode_layout.addStretch()

        func_box = QGroupBox('单求解器功能')
        func_layout = QVBoxLayout(func_box)
        self.tab4_func_combo = QComboBox()
        self.tab4_func_combo.addItem(FUNCTION_READ_MAC, FUNCTION_READ_MAC)
        self.tab4_func_combo.addItem(FUNCTION_PARSE_MAC, FUNCTION_PARSE_MAC)
        self.tab4_func_combo.addItem(FUNCTION_WEIGHT, FUNCTION_WEIGHT)
        self.tab4_func_combo.addItem(FUNCTION_FREQUENCY, FUNCTION_FREQUENCY)
        self.tab4_func_combo.addItem(FUNCTION_LOAD_CONVERSION, FUNCTION_LOAD_CONVERSION)
        self.tab4_func_combo.addItem(FUNCTION_STRAIN, FUNCTION_STRAIN)
        self.tab4_func_combo.addItem(FUNCTION_TIP_DEFLECTION, FUNCTION_TIP_DEFLECTION)
        self.tab4_func_combo.currentIndexChanged.connect(self._on_tab4_func_changed)
        func_layout.addWidget(self.tab4_func_combo)
        func_layout.addStretch()

        solver_type_box = QGroupBox('求解器类型')
        st_layout = QVBoxLayout(solver_type_box)
        self.tab4_st_group = QButtonGroup(self)
        self.tab4_rb_farob = QRadioButton('farob')
        self.tab4_rb_frbex = QRadioButton('frbex')
        self.tab4_rb_frbex.setChecked(True)
        self.tab4_st_group.addButton(self.tab4_rb_farob, 0)
        self.tab4_st_group.addButton(self.tab4_rb_frbex, 1)
        st_layout.addWidget(self.tab4_rb_farob)
        st_layout.addWidget(self.tab4_rb_frbex)
        st_layout.addStretch()

        opts_layout.addWidget(mode_box, 1)
        opts_layout.addWidget(func_box, 1)
        opts_layout.addWidget(solver_type_box, 1)
        v.addWidget(opts)

        # 高级参数
        adv = QGroupBox('高级参数')
        adv_layout = QGridLayout(adv)
        adv_layout.setContentsMargins(10, 8, 10, 8)
        adv_layout.setSpacing(6)
        adv_layout.addWidget(QLabel('drmx（frbex）:'), 0, 0)
        self.tab4_drmx_edit = QLineEdit(str(FRBEX_DEFAULT_DRMX))
        self.tab4_drmx_edit.setMaximumWidth(100)
        adv_layout.addWidget(self.tab4_drmx_edit, 0, 1)
        self.tab4_bg_run_cb = QCheckBox('后台运行（隐藏求解器窗口）')
        self.tab4_bg_run_cb.setChecked(True)
        adv_layout.addWidget(self.tab4_bg_run_cb, 0, 2)
        adv_layout.setColumnStretch(3, 1)
        v.addWidget(adv)

        # 刷新求解器路径显示
        self._refresh_solver_labels()

        v.addStretch()
        v.addWidget(self._build_exec_bar(
            stage='tab4',
            run_text='运行 TAB-4',
            run_slot=self._on_run_tab4,
            open_dir_getter=lambda: Path(self.tab4_sum_edit.text()),
        ))

        # 所有 widget 创建完毕后再触发一次显隐同步
        self._on_tab4_func_changed(self.tab4_func_combo.currentIndex())
        return page

    def _refresh_solver_labels(self):
        """刷新 TAB-4 的求解器路径显示。"""
        for key, lbl in self.tab4_solver_labels.items():
            val = self.solver_paths.get(key, '') or ''
            lbl.setText(val if val else '(未配置)')
            lbl.setStyleSheet('color: #999;' if not val else 'color: #444;')

    def _on_tab4_func_changed(self, idx):
        """根据所选功能动态显隐载荷文件 / ZSPAN 行。

        载荷文件用于：应变计算、叶尖挠度、载荷转化
        ZSPAN 仅用于：farob 应变计算（其余场景隐藏，但仍允许显式提供）
        """
        if not hasattr(self, 'tab4_func_combo'):
            return
        func = self.tab4_func_combo.currentData()
        need_load = func in (FUNCTION_STRAIN, FUNCTION_TIP_DEFLECTION, FUNCTION_LOAD_CONVERSION)
        need_zspan = func == FUNCTION_STRAIN  # 仅 farob 应变才真正读 zspan
        if hasattr(self, 'tab4_load_row'):
            self.tab4_load_row.setVisible(need_load)
        if hasattr(self, 'tab4_zspan_row'):
            self.tab4_zspan_row.setVisible(need_zspan)

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

    # ----- 通用：执行栏（复用 shape_output_panel 模式）-----
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

    # ============================================================
    # TAB-4 执行
    # ============================================================
    def _on_run_tab4(self):
        mac_file = self.tab4_mac_edit.text().strip()
        sum_folder = self.tab4_sum_edit.text().strip()
        load_file = self.tab4_load_edit.text().strip()
        zspan_file = self.tab4_zspan_edit.text().strip()
        one_click = self.tab4_rb_one_click.isChecked()
        solver_type = SOLVER_FAROB if self.tab4_rb_farob.isChecked() else SOLVER_FRBEX

        if not mac_file or not Path(mac_file).exists():
            QMessageBox.warning(self, '缺少 mac', f'文件不存在：{mac_file}')
            return
        if not sum_folder:
            QMessageBox.warning(self, '缺少工作目录', '请指定 SUM 工作目录')
            return

        # 求解器路径检查（唯一 extras：modules_path）
        modules_path = self._resolve_modules_path()
        if not modules_path:
            QMessageBox.warning(
                self, '求解器未配置',
                '未配置 FOCUS6 Modules 目录。\n请到「⚙ 设置」里配置「FOCUS6 Modules 目录」。',
            )
            return

        # 高级参数
        try:
            drmx = int(self.tab4_drmx_edit.text().strip() or FRBEX_DEFAULT_DRMX)
        except ValueError:
            QMessageBox.warning(self, 'drmx 错误', 'drmx 必须是整数')
            return
        background_run = self.tab4_bg_run_cb.isChecked()

        # 从 mac 提取半径（默认 50000 mm）
        radius = self._extract_radius_from_mac(mac_file)

        function = self.tab4_func_combo.currentData()

        # 载荷文件检查：应变/挠度/载荷转化 必填
        need_load = function in (FUNCTION_STRAIN, FUNCTION_TIP_DEFLECTION, FUNCTION_LOAD_CONVERSION)
        if need_load and (not load_file or not Path(load_file).exists()):
            QMessageBox.warning(
                self, '缺少载荷文件',
                f'当前功能 "{function}" 需要 7 列载荷文件（x/fx/fy/fz/mx/my/mz）。\n'
                f'请检查输入：{load_file or "(空)"}',
            )
            return

        # ZSPAN 自动补全：farob 应变需要；用户留空时从 mac 的 PLACE SHAPE 自动提取
        zspan_file_resolved = zspan_file
        zspan_source = 'user'
        if function == FUNCTION_STRAIN and solver_type == SOLVER_FAROB and not zspan_file_resolved:
            derived = self._derive_zspan_from_mac(mac_file, sum_folder)
            if derived:
                zspan_file_resolved = derived
                zspan_source = 'auto-from-mac'

        # 载荷转化：只走 modules_path/utils，不需要 solver_type 子目录
        # 其余功能按 solver_type 选用 Modules/{farob|frbex}
        if function == FUNCTION_LOAD_CONVERSION:
            solver_path_for_params = str(Path(modules_path) / 'utils')
        else:
            solver_path_for_params = str(Path(modules_path) / solver_type)

        params = {
            'solver_type': solver_type,
            'mac_solver_type': solver_type,
            'function': function,
            'modules_path': modules_path,
            'solver_path': solver_path_for_params,
            'sum_folder': sum_folder,
            'mac_file': mac_file,
            'radius': radius,
            'drmx': drmx,
            'background_run': background_run,
            'load_file': load_file,
            'zspan_file': zspan_file_resolved,
        }

        self.tab4_log.clear()
        self.tab4_progress.setValue(0)
        self._set_running('tab4', True)
        self.tab4_open_btn.setEnabled(False)

        self._log('tab4', f'模式: {"一键运行" if one_click else "单求解器"}')
        self._log('tab4', f'求解器: {solver_type}')
        if not one_click:
            self._log('tab4', f'功能: {function}')
        self._log('tab4', f'mac: {mac_file}')
        self._log('tab4', f'工作目录: {sum_folder}')
        self._log('tab4', f'modules_path: {modules_path}')
        if load_file:
            self._log('tab4', f'载荷文件: {load_file}')
        if zspan_file_resolved:
            tag = '' if zspan_source == 'user' else '  (从 mac PLACE SHAPE 自动生成)'
            self._log('tab4', f'ZSPAN: {zspan_file_resolved}{tag}')
        self._log('tab4', f'drmx: {drmx}, background: {background_run}, radius: {radius}')
        self._log('tab4', '---')

        self._tab4_worker = ConverterTab4Worker(params, one_click=one_click)
        self._tab4_worker.progress.connect(self._on_tab4_progress)
        self._tab4_worker.finished.connect(self._on_tab4_finished)
        self._tab4_worker.start()

    def _resolve_modules_path(self):
        """返回 ConfigCenter extras 中的 modules_path（FOCUS6 Modules 目录）。

        兼容老配置：若用户曾配过 ``farob_exe``，则向上推一级推断 Modules 目录，
        并把推断结果写入 ``modules_path``、清空 ``farob_exe``。
        新配置直接走 modules_path 字段。
        """
        # 直接从 config_center 拉 raw extras，避免 self.solver_paths 已按 EXTRA_KEYS 过滤
        raw = config_center.get_paths(self.MODULE_ID)
        val = raw.get('modules_path', '') or ''
        if val:
            return val
        # 迁移兜底：从老 farob_exe 推断（.../Modules/farob/farob.exe → .../Modules）
        farob = raw.get('farob_exe', '') or ''
        if not farob:
            return ''
        p = Path(farob)
        if p.parent.name.lower() == 'farob':
            inferred = str(p.parent.parent)
            config_center.set_extra(self.MODULE_ID, 'modules_path', inferred)
            config_center.set_extra(self.MODULE_ID, 'farob_exe', '')
            # 同步本地缓存
            self.solver_paths['modules_path'] = inferred
            return inferred
        return str(p.parent)

    @staticmethod
    def _derive_zspan_from_mac(mac_file, sum_folder):
        """从 mac 的 PLACE SHAPE 行提取展向位置（mm），写到 sum_folder/zspan_auto.txt。

        PLACE SHAPE 行格式：``PLACE SHAPE  R_1.5  1500`` —— 最后一个 token 即 span 位置 mm。
        返回生成的文件路径；失败返回空串。
        """
        import re
        try:
            with open(mac_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            spans = []
            for line in lines:
                m = re.match(r'^\s*PLACE\s+SHAPE\s+\S+\s+(\d+\.?\d*)', line,
                             re.IGNORECASE)
                if m:
                    try:
                        spans.append(float(m.group(1)))
                    except ValueError:
                        continue
            if not spans:
                return ''
            # 去重 + 排序
            spans = sorted(set(spans))
            Path(sum_folder).mkdir(parents=True, exist_ok=True)
            out = Path(sum_folder) / 'zspan_auto.txt'
            with open(out, 'w', encoding='utf-8') as f:
                for s in spans:
                    f.write(f"{s}\n")
            return str(out)
        except Exception:
            return ''

    @staticmethod
    def _extract_radius_from_mac(mac_file):
        """从 mac 文件提取 RADIUS（mm），失败返回 '50000'。"""
        import re
        try:
            with open(mac_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            m = re.search(r'DEF\s+PARA\s*,\s*RADIUS\s*=\s*(\d+\.?\d*)',
                          content, re.IGNORECASE)
            return m.group(1) if m else '50000'
        except Exception:
            return '50000'

    def _on_tab4_progress(self, percent, msg):
        self.tab4_progress.setValue(percent)
        self._log('tab4', msg)

    def _on_tab4_finished(self):
        self._set_running('tab4', False)
        res = self._tab4_worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'TAB-4 出错', res['error'])
        else:
            self.tab4_open_btn.setEnabled(True)
            self._mark_stage_completed('tab4')
