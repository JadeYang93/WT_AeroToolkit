# CATIA 叶片建模

把叶片形状输出 STAGE-3 导出的 `3D_points.stp` 点云，通过 CATIA 自动化构建为叶片曲面。

## 前置条件

1. 本机已安装 **CATIA V5** + **pywin32**（`pip install pywin32`）
2. 已通过「叶片形状输出」STAGE-3 生成 `3D_points.stp`

## 三步流程

> 三步独立运行，用户自主决定何时、对哪个文档运行。每步完成后请到 CATIA 里检查几何集质量，再决定是否继续下一步。

### 准备: 导入点云

1. 启动 CATIA，打开/新建一个**零件文档（.CATPart）**
2. 菜单「文件 → 打开」选择 `3D_points.stp` 导入（点云会带 `Sect{组}_{点}` 命名）

### ① 构建截面

读取点云，每个截面（Sect 组）生成: 样条 + 光顺曲线 + 平面 + 前缘点 + 尾缘点 + 弦线。

- 核心参数: 截面数、起始组号、四段光顺阈值
- 输出几何集: `Z_Splines` / `Z_Smooths` / `Z_Planes` / `Z_Edges` / `Z_TrailingEdges`

### ② 重采样光顺

对 ① 输出的 `Z_Smooths` 每条样条等距重采样（默认 149 点）+ 二次光顺。

- 核心参数: 源样条集（默认承接 `Z_Smooths`）、重采样点数、光顺偏差阈值
- 输出几何集: `Z_ResamplePoints` / `Z_OriginalSpline` / `Z_ResampleSmooth`

### ③ 生成曲面

把 ② 输出的 `Z_ResampleSmooth` 多条截面曲线 → 多截面曲面（Loft）。

- 核心参数: 源曲线集（默认承接 `Z_ResampleSmooth`）、截面耦合方式
- 输出: part 根下 `loft_surface`

## 常见问题

**Q: 提示「未检测到 CATIA」？**
A: 请先启动 CATIA 并打开零件文档（.CATPart），再点运行。

**Q: 第②步报「几何集不存在: Z_Smooths」？**
A: 请先运行第①步生成 `Z_Smooths`，或在高级参数里把「源样条集」改为实际存在的几何集名。

**Q: 三步默认能直接串联吗？**
A: 可以。默认几何集名已统一为 `Z_*` 体系: ①→`Z_Smooths`→②→`Z_ResampleSmooth`→③。如需处理手动导入的其他样条（如 `line`），在对应步骤的高级参数里改写源集名即可。

## 参数记忆

调过的参数会自动保存到 `配置/catia_modeling_params.json`，下次打开面板自动恢复。
