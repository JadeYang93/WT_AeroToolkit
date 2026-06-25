# 叶片结构套件 — 帮助

> 模块 ID：`blade_converter`　　默认输入：`输入数据\blade_converter\`　　默认输出：`输出\blade_converter\`

本模块是 FOCUS6 叶片结构分析的 **一站式前后处理**，覆盖 3 个子流程：

1. **TAB-1 blade_db → focus2blade**：截面属性数据库（WISDEM 风格）→ FOCUS6 标准 xlsx
2. **TAB-2 PRJ 更新**：用 focus2blade.xlsx 改写 `.prj` 项目文件的 17 个字段
3. **TAB-3 Excel ↔ txt**：`blade_geometry.mac` ↔ `blade_data.xlsx` 双向转换

UI 用 `QTabWidget` 三页（页签隐藏），由 banner 下方 **流水线 stepper** 切换阶段。

> **v0.3.0 变更**：原 TAB-4「FOCUS6」已独立成新模块，参见
> 「🎯 FOCUS6」（模块 ID：`focus6_solver`）。

---

## 1. 数据准备

输入目录约定（FOCUS6 工程）：

```
输入数据\blade_converter\
├── blade_db.xlsx                 # TAB-1 主输入：截面属性数据库
├── 变桨中心.xlsx（可选）          # TAB-1 变桨中心数据
├── blade_geometry.mac            # TAB-3 几何文件
├── <project>.prj                 # TAB-2 待更新的 FOCUS6 项目文件
└── focus2blade.xlsx              # TAB-2 主输入（若 TAB-1 已生成，从 输出\ 拿）
```

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
| Torsional stiffness GJ | 扭转刚度 | N·m² |
| Extensional stiffness EA | 拉伸刚度 | N |

> 17 列字段顺序由 `PRJ_FIELD_MAPPING` 定义，TAB-2 会按此映射改写 .prj。

---

## 2. 面板操作

### 2.1 TAB-1 — blade_db 转换

| 字段 | 说明 |
|---|---|
| blade_db 文件 | 主输入（默认 `输入数据\blade_converter\blade_db.xlsx`） |
| mac 文件（变桨中心） | 可选；从 `.mac` 提取变桨中心数据；留空跳过 |
| 输出 focus2blade | 默认 `输出\blade_converter\focus2blade\focus2blade.xlsx` |
| 求解器类型 | `farob` 或 `frbex`；影响输出文件名后缀（`_farob` / `_frbex`） |

**操作**：选好 blade_db → 点 **运行 TAB-1** → 后台 WISDEM 插值 → 算主惯性矩 → 输出 `focus2blade.xlsx`（求解器类型为后缀）。

### 2.2 TAB-2 — PRJ 更新

| 字段 | 说明 |
|---|---|
| PRJ 文件 | 待更新的 FOCUS6 项目文件 |
| focus2blade.xlsx | TAB-1 的输出（或用户自备的同结构 xlsx） |
| 输出 PRJ | 默认 `<原名>_updated.prj`（**不覆盖原文件**） |
| 运行前备份 | 勾选 → 生成 `<原名>.prj.backup` |

**操作**：点 **运行 TAB-2** → 解析 .prj 的 17 个字段行 → 用 focus2blade 数据就地覆盖数值 → 保存到输出路径。

> 同步更新 `.in` 模板？目前仅改 .prj。需要改 `aeroinfo.in / pcoeffs.in / spcurve.in / steadyop.in / modal.in` 请手工调用 `template_in.update_template_files()`。

### 2.3 TAB-3 — Excel ↔ txt 互转

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

---

## 3. 输出结果

### 3.1 TAB-1（`输出\blade_converter\focus2blade\`）

| 文件 | 内容 |
|---|---|
| `focus2blade_<solver>.xlsx` | FOCUS6 标准截面属性表，17 列 + 单位行 |

### 3.2 TAB-2（`输出\blade_converter\prj_update\`）

| 文件 | 内容 |
|---|---|
| `<原名>_updated.prj` | 17 个字段已用 focus2blade 数据覆盖 |
| `<原名>.prj.backup`（可选） | 勾选备份时生成 |

### 3.3 TAB-3（`输出\blade_converter\txt_excel\`）

| 方向 | 输出文件 |
|---|---|
| mac → Excel | `blade_data.xlsx`（7 个 sheet） |
| Excel → mac | `blade_geometry_new.mac` |

---

## 4. 常见问题

| 现象 | 处理 |
|---|---|
| TAB-1 报「WISDEM 插值失败」 | 检查 blade_db.xlsx 列名是否与 `KEY_COLUMNS` 一致（区分大小写） |
| TAB-2 报「.prj 中未找到字段 X」 | PRJ_FILE_PROCESSOR 用正则 `^X\s+` 匹配；手工编辑过 .prj 导致字段行格式异常时修复原文件 |
| TAB-3 反向报「PlaceShapes 缺 CenterX/CenterY」 | 反向要求 xlsx 由 TAB-3 正向生成；手工编辑过的 xlsx 可能丢列 |
| 路径修改后重启丢失 | 面板内「浏览」仅会话内生效，永久修改请用「⚙ 设置」 |
| `.prj.backup` 已存在 | TAB-2 不覆盖已有 backup；需要新备份时手工删除后再跑 |
| 中文路径导致报错 | 全程用 `pathlib.Path`；若仍报错，把输入/输出目录改到纯英文路径 |
| 想调用 FOCUS6 | v0.3.0 起独立为「🎯 FOCUS6」模块，本面板不再集成该功能 |
