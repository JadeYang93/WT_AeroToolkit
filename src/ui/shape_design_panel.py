# -*- coding: utf-8 -*-
"""叶片形状输出面板（QWidget 子类）。

三阶段流水线（沿用原 tkinter GUI 的 Notebook 结构，改用 QTabWidget）：
  - STAGE-1：AppData + GEO → XFOIL 批量计算 → 基准翼型
  - STAGE-2：TE 修正，余弦平滑过渡改写 GEO_for_correction.xlsx 的 TEth 列
  - STAGE-3：基于修正输入，spapi 样条拟合 → 最终叶片几何

XFOIL 路径固定 src/_bin/xfoil.exe（不走 ConfigCenter）；
输入/输出路径走 ConfigCenter（默认 输入数据/shape_design/、输出/shape_design/）。
"""
import os
import re
import sys
import traceback
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFileDialog, QCheckBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox,
    QLineEdit, QTabWidget, QRadioButton, QButtonGroup,
    QScrollArea, QFrame, QSizePolicy, QDialog,
    QComboBox,
)

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

# 重要：导入 plotting 会触发 matplotlib.use('Agg') + 中文字体配置，
# FigureCanvasQTAgg 直接用 Figure 实例即可继承字体设置，不受 Agg 影响
import core.plotting as plotting  # noqa: F401

from global_config import config_center
from config import PROJECT_ROOT, SRC_DIR

from business.shape_design import (
    ShapeDesignOptions,
    build_shape_design,
    export_shape_design,
    prepare_correction_inputs,
    apply_te_correction,
    apply_pchip_te_continuity,
    run_airfoil_correction,
    build_result_from_corrected_files,
    load_shape_design_input,
    load_airfoil_profiles,
)


# XFOIL 固定路径：src/_bin/xfoil.exe（不走 ConfigCenter）
# SRC_DIR / PROJECT_ROOT 由 config.py 统一定义，避免数层数反推
DEFAULT_XFOIL = Path(SRC_DIR) / '_bin' / 'xfoil.exe'

# 图示意图资源目录（app-bundled 静态图）
DIAGRAMS_DIR = Path(PROJECT_ROOT) / '配置' / 'diagrams'


# ============================================================
# Worker 线程
# ============================================================

class Stage1Worker(QThread):
    """STAGE-1：AppData + GEO → build_shape_design → export + prepare correction."""
    progress = pyqtSignal(int, str)

    def __init__(self, appdata, geo_path, profile_dir, stage1_output):
        super().__init__()
        self.appdata = appdata
        self.geo_path = geo_path
        self.profile_dir = profile_dir
        self.stage1_output = stage1_output
        self.result = None

    def run(self):
        try:
            self._log(5, '加载输入数据...')
            if self.profile_dir:
                base = load_shape_design_input(self.appdata, self.geo_path, profile_family=None)
                data = type(base)(
                    geo=base.geo,
                    profiles=load_airfoil_profiles(self.profile_dir),
                    sections=base.sections,
                    tail_table=base.tail_table,
                )
            else:
                data = load_shape_design_input(self.appdata, self.geo_path, profile_family=None)
            self._log(30, '计算外形输出...')
            options = ShapeDesignOptions(
                export_airfoil_points=True,
                export_3d_points=True,
                export_geometry=True,
                export_tail=True,
                export_focus=False,
                export_step_points=False,
            )
            result = build_shape_design(data, options)
            self._log(60, '导出文件...')
            # 用户可见 3 个文件写到 stage1/，中间产物写到 stage1/_internal/ 隐藏
            # 实际做法：所有 export_shape_design 输出 + prepare_correction_inputs
            # 都先写到 _internal/，再把 3 个可见文件复制到 stage1/ 顶层
            import shutil
            visible_dir = Path(self.stage1_output)
            internal_dir = visible_dir / '_internal'
            internal_dir.mkdir(parents=True, exist_ok=True)
            written_internal = export_shape_design(result, internal_dir, options, layout='flat')
            # 准备修正输入：geo 和 airfoil 都写到 _internal/
            correction_inputs = prepare_correction_inputs(
                internal_dir, internal_dir, baseline_dir=internal_dir,
            )
            # 复制 3 个用户可见文件到 stage1/
            visible_names = (
                'standard_airfoil_points.xlsx',
                'trailing_edge_thickness.xlsx',
                'GEO_for_correction.xlsx',
            )
            written = {}
            for key, src_path in written_internal.items():
                src_path = Path(src_path)
                if src_path.name in visible_names:
                    dst = visible_dir / src_path.name
                    shutil.copy2(src_path, dst)
                    written[key] = dst
                else:
                    written[key] = src_path
            # GEO_for_correction 是 prepare_correction_inputs 生成的（不在 written_internal 里）
            geo_src = Path(correction_inputs['geo'])
            if geo_src.name == 'GEO_for_correction.xlsx':
                geo_dst = visible_dir / geo_src.name
                shutil.copy2(geo_src, geo_dst)
                correction_inputs['geo'] = geo_dst

            self._log(100, '=== STAGE-1 完成 ===')
            for key, p in written.items():
                self._log(100, f'  {key}: {p}')
            self._log(100, f"  修正 GEO: {correction_inputs['geo']}")
            self._log(100, f"  修正翼型: {correction_inputs['airfoil']}")
            self.result = {
                'result': result,
                'written': written,
                'correction_inputs': correction_inputs,
            }
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    def _log(self, p, m):
        self.progress.emit(p, m)


class TECorrectionWorker(QThread):
    """STAGE-2 TE 修正：可选 PCHIP 连续性前置 + apply_te_correction 余弦过渡。"""
    progress = pyqtSignal(int, str)

    def __init__(self, geo_xlsx, tail_table_path, corr_start, corr_thickness, tip_thickness, fair_start,
                 baseline_te_path=None, enable_pchip=True,
                 th_range=(30.0, 50.0), exclude_range=(39.0, 41.0)):
        super().__init__()
        self.geo_xlsx = geo_xlsx
        self.tail_table_path = tail_table_path
        self.corr_start = corr_start
        self.corr_thickness = corr_thickness
        self.tip_thickness = tip_thickness
        self.fair_start = fair_start
        self.baseline_te_path = baseline_te_path
        self.enable_pchip = enable_pchip
        self.th_range = th_range
        self.exclude_range = exclude_range
        self.result = None

    def run(self):
        try:
            # ----- 步骤 1（可选）：PCHIP 连续性前置修正 -----
            if self.enable_pchip:
                th_lo, th_hi = sorted(self.th_range)
                ex_lo, ex_hi = sorted(self.exclude_range)
                self._log(
                    10,
                    f'执行 PCHIP 连续性修正（前置：构造 Th%∈[{th_lo},{th_hi}]，剔除 [{ex_lo},{ex_hi}]）...'
                )
                pchip_res = apply_pchip_te_continuity(
                    geo_xlsx=self.geo_xlsx,
                    th_range=self.th_range,
                    exclude_range=self.exclude_range,
                    baseline_te_path=self.baseline_te_path,
                )
                status = pchip_res.get('status', 'skipped')
                n_mod = len(pchip_res.get('modified_indices', []))
                if status == 'ok':
                    self._log(30, f'  PCHIP 完成：{n_mod} 个截面 TEth 已重算（Th%∈[{ex_lo},{ex_hi}]）')
                elif status == 'partial':
                    self._log(30, f'  PCHIP 部分修正：{n_mod} 个截面已重算；{pchip_res.get("reason", "")}')
                else:
                    self._log(30, f'  PCHIP 跳过：{pchip_res.get("reason", "")}')
                self._pchip_result = pchip_res
            else:
                self._pchip_result = None

            # ----- 步骤 2：apply_te_correction 余弦过渡 -----
            self._log(50, '执行 apply_te_correction（余弦过渡）...')
            res = apply_te_correction(
                geo_xlsx=self.geo_xlsx,
                corr_start=self.corr_start,
                corr_thickness=self.corr_thickness,
                tip_thickness=self.tip_thickness,
                fair_start=self.fair_start,
                tail_table_path=self.tail_table_path,
                baseline_te_path=self.baseline_te_path,
            )
            self._log(100, '=== STAGE-2 完成 ===')
            r = float(res['blade_radius'])
            self._log(100, f"  GEO: {res['geo']}")
            self._log(100, f'  叶片半径 R = {r:.2f} m')
            self._log(100, f'  p1={self.corr_start:.3f} → span={self.corr_start * r:.2f} m')
            self._log(100, f'  p4={self.fair_start:.3f} → span={self.fair_start * r:.2f} m')
            if self._pchip_result is not None:
                res['pchip'] = self._pchip_result
            self.result = res
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    def _log(self, p, m):
        self.progress.emit(p, m)


class Stage2Worker(QThread):
    """STAGE-3：XFOIL 修正 → 重建外形 → 导出最终文件。"""
    progress = pyqtSignal(int, str)

    # 消息文本中的 "idx/total" 用以在该阶段内插值百分比。
    # 注意：要求斜杠前必须是空格，避免误匹配阶段标识 "[1/3 准备]" 里的 "1/3"。
    _PROGRESS_RE = re.compile(r' (\d+)\s*/\s*(\d+)')

    def __init__(self, correction_geo, correction_airfoil, xfoil_outdir,
                 final_output, xfoil_mode, xfoil_exe, export_flags,
                 xfoil_cfg=None):
        super().__init__()
        self.correction_geo = correction_geo
        self.correction_airfoil = correction_airfoil
        self.xfoil_outdir = xfoil_outdir
        self.final_output = final_output
        self.xfoil_mode = xfoil_mode   # 'run' / 'skip' / 'debug'
        self.xfoil_exe = xfoil_exe
        self.export_flags = export_flags
        # XFOIL 配置：对应 run_airfoil_correction 的阈值 / 开关
        # xfoil_cfg = {
        #   'th_threshold_tail': float,  # Th% < 此值时做 TGAP（默认 60）
        #   'th_threshold_thick': float, # Th% > 此值时做 TSET（默认 40）
        #   'enable_tgap': bool,         # 是否按尾缘厚度修正
        #   'enable_tset': bool,         # 是否修正相对厚度
        # }
        self.xfoil_cfg = xfoil_cfg or {}
        self.result = None

    def run(self):
        try:
            mode = self.xfoil_mode
            # ----- 阶段 A：XFOIL 修正 (5% → 55%) -----
            # 三个子段（消息前缀）：
            #   [1/3 准备]   5  - 15  按 idx/total 插值
            #   [2/3 XFOIL]  15 - 40  开始/结束各 emit 一次，中间 subprocess.run 阻塞
            #   [3/3 修正]   40 - 55  按 idx/total 插值
            if mode == 'skip':
                corrected_airfoil = self.correction_airfoil
                self._log(5, '已跳过 XFOIL，直接用当前修正翼型输入重建。')
            else:
                if not Path(self.xfoil_exe).exists():
                    raise FileNotFoundError(f'未找到 XFOIL：{self.xfoil_exe}')
                self._log(5, '运行 XFOIL 修正...')
                corrected = run_airfoil_correction(
                    geo_xlsx=self.correction_geo,
                    airfoil_xlsx=self.correction_airfoil,
                    outdir=self.xfoil_outdir,
                    xfoil_exe=self.xfoil_exe,
                    enable_tgap=self.xfoil_cfg.get('enable_tgap', True),
                    enable_tset=self.xfoil_cfg.get('enable_tset', True),
                    th_threshold_tail=self.xfoil_cfg.get('th_threshold_tail', 60.0),
                    th_threshold_thick=self.xfoil_cfg.get('th_threshold_thick', 40.0),
                    keep_workdir=(mode == 'debug'),
                    progress_callback=self._make_corr_cb(),
                )
                corrected_airfoil = corrected['corrected_airfoil']
                self._log(55, f'修正后翼型点云: {corrected_airfoil}')
                if mode == 'debug':
                    self._log(55, '（调试模式）XFOIL 临时文件已保留。')

            # ----- 阶段 B：重建 3D 外形 (55% → 80%) -----
            result = build_result_from_corrected_files(
                geo_xlsx=self.correction_geo,
                corrected_airfoil_xlsx=corrected_airfoil,
                used_2d_path=Path(self.xfoil_outdir) / 'StdAirfoil_used_2D.xlsx',
                progress_callback=self._make_rebuild_cb(),
            )
            options = ShapeDesignOptions(**self.export_flags)

            # ----- 阶段 C：导出 (80% → 100%) -----
            written = export_shape_design(
                result, self.final_output, options,
                progress_callback=self._make_export_cb(),
            )

            self._log(100, '=== STAGE-3 完成 ===')
            for key, p in written.items():
                self._log(100, f'  {key}: {p}')
            self.result = {'result': result, 'written': written}
        except Exception:
            err = traceback.format_exc()
            self._log(100, f'[错误] {err}')
            self.result = {'error': err}

    # ----- 回调工厂：把业务函数的 message 映射到 0-100 区间 -----
    def _make_corr_cb(self):
        """run_airfoil_correction 回调。按消息前缀分派子阶段百分比。"""
        def cb(msg):
            if '[1/3' in msg:
                self._emit_in_phase(5, 15, msg)
            elif '[2/3 XFOIL] 启动' in msg:
                self._log(15, msg)
            elif '[2/3 XFOIL] 子进程退出' in msg:
                self._log(40, msg)
            elif '[3/3' in msg:
                self._emit_in_phase(40, 55, msg)
            else:
                # 共 N 个截面 / 其他提示性消息 → 5% 占位
                self._log(5, msg)
        return cb

    def _make_rebuild_cb(self):
        """build_result_from_corrected_files 回调（55% → 80%）。"""
        def cb(msg):
            if '[重建]' in msg:
                self._emit_in_phase(55, 78, msg)
            elif '完成' in msg:
                self._log(80, msg)
            else:
                self._log(55, msg)
        return cb

    def _make_export_cb(self):
        """export_shape_design 回调（80% → 100%）。按已见文件数线性插值。"""
        state = {'count': 0}
        def cb(msg):
            state['count'] += 1
            # 预计最多 6 个文件，每个文件约 +3%，最后到达 100 由完成行覆盖
            pct = min(97, 80 + state['count'] * 3)
            self._log(pct, msg)
        return cb

    def _emit_in_phase(self, base, end, msg):
        """从 msg 里解析 'idx/total'，把 base→end 按比例插值后 emit。"""
        m = self._PROGRESS_RE.search(msg)
        if m:
            idx = int(m.group(1))
            total = max(1, int(m.group(2)))
            pct = base + int((end - base) * min(idx, total) / total)
        else:
            pct = base
        self._log(pct, msg)

    def _log(self, p, m):
        self.progress.emit(p, m)


# ============================================================
# 预览对话框
# ============================================================

class BladeDistributionDialog(QDialog):
    """STAGE-1 叶片参数沿展向分布（多页：弦长/扭角/厚度等）。"""

    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle('STAGE-1：叶片参数分布')
        self.resize(920, 640)
        self.result = result
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        sampled = np.asarray(self.result.sampled_geo, dtype=float)
        span = sampled[:, 0]
        chord = sampled[:, 1]
        twist = sampled[:, 2]
        th_pct = sampled[:, 3]
        pitch = sampled[:, 4]
        preb = sampled[:, 5]
        sweep_arr = (np.zeros_like(span) if self.result.sweep is None
                     else np.asarray(self.result.sweep, dtype=float))
        abs_thick = chord * th_pct / 100.0
        le = sweep_arr - chord * pitch / 100.0
        te = sweep_arr + chord * (1.0 - pitch / 100.0)

        single = [
            ('弦长 chord', chord, '#1d4ed8', 'chord (m)'),
            ('扭角 twist', twist, '#b91c1c', 'twist (deg)'),
            ('绝对厚度', abs_thick, '#0f766e', 'thickness (m)'),
            ('相对厚度', th_pct, '#7c3aed', 'th (%)'),
            ('预弯 prebend', preb, '#9333ea', 'prebend (m)'),
            ('后掠 sweep', sweep_arr, '#0891b2', 'sweep (m)'),
        ]
        for title, y, color, ylabel in single:
            fig = Figure(figsize=(8.6, 5.0))
            ax = fig.add_subplot(111)
            ax.plot(span, y, color=color, linewidth=2)
            ax.set_xlabel('span (m)')
            ax.set_ylabel(ylabel)
            ax.set_title(title)
            ax.grid(True, alpha=0.3)
            fig.tight_layout()
            canvas = FigureCanvas(fig)
            page = QWidget()
            pv = QVBoxLayout(page)
            pv.setContentsMargins(0, 0, 0, 0)
            pv.addWidget(canvas)
            tabs.addTab(page, f'  {title}  ')

        # 前后缘分布
        fig_le = Figure(figsize=(8.6, 5.0))
        ax_le = fig_le.add_subplot(111)
        ax_le.plot(span, le, color='#1d4ed8', linewidth=2, label='前缘 LE')
        ax_le.plot(span, te, color='#b91c1c', linewidth=2, label='尾缘 TE')
        ax_le.fill_between(span, le, te, color='#94a3b8', alpha=0.25, label='叶片弦向范围')
        ax_le.set_xlabel('span (m)')
        ax_le.set_ylabel('弦向位置 X (m)')
        ax_le.set_title('前后缘沿展向分布（含后掠）')
        ax_le.grid(True, alpha=0.3)
        ax_le.legend(loc='best')
        fig_le.tight_layout()
        canvas_le = FigureCanvas(fig_le)
        page_le = QWidget()
        pv = QVBoxLayout(page_le)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(canvas_le)
        tabs.addTab(page_le, '  前后缘 LE / TE  ')


class TEComparisonDialog(QDialog):
    """STAGE-2 TE 修正前后对比（双 Tab）。

    Tab 1 叶尖段：toPS/toSS vs span（sections ≥ 0.5R）— 检查余弦过渡的视觉效果
    Tab 2 中段：TEth vs Th%（30~60%）— 检查 PCHIP 修正 + 标注剔除区
    """

    def __init__(self, compare_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle('STAGE-2 TE 修正前后对比')
        self.resize(1000, 680)
        self.data = compare_data
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ---- Tab 1: 叶尖段沿展向对比 ----
        tab1 = QWidget()
        tab1_lay = QVBoxLayout(tab1)
        tab1_lay.setContentsMargins(0, 0, 0, 0)
        fig1, ok1 = self._build_tip_figure(self.data)
        if ok1:
            canvas1 = FigureCanvas(fig1)
            tab1_lay.addWidget(NavigationToolbar(canvas1, tab1))
            tab1_lay.addWidget(canvas1)
            tabs.addTab(tab1, '叶尖段（span/R）')
        else:
            tab1_lay.addWidget(QLabel('叶尖段无数据可显示'))

        # ---- Tab 2: 中段沿相对厚度对比 ----
        tab2 = QWidget()
        tab2_lay = QVBoxLayout(tab2)
        tab2_lay.setContentsMargins(0, 0, 0, 0)
        fig2, ok2 = self._build_thickness_figure(self.data)
        if ok2:
            canvas2 = FigureCanvas(fig2)
            tab2_lay.addWidget(NavigationToolbar(canvas2, tab2))
            tab2_lay.addWidget(canvas2)
            tabs.addTab(tab2, '中段（Th% 60→30）')
        else:
            tab2_lay.addWidget(QLabel('中段无数据可显示（GEO 缺 Th% 列或无 30~60% 范围截面）'))

    def _build_tip_figure(self, r):
        """叶尖段：toPS/toSS vs span（sections ≥ 0.5R）。返回 (Figure, ok)。"""
        sections = np.asarray(r.get('sections', []), dtype=float)
        if sections.size == 0:
            return None, False
        toPS_b = np.asarray(r.get('toPS_before', []), dtype=float)
        toPS_a = np.asarray(r.get('toPS_after', []), dtype=float)
        toSS_b = np.asarray(r.get('toSS_before', []), dtype=float)
        toSS_a = np.asarray(r.get('toSS_after', []), dtype=float)

        r_blade = float(sections.max()) if sections.size else 100.0
        span_min = 0.5 * r_blade
        mask = sections >= span_min
        if not mask.any():
            return None, False

        fig = Figure(figsize=(9.4, 5.6))
        ax = fig.add_subplot(111)
        ax.plot(sections[mask], toPS_b[mask], color='#1d4ed8',
                linestyle='--', linewidth=1.5, label='toPS 修正前')
        ax.plot(sections[mask], toSS_b[mask], color='#b91c1c',
                linestyle='--', linewidth=1.5, label='toSS 修正前')
        ax.plot(sections[mask], toPS_a[mask], color='#1d4ed8',
                linestyle='-', linewidth=2.4, label='toPS 修正后')
        ax.plot(sections[mask], toSS_a[mask], color='#b91c1c',
                linestyle='-', linewidth=2.4, label='toSS 修正后')
        ax.set_xlabel('展向位置 span (m)')
        ax.set_ylabel('尾缘厚度 (mm)')
        ax.set_title(f'叶尖段 toPS / toSS 沿展向变化（{span_min:.1f} m → {r_blade:.1f} m）')
        ax.set_xlim(span_min, r_blade)
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best')
        fig.tight_layout()
        return fig, True

    def _build_thickness_figure(self, r):
        """中段：TEth vs 展向位置（m），仅展示 PCHIP 修正前后曲线 + 高亮剔除区。"""
        pchip = r.get('pchip')
        if pchip is None:
            return None, False
        sections = np.asarray(pchip.get('sections', []), dtype=float)
        th_pct = np.asarray(pchip.get('th_pct', []), dtype=float)
        te_b = np.asarray(pchip.get('te_before', []), dtype=float)
        te_a = np.asarray(pchip.get('te_after', []), dtype=float)
        if sections.size == 0 or np.all(np.isnan(sections)):
            return None, False

        # 取剔除区对应的展向范围用于高亮
        mod_idx = np.asarray(pchip.get('modified_indices', []), dtype=int)
        if mod_idx.size > 0:
            span_ex_lo = float(np.min(sections[mod_idx]))
            span_ex_hi = float(np.max(sections[mod_idx]))
        else:
            span_ex_lo, span_ex_hi = None, None

        # 可见范围：PCHIP 构造范围 Th%∈[30, 50] 对应的展向段
        th_lo, th_hi = 30.0, 50.0
        mask = (th_pct >= th_lo) & (th_pct <= th_hi) & ~np.isnan(sections)
        if not mask.any():
            return None, False

        # 按展向位置升序排序（叶根 → 叶尖）
        order = np.argsort(sections[mask])
        x = sections[mask][order]
        yb = te_b[mask][order]
        ya = te_a[mask][order]

        fig = Figure(figsize=(9.4, 5.6))
        ax = fig.add_subplot(111)

        # 高亮 PCHIP 剔除区（先画 axvspan，使其落在曲线下方）
        if span_ex_lo is not None and span_ex_hi is not None:
            ax.axvspan(span_ex_lo, span_ex_hi, alpha=0.12, color='#f59e0b',
                       label=f'PCHIP 剔除段 [{span_ex_lo:.2f}, {span_ex_hi:.2f}] m')

        ax.plot(x, yb, color='#6b7280', linestyle='--', linewidth=1.5,
                label='TEth 修正前（baseline）')
        ax.plot(x, ya, color='#0ea5e9', linestyle='-', linewidth=2.4,
                label='TEth 修正后（PCHIP 重算）')

        ax.set_xlabel('展向位置 (m)')
        ax.set_ylabel('后缘总厚度 TEth (mm)')
        ax.set_title(f'中段后缘厚度沿展向位置变化（Th% ∈ [{th_lo:.0f}, {th_hi:.0f}% 段）')
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best', fontsize=9)
        fig.tight_layout()
        return fig, True


# ============================================================
# CompactScrollArea（与 wind_farm_panel 同实现，避免跨模块导入 UI 控件耦合）
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

class ShapeDesignPanel(QWidget):
    MODULE_ID = 'shape_design'
    DEFAULT_INPUT_SUBDIR = 'shape_design'
    DEFAULT_OUTPUT_SUBDIR = 'shape_design'

    def __init__(self):
        super().__init__()
        config_center.register_module(
            self.MODULE_ID, self.DEFAULT_INPUT_SUBDIR, self.DEFAULT_OUTPUT_SUBDIR)
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        # 翼型库固定在 PROJECT_ROOT/配置/，不再走 extras（避免跨电脑绝对路径问题）
        self.appdata_dir = str(Path(PROJECT_ROOT) / '配置')
        self.xfoil_exe = str(DEFAULT_XFOIL)

        config_center.paths_changed.connect(self._on_paths_changed)

        # 暂存上一阶段结果（供预览 Dialog 用）
        self._stage1_result = None
        self._te_compare = None
        self._stage3_result = None
        # 三个 stage 的流水线状态：pending（未到达）/ completed（已成功跑过）
        # 用于 stepper 的视觉反馈，不强制顺序（用户可独立反复运行某个 stage）
        self._stage_states = {'stage1': 'pending', 'te': 'pending', 'stage2': 'pending'}

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
        # appdata_dir 固定为 PROJECT_ROOT/配置/，不随 extras 变
        if hasattr(self, 'stage1_output_edit'):
            self._sync_path_edits()

    def _sync_path_edits(self):
        """路径变更后把默认子目录同步到 UI（仅当编辑框为空或仍是旧 default 时）。"""
        defaults = self._default_paths()
        for edit, key in [
            (getattr(self, 'stage1_output_edit', None), 'stage1_output'),
            (getattr(self, 'correction_work_edit', None), 'correction_work'),
            (getattr(self, 'final_output_edit', None), 'final_output'),
        ]:
            if edit is None:
                continue
            cur = edit.text().strip()
            if not cur or cur == self._prev_default(key, cur):
                edit.setText(defaults[key])
        # te_geo 跟 stage1_output 联动
        if hasattr(self, 'te_geo_edit'):
            self.te_geo_edit.setText(defaults['te_geo'])
        # 路径变化后重新扫描下拉框
        self._on_scan_appdata(silent=True)

    def _prev_default(self, key, current):
        """简单判断：不维护历史，只接受空串或当前 default 才覆盖。
        返回 current 自身即可（配合上面的 == 比较）。"""
        return current

    def _default_paths(self):
        # appdata = 翼型库根目录（含 Aerofoil_coordinate/），固定 = PROJECT_ROOT/配置/
        appdata = Path(self.appdata_dir)
        return {
            'appdata': str(appdata),
            # GEO 文件直接放 input_dir（与翼型库分离）
            'blade_database': str(self.input_dir),
            'aerofoil_dir': str(appdata / 'Aerofoil_coordinate'),
            'stage1_output': str(Path(self.out_dir) / 'stage1'),
            'stage2_output': str(Path(self.out_dir) / 'stage2'),
            'correction_work': str(Path(self.out_dir) / '_internal' / 'xfoil_work'),
            'final_output': str(Path(self.out_dir) / 'stage3'),
            'te_geo': str(Path(self.out_dir) / 'stage2' / 'GEO_for_correction.xlsx'),
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
        title = QLabel('叶片形状输出')
        title.setObjectName('moduleTitle')
        title.setAlignment(Qt.AlignCenter)
        tf = QFont('YouSheBiaoTiHei', 16)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        title.setFont(tf)
        sub = QLabel('B L A D E   S H A P E   O U T P U T')
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

        # === 选项卡（页签隐藏，只保留内容区；切换由 stepper 唯一负责）===
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_stage1_tab(defaults), '  STAGE-1 - 基准翼型  ')
        self.tabs.addTab(self._build_te_tab(defaults), '  STAGE-2 - TE 修正  ')
        self.tabs.addTab(self._build_stage2_tab(defaults), '  STAGE-3 - 最终输出  ')
        # 隐藏 tab 页签条 — stepper 已经是唯一的阶段切换入口
        self.tabs.tabBar().setVisible(False)
        self.tabs.setStyleSheet('QTabWidget::pane { border: none; }')
        # tab 切换 → 同步 stepper 高亮
        self.tabs.currentChanged.connect(lambda _idx: self._update_stepper_state())
        outer.addWidget(self.tabs, 1)
        # stepper 视觉初始化（tabs 已建好，可安全读取 currentIndex）
        self._update_stepper_state()

    # ----- 流水线 Stepper -----
    # 顺序：STAGE-1（基准翼型）→ STAGE-2（TE 修正）→ STAGE-3（最终输出）
    # 对应 tab 索引：stage1=0, te=1, stage2=2
    _STEPPER_STEPS = (
        # (stage_key, tab_index, 编号文字, 阶段简称, stage 全称)
        ('stage1', 0, '1', '基准翼型', 'STAGE-1'),
        ('te', 1, '2', 'TE 修正', 'STAGE-2'),
        ('stage2', 2, '3', '最终输出', 'STAGE-3'),
    )

    def _build_stepper(self):
        """横向流水线 stepper：① 基准翼型 → ② TE 修正 → ③ 最终输出。

        状态语义（不强制顺序，用户可独立反复跑某个 stage）：
          - current   当前 tab 对应的节点（深钢蓝填充 + 白字 + 加粗）
          - completed 已成功跑过的 stage（气流青填充 + 白字 + ✓）
          - pending   未到达的 stage（浅灰底 + 深灰字）
        """
        wrap = QWidget()
        wrap.setObjectName('stepperBar')
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap.setFixedHeight(64)

        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(24, 12, 24, 12)
        layout.setSpacing(0)

        self._stepper_nodes = {}
        self._stepper_lines = []
        for i, (key, idx, num, label, full) in enumerate(self._STEPPER_STEPS):
            # 节点：圆形编号 + 阶段名（用 QPushButton 而不是 QWidget，方便点击切换）
            node = QPushButton(f'  {num}  {label}')
            node.setObjectName('stepperNode')
            node.setCursor(Qt.PointingHandCursor)
            node.setToolTip(f'{full} — 点击切到该阶段')
            node.setProperty('stageKey', key)
            node.clicked.connect(self._on_stepper_click)
            layout.addWidget(node, 1)
            self._stepper_nodes[key] = node

            # 连线（除最后一个节点外，每段后面一条横线）
            if i < len(self._STEPPER_STEPS) - 1:
                line = QFrame()
                line.setObjectName('stepperLine')
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                layout.addWidget(line, 1)
                self._stepper_lines.append(line)

        # 注意：此处不调用 _update_stepper_state()，
        # 因为 self.tabs 还没创建；交由 _build_ui 在 tabs 建好后调一次。
        return wrap

    def _on_stepper_click(self):
        """点击 stepper 节点 → 切到对应 tab。"""
        sender = self.sender()
        key = sender.property('stageKey')
        if key is None:
            return
        for stage_key, idx, _num, _label, _full in self._STEPPER_STEPS:
            if stage_key == key:
                self.tabs.setCurrentIndex(idx)
                return

    def _update_stepper_state(self):
        """根据当前 tab 刷新 stepper 视觉（二态：current=深钢蓝 / 其他=灰）。

        用 QSS property selector（[current=true]）切样式。
        """
        if not hasattr(self, '_stepper_nodes'):
            return
        current_idx = self.tabs.currentIndex()
        current_key = self._STEPPER_STEPS[current_idx][0]
        for key, _idx, _num, _label, _full in self._STEPPER_STEPS:
            node = self._stepper_nodes.get(key)
            if node is None:
                continue
            node.setProperty('current', 'true' if key == current_key else None)
            # 触发 QSS 重绘
            node.style().unpolish(node)
            node.style().polish(node)

    def _mark_stage_completed(self, key):
        """某 stage 跑成功后调用，更新状态 + 刷新 stepper。"""
        self._stage_states[key] = 'completed'
        self._update_stepper_state()

    # ----- Stage1 Tab -----
    def _build_stage1_tab(self, defaults):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # 输入配置
        box = QGroupBox('输入配置')
        box.setObjectName('gb_data')
        grid = QGridLayout(box)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)
        # 翼型库目录已固定为 PROJECT_ROOT/配置/，不再在 UI 显式给出
        # row0: GEO 文件下拉 + 浏览 + 刷新（GEO 直接放 输入数据/shape_design/ 根目录）
        grid.addWidget(QLabel('GEO 输入文件:'), 0, 0)
        self.geo_combo = QComboBox()
        self.geo_combo.setToolTip('选择 .geo 文件（来自 输入数据/shape_design/）')
        grid.addWidget(self.geo_combo, 0, 1)
        geo_browse = QPushButton('…')
        geo_browse.setMaximumWidth(28)
        geo_browse.setToolTip('浏览选择 .geo 文件（默认定位到 输入数据/shape_design/）')
        geo_browse.clicked.connect(self._on_browse_geo)
        grid.addWidget(geo_browse, 0, 2)
        geo_refresh = QPushButton('🔄')
        geo_refresh.setMaximumWidth(40)
        geo_refresh.setToolTip('重新扫描 输入数据/shape_design/，刷新本下拉框')
        geo_refresh.clicked.connect(self._on_refresh_geo)
        grid.addWidget(geo_refresh, 0, 3)
        # row1: 翼型库下拉 + 刷新（固定用 配置/Aerofoil_coordinate/，无浏览按钮）
        grid.addWidget(QLabel('翼型库:'), 1, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.setToolTip('选择翼型族（配置/Aerofoil_coordinate/ 下的子目录，翼型库根目录固定）')
        grid.addWidget(self.profile_combo, 1, 1)
        prof_refresh = QPushButton('🔄')
        prof_refresh.setMaximumWidth(40)
        prof_refresh.setToolTip('重新扫描 配置/Aerofoil_coordinate/，刷新本下拉框')
        prof_refresh.clicked.connect(self._on_refresh_profile)
        grid.addWidget(prof_refresh, 1, 3)
        # row2: STAGE-1 输出目录（隐藏 UI，路径走 ConfigCenter）
        self.stage1_output_edit = QLineEdit(defaults['stage1_output'])
        self.stage1_output_edit.setVisible(False)
        grid.addWidget(self.stage1_output_edit, 2, 1)
        grid.setColumnStretch(1, 1)
        v.addWidget(box)

        # 首次扫描填充下拉框
        self._on_scan_appdata(silent=True)

        # 说明
        info = QGroupBox('本阶段固定输出（stage1/ 顶层）')
        info_layout = QVBoxLayout(info)
        info_label = QLabel(
            '用户可见（stage1/）：\n'
            '  standard_airfoil_points.xlsx      归一化标准翼型点云\n'
            '  GEO_for_correction.xlsx           GEO 参数表（STAGE-2 TE 修正目标）\n'
            '  trailing_edge_thickness.xlsx      基础尾缘厚度表\n'
            '中间产物（stage1/_internal/，自动管理）：\n'
            '  blade_aero_geometry.xlsx / blade_3d_points.xlsx / standard_airfoil_for_correction.xlsx'
        )
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label)
        v.addWidget(info)

        # 弹簧在执行栏上方：内容少时把执行栏顶到底，保证三个 stage 底部对齐
        v.addStretch()
        # 执行栏
        v.addWidget(self._build_exec_bar(
            stage='stage1',
            run_text='运行 STAGE-1',
            run_slot=self._on_run_stage1,
            open_dir_getter=lambda: Path(self.stage1_output_edit.text()),
            extra_btns=[
                ('dist', '查看叶片参数分布', self._on_show_stage1_dist),
            ],
        ))
        return page

    # ----- TE Tab -----
    def _build_te_tab(self, defaults):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # 示意图（按需打开 → 不常驻主 UI，避免分辨率对齐问题）
        diagram_box = QGroupBox('TE 修正示意图')
        diagram_box.setObjectName('gb_data')
        diagram_layout = QHBoxLayout(diagram_box)
        diagram_layout.setContentsMargins(10, 8, 10, 8)
        diagram_btn = QPushButton('🖼  查看 TE 修正示意图')
        diagram_btn.clicked.connect(self._on_show_te_diagram)
        diagram_layout.addWidget(diagram_btn)
        diagram_layout.addStretch()
        v.addWidget(diagram_box)

        # 参数（占满宽度）
        params = QGroupBox('STAGE-2 TE 修正参数')
        params.setObjectName('gb_params')
        grid = QGridLayout(params)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setSpacing(6)
        self.te_corr_start_edit = QLineEdit('0.85')
        self.te_corr_thickness_edit = QLineEdit('4.0')
        self.te_tip_thickness_edit = QLineEdit('3.0')
        self.te_fair_start_edit = QLineEdit('0.80')
        # 4 个参数输入框限宽 200px：用户明确要求，不占满 GroupBox 整宽。
        # 高 DPI 下 Qt 会自动按系统缩放系数处理（AA_EnableHighDpiScaling）。
        for edit in (self.te_corr_start_edit, self.te_corr_thickness_edit,
                     self.te_tip_thickness_edit, self.te_fair_start_edit):
            edit.setMaximumWidth(200)
        grid.addWidget(QLabel('修正区起始 p1 (span/R):'), 0, 0)
        grid.addWidget(self.te_corr_start_edit, 0, 1)
        grid.addWidget(QLabel('修正区厚度 p2 (mm):'), 1, 0)
        grid.addWidget(self.te_corr_thickness_edit, 1, 1)
        grid.addWidget(QLabel('叶尖厚度 p3 (mm):'), 2, 0)
        grid.addWidget(self.te_tip_thickness_edit, 2, 1)
        grid.addWidget(QLabel('光顺过渡起始 p4 (span/R):'), 3, 0)
        grid.addWidget(self.te_fair_start_edit, 3, 1)
        # PCHIP 连续性修正（前置步骤）：勾选后 apply_te_correction 之前先跑一次 PCHIP
        self.cb_te_pchip = QCheckBox(
            '启用 PCHIP 连续性修正（前置：构造范围与剔除范围可在下方调整）'
        )
        self.cb_te_pchip.setChecked(True)
        self.cb_te_pchip.setToolTip(
            '在 apply_te_correction 之前，对 GEO 的 TEth 做 PCHIP 连续性修正：\n'
            '  • 在构造范围内收集基础数据\n'
            '  • 剔除剔除范围内的点（原始数据连续性不够的区段）\n'
            '  • 用剩余点构造 PCHIP 曲线，插值出剔除段的新 TEth\n'
            '  • 同时更新 baseline.npy 的剔除段，避免被后续余弦过渡覆盖\n'
            '其他区段（构造范围外、剔除范围外）的 TEth 保持原值不动。'
        )
        grid.addWidget(self.cb_te_pchip, 4, 0, 1, 3)
        # PCHIP 参数行：构造范围 + 剔除范围（4 个 QLineEdit）
        pchip_params = QWidget()
        pchip_layout = QHBoxLayout(pchip_params)
        pchip_layout.setContentsMargins(20, 2, 0, 2)
        pchip_layout.setSpacing(6)
        pchip_layout.addWidget(QLabel('构造范围 Th%:'))
        self.te_pchip_th_low = QLineEdit('30')
        self.te_pchip_th_low.setFixedWidth(50)
        pchip_layout.addWidget(self.te_pchip_th_low)
        pchip_layout.addWidget(QLabel('~'))
        self.te_pchip_th_high = QLineEdit('50')
        self.te_pchip_th_high.setFixedWidth(50)
        pchip_layout.addWidget(self.te_pchip_th_high)
        pchip_layout.addSpacing(16)
        pchip_layout.addWidget(QLabel('剔除范围 Th%:'))
        self.te_pchip_ex_low = QLineEdit('39')
        self.te_pchip_ex_low.setFixedWidth(50)
        pchip_layout.addWidget(self.te_pchip_ex_low)
        pchip_layout.addWidget(QLabel('~'))
        self.te_pchip_ex_high = QLineEdit('41')
        self.te_pchip_ex_high.setFixedWidth(50)
        pchip_layout.addWidget(self.te_pchip_ex_high)
        pchip_layout.addStretch(1)
        grid.addWidget(pchip_params, 5, 0, 1, 3)
        # col 1 不拉伸，col 2（空列）吸收多余宽度 → 输入框右侧留白
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)
        v.addWidget(params)

        # 改写目标（占满宽度，首次运行时从 stage1/ 复制到 stage2/）
        target = QGroupBox('STAGE-2 改写目标（stage2/GEO_for_correction.xlsx）')
        target_layout = QGridLayout(target)
        target_layout.setContentsMargins(10, 8, 10, 8)
        target_layout.addWidget(QLabel('GEO_for_correction.xlsx:'), 0, 0)
        self.te_geo_edit = QLineEdit(defaults['te_geo'])
        self.te_geo_edit.setReadOnly(True)
        target_layout.addWidget(self.te_geo_edit, 0, 1)
        target_layout.setColumnStretch(1, 1)
        v.addWidget(target)

        # 弹簧在执行栏上方：内容少时把执行栏顶到底
        v.addStretch()
        # 执行栏
        v.addWidget(self._build_exec_bar(
            stage='te',
            run_text='运行 STAGE-2',
            run_slot=self._on_run_te,
            open_dir_getter=lambda: Path(self.te_geo_edit.text()).parent,
            extra_btns=[
                ('compare', '查看 TE 对比曲线', self._on_show_te_compare),
            ],
        ))
        return page

    # ----- Stage2 Tab -----
    def _build_stage2_tab(self, defaults):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # 路径数据持有（不显示在 UI，仅供 _on_run_stage2 读取）
        self.correction_work_edit = QLineEdit(defaults['correction_work'], page)
        self.correction_work_edit.setVisible(False)
        self.final_output_edit = QLineEdit(defaults['final_output'], page)
        self.final_output_edit.setVisible(False)

        # 流程示意图（按需打开 → 不常驻主 UI）
        flow_box = QGroupBox('STAGE-3 流程示意图')
        flow_box.setObjectName('gb_data')
        flow_layout = QHBoxLayout(flow_box)
        flow_layout.setContentsMargins(10, 8, 10, 8)
        flow_btn = QPushButton('🖼  查看 STAGE-3 流程示意图')
        flow_btn.clicked.connect(self._on_show_stage3_diagram)
        flow_layout.addWidget(flow_btn)
        flow_layout.addStretch()
        v.addWidget(flow_box)

        # XFOIL 配置（用户可调的修正阈值与开关）
        # 对应 run_airfoil_correction() 的入参：
        #   th_threshold_tail → 仅 Th% < 此值的截面做尾缘厚度修正（默认 60）
        #   th_threshold_thick → 仅 Th% > 此值的截面做相对厚度修正（默认 40）
        #   enable_tgap → 是否按尾缘厚度修正（对应「按 STAGE-2 输出的尾缘厚度修正」）
        #   enable_tset → 是否修正相对厚度
        cfg_box = QGroupBox('XFOIL 配置')
        cfg_box.setObjectName('gb_data')
        cfg_grid = QGridLayout(cfg_box)
        cfg_grid.setContentsMargins(10, 8, 10, 8)
        cfg_grid.setSpacing(6)

        lbl_tail = QLabel('后缘厚度修正起始 Th%：')
        lbl_tail.setToolTip('仅 Th% < 此值的截面（靠近叶尖）做尾缘厚度修正。\n默认 60。')
        self.edit_th_tail = QLineEdit('60')
        self.edit_th_tail.setMaximumWidth(80)
        cfg_grid.addWidget(lbl_tail, 0, 0)
        cfg_grid.addWidget(self.edit_th_tail, 0, 1)

        lbl_thick = QLabel('相对厚度修正起始 Th%：')
        lbl_thick.setToolTip('仅 Th% > 此值的截面（靠近叶根）做相对厚度修正。\n默认 40。')
        self.edit_th_thick = QLineEdit('40')
        self.edit_th_thick.setMaximumWidth(80)
        cfg_grid.addWidget(lbl_thick, 1, 0)
        cfg_grid.addWidget(self.edit_th_thick, 1, 1)

        self.cb_enable_tgap = QCheckBox('按 STAGE-2 输出的尾缘厚度修正（TGAP）')
        self.cb_enable_tgap.setChecked(True)
        self.cb_enable_tgap.setToolTip('勾选：使用 STAGE-2 生成的尾缘厚度对翼型做尾缘间隙修正。\n不勾选：跳过尾缘厚度修正。')
        cfg_grid.addWidget(self.cb_enable_tgap, 0, 2, 1, 2)

        self.cb_enable_tset = QCheckBox('修正相对厚度（TSET）')
        self.cb_enable_tset.setChecked(True)
        self.cb_enable_tset.setToolTip('勾选：按几何参数表中的 Th% 修正翼型相对厚度。\n不勾选：跳过相对厚度修正。')
        cfg_grid.addWidget(self.cb_enable_tset, 1, 2, 1, 2)

        cfg_grid.setColumnStretch(3, 1)
        v.addWidget(cfg_box)

        # XFOIL 模式（固定完整运行，UI 不显示选择）
        self.xfoil_mode_group = QButtonGroup(self)
        self.rb_mode_run = QRadioButton('完整运行（修正 + 重建）')
        self.rb_mode_run.setChecked(True)
        self.xfoil_mode_group.addButton(self.rb_mode_run, 0)

        # 弹簧在执行栏上方：内容少时把执行栏顶到底
        v.addStretch()
        # 执行栏
        v.addWidget(self._build_exec_bar(
            stage='stage2',
            run_text='运行 STAGE-3',
            run_slot=self._on_run_stage2,
            open_dir_getter=lambda: Path(self.final_output_edit.text()),
            extra_btns=[
                ('dist', '查看最终叶片参数', self._on_show_stage3_dist),
            ],
        ))
        return page

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

    # ----- Stage1 扫描与下拉 -----
    def _on_scan_appdata(self, silent=False):
        """扫描 input_dir（GEO）+ 配置/Aerofoil_coordinate/（翼型库），
        刷新 GEO 文件下拉与翼型库下拉。

        silent=True 时不写日志（首次构建 / 路径变更联动用）。
        翼型库目录固定为 PROJECT_ROOT/配置/，不再从 UI 读取。
        """
        appdata = self.appdata_dir
        if not appdata or not Path(appdata).exists():
            if not silent:
                self._log('stage1', f'[扫描] ⚠ 翼型库目录不存在：{appdata}')
            n_prof = 0
        else:
            n_prof = self._scan_profile_combo(appdata)
        n_geo = self._scan_geo_combo()

        if not silent:
            self._log('stage1', f'[扫描] 翼型库：{appdata}')
            self._log('stage1', f'         GEO 目录：{self.input_dir}')
            self._log('stage1', f'  • GEO 文件：{n_geo} 个')
            self._log('stage1', f'  • 翼型族：{n_prof} 个')
        return n_geo, n_prof

    def _on_refresh_geo(self):
        """单独刷新 GEO 下拉（导入新 .geo 后用）。"""
        if not Path(self.input_dir).is_dir():
            QMessageBox.warning(self, '路径无效',
                                f'GEO 输入目录不存在：\n{self.input_dir}')
            return
        n = self._scan_geo_combo()
        self._log('stage1', f'[刷新] GEO 下拉：{n} 个 .geo 文件')

    def _on_refresh_profile(self):
        """单独刷新翼型库下拉（导入新翼型族后用）。"""
        appdata = self.appdata_dir
        if not appdata or not Path(appdata).exists():
            QMessageBox.warning(self, '路径无效',
                                f'翼型库目录不存在：\n{appdata}')
            return
        n = self._scan_profile_combo(appdata)
        self._log('stage1', f'[刷新] 翼型库下拉：{n} 个翼型族')

    def _scan_geo_combo(self):
        """扫描 input_dir 下的 .geo 文件，刷新 GEO 下拉。
        GEO 直接放在 输入数据/shape_design/ 根目录（不再嵌套 Blade_database/）。
        返回扫描到的 GEO 文件数。保留用户浏览过的外部项。
        """
        geo_files = []
        in_dir = Path(self.input_dir)
        if in_dir.is_dir():
            # 大小写不敏感：.geo / .GEO 都扫
            seen = set()
            for pattern in ('*.geo', '*.GEO'):
                for p in sorted(in_dir.glob(pattern)):
                    if p not in seen:
                        seen.add(p)
                        geo_files.append((p.name, str(p)))
        # 若下拉中已有用户浏览过的外部文件，保留
        prev_geo = self.geo_combo.currentData()
        self.geo_combo.clear()
        for name, path in geo_files:
            self.geo_combo.addItem(name, path)
        if prev_geo:
            idx = self.geo_combo.findData(prev_geo)
            if idx >= 0:
                self.geo_combo.setCurrentIndex(idx)
            else:
                # 之前选的文件不在扫描结果里 → 作为额外项保留
                self.geo_combo.addItem(Path(prev_geo).name + '  (外部)', prev_geo)
                self.geo_combo.setCurrentIndex(self.geo_combo.count() - 1)
        elif self.geo_combo.count() > 0:
            self.geo_combo.setCurrentIndex(0)
        return len(geo_files)

    def _scan_profile_combo(self, appdata):
        """扫描 Aerofoil_coordinate/，刷新翼型库下拉。
        返回扫描到的翼型族数。保留用户之前的选择；首次扫描默认选 WN919。
        """
        aerofoil_dir = Path(appdata) / 'Aerofoil_coordinate'
        profiles = []
        if aerofoil_dir.is_dir():
            for d in sorted(aerofoil_dir.iterdir()):
                if d.is_dir():
                    # 子目录里必须有 .prof 文件才算翼型族
                    has_prof = any(d.glob('*.prof'))
                    if has_prof:
                        profiles.append((d.name, str(d)))
        prev_prof = self.profile_combo.currentData()
        self.profile_combo.clear()
        for name, path in profiles:
            self.profile_combo.addItem(name, path)
        if prev_prof:
            # 保留用户之前的选择
            idx = self.profile_combo.findData(prev_prof)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
                return len(profiles)
        # 首次扫描：默认选 WN919（找不到则退到第一个）
        wn_idx = self.profile_combo.findText('WN919')
        if wn_idx >= 0:
            self.profile_combo.setCurrentIndex(wn_idx)
        elif self.profile_combo.count() > 0:
            self.profile_combo.setCurrentIndex(0)
        return len(profiles)

    def _on_browse_geo(self):
        """浏览选择 GEO 文件，加入下拉框。"""
        start = self.input_dir
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 GEO 文件', start, 'GEO 文件 (*.geo);;所有文件 (*)')
        if not path:
            return
        # 若已存在则选中，否则追加
        idx = self.geo_combo.findData(path)
        if idx < 0:
            self.geo_combo.addItem(Path(path).name + '  (外部)', path)
            idx = self.geo_combo.count() - 1
        self.geo_combo.setCurrentIndex(idx)

    def _on_browse_profile(self):
        """浏览选择翼型库文件夹，加入下拉框。"""
        start = self.input_dir
        path = QFileDialog.getExistingDirectory(self, '选择翼型库文件夹', start)
        if not path:
            return
        idx = self.profile_combo.findData(path)
        if idx < 0:
            self.profile_combo.addItem(Path(path).name + '  (外部)', path)
            idx = self.profile_combo.count() - 1
        self.profile_combo.setCurrentIndex(idx)

    # ----- 通用：执行栏 -----
    def _build_exec_bar(self, stage, run_text, run_slot, open_dir_getter, extra_btns=None):
        """构建底部执行栏（开始 + 打开目录 + 预览 + 进度 + 日志）。

        返回 QWidget（外层 Fixed 容器 + 最小高度 180），保证三个 stage 高度一致。
        对照 wind_farm_panel 的 bottom 容器实现。

        extra_btns 格式：[(key, label, slot), ...]
          - key   英文短标识，用于生成属性名 _extra_btn_{stage}_{key}
          - label 按钮显示文本（可含中文/空格）
          - slot  点击信号槽
        """
        wrap = QWidget()
        wrap.setObjectName('execBar')
        # Fixed 垂直策略 + 220px 固定高度（minHeight 只是下限会被 sizeHint 撑大，
        # 必须用 setFixedHeight 才能锁死；220 容纳左侧 4 个按钮 + 间距 + 进度条）
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
            # 用英文 key 拼属性名，避免中文/空格引发的命名错位
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

        # 挂引用
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
        """切换某个 Tab 的运行按钮状态（禁用/启用 + 文字切换）。"""
        run_btn = getattr(self, f'{stage}_run_btn')
        if running:
            # 首次进入运行时，缓存原始文字
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
    # Stage1 执行
    # ============================================================
    def _on_run_stage1(self):
        geo = self.geo_combo.currentData()
        if not geo:
            QMessageBox.warning(self, '缺少 GEO', '请先选择 GEO 输入文件。')
            return
        appdata = self.appdata_dir
        profile_dir = self.profile_combo.currentData() or ''
        if not profile_dir:
            QMessageBox.warning(self, '缺少翼型库',
                                '请先选择翼型库（配置/Aerofoil_coordinate/ 下的翼型族）。\n'
                                '若列表为空，点翼型库旁的 🔄 刷新。')
            return
        # 清空日志 + 进度
        self.stage1_log.clear()
        self.stage1_progress.setValue(0)
        self._set_running('stage1', True)
        self.stage1_open_btn.setEnabled(False)
        # 同步 TE Tab 的目标文件路径（STAGE-2 在 stage2/ 上改写）
        stage1_out = self.stage1_output_edit.text().strip()
        stage2_out = Path(stage1_out).parent / 'stage2'
        self.te_geo_edit.setText(str(stage2_out / 'GEO_for_correction.xlsx'))
        # 预览按钮初始禁用
        self._extra_btn_stage1_dist.setEnabled(False)

        self._log('stage1', f'输入: 翼型库={appdata}')
        self._log('stage1', f'      GEO={geo}')
        self._log('stage1', f'输出: {stage1_out}')
        self._log('stage1', f'      翼型库={profile_dir}')
        self._log('stage1', '---')

        self._stage1_worker = Stage1Worker(appdata, geo, profile_dir, stage1_out)
        self._stage1_worker.progress.connect(self._on_stage1_progress)
        self._stage1_worker.finished.connect(self._on_stage1_finished)
        self._stage1_worker.start()

    def _on_stage1_progress(self, percent, msg):
        self.stage1_progress.setValue(percent)
        self._log('stage1', msg)

    def _on_stage1_finished(self):
        self._set_running('stage1', False)
        res = self._stage1_worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'STAGE-1 出错', res['error'])
        else:
            self._stage1_result = res['result']
            self.stage1_open_btn.setEnabled(True)
            # 启用预览按钮
            self._extra_btn_stage1_dist.setEnabled(True)
            self._mark_stage_completed('stage1')
            # 同步 STAGE-2 工作模板：stage1/GEO → stage2/GEO（覆盖）
            self._sync_stage2_geo_from_stage1()

    def _sync_stage2_geo_from_stage1(self):
        """STAGE-1 完成后把 stage1/GEO_for_correction.xlsx 复制到 stage2/，覆盖已有版本。

        保证 STAGE-2 TE 修正永远基于最新的 STAGE-1 输出，避免老 stage2/GEO 残留导致
        截面数与 baseline/trailing_edge_thickness 错位（曾因此出现 171 vs 132 广播错误）。
        """
        import shutil
        try:
            stage1_out = Path(self.stage1_output_edit.text().strip())
        except (AttributeError, ValueError):
            return
        src = stage1_out / 'GEO_for_correction.xlsx'
        if not src.exists():
            return
        dst = stage1_out.parent / 'stage2' / 'GEO_for_correction.xlsx'
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except PermissionError as e:
            # 常见原因：stage2/GEO 被 Excel 或上一次 Python 进程占用（read_only 句柄泄漏）
            self._log('stage1', f'⚠ 同步 STAGE-2 GEO 失败（文件被占用，请关闭 Excel 后重跑 STAGE-1）：{e}')
            return
        self._log('stage1', f'已同步 GEO 模板到 STAGE-2：{dst}')

    def _on_show_stage1_dist(self):
        if self._stage1_result is None:
            QMessageBox.information(self, '无数据', '请先运行 STAGE-1。')
            return
        dlg = BladeDistributionDialog(self._stage1_result, self)
        dlg.exec_()

    def _on_show_stage3_dist(self):
        if self._stage3_result is None:
            QMessageBox.information(self, '无数据', '请先运行 STAGE-3。')
            return
        dlg = BladeDistributionDialog(self._stage3_result, self)
        dlg.exec_()

    def _on_show_stage3_diagram(self):
        """按需打开 STAGE-3 流程示意图（弹窗显示原始大图）。"""
        path = DIAGRAMS_DIR / 'stage3_flow_diagram.png'
        if not path.exists():
            QMessageBox.warning(self, '找不到示意图', f'文件不存在：\n{path}')
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            QMessageBox.warning(self, '加载失败', f'无法读取图像：\n{path}')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('STAGE-3 叶片形状输出流程示意图')
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel()
        screen_w = self.window().windowHandle().screen().size().width() if self.window().windowHandle() else 1920
        max_w = min(1400, int(screen_w * 0.8))
        if pix.width() > max_w:
            pix = pix.scaledToWidth(max_w, Qt.SmoothTransformation)
        label.setPixmap(pix)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        dlg.exec_()

    # ============================================================
    # TE 修正 执行
    # ============================================================
    def _on_run_te(self):
        import shutil
        geo_path = Path(self.te_geo_edit.text())  # 指向 stage2/GEO_for_correction.xlsx
        stage1_out = Path(self.stage1_output_edit.text().strip())
        stage1_geo = stage1_out / 'GEO_for_correction.xlsx'
        if not stage1_geo.exists():
            QMessageBox.warning(self, '找不到文件',
                                f'STAGE-1 未生成 GEO_for_correction.xlsx：\n{stage1_geo}\n请先运行 STAGE-1。')
            return
        # 首次运行 STAGE-2：从 stage1/ 复制一份干净模板到 stage2/，
        # 后续反复调参都在 stage2/ 上改写，保证 stage1/ 永远是 STAGE-1 原始产物。
        if not geo_path.exists():
            geo_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage1_geo, geo_path)
        try:
            corr_start = float(self.te_corr_start_edit.text())
            corr_thickness = float(self.te_corr_thickness_edit.text())
            tip_thickness = float(self.te_tip_thickness_edit.text())
            fair_start = float(self.te_fair_start_edit.text())
            th_lo = float(self.te_pchip_th_low.text())
            th_hi = float(self.te_pchip_th_high.text())
            ex_lo = float(self.te_pchip_ex_low.text())
            ex_hi = float(self.te_pchip_ex_high.text())
        except ValueError as e:
            QMessageBox.warning(self, '参数错误', f'STAGE-2 参数必须是数字：{e}')
            return
        # PCHIP 范围校验：剔除范围必须在构造范围内
        th_lo, th_hi = sorted([th_lo, th_hi])
        ex_lo, ex_hi = sorted([ex_lo, ex_hi])
        if not (th_lo <= ex_lo < ex_hi <= th_hi):
            QMessageBox.warning(
                self, 'PCHIP 范围错误',
                f'剔除范围 [{ex_lo}, {ex_hi}] 必须在构造范围 [{th_lo}, {th_hi}] 内\n'
                f'且 ex_low < ex_high。'
            )
            return
        pchip_th_range = (th_lo, th_hi)
        pchip_exclude_range = (ex_lo, ex_hi)

        self.te_log.clear()
        self.te_progress.setValue(0)
        self._set_running('te', True)
        self.te_open_btn.setEnabled(False)
        self._extra_btn_te_compare.setEnabled(False)

        tail_table = stage1_out / 'trailing_edge_thickness.xlsx'
        # TEth_baseline.npy 现在写到 _internal/（与用户可见的 stage1/ 分离）
        baseline_te = stage1_out.parent / '_internal' / 'TEth_baseline.npy'
        self._log('te', f'模板: {stage1_geo}')
        self._log('te', f'改写: {geo_path}')
        self._log('te', f'参数: p1={corr_start}, p2={corr_thickness}, p3={tip_thickness}, p4={fair_start}')
        if baseline_te.exists():
            self._log('te', f'基准: {baseline_te.name}（每次从原始 TEth 重算）')
        else:
            self._log('te', '⚠ 未找到 TEth_baseline.npy（请重跑 STAGE-1 生成基准），回退到当前 TEth')
        self._log('te', '---')

        self._te_worker = TECorrectionWorker(
            str(geo_path), str(tail_table),
            corr_start, corr_thickness, tip_thickness, fair_start,
            baseline_te_path=str(baseline_te) if baseline_te.exists() else None,
            enable_pchip=self.cb_te_pchip.isChecked(),
            th_range=pchip_th_range,
            exclude_range=pchip_exclude_range,
        )
        self._te_worker.progress.connect(self._on_te_progress)
        self._te_worker.finished.connect(self._on_te_finished)
        self._te_worker.start()

    def _on_te_progress(self, percent, msg):
        self.te_progress.setValue(percent)
        self._log('te', msg)

    def _on_te_finished(self):
        self._set_running('te', False)
        res = self._te_worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'STAGE-2 出错', res['error'])
        else:
            self._te_compare = res
            self.te_open_btn.setEnabled(True)
            self._extra_btn_te_compare.setEnabled(True)
            self._mark_stage_completed('te')

    def _on_show_te_compare(self):
        if self._te_compare is None:
            QMessageBox.information(self, '无数据', '请先运行 STAGE-2。')
            return
        dlg = TEComparisonDialog(self._te_compare, self)
        dlg.exec_()

    def _on_show_te_diagram(self):
        """按需打开 TE 修正示意图（弹窗显示原始大图，不参与主 UI 布局）。"""
        path = DIAGRAMS_DIR / 'te_correction_diagram.png'
        if not path.exists():
            QMessageBox.warning(self, '找不到示意图', f'文件不存在：\n{path}')
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            QMessageBox.warning(self, '加载失败', f'无法读取图像：\n{path}')
            return
        dlg = QDialog(self)
        dlg.setWindowTitle('TE 修正示意图')
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel()
        # 按屏幕宽度自适应：超过 1400px 才缩放，否则原图展示
        screen_w = self.window().windowHandle().screen().size().width() if self.window().windowHandle() else 1920
        max_w = min(1400, int(screen_w * 0.8))
        if pix.width() > max_w:
            pix = pix.scaledToWidth(max_w, Qt.SmoothTransformation)
        label.setPixmap(pix)
        label.setAlignment(Qt.AlignCenter)
        layout.addWidget(label)
        dlg.exec_()

    # ============================================================
    # Stage2 执行
    # ============================================================
    def _on_run_stage2(self):
        stage1_out = Path(self.stage1_output_edit.text().strip())
        # STAGE-2 在 stage2/ 上改写 GEO；STAGE-3 从 stage2/ 读 GEO，从 stage1/ 读翼型输入
        stage2_out = stage1_out.parent / 'stage2'
        correction_geo = stage2_out / 'GEO_for_correction.xlsx'
        correction_airfoil = stage1_out / '_internal' / 'standard_airfoil_for_correction.xlsx'
        if not correction_geo.exists():
            QMessageBox.warning(self, '找不到修正 GEO',
                                f'请先运行 STAGE-2 生成修正后的 GEO：\n{correction_geo}')
            return
        if not correction_airfoil.exists():
            QMessageBox.warning(self, '找不到修正翼型',
                                f'请先运行 STAGE-1 生成翼型输入：\n{correction_airfoil}')
            return
        xfoil_outdir = Path(self.correction_work_edit.text().strip()) / 'Corrected_Airfoils'
        final_output = self.final_output_edit.text().strip()
        mode_id = self.xfoil_mode_group.checkedId()
        mode = {0: 'run', 1: 'skip', 2: 'debug'}.get(mode_id, 'run')

        # XFOIL 配置：先校验（在 _set_running 之前，避免状态回滚）
        try:
            th_tail = float(self.edit_th_tail.text().strip())
        except ValueError:
            QMessageBox.warning(self, '参数无效',
                                f'后缘厚度修正起始 Th% 必须是数字：\n{self.edit_th_tail.text()}')
            return
        try:
            th_thick = float(self.edit_th_thick.text().strip())
        except ValueError:
            QMessageBox.warning(self, '参数无效',
                                f'相对厚度修正起始 Th% 必须是数字：\n{self.edit_th_thick.text()}')
            return
        xfoil_cfg = {
            'th_threshold_tail': th_tail,
            'th_threshold_thick': th_thick,
            'enable_tgap': self.cb_enable_tgap.isChecked(),
            'enable_tset': self.cb_enable_tset.isChecked(),
        }

        self.stage2_log.clear()
        self.stage2_progress.setValue(0)
        self._set_running('stage2', True)
        self.stage2_open_btn.setEnabled(False)
        self._extra_btn_stage2_dist.setEnabled(False)

        # 输出文件：STAGE-3 固定导出全部（UI 不再提供勾选）
        export_flags = {
            'export_airfoil_points': True,
            'export_3d_points': True,
            'export_geometry': True,
            'export_tail': True,
            'export_focus': True,
            'export_step_points': True,
        }

        self._log('stage2', f'输入: {correction_geo}')
        self._log('stage2', f'      {correction_airfoil}')
        self._log('stage2', f'XFOIL: {self.xfoil_exe}  (mode={mode})')
        self._log('stage2', f'  • 后缘厚度修正起始 Th% = {th_tail}  '
                            f'({"启用" if xfoil_cfg["enable_tgap"] else "禁用"})')
        self._log('stage2', f'  • 相对厚度修正起始 Th% = {th_thick}  '
                            f'({"启用" if xfoil_cfg["enable_tset"] else "禁用"})')
        self._log('stage2', f'输出: {final_output}')
        self._log('stage2', '---')

        self._stage2_worker = Stage2Worker(
            str(correction_geo), str(correction_airfoil), str(xfoil_outdir),
            final_output, mode, self.xfoil_exe, export_flags, xfoil_cfg=xfoil_cfg,
        )
        self._stage2_worker.progress.connect(self._on_stage2_progress)
        self._stage2_worker.finished.connect(self._on_stage2_finished)
        self._stage2_worker.start()

    def _on_stage2_progress(self, percent, msg):
        self.stage2_progress.setValue(percent)
        self._log('stage2', msg)

    def _on_stage2_finished(self):
        self._set_running('stage2', False)
        res = self._stage2_worker.result
        if res and res.get('error'):
            QMessageBox.critical(self, 'STAGE-3 出错', res['error'])
        else:
            self._stage3_result = res.get('result')
            self.stage2_open_btn.setEnabled(True)
            self._extra_btn_stage2_dist.setEnabled(True)
            self._mark_stage_completed('stage2')
