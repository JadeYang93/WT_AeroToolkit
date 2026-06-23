# -*- coding: utf-8 -*-
"""设置对话框：模块输入/输出路径的唯一持久化入口。

QDialog 模态弹窗，QTableWidget 三列：模块 | 输入目录 | 输出目录。
每行后两列内嵌 QLineEdit + 浏览按钮。
- 点 OK：遍历每行调 config_center.set_paths()（内部校验 + 写 JSON + 广播）。
  任一行校验失败 → 列出全部错误，不关闭对话框。
- 点取消：丢弃所有改动。

特殊：blade_converter 模块在主表格下方额外显示「求解器路径」QGroupBox，
配置 3 个 FOCUS6 .exe（farob/frbex/UserLoadcaseConverter）。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QFileDialog, QMessageBox, QWidget,
    QLineEdit, QAbstractItemView, QSizePolicy, QGroupBox, QFormLayout,
)

from global_config import config_center


# 模块名映射表：module_id → 友好显示名
# 新增模块时在这里加一行（或在 main.py 启动时注入）
_MODULE_LABELS = {
    'wind_farm': '风场数据统计',
    'wind_farm_compare': '风场对比',
    'shape_output': '叶片形状输出',
    'blade_converter': '叶片结构套件',
}

# blade_converter 的求解器路径：1 个 Modules 目录（内含 farob/ frbex/ 等子目录）
# 不再让用户分别配 3 个 .exe；具体哪个求解器由 TAB-4 内部按需选用
_SOLVER_EXE_KEYS = [
    ('modules_path', 'FOCUS6 Modules 目录',
     'C:\\Program Files (x86)\\ECN_WMC\\FOCUS6.3\\Modules'),
]

# 仅当此模块在 config_center.list_modules() 中时显示求解器 section
_SOLVER_MODULE_ID = 'blade_converter'


def _module_label(module_id):
    return _MODULE_LABELS.get(module_id, module_id)


class SettingsDialog(QDialog):
    """路径设置对话框。

    构造时会从 config_center 拉一次所有已注册模块的当前路径。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('路径设置')
        self.setMinimumWidth(720)
        self._solver_edits = {}   # extra_key -> QLineEdit
        self._build_ui()
        self._load_modules()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel('修改各模块的输入/输出目录。点确定后持久化，并通知对应面板刷新。')
        hint.setObjectName('hintLabel')
        layout.addWidget(hint)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['模块', '输入目录', '输出目录'])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 140)
        layout.addWidget(self.table, 1)

        # 求解器路径 section（仅 blade_converter 注册后显示）
        self.solver_group = QGroupBox('叶片结构套件 — 求解器路径')
        solver_lay = QFormLayout(self.solver_group)
        solver_lay.setSpacing(6)
        for key, label_text, _placeholder in _SOLVER_EXE_KEYS:
            row_w = QWidget()
            row_lay = QHBoxLayout(row_w)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(4)
            edit = QLineEdit()
            edit.setMinimumHeight(24)
            edit.setPlaceholderText('选择对应的 .exe 文件路径')
            browse_btn = QPushButton('…')
            browse_btn.setFixedWidth(28)
            browse_btn.setToolTip('浏览 .exe…')
            browse_btn.clicked.connect(
                lambda _=False, e=edit: self._on_browse_exe(e))
            row_lay.addWidget(edit, 1)
            row_lay.addWidget(browse_btn)
            self._solver_edits[key] = edit
            solver_lay.addRow(label_text, row_w)
        self.solver_group.setVisible(False)   # 默认隐藏，_load_modules 中按需显示
        layout.addWidget(self.solver_group)

        # 底部按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton('确定')
        btn_ok.setObjectName('primaryBtn')
        btn_ok.setMinimumWidth(96)
        btn_ok.clicked.connect(self._on_ok)
        btn_cancel = QPushButton('取消')
        btn_cancel.setMinimumWidth(96)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def _load_modules(self):
        """从 config_center 拉取已注册模块，填充表格。"""
        modules = config_center.list_modules()
        self.table.setRowCount(len(modules))
        for row, module_id in enumerate(modules):
            paths = config_center.get_paths(module_id)

            # 模块名
            name_item = QTableWidgetItem(_module_label(module_id))
            name_item.setData(Qt.UserRole, module_id)
            name_item.setTextAlignment(Qt.AlignCenter)
            name_item.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(row, 0, name_item)

            self.table.setCellWidget(row, 1, self._make_path_cell(paths['input']))
            self.table.setCellWidget(row, 2, self._make_path_cell(paths['output']))

        # 若 blade_converter 已注册，显示求解器 section 并回填当前 extras
        if _SOLVER_MODULE_ID in modules:
            self.solver_group.setVisible(True)
            paths = config_center.get_paths(_SOLVER_MODULE_ID)
            for key, _label, _ph in _SOLVER_EXE_KEYS:
                edit = self._solver_edits.get(key)
                if edit is not None:
                    edit.setText(paths.get(key, '') or '')

    def _make_path_cell(self, path):
        """单元格：QLineEdit + 浏览按钮。返回容器 widget。"""
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(4)
        edit = QLineEdit(path)
        edit.setMinimumHeight(24)
        lay.addWidget(edit, 1)
        btn = QPushButton('…')
        btn.setFixedWidth(28)
        btn.setToolTip('浏览…')
        btn.clicked.connect(lambda _=False, e=edit: self._on_browse(e))
        lay.addWidget(btn)
        return w

    def _on_browse(self, edit):
        start = edit.text() or ''
        d = QFileDialog.getExistingDirectory(self, '选择目录', start)
        if d:
            edit.setText(d)

    def _on_browse_exe(self, edit):
        """求解器 Modules 目录选择（目录而非单个 .exe）。"""
        start = edit.text() or ''
        d = QFileDialog.getExistingDirectory(
            self, '选择 FOCUS6 Modules 文件夹', start)
        if d:
            edit.setText(d)

    def _on_ok(self):
        """校验 + 持久化所有改动。任一行失败则列出错误并保持对话框打开。"""
        errs = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if name_item is None:
                continue
            module_id = name_item.data(Qt.UserRole)
            in_w = self.table.cellWidget(row, 1)
            out_w = self.table.cellWidget(row, 2)
            if in_w is None or out_w is None:
                continue
            input_path = in_w.findChild(QLineEdit).text().strip()
            output_path = out_w.findChild(QLineEdit).text().strip()
            row_errs = config_center.set_paths(module_id, input_path, output_path)
            if row_errs:
                label = _module_label(module_id)
                for e in row_errs:
                    errs.append(f'[{label}] {e}')

        # 求解器 extras（仅 blade_converter 注册后才会有 section）
        if self.solver_group.isVisible():
            for key, label_text, _ph in _SOLVER_EXE_KEYS:
                edit = self._solver_edits.get(key)
                if edit is None:
                    continue
                val = edit.text().strip()
                # 允许留空（不强制配置）——但若填了，必须是已存在的目录
                # （不强校验内含 farob/frbex 子目录，用哪个用户自己决定）
                if val:
                    if not os.path.isdir(val):
                        errs.append(f'[叶片结构套件] {label_text} 目录不存在：{val}')
                    else:
                        config_center.set_extra(_SOLVER_MODULE_ID, key, val)
                else:
                    # 留空时清空已存储的值
                    config_center.set_extra(_SOLVER_MODULE_ID, key, '')

        if errs:
            QMessageBox.warning(
                self, '路径校验失败',
                '以下路径未保存（其余已保存）：\n\n' + '\n'.join(errs)
            )
            return
        self.accept()
