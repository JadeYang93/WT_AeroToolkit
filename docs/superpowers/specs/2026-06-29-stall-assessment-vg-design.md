# 失速评估扩展：VG（涡发生器）安装段的失速攻角插值

## 背景与动机

现有「失速评估」模块只支持一种逻辑：用户给一张「相对厚度 → 标准失速攻角」表（如
`(100%,0°)`、`(40%,10°)`、`(30%,13°)`、`(18%,15.5°)` …），系统对每个展向位置 `z`，
按该处的相对厚度 `t(z)` 在整张标准表上做 PCHIP 保形插值。

实际叶片会安装 VG（涡发生器）来推迟失速——同一种厚度翼型贴了 VG 后失速攻角会
升高（如 `30%` 厚度翼型，无 VG 是 `13°`，有 VG 是 `15°`）。VG 不是装满整张叶片，
是装在某些**展向子段**上。比如：

```
叶片段 z ∈ [10m, 30m]，相对厚度从 40% 渐减到 30%
        ├─ z ∈ [10m, 18m]：装了 VG
        └─ z ∈ [18m, 30m]：未装 VG
```

装了 VG 的子段，失速攻角计算时**对应厚度端的攻角值要替换为 VG 版**——`30%` 端用
`α_30VG` 而不是 `α_30`；未装 VG 的子段继续用标攻角。

**目标**：扩展现有插值逻辑，支持「按展向子段指定某些标准翼型的 VG 状态」，使得
失速攻角计算在每个子段选用正确的端点对。

**版本**：v0.3.18 → v0.3.19。

---

## 核心设计（一句话）

**插值始终按相对厚度在标准厚度区间内做两点线性；VG 的作用 = 在某些 z 子段内把某些
标准厚度点的失速攻角值从「标」替换为「VG」。**

VG 不创造新的厚度，也不引入新的端点；它只决定「这个标准厚度点在当前 z 处用哪个攻角」。

---

## 数据模型

### 1. 标准翼型表（已有，扩展为 3 列）

| 厚度(%) | 标失速攻角(°) | VG 失速攻角(°, 可选) |
|---------|---------------|----------------------|
| 18      | 15.5          | —                    |
| 21      | 12            | —                    |
| 25      | 12            | —                    |
| 30      | 13            | 15                   |
| 40      | 10            | 12                   |
| 100     | 0             | —                    |

- VG 列空 = 该厚度翼型没有 VG 变体（如下游较薄的 25/21/18 通常无 VG）。
- UI 上保留原有的「+ 添加 / − 删除」增删行。

### 2. VG 安装范围表（新增）

每行描述「哪个标准厚度的翼型在哪个 z 范围内装了 VG」：

| 标准厚度(%) | VG 起 z (r/R) | VG 止 z (r/R) |
|-------------|---------------|---------------|
| 40          | 0.10          | 0.25          |
| 30          | 0.20          | 0.35          |

- **标准厚度** 列：下拉菜单，选项 = 标准翼型表里 VG 列非空的厚度（如 30、40）。
- **VG 起 / 止 z** 列：用户填，默认预填「该厚度在展向分布中的 z 位置」（系统从展向
  分布查找），用户可改。
- 同一标准厚度可以有多行（如「30% 厚度装了两段 VG」），系统视为多段 OR 关系。
- 表为空 = 全展向无 VG → 退化为原 PCHIP 兼容逻辑。

---

## 算法

### 主流程

```python
def compute_alpha_span(span_positions, span_thickness, std_table, vg_table):
    """
    span_positions: ndarray, 展向位置 r/R ∈ [0, 1]
    span_thickness: ndarray, 对应每个 z 的相对厚度
    std_table:    DataFrame, 列 [thickness, alpha_std, alpha_vg(可选)]
    vg_table:     DataFrame, 列 [thickness, z_start, z_end]
    Returns:      ndarray, 每个 z 的失速攻角
    """
    # 兼容路径：无 VG 安装 → 走原 PCHIP 逻辑
    if vg_table.empty:
        return pchip_interpolate(std_table.thickness, std_table.alpha_std, span_thickness)

    alphas = np.empty_like(span_positions)
    for i, (z, t_z) in enumerate(zip(span_positions, span_thickness)):
        # 1. 找 t_z 所在的标准厚度区间 [t_a, t_b]
        t_a, t_b = find_thickness_interval(t_z, std_table)

        # 2. 决定 t_a, t_b 在 z 处用哪个攻角
        alpha_a = pick_alpha(t_a, z, std_table, vg_table)
        alpha_b = pick_alpha(t_b, z, std_table, vg_table)

        # 3. 按相对厚度两点线性插值
        alphas[i] = alpha_a + (alpha_b - alpha_a) * (t_a - t_z) / (t_a - t_b)

    return alphas


def pick_alpha(thickness, z, std_table, vg_table):
    """标准厚度 `thickness` 在 z 处的失速攻角：z 在 VG 安装范围内 → α_VG，否则 α_std。"""
    # 该 thickness 是否在 VG 表内有覆盖 z 的安装段
    mask = (
        (vg_table.thickness == thickness) &
        (vg_table.z_start <= z) & (z <= vg_table.z_end)
    )
    if mask.any():
        # 取第一条匹配（同一厚度多段 VG 时，理论上不重叠）
        return std_table.loc[std_table.thickness == thickness, 'alpha_vg'].iloc[0]
    return std_table.loc[std_table.thickness == thickness, 'alpha_std'].iloc[0]


def find_thickness_interval(t_z, std_table):
    """找 t_z 落在哪两个相邻标准厚度之间，返回 (t_a, t_b) 且 t_a > t_b（厚度单调减）。"""
    sorted_t = np.sort(std_table.thickness.values)[::-1]  # 降序 [100, 40, 30, 25, 21, 18]
    # 边界检查
    if t_z > sorted_t[0] or t_z < sorted_t[-1]:
        raise ValueError(f'相对厚度 {t_z}% 超出标准表范围')
    for i in range(len(sorted_t) - 1):
        if sorted_t[i] >= t_z >= sorted_t[i + 1]:
            return sorted_t[i], sorted_t[i + 1]
    raise ValueError(f'相对厚度 {t_z}% 找不到所在区间')
```

### 连续性

- **段内**：两点线性，必然连续。
- **段边界（不同厚度区间交接）**：端点攻角由 `pick_alpha` 决定，两端点共享相同厚度
  和攻角 → 自动连续。
- **VG 装卸边界（同厚度区间内 z 子段切换 VG 状态）**：VG 状态切换的瞬间，端点对从
  `(α_std, α_VG)` 切换为 `(α_std, α_std)`，**攻角会跳变**——这是 VG 终止的物理表现，
  符合用户「重点不是平滑」的明确要求。

---

## UI 设计

### 整体布局（在现有面板上加 GroupBox）

```
┌──────────────────────────────────┬──────────────────────────┐
│ [标准翼型表]    [结果]            │                          │
│  厚度│标攻角│VG攻角               │      失速攻角展向分布图 │
│  ────┼─────┼─────                │      （已有，增强标注）   │
│  18  │15.5 │–                    │                          │
│  30  │13   │15                   │      ▒▒▒▒ VG 安装段阴影  │
│  ...                              │      ┊ ┊  段边界竖虚线   │
│  [+ 添加] [− 删除]                │      ●    标准点(VG=红)  │
│                                  │                          │
│ [展向分布]    [攻角分布]          │                          │
│  (z, t(z))     (z, α_max)        │                          │
│                                  │                          │
│ [VG 安装范围表] (新增)            │                          │
│  厚度│起 z│止 z                  │                          │
│  ────┼────┼────                  │                          │
│  40  │0.10│0.25                  │                          │
│  30  │0.20│0.35                  │                          │
│  [+ 添加] [− 删除]                │                          │
└──────────────────────────────────┴──────────────────────────┘
                    [基类 exec_bar: 计算 / 打开目录 / 进度 / 日志]
```

### 控件清单

| 控件 | 类型 | 说明 |
|------|------|------|
| `profile_table` | QTableWidget（已有）| 列数 2 → 3，新增「VG 失速攻角」列 |
| `vg_table` | QTableWidget（新增）| 3 列：标准厚度 / VG 起 z / VG 止 z |
| `vg_thickness_combo` | QTableWidgetItem with setCellWidget | 标准厚度列用 QComboBox，选项动态更新 |
| `vg_add_btn` / `vg_del_btn` | QPushButton（新增）| 加/删行 |

### VG 表的「标准厚度」下拉

`vg_table` 的「标准厚度」列用 `setCellWidget(row, col, QComboBox)` 实现下拉。选项
= `profile_table` 里 VG 列非空的厚度。每次 `profile_table` 变化时刷新所有行的下拉
选项（保留当前值如果在新的选项里）。

---

## 绘图增强

### 失速攻角展向分布图（右上主图）

1. **基础曲线**（已有）：失速攻角 `α(z)` 沿 `z` 的折线。
2. **VG 安装段阴影**（新增）：对 `vg_table` 每一行 `(thickness, z_start, z_end)`，
   在 `ax` 上画 `axvspan(z_start, z_end, alpha=0.15, color='#FCE4D6')`。同一厚度
   多段 VG 会画多个阴影，可叠加（颜色一致）。
3. **段边界竖虚线**（新增）：把所有 VG 起/止 z 收集到去重列表，每个 z 画一条
   `ax.axvline(z, linestyle=':', color='#888')`。
4. **图例条目**：阴影 = ` VG 安装区域`；竖虚线 = ` VG 边界`。

### 插值校核图（如有，可选增强）

标准翼型点的散点图扩展为两种颜色：标攻角点（灰）、VG 攻角点（红）。让用户直观看到
哪些厚度有 VG 数据。

---

## 输出 CSV

`输出/stall_assessment/stall_alpha_span.csv` 加一列 `vg_active`：

| span_position | relative_thickness | stall_alpha_deg | vg_active |
|---------------|--------------------|-----------------|-----------|
| 0.00          | 100                | 0.0             | False     |
| 0.14          | 37                 | 11.5            | True      |
| 0.18          | 35                 | 12.5            | True      |
| 0.19          | 34.8               | 11.4            | False     |
| ...           | ...                | ...             | ...       |

`vg_active` = 该 z 是否落在任何 VG 安装范围内（不论厚度），便于下游分析识别 VG 影响。

---

## 兼容性

- **VG 安装表为空**：直接走原 PCHIP 逻辑（用整张标准表的标攻角做 PCHIP 插值）。
  - 这样未配置 VG 的用户得到与 v0.3.18 完全一致的结果。
- **VG 列全空（标准翼型表只有标攻角）**：等同于 VG 安装表空，走 PCHIP。
- **展向分布数据未变**：UI 输入、CSV 输出格式向后兼容。

---

## 文件清单

**修改**：

| 文件 | 改动 |
|------|------|
| `src/business/stall_assessment/core.py` | 新增 `compute_alpha_span`（带 VG 逻辑）+ `pick_alpha` + `find_thickness_interval`；保留原 `interpolate` 函数（兼容路径） |
| `src/business/stall_assessment/__init__.py` | 导出新 API |
| `src/ui/stall_assessment_panel.py` | `profile_table` 加 VG 列；新增 `vg_table` GroupBox；Worker 改调 `compute_alpha_span`；绘图增强（VG 阴影 + 段边界竖虚线） |
| `src/help/stall_assessment.md` | 重写「输入数据格式」「插值方法」「UI 操作」3 节，新增 VG 配置说明 |
| `使用说明.md` | 失速评估章节追加 VG 配置说明 + 版本号备注 |
| `src/config.py` | `APP_VERSION = 'v0.3.18'` → `'v0.3.19'` |

**不动**：

- `core.plotting`（matplotlib 字体配置，沿用）。
- 原 `interpolate` 函数（保留作为兼容路径）。

---

## 关键复用

- `parse_span_text` / `parse_span_file`（core.py:66, 77）：展向分布解析，不改。
- `normalize_positions`（core.py:111）：展向位置无量纲化，不改。
- `find_intersections`（core.py:229）：失速攻角 vs 实际攻角交点，沿用。
- `plot_span_compare`（core.py:272）：双曲线对比绘图，沿用（增强在 panel 层加阴影）。

---

## 验证（端到端）

1. **py_compile**：每个改动文件单独编译通过。
2. **算法单元测试**（独立脚本）：
   - 构造标准表 `(100,0), (40,10), (40VG,12), (30,13), (30VG,15), (18,15.5)`。
   - 构造展向分布：`z ∈ [0,1]`，厚度从 100% 单调减到 18%。
   - 配置 VG 安装：`(30, z=0.2, z=0.4)`。
   - 验证：
     - `z=0.1`（厚度 70%，无 VG）：α 介于 α_100 和 α_40 之间。
     - `z=0.3`（厚度 35%，VG 区域内）：α 用 (α_40, α_30VG) 插值。
     - `z=0.5`（厚度 25%，VG 区域外）：α 用 (α_30, α_25) 插值（如标准表有 25）。
   - 边界测试：`z=0.2`（VG 起，应激活）、`z=0.4`（VG 止，应激活）、`z=0.41`（应不激活）。
3. **GUI 启动**：`python src/main.py` →「失速评估」。
4. **交互验证**：
   - 不填 VG 表 → 行为与 v0.3.18 一致。
   - 填 VG 表 → 画图出现阴影 + 竖虚线 + 失速攻角曲线在 VG 段变化。
   - 修改 VG 起/止 z → 阴影范围和曲线变化。
5. **导出**：CSV 含 `vg_active` 列。

---

## 非目标（明确排除）

- **不做** VG 段内攻角平滑过渡（用户明确「重点不是平滑」）。
- **不做** VG 安装范围自动从外部文件导入（v0.3.19 只支持 UI 手填，未来再加）。
- **不做** 标准 PCHIP 形状在 VG 段的保留（VG 段统一用两点线性，简单一致）。
- **不做** 多套 VG 配置文件的保存/加载（v0.3.19 单次会话内配置）。
