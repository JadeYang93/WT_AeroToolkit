# 气动组工具箱 GUI 架构改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `src/main.py` 的单一 `MainWindow` 改造为 `ToolShell` + `WindFarmStatsPanel` 两层结构，应用改名「气动组工具箱」，左侧加导航栏。

**Architecture:** `ToolShell`（顶层 QMainWindow）= `QListWidget`（左导航 160px）+ `QStackedWidget`（右内容区）；`WindFarmStatsPanel`（QWidget）由原 `MainWindow` 改造，作为右侧第一个面板。底层 7 个业务模块（config/io_utils/processing/ti_bin/plotting/export/pipeline）零改动。

**Tech Stack:** PyQt5（QListWidget + QStackedWidget + QWidget），Python 3，pandas/matplotlib（业务侧不变）

---

## 项目背景（执行者必读）

- 项目根：`F:\python\风场失效\风场数据统计工具`
- **项目非 git 仓库**，本 plan 不含 commit 步骤（用 verify 步骤代替）
- 当前 `src/main.py`（694 行）含 `StatsWorker` + `MainWindow`（业务 GUI）+ `main()` 三部分
- 改造后 `src/main.py` 只剩 `ToolShell` + `TOOLS` + `main()`（~60 行），原业务 GUI 整体迁到 `src/tools/wind_farm_panel.py`
- **路径关键点**：`wind_farm_panel.py` 在 `src/tools/` 下，比原 `main.py` 多一层目录，计算项目根需要**两层** `os.path.dirname`（原 main.py 只需一层）

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `src/tools/__init__.py` | Create（空）| 标记 tools 为 Python 包 |
| `src/tools/wind_farm_panel.py` | Create | `WindFarmStatsPanel`（QWidget）+ `StatsWorker`（从 main.py 迁出 + 改造）|
| `src/main.py` | Overwrite | `MainWindow`（ToolShell 壳）+ `TOOLS` 注册表 + `main()` |
| `使用说明.md` | Edit | §1 简介 / §2.2 启动 / §4 界面操作 / §8 目录结构 |
| `src/{config,io_utils,processing,ti_bin,plotting,export,pipeline}.py` | **不动** | 业务层零改动 |
| `运行.bat` | **不动** | 命令仍 `python src\main.py` |

依赖方向严格单向：`main → tools.wind_farm_panel → pipeline → {io_utils, processing, ti_bin, plotting, export} → config`

---

### Task 1: 创建 tools/ 包骨架

**Files:**
- Create: `src/tools/__init__.py`

- [ ] **Step 1.1: 创建空 `__init__.py`**

写入文件 `src/tools/__init__.py`，完整内容：

```python
# -*- coding: utf-8 -*-
"""tools 包：所有工具面板放在此目录下。
新建工具 = 新建 xxx_panel.py（实现 QWidget 子类）+ 在 main.py 的 TOOLS 注册表加一行。
"""
```

- [ ] **Step 1.2: 验证包可被 import**

Run（在项目根）：

```bash
cd "F:/python/风场失效/风场数据统计工具/src" && python -c "import tools; print(tools.__file__)"
```

Expected：输出 `tools/__init__.py` 的绝对路径，无 ImportError。

---

### Task 2: 创建 wind_farm_panel.py（迁移 + 改造）

策略：先用 `cp` 把 `src/main.py` 完整复制到 `src/tools/wind_farm_panel.py`，再做 6 处精确 Edit。这样保证业务方法零遗漏。

**Files:**
- Create: `src/tools/wind_farm_panel.py`
- Read（参考，不修改）：`src/main.py`

- [ ] **Step 2.1: 复制 main.py 到 wind_farm_panel.py**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具" && cp src/main.py src/tools/wind_farm_panel.py
```

Verify：`ls -la src/tools/wind_farm_panel.py` 文件存在，行数与 `src/main.py`（694）相同。

- [ ] **Step 2.2: 改模块 docstring**

Edit `src/tools/wind_farm_panel.py`：

old_string:
```
# -*- coding: utf-8 -*-
"""风场数据统计工具 - GUI 主程序"""
import sys
import os
```

new_string:
```
# -*- coding: utf-8 -*-
"""风场数据统计面板（QWidget 子类，由原 MainWindow 改造）。

作为「气动组工具箱」ToolShell 的右侧第一个面板。本文件不含入口 main()，
入口在 src/main.py 的 ToolShell 中。
"""
import os
```

说明：去掉 `import sys`（panel 不再需要，sys 只在原 main() 用过）。

- [ ] **Step 2.3: 改 PyQt5 import（去掉 QMainWindow、QApplication）**

Edit `src/tools/wind_farm_panel.py`：

old_string:
```
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QCheckBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpinBox, QDateEdit, QComboBox
)
```

new_string:
```
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QCheckBox,
    QProgressBar, QTextEdit, QMessageBox, QGroupBox, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpinBox, QDateEdit, QComboBox
)
```

说明：去掉 `QApplication`（仅 main() 用）、`QMainWindow`（基类换为 QWidget）。其余保留。

- [ ] **Step 2.4: 改类定义 + 删除 setWindowTitle/resize**

Edit `src/tools/wind_farm_panel.py`：

old_string:
```
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('风场数据统计工具')
        self.resize(820, 760)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        # 兼容从 src/main.py 启动：默认输入/输出目录在项目根（src 的上一级）
        project_dir = os.path.dirname(script_dir) if os.path.basename(script_dir) == 'src' else script_dir
        default_input = os.path.join(project_dir, '输入数据')
        self.data_dir = default_input if os.path.isdir(default_input) else project_dir
        self.out_dir = os.path.join(project_dir, '输出')
        self.cache_path = os.path.join(self.out_dir, '.cache.pkl')
        self.data_type = 'raw'   # 'raw' (秒级原始数据) 或 'monthly_ti' (月度湍流表)
```

new_string:
```
class WindFarmStatsPanel(QWidget):
    def __init__(self):
        super().__init__()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        # wind_farm_panel.py 在 src/tools/，需要两层 dirname 到项目根：
        #   script_dir = src/tools/  → 上一层 = src/  → 再上一层 = 项目根
        src_dir = os.path.dirname(script_dir)
        project_dir = os.path.dirname(src_dir)
        default_input = os.path.join(project_dir, '输入数据')
        self.data_dir = default_input if os.path.isdir(default_input) else project_dir
        self.out_dir = os.path.join(project_dir, '输出')
        self.cache_path = os.path.join(self.out_dir, '.cache.pkl')
        self.data_type = 'raw'   # 'raw' (秒级原始数据) 或 'monthly_ti' (月度湍流表)
```

说明：类名 `MainWindow` → `WindFarmStatsPanel`，基类 `QMainWindow` → `QWidget`。删除 `setWindowTitle` / `resize`（壳统一管理）。路径计算改为**两层** `dirname`（src/tools/ → src/ → 项目根）。

- [ ] **Step 2.5: 改 `_build_ui` 第一段（去掉 central widget 容器）**

Edit `src/tools/wind_farm_panel.py`：

old_string:
```
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
```

new_string:
```
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
```

说明：QWidget 子类直接把 layout 设到 self，无需 central widget 中转。其余 `_build_ui` 内部代码（folder_box/options_box/ti_box/date_box/start_btn/progress_bar/log_area 等）**全部不动**。

- [ ] **Step 2.6: 删除文件末尾的 main() 入口**

`wind_farm_panel.py` 不含入口（入口在 `src/main.py` 的 ToolShell），需删除文件末尾的 `main()` 函数和 `if __name__ == '__main__':` 块。

用 Edit 工具，old_string 为下面整段（注意结尾的空行），**new_string 留空**（即 Edit 的 new_string 参数传空字符串 `""`，表示删除）：

old_string（精确匹配，含末尾换行）：
```
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
```

new_string: `""`（空字符串，整段删除）

Verify：

```bash
cd "F:/python/风场失效/风场数据统计工具" && grep -c "^def main" src/tools/wind_farm_panel.py
```

Expected：`0`（main 函数已删除）。

- [ ] **Step 2.7: 验证 wind_farm_panel.py import 与方法完整性**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具/src" && python -c "from tools.wind_farm_panel import WindFarmStatsPanel, StatsWorker; print('import OK')"
```

Expected：输出 `import OK`，无 ImportError / SyntaxError。

Run（方法完整性对比）：

```bash
cd "F:/python/风场失效/风场数据统计工具" && echo "=== main.py 的 def ===" && grep -E "^    def |^def " src/main.py && echo "=== wind_farm_panel.py 的 def ===" && grep -E "^    def |^def " src/tools/wind_farm_panel.py
```

Expected：wind_farm_panel.py 应包含原 main.py 的所有业务方法（`_build_ui` / `_set_table_col` / `_collect_checked_turbines` / `_refresh_turbine_lists` / `_collect_turbine_blades` / `_refresh_blade_styles` / `_collect_blade_styles` / `_update_scan_status` / `_on_toggle_dates` / `_on_scan` / `_on_browse` / `_on_data_type_changed` / `_log` / `_on_start` / `_on_progress` / `_on_finished`）+ `StatsWorker` 的 `run`。wind_farm_panel.py **不应**有 `main` 函数（已删）。main.py 仍含原 `main()`（下一步 Task 3 会重写）。

---

### Task 3: 重写 main.py 为 ToolShell

**Files:**
- Overwrite: `src/main.py`

- [ ] **Step 3.1: 重写 src/main.py 完整内容**

用 Write 工具覆盖 `src/main.py`，完整内容：

```python
# -*- coding: utf-8 -*-
"""气动组工具箱 - 入口。

ToolShell（顶层 QMainWindow）：左侧 QListWidget 导航 + 右侧 QStackedWidget 内容区。
当前注册 1 个工具：风场数据统计（WindFarmStatsPanel）。
未来加新工具：在 tools/ 下新建 xxx_panel.py + 在下方 TOOLS 加一行。
"""
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout,
    QListWidget, QStackedWidget,
)

from tools.wind_farm_panel import WindFarmStatsPanel


# 工具注册表：(导航栏显示名, 面板类)。顺序决定导航栏从上到下的顺序。
TOOLS = [
    ('风场数据统计', WindFarmStatsPanel),
]


class MainWindow(QMainWindow):
    """工具集壳：左侧导航 + 右侧内容区。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('气动组工具箱')
        self.resize(1000, 780)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧导航
        self.nav_list = QListWidget()
        self.nav_list.setFixedWidth(160)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)

        # 右侧内容区
        self.content_stack = QStackedWidget()

        # 按 TOOLS 顺序实例化每个面板
        for name, panel_cls in TOOLS:
            panel = panel_cls()
            self.nav_list.addItem(name)
            self.content_stack.addWidget(panel)

        layout.addWidget(self.nav_list)
        layout.addWidget(self.content_stack, 1)
        self.setCentralWidget(central)

        # 默认选中第一个工具
        if self.nav_list.count() > 0:
            self.nav_list.setCurrentRow(0)

    def _on_nav_changed(self, row):
        if 0 <= row < self.content_stack.count():
            self.content_stack.setCurrentIndex(row)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
```

- [ ] **Step 3.2: 验证 main.py import**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具/src" && python -c "import main; print('import OK')"
```

Expected：输出 `import OK`，无 ImportError。

- [ ] **Step 3.3: 验证 main.py 行数大幅缩减**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具" && wc -l src/main.py
```

Expected：约 60 行（原 694 行）。若仍是 ~694 行说明 Write 未生效，重试。

- [ ] **Step 3.4: GUI 启动冒烟测试**

Run（headless，仅验证不抛异常）：

```bash
cd "F:/python/风场失效/风场数据统计工具/src" && python -c "
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
import main
w = main.MainWindow()
w.show()
app.processEvents()
# 验证壳结构
assert w.windowTitle() == '气动组工具箱', f'title={w.windowTitle()}'
assert w.nav_list.count() == 1, f'nav count={w.nav_list.count()}'
assert w.nav_list.item(0).text() == '风场数据统计', f'nav item={w.nav_list.item(0).text()}'
assert w.content_stack.count() == 1, f'stack count={w.content_stack.count()}'
assert w.content_stack.currentIndex() == 0, f'current idx={w.content_stack.currentIndex()}'
print('GUI shell OK')
"
```

Expected：输出 `GUI shell OK`。断言失败会抛 AssertionError。

> 备注：`QT_QPA_PLATFORM=offscreen` 让 Qt 在无显示设备环境跑（CI/SSH）。本机有显示器时此变量无副作用。

- [ ] **Step 3.5: 人工视觉验证（用户执行）**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具" && python src/main.py
```

人工检查清单（看到即通过）：

1. 窗口标题栏显示「气动组工具箱」
2. 窗口尺寸约 1000×780
3. 左侧有窄栏（宽 160px），含一项「风场数据统计」，默认蓝底高亮
4. 右侧显示完整风场统计 UI（数据类型下拉/扫描按钮/路径/选项表/叶型映射/TI 参数/日期/开始按钮/进度条/日志）
5. 点击左侧「风场数据统计」右侧内容不变（仅 1 项，无切换效果）

---

### Task 4: 端到端业务冒烟测试（验证零回归）

目的：确认 GUI 改造**未影响**任何业务逻辑。直接调 `pipeline.run(...)`（绕过 GUI），对比输出图数/Excel。

**Files:** 无修改，仅运行验证脚本。

- [ ] **Step 4.1: monthly_ti 模式冒烟**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具/src" && python -c "
from pipeline import run
res = run('../输入数据', '../输出_smoke_mti', [], [], data_type='monthly_ti', progress_callback=lambda p,m: None)
print('plots:', res['plots'], 'error:', res['error'])
"
```

Expected：`plots: 8 error: None`。

Verify 文件生成：

```bash
cd "F:/python/风场失效/风场数据统计工具" && ls 输出_smoke_mti/ | wc -l
```

Expected：9（8 张 PNG + 1 个 xlsx）。

- [ ] **Step 4.2: raw 模式冒烟**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具/src" && python -c "
from pipeline import run
res = run(
    '../输入数据', '../输出_smoke_raw',
    metrics=['wind_speed', 'ti', 'density'],
    granularities=['daily', 'weekly', 'monthly'],
    progress_callback=lambda p,m: None,
)
print('plots:', res['plots'], 'error:', res['error'])
"
```

Expected：`plots: 7 error: None`。

- [ ] **Step 4.3: 清理冒烟测试输出**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具" && rm -rf 输出_smoke_mti 输出_smoke_raw && echo cleaned
```

Expected：输出 `cleaned`。

---

### Task 5: 更新 使用说明.md

**Files:**
- Edit: `使用说明.md`

- [ ] **Step 5.1: 更新 §1 简介（应用名 + 工具集定位）**

Edit `使用说明.md`：

old_string:
```
# 风场数据统计工具 使用说明

## 1. 简介

本工具用于风场数据的批量统计与可视化，支持两种数据来源：
```

new_string:
```
# 气动组工具箱 使用说明

## 1. 简介

「气动组工具箱」是一个可扩展的工具集应用，目前包含以下工具：

- **风场数据统计**：风场数据的批量统计与可视化，支持两种数据来源：
```

说明：标题改「气动组工具箱」，§1 开头加"工具集"定位，原"两种数据来源"段降为「风场数据统计」工具的子项。

接着把 §1 原来的两个 `-` 列表项的缩进加一级（变成「风场数据统计」下的子项）。具体：找到原

```
- **秒级原始数据**：秒级时间序列文件（CSV/XLSX），自动完成风速清洗、湍流度（TI）滑动窗口计算、空气密度统计，并按日/周/月聚合出图。
- （从智慧风场导出时间、风速、密度秒级数据）
- **月度湍流表**：已经按月按风速 bin 预计算好的湍流度 Excel 文件，直接出每个风速 bin 的月度时间序列曲线。
- （从智慧风场导出月度湍流度）
```

整体缩进 2 空格（嵌套到「风场数据统计」项下）。

- [ ] **Step 5.2: 更新 §2.2 启动说明**

Edit `使用说明.md`：

old_string:
```
### 2.2 启动

方式一（双击启动）：双击 `运行.bat`

方式二（命令行）：

```bash
python src/main.py
```

启动后默认数据文件夹指向 `项目根目录\输入数据\`（即 `src/main.py` 上一级的 `输入数据\`，若存在），否则指向项目根目录。
```

new_string:
```
### 2.2 启动

方式一（双击启动）：双击 `运行.bat`

方式二（命令行）：

```bash
python src/main.py
```

启动后显示「气动组工具箱」主界面：**左侧导航栏**列出所有工具，**右侧内容区**显示当前选中工具的面板。默认选中「风场数据统计」，右侧立即显示风场统计 UI。

风场统计面板的默认数据文件夹指向 `项目根目录\输入数据\`（即 `src/tools/wind_farm_panel.py` 上两级的 `输入数据\`，若存在），否则指向项目根目录。
```

- [ ] **Step 5.3: 在 §4 界面操作开头新增「§4.0 左侧导航」**

Edit `使用说明.md`：

old_string:
```
## 4. 界面操作

主界面从上到下依次为：

### 4.1 数据文件夹
```

new_string:
```
## 4. 界面操作

主界面分左右两区：**左侧导航栏**（窄列，列出工具集所有工具）+ **右侧内容区**（当前选中工具的完整操作 UI）。点左侧条目切换右侧内容。当前版本只有「风场数据统计」一项。

下面的小节描述「风场数据统计」面板内部的控件，从上到下依次为：

### 4.0 左侧导航栏

- 控件：`QListWidget`，固定宽 160px，纯文字单列
- 当前条目：「风场数据统计」1 项
- 启动后默认选中第 1 项，右侧立即显示对应面板
- 未来加新工具时，此栏会自动多出条目（详见开发者文档/目录结构 §8）

### 4.1 数据文件夹
```

- [ ] **Step 5.4: 更新 §8 目录结构**

Edit `使用说明.md`：

old_string:
```
## 8. 目录结构

```
风场数据统计工具\
├── 运行.bat               # 双击启动入口（调用 python src\main.py）
├── 使用说明.md            # 本文档
├── src\                   # 所有源代码
│   ├── main.py            # GUI 入口（StatsWorker + MainWindow）
│   ├── config.py          # 所有常量（窗口/阈值/调色板/线型等）
│   ├── io_utils.py        # 文件扫描、读取、列识别
│   ├── processing.py      # 风速清洗、TI 滑窗、日级统计、周/月聚合
│   ├── ti_bin.py          # P90 / bin / 有效窗口统计
│   ├── plotting.py        # 所有绘图函数 + 叶型线型辅助
│   ├── export.py          # Excel 多 sheet 导出
│   └── pipeline.py        # 主流程编排（run / _run_monthly_ti）
├── 输入数据\              # 默认数据存放处
│   └── （用户投放的 CSV/XLSX 文件）
└── 输出\                  # 程序运行时自动创建
    ├── *.png              # 曲线图
    ├── 风场统计数据.xlsx  # 多 sheet 数据表
    └── .cache.pkl         # 读取缓存（可删）
```

**模块依赖关系（严格单向，无循环）**：

```
config ←─ io_utils ←─ processing ←─┐
config ←─ ti_bin ←──────────────────┤
config ←─ plotting ←────────────────┼─ pipeline ←─ main
config ←─ export ←──────────────────┘
```
```

new_string:
```
## 8. 目录结构

```
气动组工具箱\
├── 运行.bat               # 双击启动入口（调用 python src\main.py）
├── 使用说明.md            # 本文档
├── src\                   # 所有源代码
│   ├── main.py            # 入口 + ToolShell（左侧导航 + 右侧内容区壳）
│   ├── tools\             # 工具面板目录（每个工具一个文件）
│   │   ├── __init__.py    # 包标记
│   │   └── wind_farm_panel.py  # 风场数据统计面板（WindFarmStatsPanel + StatsWorker）
│   ├── config.py          # 所有常量（窗口/阈值/调色板/线型等）
│   ├── io_utils.py        # 文件扫描、读取、列识别
│   ├── processing.py      # 风速清洗、TI 滑窗、日级统计、周/月聚合
│   ├── ti_bin.py          # P90 / bin / 有效窗口统计
│   ├── plotting.py        # 所有绘图函数 + 叶型线型辅助
│   ├── export.py          # Excel 多 sheet 导出
│   └── pipeline.py        # 主流程编排（run / _run_monthly_ti）
├── 输入数据\              # 默认数据存放处
│   └── （用户投放的 CSV/XLSX 文件）
└── 输出\                  # 程序运行时自动创建
    ├── *.png              # 曲线图
    ├── 风场统计数据.xlsx  # 多 sheet 数据表
    └── .cache.pkl         # 读取缓存（可删）
```

**模块依赖关系（严格单向，无循环）**：

```
config ←─ io_utils ←─ processing ←─┐
config ←─ ti_bin ←──────────────────┤
config ←─ plotting ←────────────────┼─ pipeline ←─ tools.wind_farm_panel ←─ main
config ←─ export ←──────────────────┘
```

**加新工具的步骤**（开发者参考）：

1. 在 `src/tools/` 下新建 `xxx_panel.py`，实现 `XxxPanel(QWidget)` 子类
2. 在 `src/main.py` 顶部加 `from tools.xxx_panel import XxxPanel`
3. 在 `src/main.py` 的 `TOOLS` 列表加一行 `('工具显示名', XxxPanel)`
4. 重新启动应用，左侧导航栏自动出现新条目
```

- [ ] **Step 5.5: 验证文档更新**

Run：

```bash
cd "F:/python/风场失效/风场数据统计工具" && grep -n "气动组工具箱\|tools\\\\\|左侧导航\|加新工具的步骤" 使用说明.md
```

Expected：至少匹配 4 处（标题、tools/ 目录、§4.0 左侧导航、加新工具的步骤）。

Run（确认旧标题已替换）：

```bash
cd "F:/python/风场失效/风场数据统计工具" && grep -c "风场数据统计工具 使用说明" 使用说明.md
```

Expected：`0`（旧标题已被替换为「气动组工具箱 使用说明」）。

---

## 全局验收清单（所有 Task 完成后）

执行以下命令，全部通过即改造完成：

- [ ] **A. import 完整性**

```bash
cd "F:/python/风场失效/风场数据统计工具/src" && python -c "import main; from tools.wind_farm_panel import WindFarmStatsPanel, StatsWorker; print('all imports OK')"
```

Expected：`all imports OK`。

- [ ] **B. main.py 行数**

```bash
cd "F:/python/风场失效/风场数据统计工具" && wc -l src/main.py
```

Expected：约 60 行。

- [ ] **C. GUI 壳结构（headless 断言）**

复用 Task 3 Step 3.4 的脚本，Expected：`GUI shell OK`。

- [ ] **D. 业务零回归（monthly_ti + raw 冒烟）**

复用 Task 4 Step 4.1 + 4.2，Expected：分别 8 / 7 plots，error=None。

- [ ] **E. 残留检查（main.py 无业务方法）**

```bash
cd "F:/python/风场失效/风场数据统计工具" && grep -E "^    def " src/main.py
```

Expected：仅输出 `__init__` 和 `_on_nav_changed` 两个方法（ToolShell 的方法），无 `_build_ui` / `_on_start` 等业务方法残留。

- [ ] **F. 文档更新到位**

```bash
cd "F:/python/风场失效/风场数据统计工具" && grep -c "气动组工具箱" 使用说明.md
```

Expected：≥ 2（标题 + §2.2 + §8 等多处）。
