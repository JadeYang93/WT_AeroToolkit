# 气动组工具箱 GUI 架构改造 设计文档

> 日期：2026-06-19
> 状态：待实现
> 范围：把现有"风场数据统计工具"改造为"气动组工具箱"中的一个功能

## 1. 目标

把单一用途的"风场数据统计工具"重构为可扩展的"工具集"应用：

- 应用名改为「气动组工具箱」
- 左侧加导航栏，承载多个工具的入口
- 当前只有一个功能「风场数据统计」可用，未来按需添加
- 现有风场统计的业务逻辑、算法、输出格式零变化

## 2. 整体架构

应用分两层：

**ToolShell（壳）** —— 顶层 QMainWindow，承载：

- 左侧 QListWidget（导航，固定宽 160px，纯文字单列）
- 右侧 QStackedWidget（内容区，每次显示一个工具的面板）

**ToolPanel（面板）** —— 每个工具是一个 QWidget 子类。当前只有：

- `WindFarmStatsPanel`：由原 `MainWindow` 改造（基类 `QMainWindow` → `QWidget`）

切换逻辑：`QListWidget.currentRowChanged` 信号 → `QStackedWidget.setCurrentIndex` 槽。启动后默认选中第一个工具。

## 3. 文件结构（tools/ 包）

```
src/
├── main.py                 # 瘦身：ToolShell + main()，~100 行
├── tools/
│   ├── __init__.py         # 空，标记为 Python 包
│   └── wind_farm_panel.py  # WindFarmStatsPanel + StatsWorker（从 main.py 迁出）
├── config.py               # 不动
├── io_utils.py             # 不动
├── processing.py           # 不动
├── ti_bin.py               # 不动
├── plotting.py             # 不动
├── export.py               # 不动
└── pipeline.py             # 不动
```

依赖方向严格单向：

```
main → tools.wind_farm_panel → pipeline → {io_utils, processing, ti_bin, plotting, export} → config
```

未来加新工具：在 `tools/` 下新建 `xxx_panel.py`，实现 `XxxPanel(QWidget)`，在 main.py 的 `TOOLS` 注册表加一行。

## 4. 关键类设计

### 4.1 ToolShell（src/main.py）

```python
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout,
    QListWidget, QStackedWidget,
)
from tools.wind_farm_panel import WindFarmStatsPanel


# 工具注册表：顺序决定导航栏顺序；新增工具在此追加一行
TOOLS = [
    ('风场数据统计', WindFarmStatsPanel),
]


class MainWindow(QMainWindow):
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

        # 注册工具（按 TOOLS 顺序）
        for name, panel_cls in TOOLS:
            panel = panel_cls()
            self.nav_list.addItem(name)
            self.content_stack.addWidget(panel)

        layout.addWidget(self.nav_list)
        layout.addWidget(self.content_stack, 1)
        self.setCentralWidget(central)

        # 默认选中第一个
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

### 4.2 WindFarmStatsPanel（src/tools/wind_farm_panel.py）

由原 `MainWindow` 改造，改动点（最小集）：

| 改动 | 原代码 | 新代码 |
|---|---|---|
| 基类 | `class MainWindow(QMainWindow)` | `class WindFarmStatsPanel(QWidget)` |
| 窗口标题 | `self.setWindowTitle('风场数据统计工具')` | 删除（壳统一管理） |
| 窗口尺寸 | `self.resize(820, 760)` | 删除（壳统一管理） |
| UI 容器 | `central = QWidget(); self.setCentralWidget(central); layout = QVBoxLayout(central)` | `layout = QVBoxLayout(self)` |
| 项目路径 | `__file__` 算一层 `dirname` 到项目根（main.py 在 src/） | `__file__` 算**两层** `dirname`（wind_farm_panel.py 在 src/tools/） |

其余所有方法（`_refresh_turbine_lists` / `_refresh_blade_styles` / `_on_start` / `_on_progress` / `_on_finished` / `_build_ui` 内部全部逻辑）**原样搬迁**，零算法改动。

路径处理（这是改造中唯一需要小心的细节）：

```python
script_dir = os.path.dirname(os.path.abspath(__file__))
# wind_farm_panel.py 在 src/tools/，需要再上一层到项目根
project_dir = os.path.dirname(script_dir)
default_input = os.path.join(project_dir, '输入数据')
self.data_dir = default_input if os.path.isdir(default_input) else project_dir
self.out_dir = os.path.join(project_dir, '输出')
self.cache_path = os.path.join(self.out_dir, '.cache.pkl')
```

### 4.3 StatsWorker

不变，随 panel 一起迁到 wind_farm_panel.py。仍然是 QThread 子类，调用 `pipeline.run(...)`。

## 5. 导航栏视觉规格

- 控件：`QListWidget`
- 宽度：固定 160px
- 内容：纯文字（无图标），单列
- 当前条目数：1（"风场数据统计"）
- 选中样式：QListWidget 默认高亮（系统主题色）
- 未来扩展：加新工具时只需在 `TOOLS` 注册表加一行 + 新建对应 panel 文件

## 6. 影响范围

**新建**：

- `src/tools/__init__.py`（空文件，标记为 Python 包）
- `src/tools/wind_farm_panel.py`（从 main.py 迁移 MainWindow + StatsWorker + 基类改造）

**改造**：

- `src/main.py`：从 ~690 行瘦身到 ~60 行（ToolShell + `TOOLS` + `main()`）。原 MainWindow 类的所有业务方法整体迁出。
- `使用说明.md`：
  - 1. 简介：应用名改"气动组工具箱"，定位为"工具集"
  - 2.2 启动：说明启动后看到工具集界面，左侧导航 + 右侧默认显示"风场数据统计"面板
  - 4. 界面操作：新增"4.0 左侧导航"小节
  - 8. 目录结构：重画为含 `tools/` 子目录的树

**不动**：

- `运行.bat`（命令 `python src\main.py` 不变）
- `src/config.py` / `io_utils.py` / `processing.py` / `ti_bin.py` / `plotting.py` / `export.py` / `pipeline.py`
- 所有业务逻辑、算法、输出格式

## 7. 不做（Out of Scope）

- 不加图标、不分组、不加"待开发"占位项（YAGNI，未来按需扩展）
- 不引入跨 panel 状态共享机制（当前每个 panel 独立）
- 不改 `运行.bat` 启动命令
- 不动底层 7 个业务模块
- 不为未来工具预留抽象基类（如 `ToolPanel`）——当前只有 1 个 panel，YAGNI；未来加第 2 个时再抽象

## 8. 验收标准

1. `python src/main.py` 启动后弹出"气动组工具箱"窗口（标题栏显示），左侧显示"风场数据统计"导航条
2. 右侧立即显示完整的风场统计 UI（数据类型选择/扫描/选项表/参数/日期/开始按钮/进度条/日志）
3. 完整跑一遍 monthly_ti + raw 两模式，输出与改造前一致（图数、Excel sheet 内容、文件名）
4. import 完整性检查：`cd src && python -c "import main"` 无 ImportError
5. 残留检查：`grep -n "^    def " src/main.py` 应只列出 ToolShell 的方法（`__init__` / `_on_nav_changed`），无业务方法

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| `wind_farm_panel.py` 路径计算多套一层 `dirname` 导致输出写到错误位置 | §4.2 已显式标注两层 dirname；实现后用冒烟测试验证输出落在项目根的 `输出/` |
| 改造时漏迁原 MainWindow 某方法 | 实现后用 `grep "^    def " src/main.py` 对比 wind_farm_panel.py 的 def 列表，diff 应为空 |
| QListWidget 默认无选中项导致右侧空白 | ToolShell 构造末尾 `setCurrentRow(0)` 兜底（已在代码示例中包含） |
