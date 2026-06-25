# 载荷预估使用说明

> 路径：工具箱 → 载荷预估
> 模块 ID：`load_estimation`

## 这是什么

基准稳态/动态载荷的多项式拟合 + 新工况载荷预测。

输入一组基准工况（稳态参数 + 动态载荷）和一组新工况（只有稳态参数），
用 6 阶多项式拟合「稳态参数 → 动态载荷」的映射关系，再把新工况的稳态参数代入，
预测出对应的动态载荷。

## 输入数据格式

放一份 `load_data.xlsx` 到 `输入数据/load_estimation/`，必须包含 3 个 sheet：

| Sheet 名 | 列含义 |
|---|---|
| `baseLineSteady` | `t, paramX, paramY, ...`（基准稳态：t 是展向位置，paramX/paramY 是自变量） |
| `baselineDynamic` | `t, maxMx, minMx, maxMy, minMy`（基准动态：4 个载荷分量） |
| `newSteady` | `t, paramX, paramY, ...`（新工况稳态：只需要 t + 自变量） |

> 第 1 行为表头（自动跳过）。`baseLineSteady` 和 `baselineDynamic` 行数应相等。

## 拟合关系

- `maxMx / minMx ← polyfit(baseLineSteady.paramX, baselineDynamic.maxMx / minMx, 6)`
- `maxMy / minMy ← polyfit(baseLineSteady.paramY, baselineDynamic.maxMy / minMy, 6)`
- 新工况预测：把 `newSteady.paramX / paramY` 代入上面的 6 阶多项式

## 输出

全部写入 `输出/load_estimation/`：

| 文件 | 内容 |
|---|---|
| `result.csv` | 新工况预测结果（zspan, maxMx, minMx, maxMy, minMy） |
| `coefficients.csv` | 4 组多项式系数（高次 → 低次） |
| `figure_baseline_*.png` × 4 | 基准动态：原始 vs 拟合曲线（maxMx / minMx / maxMy / minMy） |
| `figure_new_*.png` × 4 | 新工况预测曲线（4 个分量） |

## UI 操作

1. 「数据文件」浏览选择 `load_data.xlsx`（默认走 `输入数据/load_estimation/`）
2. 点「运行拟合」→ 后台线程执行读取 + 拟合 + 写文件
3. 完成后，「拟合曲线」区的下拉框激活，可选 8 个视图（baseline × 4 + new × 4）
4. 用「上一张 / 下一张」顺序翻看
5. 「📂 打开输出目录」直接打开 `输出/load_estimation/`

## 路径配置

输入 / 输出目录在「⚙ 设置」里改。改完即时生效，无需重启。
