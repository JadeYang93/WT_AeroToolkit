# -*- coding: utf-8 -*-
"""统一的 (?) 帮助按钮组件——紧贴 QGroupBox 标题文字末尾。

使用方式：
    from ui.help_button import HelpButton, add_help_to_groupbox

    # 方式 1：单独用
    btn = HelpButton(title='分段拟合', text='说明文字...')
    layout.addWidget(btn)

    # 方式 2：把 GroupBox 灰字 tip 换成 (?) 紧贴标题
    add_help_to_groupbox(my_groupbox, title='分段拟合',
                         text='原灰字说明...', replace_label=old_tip_label)

定位原理：
    (?) 作为 group 的**子 widget**（不在 layout 里），通过事件过滤器监听
    QGroupBox 的 Resize/Show/Polish 事件，用 QFontMetrics 测量标题文字宽度，
    move() 到「徽章右侧 + 2px」位置。QSS 里 title 是 subcontrol-position: top left;
    left: 10px; padding: 2px 10px，徽章宽度 = text_width + 20px。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QObject, QEvent, QTimer
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import (
    QPushButton, QMessageBox, QGroupBox, QHBoxLayout, QVBoxLayout, QLayout,
    QLabel,
)


_STYLE = """
QPushButton {
    border-radius: 9px;
    background: #1e3a5f;
    color: #ffffff;
    font-weight: bold;
    border: none;
    font-size: 11px;
    padding: 0px;
    min-width: 18px;
}
QPushButton:hover {
    background: #0ea5e9;
    color: white;
}
QPushButton:pressed {
    background: #0284c7;
}
"""


class HelpButton(QPushButton):
    """小圆形 (?) 按钮，点击弹窗显示帮助文字。"""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__('?', parent)
        self._title = title
        self._text = text
        self.setFixedSize(18, 18)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(_STYLE)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip('点击查看说明')
        self.clicked.connect(self._show_help)

    def _show_help(self):
        msg = QMessageBox(self)
        msg.setWindowTitle(self._title or '说明')
        msg.setText(self._text)
        msg.setTextFormat(Qt.RichText)
        msg.setIcon(QMessageBox.Information)
        msg.exec_()


class _TitleHelpPositioner(QObject):
    """监听 QGroupBox 事件，把 HelpButton 紧贴到标题徽章右侧。

    QSS（main.py 全局）：
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 2px 10px;       ← 徽章左右内边距 10px
            font-size: 12px;
            font-weight: bold;
        }
        QGroupBox { margin-top: 10px; }
    徽章左上角 ≈ (10, 0)，宽 = text_w + 20，高 ≈ 12 + 4 = 16。
    (?) 放在 (badge_left + badge_w + 8, ~0)，垂直与徽章对齐。
    """

    def __init__(self, group: QGroupBox, btn: HelpButton):
        super().__init__(group)
        self._group = group
        self._btn = btn
        btn.setParent(group)
        group.installEventFilter(self)
        # QSS 首次应用可能晚于构造，延迟到下一轮事件循环再定位
        QTimer.singleShot(0, self._reposition)

    def eventFilter(self, obj, event):
        if obj is self._group:
            t = event.type()
            if t in (QEvent.Resize, QEvent.Show, QEvent.Polish,
                     QEvent.FontChange):
                self._reposition()
        return super().eventFilter(obj, event)

    def _reposition(self):
        title = self._group.title()
        if not title:
            return
        # 用与 QSS title 一致的字体测量（bold, 12px）
        f = QFont(self._group.font())
        f.setBold(True)
        f.setPixelSize(12)
        fm = QFontMetrics(f)
        text_w = fm.horizontalAdvance(title)
        badge_left = 10            # QSS: left: 10px
        badge_w = text_w + 20      # QSS: padding 2px 10px → 左右各 10px
        badge_h = 12 + 4           # 字高 12 + 上下 padding 2*2
        x = badge_left + badge_w + 8
        # 垂直：让按钮垂直中心 ≈ 徽章中心（徽章 y ∈ [0, badge_h]）
        y = max(0, (badge_h - self._btn.height()) // 2)
        self._btn.move(x, y)
        self._btn.raise_()
        self._btn.show()


def add_help_to_groupbox(
    group: QGroupBox,
    title: str,
    text: str,
    replace_label: QLabel | None = None,
) -> HelpButton:
    """在 QGroupBox 标题右侧插入 (?) 帮助按钮（紧贴标题徽章）。

    Parameters
    ----------
    group : QGroupBox
        目标分组框（任意 layout 类型均可，按钮作为子 widget 不进 layout）。
    title : str
        弹窗标题。
    text : str
        帮助正文（支持 HTML 富文本）。
    replace_label : QLabel | None
        若提供原灰字 QLabel，会被隐藏（用 (?) 替代其作用）。

    Returns
    -------
    HelpButton
        创建的按钮实例。
    """
    btn = HelpButton(title, text, group)
    _TitleHelpPositioner(group, btn)
    # 隐藏原灰字 label
    if replace_label is not None:
        try:
            replace_label.setVisible(False)
        except Exception:
            pass
    return btn
