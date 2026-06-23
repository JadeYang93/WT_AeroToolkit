# 叶片结构套件 — 帮助

> 模块 ID：`blade_converter`　　默认输入：`输入数据\blade_converter\`　　默认输出：`输出\blade_converter\`

本模块是 FOCUS6 叶片结构分析的 **一站式前后处理**，覆盖 4 个子流程：

1. **TAB-1 blade_db → focus2blade**：截面属性数据库（WISDEM 风格）→ FOCUS6 标准 xlsx
2. **TAB-2 PRJ 更新**：用 focus2blade.xlsx 改写 `.prj` 项目文件的 17 个字段
3. **TAB-3 Excel ↔ txt**：`blade_geometry.mac` ↔ `blade_data.xlsx` 双向转换
4. **TAB-4 FOCUS6 求解器**：调用 `farob` / `frbex` / `UserLoadcaseConverter`，支持「一键运行」

UI 用 `QTabWidget` 四页（页签隐藏），由 banner 下方 **流水线 stepper** 切换阶段。
3 个求解器 `.exe` 路径走「⚙ 设置」（首次使用必须先配置）。

---

## 1. 数据准备

输入目录约定（FOCUS6 工程）：

```
输入数据\blade_converter\
├── blade_db.xlsx                 # TAB-1 主输入：截面属性数据库
├── 变桨中心.xlsx（可选）          # TAB-1 变桨中心数据
├── blade_geometry.mac            # TAB-3 / TAB-4 FOCUS6 几何文件
├── <project>.prj                 # TAB-2 待更新的 FOCUS6 项目文件
├── focus2blade.xlsx              # TAB-2 主输入（若 TAB-1 已生成，从 输出\ 拿）
├── 载荷文件（可选）               # TAB-4 应变/挠度/载荷转化需要；7 列 x/fx/fy/fz/mx/my/mz
└── zspan 文件（可选）             # TAB-4 展向位置；留空时从 mac 的 PLACE SHAPE 自动提取
```

> **注意**：`LOAD.LD1` 是 frbex 应变换算的**输出**而非输入。若你需要单独产生它，
> 在 TAB-4 单求解器中选择「载荷转化」功能（仅调用 UserLoadcaseConverter，不跑应变）。

### blade_db.xlsx 字段（关键列）

| 列名（英文表头） | 含义 | 单位 |
|---|---|---|
| Distance along blade | 展向位置 | m |
| Chord | 弦长 | m |
| Twist angle | 扭角 | deg |
| Mass per unit length | 单位长度质量 | kg/m |
| Flapwise stiffness | 挥舞刚度 | N·m² |
| Edgewise stiffness | 摆振刚度 | N·m² |
| Neutral axis (x/y) | 中性轴坐标 | m |
| Center of elasticity (x/y) | 弹性中心 | m |
| Mass center (x/y) | 质心 | m |
| Torsional stiffness | 扭转刚度 GJ | N·m² |
| Extensional stiffness EA | 拉伸刚度 | N |

> 17 列字段顺序由 `PRJ_FIELD_MAPPING` 定义，TAB-2 会按此映射改写 .prj。

---

## 2. 求解器可执行文件

**首次使用必须**在「⚙ 设置」对话框底部「叶片结构套件 — 求解器路径」配置 **1 个**目录：
FOCUS6 Modules 目录。

| 配置项 | 典型路径 |
|---|---|
| FOCUS6 Modules 目录 | `C:\Program Files (x86)\ECN_WMC\FOCUS6.3\Modules` |

该目录内含 `farob/` / `frbex/` / `utils/`（UserLoadcaseConverter）等子目录；TAB-4 按所选「求解器类型」自动选用对应子目录。**不再需要分别配 3 个 .exe**。

校验规则：必须是已存在的目录。

TAB-4 顶部会实时显示当前 Modules 目录（未配置时显示「(未配置)」）。

---

## 3. 面板操作

### 3.1 TAB-1 — blade_db 转换

| 字段 | 说明 |
|---|---|
| blade_db 文件 | 主输入（默认 `输入数据\blade_converter\blade_db.xlsx`） |
| mac 文件（变桨中心） | 可选；从 `.mac` 提取变桨中心数据；留空跳过 |
| 输出 focus2blade | 默认 `输出\blade_converter\focus2blade\focus2blade.xlsx` |
| 求解器类型 | `farob` 或 `frbex`；影响输出文件名后缀（`_farob` / `_frbex`） |

**操作**：选好 blade_db → 点 **运行 TAB-1** → 后台 WISDEM 插值 → 算主惯性矩 → 输出 `focus2blade.xlsx`（求解器类型为后缀）。

### 3.2 TAB-2 — PRJ 更新

| 字段 | 说明 |
|---|---|
| PRJ 文件 | 待更新的 FOCUS6 项目文件 |
| focus2blade.xlsx | TAB-1 的输出（或用户自备的同结构 xlsx） |
| 输出 PRJ | 默认 `<原名>_updated.prj`（**不覆盖原文件**） |
| 运行前备份 | 勾选 → 生成 `<原名>.prj.backup` |

**操作**：点 **运行 TAB-2** → 解析 .prj 的 17 个字段行 → 用 focus2blade 数据就地覆盖数值 → 保存到输出路径。

> 同步更新 `.in` 模板？目前仅改 .prj。需要改 `aeroinfo.in / pcoeffs.in / spcurve.in / steadyop.in / modal.in` 请手工调用 `template_in.update_template_files()`。

### 3.3 TAB-3 — Excel ↔ txt 互转

| 字段 | 说明 |
|---|---|
| 转换方向 | 单选：mac → Excel 或 Excel → mac |
| 输入文件 | `blade_geometry.mac`（正向）或 `blade_data.xlsx`（反向） |
| 输出文件 | `blade_data.xlsx`（正向）或 `blade_geometry_new.mac`（反向） |

**正向（mac → Excel）**：
- 解析 mac 中的 `DEF PARA / DEF SHAPE / POINTS / PLACE SHAPE / DEF MATERIAL / DEF S-N LINE / DEF LINE / DEF SECTION`
- 输出 7 个 sheet：`Parameters / shape_points / PlaceShapes / Materials / S_N Lines / Line / Sections`

**反向（Excel → mac）**：
- 要求 xlsx 由 TAB-3 正向转换生成（`PlaceShapes` 必须含 `CenterX / CenterY` 列）
- 输出与原 mac 等价的文本格式（缩进 / 对齐尽量保留）

### 3.4 TAB-4 — FOCUS6 求解器

**输入配置**：

| 字段 | 说明 |
|---|---|
| mac 文件 | 叶片几何 |
| 工作目录（SUM） | 求解器输出目录，FOCUS6 称 SUM 目录 |
| 载荷文件（可选） | 7 列格式 `x/fx/fy/fz/mx/my/mz`；应变/挠度/载荷转化必填 |
| ZSPAN 文件（可选） | 展向节点分布；farob 应变需要；留空时从 mac 的 PLACE SHAPE 自动生成 |

> 「载荷文件」和「ZSPAN 文件」行会根据所选「单求解器功能」自动显隐。

**运行模式**（单选）：
- **单求解器**：只跑下方选定的单一功能
- **一键运行**：并行执行 [读取 mac + 载荷转化] → [解析 mac] → [重量/频率/应变/叶尖挠度]，任一步失败则后续不执行

**单求解器功能**（下拉，仅「单求解器」模式生效）：
- 读取 mac 文件 / 解析 mac 文件 / 重量计算 / 频率计算 / **载荷转化** / 应变计算 / 叶尖挠度计算

> **载荷转化**：单独调用 `UserLoadcaseConverter.exe` 把 7 列载荷文件转成 `LOAD.LD1`，不跑应变。
> 适合你只想生成 `LOAD.LD1` 给别的工具用的场景。

**求解器类型**（单选）：`farob` / `frbex`（默认 frbex）

**高级参数**：
- `drmx`：frbex 求解器的阻尼矩阵缩放（默认 250）
- 后台运行：勾选后隐藏求解器控制台窗口（推荐）

**操作**：
1. 确认顶部 Modules 目录已配置（「(未配置)」 → 去「⚙ 设置」）
2. 选模式 + 选求解器类型 → 点 **运行 TAB-4** → 日志区显示 PID + 进度
3. 完成后 **📂 打开目录** 直接跳到 SUM 工作目录

> **进程超时 / 卡死**：Worker 内 `subprocess.Popen` + 超时强杀；日志输出 PID 便于排查。

---

## 4. 输出结果

### 4.1 TAB-1（`输出\blade_converter\focus2blade\`）

| 文件 | 内容 |
|---|---|
| `focus2blade_<solver>.xlsx` | FOCUS6 标准截面属性表，17 列 + 单位行 |

### 4.2 TAB-2（`输出\blade_converter\prj_update\`）

| 文件 | 内容 |
|---|---|
| `<原名>_updated.prj` | 17 个字段已用 focus2blade 数据覆盖 |
| `<原名>.prj.backup`（可选） | 勾选备份时生成 |

### 4.3 TAB-3（`输出\blade_converter\txt_excel\`）

| 方向 | 输出文件 |
|---|---|
| mac → Excel | `blade_data.xlsx`（7 个 sheet） |
| Excel → mac | `blade_geometry_new.mac` |

### 4.4 TAB-4（`SUM 工作目录`）

FOCUS6 原生输出：`*.SUM`、`*.OUT`、`*.FRD` 等，由 farob/frbex 决定。

若使用「载荷转化」单功能，额外在 `{solver_type}_LoadConversion/` 下产生 `LOAD.LD1`、`foculf.txt`、`run.bat`。

---

## 5. 常见问题

| 现象 | 处理 |
|---|---|
| TAB-4 顶部「(未配置)」 | 打开「⚙ 设置」→ 底部「求解器路径」→ 选 FOCUS6 Modules 目录 → 确定 |
| 「找不到 UserLoadcaseConverter.exe」 | 该工具位于 `<Modules>/utils/UserLoadcaseConverter.exe`，确认 Modules 目录正确 |
| TAB-1 报「WISDEM 插值失败」 | 检查 blade_db.xlsx 列名是否与 `KEY_COLUMNS` 一致（区分大小写） |
| TAB-2 报「.prj 中未找到字段 X」 | PRJ_FILE_PROCESSOR 用正则 `^X\s+` 匹配；手工编辑过 .prj 导致字段行格式异常时修复原文件 |
| TAB-3 反向报「PlaceShapes 缺 CenterX/CenterY」 | 反向要求 xlsx 由 TAB-3 正向生成；手工编辑过的 xlsx 可能丢列 |
| TAB-4 一键运行中断 | 日志会明确指明在哪一步失败（载荷转化 / farob / frbex / 结果收集） |
| TAB-4 进程长时间无响应 | 关掉「后台运行」勾选 → 重跑 → 看控制台错误；或查 SUM 目录下的 `*.out` 日志 |
| 路径修改后重启丢失 | 面板内「浏览」仅会话内生效，永久修改请用「⚙ 设置」 |
| `.prj.backup` 已存在 | TAB-2 不覆盖已有 backup；需要新备份时手工删除后再跑 |
| 中文路径导致 subprocess 报错 | 全程用 `pathlib.Path`；若仍报错，把 SUM 目录改到纯英文路径 |
| 应变计算报「找不到载荷文件」 | TAB-4 载荷文件需要 7 列格式 `x/fx/fy/fz/mx/my/mz`（不是 LOAD.LD1） |
| 从老版本升级后求解器路径丢失 | 老配置的 `farob_exe` 会被自动迁移到 `modules_path`（向上推一级） |
