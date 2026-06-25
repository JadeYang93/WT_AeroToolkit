# 叶片形状输出 — 帮助

> 模块 ID：`shape_design`　　默认输入：`输入数据\shape_design\`　　默认输出：`输出\shape_design\`
> 翼型库目录（固定）：`配置\`（含 `Aerofoil_coordinate\`）

本模块按 **三阶段流水线** 输出风机叶片几何：STAGE-1 算出基准翼型与修正输入 →
STAGE-2 TE 修正改写尾缘厚度 → STAGE-3 用 XFOIL 修正 + spapi 样条重建最终几何。
UI 用 `QTabWidget` 三页（页签隐藏），由 banner 下方 **流水线 stepper** 切换阶段。

---

## 1. 数据准备

输入约定：**GEO 文件直接放输入目录根**，**翼型库放配置目录**（与输入数据分离）：

```
输入数据\shape_design\
└── <你的叶片>.geo               # 直接放根目录（不再嵌套 Blade_database\）

配置\                             # 翼型库根目录（固定，随工具箱根目录走）
└── Aerofoil_coordinate\
    └── <翼型族名>\               # 多个 .prof 文件，文件名首位数字 = 相对厚度
```

### GEO 文件格式

Tab / 逗号 / 多空格分隔；前 2 行表头（单位行），从第 3 行起为数据。**必须 7 列**：

| 列 | 含义 | 单位 |
|---|---|---|
| 1 | 展长 span | m |
| 2 | 弦长 chord | m |
| 3 | 扭角 twist | deg |
| 4 | 相对厚度 thickness | % |
| 5 | 变桨轴 pitchaxis | % |
| 6 | 预弯 prebend | m |
| 7 | 后掠 sweep | m |

---

## 2. XFOIL 可执行文件

`src\_bin\xfoil.exe` — **固定路径**，不走设置对话框。
缺失时 Stage2 日志会明确提示「未找到 XFOIL：{路径}」。

---

## 3. 面板操作

### 3.1 STAGE-1 Tab — 基准翼型

| 字段 | 说明 |
|---|---|
| GEO 输入文件 | 下拉选择 `.geo` 文件（来自 `输入数据\shape_design\`）；点 `🔄` 只刷新本下拉 |
| 翼型库（可空） | 下拉选择翼型族（`配置\Aerofoil_coordinate\` 下的子目录）；点 `🔄` 只刷新本下拉 |
| STAGE-1 输出目录 | 默认 `输出\shape_design\stage1\` |

> 翼型库目录固定为工具箱根目录下的 `配置\`，不在 UI 中显式给出（跨电脑迁移自动跟随）。

**操作**：
- 点 **🔍 扫描** 一键刷新两个下拉（首次进入会自动扫描一次）
- **导入新 .geo 后** → 点 GEO 旁的 **🔄** 单独刷新 GEO 下拉
- **导入新翼型族后** → 点翼型库旁的 **🔄** 单独刷新翼型库下拉
- 选好 GEO + 翼型库 → 点 **运行 STAGE-1** → 后台加载 → 计算 → 导出 → 自动准备 STAGE-2 修正输入
- 完成后 **打开目录** 与 **查看叶片参数分布** 启用
- **查看叶片参数分布** → 弹出 QDialog，多 Tab 展示 弦长 / 扭角 / 厚度 / 预弯 / 后掠 / 前后缘

### 3.2 STAGE-2 TE 修正 Tab

顶部展示**修正示意图**（`配置\diagrams\te_correction_diagram.png`），
下方是规则说明文字与参数表。

四个参数（余弦光顺过渡规则）：

| 参数 | 含义 |
|---|---|
| p1 = 修正区起始 | span/R ≥ p1 到叶尖前最后截面 = p2（mm） |
| p2 = 修正区厚度 | 目标尾缘总厚度 |
| p3 = 叶尖厚度 | 最后截面目标尾缘厚度 |
| p4 = 光顺过渡起始 | p4 → p1 之间用 `0.5*(1-cos(πt))` 平滑过渡 |

> 约束：**p4 < p1**，否则报错（过渡段无意义）。

**PCHIP 连续性前置修正**（可选，默认开启）：

勾选「启用 PCHIP 连续性修正」后，STAGE-2 每次运行会**先**做 PCHIP 修正，**再**跑上述余弦过渡。

| 步骤 | 说明 |
|---|---|
| 取基础数据 | Th%∈[30,50] 范围的所有截面作为基础数据 |
| 剔除异常段 | 把 Th%∈[39,41] 范围的点从基础数据中剔除（这段原始数据连续性不够） |
| PCHIP 构造 | 用剩余点构造 PCHIP 曲线 `TEth = f(Th%)`（保单调、不过冲） |
| 重算 39-41 段 | 用 PCHIP 曲线插值出 Th%∈[39,41] 段的新 TEth，替换原值 |
| 同步 baseline | 同时更新 `_internal\TEth_baseline.npy` 的 39-41 段，避免后续余弦过渡用老基准覆盖 |

> 仅影响 Th%∈[39,41] 段；Th%<30、Th%>50、以及 [30,39]∪[41,50] 段的 TEth 全部保持原值。
> 边界保护：39-41 段无截面 / 构造点不足 4 个 → 自动跳过，日志会说明原因。

**目标文件**：默认 `输出\shape_design\stage2\GEO_for_correction.xlsx`。
STAGE-1 跑完后会自动把 `stage1\GEO_for_correction.xlsx` 复制到 stage2/（覆盖老版本），保证 STAGE-2 永远基于最新的 STAGE-1 输出。

**操作**：
- 点 **执行 TE 修正** → 改写 stage2/ 中 GEO 的 `TEth` 列（TEth 原始基准在 `_internal\TEth_baseline.npy`）
- 完成后 **查看 TE 对比曲线** 启用 → 弹出 `TEComparisonDialog`，展示 `toPS` / `toSS` 修正前后对比

### 3.3 STAGE-3 Tab — 最终输出

| 字段 | 说明 |
|---|---|
| XFOIL 工作目录 | 默认 `输出\shape_design\_internal\xfoil_work\` |
| 最终输出目录 | 默认 `输出\shape_design\stage3\` |

**输出文件勾选**（多选）：
- 标准翼型点云 `standard_airfoil_points.xlsx`
- 3D 叶片点云 `blade_3d_points.xlsx`
- 几何参数表 `blade_aero_geometry.xlsx`
- 修正后尾缘厚度 `trailing_edge_thickness.xlsx`（内含 `Focus` sheet）
- `Focus.mac`
- STP 点云 `3D_points.stp`

**XFOIL 模式**（三选一）：
- **完整运行**（默认）：XFOIL 跑 TGAP/TSET 修正 + 重建
- **跳过 XFOIL**：用当前修正翼型直接重建（适合调试）
- **调试模式**：完整运行 + 保留 `xfoil_work/` 临时文件

**操作**：点 **运行 STAGE-3** → XFOIL 批量修正 → 重建 → 导出最终文件。

---

## 4. 输出结果

### 4.1 STAGE-1（`输出\shape_design\stage1\`）

| 文件 | 内容 |
|---|---|
| `blade_aero_geometry.xlsx` | 叶片气动几何参数表 |
| `standard_airfoil_points.xlsx` | 归一化标准翼型点云（MATLAB 风格双行表头） |
| `blade_3d_points.xlsx` | 3D 真实坐标点云 |
| `trailing_edge_thickness.xlsx` | 基础尾缘厚度表（含 Focus sheet） |
| `GEO_for_correction.xlsx` | STAGE-2 修正 GEO 输入（**模板**，TE Tab 不直接改写此文件） |
| `standard_airfoil_for_correction.xlsx` | STAGE-3 修正翼型输入 |

### 4.2 STAGE-2（`输出\shape_design\stage2\`）

| 文件 | 内容 |
|---|---|
| `GEO_for_correction.xlsx` | STAGE-2 改写后的 GEO（首次运行从 stage1/ 复制模板，后续就地改写 TEth 列） |

> STAGE-2 反复调 p1/p2/p3/p4 都在此文件上覆盖；原始模板在 stage1/ 永远不变。
> TEth 的原始基准单独保存在 `_internal\TEth_baseline.npy`，避免调参时污染过渡区。

### 4.3 STAGE-3（`输出\shape_design\stage3\`）

跟 STAGE-1 文件名一致，但参数 / 翼型 / 尾缘厚度全部基于修正后的数据。
`_internal\xfoil_work\Corrected_Airfoils\` 是 XFOIL 修正过程的中间产物（dat + summary）。
`TEth_baseline.npy` 也在 `_internal\` 下，作为 STAGE-2 反复调参的原始基准。

---

## 5. 三阶段流程示意

```
[STAGE-1 Tab]
  翼型库 + GEO → build_shape_design → 6 个 stage1/*.xlsx（含 GEO 模板）
                                        ↓
[STAGE-2 Tab] 复制 stage1/GEO_for_correction.xlsx → stage2/，apply_te_correction 改写 TEth 列
                                        ↓
[STAGE-3 Tab] run_airfoil_correction (XFOIL)，从 stage2/ 读 GEO + stage1/ 读翼型 → rebuild → 导出最终文件到 stage3/
```

> **典型用法**：STAGE-1 → 在 STAGE-2 Tab 改 p1/p2/p3/p4 → 预览对比 → STAGE-3 出最终结果。
> 想手工编辑 GEO 参数？直接编辑 `stage2\GEO_for_correction.xlsx` 后再跑 STAGE-2/3。
> 想回到 STAGE-1 原始 GEO？删掉 `stage2\GEO_for_correction.xlsx`，STAGE-2 下次运行会自动从 stage1/ 重新复制模板。

---

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| STAGE-3 日志「未找到 XFOIL」 | 检查 `src\_bin\xfoil.exe` 是否存在；被杀软删掉时恢复或加白名单 |
| STAGE-1 日志「GEO 文件第 N 行 X 列空缺」 | GEO 第 N 行第 X 列空着；补全或删该行 |
| STAGE-1 日志「.prof files found in」 | 翼型库目录的 `Aerofoil_coordinate\<族名>\` 下没有 `.prof` 文件 |
| STAGE-2 提示「GEO_for_correction.xlsx 不存在」 | 先在 STAGE-1 Tab 跑一次 |
| STAGE-2 提示「fair_start 必须小于 corr_start」 | 调整 p4 < p1（p4 是过渡起始，必须在修正区起始之前） |
| STAGE-3 抛 PermissionError | 关闭 Excel / 编辑器再跑（xlsx 被占用） |
| XFOIL 修正耗时过长 | 大叶片截面数 ×30s 是正常基线；如频繁超时改调试模式看 `xfoil_work/xfoil.out` |
| 路径修改后重启丢失 | 面板内「浏览」仅会话内生效，永久修改请用「⚙ 设置」 |
| GEO 下拉框为空 | 点 GEO 旁 **🔄** 单独刷新；若仍空，确认 `输入数据\shape_design\` 下有 `.geo` 文件 |
| 翼型库下拉框只有「默认」 | 点翼型库旁 **🔄** 单独刷新；确认 `配置\Aerofoil_coordinate\<族名>\` 下有 `.prof` 文件，子目录无 `.prof` 不会出现在下拉里 |
| 导入新文件后下拉没看到 | **🔍 扫描** 是全量刷新；若只想刷一个，用对应下拉旁的 **🔄**（只刷 GEO 或只刷翼型库，不影响另一边） |
| 外部选的 GEO/翼型库丢失 | 浏览外部文件后路径保存在下拉当前选项里；切到其他项后会消失，可重新 `...` 浏览 |
