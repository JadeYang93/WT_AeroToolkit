# 载荷预估 — 实现原理与工作流程

> 配套文档：用法说明见 `load_estimation.md`（输入格式 / UI 操作 / 输出文件）
> 本文聚焦：**为什么这么做、算法怎么跑、数据怎么流**

## 1. 业务问题

叶片结构分析中，动载荷分量（`Mx / My` 的极大值与极小值）通常来自基准工况的气弹仿真。
当需要评估一个**新工况**（不同稳态参数沿展向的分布）的载荷时，重跑气弹仿真成本很高。
本模块用基准数据训练一个**展向映射**，把新工况的稳态参数代入即可秒级预测动载荷。

形式化：
- 已知：基准稳态 $S_b(z)$ → 基准动载荷 $D_b(z)$，沿展向 $z$ 的两组离散点
- 求：新稳态 $S_n(z)$ → 新动载荷预测 $\hat D_n(z)$
- 假设：$D$ 是 $S$ 的函数（与 $z$ 解耦）—— $D = f(S)$，对每个分量独立拟合

## 2. 为什么用 6 阶多项式

`np.polyfit` 的 6 阶选择是源项目 `load_estimation.py` 沿用的经验值，理由：

| 备选 | 不选的原因 |
|---|---|
| 3 阶以下 | 叶片载荷展向分布有拐点（根部约束 + 叶尖效应），低阶无法捕捉 |
| 8 阶以上 | 高阶多项式在端点（叶根 / 叶尖）容易过冲（Runge 现象） |
| 样条 | 平滑但系数存储和插值略复杂；载荷预测不需要 C² 连续 |

6 阶 = 7 个系数，对 30~50 个截面点足够稳定，端点行为可控。`coefficients.csv` 输出 7 列
（`c_x6 ... c_x0`）即此 7 个系数，便于离线复算或第三方工具核对。

## 3. 数据流（端到端）

```
load_data.xlsx（3 sheet）
        │
        ▼
┌─────────────────────────────┐
│ load_data()                  │
│  openpyxl read_only=True     │  ← 必须 wb.close()，否则 Windows 文件锁
│  3 sheet → 3 ndarray         │
│  baseLineSteady 行数断言     │  ← 与 baselineDynamic 不等则截断 dynamic
└─────────────────────────────┘
        │
        ▼  data = {base_steady, base_dynamic, new_steady}
┌─────────────────────────────┐
│ fit_loads(data, n=6)         │
│                              │
│  4 次 polyfit（独立）：       │
│   p_maxMx ← fit(paramX, maxMx)
│   p_minMx ← fit(paramX, minMx)
│   p_maxMy ← fit(paramY, maxMy)  ← 注意：My 用 paramY，不是 paramX
│   p_minMy ← fit(paramY, minMy)
│                              │
│  baseline_fits = polyval(p, baseLineSteady.paramX/Y)  ← 拟合曲线在基准点上的回算
│  new_preds    = polyval(p, newSteady.paramX/Y)        ← 新工况预测
└─────────────────────────────┘
        │
        ▼  results = {coeffs, baseline, new, result}
┌─────────────────────────────┐
│ save_results(results, out)   │
│  result.csv        5 列：zspan + 4 分量预测
│  coefficients.csv  4×7：4 组系数（高次→低次）
│  figure_baseline_*.png × 4：基准原始 vs 拟合曲线（黑+红）
│  figure_new_*.png × 4：     新工况预测曲线（蓝）
└─────────────────────────────┘
```

## 4. 列约定（不可变）

| Sheet | 列序（跳过表头后） |
|---|---|
| `baseLineSteady` | `[0]t  [1]paramX  [2]paramY  ...` |
| `baselineDynamic`| `[0]maxMx  [1]minMx  [2]maxMy  [3]minMy` |
| `newSteady`      | `[0]t  [1]paramX  [2]paramY  ...` |

**关键不对称**：`maxMx/minMx` 用 `paramX` 拟合，`maxMy/minMy` 用 `paramY` 拟合。
源项目假设 `Mx` 主要由一个稳态参数驱动（如弦长 / 厚度），`My` 由另一个（如扭角）。
若你的数据语义不同，需在 `fit_loads` 调整列索引。

## 5. 拟合关系（数学）

对每个分量 $D \in \{\max M_x, \min M_x, \max M_y, \min M_y\}$：

$$
D(z) \approx \sum_{k=0}^{6} c_k \cdot s(z)^{6-k}
$$

其中 $s$ 取 `paramX`（$M_x$ 系）或 `paramY`（$M_y$ 系）。最小二乘解：

$$
\mathbf{c}^* = \arg\min_{\mathbf{c}} \sum_i \left( D_i - \sum_k c_k s_i^{6-k} \right)^2
$$

`np.polyfit` 内部用 SVD 求解，条件数大时会有 `RankWarning`（不影响计算，但说明该阶数
对当前数据可能过参数化）。

## 6. 工作流程（UI 视角）

```
用户操作                              后台 LoadEstimationWorker
─────────────────────────────────────────────────────────────
选 load_data.xlsx
点「运行拟合」                   ─►   emit progress(5, '读取数据')
                                      load_data(xlsx)
                                 ─►   emit progress(30..40, 行数报告)
                                      fit_loads(data)
                                 ─►   emit progress(55, '执行 6 阶多项式拟合')
                                      save_results(results, out_dir)
                                 ─►   emit progress(70, '写入输出目录')
                                 ─►   emit progress(100, '=== 拟合完成 ===')
                                      finished signal → 主线程启用查看控件

切下拉「baseline-maxMx」          ─►   _refresh_plot()
                                      ax.clear()
                                      plot_result(ax, results, 'baseline', 'maxMx')
                                      canvas.draw()

「上一张 / 下一张」               ─►   view_combo.setCurrentIndex(idx ± 1) % 8
```

8 个视图 = `{baseline, new} × {maxMx, minMx, maxMy, minMy}`，顺序见 `VIEW_OPTIONS`。

## 7. 不可变量与已知边界

| 不变量 | 处理 |
|---|---|
| Excel 必须 3 个 sheet 名严格匹配 | 不匹配 → `KeyError` 由 worker 捕获 → 弹窗 |
| `baseLineSteady` 行数 = `baselineDynamic` 行数 | 不等 → 警告 + 截断 dynamic |
| 6 阶多项式系数顺序 = 高次 → 低次 | `coefficients.csv` 表头固定 7 列 |
| 字体配置在 UI 侧（`import plotting`） | core.py 不设置 rcParams，避免双重配置 |

## 8. 源代码索引

| 文件 | 角色 |
|---|---|
| `src/load_estimation/core.py` | 业务逻辑（`load_data` / `fit_loads` / `save_results` / `plot_result` + `N_ORDER=6` / `COMPONENTS` / `VIEW_OPTIONS`） |
| `src/load_estimation/__init__.py` | 公共 API 导出 |
| `src/tools/load_estimation_panel.py` | UI（`LoadEstimationWorker` QThread + `LoadEstimationPanel` 主面板） |
| `src/help/load_estimation.md` | 用法说明（输入格式 / UI 操作 / 输出文件） |

## 9. 常见误用

- **`baseLineSteady` / `baselineDynamic` 行数不等** → 模块会截断 dynamic 并警告；真实数据应保证等长
- **`newSteady.paramX` 范围超出基准** → 多项式外推，端点可能振荡；预测可信区间是基准 `paramX` 范围内
- **`paramX` / `paramY` 列含 0 或空** → `polyfit` 会 NaN；需在 Excel 中清洗
- **想用不同阶数** → 当前 UI 不暴露，改 `core.py` 的 `N_ORDER` 常量即可
