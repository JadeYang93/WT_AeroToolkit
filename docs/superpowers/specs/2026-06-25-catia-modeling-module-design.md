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
| 参数暴露 | 核心参数直露 + 高级参数折叠 | 每步 GroupBox 直露 3~4 个核心参数；勾选「高级参数」展开后可调全部 24 个 |
| 参数持久化 | 记住上次值（独立 JSON） | 调过的参数写入 `配置/catia_modeling_params.json`，下次打开自动恢复 |

## 3. 架构设计

### 3.1 模块定位

在导航栏"叶片形状输出"之后新增一项「📐 CATIA 叶片建模」。注册到 `TOOLS` 列表（`src/main.py`），紧跟在预弯设计之后（或按用户偏好的位置）。

```
src/
├── main.py                          # TOOLS 列表加一行
├── catia_modeling/                  # 新增业务子包
│   ├── __init__.py                  # 导出公共 API
│   ├── context.py                   # CatiaContext：连接 + 文档句柄封装
│   ├── sections.py                  # build_sections() + SectionParams
│   ├── resample.py                  # resample_and_smooth() + ResampleParams
│   ├── loft.py                      # build_loft_surface() + LoftParams
│   ├── params_store.py              # load_params()/save_params() 参数持久化
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
        source_set: str           源样条几何集名（默认 'Z_Smooths'，承接①输出）
        num_points: int           每条曲线重采样点数（默认 149）
        smooth_threshold: float   光顺阈值（默认 1.0）
        ...
    返回: {'curves_processed': int}
    """

# loft.py —— 对应 lin2surface.py
def build_loft_surface(ctx, params: LoftParams, progress_callback=None) -> dict:
    """多条截面曲线 → 多截面曲面（Loft）。

    params:
        source_set: str           源曲线几何集名（默认 'Z_ResampleSmooth'，承接②输出）
        section_coupling: int     截面耦合方式（默认 1）
        ...
    返回: {'surface_name': str, 'section_count': int}
    """
```

`progress_callback(msg: str)` 每完成一个截面/曲线回调一次，由 Worker 映射到进度百分比。

### 3.5 参数化（硬编码 → 可调）

参考脚本共有 **24 个可配置参数**。采用「核心直露 + 高级折叠」分层：每个步骤的 GroupBox 顶部直接摆放 3~4 个核心参数；GroupBox 底部一个「⚙ 高级参数」勾选框，勾选后展开剩余参数。所有参数**记住上次值**（见 3.7）。

#### 步骤 ① 构建截面（对应 Pre-process.py）

| 参数 | 字段名 | 默认 | 层级 | 含义 |
|---|---|---|---|---|
| 截面数 | `num_groups` | 96 | 核心 | 截面总数 |
| 起始组号 | `start_group` | 1 | 核心 | 起始组号（可只跑某段） |
| 四段光顺阈值 | `smooth_thresholds` | (4,3,2,1) | 核心 | 前1/4、中两段、后1/4 各段阈值 |
| 每截面点数上限 | `points_per_section` | 400 | 高级 | 点序号遍历上限 `range(1, 400)` |
| 前缘点序号 | `le_point_num` | 200 | 高级 | 取作前缘的点序号 |
| 尾缘点1序号 | `te_point1_num` | 1 | 高级 | 取作尾缘的左点序号 |
| 尾缘点2序号 | `te_point399_num` | 399 | 高级 | 取作尾缘的右点序号 |
| 相切阈值 | `tangency_threshold` | 0.5 | 高级 | `SetTangencyThreshold`（全截面共用） |
| 校正模式 | `correction_mode` | 3 | 高级 | `CorrectionMode` |
| 样条输出集名 | `spline_set` | `Z_Splines` | 高级 | 样条输出几何集 |
| 光顺输出集名 | `smooth_set` | `Z_Smooths` | 高级 | 光顺曲线几何集 |
| 平面输出集名 | `plane_set` | `Z_Planes` | 高级 | 平面几何集 |
| 边缘输出集名 | `edge_set` | `Z_Edges` | 高级 | 前缘点+弦线几何集 |
| 尾缘输出集名 | `te_set` | `Z_TrailingEdges` | 高级 | 尾缘点几何集 |

#### 步骤 ② 重采样光顺（对应 1227-2opt.py）

| 参数 | 字段名 | 默认 | 层级 | 含义 |
|---|---|---|---|---|
| 源样条集名 | `source_set` | `Z_Smooths` | 核心 | 从哪个几何集读样条（承接①输出） |
| 重采样点数 | `num_points` | 149 | 核心 | 每条曲线等距重采样点数 |
| 光顺偏差阈值 | `smooth_max_deviation` | 1.0 | 核心 | `SetMaximumDeviation` |
| 相切阈值 | `tangency_threshold` | 0.5 | 高级 | `SetTangencyThreshold` |
| 校正模式 | `correction_mode` | 3 | 高级 | `CorrectionMode` |
| 点集输出集名 | `point_set` | `Z_ResamplePoints` | 高级 | 重采样点几何集 |
| 原始样条集名 | `original_set` | `Z_OriginalSpline` | 高级 | 重采样后原始样条几何集 |
| 光顺输出集名 | `smooth_set` | `Z_ResampleSmooth` | 高级 | 光顺曲线几何集（喂给③） |

#### 步骤 ③ 生成曲面（对应 lin2surface.py）

| 参数 | 字段名 | 默认 | 层级 | 含义 |
|---|---|---|---|---|
| 源曲线集名 | `source_set` | `Z_ResampleSmooth` | 核心 | 从哪个几何集读截面曲线（承接②输出） |
| 截面耦合方式 | `section_coupling` | 1 | 核心 | `SectionCoupling` |
| 重新限定 | `relimitation` | 1 | 高级 | `Relimitation` |
| 规范检测 | `canonical_detection` | 2 | 高级 | `CanonicalDetection` |

> 共 14 + 8 + 4 = 26 行（其中含 2 个枚举说明），实际参数字段 24 个。核心参数 3+3+2 = 8 个直露，高级参数 16 个折叠。

### 3.6 参数校验

参数对象（`SectionParams` / `ResampleParams` / `LoftParams`，dataclass）构造时做基本校验：

- 数值范围：`num_groups >= 1`、`num_points >= 2`、阈值 `>= 0`、点序号 `>= 1`
- 四段阈值：长度必须为 4（否则无法分段）
- 几何集名：非空字符串（CATIA 对中英文名都兼容）

校验失败在 UI 层拦截（点运行时 `QMessageBox.warning`），不进入 Worker。

### 3.7 参数持久化（记住上次值）

项目现有的 `ConfigCenter` 是为**路径型字段**设计的（带路径校验、相对/绝对转换，见 `global_config.py:215 set_extra`），用它存数值参数（阈值 0.5、点数 149、数组 (4,3,2,1)）会触发路径校验报错。项目里也无现成的数值参数持久化先例（curve_fitter 等参数都是每次用默认值）。

因此 CATIA 模块新建一个**独立轻量存储**：

```
配置/catia_modeling_params.json
```

格式（按步骤分组，扁平 key-value）：

```json
{
  "sections": {
    "num_groups": 96,
    "start_group": 1,
    "smooth_thresholds": [4, 3, 2, 1],
    "points_per_section": 400,
    "le_point_num": 200,
    "te_point1_num": 1,
    "te_point399_num": 399,
    "tangency_threshold": 0.5,
    "correction_mode": 3,
    "spline_set": "Z_Splines",
    "smooth_set": "Z_Smooths",
    "plane_set": "Z_Planes",
    "edge_set": "Z_Edges",
    "te_set": "Z_TrailingEdges"
  },
  "resample": {
    "source_set": "Z_Smooths",
    "num_points": 149,
    "smooth_max_deviation": 1.0,
    "tangency_threshold": 0.5,
    "correction_mode": 3,
    "point_set": "Z_ResamplePoints",
    "original_set": "Z_OriginalSpline",
    "smooth_set": "Z_ResampleSmooth"
  },
  "loft": {
    "source_set": "Z_ResampleSmooth",
    "section_coupling": 1,
    "relimitation": 1,
    "canonical_detection": 2
  }
}
```

读写职责（封装在 `catia_modeling/params_store.py`）：

- `load_params() -> dict`：文件不存在或解析失败 → 返回全默认值（容错，不抛异常）
- `save_params(params: dict)`：原子写（先写临时文件再 rename，避免中途崩溃损坏）
- 输入文件路径（STP）也一并存入 JSON 的 `input.stp_path` 字段

UI 触发时机：**运行按钮点击时**读取构造参数对象（同时若值非默认则存盘），**面板初始化时**读取回填到各控件。即「记忆的是上次成功运行的那组值」。高级折叠框的展开/收起状态也存盘（`ui.advanced_expanded` 字段），避免每次重新展开。

> 放在 `配置/` 而非模块输出目录：参数是「工具配置」而非「运行产物」，与 `ConfigCenter` 的 JSON 同级、可手动编辑、可随包分发。

### 3.8 数据流

```
[叶片形状输出 STAGE-3]
      │ 输出 3D_points.stp（点命名 Sect{组}_{点}）
      ▼
[用户在 CATIA 手动导入 STP → 点云带命名]
      │
      ▼ 点「① 构建截面」按钮
[build_sections] 读点云 → 写 Z_Splines / Z_Smooths / Z_Planes / Z_Edges / Z_TrailingEdges
      │
      ▼ （用户在 CATIA 检查后）点「② 重采样光顺」按钮
[resample_and_smooth] 读 Z_Smooths → 写 Z_ResamplePoints / Z_OriginalSpline / Z_ResampleSmooth
      │
      ▼ （用户在 CATIA 检查后）点「③ 生成曲面」按钮
[build_loft_surface] 读 Z_ResampleSmooth → 写 loft_surface（叶片蒙皮曲面）
```

三个步骤间**无内存数据传递**——全部通过 CATIA 文档内的几何集交互。用户在每步之间可以在 CATIA 里检查、删改几何集，再决定是否继续下一步。这正是"三个独立单步按钮"模式的价值。

**几何集命名衔接（重要修正）**：参考脚本 `1227-2opt.py` 的源集名硬编码为 `line`，与主线 `Z_*` 体系不一致。集成时默认改为读 **`Z_Smooths`**（承接步骤①输出）、写 `Z_*` 系列（见下表），使三步默认即可串联。用户仍可在高级参数里改写任意集名。

| 步骤 | 默认读 | 默认写 |
|---|---|---|
| ① 构建截面 | 点云 `Sect{组}_{点}` | `Z_Splines` / `Z_Smooths` / `Z_Planes` / `Z_Edges` / `Z_TrailingEdges` |
| ② 重采样光顺 | **`Z_Smooths`** | `Z_ResamplePoints` / `Z_OriginalSpline` / `Z_ResampleSmooth` |
| ③ 生成曲面 | **`Z_ResampleSmooth`** | `loft_surface` |

## 4. UI 设计

继承 `BaseWorkerPanel`（`src/tools/base_module_panel.py:170`），复用其 banner + 执行栏 + 通用信号槽。

### 4.1 布局

「核心直露 + 高级折叠」—— 每步 GroupBox 顶部直接摆核心参数，底部一个 `☐ 高级参数` 勾选框，勾选后展开 QGridLayout 容纳剩余参数。

```
┌─ banner：CATIA 叶片建模 / C A T I A   B L A D E   M O D E L I N G ─┐
├──────────────────────────────────────────────────────────────────────┤
│ ┌ 输入文件 ──────────────────────────────────────────────────────┐ │
│ │ STP 点云文件: [输出/shape_design/stage3/CATIA/3D_points.stp] …│ │
│ │ （提示：先在 CATIA 手动导入此文件，点云需带 Sect{组}_{点} 命名）│ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│ ┌ ① 构建截面 ────────────────────────────────────────────────────┐ │
│ │ 截面数[ 96 ]   起始组[ 1 ]                                      │ │
│ │ 四段光顺阈值[4][3][2][1]                                         │ │
│ │ ☐ 高级参数                                                      │ │
│ │   ┌─ 勾选后展开 ───────────────────────────────────────────┐  │ │
│ │   │ 点数上限[400] 前缘点[200] 尾缘点1[1] 尾缘点2[399]       │  │ │
│ │   │ 相切阈值[0.5] 校正模式[3]                                │  │ │
│ │   │ 样条集[Z_Splines] 光顺集[Z_Smooths] 平面集[Z_Planes]    │  │ │
│ │   │ 边缘集[Z_Edges] 尾缘集[Z_TrailingEdges]                 │  │ │
│ │   └─────────────────────────────────────────────────────────┘  │ │
│ └────────────────────────────────────────────────────────────────┘ │
│ ┌ ② 重采样光顺 ──────────────────────────────────────────────────┐ │
│ │ 源样条集[Z_Smooths]  重采样点数[ 149 ]  光顺偏差阈值[ 1.0 ]    │ │
│ │ ☐ 高级参数                                                      │ │
│ │   ┌─ 勾选后展开 ───────────────────────────────────────────┐  │ │
│ │   │ 相切阈值[0.5] 校正模式[3]                                │  │ │
│ │   │ 点集[Z_ResamplePts] 原始样条[Z_OrigSpline] 光顺[Z_ResSmooth]│  │ │
│ │   └─────────────────────────────────────────────────────────┘  │ │
│ └────────────────────────────────────────────────────────────────┘ │
│ ┌ ③ 生成曲面 ────────────────────────────────────────────────────┐ │
│ │ 源曲线集[Z_ResSmooth]  截面耦合方式[ 1 ]                        │ │
│ │ ☐ 高级参数                                                      │ │
│ │   ┌─ 勾选后展开 ───────────────────────────────────────────┐  │ │
│ │   │ 重新限定[1] 规范检测[2]                                  │  │ │
│ │   └─────────────────────────────────────────────────────────┘  │ │
│ └────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│ ┌ 步骤选择 + 运行 ────────────────────────────────────────────────┐ │
│ │ 运行步骤: ◉①构建截面  ○②重采样光顺  ○③生成曲面                 │ │
│ │ [▶ 运行当前步]  [📂 打开输出目录]                                │ │
│ └────────────────────────────────────────────────────────────────┘ │
├─ 执行栏：进度条 + 日志（继承 BaseWorkerPanel） ─────────────────────┤
│ [████████░░░░░░░░] 60%         ┌──────────────────────────────┐   │
│                                │ [①] 连接 CATIA...              │   │
│                                │ 处理样条: Sect1, 长度: 3.2m   │   │
│                                │ ...                            │   │
│                                └──────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

**控件类型约定**：
- 整数参数（截面数、点数、点序号、模式）→ `QSpinBox`（带范围限制）
- 浮点参数（阈值）→ `QDoubleSpinBox`（带 decimals）
- 几何集名 → `QLineEdit`
- 四段阈值 → 4 个 `QSpinBox` 横排
- 高级折叠 → `QCheckBox` + 一组 `QFrame`，`stateChanged` 切 `setVisible`
- 运行步骤选择 → `QRadioButton` 组（与三个 GroupBox 视觉对应）

### 4.2 控件与状态

- **输入文件区**：`QLineEdit` + 浏览按钮 `…`。默认值从 `config_center.get_paths('shape_design')` 推导出 `<shape_design 输出>/stage3/CATIA/3D_points.stp`。该框仅作提示/记录，**实际不通过它把文件传给 CATIA**（CATIA 的 STP 导入由用户手动完成）。
- **三个步骤参数 GroupBox**：每个 GroupBox 顶部直接摆核心参数（SpinBox/LineEdit），底部 `☐ 高级参数` 勾选框 + 折叠区。`stateChanged` → 切折叠区 `setVisible`，并 `save_params` 记住展开状态。
- **步骤选择 + 运行**：一组 `QRadioButton`（①②③）选中当前要运行的步骤；下方「▶ 运行当前步」按钮根据选中步骤动态切文字（"运行① 构建截面" 等）。点运行 → 读当前步参数控件值 → 构造 `SectionParams`/`ResampleParams`/`LoftParams` → 校验 → 存盘 → 启动 Worker。
- **执行栏**：复用 `BaseWorkerPanel._build_exec_bar()`，运行按钮/进度/日志沿用基类。
- **参数持久化回填**：面板 `__init__` 末尾调 `load_params()` 把所有控件值（含高级折叠展开态）回填，实现「记住上次值」。运行成功后 `save_params()` 存盘。

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

- **CATIA 版本兼容**：参考脚本针对 CATIA V5。若团队用 V6 / 3DEXPERIENCE，COM 接口不同——首版只支持 V5，文档注明。
- **几何集命名已定型**（3.8 表）：三步统一走 `Z_*` 体系，②的源集默认改为读 `Z_Smooths`（承接①）、③默认读 `Z_ResampleSmooth`（承接②）。用户仍可在高级参数改写任意集名，用于"旁路"场景（如手动导入的 `line` 样条单独走②）。
