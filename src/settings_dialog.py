# -*- coding: utf-8 -*-
"""设置对话框：模块输入/输出路径的唯一持久化入口。

QDialog 模态弹窗，QTableWidget 三列：模块 | 输入目录 | 输出目录。
每行后两列内嵌 QLineEdit + 浏览按钮。
- 点 OK：遍历每行调 config_center.set_paths()（内部校验 + 写 JSON + 广播）。
  任一行校验失败 → 列出全部错误，不关闭对话框。
- 点取消：丢弃所有改动。

各模块的 extras（如 focus6_solver 的 Modules
目录）在主表格下方按模块分组显示，由 _MODULE_EXTRAS 配置驱动。
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
    'shape_design': '叶片形状输出',
    'blade_converter': '叶片结构套件',
    'focus6_solver': 'FOCUS6',
    'load_estimation': '载荷预估',
    'curve_fitter': '曲线拟合',
    'prebend_design': '预弯设计',
}

# 各模块的额外路径配置（extras）：在主表格下方按模块分组显示
# key = (label, placeholder, browse_type: 'dir'/'file')
# 注：modules_path 已从 blade_converter 迁移到 focus6_solver（v0.3.0）
# 注：shape_design 的 appdata_path 已移除（v0.3.03）—— 翼型库固定在 PROJECT_ROOT/配置/，
#     不再走 extras，避免跨电脑绝对路径问题
_MODULE_EXTRAS = {
    'focus6_solver': [
        ('modules_path', 'FOCUS6 Modules 目录',
         'C:\\Program Files (x86)\\ECN_WMC\\FOCUS6.3\\Modules', 'dir'),
    ],
}


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
        self._extras_edits = {}   # (module_id, extra_key) -> QLineEdit
        self._extras_groups = {}  # module_id -> QGroupBox（按需显隐）
        self._build_ui()
        self._load_modules()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel('修改各模块的输入/输出目录。点确定后持久化，并通知对应面板刷新。\n'
                      '工具箱内的目录存相对路径（工具箱整体迁移自动跟随）；外部目录存绝对路径。')
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

        # 各模块的 extras 区（按 _MODULE_EXTRAS 配置动态创建）
        # 每个 module_id 一个 QGroupBox，标题 = "模块名 — 资源/求解器路径"
        # extras 路径（AppData/求解器 Modules）只通过浏览选择，不主动创建
        for module_id, extras_spec in _MODULE_EXTRAS.items():
            group = QGroupBox(f'{_module_label(module_id)} — 额外路径')
            form = QFormLayout(group)
            form.setSpacing(6)
            for key, label_text, placeholder, browse_type in extras_spec:
                row_w = QWidget()
                row_lay = QHBoxLayout(row_w)
                row_lay.setContentsMargins(0, 0, 0, 0)
                row_lay.setSpacing(4)
                edit = QLineEdit()
                edit.setMinimumHeight(24)
                edit.setPlaceholderText(placeholder)
                browse_btn = QPushButton('…')
                browse_btn.setFixedWidth(28)
                browse_btn.setToolTip('浏览…')
                browse_btn.clicked.connect(
                    lambda _=False, e=edit, bt=browse_type: (
                        self._on_browse_dir(e) if bt == 'dir'
                        else self._on_browse_file(e)))
                row_lay.addWidget(edit, 1)
                row_lay.addWidget(browse_btn)
                self._extras_edits[(module_id, key)] = edit
                form.addRow(label_text, row_w)
            group.setVisible(False)  # 默认隐藏，_load_modules 按需显示
            self._extras_groups[module_id] = group
            layout.addWidget(group)

        # 一键创建所有模块的输入/输出文件夹（不弹窗，直接批量 makedirs）
        # 资源/求解器 extras 路径不参与批量创建（应通过浏览选择已存在的目录）
        mkdir_btn = QPushButton('📁 一键创建所有模块文件夹')
        mkdir_btn.setToolTip('为所有模块的输入/输出目录递归创建文件夹（已存在的跳过）')
        mkdir_btn.clicked.connect(self._on_mkdir_all)
        layout.addWidget(mkdir_btn)

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
        """从 config_center 拉取已注册模块，填充表格 + extras 区。"""
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

        # 显示已注册模块的 extras 区，并回填当前值
        for module_id, group in self._extras_groups.items():
            if module_id in modules:
                group.setVisible(True)
                paths = config_center.get_paths(module_id)
                for (mid, key), edit in self._extras_edits.items():
                    if mid == module_id:
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
        btn.clicked.connect(lambda _=False, e=edit: self._on_browse_dir(e))
        lay.addWidget(btn)
        return w

    def _on_browse_dir(self, edit):
        """选择目录。"""
        start = edit.text() or ''
        d = QFileDialog.getExistingDirectory(self, '选择目录', start)
        if d:
            edit.setText(d)

    def _on_browse_file(self, edit):
        """选择文件（用于 .exe 等场景，当前未启用）。"""
        start = edit.text() or ''
        f, _ = QFileDialog.getOpenFileName(self, '选择文件', start)
        if f:
            edit.setText(f)

    def _on_mkdir_all(self):
        """一键批量创建所有模块的输入/输出目录。

        - 静默创建（不弹窗）：直接 os.makedirs(exist_ok=True)
        - 跳过空路径和已存在路径
        - 成功时只在按钮文字上短暂反馈（如 "✓ 已创建 5 个"），3 秒后恢复
        - 仅失败时弹一次汇总错误对话框（必须让用户知道哪里出问题）
        - extras 路径（AppData/求解器 Modules）不参与：那些路径应通过浏览
          按钮选择已存在的目录，不主动创建；缺失时由对应模块在运行时报错
        """
        import os
        from PyQt5.QtCore import QTimer

        created = []
        existed = []
        failed = []
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if name_item is None:
                continue
            module_id = name_item.data(Qt.UserRole)
            for col_idx, role in ((1, '输入'), (2, '输出')):
                cell_w = self.table.cellWidget(row, col_idx)
                if cell_w is None:
                    continue
                edit = cell_w.findChild(QLineEdit)
                if edit is None:
                    continue
                path = edit.text().strip()
                if not path:
                    continue
                if os.path.exists(path):
                    existed.append(path)
                    continue
                try:
                    os.makedirs(path, exist_ok=True)
                    created.append(path)
                except OSError as e:
                    failed.append(f'{path}  ({e})')

        # 成功：按钮文字短暂反馈，不弹窗
        sender = self.sender()
        if sender is not None:
            original_text = sender.text()
            sender.setText(f'✓ 已创建 {len(created)} 个 / 已存在 {len(existed)} 个')
            QTimer.singleShot(3000, lambda: sender.setText(original_text))

        # 仅失败时弹窗
        if failed:
            QMessageBox.warning(
                self, '部分目录创建失败',
                f'失败 {len(failed)} 个：\n\n' + '\n'.join(failed)
            )

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

        # 各模块的 extras（按 _MODULE_EXTRAS 配置遍历已显示的 group）
        for module_id, group in self._extras_groups.items():
            if not group.isVisible():
                continue
            paths = config_center.get_paths(module_id)
            label = _module_label(module_id)
            for (mid, key), edit in self._extras_edits.items():
                if mid != module_id:
                    continue
                val = edit.text().strip()
                # 留空：清空已存储值
                if not val:
                    config_center.set_extra(module_id, key, '')
                    continue
                # 非空：必须是已存在的目录（求解器 Modules / AppData 都是目录）
                if not os.path.isdir(val):
                    errs.append(f'[{label}] {edit.placeholderText()} 目录不存在：{val}')
                else:
                    config_center.set_extra(module_id, key, val)

        if errs:
            QMessageBox.warning(
                self, '路径校验失败',
                '以下路径未保存（其余已保存）：\n\n' + '\n'.join(errs)
            )
            return
        self.accept()
