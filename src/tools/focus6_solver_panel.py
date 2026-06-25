# -*- coding: utf-8 -*-
"""FOCUS6 面板（QWidget 子类）。

v0.3.0 从 blade_converter 拆出，独立成模块。
单页平铺布局（无 Tab 切换），4 个 GroupBox：
  1. FOCUS6 Modules 目录提示（在「⚙ 设置」里配置）
  2. 输入/输出：mac 文件 / SUM 工作目录 / 载荷文件 / ZSPAN 文件
  3. 运行选项：运行模式（单/一键）+ 功能 + 求解器类型
  4. 高级参数：drmx / 后台运行

业务走 focus6_solver 子包（Focus6SolverThread / OneClickRunThread）。
modules_path extra 从 blade_converter 迁移（首启自动复制）。
"""
import os
import sys
import traceback
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QCheckBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox,
    QLineEdit, QRadioButton, QButtonGroup,
    QScrollArea, QFrame, QSizePolicy, QComboBox,
)

from global_config import config_center
from focus6_solver.solver_config import (
    DEFAULT_MAC_FILE, DEFAULT_MODULES_PATH,
    SOLVER_FAROB, SOLVER_FRBEX,
    FUNCTION_READ_MAC, FUNCTION_PARSE_MAC, FUNCTION_FREQUENCY,
    FUNCTION_TIP_DEFLECTION, FUNCTION_STRAIN, FUNCTION_WEIGHT,
    FUNCTION_LOAD_CONVERSION,
    FRBEX_DEFAULT_DRMX,
)
from focus6_solver import Focus6SolverThread, OneClickRunThread


# ============================================================
# Worker
# ============================================================

class Focus6SolverWorker(QThread):
    """FOCUS6 执行 Worker（支持一键运行）。

    内部直接复用 focus6_solver.Focus6SolverThread / OneClickRunThread 两个 QThread 类，
    但 QThread 不能嵌套 start，这里在 run() 里直接调用其 run()（同步执行）。
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
                self._log(10, '一键运行模式（依次执行 6 步）')
                runner = OneClickRunThread(self.params, summarize_only=False)
                runner.log_signal.connect(lambda m: self._log(50, m))
                runner.progress_signal.connect(
                    lambda cur, total: self._log(
                        10 + int(80 * cur / max(1, total)), f'步骤 {cur}/{total}'
                    )
                )
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
            self._log(100, '=== 求解器任务完成 ===')
            self.result = {'output': self.params.get('sum_folder', '')}
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    def _log(self, p, m):
        self.progress.emit(p, m)


# ============================================================
# 主面板
# ============================================================

class Focus6SolverPanel(QWidget):
    MODULE_ID = 'focus6_solver'
    DEFAULT_INPUT_SUBDIR = 'focus6_solver'
    DEFAULT_OUTPUT_SUBDIR = 'focus6_solver'
    EXTRA_KEYS = ['modules_path']

    def __init__(self):
        super().__init__()
        # 从 blade_converter 复制 modules_path（一次性，仅当新模块未配时）
        # 这里的 get_paths 在 panel 未注册前返回 input/output 各为 ''，extras 读不到；
        # 实际复制由 path_migration.migrate_extras_between_modules 在 main.py 里完成
        bc_paths = config_center.get_paths('blade_converter') or {}
        bc_modules = bc_paths.get('modules_path', '')
        config_center.register_module(
            self.MODULE_ID,
            self.DEFAULT_INPUT_SUBDIR,
            self.DEFAULT_OUTPUT_SUBDIR,
            extra_keys=self.EXTRA_KEYS,
            default_extras={'modules_path': bc_modules} if bc_modules else None,
        )
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        self.solver_paths = {k: paths.get(k, '') for k in self.EXTRA_KEYS}

        config_center.paths_changed.connect(self._on_paths_changed)

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
        if hasattr(self, 'mac_edit'):
            self._sync_path_edits()
            self._refresh_solver_labels()

    def _sync_path_edits(self):
        defaults = self._default_paths()
        for edit, key in [
            (self.mac_edit, 'mac'),
            (self.sum_edit, 'sum'),
            (self.load_edit, 'load'),
            (self.zspan_edit, 'zspan'),
        ]:
            cur = edit.text().strip()
            if not cur:
                edit.setText(defaults[key])

    def _default_paths(self):
        in_dir = Path(self.input_dir)
        out_dir = Path(self.out_dir)
        return {
            'mac': str(in_dir / DEFAULT_MAC_FILE),
            'sum': str(out_dir / 'solver_work'),
            'load': str(in_dir / 'loads.txt'),
            'zspan': str(in_dir / 'zspan.txt'),
        }

    def _build_ui(self):
        defaults = self._default_paths()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_banner())

        # 滚动区包裹内容，窗口太矮时可上下滚动
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setMinimumHeight(0)
        scroll.setWidget(content)

        v = QVBoxLayout(content)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # === 1. 求解器路径提示 ===
        solver_box = QGroupBox('FOCUS6 Modules 目录（在「⚙ 设置」里配置）')
        solver_box.setObjectName('gb_solver')
        solver_layout = QGridLayout(solver_box)
        solver_layout.setContentsMargins(10, 8, 10, 8)
        solver_layout.setSpacing(6)
        self.solver_labels = {}
        lbl_modules = QLabel(self.solver_paths.get('modules_path', '') or '(未配置)')
        lbl_modules.setWordWrap(True)
        lbl_modules.setStyleSheet('color: #666;')
        self.solver_labels['modules_path'] = lbl_modules
        solver_layout.addWidget(QLabel('Modules 目录:'), 0, 0)
        solver_layout.addWidget(lbl_modules, 0, 1)
        hint_lbl = QLabel('内含 farob/ frbex/ utils/ 等子目录；具体用哪个求解器由下方「求解器类型」决定。')
        hint_lbl.setStyleSheet('color: #999; font-size: 11px;')
        solver_layout.addWidget(hint_lbl, 1, 0, 1, 2)
        solver_layout.setColumnStretch(1, 1)
        v.addWidget(solver_box)

        # === 2. 输入/输出 ===
        box = QGroupBox('输入/输出')
        box.setObjectName('gb_data')
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)

        grid.addWidget(QLabel('mac 文件:'), 0, 0)
        self.mac_edit = QLineEdit(defaults['mac'])
        grid.addWidget(self.mac_edit, 0, 1)
        grid.addWidget(self._browse_btn(self.mac_edit, 'file'), 0, 2)

        grid.addWidget(QLabel('工作目录（SUM）:'), 1, 0)
        self.sum_edit = QLineEdit(defaults['sum'])
        grid.addWidget(self.sum_edit, 1, 1)
        grid.addWidget(self._browse_btn(self.sum_edit, 'dir'), 1, 2)

        # 载荷文件行（封装为单独 widget，便于整行显隐）
        self.load_row = QWidget()
        load_row_lay = QHBoxLayout(self.load_row)
        load_row_lay.setContentsMargins(0, 0, 0, 0)
        load_row_lay.setSpacing(6)
        load_row_lay.addWidget(QLabel('载荷文件 (可选):'))
        self.load_edit = QLineEdit(defaults['load'])
        self.load_edit.setPlaceholderText('7 列格式 x/fx/fy/fz/mx/my/mz（应变/挠度/载荷转化需要）')
        load_row_lay.addWidget(self.load_edit, 1)
        load_row_lay.addWidget(self._browse_btn(self.load_edit, 'file'))
        grid.addWidget(self.load_row, 2, 0, 1, 3)

        # ZSPAN 文件行
        self.zspan_row = QWidget()
        zspan_row_lay = QHBoxLayout(self.zspan_row)
        zspan_row_lay.setContentsMargins(0, 0, 0, 0)
        zspan_row_lay.setSpacing(6)
        zspan_row_lay.addWidget(QLabel('ZSPAN 文件 (可选):'))
        self.zspan_edit = QLineEdit(defaults['zspan'])
        self.zspan_edit.setPlaceholderText('留空则从 mac 的 PLACE SHAPE 自动读取')
        zspan_row_lay.addWidget(self.zspan_edit, 1)
        zspan_row_lay.addWidget(self._browse_btn(self.zspan_edit, 'file'))
        grid.addWidget(self.zspan_row, 3, 0, 1, 3)

        grid.setColumnStretch(1, 1)
        v.addWidget(box)

        # === 3. 运行选项 ===
        opts = QWidget()
        opts_layout = QHBoxLayout(opts)
        opts_layout.setContentsMargins(0, 0, 0, 0)
        opts_layout.setSpacing(8)

        mode_box = QGroupBox('运行模式')
        mode_layout = QVBoxLayout(mode_box)
        self.mode_group = QButtonGroup(self)
        self.rb_single = QRadioButton('单求解器（下方选定功能）')
        self.rb_one_click = QRadioButton('一键运行（依次执行所有步骤）')
        self.rb_single.setChecked(True)
        self.mode_group.addButton(self.rb_single, 0)
        self.mode_group.addButton(self.rb_one_click, 1)
        mode_layout.addWidget(self.rb_single)
        mode_layout.addWidget(self.rb_one_click)
        mode_layout.addStretch()

        func_box = QGroupBox('单求解器功能')
        func_layout = QVBoxLayout(func_box)
        self.func_combo = QComboBox()
        self.func_combo.addItem(FUNCTION_READ_MAC, FUNCTION_READ_MAC)
        self.func_combo.addItem(FUNCTION_PARSE_MAC, FUNCTION_PARSE_MAC)
        self.func_combo.addItem(FUNCTION_WEIGHT, FUNCTION_WEIGHT)
        self.func_combo.addItem(FUNCTION_FREQUENCY, FUNCTION_FREQUENCY)
        self.func_combo.addItem(FUNCTION_LOAD_CONVERSION, FUNCTION_LOAD_CONVERSION)
        self.func_combo.addItem(FUNCTION_STRAIN, FUNCTION_STRAIN)
        self.func_combo.addItem(FUNCTION_TIP_DEFLECTION, FUNCTION_TIP_DEFLECTION)
        self.func_combo.currentIndexChanged.connect(self._on_func_changed)
        func_layout.addWidget(self.func_combo)
        func_layout.addStretch()

        solver_type_box = QGroupBox('求解器类型')
        st_layout = QVBoxLayout(solver_type_box)
        self.st_group = QButtonGroup(self)
        self.rb_farob = QRadioButton('farob')
        self.rb_frbex = QRadioButton('frbex')
        self.rb_frbex.setChecked(True)
        self.st_group.addButton(self.rb_farob, 0)
        self.st_group.addButton(self.rb_frbex, 1)
        st_layout.addWidget(self.rb_farob)
        st_layout.addWidget(self.rb_frbex)
        st_layout.addStretch()

        opts_layout.addWidget(mode_box, 1)
        opts_layout.addWidget(func_box, 1)
        opts_layout.addWidget(solver_type_box, 1)
        v.addWidget(opts)

        # === 4. 高级参数 ===
        adv = QGroupBox('高级参数')
        adv_layout = QGridLayout(adv)
        adv_layout.setContentsMargins(10, 8, 10, 8)
        adv_layout.setSpacing(6)
        adv_layout.addWidget(QLabel('drmx（frbex）:'), 0, 0)
        self.drmx_edit = QLineEdit(str(FRBEX_DEFAULT_DRMX))
        self.drmx_edit.setMaximumWidth(100)
        adv_layout.addWidget(self.drmx_edit, 0, 1)
        self.bg_run_cb = QCheckBox('后台运行（隐藏求解器窗口）')
        self.bg_run_cb.setChecked(True)
        adv_layout.addWidget(self.bg_run_cb, 0, 2)
        adv_layout.setColumnStretch(3, 1)
        v.addWidget(adv)

        # 刷新求解器路径显示
        self._refresh_solver_labels()

        v.addStretch()
        v.addWidget(self._build_exec_bar(
            stage='main',
            run_text='运行',
            run_slot=self._on_run,
            open_dir_getter=lambda: Path(self.sum_edit.text()),
        ))

        # 初始显隐同步
        self._on_func_changed(self.func_combo.currentIndex())

        outer.addWidget(scroll, 1)

    def _build_banner(self):
        banner = QWidget()
        banner.setObjectName('moduleBanner')
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(4)
        title = QLabel('FOCUS6')
        title.setObjectName('moduleTitle')
        title.setAlignment(Qt.AlignCenter)
        tf = QFont('YouSheBiaoTiHei', 16)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        title.setFont(tf)
        sub = QLabel('F O C U S 6   S O L V E R')
        sub.setObjectName('moduleSubtitle')
        sub.setAlignment(Qt.AlignCenter)
        sf = QFont('Consolas', 8)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        sf.setBold(True)
        sub.setFont(sf)
        bl.addWidget(title)
        bl.addWidget(sub)
        return banner

    def _refresh_solver_labels(self):
        """刷新 Modules 目录路径显示。"""
        for key, lbl in self.solver_labels.items():
            val = self.solver_paths.get(key, '') or ''
            lbl.setText(val if val else '(未配置)')
            lbl.setStyleSheet('color: #999;' if not val else 'color: #444;')

    def _on_func_changed(self, idx):
        """根据所选功能动态显隐载荷文件 / ZSPAN 行。"""
        if not hasattr(self, 'func_combo'):
            return
        func = self.func_combo.currentData()
        need_load = func in (FUNCTION_STRAIN, FUNCTION_TIP_DEFLECTION, FUNCTION_LOAD_CONVERSION)
        need_zspan = func == FUNCTION_STRAIN  # 仅 farob 应变才真正读 zspan
        if hasattr(self, 'load_row'):
            self.load_row.setVisible(need_load)
        if hasattr(self, 'zspan_row'):
            self.zspan_row.setVisible(need_zspan)

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

    # ----- 通用：执行栏 -----
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

    # ----- 通用：日志/状态 -----
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
    # 执行
    # ============================================================
    def _on_run(self):
        mac_file = self.mac_edit.text().strip()
        sum_folder = self.sum_edit.text().strip()
        load_file = self.load_edit.text().strip()
        zspan_file = self.zspan_edit.text().strip()
        one_click = self.rb_one_click.isChecked()
        solver_type = SOLVER_FAROB if self.rb_farob.isChecked() else SOLVER_FRBEX

        if not mac_file or not Path(mac_file).exists():
            QMessageBox.warning(self, '缺少 mac', f'文件不存在：{mac_file}')
            return
        if not sum_folder:
            QMessageBox.warning(self, '缺少工作目录', '请指定 SUM 工作目录')
            return

        # 求解器路径检查
        modules_path = self._resolve_modules_path()
        if not modules_path:
            QMessageBox.warning(
                self, '求解器未配置',
                '未配置 FOCUS6 Modules 目录。\n请到「⚙ 设置」里配置「FOCUS6 Modules 目录」。',
            )
            return

        # 高级参数
        try:
            drmx = int(self.drmx_edit.text().strip() or FRBEX_DEFAULT_DRMX)
        except ValueError:
            QMessageBox.warning(self, 'drmx 错误', 'drmx 必须是整数')
            return
        background_run = self.bg_run_cb.isChecked()

        # 从 mac 提取半径
        radius = self._extract_radius_from_mac(mac_file)

        function = self.func_combo.currentData()

        # 载荷文件检查
        need_load = function in (FUNCTION_STRAIN, FUNCTION_TIP_DEFLECTION, FUNCTION_LOAD_CONVERSION)
        if need_load and (not load_file or not Path(load_file).exists()):
            QMessageBox.warning(
                self, '缺少载荷文件',
                f'当前功能 "{function}" 需要 7 列载荷文件（x/fx/fy/fz/mx/my/mz）。\n'
                f'请检查输入：{load_file or "(空)"}',
            )
            return

        # ZSPAN 自动补全
        zspan_file_resolved = zspan_file
        zspan_source = 'user'
        if function == FUNCTION_STRAIN and solver_type == SOLVER_FAROB and not zspan_file_resolved:
            derived = self._derive_zspan_from_mac(mac_file, sum_folder)
            if derived:
                zspan_file_resolved = derived
                zspan_source = 'auto-from-mac'

        # 载荷转化走 utils，其余按 solver_type 选子目录
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

        self.main_log.clear()
        self.main_progress.setValue(0)
        self._set_running('main', True)
        self.main_open_btn.setEnabled(False)

        self._log('main', f'模式: {"一键运行" if one_click else "单求解器"}')
        self._log('main', f'求解器: {solver_type}')
        if not one_click:
            self._log('main', f'功能: {function}')
        self._log('main', f'mac: {mac_file}')
        self._log('main', f'工作目录: {sum_folder}')
        self._log('main', f'modules_path: {modules_path}')
        if load_file:
            self._log('main', f'载荷文件: {load_file}')
        if zspan_file_resolved:
            tag = '' if zspan_source == 'user' else '  (从 mac PLACE SHAPE 自动生成)'
            self._log('main', f'ZSPAN: {zspan_file_resolved}{tag}')
        self._log('main', f'drmx: {drmx}, background: {background_run}, radius: {radius}')
        self._log('main', '---')

        self._worker = Focus6SolverWorker(params, one_click=one_click)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _resolve_modules_path(self):
        """返回 ConfigCenter extras 中的 modules_path。

        兼容：若用户曾配过 ``farob_exe``（老格式），向上推一级推断 Modules 目录，
        并写入 ``modules_path``、清空 ``farob_exe``。
        """
        raw = config_center.get_paths(self.MODULE_ID)
        val = raw.get('modules_path', '') or ''
        if val:
            return val
        farob = raw.get('farob_exe', '') or ''
        if not farob:
            return ''
        p = Path(farob)
        if p.parent.name.lower() == 'farob':
            inferred = str(p.parent.parent)
            config_center.set_extra(self.MODULE_ID, 'modules_path', inferred)
            config_center.set_extra(self.MODULE_ID, 'farob_exe', '')
            self.solver_paths['modules_path'] = inferred
            return inferred
        return str(p.parent)

    @staticmethod
    def _derive_zspan_from_mac(mac_file, sum_folder):
        """从 mac 的 PLACE SHAPE 行提取展向位置（mm），写到 sum_folder/zspan_auto.txt。"""
        import re
        try:
            with open(mac_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            spans = []
            for line in lines:
                m = re.match(r'^\s*PLACE\s+SHAPE\s+\S+\s+(\d+\.?\d*)', line, re.IGNORECASE)
                if m:
                    try:
                        spans.append(float(m.group(1)))
                    except ValueError:
                        continue
            if not spans:
                return ''
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

    def _on_progress(self, percent, msg):
        self.main_progress.setValue(percent)
        self._log('main', msg)

    def _on_finished(self):
        self._set_running('main', False)
        res = self._worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'FOCUS6 出错', res['error'])
        else:
            self.main_open_btn.setEnabled(True)
