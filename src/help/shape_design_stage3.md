# STAGE-3 输出逻辑说明

> 适用面板：「叶片形状输出」→ 第 3 步「XFOIL 修正 → 重建 → 最终导出」
> 对应代码：`src/tools/shape_design_panel.py::Stage2Worker` + `src/shape_design/correction.py`

## 1. 这一步在做什么

STAGE-3 把 STAGE-1 输出的「标准翼型点云」按 STAGE-2 生成的「GEO 几何参数表」和「尾缘厚度表」做两件事：

1. **XFOIL 修正翼型**：对每个截面，按需调用 XFOIL 重新计算翼型坐标，让它的
   - **尾缘间隙（TGAP）** 符合 STAGE-2 指定的尾缘厚度
   - **相对厚度（TSET）** 符合 GEO 表中的 `Th%`
2. **重建 3D 外形**：用修正后的 2D 翼型叠加 GEO 表中的弦长 / 扭角 / 变桨轴 / 预弯 / 后掠，生成 3D 叶片点云。
3. **导出最终文件**：把 3D 叶片的所有几何表达一次性导出成一组标准文件（点云、几何表、Focus.mac、STP 等）。

UI 上看到的进度条 0–100% 分三段：**修正 (5→55) → 重建 (55→80) → 导出 (80→100)**。

---

## 2. 输入文件（不显示在 UI，走 ConfigCenter 默认路径）

| 文件 | 来源 | 路径 |
|---|---|---|
| `GEO_for_correction.xlsx` | **STAGE-2** 输出（已被尾缘厚度修改过） | `<输出>/stage2/GEO_for_correction.xlsx` |
| `standard_airfoil_for_correction.xlsx` | **STAGE-1** 输出（内部文件，对外不可见） | `<输出>/stage1/_internal/standard_airfoil_for_correction.xlsx` |
| `xfoil.exe` | 工具箱内置 | `src/_bin/xfoil.exe` |

> 缺任一文件 → 点「运行 STAGE-3」时弹窗提示「请先运行 STAGE-1 / STAGE-2」。

---

## 3. XFOIL 配置（UI 可调）

`_build_stage2_tab` 里 4 个控件，对应 `run_airfoil_correction()` 的入参：

| UI 控件 | 后端参数 | 默认 | 作用 |
|---|---|---|---|
| 后缘厚度修正起始 Th% | `th_threshold_tail` | 60 | 仅当 `Th% < 此值` 的截面（靠近叶尖）执行 **TGAP** |
| 相对厚度修正起始 Th% | `th_threshold_thick` | 40 | 仅当 `Th% > 此值` 的截面（靠近叶根）执行 **TSET** |
| 按 STAGE-2 输出的尾缘厚度修正（TGAP） | `enable_tgap` | 勾选 | 总开关：关 → 所有截面都不做 TGAP |
| 修正相对厚度（TSET） | `enable_tset` | 勾选 | 总开关：关 → 所有截面都不做 TSET |

判定逻辑（correction.py:807-809）：

```python
do_tgap = enable_tgap and (th_pct[idx] < th_threshold_tail)
do_tset = enable_tset and (th_pct[idx] > th_threshold_thick) and (|toc_before - toc_target| > toc_eps)
need_xfoil = do_tgap or do_tset
```

- `Th%` 在 40–60 之间 → 两项修正都可能生效
- `Th%` < 40 → 只做 TGAP
- `Th%` > 60 → 只做 TSET
- 两个总开关都关 → XFOIL 完全不跑，直接用原始翼型重建（退化模式）

---

## 4. 三阶段内部流程

### 阶段 A：XFOIL 修正（进度 5% → 55%）

对应 `run_airfoil_correction()`，内部又分 3 个子段。

#### A.1 准备（5% → 15%）`[1/3 准备]`

逐截面读 GEO + 翼型表，为每个截面准备一份任务卡：

- 从翼型表取出 `(x0, y0)`，剥掉最后 10 个尾缘点（`_strip_te_10`）→ 399 点
- 计算 `toc_before`（当前相对厚度）
- 计算 `tgap = TEth(mm) * 1e-3 / chord`（目标尾缘间隙 / 弦长，无量纲）
- 写出 `base_<label>_<idx>.dat`（XFOIL 输入）
- 决定 `do_tgap / do_tset / need_xfoil`

> 每完成一个截面发一次 `[1/3 准备] idx/total` 进度。

#### A.2 批量调用 XFOIL（15% → 40%）`[2/3 XFOIL]`

**关键优化**：把所有需要 XFOIL 的任务一次性交给子进程批量执行（`_run_xfoil_batch`），
而不是每个截面启一次 XFOIL —— 这是性能瓶颈所在，预计耗时按 `任务数 × timeout / 60` 估算。

- 启动时发 `[2/3 XFOIL] 启动批量修正：N/total 个截面需要 XFOIL`
- 子进程退出后发 `[2/3 XFOIL] 子进程退出，开始读结果 + 后处理`

中间这段时间 UI 阻塞在 `subprocess.run`，进度条不动是正常的。

#### A.3 读结果 + refit（40% → 55%）`[3/3 修正]`

逐截面：

1. 读 XFOIL 写出的 `corr_<label>_<idx>.dat`
2. 剥尾缘 10 点 → 399 点
3. 如需 TSET 或最后一个截面：`_refit_keep_x_by_surface_399`（保持 x 网格、对 y 做曲面最小二乘重拟合，让形状更光顺）
4. **补回尾缘 10 点**（`_add_te_10`）→ 409 点（写回 `corr_*.dat`）
5. 把修正后的 `(x, y)` 写回 `corrected[:, col_x/col_y]`
6. 记录一行 summary：`span / chord / Th% / toc_target / toc_before / toc_after / TE_target / TE_up / TE_low`

输出两个中间文件（在工作目录的 `Corrected_Airfoils/` 下）：

- `standard_airfoil_corrected.xlsx`：修正后的翼型点云（所有截面）
- `TE_thickness_corrected.xlsx`：修正前后对比表（9 列）

---

### 阶段 B：重建 3D 外形（55% → 80%）

对应 `build_result_from_corrected_files()`。

输入：`GEO_for_correction.xlsx` + `standard_airfoil_corrected.xlsx`

流程：

1. 从 GEO 表读 `Span / Chord / Twist / Th% / PitchAxis / Prebend / Sweep`（sweep 缺失置 0）
2. 从修正翼型表读所有截面，逐截面剥尾缘 → 统一到同一个 `profile_x` 网格（不一致就插值）
3. 调 `build_result_from_airfoil_points(...)` 把 2D 翼型 + 几何参数组装成 `ShapeDesignResult`：
   - 每个截面在 3D 空间中的实际坐标（考虑弦长、扭角、变桨轴、预弯、后掠）
   - 尾缘厚度沿展向的分布
4. 顺带写出 `StdAirfoil_used_2D.xlsx`（实际用于重建的 2D 翼型，便于事后核对）

进度回调：`[重建] idx/total`。

---

### 阶段 C：导出最终文件（80% → 100%）

对应 `export_shape_design()`。**STAGE-3 固定导出全部 6 类文件**（UI 不再提供勾选）：

| 文件 | 默认路径 | 内容 |
|---|---|---|
| `standard_airfoil_points.xlsx` | `<输出>/stage3/standard_airfoil_points.xlsx` | 修正后的标准翼型点云（MATLAB 风格双列） |
| `blade_3d_points.xlsx` | `<输出>/stage3/blade_3d_points.xlsx` | 3D 叶片点云（X/Y/Z 三列 × 各截面） |
| `blade_aero_geometry.xlsx` | `<输出>/stage3/blade_aero_geometry.xlsx` | 几何参数表（Span/Chord/Twist/Th%/PitchAxis/Prebend/Sweep） |
| `trailing_edge_thickness.xlsx` | `<输出>/stage3/trailing_edge_thickness.xlsx` | 尾缘厚度分布（span / R_thickness / thickness(mm) / toSS / toPS） |
| `Focus.mac` | `<输出>/stage3/Focus.mac` | FOCUS6 宏文件（含叶片几何 + 翼型表） |
| `3D_points.stp` | `<输出>/stage3/CATIA/3D_points.stp` | CATIA STP 点云 |

完成后日志：

```
=== STAGE-3 完成 ===
  airfoil_points: <path>
  3d_points:      <path>
  geometry:       <path>
  tail:           <path>
  focus:          <path>
  step_points:    <path>
```

---

## 5. TGAP / TSET 修正算法说明

### TGAP（尾缘间隙修正）

**目的**：让翼型尾缘上下表面的间隙等于 STAGE-2 给定的目标厚度。

- 输入：翼型坐标 + `tgap = TEth(mm) / chord / 1000`
- XFOIL 内部按 `tgap` 重开尾缘 → 生成新的 `(x, y)`
- 仅对 `Th% < th_threshold_tail` 的截面生效（靠近叶尖的薄翼型才有意义）

### TSET（相对厚度设置）

**目的**：让翼型的实际相对厚度（最大厚度 / 弦长）等于 GEO 表中指定的 `Th%`。

- 输入：翼型坐标 + `toc_target = Th% / 100`
- 先算 `toc_before`，若 `|toc_before - toc_target| > toc_eps (1e-5)` 才触发
- XFOIL 内部按 `tgap` + 目标 `toc` 重新生成翼型
- 仅对 `Th% > th_threshold_thick` 的截面生效（靠近叶根的厚翼型才需要厚度修正）

### refit（曲面光顺）

XFOIL 输出后还会做一次 `_refit_keep_x_by_surface_399`：

- 保持 x 网格不变（399 点）
- 用最小二乘曲面拟合 y，过滤 XFOIL 可能引入的数值噪声
- 触发条件：做了 TSET，或这是最后一个截面（叶根）

---

## 6. 关键路径速查

| 路径 | 由谁生成 | 谁消费 |
|---|---|---|
| `<输出>/stage1/_internal/standard_airfoil_for_correction.xlsx` | STAGE-1 | STAGE-3 输入 |
| `<输出>/stage2/GEO_for_correction.xlsx` | STAGE-2 | STAGE-3 输入 |
| `<输出>/stage3/Corrected_Airfoils/standard_airfoil_corrected.xlsx` | STAGE-3 阶段 A | STAGE-3 阶段 B |
| `<输出>/stage3/Corrected_Airfoils/TE_thickness_corrected.xlsx` | STAGE-3 阶段 A | 留档（人工核对） |
| `<输出>/stage3/StdAirfoil_used_2D.xlsx` | STAGE-3 阶段 B | 留档（实际用于重建的 2D） |
| `<输出>/stage3/*.{xlsx, mac, stp}` | STAGE-3 阶段 C | **最终交付物** |

---

## 7. 调试模式

当前 UI 固定为「完整运行（修正 + 重建）」，没有暴露调试模式。如需排查：

- 代码内 `mode='debug'` 时，`keep_workdir=True`，XFOIL 临时目录（`xfoil_work/`）不会被清理
- 可查看 `base_*.dat`（输入）与 `corr_*.dat`（输出）的逐截面差异
- 切换方式：临时改 `_on_run_stage2` 里的 `mode_id → 2`

---

## 8. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 点「运行 STAGE-3」弹「找不到修正 GEO」 | STAGE-2 没跑过 | 先跑 STAGE-2 |
| 弹「找不到修正翼型」 | STAGE-1 没跑过 | 先跑 STAGE-1 |
| 进度卡在 15–40% | XFOIL 子进程在批量计算 | 按任务数估算时长，正常等 |
| `[错误] FileNotFoundError: 未找到 XFOIL` | `src/_bin/xfoil.exe` 缺失 | 从工具箱分发包重新拷 |
| `参数无效：必须是数字` | Th% 输入框填了非数字 | 改回数字（默认 60/40） |
| 修正后 `toc_after` 与 `toc_target` 还是有差 | XFOIL 数值精度 + refit 平滑 | 差异应在 `toc_eps=1e-5` 量级，可接受 |
