# CATIA 叶片建模模块设计

> 日期：2026-06-25
> 状态：设计稿（待用户审阅）
> 关联：叶片形状输出 STAGE-3 的下游 CATIA 建模环节

## 1. 背景与目标

### 1.1 背景

`参考代码/` 目录下有三个 CATIA 自动化脚本（均依赖 `pywin32`，本机已安装）：

| 脚本 | 职责 | CATIA 输入 | 产出几何集 |
|---|---|---|---|
| `Pre-process.py` | **截面构建**：点云 → 样条 → 光顺 → 平面 → 前缘/尾缘点 → 弦线 | 命名为 `Sect{组}_{点}` 的点云 | `Z_Splines` / `Z_Smooths` / `Z_Planes` / `Z_Edges` / `Z_TrailingEdges` |
| `1227-2opt.py` | **重采样优化**：对已有样条等距重采样（默认 149 点）→ 重新样条 + 光顺 | `line` 几何集里的样条 | `点集` / `OriginalSplines` / `Smoothed1` |
| `lin2surface.py` | **蒙皮成型**：多条光顺截面线 → 多截面曲面（Loft） | `Z_Smooths` 几何集 | `loft_surface`（叶片曲面） |

三者构成一条 CATIA 内的建模流水线：**点云 → 截面样条 →（可选重采样）→ 多截面曲面**。

### 1.2 与现有工具的衔接点

"叶片形状输出"面板 STAGE-3 的 `write_step_points_file`（`src/shape_design/exporters.py:240`）导出的 `3D_points.stp`，其点命名正是：

```
Sect{sec+1}_{point+1}   （1-based，如 Sect1_1, Sect1_2 ... Sect96_399）
```

该命名与 `Pre-process.py` 里 `parameters.Item(f"Sect{group_num}_{point_num}")` 的查找约定**完全一致**。因此 `3D_points.stp` 导入 CATIA 后，点即带 `Sect{组}_{点}` 名，可直接喂给截面构建步骤——这是一条天然的数据流。

### 1.3 目标

把这三个脚本封装为工具箱的一个**独立侧边栏模块**「📐 CATIA 叶片建模」，让用户：

1. 在 CATIA 中导入 `3D_points.stp`（手动，CATIA 导入 STP 是交互式操作）
2. 在工具箱面板上**按需点击三个单步按钮**，依次驱动 CATIA 完成截面构建、重采样、蒙皮
3. 全程在面板日志区看到进度与提示；CATIA 未启动 / 文档未打开时给出友好提示而非崩溃

**非目标**：
- 不自动导入 STP 到 CATIA（CATIA 的 STP 导入是交互式向导，自动化收益低且易出错，由用户手动完成）
- 不替代 CATIA 的曲面质量检查（最终曲面是否满足建模要求仍由工程师在 CATIA 里目视确认）
- 不做 CATIA 版本适配（假设 V5，与参考脚本一致）

## 2. 关键决策（已与用户确认）

| 决策点 | 选择 | 说明 |
|---|---|---|
| 模块形态 | 侧边栏独立工具 | 与"叶片形状输出"解耦，独立管理输入/日志/错误 |
| 环境依赖处理 | 运行时检测 + 友好提示 | 点运行时 `try` 连接 CATIA，失败弹窗引导；未装 CATIA 不影响其他模块 |
| 三步呈现 | 三个独立单步按钮 | 用户自主决定跑哪步、对哪个文档跑；不强制一键顺序 |
| 输入文件管理 | 文件选择框，默认指向 STAGE-3 输出 | 默认 `输出/shape_design/stage3/CATIA/3D_points.stp`，可手动改 |
| 代码组织 | 方案 A：子包 + 纯函数 | 与 `shape_design/`、`focus6_solver/` 等现有 8 个模块结构一致 |

## 3. 架构设计

### 3.1 模块定位

在导航栏"叶片形状输出"之后新增一项「📐 CATIA 叶片建模」。注册到 `TOOLS` 列表（`src/main.py`），紧跟在预弯设计之后（或按用户偏好的位置）。

```
src/
├── main.py                          # TOOLS 列表加一行
├── catia_modeling/                  # 新增业务子包
│   ├── __init__.py                  # 导出公共 API
│   ├── context.py                   # CatiaContext：连接 + 文档句柄封装
│   ├── sections.py                  # build_sections() —— 对应 Pre-process.py
│   ├── resample.py                  # resample_and_smooth() —— 对应 1227-2opt.py
│   ├── loft.py                      # build_loft_surface() —— 对应 lin2surface.py
│   └── exceptions.py                # CatiaNotRunningError / NoActiveDocumentError 等
└── tools/
    └── catia_modeling_panel.py      # 新增 UI 面板（继承 BaseWorkerPanel）
```

### 3.2 分层职责

```
┌─────────────────────────────────────────────────────┐
│  catia_modeling_panel.py  (UI 编排层)                │
│  - 三个单步按钮 + 输入文件选择 + 参数区 + 执行栏     │
│  - CatiaModelingWorker(QThread) × 3                  │
│  - 运行前 try 连接 CATIA，失败友好弹窗               │
└──────────────────┬──────────────────────────────────┘
                   │ 调用纯函数（传 params + progress_callback）
                   ▼
┌─────────────────────────────────────────────────────┐
│  catia_modeling/  (业务逻辑层，无 PyQt 依赖)         │
│  - CatiaContext：封装 catia.app / partDocument / part│
│  - build_sections(ctx, params, cb)                   │
│  - resample_and_smooth(ctx, params, cb)              │
│  - build_loft_surface(ctx, params, cb)               │
└─────────────────────────────────────────────────────┘
```

业务层完全不 import PyQt，可被任何调用方（UI Worker、命令行脚本、测试）复用——这是项目既有的解耦规范（见 `base_module_panel.py` 注释）。

### 3.3 CatiaContext 设计

三个脚本共享大量样板（获取 `part`、`hybridShapeFactory`、`spaWorkbench`、`measure_point`、几何集管理）。抽象为一个 context 对象：

```python
# catia_modeling/context.py（核心接口）
class CatiaContext:
    """CATIA 连接 + 当前文档句柄的封装。三个建模步骤共用。"""

    def __init__(self):
        self.catia = win32.Dispatch("CATIA.Application")
        self.catia.Visible = True
        doc = self.catia.ActiveDocument
        if doc is None:
            raise NoActiveDocumentError("CATIA 没有打开的文档")
        self.part_document = doc
        self.part = doc.Part
        self.hybrid_shape_factory = part.HybridShapeFactory
        self.spa_workbench = doc.GetWorkbench("SPAWorkbench")

    def measure_point(self, ref) -> list[float]:
        """测量点坐标（封装参考脚本的 VBA Evaluate 方法）。"""

    def ensure_hybrid_body(self, name: str):
        """获取或创建几何集，不存在则新建。"""

    def create_reference(self, obj):
        return self.part.CreateReferenceFromObject(obj)
```

**连接生命周期**：每次点"运行"在 Worker 线程里 `CatiaContext()` 新建，跑完即释放（COM 对象不跨调用缓存，避免文档切换后的悬空句柄）。

### 3.4 三个步骤函数签名

全部统一为 `(ctx, params, progress_callback) -> dict`：

```python
# sections.py —— 对应 Pre-process.py
def build_sections(ctx, params: SectionParams, progress_callback=None) -> dict:
    """点云 → 每截面样条 + 光顺 + 平面 + 前缘/尾缘点 + 弦线。

    params:
        num_groups: int           截面数（参考脚本默认 96）
        start_group: int          起始组号（默认 1）
        smooth_thresholds: tuple  四段光顺阈值（默认 (4,3,2,1)）
        spline_set: str           样条输出几何集名（默认 'Z_Splines'）
        ...
    返回: {'sections_built': int, 'z_values': [...]}
    """

# resample.py —— 对应 1227-2opt.py
def resample_and_smooth(ctx, params: ResampleParams, progress_callback=None) -> dict:
    """对已有样条等距重采样 + 重新样条 + 光顺。

    params:
        source_set: str           源样条几何集名（默认 'line'）
        num_points: int           每条曲线重采样点数（默认 149）
        smooth_threshold: float   光顺阈值（默认 1.0）
        ...
    返回: {'curves_processed': int}
    """

# loft.py —— 对应 lin2surface.py
def build_loft_surface(ctx, params: LoftParams, progress_callback=None) -> dict:
    """多条截面曲线 → 多截面曲面（Loft）。

    params:
        source_set: str           源曲线几何集名（默认 'Z_Smooths'）
        section_coupling: int     截面耦合方式（默认 1）
        ...
    返回: {'surface_name': str, 'section_count': int}
    """
```

`progress_callback(msg: str)` 每完成一个截面/曲线回调一次，由 Worker 映射到进度百分比。

### 3.5 参数化（硬编码 → 可调）

参考脚本的硬编码全部参数化，默认值取脚本原值，UI 暴露最常用的几个：

| 参数 | 来源脚本 | 默认值 | UI 是否暴露 |
|---|---|---|---|
| 截面数 `num_groups` | Pre-process | 96 | ✅ |
| 起始组号 `start_group` | Pre-process | 1 | ✅ |
| 光顺阈值 `smooth_thresholds` | Pre-process | (4,3,2,1) | ✅（四段） |
| 重采样点数 `num_points` | 1227-2opt | 149 | ✅ |
| 光顺阈值（重采样） | 1227-2opt | 1.0 | ✅ |
| 源几何集名（重采样）`source_set` | 1227-2opt | `line` | ✅ |
| 源几何集名（蒙皮）`source_set` | lin2surface | `Z_Smooths` | ✅ |

### 3.6 数据流

```
[叶片形状输出 STAGE-3]
      │ 输出 3D_points.stp（点命名 Sect{组}_{点}）
      ▼
[用户在 CATIA 手动导入 STP → 点云带命名]
      │
      ▼ 点「① 构建截面」按钮
[build_sections] → Z_Splines / Z_Smooths / Z_Planes / Z_Edges / Z_TrailingEdges
      │
      ▼ （用户在 CATIA 检查后）点「② 重采样光顺」按钮
[resample_and_smooth] → 点集 / OriginalSplines / Smoothed1
      │
      ▼ （用户在 CATIA 检查后）点「③ 生成曲面」按钮
[build_loft_surface] → loft_surface（叶片蒙皮曲面）
```

三个步骤间**无内存数据传递**——全部通过 CATIA 文档内的几何集交互。用户在每步之间可以在 CATIA 里检查、删改几何集，再决定是否继续下一步。这正是"三个独立单步按钮"模式的价值。

## 4. UI 设计

继承 `BaseWorkerPanel`（`src/tools/base_module_panel.py:170`），复用其 banner + 执行栏 + 通用信号槽。

### 4.1 布局

```
┌─ banner：CATIA 叶片建模 / C A T I A   B L A D E   M O D E L I N G ─┐
├──────────────────────────────────────────────────────────────────────┤
│ ┌ 输入文件 ──────────────────────────────────────────────────────┐ │
│ │ STP 点云文件: [输出/shape_design/stage3/CATIA/3D_points.stp] …│ │
│ │              （默认指向 STAGE-3，可手动改；提示：先在 CATIA    │ │
│ │               手动导入此文件，点云需带 Sect{组}_{点} 命名）    │ │
│ └────────────────────────────────────────────────────────────────┘ │
│ ┌ 三个步骤（每步独立运行，按钮禁用条件见下） ───────────────────┐ │
│ │  [① 构建截面]  截面数[96] 起始组[1] 光顺阈值[4][3][2][1]      │ │
│ │  [② 重采样光顺] 源集[line] 点数[149] 光顺阈值[1.0]            │ │
│ │  [③ 生成曲面]  源集[Z_Smooths]                                │ │
│ └────────────────────────────────────────────────────────────────┘ │
├─ 执行栏（320px 左：当前步进度 + 日志区右） ───────────────────────┤
│ [运行当前步]  [📂打开输出目录]   日志:                            │
│ [████████░░░░░░░░] 60%         ┌──────────────────────────────┐  │
│                                │ [① 构建截面] 连接 CATIA...     │  │
│                                │ 处理样条: Sect1, 长度: 3.2m   │  │
│                                │ ...                            │  │
│                                └──────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.2 控件与状态

- **输入文件区**：`QLineEdit` + 浏览按钮 `…`。默认值从 `config_center.get_paths('shape_design')` 推导出 `<shape_design 输出>/stage3/CATIA/3D_points.stp`。该框仅作提示/记录，**实际不通过它把文件传给 CATIA**（CATIA 的 STP 导入由用户手动完成）。
- **三个步骤按钮**：各自一组参数控件 + 一个运行按钮。点某按钮 → 跑对应步骤 → 进度/日志进入下方执行栏。
- **执行栏**：复用 `BaseWorkerPanel._build_exec_bar()`，但运行按钮文字动态显示当前步（"运行① 构建截面"等）。

### 4.3 运行时检测

点任一步骤按钮，UI 线程**先做轻量探测**：

```python
def _on_run_step(self, step):
    if not self._check_catia_available():   # try win32 GetActiveObject / Dispatch
        QMessageBox.warning(self, '未检测到 CATIA',
            '请先启动 CATIA 并打开零件文档（.CATPart），\n'
            '再点击运行。')
        return
    # 启动 Worker
```

Worker 线程内 `CatiaContext()` 再做一次正式连接（双重保险，因为探测到运行也可能中途 CATIA 被关）。连接失败抛 `CatiaNotRunningError` / `NoActiveDocumentError`，Worker 捕获后通过 `progress` 信号回传错误文本，UI 弹 `QMessageBox.critical`。

## 5. 错误处理

| 场景 | 处理 |
|---|---|
| 未装 CATIA / CATIA 未启动 | UI 探测阶段弹窗，不进入 Worker |
| CATIA 已启动但无活动文档 | Worker 内 `NoActiveDocumentError` → 回传 → 弹窗 |
| 点云缺少 `Sect{组}_{点}` 命名 | `build_sections` 内 `parameters.Item()` 抛异常 → 捕获 → 日志提示"请确认已导入 STP 且点带命名" |
| 源几何集不存在（如重采样时无 `line` 集） | 函数内显式检查 → 抛 `GeoSetNotFoundError` → 日志提示先跑上一步 |
| 单个截面处理失败 | 参考脚本已有 `try/except continue` 模式，保留——失败截面跳过，日志记录，不中断整体 |
| COM 调用异常 | Worker 顶层 `try/except` 捕获 traceback → 回传 → 弹窗 |

## 6. 集成点清单（改动现有文件）

| 文件 | 改动 |
|---|---|
| `src/main.py` | `TOOLS` 列表新增 `('📐 CATIA 叶片建模', CatiaModelingPanel)` + import |
| `src/tools/__init__.py` | 无需改（panel 不在此导出） |
| `requirements.txt` | 新增 `pywin32 >= 305`（注释说明仅 CATIA 模块需要） |
| `src/help/` | 新增 `catia_modeling.md` 帮助文档 |
| 帮助菜单（如 `help_viewer.py` 注册了模块帮助） | 注册新文档 |

**不改动**任何现有模块代码——CATIA 模块完全新增，与叶片形状输出解耦（仅在 UI 默认路径上"软引用"其输出目录）。

## 7. 测试策略

CATIA 自动化无法在 CI 环境（无 CATIA 实例）做端到端测试，采用分层策略：

1. **纯函数/参数对象**：`SectionParams` / `ResampleParams` / `LoftParams` 的构造与校验逻辑（如四段阈值的边界分段计算）可单元测试，无 CATIA 依赖。
2. **CatiaContext 与三个步骤函数**：通过 `unittest.mock` mock `win32.Dispatch` 返回的对象图，验证：
   - 几何集不存在时正确创建
   - 进度回调按预期次数触发
   - 异常路径（无文档、点缺失）抛出正确异常类型
3. **UI 面板**：人工测试（需 CATIA 环境）。重点验证：CATIA 未启动时的友好提示、三步独立运行、日志输出。

## 8. 开放问题（实现阶段再定）

- **几何集命名约定**：参考脚本里 `Pre-process.py` 用 `Z_Smooths`，`lin2surface.py` 也默认读 `Z_Smooths`——衔接是通的。但 `1227-2opt.py` 默认读 `line`、写 `Smoothed1`，与另两个脚本的命名不在同一套体系。实现时是否要把三步的默认几何集名统一成一套（如都走 `Z_*`），还是在 UI 上让用户自填源/目标集名？**倾向后者（用户自填，默认值保留参考脚本原值）**，灵活性最高且不破坏参考脚本语义。
- **CATIA 版本兼容**：参考脚本针对 CATIA V5。若团队用 V6 / 3DEXPERIENCE，COM 接口不同——首版只支持 V5，文档注明。
