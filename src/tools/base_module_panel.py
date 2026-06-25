# -*- coding: utf-8 -*-
"""模块面板基类：抽取 8 个 `*_panel.py` 的共性代码。

两层继承：

- `BaseModulePanel`：所有面板共用
    - banner（QWidget#moduleBanner + YouSheBiaoTiHei 标题 + Consolas 副标题）
    - `__init__` 标准流程：register_module → get_paths → paths_changed 监听 → build UI
    - `_on_paths_changed` 统一回调（过滤 module_id + 拉新路径 + 子类钩子）

- `BaseWorkerPanel(BaseModulePanel)`：带执行栏的面板共用
    （wind_farm / wind_farm_compare / load_estimation / focus6_solver 等）
    - `_build_exec_bar`：320px 左侧（运行按钮 + 打开目录按钮 + 进度条）+ 右侧日志区
    - 通用信号槽：`_on_progress(int, str='')` / `_on_log(str)` / `_on_open_output`
    - 默认 `_build_body`：先调子类 `_build_main_content`，再加 `_build_exec_bar`

子类责任：
- 类属性：MODULE_ID / DEFAULT_INPUT_SUBDIR / DEFAULT_OUTPUT_SUBDIR /
  MODULE_TITLE / MODULE_SUBTITLE（必填）
- `_build_body(outer_layout)` 或 `_build_main_content()`：实现主体内容
- 业务逻辑（_on_run / _on_finished / Worker 启动等）自行实现

特殊面板：
- shape_design / blade_converter：多 stage（每 Tab 独立 exec_bar）→ 重写 `_build_body`
  不调用基类 `_build_exec_bar`，自行管理每 Tab 的执行栏
- curve_fitter / prebend_design：matplotlib 交互式，无 exec_bar → 直接继承 BaseModulePanel
"""
import os
import sys
import subprocess

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QProgressBar, QTextEdit, QSizePolicy,
)

from global_config import config_center


class BaseModulePanel(QWidget):
    """所有模块面板的基类：banner + ConfigCenter 集成 + paths_changed 监听。

    子类需提供类属性：
        MODULE_ID (str)              模块标识（如 'wind_farm'）
        DEFAULT_INPUT_SUBDIR (str)   默认输入子目录名
        DEFAULT_OUTPUT_SUBDIR (str)  默认输出子目录名
        MODULE_TITLE (str)           banner 中文标题（如 '风场数据统计'）
        MODULE_SUBTITLE (str)        banner 英文副标题（如 'W I N D   F A R M'）

    可选类属性：
        EXTRA_KEYS (list[str])         extras 字段名列表
        DEFAULT_EXTRAS (dict)          extras 默认值（静态）

    子类需实现：
        _build_body(outer_layout)      往外层 layout 加主体内容

    可选重写：
        _compute_default_extras()      动态计算 extras 默认值（如跨模块读取）
        _on_paths_changed_extra()      paths 变更后同步 UI（默认空实现）
    """

    # 子类必填
    MODULE_ID = ''
    DEFAULT_INPUT_SUBDIR = ''
    DEFAULT_OUTPUT_SUBDIR = ''
    MODULE_TITLE = ''
    MODULE_SUBTITLE = ''

    # 子类可选
    EXTRA_KEYS = None
    DEFAULT_EXTRAS = None

    def __init__(self):
        super().__init__()
        # 1. 动态 extras 钩子（默认返回类属性 DEFAULT_EXTRAS，子类可重写以跨模块读取）
        default_extras = self._compute_default_extras()
        # 2. 注册模块（含 extras）
        config_center.register_module(
            self.MODULE_ID,
            self.DEFAULT_INPUT_SUBDIR,
            self.DEFAULT_OUTPUT_SUBDIR,
            extra_keys=self.EXTRA_KEYS,
            default_extras=default_extras,
        )
        # 3. 拉路径（input/output + 完整 dict 供 extras 读）
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        self._paths = paths
        # 4. 监听变更（其他模块改路径时也触发，slot 内会过滤 module_id）
        config_center.paths_changed.connect(self._on_paths_changed)
        # 5. UI（banner + 子类主体）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_banner())
        self._build_body(outer)
        # 关键：强制 panel 自身 minimum=0，否则某些面板内部的 sizeHint
        # 会透传到顶层，叠加 exec_bar 后窗口高度锁死
        self.setMinimumHeight(0)
        self.setMinimumSize(0, 0)

    # ------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------
    def _build_banner(self):
        """统一 banner：模块中文标题 + 英文副标题。

        QSS 选择器：#moduleBanner / #moduleTitle / #moduleSubtitle
        （APP_STYLE 已就位，见 main.py）
        """
        banner = QWidget()
        banner.setObjectName('moduleBanner')
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(4)

        title = QLabel(self.MODULE_TITLE)
        title.setObjectName('moduleTitle')
        title.setAlignment(Qt.AlignCenter)
        tf = QFont('YouSheBiaoTiHei', 16)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        title.setFont(tf)

        sub = QLabel(self.MODULE_SUBTITLE)
        sub.setObjectName('moduleSubtitle')
        sub.setAlignment(Qt.AlignCenter)
        sf = QFont('Consolas', 8)
        sf.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        sf.setBold(True)
        sub.setFont(sf)

        bl.addWidget(title)
        bl.addWidget(sub)
        return banner

    def _build_body(self, outer_layout):
        """子类必填：往 outer_layout 加主体内容（exec_bar 由 BaseWorkerPanel 自动加）。"""
        raise NotImplementedError

    # ------------------------------------------------------------
    # 配置变更回调
    # ------------------------------------------------------------
    def _on_paths_changed(self, module_id):
        """全局路径变更 slot。module_id 是被改的模块；空串表示全量刷新。"""
        if module_id and module_id != self.MODULE_ID:
            return
        paths = config_center.get_paths(self.MODULE_ID)
        self.input_dir = paths['input']
        self.out_dir = paths['output']
        self._paths = paths
        # 调子类钩子同步 UI（如 folder_label、extras 路径显示等）
        self._on_paths_changed_extra()

    def _on_paths_changed_extra(self):
        """子类重写：paths 变更后同步 UI 控件。默认空实现。"""
        pass

    def _compute_default_extras(self):
        """子类重写：动态计算 extras 默认值（如从其他模块读取）。

        默认返回类属性 DEFAULT_EXTRAS（静态）。
        典型场景：focus6_solver 从 blade_converter 复制 modules_path。
        """
        return self.DEFAULT_EXTRAS


class BaseWorkerPanel(BaseModulePanel):
    """带执行栏的模块面板基类。

    在 BaseModulePanel 基础上加：
    - `_build_exec_bar`：统一底部执行栏
    - 通用信号槽：progress / log / open_output

    子类需实现 `_build_main_content()` 返回主体 QWidget（不含 exec_bar）。
    默认 `_build_body`：先调 `_build_main_content`，再加 `_build_exec_bar`。

    多 stage 面板（每 Tab 独立 exec_bar）可重写 `_build_body` 不调基类 exec_bar。
    """

    # 子类可选（有默认值）
    RUN_BUTTON_TEXT = '▶  运行'              # 运行按钮文字
    OPEN_BUTTON_TEXT = '📂  打开输出目录'     # 打开目录按钮文字
    EXEC_BAR_HEIGHT = 180                    # 执行栏最小高度

    def _build_body(self, outer_layout):
        """默认：主体 + exec_bar。子类一般不重写。

        多 stage 面板（shape_design / blade_converter）需重写以自定义布局。
        """
        body = self._build_main_content()
        if body is not None:
            outer_layout.addWidget(body, 1)
        outer_layout.addWidget(self._build_exec_bar())

    def _build_main_content(self):
        """子类必填：主体内容 QWidget（不含 exec_bar）。返回 None 则不占主体区。"""
        raise NotImplementedError

    def _build_exec_bar(self):
        """统一执行栏：左侧 320px（运行按钮 + 打开目录按钮 + 进度条）+ 右侧日志区。

        创建属性：
            self.run_btn      运行按钮（子类连到 _on_run）
            self.open_btn     打开输出目录按钮（默认连到 _on_open_output）
            self.progress     进度条
            self.log_area     日志只读文本框
        """
        wrap = QWidget()
        wrap.setObjectName('execBar')
        # 强制占住空间：Fixed 垂直策略 + 最小高度，确保主体内容再高也压不掉执行栏
        wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        wrap.setMinimumHeight(self.EXEC_BAR_HEIGHT)

        bar = QHBoxLayout(wrap)
        bar.setContentsMargins(2, 8, 2, 2)
        bar.setSpacing(10)

        # 左侧：运行按钮 + 打开目录按钮 + 进度条（垂直堆叠，固定宽度）
        left_wrap = QWidget()
        left_wrap.setFixedWidth(320)
        left_layout = QVBoxLayout(left_wrap)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.run_btn = QPushButton(self.RUN_BUTTON_TEXT)
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setObjectName('primaryBtn')
        self.run_btn.setCursor(Qt.PointingHandCursor)

        self.open_btn = QPushButton(self.OPEN_BUTTON_TEXT)
        self.open_btn.setObjectName('secondaryBtn')
        self.open_btn.setMinimumHeight(36)
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._on_open_output)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)

        left_layout.addWidget(self.run_btn)
        left_layout.addWidget(self.open_btn)
        left_layout.addWidget(self.progress)
        left_layout.addStretch()

        # 右侧：日志区
        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)
        right_layout.addWidget(QLabel('日志:'))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setObjectName('logArea')
        right_layout.addWidget(self.log_area, 1)

        bar.addWidget(left_wrap, 0)
        bar.addWidget(right_wrap, 1)
        return wrap

    # ------------------------------------------------------------
    # 通用槽（子类 Worker 信号连到这些）
    # ------------------------------------------------------------
    def _on_progress(self, percent, msg=''):
        """通用 progress 信号槽：(int, str)。percent=进度百分比，msg=可选日志。

        兼容两种 Worker 信号签名：
        - progress(int, str)  → 直接连
        - progress(int)       → 用 lambda 包装为 (p, '')
        """
        self.progress.setValue(int(percent))
        if msg:
            self.log_area.append(msg)
            self.log_area.verticalScrollBar().setValue(
                self.log_area.verticalScrollBar().maximum()
            )

    def _on_log(self, msg):
        """通用日志追加槽：(str)。"""
        self.log_area.append(msg)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    def _on_open_output(self):
        """打开输出目录（跨平台）。"""
        if not self.out_dir:
            return
        try:
            if sys.platform == 'win32':
                os.startfile(self.out_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self.out_dir])
            else:
                subprocess.Popen(['xdg-open', self.out_dir])
        except OSError as e:
            self.log_area.append(f'⚠ 打开输出目录失败：{e}')
