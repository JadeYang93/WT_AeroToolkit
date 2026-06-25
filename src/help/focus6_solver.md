# FOCUS6 — 帮助

> 模块 ID：`focus6_solver`　　默认输入：`输入数据\focus6_solver\`　　默认输出：`输出\focus6_solver\`

本模块专门负责 **调用 FOCUS6 跑有限元分析**，从 `blade_converter`（叶片结构套件）
中独立出来。支持 7 种求解器功能，并提供「一键运行」串行模式。

覆盖的子流程：

1. **读取 mac 文件**（READ MAC）：把 `.mac` 拷进 SUM 工作目录
2. **解析 mac 文件**（PARSE MAC）：调用 `mac2dbf` 把 `.mac` 转成 `.dbf`
3. **重量计算**（WEIGHT）：调 frbex/farob 算叶片总质量
4. **频率计算**（FREQUENCY）：算叶片固有频率
5. **载荷转化**（LOAD CONVERSION）：调 `UserLoadcaseConverter` 把 7 列载荷文件转 `LOAD.LD1`
6. **应变计算**（STRAIN）：基于 `LOAD.LD1` 算应变分布
7. **叶尖挠度计算**（TIP DEFLECTION）：基于 `LOAD.LD1` 算叶尖挠度

UI 为单页平铺（无 Tab），通过滚动区滚动查看各分组：
**FOCUS6 Modules 路径** / **输入输出** / **运行选项** / **高级参数**。

FOCUS6 Modules 目录走「⚙ 设置」（首次使用必须先配置）。

---

## 1. 数据准备

输入目录约定：

```
输入数据\focus6_solver\
├── blade_geometry.mac            # 叶片几何（必填）
├── 载荷文件（可选）               # 应变/挠度/载荷转化需要；7 列 x/fx/fy/fz/mx/my/mz
└── zspan 文件（可选）             # 展向节点分布；留空时从 mac 的 PLACE SHAPE 自动提取
```

> **注意**：`LOAD.LD1` 是 frbex 应变换算的**输出**而非输入。若你需要单独产生它，
> 在单求解器模式中选择「载荷转化」功能（仅调用 UserLoadcaseConverter，不跑应变）。

### 载荷文件格式

7 列文本（空格或 tab 分隔），列顺序固定：

| x | fx | fy | fz | mx | my | mz |
|---|---|---|---|---|---|---|
| 展向位置 mm | 力 x | 力 y | 力 z | 力矩 x | 力矩 y | 力矩 z |

---

## 2. FOCUS6 Modules 目录

**首次使用必须**在「⚙ 设置」对话框底部「FOCUS6 — 额外路径」配置 **1 个**目录：
FOCUS6 Modules 目录。

| 配置项 | 典型路径 |
|---|---|
| FOCUS6 Modules 目录 | `C:\Program Files (x86)\ECN_WMC\FOCUS6.3\Modules` |

该目录内含 `farob/` / `frbex/` / `utils/`（UserLoadcaseConverter）等子目录；模块按所选
「求解器类型」自动选用对应子目录。**不需要分别配 3 个 .exe**。

校验规则：必须是已存在的目录。

面板顶部会实时显示当前 Modules 目录（未配置时显示「(未配置)」）。

> **v0.3.0 迁移提示**：从 v0.3.0 起，modules_path 已从 `blade_converter` 迁到本模块。
> 首次启动 v0.3.0 时，旧 `blade_converter` 的 modules_path 会被自动复制到
> `focus6_solver`（一次性，不删源）。

---

## 3. 面板操作

### 3.1 输入配置

| 字段 | 说明 |
|---|---|
| mac 文件 | 叶片几何（默认 `输入数据\focus6_solver\blade_geometry.mac`） |
| 工作目录（SUM） | 求解器输出目录，FOCUS6 称 SUM 目录 |
| 载荷文件（可选） | 7 列格式 `x/fx/fy/fz/mx/my/mz`；应变/挠度/载荷转化必填 |
| ZSPAN 文件（可选） | 展向节点分布；farob 应变需要；留空时从 mac 的 PLACE SHAPE 自动生成 |

> 「载荷文件」和「ZSPAN 文件」行会根据所选「单求解器功能」自动显隐。

### 3.2 运行模式（单选）

- **单求解器**：只跑下方选定的单一功能
- **一键运行**：串行执行 [读取 mac + 载荷转化] → [解析 mac] → [重量/频率/应变/叶尖挠度]，
  任一步失败则后续不执行

### 3.3 单求解器功能（下拉，仅「单求解器」模式生效）

- 读取 mac 文件 / 解析 mac 文件 / 重量计算 / 频率计算 / **载荷转化** / 应变计算 / 叶尖挠度计算

> **载荷转化**：单独调用 `UserLoadcaseConverter.exe` 把 7 列载荷文件转成 `LOAD.LD1`，不跑应变。
> 适合你只想生成 `LOAD.LD1` 给别的工具用的场景。

### 3.4 求解器类型（单选）

`farob` / `frbex`（默认 frbex）

### 3.5 高级参数

- `drmx`：frbex 求解器的阻尼矩阵缩放（默认 250）
- 后台运行：勾选后隐藏求解器控制台窗口（推荐）

### 3.6 操作流程

1. 确认顶部 Modules 目录已配置（「(未配置)」 → 去「⚙ 设置」）
2. 选模式 + 选求解器类型 → 点 **运行** → 日志区显示 PID + 进度
3. 完成后 **📂 打开目录** 直接跳到 SUM 工作目录

> **进程超时 / 卡死**：Worker 内 `subprocess.Popen` + 超时强杀；日志输出 PID 便于排查。

---

## 4. 输出结果

### 4.1 SUM 工作目录

FOCUS6 原生输出：`*.SUM`、`*.OUT`、`*.FRD` 等，由 farob/frbex 决定。

### 4.2 载荷转化额外输出

若使用「载荷转化」单功能，额外在 `{solver_type}_LoadConversion/` 下产生
`LOAD.LD1`、`foculf.txt`、`run.bat`。

---

## 5. 常见问题

| 现象 | 处理 |
|---|---|
| 顶部「(未配置)」 | 打开「⚙ 设置」→ FOCUS6 行 → 选 FOCUS6 Modules 目录 → 确定 |
| 「找不到 UserLoadcaseConverter.exe」 | 该工具位于 `<Modules>/utils/UserLoadcaseConverter.exe`，确认 Modules 目录正确 |
| 一键运行中断 | 日志会明确指明在哪一步失败（载荷转化 / farob / frbex / 结果收集） |
| 进程长时间无响应 | 关掉「后台运行」勾选 → 重跑 → 看控制台错误；或查 SUM 目录下的 `*.out` 日志 |
| 路径修改后重启丢失 | 面板内「浏览」仅会话内生效，永久修改请用「⚙ 设置」 |
| 中文路径导致 subprocess 报错 | 全程用 `pathlib.Path`；若仍报错，把 SUM 目录改到纯英文路径 |
| 应变计算报「找不到载荷文件」 | 载荷文件需要 7 列格式 `x/fx/fy/fz/mx/my/mz`（不是 LOAD.LD1） |
| 从老版本升级后求解器路径丢失 | 旧 `blade_converter` 的 modules_path 会自动复制到 `focus6_solver`（v0.3.0+） |
