# FOCUS6求解器配置模板文件

本文件夹包含所有FOCUS6求解器功能的配置文件模板。

## 📋 目录

- [farob求解器模板](#farob求解器模板旧格式)
- [frbex求解器模板](#frbex求解器模板新格式)
- [通用辅助文件](#通用辅助文件)
- [模板修改说明](#模板修改说明)
- [求解器类型对比](#求解器类型对比)

---

## 🔧 farob求解器模板

farob求解器使用传统的.frb配置文件，所有参数直接写在.frb文件中。

### 1. parse.frb.template
- **功能**：读取mac文件
- **用途**：将blade_geometry.mac解析为BUFFER数据
- **输出**：BUFFER文件夹（包含解析后的数据）
- **执行命令**：`farob.exe /F6 parse.frb`

### 2. build_database.frb.template
- **功能**：解析mac文件
- **用途**：从BUFFER数据构建blade_db.xls
- **输入**：radius参数（单位：mm）
- **输出**：blade_db.xls
- **执行命令**：`farob.exe /F6 build_database.frb`

### 3. structural_analysis.frb.template
- **功能**：应变计算（farob）
- **用途**：结构分析主配置文件
- **输入**：`{radius}` - 叶片半径（单位：mm）
- **输出**：buffer\strain_summary_BLD.txt
- **相关文件**：location.frb、points.def、foculf.txt
- **执行命令**：`farob.exe /F6 structural_analysis.frb`

### 4. eigenfr.frb.template
- **功能**：频率计算（farob求解器）
- **用途**：计算叶片固有频率
- **输出**：
  - freq_coupled.txt（耦合频率）
  - freq_uncoupled.txt（非耦合频率）
- **执行命令**：`farob.exe /F6 eigenfr.frb`
- **注意**：频率计算功能统一使用farob求解器执行

---

## 🚀 frbex求解器模板

frbex求解器使用新的配置方式：.frb文件调用.json配置文件，参数更清晰、更易维护。

### 5. frbex_build_blade_database.frb.template
- **功能**：构建叶片数据库（frbex）
- **用途**：从BUFFER数据构建blade_db.xls
- **特点**：通过.json文件配置参数
- **相关配置**：frbex_build_blade_database.json.template
- **执行命令**：`frbex.exe /F6 frbex_build_blade_database.frb`

### 6. frbex_build_blade_database.json.template
- **功能**：构建叶片数据库的配置文件
- **主要参数**：
  - `blade_identifier` - 叶片标识符
  - `drmx` - 截面间距阈值（单位：mm）
  - `s` - 截面位置数组
  - `vtk_cross_mesh` - 是否输出VTK截面网格
  - `vtk_lines` - 是否输出VTK线图
- **占位符**：
  - `{drmx}` - 截面间距阈值，自动替换

### 7. frbex_structural_analysis.frb.template
- **功能**：应变计算（frbex）
- **用途**：结构分析主配置文件
- **特点**：支持更多分析选项（单位载荷、屈曲、疲劳等）
- **相关配置**：frbex_structural_analysis.json.template
- **执行命令**：`frbex.exe /F6 frbex_structural_analysis.frb`

### 8. frbex_structural_analysis.json.template
- **功能**：结构分析的配置文件
- **主要参数**：
  - `unit_loads` - 是否计算单位载荷
  - `buckling` - 是否计算屈曲
  - `strain_analysis` - 是否计算应变（必须=true）
  - `write_extreme_strain` - 是否输出极端应变
  - `write_extreme_force` - 是否输出极端力
  - `s` - 截面位置数组
  - `loadcases` - 载荷工况列表
- **占位符**：
  - `{s_positions}` - 截面位置数组，自动替换
  - `{work_folder}` - 工作文件夹路径，自动替换

### 9. frbex_tip_deflection.frb.template
- **功能**：叶尖挠度计算（仅frbex支持）
- **用途**：计算叶片叶尖挠度
- **特点**：需要先构建blade_db（buffer/frbex.dbf）
- **相关配置**：frbex_tip_deflection.json.template
- **执行命令**：`frbex.exe /F6 frbex_tip_deflection.frb`

### 10. frbex_tip_deflection.json.template
- **功能**：叶尖挠度计算的配置文件
- **主要参数**：
  - `write2vtk` - 是否输出VTK格式
  - `write2tim` - 是否输出TIM格式
  - `writetip2tim` - 是否写入叶尖TIM文件
  - `blade_number` - 叶片编号
  - `number_stations` - 截面数量
  - `nr_blades` - 叶片数量
  - `correct_loadfactor` - 是否修正载荷系数
  - `azimuth_min/max` - 方位角范围
  - `cone` - 锥角
  - `tilt` - 倾角
  - `s` - 截面位置数组（**v5.1更新：已改为空数组[]**）
  - `loadcases` - 载荷工况列表
- **占位符**：
  - ~~`{s_positions_m}`~~ - ~~截面位置数组（单位：m），自动替换~~ （v5.1已移除，s字段固定为空数组）
  - `{work_folder}` - 工作文件夹路径，自动替换
- **v5.1变更说明**：
  - s字段从 `{s_positions_m}` 改为固定空数组 `[]`
  - 不再需要从ZSPAN文件读取展向位置数据
  - 不再需要配置展向位置文件

### 11. frbex_eigenfrequencies.frb.template
- **功能**：频率计算（frbex求解器配置）
- **用途**：计算叶片固有频率（使用frbex数据格式）
- **特点**：
  - 使用 `buffer/frbex.dbf` 数据库
  - 生成 `list.xls` 结果文件
  - 输出耦合频率和非耦合频率
- **输出**：
  - freq_coupled.txt（耦合频率）
  - freq_uncoupled.txt（非耦合频率）
  - list.xls（频率列表）
- **执行命令**：`farob.exe /F6 frbex_eigenfrequencies.frb`
- **重要说明**：
  - 虽然配置文件是frbex格式
  - 但频率计算功能统一使用 **farob求解器** 执行
  - farob求解器可以读取frbex.dbf数据库文件

---

## 📁 通用辅助文件

### 12. solver_geometry.mac.template
- **功能**：应变计算 / 频率计算
- **用途**：指定使用哪个几何文件
- **内容**：`USE MACRO blade_geometry.mac`
- **说明**：被structural_analysis和eigenfr功能引用

### 12. location.frb.template
- **功能**：应变计算（farob）
- **用途**：定义展向位置（Z-VALUE）
- **输入**：`{z_values}` - 展向位置列表
- **格式**：
  ```
  ACTIVE Z-VALUE      {值1}
  USE MACRO MACROS\SECTION.MAC
  ACTIVE Z-VALUE      {值2}
  USE MACRO MACROS\SECTION.MAC
  ...
  ```

### 13. points.def.template
- **功能**：应变计算（farob）
- **用途**：疲劳计算初始设置
- **内容**：固定格式的疲劳参数

### 14. foculf.txt.template
- **功能**：应变计算 - 载荷转化（farob）
- **用途**：将载荷文件转换为LOAD.LD1格式
- **输入**：
  - `{blade_span}` - 叶片半径（单位：m）
  - `{load_data}` - 载荷数据（分号分隔）
- **输出**：LOAD.LD1
- **执行命令**：`UserLoadcaseConverter.exe foculf.txt`

---

## 🔨 模板修改说明

### 1. 如何修改模板文件

**直接修改**：
- 用文本编辑器打开对应的 `.template` 文件
- 根据需要修改配置内容
- 保存文件（UTF-8编码）

**注意事项**：
- 修改后需要重启程序才能生效
- 建议修改前先备份原文件
- 保持文件编码为 UTF-8

### 2. 占位符说明

**通用占位符**：
- `{radius}` - 叶片半径（mm），代码会自动替换
- `{blade_span}` - 叶片半径（m），代码会自动替换
- `{work_folder}` - 工作文件夹路径，代码会自动替换

**frbex专用占位符**：
- `{drmx}` - 截面间距阈值（frbex），自动替换
- `{s_positions}` - 截面位置数组（frbex），自动替换
- `{s_positions_m}` - 截面位置数组（frbex，单位：m），自动替换

**载荷相关占位符**：
- `{load_data}` - 载荷数据，代码会自动替换
- `{z_values}` - 展向位置，代码会自动替换

### 3. 文件命名规则

- `.template` 后缀表示这是模板文件
- 实际使用时，程序会：
  1. 读取模板文件
  2. 替换所有占位符
  3. 生成实际的配置文件（去掉.template后缀）

---

## 📊 求解器类型对比

### farob（旧格式）
- **配置方式**：所有参数直接写在.frb文件中
- **文件数量**：每个功能1个.frb文件
- **适用功能**：读取mac、解析mac、应变计算、频率计算
- **优点**：配置简单直观
- **缺点**：参数较多时文件较长，不易维护

### frbex（新格式）
- **配置方式**：.frb文件 + .json配置文件
- **文件数量**：每个功能2个文件（.frb + .json）
- **适用功能**：读取mac、解析mac、应变计算、叶尖挠度
- **优点**：
  - 参数结构清晰（JSON格式）
  - 更容易修改和维护
  - 支持更多功能（如叶尖挠度）
- **缺点**：需要维护两个文件

### 功能支持对比

| 功能 | farob | frbex |
|------|-------|-------|
| 读取mac文件 | ✅ | ✅ (共用parse.frb) |
| 解析mac文件 | ✅ | ✅ |
| 应变计算 | ✅ | ✅ |
| 频率计算 | ✅ | ✅ (配置文件不同，但统一使用farob求解器) |
| 叶尖挠度计算 | ❌ | ✅ |

---

**版本**：v5.1
**创建日期**：2026-03-22
**更新日期**：2026-03-23
**维护者**：AI Assistant
**更新历史**：
- v4.7 (2026-03-22): 添加frbex_eigenfrequencies.frb.template模板说明；频率计算功能支持frbex求解器
- v5.1 (2026-03-23): 更新frbex_tip_deflection.json模板说明（s字段改为空数组，不再需要配置展向位置）
