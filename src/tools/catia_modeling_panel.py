# -*- coding: utf-8 -*-
"""CATIA 叶片建模 面板。

侧边栏独立工具。三个步骤 GroupBox（核心参数直露 + 高级折叠），
步骤选择 RadioButton + 运行按钮，复用 BaseWorkerPanel 的执行栏。

运行时检测 CATIA: 点运行先 try 连接，失败弹窗引导，不进入 Worker。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QCheckBox, QRadioButton, QButtonGroup, QFileDialog, QMessageBox,
    QScrollArea,
)

from tools.base_module_panel import BaseWorkerPanel
from catia_modeling import (
    SectionParams, ResampleParams, LoftParams,
    load_params, save_params, CatiaModelError,
)
from catia_modeling.worker import CatiaModelingWorker


class CatiaModelingPanel(BaseWorkerPanel):
    MODULE_ID = 'catia_modeling'
    DEFAULT_INPUT_SUBDIR = 'catia_modeling/input'
    DEFAULT_OUTPUT_SUBDIR = 'catia_modeling/output'
    MODULE_TITLE = 'CATIA 叶片建模'
    MODULE_SUBTITLE = 'C A T I A   B L A D E   M O D E L I N G'
    RUN_BUTTON_TEXT = '▶  运行当前步'
    EXEC_BAR_HEIGHT = 160

    def __init__(self):
        self._param_widgets = {}  # key -> widget，运行时读值
        self._step_radios = {}
        super().__init__()
        self._load_params_to_ui()   # 回填持久化参数
        self._wire_signals()

    # BaseWorkerPanel 要求实现
    def _build_main_content(self):
        """主体: 输入区 + 三个步骤 GroupBox + 步骤选择运行区，外层用滚动区包裹。"""
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(12)

        cl.addWidget(self._build_input_area())
        cl.addWidget(self._build_section_group())    # ①
        cl.addWidget(self._build_resample_group())   # ②
        cl.addWidget(self._build_loft_group())       # ③
        cl.addWidget(self._build_run_area())
        cl.addStretch()

        # 滚动区包裹（参数多，小屏可滚）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QScrollArea.NoFrame)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(scroll)
        return wrap

    # ------------------------------------------------------------
    # 输入区 + 步骤选择运行区
    # ------------------------------------------------------------
    def _build_input_area(self):
        """STP 文件选择区（仅提示/记录，不传给 CATIA）。"""
        box = QGroupBox('输入文件')
        bl = QGridLayout(box)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.addWidget(QLabel('STP 点云:'), 0, 0)
        self._stp_edit = QLineEdit()
        self._stp_edit.setPlaceholderText(
            '默认指向叶片形状输出 STAGE-3 的 3D_points.stp')
        bl.addWidget(self._stp_edit, 0, 1)
        browse = QPushButton('…')
        browse.setFixedWidth(36)
        browse.clicked.connect(self._on_browse_stp)
        bl.addWidget(browse, 0, 2)
        tip = QLabel('提示: 请先在 CATIA 中手动导入此 STP，'
                     '点云需带 Sect{组}_{点} 命名')
        tip.setStyleSheet('color: #6b7280; font-size: 11px;')
        bl.addWidget(tip, 1, 0, 1, 3)
        return box

    def _on_browse_stp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 STP 点云文件', '', 'STEP 文件 (*.stp *.step)')
        if path:
            self._stp_edit.setText(path)

    def _build_run_area(self):
        """步骤选择 RadioButton + 运行按钮（运行按钮来自基类 exec_bar）。"""
        box = QGroupBox('运行')
        bl = QHBoxLayout(box)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.addWidget(QLabel('运行步骤:'))
        self._step_group = QButtonGroup(self)
        for key, label in [('sections', '① 构建截面'),
                           ('resample', '② 重采样光顺'),
                           ('loft', '③ 生成曲面')]:
            rb = QRadioButton(label)
            self._step_radios[key] = rb
            self._step_group.addButton(rb)
            bl.addWidget(rb)
        self._step_radios['sections'].setChecked(True)
        bl.addStretch()
        # 运行按钮由基类 _build_exec_bar 创建为 self.run_btn，这里连信号
        return box

    # ------------------------------------------------------------
    # 控件构建辅助
    # ------------------------------------------------------------
    def _spin(self, key, lo, hi, default, is_double=False):
        """创建并登记一个 SpinBox。"""
        if is_double:
            w = QDoubleSpinBox()
            w.setDecimals(3)
        else:
            w = QSpinBox()
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
        """生成 (QLabel, [widgets...]) 横排的 QHBoxLayout 容器。"""
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
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

    # ---- ① 构建截面 ----
    def _build_section_group(self):
        box = QGroupBox('① 构建截面  （点云 → 样条 + 光顺 + 平面 + 前尾缘 + 弦线）')
        gl = QVBoxLayout(box)
        gl.setContentsMargins(10, 8, 10, 8)
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
        return box

    # ---- ② 重采样光顺 ----
    def _build_resample_group(self):
        box = QGroupBox('② 重采样光顺  （样条 → 等距重采样 + 光顺）')
        gl = QVBoxLayout(box)
        gl.setContentsMargins(10, 8, 10, 8)
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
        return box

    # ---- ③ 生成曲面 ----
    def _build_loft_group(self):
        box = QGroupBox('③ 生成曲面  （多截面曲线 → 多截面曲面 Loft）')
        gl = QVBoxLayout(box)
        gl.setContentsMargins(10, 8, 10, 8)
        gl.addWidget(self._row('源曲线集', self._line('loft.source_set', 'Z_ResampleSmooth')))
        gl.addWidget(self._row('截面耦合方式', self._spin('loft.section_coupling', 0, 2, 1)))
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._row('重新限定', self._spin('loft.relimitation', 0, 1, 1)))
        al.addWidget(self._row('规范检测', self._spin('loft.canonical_detection', 0, 2, 2)))
        self._advanced_toggle(gl, adv, 'loft')
        return box

    # ------------------------------------------------------------
    # 信号连接
    # ------------------------------------------------------------
    def _wire_signals(self):
        self.run_btn.clicked.connect(self._on_run)
        self._worker = None

    # ------------------------------------------------------------
    # 参数读写（UI 控件 ↔ params_store）
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # 运行编排
    # ------------------------------------------------------------
    def _current_step(self):
        for key, rb in self._step_radios.items():
            if rb.isChecked():
                return key
        return 'sections'

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

    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, '运行中', '上一步仍在运行，请等待完成。')
            return
        if not self._check_catia_available():
            return
        step = self._current_step()
        try:
            params = self._build_step_params(step)
            params.validate()
        except ValueError as e:
            QMessageBox.warning(self, '参数错误', str(e))
            return
        # 存盘（记住上次值）
        save_params(self._collect_ui_params())
        # 清日志、启动 Worker
        self.log_area.clear()
        self.progress.setValue(0)
        step_label = {'sections': '① 构建截面',
                      'resample': '② 重采样光顺',
                      'loft': '③ 生成曲面'}[step]
        self._on_log(f'▶ 开始: {step_label}')
        self._worker = CatiaModelingWorker(step, params)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_msg.connect(self._on_log)
        self._worker.finished_ok.connect(self._on_finished_ok)
        self._worker.finished_err.connect(self._on_finished_err)
        self.run_btn.setEnabled(False)
        self._worker.start()

    def _on_finished_ok(self, summary):
        self.run_btn.setEnabled(True)
        self._on_log(f'✓ {summary}')
        QMessageBox.information(self, '完成', summary)

    def _on_finished_err(self, err):
        self.run_btn.setEnabled(True)
        self._on_log(f'✗ {err}')
        QMessageBox.critical(self, '失败', err)
