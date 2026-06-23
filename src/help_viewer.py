# -*- coding: utf-8 -*-
"""帮助查看器：渲染 src/help/*.md 为模态对话框。

加载约定：HELP_DIR 下 {key}.md，key 由调用方传入（如 'wind_farm' / 'about'）。
用 QTextBrowser.setMarkdown() 渲染（Qt 5.14+ 支持，本环境为 5.15）。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QPushButton, QHBoxLayout, QTextBrowser,
)

# help 文件目录：src/help/（本文件在 src/ 下）
HELP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'help')


class HelpDialog(QDialog):
    """Markdown 帮助查看器。

    Args:
        key: help 文件名（不带 .md 后缀），如 'wind_farm' / 'about'
        title: 对话框标题
        parent: 父 widget
    """

    def __init__(self, key, title='帮助', parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 640)
        self._build_ui()
        self._load(key)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)   # 允许点链接打开外部浏览器
        # 内边距让正文呼吸
        self.browser.document().setDocumentMargin(20)
        layout.addWidget(self.browser, 1)

        # 底部关闭按钮行
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(12, 8, 12, 10)
        btn_row.addStretch()
        btn_close = QPushButton('关闭')
        btn_close.setObjectName('primaryBtn')
        btn_close.setMinimumWidth(96)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _load(self, key):
        """读取 HELP_DIR/{key}.md 并 setMarkdown。文件缺失时显示占位提示。"""
        path = os.path.join(HELP_DIR, f'{key}.md')
        if not os.path.exists(path):
            self.browser.setPlainText(
                f'（未找到帮助文件：{path}）\n\n'
                f'请确认 src/help/{key}.md 存在。'
            )
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                md = f.read()
        except OSError as e:
            self.browser.setPlainText(f'读取帮助文件失败：{e}')
            return
        # setMarkdown 在 Qt 5.14+ 可用；标题/列表/表格/代码块/引用均支持
        self.browser.setMarkdown(md)
