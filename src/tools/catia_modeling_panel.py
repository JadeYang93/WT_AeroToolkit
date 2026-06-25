# -*- coding: utf-8 -*-
"""CATIA 叶片建模 面板。

侧边栏独立工具。三个 Tab（① 构建截面 / ② 重采样光顺 / ③ 生成曲面），
每个 Tab 内有独立参数区 + 独立执行栏（运行按钮 + 进度条 + 日志），
结构参照叶片形状输出（shape_design_panel）的多 stage 模式。

运行时检测 CATIA: 点运行先 try 连接，失败弹窗引导，不进入 Worker。
"""
import os
import sys
import subprocess

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QFrame, QLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
    QCheckBox, QFileDialog, QMessageBox,
    QScrollArea, QTabWidget, QProgressBar, QTextEdit, QSizePolicy,
)

from tools.base_module_panel import BaseModulePanel
from catia_modeling import (
    SectionParams, ResampleParams, LoftParams,
    load_params, save_params, CatiaModelError,
)
from catia_modeling.worker import CatiaModelingWorker


# 三个步骤的元信息：(step_key, tab 标题, tab 副标题, 运行按钮文字)
_STEPS = (
    ('sections', '① 构建截面', '点云 → 样条 + 光顺 + 平面 + 前尾缘 + 弦线', '▶  运行 ① 构建截面'),
    ('resample', '② 重采样光顺', '样条 → 等距重采样 + 光顺', '▶  运行 ② 重采样光顺'),
    ('loft', '③ 生成曲面', '多截面曲线 → 多截面曲面 Loft', '▶  运行 ③ 生成曲面'),
)


class CatiaModelingPanel(BaseModulePanel):
    MODULE_ID = 'catia_modeling'
    DEFAULT_INPUT_SUBDIR = 'catia_modeling/input'
    DEFAULT_OUTPUT_SUBDIR = 'catia_modeling/output'
    MODULE_TITLE = 'CATIA 叶片建模'
    MODULE_SUBTITLE = 'C A T I A   B L A D E   M O D E L I N G'

    # 各步骤执行栏的固定高度（与基类 exec_bar 视觉一致）
    EXEC_BAR_HEIGHT = 160

    def __init__(self):
        self._param_widgets = {}        # key -> widget，运行时读值
        self._step_meta = {}            # step_key -> (run_btn, progress, log_area)
        self._workers = {'sections': None, 'resample': None, 'loft': None}
        super().__init__()
        self._load_params_to_ui()       # 回填持久化参数

    # ============================================================
    # 主体构建：输入区 + 三 Tab（每 Tab 参数区 + 独立执行栏）
    # ============================================================
    def _build_body(self, outer_layout):
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.setSpacing(12)

        # 顶部输入区（三步骤共用，放 tab 之外）
        bl.addWidget(self._build_input_area())

        # 三 Tab
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_sections_tab(), '  ① 构建截面  ')
        self.tabs.addTab(self._build_resample_tab(), '  ② 重采样光顺  ')
        self.tabs.addTab(self._build_loft_tab(), '  ③ 生成曲面  ')
        bl.addWidget(self.tabs, 1)

        outer_layout.addWidget(body, 1)

    # ------------------------------------------------------------
    # 输入区（STP 路径，三步骤共用）
    # ------------------------------------------------------------
    def _build_input_area(self):
        """STP 文件选择区（仅提示/记录，不传给 CATIA）。"""
        box = QGroupBox('输入文件')
        gl = QGridLayout(box)
        gl.setContentsMargins(10, 8, 10, 8)
        gl.addWidget(QLabel('STP 点云:'), 0, 0)
        self._stp_edit = QLineEdit()
        self._stp_edit.setPlaceholderText(
            '默认指向叶片形状输出 STAGE-3 的 3D_points.stp')
        gl.addWidget(self._stp_edit, 0, 1)
        browse = QPushButton('…')
        browse.setFixedWidth(36)
        browse.clicked.connect(self._on_browse_stp)
        gl.addWidget(browse, 0, 2)
        tip = QLabel('提示: 请先在 CATIA 中手动导入此 STP，'
                     '点云需带 Sect{组}_{点} 命名')
        tip.setStyleSheet('color: #6b7280; font-size: 11px;')
        gl.addWidget(tip, 1, 0, 1, 3)
        return box

    def _on_browse_stp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 STP 点云文件', '', 'STEP 文件 (*.stp *.step)')
        if path:
            self._stp_edit.setText(path)

    # ============================================================
    # 控件构建辅助（与原单页面版一致）
    # ============================================================
    def _spin(self, key, lo, hi, default, is_double=False):
        """创建并登记一个 SpinBox（无上下箭头按钮，纯键盘输入）。"""
        if is_double:
            w = QDoubleSpinBox()
            w.setDecimals(3)
        else:
            w = QSpinBox()
        # 隐藏右侧上下箭头按钮——参数靠键盘直接输入，箭头无意义
        w.setButtonSymbols(QAbstractSpinBox.NoButtons)
        w.setRange(lo, hi)
        w.setValue(default)
        self._param_widgets[key] = w
        return w

    def _line(self, key, default):
        """创建并登记一个 LineEdit。"""
        w = QLineEdit(str(default))
        self._param_widgets[key] = w
        return w

    def _row(self, label, *widgets):
        """生成 (QLabel, [widgets...]) 横排的 QHBoxLayout 容器。

        垂直 sizePolicy 设为 Fixed：防止在 QVBoxLayout / ScrollArea 中被
        拉伸占满高度，确保折叠区展开/收起时上方各行位置不动（顶对齐）。
        """
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSizeConstraint(QLayout.SetFixedSize)
        rl.addWidget(QLabel(label))
        for w in widgets:
            rl.addWidget(w)
        rl.addStretch()
        return row

    def _advanced_toggle(self, group_layout, advanced_frame, group_key):
        """在 GroupBox 底部加高级参数折叠勾选框。"""
        cb = QCheckBox('⚙ 高级参数')
        advanced_frame.setVisible(False)

        def _toggle(state):
            advanced_frame.setVisible(bool(state))

        cb.stateChanged.connect(_toggle)
        self._param_widgets[f'_advanced_{group_key}'] = cb
        group_layout.addWidget(cb)
        group_layout.addWidget(advanced_frame)

    # ============================================================
    # 各步骤参数区构建（内容不变，仅去掉 GroupBox 外壳改成 tab 内区）
    # ============================================================
    def _make_params_container(self):
        """创建参数区容器：垂直 Fixed，内容按需撑开，多余空间归 ScrollArea。

        返回 (widget, layout)。各步骤构建方法把行 addWidget 到 layout，
        末尾由调用方 _end_params_container 加 stretch 收尾。
        这样折叠区显隐时，参数区只占内容高度，上方行顶对齐、不乱动。
        """
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        gl = QVBoxLayout(wrap)
        gl.setContentsMargins(0, 6, 0, 6)
        gl.setSpacing(6)
        return wrap, gl

    def _build_sections_params(self):
        """① 构建截面参数区。"""
        wrap, gl = self._make_params_container()
        # 核心
        gl.addWidget(self._row('截面数', self._spin('sec.num_groups', 1, 9999, 96)))
        gl.addWidget(self._row('起始组号', self._spin('sec.start_group', 1, 9999, 1)))
        t1 = self._spin('sec.smooth_t1', 0, 9999, 4)
        t2 = self._spin('sec.smooth_t2', 0, 9999, 3)
        t3 = self._spin('sec.smooth_t3', 0, 9999, 2)
        t4 = self._spin('sec.smooth_t4', 0, 9999, 1)
        gl.addWidget(self._row('四段光顺阈值', t1, t2, t3, t4))
        # 高级
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._row('点数上限', self._spin('sec.points_per_section', 2, 99999, 400)))
        al.addWidget(self._row('前缘点序号', self._spin('sec.le_point_num', 1, 99999, 200)))
        al.addWidget(self._row('尾缘点1', self._spin('sec.te_point1_num', 1, 99999, 1)))
        al.addWidget(self._row('尾缘点2', self._spin('sec.te_point399_num', 1, 99999, 399)))
        al.addWidget(self._row('相切阈值', self._spin('sec.tangency_threshold', 0, 99, 0.5, is_double=True)))
        al.addWidget(self._row('校正模式', self._spin('sec.correction_mode', 0, 9, 3)))
        al.addWidget(self._row('样条集', self._line('sec.spline_set', 'Z_Splines')))
        al.addWidget(self._row('光顺集', self._line('sec.smooth_set', 'Z_Smooths')))
        al.addWidget(self._row('平面集', self._line('sec.plane_set', 'Z_Planes')))
        al.addWidget(self._row('边缘集', self._line('sec.edge_set', 'Z_Edges')))
        al.addWidget(self._row('尾缘集', self._line('sec.te_set', 'Z_TrailingEdges')))
        self._advanced_toggle(gl, adv, 'sections')
        return wrap

    def _build_resample_params(self):
        """② 重采样光顺参数区。"""
        wrap, gl = self._make_params_container()
        gl.addWidget(self._row('源样条集', self._line('res.source_set', 'Z_Smooths')))
        gl.addWidget(self._row('重采样点数', self._spin('res.num_points', 2, 99999, 149)))
        gl.addWidget(self._row('光顺偏差阈值', self._spin('res.smooth_max_deviation', 0, 9999, 1.0, is_double=True)))
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._row('相切阈值', self._spin('res.tangency_threshold', 0, 99, 0.5, is_double=True)))
        al.addWidget(self._row('校正模式', self._spin('res.correction_mode', 0, 9, 3)))
        al.addWidget(self._row('点集', self._line('res.point_set', 'Z_ResamplePoints')))
        al.addWidget(self._row('原始样条集', self._line('res.original_set', 'Z_OriginalSpline')))
        al.addWidget(self._row('光顺集', self._line('res.smooth_set', 'Z_ResampleSmooth')))
        self._advanced_toggle(gl, adv, 'resample')
        return wrap

    def _build_loft_params(self):
        """③ 生成曲面参数区。"""
        wrap, gl = self._make_params_container()
        gl.addWidget(self._row('源曲线集', self._line('loft.source_set', 'Z_ResampleSmooth')))
        gl.addWidget(self._row('截面耦合方式', self._spin('loft.section_coupling', 0, 2, 1)))
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._row('重新限定', self._spin('loft.relimitation', 0, 1, 1)))
        al.addWidget(self._row('规范检测', self._spin('loft.canonical_detection', 0, 2, 2)))
        self._advanced_toggle(gl, adv, 'loft')
        return wrap

    # ============================================================
    # 各 Tab 构建：参数区（滚动） + 独立执行栏
    # ============================================================
    def _build_sections_tab(self):
        return self._build_step_tab('sections', '① 构建截面',
                                     '点云 → 样条 + 光顺 + 平面 + 前尾缘 + 弦线',
                                     '▶  运行 ① 构建截面',
                                     self._build_sections_params())

    def _build_resample_tab(self):
        return self._build_step_tab('resample', '② 重采样光顺',
                                     '样条 → 等距重采样 + 光顺',
                                     '▶  运行 ② 重采样光顺',
                                     self._build_resample_params())

    def _build_loft_tab(self):
        return self._build_step_tab('loft', '③ 生成曲面',
                                     '多截面曲线 → 多截面曲面 Loft',
                                     '▶  运行 ③ 生成曲面',
                                     self._build_loft_params())

    def _build_step_tab(self, step_key, title, subtitle, run_text, params_widget):
        """通用单 Tab 构建：标题 + 参数区（滚动） + 独立执行栏。

        执行栏控件挂到 self._step_meta[step_key] = (run_btn, progress, log_area)。
        """
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(12, 10, 12, 8)
        v.setSpacing(8)

        # 标题 + 副标题
        v.addWidget(self._build_step_header(title, subtitle))

        # 参数区（可滚动）。用中间容器包裹：顶部参数区（Fixed，按内容定高）
        # + 底部 stretch 吸收多余空间，确保参数行始终顶对齐、折叠/展开时
        # 不被 ScrollArea 的 widgetResizable 拉伸导致位置乱动。
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll_container = QWidget()
        sc_layout = QVBoxLayout(scroll_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(0)
        sc_layout.addWidget(params_widget)
        sc_layout.addStretch()
        scroll.setWidget(scroll_container)
        v.addWidget(scroll, 1)

        # 独立执行栏
        v.addWidget(self._build_step_exec_bar(step_key, run_text))
        return page

    def _build_step_header(self, title, subtitle):
        """Tab 内顶部标题区。"""
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(2)
        t = QLabel(title)
        f = QFont('YouSheBiaoTiHei', 13)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        t.setFont(f)
        t.setStyleSheet('color: #1e3a5f;')
        s = QLabel(subtitle)
        s.setStyleSheet('color: #6b7280; font-size: 11px;')
        wl.addWidget(t)
        wl.addWidget(s)
        return wrap

    def _build_step_exec_bar(self, step_key, run_text):
        """单步骤执行栏：运行按钮 + 打开目录 + 进度条 + 日志。

        结构对照 BaseWorkerPanel._build_exec_bar，但每个步骤独立一份。
        """
        wrap = QWidget()
        wrap.setObjectName('execBar')
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap.setMinimumHeight(self.EXEC_BAR_HEIGHT)

        bar = QHBoxLayout(wrap)
        bar.setContentsMargins(2, 8, 2, 2)
        bar.setSpacing(10)

        # 左侧：运行按钮 + 打开目录 + 进度条
        left_wrap = QWidget()
        left_wrap.setFixedWidth(320)
        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        run_btn = QPushButton(run_text)
        run_btn.setMinimumHeight(40)
        run_btn.setObjectName('primaryBtn')
        run_btn.setCursor(Qt.PointingHandCursor)
        run_btn.clicked.connect(lambda _, k=step_key: self._on_run(k))

        open_btn = QPushButton('📂  打开输出目录')
        open_btn.setObjectName('secondaryBtn')
        open_btn.setMinimumHeight(36)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(self._on_open_output)

        progress = QProgressBar()
        progress.setValue(0)
        progress.setTextVisible(True)

        left_layout.addWidget(run_btn)
        left_layout.addWidget(open_btn)
        left_layout.addWidget(progress)
        left_layout.addStretch()

        # 右侧：日志区
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

        # 挂引用，供运行时按步骤定位
        self._step_meta[step_key] = (run_btn, progress, log_area)
        return wrap

    # ============================================================
    # 参数读写（UI 控件 ↔ params_store）
    # ============================================================
    def _collect_ui_params(self):
        """从所有控件读值，组装成 params_store 格式的 dict。"""
        return {
            'sections': {
                'num_groups': self._param_widgets['sec.num_groups'].value(),
                'start_group': self._param_widgets['sec.start_group'].value(),
                'smooth_thresholds': [
                    self._param_widgets['sec.smooth_t1'].value(),
                    self._param_widgets['sec.smooth_t2'].value(),
                    self._param_widgets['sec.smooth_t3'].value(),
                    self._param_widgets['sec.smooth_t4'].value(),
                ],
                'points_per_section': self._param_widgets['sec.points_per_section'].value(),
                'le_point_num': self._param_widgets['sec.le_point_num'].value(),
                'te_point1_num': self._param_widgets['sec.te_point1_num'].value(),
                'te_point399_num': self._param_widgets['sec.te_point399_num'].value(),
                'tangency_threshold': self._param_widgets['sec.tangency_threshold'].value(),
                'correction_mode': self._param_widgets['sec.correction_mode'].value(),
                'spline_set': self._param_widgets['sec.spline_set'].text(),
                'smooth_set': self._param_widgets['sec.smooth_set'].text(),
                'plane_set': self._param_widgets['sec.plane_set'].text(),
                'edge_set': self._param_widgets['sec.edge_set'].text(),
                'te_set': self._param_widgets['sec.te_set'].text(),
            },
            'resample': {
                'source_set': self._param_widgets['res.source_set'].text(),
                'num_points': self._param_widgets['res.num_points'].value(),
                'smooth_max_deviation': self._param_widgets['res.smooth_max_deviation'].value(),
                'tangency_threshold': self._param_widgets['res.tangency_threshold'].value(),
                'correction_mode': self._param_widgets['res.correction_mode'].value(),
                'point_set': self._param_widgets['res.point_set'].text(),
                'original_set': self._param_widgets['res.original_set'].text(),
                'smooth_set': self._param_widgets['res.smooth_set'].text(),
            },
            'loft': {
                'source_set': self._param_widgets['loft.source_set'].text(),
                'section_coupling': self._param_widgets['loft.section_coupling'].value(),
                'relimitation': self._param_widgets['loft.relimitation'].value(),
                'canonical_detection': self._param_widgets['loft.canonical_detection'].value(),
            },
            'input': {'stp_path': self._stp_edit.text()},
            'ui': {
                'advanced_expanded_sections': self._param_widgets['_advanced_sections'].isChecked(),
                'advanced_expanded_resample': self._param_widgets['_advanced_resample'].isChecked(),
                'advanced_expanded_loft': self._param_widgets['_advanced_loft'].isChecked(),
            },
        }

    def _load_params_to_ui(self):
        """从 params_store 回填到所有控件。"""
        p = load_params()
        s, r, l = p['sections'], p['resample'], p['loft']
        w = self._param_widgets
        w['sec.num_groups'].setValue(s['num_groups'])
        w['sec.start_group'].setValue(s['start_group'])
        t = s['smooth_thresholds']
        for k, v in zip(('t1', 't2', 't3', 't4'), t):
            w[f'sec.smooth_{k}'].setValue(v)
        w['sec.points_per_section'].setValue(s['points_per_section'])
        w['sec.le_point_num'].setValue(s['le_point_num'])
        w['sec.te_point1_num'].setValue(s['te_point1_num'])
        w['sec.te_point399_num'].setValue(s['te_point399_num'])
        w['sec.tangency_threshold'].setValue(s['tangency_threshold'])
        w['sec.correction_mode'].setValue(s['correction_mode'])
        w['sec.spline_set'].setText(s['spline_set'])
        w['sec.smooth_set'].setText(s['smooth_set'])
        w['sec.plane_set'].setText(s['plane_set'])
        w['sec.edge_set'].setText(s['edge_set'])
        w['sec.te_set'].setText(s['te_set'])
        w['res.source_set'].setText(r['source_set'])
        w['res.num_points'].setValue(r['num_points'])
        w['res.smooth_max_deviation'].setValue(r['smooth_max_deviation'])
        w['res.tangency_threshold'].setValue(r['tangency_threshold'])
        w['res.correction_mode'].setValue(r['correction_mode'])
        w['res.point_set'].setText(r['point_set'])
        w['res.original_set'].setText(r['original_set'])
        w['res.smooth_set'].setText(r['smooth_set'])
        w['loft.source_set'].setText(l['source_set'])
        w['loft.section_coupling'].setValue(l['section_coupling'])
        w['loft.relimitation'].setValue(l['relimitation'])
        w['loft.canonical_detection'].setValue(l['canonical_detection'])
        self._stp_edit.setText(p.get('input', {}).get('stp_path', ''))
        # 高级展开态
        adv = p.get('ui', {})
        w['_advanced_sections'].setChecked(adv.get('advanced_expanded_sections', False))
        w['_advanced_resample'].setChecked(adv.get('advanced_expanded_resample', False))
        w['_advanced_loft'].setChecked(adv.get('advanced_expanded_loft', False))

    # ============================================================
    # 运行编排（按 step_key 区分，每步独立 Worker + 日志）
    # ============================================================
    def _build_step_params(self, step):
        p = self._collect_ui_params()
        if step == 'sections':
            s = p['sections']
            return SectionParams(
                num_groups=s['num_groups'], start_group=s['start_group'],
                smooth_thresholds=tuple(s['smooth_thresholds']),
                points_per_section=s['points_per_section'],
                le_point_num=s['le_point_num'],
                te_point1_num=s['te_point1_num'],
                te_point399_num=s['te_point399_num'],
                tangency_threshold=s['tangency_threshold'],
                correction_mode=s['correction_mode'],
                spline_set=s['spline_set'], smooth_set=s['smooth_set'],
                plane_set=s['plane_set'], edge_set=s['edge_set'],
                te_set=s['te_set'],
            )
        if step == 'resample':
            r = p['resample']
            return ResampleParams(
                source_set=r['source_set'], num_points=r['num_points'],
                smooth_max_deviation=r['smooth_max_deviation'],
                tangency_threshold=r['tangency_threshold'],
                correction_mode=r['correction_mode'],
                point_set=r['point_set'], original_set=r['original_set'],
                smooth_set=r['smooth_set'],
            )
        l = p['loft']
        return LoftParams(
            source_set=l['source_set'], section_coupling=l['section_coupling'],
            relimitation=l['relimitation'], canonical_detection=l['canonical_detection'],
        )

    def _check_catia_available(self):
        """运行时探测 CATIA。可用返回 True，否则弹窗返回 False。"""
        try:
            import win32com.client
            app = win32com.client.GetActiveObject('CATIA.Application')
            return True
        except Exception:
            QMessageBox.warning(
                self, '未检测到 CATIA',
                '请先启动 CATIA 并打开零件文档（.CATPart），\n再点击运行。')
            return False

    def _on_run(self, step):
        """运行指定步骤。step 由各 tab 的运行按钮传入。"""
        run_btn, progress, log_area = self._step_meta[step]
        if self._workers[step] is not None and self._workers[step].isRunning():
            QMessageBox.information(self, '运行中', '该步骤仍在运行，请等待完成。')
            return
        if not self._check_catia_available():
            return
        try:
            params = self._build_step_params(step)
            params.validate()
        except ValueError as e:
            QMessageBox.warning(self, '参数错误', str(e))
            return
        # 存盘（记住上次值）
        save_params(self._collect_ui_params())
        # 清日志、启动 Worker
        log_area.clear()
        progress.setValue(0)
        step_label = dict((k, t) for k, t, _s, _r in _STEPS)[step]
        log_area.append(f'▶ 开始: {step_label}')
        worker = CatiaModelingWorker(step, params)
        self._workers[step] = worker
        # 信号连到本步骤的进度/日志/完成槽（用 lambda 绑定 step 与对应控件）
        worker.progress.connect(
            lambda pct, msg, p=progress, la=log_area: self._on_step_progress(pct, msg, p, la))
        worker.log_msg.connect(
            lambda msg, la=log_area: self._on_step_log(msg, la))
        worker.finished_ok.connect(
            lambda summary, k=step, rb=run_btn: self._on_step_finished_ok(summary, k, rb))
        worker.finished_err.connect(
            lambda err, k=step, rb=run_btn: self._on_step_finished_err(err, k, rb))
        run_btn.setEnabled(False)
        worker.start()

    def _on_step_progress(self, pct, msg, progress, log_area):
        """单步骤进度槽：更新该步骤进度条 + 追加日志。"""
        progress.setValue(int(pct))
        if msg:
            log_area.append(msg)
            log_area.verticalScrollBar().setValue(
                log_area.verticalScrollBar().maximum())

    def _on_step_log(self, msg, log_area):
        """单步骤纯日志槽。"""
        log_area.append(msg)
        log_area.verticalScrollBar().setValue(
            log_area.verticalScrollBar().maximum())

    def _on_step_finished_ok(self, summary, step, run_btn):
        run_btn.setEnabled(True)
        _run_btn, progress, log_area = self._step_meta[step]
        log_area.append(f'✓ {summary}')
        log_area.verticalScrollBar().setValue(
            log_area.verticalScrollBar().maximum())
        QMessageBox.information(self, '完成', summary)

    def _on_step_finished_err(self, err, step, run_btn):
        run_btn.setEnabled(True)
        _run_btn, progress, log_area = self._step_meta[step]
        log_area.append(f'✗ {err}')
        log_area.verticalScrollBar().setValue(
            log_area.verticalScrollBar().maximum())
        QMessageBox.critical(self, '失败', err)

    # 打开输出目录（基类 BaseModulePanel 提供 out_dir；这里实现，三个 tab 共用）
    def _on_open_output(self):
        if not self.out_dir:
            return
        try:
            if os.name == 'nt':
                os.startfile(self.out_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self.out_dir])
            else:
                subprocess.Popen(['xdg-open', self.out_dir])
        except OSError as e:
            QMessageBox.warning(self, '打开失败', str(e))
