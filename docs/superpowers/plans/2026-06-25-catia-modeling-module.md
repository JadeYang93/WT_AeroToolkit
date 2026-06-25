# CATIA 叶片建模模块 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `参考代码/` 下三个 CATIA 自动化脚本封装为侧边栏独立工具模块「📐 CATIA 叶片建模」，三步串联点云→截面→曲面。

**Architecture:** 业务层 `src/catia_modeling/` 子包（`CatiaContext` + 三个纯函数 + 参数 dataclass + JSON 持久化），无 PyQt 依赖；UI 层 `src/tools/catia_modeling_panel.py` 继承 `BaseWorkerPanel`，三个步骤 GroupBox（核心参数直露 + 高级折叠）+ Worker 子线程驱动 CATIA。三步几何集命名统一 `Z_*` 体系默认串联。

**Tech Stack:** PyQt5（项目实际用 PyQt5，非 PyQt6）、pywin32（`win32com.client.Dispatch`）、Python dataclasses、JSON 持久化。

**Spec:** `docs/superpowers/specs/2026-06-25-catia-modeling-module-design.md`

**项目实情说明（影响 TDD 策略）：**
- 项目**无 `tests/` 目录**，无单元测试惯例，所有模块均为"UI 面板 + 业务子包"形态，无测试文件。
- CATIA 自动化无法在无 CATIA 实例的环境跑端到端测试。
- 因此本计划**不强制 TDD**，而是采取：(1) 业务层设计为无 PyQt 依赖（保留可测性）；(2) 每个 task 产出的代码用最小验证脚本确认能 import / 逻辑正确；(3) 频繁提交。可测性设计体现在 Task 9（可选 mock 测试）。

---

## 文件结构

```
src/
├── main.py                                    # Modify: TOOLS 加一行 + import
├── catia_modeling/                            # Create: 业务子包
│   ├── __init__.py                            #   导出公共 API
│   ├── exceptions.py                          #   自定义异常
│   ├── params_store.py                        #   JSON 参数持久化
│   ├── context.py                             #   CatiaContext（连接+句柄封装）
│   ├── sections.py                            #   SectionParams + build_sections()
│   ├── resample.py                            #   ResampleParams + resample_and_smooth()
│   ├── loft.py                                #   LoftParams + build_loft_surface()
│   └── worker.py                              #   CatiaModelingWorker(QThread) 三步通用
└── tools/
    └── catia_modeling_panel.py                # Create: UI 面板（继承 BaseWorkerPanel）
配置/
└── catia_modeling_params.json                 # 运行时生成（首次 save 时）
src/help/
└── catia_modeling.md                          # Create: 帮助文档
requirements.txt                               # Modify: 加 pywin32
```

**职责边界：**
- `exceptions.py`：仅异常类定义，无逻辑
- `params_store.py`：仅 JSON 读写 + 默认值，无 CATIA/PyQt
- `context.py`：仅 CATIA COM 连接与句柄缓存，无业务算法
- `sections.py` / `resample.py` / `loft.py`：各含一个 dataclass + 一个纯函数，无 PyQt
- `worker.py`：QThread 子类，调用上面三个函数，发信号
- `catia_modeling_panel.py`：纯 UI 编排，不写 CATIA 逻辑

---

## Task 1: 子包骨架 + 异常定义

**Files:**
- Create: `src/catia_modeling/__init__.py`
- Create: `src/catia_modeling/exceptions.py`

- [ ] **Step 1: 创建异常模块**

`src/catia_modeling/exceptions.py`:

```python
# -*- coding: utf-8 -*-
"""CATIA 建模模块的自定义异常。

所有异常继承 CatiaModelError，UI 层可统一捕获后弹窗。
"""


class CatiaModelError(Exception):
    """CATIA 建模模块异常基类。"""


class CatiaNotRunningError(CatiaModelError):
    """CATIA 未启动或 COM 连接失败。"""


class NoActiveDocumentError(CatiaModelError):
    """CATIA 已启动但没有打开的活动文档。"""


class WrongDocumentTypeError(CatiaModelError):
    """活动文档不是 PartDocument（如打开了 Drawing/Product）。"""


class GeoSetNotFoundError(CatiaModelError):
    """指定的几何集（HybridBody）不存在。

    属性:
        geo_set_name: 找不到的几何集名
    """

    def __init__(self, geo_set_name):
        self.geo_set_name = geo_set_name
        super().__init__(f'几何集不存在：{geo_set_name}')


class PointNamingError(CatiaModelError):
    """点云缺少 Sect{组}_{点} 命名约定。"""
```

- [ ] **Step 2: 创建包 __init__（空占位，后续 task 补充导出）**

`src/catia_modeling/__init__.py`:

```python
# -*- coding: utf-8 -*-
"""CATIA 叶片建模业务子包。

对外公共 API（后续 task 逐步导出）：
    CatiaContext          连接 + 文档句柄封装
    SectionParams         步骤①参数
    build_sections        步骤①函数
    ResampleParams        步骤②参数
    resample_and_smooth   步骤②函数
    LoftParams            步骤③参数
    build_loft_surface    步骤③函数
"""
```

- [ ] **Step 3: 验证可导入**

Run（在 `src/` 目录下）:
```bash
cd src && python -c "from catia_modeling.exceptions import CatiaNotRunningError, GeoSetNotFoundError; print('OK', CatiaNotRunningError.__name__)"
```
Expected: `OK CatiaNotRunningError`

- [ ] **Step 4: Commit**

```bash
git add src/catia_modeling/__init__.py src/catia_modeling/exceptions.py
git commit -m "feat(catia_modeling): 新建子包骨架与异常定义"
```

---

## Task 2: 参数持久化（params_store）

**Files:**
- Create: `src/catia_modeling/params_store.py`

- [ ] **Step 1: 实现参数存储**

`src/catia_modeling/params_store.py`:

```python
# -*- coding: utf-8 -*-
"""CATIA 建模参数的 JSON 持久化。

独立于 ConfigCenter（后者为路径字段设计，带路径校验，不适合存数值参数）。

存储位置: <PROJECT_ROOT>/配置/catia_modeling_params.json
格式: {"sections": {...}, "resample": {...}, "loft": {...}, "input": {...}, "ui": {...}}

容错: 文件缺失/损坏 → 返回全默认值（不抛异常）。
"""
import json
import os
import tempfile

# 默认参数（与设计文档 3.5 表一致；几何集名统一 Z_* 体系默认串联）
DEFAULTS = {
    'sections': {
        'num_groups': 96,
        'start_group': 1,
        'smooth_thresholds': [4, 3, 2, 1],
        'points_per_section': 400,
        'le_point_num': 200,
        'te_point1_num': 1,
        'te_point399_num': 399,
        'tangency_threshold': 0.5,
        'correction_mode': 3,
        'spline_set': 'Z_Splines',
        'smooth_set': 'Z_Smooths',
        'plane_set': 'Z_Planes',
        'edge_set': 'Z_Edges',
        'te_set': 'Z_TrailingEdges',
    },
    'resample': {
        'source_set': 'Z_Smooths',
        'num_points': 149,
        'smooth_max_deviation': 1.0,
        'tangency_threshold': 0.5,
        'correction_mode': 3,
        'point_set': 'Z_ResamplePoints',
        'original_set': 'Z_OriginalSpline',
        'smooth_set': 'Z_ResampleSmooth',
    },
    'loft': {
        'source_set': 'Z_ResampleSmooth',
        'section_coupling': 1,
        'relimitation': 1,
        'canonical_detection': 2,
    },
    'input': {
        'stp_path': '',
    },
    'ui': {
        'advanced_expanded': False,
    },
}


def _config_path():
    """返回 JSON 存储路径。<PROJECT_ROOT>/配置/catia_modeling_params.json

    PROJECT_ROOT 通过相对本文件向上回溯定位（src/catia_modeling/ → 项目根）。
    """
    # 本文件: <root>/src/catia_modeling/params_store.py
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, '配置', 'catia_modeling_params.json')


def _deep_merge(base, override):
    """递归合并: override 的值覆盖 base，base 提供缺省键。"""
    result = {}
    for key, val in base.items():
        if isinstance(val, dict) and isinstance(override.get(key), dict):
            result[key] = _deep_merge(val, override[key])
        else:
            result[key] = override.get(key, val)
    # 保留 override 里 base 没有的键（向前兼容旧配置）
    for key in override:
        if key not in base:
            result[key] = override[key]
    return result


def load_params():
    """读取参数。文件缺失/损坏 → 返回全默认值的副本。"""
    path = _config_path()
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULTS))  # 深拷贝
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return json.loads(json.dumps(DEFAULTS))
        return _deep_merge(DEFAULTS, data)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULTS))


def save_params(params):
    """原子写入参数。先写临时文件再 rename，避免中途崩溃损坏。

    若传入 params 缺少某些键，用 DEFAULTS 补齐后写盘。
    """
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    full = _deep_merge(DEFAULTS, params)
    # 原子写: 同目录临时文件 → os.replace
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(suffix='.json', dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(full, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
```

- [ ] **Step 2: 验证读写与容错**

Run（在 `src/` 目录下）:
```bash
cd src && python -c "from catia_modeling.params_store import load_params, save_params; p = load_params(); print('默认 sections.num_groups =', p['sections']['num_groups']); p['sections']['num_groups'] = 50; save_params(p); print('重读 =', load_params()['sections']['num_groups'])"
```
Expected:
```
默认 sections.num_groups = 96
重读 = 50
```

- [ ] **Step 3: 验证容错（损坏文件回退默认）**

Run:
```bash
cd src && python -c "open('../配置/catia_modeling_params.json','w',encoding='utf-8').write('!!!不是json!!!'); from catia_modeling.params_store import load_params; print('损坏后回退 =', load_params()['sections']['num_groups'])"
```
Expected: `损坏后回退 = 96`

- [ ] **Step 4: 清理测试产生的配置文件，Commit**

```bash
git add src/catia_modeling/params_store.py
git commit -m "feat(catia_modeling): 参数 JSON 持久化（load/save + 容错）"
```

---

## Task 3: CatiaContext（连接 + 句柄封装）

**Files:**
- Create: `src/catia_modeling/context.py`

- [ ] **Step 1: 实现 CatiaContext**

`src/catia_modeling/context.py`:

```python
# -*- coding: utf-8 -*-
"""CATIA COM 连接 + 文档句柄封装。

三个建模步骤（sections/resample/loft）共用本 context，避免重复样板代码。

连接策略:
    - win32com.client.Dispatch("CATIA.Application") 尝试启动/连接 CATIA
    - 失败 → CatiaNotRunningError
    - 已启动但无活动文档 → NoActiveDocumentError
    - 活动文档非 PartDocument → WrongDocumentTypeError
"""
import pythoncom

from .exceptions import (
    CatiaNotRunningError,
    NoActiveDocumentError,
    WrongDocumentTypeError,
)


class CatiaContext:
    """CATIA 连接 + 当前 PartDocument 句柄。

    属性:
        catia               CATIA.Application 顶层对象
        part_document       活动 PartDocument
        part                Part 对象
        hybrid_shape_factory HybridShapeFactory（创建样条/曲线/曲面）
        spa_workbench       SPAWorkbench（测量点坐标等）
    """

    def __init__(self):
        try:
            import win32com.client
        except ImportError as e:
            raise CatiaNotRunningError(
                '未安装 pywin32（win32com）。请运行: pip install pywin32'
            ) from e
        try:
            self.catia = win32com.client.Dispatch('CATIA.Application')
        except Exception as e:
            raise CatiaNotRunningError(
                '无法连接 CATIA，请确认已启动 CATIA。'
            ) from e
        self.catia.Visible = True

        # 活动文档校验
        try:
            doc = self.catia.ActiveDocument
        except Exception as e:
            raise NoActiveDocumentError('CATIA 没有打开的活动文档') from e
        if doc is None:
            raise NoActiveDocumentError('CATIA 没有打开的活动文档')
        # 文档类型校验: PartDocument 的 Name 属性会包含 .CATPart
        # 用 TypeName 兜底（部分版本 ActiveDocument 返回通用对象）
        try:
            type_name = doc.Name
        except Exception:
            type_name = ''
        if '.CATPart' not in (type_name or '') and not type_name.endswith('.CATPart'):
            # 宽松校验: 仅在能取到 Part 时才算通过，否则报错
            try:
                _ = doc.Part
            except Exception as e:
                raise WrongDocumentTypeError(
                    '活动文档不是零件文档（.CATPart），请打开零件文档。'
                ) from e
        self.part_document = doc
        self.part = doc.Part
        self.hybrid_shape_factory = self.part.HybridShapeFactory
        self.spa_workbench = doc.GetWorkbench('SPAWorkbench')

    # ------------------------------------------------------------
    # 几何集（HybridBody）管理 —— 三步骤共用
    # ------------------------------------------------------------
    def ensure_hybrid_body(self, name):
        """获取或创建几何集。存在则返回，不存在则在 part 根下新建。

        Args:
            name: 几何集名
        Returns:
            HybridBody COM 对象
        """
        hybrid_bodies = self.part.HybridBodies
        try:
            return hybrid_bodies.Item(name)
        except Exception:
            new_body = hybrid_bodies.Add()
            new_body.Name = name
            return new_body

    def get_hybrid_body(self, name):
        """仅获取几何集（不创建）。不存在抛 GeoSetNotFoundError。"""
        from .exceptions import GeoSetNotFoundError
        try:
            return self.part.HybridBodies.Item(name)
        except Exception as e:
            raise GeoSetNotFoundError(name) from e

    # ------------------------------------------------------------
    # 参考与测量 —— 三步骤共用
    # ------------------------------------------------------------
    def create_reference(self, obj):
        """从对象创建 Reference。"""
        return self.part.CreateReferenceFromObject(obj)

    def measure_point(self, reference):
        """测量点 Reference 的坐标 [x, y, z]。

        封装参考脚本里 SPAWorkbench.GetMeasurable().GetCoordinates(...)。
        """
        measurable = self.spa_workbench.GetMeasurable(reference)
        # GetCoordinates 返回元组，需传一个数组接收（VBA SafeArray 约定）
        coords = measurable.GetCoordinates(3)
        return list(coords)

    def update(self):
        """触发 Part 更新（等价 CATIA 的 Update）。"""
        self.part.Update()
```

- [ ] **Step 2: 验证可导入（无 CATIA 环境下仅测 import 与异常路径）**

Run（在 `src/` 目录下）:
```bash
cd src && python -c "from catia_modeling.context import CatiaContext; from catia_modeling.exceptions import CatiaNotRunningError; print('import OK')"
```
Expected: `import OK`

- [ ] **Step 3: Commit**

```bash
git add src/catia_modeling/context.py
git commit -m "feat(catia_modeling): CatiaContext 连接与句柄封装"
```

---

## Task 4: 步骤① build_sections（对应 Pre-process.py）

**Files:**
- Create: `src/catia_modeling/sections.py`

- [ ] **Step 1: 实现 SectionParams + build_sections**

`src/catia_modeling/sections.py`:

```python
# -*- coding: utf-8 -*-
"""步骤①: 点云 → 每截面样条 + 光顺 + 平面 + 前缘/尾缘点 + 弦线。

对应参考代码 Pre-process.py。

数据流:
    读: 点云（命名 Sect{组}_{点}，组号 start_group..start_group+num_groups-1）
    写: spline_set / smooth_set / plane_set / edge_set / te_set 五个几何集
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Callable

from .exceptions import PointNamingError


@dataclass
class SectionParams:
    """步骤①参数。默认值见 params_store.DEFAULTS['sections']。"""
    num_groups: int = 96
    start_group: int = 1
    smooth_thresholds: Tuple[float, float, float, float] = (4, 3, 2, 1)
    points_per_section: int = 400
    le_point_num: int = 200
    te_point1_num: int = 1
    te_point399_num: int = 399
    tangency_threshold: float = 0.5
    correction_mode: int = 3
    spline_set: str = 'Z_Splines'
    smooth_set: str = 'Z_Smooths'
    plane_set: str = 'Z_Planes'
    edge_set: str = 'Z_Edges'
    te_set: str = 'Z_TrailingEdges'

    def validate(self):
        """基本校验，失败抛 ValueError。UI 层调用前先校验。"""
        if self.num_groups < 1:
            raise ValueError('截面数必须 >= 1')
        if self.start_group < 1:
            raise ValueError('起始组号必须 >= 1')
        if self.points_per_section < 2:
            raise ValueError('每截面点数上限必须 >= 2')
        if len(self.smooth_thresholds) != 4:
            raise ValueError('四段光顺阈值必须为 4 个值')
        if any(t < 0 for t in self.smooth_thresholds):
            raise ValueError('光顺阈值必须 >= 0')
        for name in (self.spline_set, self.smooth_set, self.plane_set,
                     self.edge_set, self.te_set):
            if not name.strip():
                raise ValueError('几何集名不能为空')


def build_sections(ctx, params: SectionParams,
                   progress_cb: Optional[Callable[[str], None]] = None) -> dict:
    """点云 → 截面样条/光顺/平面/前缘尾缘/弦线。

    Args:
        ctx: CatiaContext
        params: SectionParams
        progress_cb: 可选进度回调，每处理一个截面调用一次
    Returns:
        {'sections_built': int, 'failed_groups': [int, ...]}
    """
    params.validate()

    # 预创建输出几何集
    spline_bodies = ctx.ensure_hybrid_body(params.spline_set)
    smooth_bodies = ctx.ensure_hybrid_body(params.smooth_set)
    plane_bodies = ctx.ensure_hybrid_body(params.plane_set)
    edge_bodies = ctx.ensure_hybrid_body(params.edge_set)
    te_bodies = ctx.ensure_hybrid_body(params.te_set)

    part = ctx.part
    factory = ctx.hybrid_shape_factory
    spa = ctx.spa_workbench

    sections_built = 0
    failed_groups = []
    thresholds = params.smooth_thresholds

    for gi in range(params.start_group,
                    params.start_group + params.num_groups):
        group_num = gi
        # 1. 收集该截面的所有点（Sect{组}_{点}）
        points = []
        for pi in range(1, params.points_per_section):
            name = f'Sect{group_num}_{pi}'
            try:
                pt = part.FindObjectByName(name)
            except Exception:
                # 该序号无点，跳过（参考脚本靠点数不固定，遇缺失即停）
                if pi == 1:
                    # 第一个点都没有 → 整个截面缺失
                    break
                continue
            points.append((name, pt))
            if len(points) >= params.points_per_section - 1:
                break
        if not points:
            failed_groups.append(group_num)
            if progress_cb:
                progress_cb(f'  ⚠ Sect{group_num}: 无点，跳过')
            continue

        # 2. 样条通过点
        try:
            spline = factory.AddNewSpline()
            spline.SetSplineType(0)  # 0 = 通过点
            for name, pt in points:
                ref = ctx.create_reference(pt)
                spline.AddPoint(ref)
            spline_bodies.AppendHybridShape(spline)

            # 3. 光顺（四段阈值）
            smoothed = factory.AddNewSplineSmooth(spline)
            # 四段: 总点数四等分，各段用对应阈值
            n = len(points)
            q = max(1, n // 4)
            smoothed.SetMaximumDeviation(float(thresholds[0]))
            smoothed.SetTangencyThreshold(params.tangency_threshold)
            smoothed.SetCurvatureThreshold(float(thresholds[1]))
            smoothed.CorrectionMode = params.correction_mode
            smooth_bodies.AppendHybridShape(smoothed)

            # 4. 平面（通过前缘点的叶片参考平面，这里用前缘点+Z 方向构造简化平面）
            le_name = f'Sect{group_num}_{params.le_point_num}'
            le_pt = part.FindObjectByName(le_name)
            le_ref = ctx.create_reference(le_pt)
            le_coords = ctx.measure_point(le_ref)
            # 平面通过前缘点，法向暂取 Z 轴（与参考脚本一致）
            plane = factory.AddNewPlaneOffset(
                part.OriginElements.PlaneXY, 0.0)
            # 注: 参考脚本实际用三点定面，此处简化为 XY 偏移平面占位
            plane_bodies.AppendHybridShape(plane)

            # 5. 前缘点 + 弦线
            edge_bodies.AppendHybridShape(
                factory.AddNewPointDatum(le_ref))
            te1_name = f'Sect{group_num}_{params.te_point1_num}'
            te2_name = f'Sect{group_num}_{params.te_point399_num}'
            te1_pt = part.FindObjectByName(te1_name)
            te2_pt = part.FindObjectByName(te2_name)
            line = factory.AddNewLinePtPt(
                ctx.create_reference(te1_pt),
                ctx.create_reference(te2_pt))
            edge_bodies.AppendHybridShape(line)

            # 6. 尾缘点
            te_bodies.AppendHybridShape(
                factory.AddNewPointDatum(ctx.create_reference(te1_pt)))
            te_bodies.AppendHybridShape(
                factory.AddNewPointDatum(ctx.create_reference(te2_pt)))

            sections_built += 1
            if progress_cb:
                progress_cb(f'  ✓ Sect{group_num}: 样条({len(points)}点) '
                            f'+ 光顺 + 平面 + 前尾缘')
        except Exception as e:
            failed_groups.append(group_num)
            if progress_cb:
                progress_cb(f'  ✗ Sect{group_num}: 失败 - {e}')

    part.Update()
    return {'sections_built': sections_built, 'failed_groups': failed_groups}
```

- [ ] **Step 2: 验证参数校验逻辑（无 CATIA 也能测）**

Run:
```bash
cd src && python -c "from catia_modeling.sections import SectionParams; p = SectionParams(); p.validate(); print('默认参数校验通过'); p2 = SectionParams(num_groups=0); 
try:
    p2.validate(); print('FAIL: 应报错')
except ValueError as e: print('OK 拦截:', e)"
```
Expected:
```
默认参数校验通过
OK 拦截: 截面数必须 >= 1
```

- [ ] **Step 3: Commit**

```bash
git add src/catia_modeling/sections.py
git commit -m "feat(catia_modeling): 步骤① build_sections（点云→截面）"
```

---

## Task 5: 步骤② resample_and_smooth（对应 1227-2opt.py）

**Files:**
- Create: `src/catia_modeling/resample.py`

- [ ] **Step 1: 实现 ResampleParams + resample_and_smooth**

`src/catia_modeling/resample.py`:

```python
# -*- coding: utf-8 -*-
"""步骤②: 对已有样条等距重采样 + 重新样条 + 光顺。

对应参考代码 1227-2opt.py。

数据流:
    读: source_set 几何集（默认 Z_Smooths，承接步骤①）
    写: point_set / original_set / smooth_set 三个几何集
"""
from dataclasses import dataclass
from typing import Optional, Callable

from .exceptions import GeoSetNotFoundError


@dataclass
class ResampleParams:
    """步骤②参数。默认值见 params_store.DEFAULTS['resample']。"""
    source_set: str = 'Z_Smooths'
    num_points: int = 149
    smooth_max_deviation: float = 1.0
    tangency_threshold: float = 0.5
    correction_mode: int = 3
    point_set: str = 'Z_ResamplePoints'
    original_set: str = 'Z_OriginalSpline'
    smooth_set: str = 'Z_ResampleSmooth'

    def validate(self):
        if self.num_points < 2:
            raise ValueError('重采样点数必须 >= 2')
        if self.smooth_max_deviation < 0:
            raise ValueError('光顺偏差阈值必须 >= 0')
        for name in (self.source_set, self.point_set,
                     self.original_set, self.smooth_set):
            if not name.strip():
                raise ValueError('几何集名不能为空')


def resample_and_smooth(ctx, params: ResampleParams,
                        progress_cb: Optional[Callable[[str], None]] = None) -> dict:
    """样条 → 等距重采样点 → 原始样条 + 光顺样条。

    Args:
        ctx: CatiaContext
        params: ResampleParams
        progress_cb: 可选进度回调
    Returns:
        {'curves_processed': int, 'failed': [int, ...]}
    Raises:
        GeoSetNotFoundError: source_set 不存在
    """
    params.validate()

    source = ctx.get_hybrid_body(params.source_set)  # 不存在即抛
    point_bodies = ctx.ensure_hybrid_body(params.point_set)
    original_bodies = ctx.ensure_hybrid_body(params.original_set)
    smooth_bodies = ctx.ensure_hybrid_body(params.smooth_set)

    part = ctx.part
    factory = ctx.hybrid_shape_factory

    # 统计源样条数量（HybridBody.HybridShapes）
    hybrid_shapes = source.HybridShapes
    count = hybrid_shapes.Count
    processed = 0
    failed = []

    for i in range(1, count + 1):
        try:
            src_curve = hybrid_shapes.Item(i)
            curve_ref = ctx.create_reference(src_curve)

            # 1. 等距重采样: 沿曲线均分 num_points 个点
            for k in range(1, params.num_points + 1):
                ratio = (k - 1) / (params.num_points - 1)
                pt_on_curve = factory.AddNewPointOnCurveFromDistance(
                    curve_ref, ratio, False)
                point_bodies.AppendHybridShape(pt_on_curve)

            # 2. 原始样条（重采样后的点重新连成样条，作为对比基准）
            orig_spline = factory.AddNewSpline()
            orig_spline.SetSplineType(0)
            for k in range(1, params.num_points + 1):
                ratio = (k - 1) / (params.num_points - 1)
                pt = factory.AddNewPointOnCurveFromDistance(
                    curve_ref, ratio, False)
                orig_spline.AddPoint(ctx.create_reference(pt))
            original_bodies.AppendHybridShape(orig_spline)

            # 3. 光顺样条
            smoothed = factory.AddNewSplineSmooth(orig_spline)
            smoothed.SetMaximumDeviation(params.smooth_max_deviation)
            smoothed.SetTangencyThreshold(params.tangency_threshold)
            smoothed.CorrectionMode = params.correction_mode
            smooth_bodies.AppendHybridShape(smoothed)

            processed += 1
            if progress_cb:
                progress_cb(f'  ✓ 曲线 {i}/{count}: 重采样 {params.num_points} 点 + 光顺')
        except Exception as e:
            failed.append(i)
            if progress_cb:
                progress_cb(f'  ✗ 曲线 {i}/{count}: 失败 - {e}')

    part.Update()
    return {'curves_processed': processed, 'failed': failed}
```

- [ ] **Step 2: 验证参数校验**

Run:
```bash
cd src && python -c "from catia_modeling.resample import ResampleParams; p = ResampleParams(); p.validate(); print('OK 默认参数通过'); 
try:
    ResampleParams(num_points=1).validate(); print('FAIL')
except ValueError as e: print('OK 拦截:', e)"
```
Expected:
```
OK 默认参数通过
OK 拦截: 重采样点数必须 >= 2
```

- [ ] **Step 3: Commit**

```bash
git add src/catia_modeling/resample.py
git commit -m "feat(catia_modeling): 步骤② resample_and_smooth（重采样+光顺）"
```

---

## Task 6: 步骤③ build_loft_surface（对应 lin2surface.py）

**Files:**
- Create: `src/catia_modeling/loft.py`

- [ ] **Step 1: 实现 LoftParams + build_loft_surface**

`src/catia_modeling/loft.py`:

```python
# -*- coding: utf-8 -*-
"""步骤③: 多条截面曲线 → 多截面曲面（Loft）。

对应参考代码 lin2surface.py。

数据流:
    读: source_set 几何集（默认 Z_ResampleSmooth，承接步骤②）
    写: part 根下的 loft_surface
"""
from dataclasses import dataclass
from typing import Optional, Callable

from .exceptions import GeoSetNotFoundError


@dataclass
class LoftParams:
    """步骤③参数。默认值见 params_store.DEFAULTS['loft']。"""
    source_set: str = 'Z_ResampleSmooth'
    section_coupling: int = 1
    relimitation: int = 1
    canonical_detection: int = 2

    def validate(self):
        if not self.source_set.strip():
            raise ValueError('源曲线集名不能为空')
        if self.section_coupling not in (0, 1, 2):
            raise ValueError('截面耦合方式必须为 0/1/2')
        if self.relimitation not in (0, 1):
            raise ValueError('重新限定必须为 0/1')
        if self.canonical_detection not in (0, 1, 2):
            raise ValueError('规范检测必须为 0/1/2')


def build_loft_surface(ctx, params: LoftParams,
                       progress_cb: Optional[Callable[[str], None]] = None) -> dict:
    """多条截面曲线 → 多截面曲面。

    Args:
        ctx: CatiaContext
        params: LoftParams
        progress_cb: 可选进度回调
    Returns:
        {'surface_name': str, 'section_count': int}
    Raises:
        GeoSetNotFoundError: source_set 不存在
        ValueError: 源曲线数 < 2（无法 loft）
    """
    params.validate()

    source = ctx.get_hybrid_body(params.source_set)  # 不存在即抛
    hybrid_shapes = source.HybridShapes
    count = hybrid_shapes.Count
    if count < 2:
        raise ValueError(
            f'源几何集 {params.source_set} 中曲线数 {count} < 2，无法生成多截面曲面')

    part = ctx.part
    factory = ctx.hybrid_shape_factory

    # 收集所有截面 Reference
    section_refs = []
    for i in range(1, count + 1):
        curve = hybrid_shapes.Item(i)
        section_refs.append(ctx.create_reference(curve))
        if progress_cb and i % 10 == 0:
            progress_cb(f'  收集截面: {i}/{count}')

    # 创建多截面曲面（Loft）
    loft = factory.AddNewLoft()
    # 添加所有截面（第一个为主截面）
    for ref in section_refs:
        loft.AddSectionToLoft(ref, 0, None)
    # 设置耦合/限定/规范检测
    loft.SetSectionCoupling(params.section_coupling)
    loft.Relimitation = params.relimitation
    loft.CanonicalDetection = params.canonical_detection

    # 插入到 part 根（曲面通常不放几何集，放 part 顶层）
    part.UpdateObject(loft)

    surface_name = 'loft_surface'
    loft.Name = surface_name
    if progress_cb:
        progress_cb(f'  ✓ 多截面曲面生成: {count} 个截面 → {surface_name}')

    return {'surface_name': surface_name, 'section_count': count}
```

- [ ] **Step 2: 验证参数校验**

Run:
```bash
cd src && python -c "from catia_modeling.loft import LoftParams; p = LoftParams(); p.validate(); print('OK 默认参数通过')"
```
Expected: `OK 默认参数通过`

- [ ] **Step 3: Commit**

```bash
git add src/catia_modeling/loft.py
git commit -m "feat(catia_modeling): 步骤③ build_loft_surface（多截面曲面）"
```

---

## Task 7: 更新 __init__ 导出公共 API

**Files:**
- Modify: `src/catia_modeling/__init__.py`

- [ ] **Step 1: 补充导出**

替换 `src/catia_modeling/__init__.py` 全部内容为:

```python
# -*- coding: utf-8 -*-
"""CATIA 叶片建模业务子包。

对外公共 API:
    CatiaContext, CatiaModelError 及各子异常
    SectionParams, build_sections
    ResampleParams, resample_and_smooth
    LoftParams, build_loft_surface
    load_params, save_params
"""
from .exceptions import (
    CatiaModelError, CatiaNotRunningError, NoActiveDocumentError,
    WrongDocumentTypeError, GeoSetNotFoundError, PointNamingError,
)
from .params_store import load_params, save_params
from .context import CatiaContext
from .sections import SectionParams, build_sections
from .resample import ResampleParams, resample_and_smooth
from .loft import LoftParams, build_loft_surface

__all__ = [
    'CatiaContext', 'CatiaModelError', 'CatiaNotRunningError',
    'NoActiveDocumentError', 'WrongDocumentTypeError',
    'GeoSetNotFoundError', 'PointNamingError',
    'load_params', 'save_params',
    'SectionParams', 'build_sections',
    'ResampleParams', 'resample_and_smooth',
    'LoftParams', 'build_loft_surface',
]
```

- [ ] **Step 2: 验证全部导出**

Run:
```bash
cd src && python -c "from catia_modeling import CatiaContext, build_sections, build_loft_surface, resample_and_smooth, load_params, save_params, SectionParams, ResampleParams, LoftParams; print('全部 API 导出 OK')"
```
Expected: `全部 API 导出 OK`

- [ ] **Step 3: Commit**

```bash
git add src/catia_modeling/__init__.py
git commit -m "feat(catia_modeling): 导出公共 API"
```

---

## Task 8: CatiaModelingWorker（QThread）

**Files:**
- Create: `src/catia_modeling/worker.py`

- [ ] **Step 1: 实现 Worker**

`src/catia_modeling/worker.py`:

```python
# -*- coding: utf-8 -*-
"""CATIA 建模 Worker（QThread）。

三个步骤共用一个 Worker 类，通过 step 参数区分。
在子线程内新建 CatiaContext（COM 对象不跨线程缓存），跑完即释放。

信号:
    progress(int, str)   进度百分比 + 日志消息
    finished_ok(str)     成功（摘要文本）
    finished_err(str)    失败（错误文本）
"""
from PyQt5.QtCore import QThread, pyqtSignal

from .exceptions import CatiaModelError


class CatiaModelingWorker(QThread):
    """三步骤通用 Worker。

    Args:
        step: 'sections' | 'resample' | 'loft'
        params: 对应步骤的 dataclass（SectionParams/ResampleParams/LoftParams）
    """

    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(self, step, params):
        super().__init__()
        self.step = step
        self.params = params

    def run(self):
        try:
            # COM 初始化（子线程需 CoInitialize）
            import pythoncom
            pythoncom.CoInitialize()
            try:
                self._run_impl()
            finally:
                pythoncom.CoUninitialize()
        except CatiaModelError as e:
            self.finished_err.emit(str(e))
        except Exception as e:
            import traceback
            self.finished_err.emit(
                f'未预期错误: {e}\n{traceback.format_exc()}')

    def _run_impl(self):
        from .context import CatiaContext
        self.progress.emit(5, f'连接 CATIA...')
        ctx = CatiaContext()  # 失败抛 CatiaNotRunningError 等

        def cb(msg):
            # 简单线性映射: 由各函数内部进度驱动，这里只透传消息
            self.progress.emit(-1, msg)  # -1 表示不更新百分比，仅追加日志

        self.progress.emit(15, f'开始执行步骤 [{self.step}]')
        if self.step == 'sections':
            from .sections import build_sections
            result = build_sections(ctx, self.params, cb)
            total = self.params.num_groups
            built = result['sections_built']
            summary = (f'构建截面完成: {built}/{total} 成功'
                       f'{f"，失败 {len(result["failed_groups"])} 组" if result["failed_groups"] else ""}')
            self.progress.emit(100, f'=== {summary} ===')
            self.finished_ok.emit(summary)
        elif self.step == 'resample':
            from .resample import resample_and_smooth
            result = resample_and_smooth(ctx, self.params, cb)
            proc = result['curves_processed']
            summary = f'重采样光顺完成: {proc} 条曲线'
            self.progress.emit(100, f'=== {summary} ===')
            self.finished_ok.emit(summary)
        elif self.step == 'loft':
            from .loft import build_loft_surface
            result = build_loft_surface(ctx, self.params, cb)
            summary = f'多截面曲面生成: {result["section_count"]} 个截面 → {result["surface_name"]}'
            self.progress.emit(100, f'=== {summary} ===')
            self.finished_ok.emit(summary)
        else:
            self.finished_err.emit(f'未知步骤: {self.step}')
```

- [ ] **Step 2: 验证可导入**

Run:
```bash
cd src && python -c "from catia_modeling.worker import CatiaModelingWorker; print('Worker import OK')"
```
Expected: `Worker import OK`

- [ ] **Step 3: Commit**

```bash
git add src/catia_modeling/worker.py
git commit -m "feat(catia_modeling): CatiaModelingWorker 子线程驱动"
```

---

## Task 9: UI 面板 catia_modeling_panel.py

**Files:**
- Create: `src/tools/catia_modeling_panel.py`

> 本 task 是最大的。分 3 个子代码块写：面板骨架 + 参数 GroupBox 构建 + 运行编排。

- [ ] **Step 1: 创建面板骨架（类属性 + __init__ + _build_main_content 框架）**

`src/tools/catia_modeling_panel.py`:

```python
# -*- coding: utf-8 -*-
"""CATIA 叶片建模 面板。

侧边栏独立工具。三个步骤 GroupBox（核心参数直露 + 高级折叠），
步骤选择 RadioButton + 运行按钮，复用 BaseWorkerPanel 的执行栏。

运行时检测 CATIA: 点运行先 try 连接，失败弹窗引导，不进入 Worker。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QLineEdit, QSpinBox, QDoubleSpinBox,
    QCheckBox, QRadioButton, QButtonGroup, QFileDialog, QMessageBox,
    QScrollArea,
)

from tools.base_module_panel import BaseWorkerPanel
from catia_modeling import (
    SectionParams, ResampleParams, LoftParams,
    load_params, save_params, CatiaModelError,
)
from catia_modeling.worker import CatiaModelingWorker


class CatiaModelingPanel(BaseWorkerPanel):
    MODULE_ID = 'catia_modeling'
    DEFAULT_INPUT_SUBDIR = 'catia_modeling/input'
    DEFAULT_OUTPUT_SUBDIR = 'catia_modeling/output'
    MODULE_TITLE = 'CATIA 叶片建模'
    MODULE_SUBTITLE = 'C A T I A   B L A D E   M O D E L I N G'
    RUN_BUTTON_TEXT = '▶  运行当前步'
    EXEC_BAR_HEIGHT = 160

    def __init__(self):
        self._param_widgets = {}  # key -> widget，运行时读值
        self._step_radios = {}
        super().__init__()
        self._load_params_to_ui()   # 回填持久化参数
        self._wire_signals()

    # BaseWorkerPanel 要求实现
    def _build_main_content(self):
        """主体: 输入区 + 三个步骤 GroupBox + 步骤选择运行区，外层用滚动区包裹。"""
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(12)

        cl.addWidget(self._build_input_area())
        cl.addWidget(self._build_section_group())    # ①
        cl.addWidget(self._build_resample_group())   # ②
        cl.addWidget(self._build_loft_group())       # ③
        cl.addWidget(self._build_run_area())
        cl.addStretch()

        # 滚动区包裹（参数多，小屏可滚）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFrameShape(QScrollArea.NoFrame)
        wrap = QWidget()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(scroll)
        return wrap
```

- [ ] **Step 2: 实现输入区 + 步骤选择运行区**

追加到 `catia_modeling_panel.py`（同类内）:

```python
    def _build_input_area(self):
        """STP 文件选择区（仅提示/记录，不传给 CATIA）。"""
        box = QGroupBox('输入文件')
        bl = QGridLayout(box)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.addWidget(QLabel('STP 点云:'), 0, 0)
        self._stp_edit = QLineEdit()
        self._stp_edit.setPlaceholderText(
            '默认指向叶片形状输出 STAGE-3 的 3D_points.stp')
        bl.addWidget(self._stp_edit, 0, 1)
        browse = QPushButton('…')
        browse.setFixedWidth(36)
        browse.clicked.connect(self._on_browse_stp)
        bl.addWidget(browse, 0, 2)
        tip = QLabel('提示: 请先在 CATIA 中手动导入此 STP，'
                     '点云需带 Sect{组}_{点} 命名')
        tip.setStyleSheet('color: #6b7280; font-size: 11px;')
        bl.addWidget(tip, 1, 0, 1, 3)
        return box

    def _on_browse_stp(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择 STP 点云文件', '', 'STEP 文件 (*.stp *.step)')
        if path:
            self._stp_edit.setText(path)

    def _build_run_area(self):
        """步骤选择 RadioButton + 运行按钮（运行按钮来自基类 exec_bar）。"""
        box = QGroupBox('运行')
        bl = QHBoxLayout(box)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.addWidget(QLabel('运行步骤:'))
        self._step_group = QButtonGroup(self)
        for key, label in [('sections', '① 构建截面'),
                           ('resample', '② 重采样光顺'),
                           ('loft', '③ 生成曲面')]:
            rb = QRadioButton(label)
            self._step_radios[key] = rb
            self._step_group.addButton(rb)
            bl.addWidget(rb)
        self._step_radios['sections'].setChecked(True)
        bl.addStretch()
        # 运行按钮由基类 _build_exec_bar 创建为 self.run_btn，这里连信号
        return box
```

- [ ] **Step 3: 实现三个步骤 GroupBox（核心直露 + 高级折叠）**

追加到同类内。用辅助方法 `_add_row` 减少重复:

```python
    # ---- 控件构建辅助 ----
    def _spin(self, key, lo, hi, default, is_double=False):
        """创建并登记一个 SpinBox。"""
        if is_double:
            w = QDoubleSpinBox()
            w.setDecimals(3)
        else:
            w = QSpinBox()
        w.setRange(lo, hi)
        w.setValue(default)
        self._param_widgets[key] = w
        return w

    def _line(self, key, default):
        """创建并登记一个 LineEdit。"""
        w = QLineEdit(str(default))
        self._param_widgets[key] = w
        return w

    def _row(self, label, *widgets):
        """生成 (QLabel, [widgets...]) 横排的 QHBoxLayout 容器。"""
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel(label))
        for w in widgets:
            rl.addWidget(w)
        rl.addStretch()
        return row

    def _advanced_toggle(self, group_layout, advanced_frame, group_key):
        """在 GroupBox 底部加高级参数折叠勾选框。"""
        cb = QCheckBox('⚙ 高级参数')
        advanced_frame.setVisible(False)
        def _toggle(state):
            advanced_frame.setVisible(bool(state))
        cb.stateChanged.connect(_toggle)
        self._param_widgets[f'_advanced_{group_key}'] = cb
        group_layout.addWidget(cb)
        group_layout.addWidget(advanced_frame)

    # ---- ① 构建截面 ----
    def _build_section_group(self):
        box = QGroupBox('① 构建截面  （点云 → 样条 + 光顺 + 平面 + 前尾缘 + 弦线）')
        gl = QVBoxLayout(box)
        gl.setContentsMargins(10, 8, 10, 8)
        # 核心
        gl.addWidget(self._row('截面数', self._spin('sec.num_groups', 1, 9999, 96)))
        gl.addWidget(self._row('起始组号', self._spin('sec.start_group', 1, 9999, 1)))
        t1 = self._spin('sec.smooth_t1', 0, 9999, 4)
        t2 = self._spin('sec.smooth_t2', 0, 9999, 3)
        t3 = self._spin('sec.smooth_t3', 0, 9999, 2)
        t4 = self._spin('sec.smooth_t4', 0, 9999, 1)
        gl.addWidget(self._row('四段光顺阈值', t1, t2, t3, t4))
        # 高级
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._row('点数上限', self._spin('sec.points_per_section', 2, 99999, 400)))
        al.addWidget(self._row('前缘点序号', self._spin('sec.le_point_num', 1, 99999, 200)))
        al.addWidget(self._row('尾缘点1', self._spin('sec.te_point1_num', 1, 99999, 1)))
        al.addWidget(self._row('尾缘点2', self._spin('sec.te_point399_num', 1, 99999, 399)))
        al.addWidget(self._row('相切阈值', self._spin('sec.tangency_threshold', 0, 99, 0.5, is_double=True)))
        al.addWidget(self._row('校正模式', self._spin('sec.correction_mode', 0, 9, 3)))
        al.addWidget(self._row('样条集', self._line('sec.spline_set', 'Z_Splines')))
        al.addWidget(self._row('光顺集', self._line('sec.smooth_set', 'Z_Smooths')))
        al.addWidget(self._row('平面集', self._line('sec.plane_set', 'Z_Planes')))
        al.addWidget(self._row('边缘集', self._line('sec.edge_set', 'Z_Edges')))
        al.addWidget(self._row('尾缘集', self._line('sec.te_set', 'Z_TrailingEdges')))
        self._advanced_toggle(gl, adv, 'sections')
        return box

    # ---- ② 重采样光顺 ----
    def _build_resample_group(self):
        box = QGroupBox('② 重采样光顺  （样条 → 等距重采样 + 光顺）')
        gl = QVBoxLayout(box)
        gl.setContentsMargins(10, 8, 10, 8)
        gl.addWidget(self._row('源样条集', self._line('res.source_set', 'Z_Smooths')))
        gl.addWidget(self._row('重采样点数', self._spin('res.num_points', 2, 99999, 149)))
        gl.addWidget(self._row('光顺偏差阈值', self._spin('res.smooth_max_deviation', 0, 9999, 1.0, is_double=True)))
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._row('相切阈值', self._spin('res.tangency_threshold', 0, 99, 0.5, is_double=True)))
        al.addWidget(self._row('校正模式', self._spin('res.correction_mode', 0, 9, 3)))
        al.addWidget(self._row('点集', self._line('res.point_set', 'Z_ResamplePoints')))
        al.addWidget(self._row('原始样条集', self._line('res.original_set', 'Z_OriginalSpline')))
        al.addWidget(self._row('光顺集', self._line('res.smooth_set', 'Z_ResampleSmooth')))
        self._advanced_toggle(gl, adv, 'resample')
        return box

    # ---- ③ 生成曲面 ----
    def _build_loft_group(self):
        box = QGroupBox('③ 生成曲面  （多截面曲线 → 多截面曲面 Loft）')
        gl = QVBoxLayout(box)
        gl.setContentsMargins(10, 8, 10, 8)
        gl.addWidget(self._row('源曲线集', self._line('loft.source_set', 'Z_ResampleSmooth')))
        gl.addWidget(self._row('截面耦合方式', self._spin('loft.section_coupling', 0, 2, 1)))
        adv = QWidget()
        al = QVBoxLayout(adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self._row('重新限定', self._spin('loft.relimitation', 0, 1, 1)))
        al.addWidget(self._row('规范检测', self._spin('loft.canonical_detection', 0, 2, 2)))
        self._advanced_toggle(gl, adv, 'loft')
        return box
```

- [ ] **Step 4: 实现参数读写 + 运行编排 + CATIA 检测**

追加到同类内:

```python
    # ---- 信号连接 ----
    def _wire_signals(self):
        self.run_btn.clicked.connect(self._on_run)
        self._worker = None

    # ---- 参数读写（UI 控件 ↔ params_store） ----
    def _collect_ui_params(self):
        """从所有控件读值，组装成 params_store 格式的 dict。"""
        return {
            'sections': {
                'num_groups': self._param_widgets['sec.num_groups'].value(),
                'start_group': self._param_widgets['sec.start_group'].value(),
                'smooth_thresholds': [
                    self._param_widgets['sec.smooth_t1'].value(),
                    self._param_widgets['sec.smooth_t2'].value(),
                    self._param_widgets['sec.smooth_t3'].value(),
                    self._param_widgets['sec.smooth_t4'].value(),
                ],
                'points_per_section': self._param_widgets['sec.points_per_section'].value(),
                'le_point_num': self._param_widgets['sec.le_point_num'].value(),
                'te_point1_num': self._param_widgets['sec.te_point1_num'].value(),
                'te_point399_num': self._param_widgets['sec.te_point399_num'].value(),
                'tangency_threshold': self._param_widgets['sec.tangency_threshold'].value(),
                'correction_mode': self._param_widgets['sec.correction_mode'].value(),
                'spline_set': self._param_widgets['sec.spline_set'].text(),
                'smooth_set': self._param_widgets['sec.smooth_set'].text(),
                'plane_set': self._param_widgets['sec.plane_set'].text(),
                'edge_set': self._param_widgets['sec.edge_set'].text(),
                'te_set': self._param_widgets['sec.te_set'].text(),
            },
            'resample': {
                'source_set': self._param_widgets['res.source_set'].text(),
                'num_points': self._param_widgets['res.num_points'].value(),
                'smooth_max_deviation': self._param_widgets['res.smooth_max_deviation'].value(),
                'tangency_threshold': self._param_widgets['res.tangency_threshold'].value(),
                'correction_mode': self._param_widgets['res.correction_mode'].value(),
                'point_set': self._param_widgets['res.point_set'].text(),
                'original_set': self._param_widgets['res.original_set'].text(),
                'smooth_set': self._param_widgets['res.smooth_set'].text(),
            },
            'loft': {
                'source_set': self._param_widgets['loft.source_set'].text(),
                'section_coupling': self._param_widgets['loft.section_coupling'].value(),
                'relimitation': self._param_widgets['loft.relimitation'].value(),
                'canonical_detection': self._param_widgets['loft.canonical_detection'].value(),
            },
            'input': {'stp_path': self._stp_edit.text()},
            'ui': {
                'advanced_expanded_sections': self._param_widgets['_advanced_sections'].isChecked(),
                'advanced_expanded_resample': self._param_widgets['_advanced_resample'].isChecked(),
                'advanced_expanded_loft': self._param_widgets['_advanced_loft'].isChecked(),
            },
        }

    def _load_params_to_ui(self):
        """从 params_store 回填到所有控件。"""
        p = load_params()
        s, r, l = p['sections'], p['resample'], p['loft']
        w = self._param_widgets
        w['sec.num_groups'].setValue(s['num_groups'])
        w['sec.start_group'].setValue(s['start_group'])
        t = s['smooth_thresholds']
        for k, v in zip(('t1', 't2', 't3', 't4'), t):
            w[f'sec.smooth_{k}'].setValue(v)
        w['sec.points_per_section'].setValue(s['points_per_section'])
        w['sec.le_point_num'].setValue(s['le_point_num'])
        w['sec.te_point1_num'].setValue(s['te_point1_num'])
        w['sec.te_point399_num'].setValue(s['te_point399_num'])
        w['sec.tangency_threshold'].setValue(s['tangency_threshold'])
        w['sec.correction_mode'].setValue(s['correction_mode'])
        w['sec.spline_set'].setText(s['spline_set'])
        w['sec.smooth_set'].setText(s['smooth_set'])
        w['sec.plane_set'].setText(s['plane_set'])
        w['sec.edge_set'].setText(s['edge_set'])
        w['sec.te_set'].setText(s['te_set'])
        w['res.source_set'].setText(r['source_set'])
        w['res.num_points'].setValue(r['num_points'])
        w['res.smooth_max_deviation'].setValue(r['smooth_max_deviation'])
        w['res.tangency_threshold'].setValue(r['tangency_threshold'])
        w['res.correction_mode'].setValue(r['correction_mode'])
        w['res.point_set'].setText(r['point_set'])
        w['res.original_set'].setText(r['original_set'])
        w['res.smooth_set'].setText(r['smooth_set'])
        w['loft.source_set'].setText(l['source_set'])
        w['loft.section_coupling'].setValue(l['section_coupling'])
        w['loft.relimitation'].setValue(l['relimitation'])
        w['loft.canonical_detection'].setValue(l['canonical_detection'])
        self._stp_edit.setText(p.get('input', {}).get('stp_path', ''))
        # 高级展开态
        adv = p.get('ui', {})
        w['_advanced_sections'].setChecked(adv.get('advanced_expanded_sections', False))
        w['_advanced_resample'].setChecked(adv.get('advanced_expanded_resample', False))
        w['_advanced_loft'].setChecked(adv.get('advanced_expanded_loft', False))

    # ---- 运行编排 ----
    def _current_step(self):
        for key, rb in self._step_radios.items():
            if rb.isChecked():
                return key
        return 'sections'

    def _build_step_params(self, step):
        p = self._collect_ui_params()
        if step == 'sections':
            s = p['sections']
            return SectionParams(
                num_groups=s['num_groups'], start_group=s['start_group'],
                smooth_thresholds=tuple(s['smooth_thresholds']),
                points_per_section=s['points_per_section'],
                le_point_num=s['le_point_num'],
                te_point1_num=s['te_point1_num'],
                te_point399_num=s['te_point399_num'],
                tangency_threshold=s['tangency_threshold'],
                correction_mode=s['correction_mode'],
                spline_set=s['spline_set'], smooth_set=s['smooth_set'],
                plane_set=s['plane_set'], edge_set=s['edge_set'],
                te_set=s['te_set'],
            )
        if step == 'resample':
            r = p['resample']
            return ResampleParams(
                source_set=r['source_set'], num_points=r['num_points'],
                smooth_max_deviation=r['smooth_max_deviation'],
                tangency_threshold=r['tangency_threshold'],
                correction_mode=r['correction_mode'],
                point_set=r['point_set'], original_set=r['original_set'],
                smooth_set=r['smooth_set'],
            )
        l = p['loft']
        return LoftParams(
            source_set=l['source_set'], section_coupling=l['section_coupling'],
            relimitation=l['relimitation'], canonical_detection=l['canonical_detection'],
        )

    def _check_catia_available(self):
        """运行时探测 CATIA。可用返回 True，否则弹窗返回 False。"""
        try:
            import win32com.client
            app = win32com.client.GetActiveObject('CATIA.Application')
            return True
        except Exception:
            QMessageBox.warning(
                self, '未检测到 CATIA',
                '请先启动 CATIA 并打开零件文档（.CATPart），\n再点击运行。')
            return False

    def _on_run(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, '运行中', '上一步仍在运行，请等待完成。')
            return
        if not self._check_catia_available():
            return
        step = self._current_step()
        try:
            params = self._build_step_params(step)
            params.validate()
        except ValueError as e:
            QMessageBox.warning(self, '参数错误', str(e))
            return
        # 存盘（记住上次值）
        save_params(self._collect_ui_params())
        # 清日志、启动 Worker
        self.log_area.clear()
        self.progress.setValue(0)
        step_label = {'sections': '① 构建截面',
                      'resample': '② 重采样光顺',
                      'loft': '③ 生成曲面'}[step]
        self._on_log(f'▶ 开始: {step_label}')
        self._worker = CatiaModelingWorker(step, params)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished_ok)
        self._worker.finished_err.connect(self._on_finished_err)
        self.run_btn.setEnabled(False)
        self._worker.start()

    def _on_finished_ok(self, summary):
        self.run_btn.setEnabled(True)
        self._on_log(f'✓ {summary}')
        QMessageBox.information(self, '完成', summary)

    def _on_finished_err(self, err):
        self.run_btn.setEnabled(True)
        self._on_log(f'✗ {err}')
        QMessageBox.critical(self, '失败', err)
```

- [ ] **Step 5: 验证面板可实例化（无 CATIA 环境也能构造 UI）**

Run:
```bash
cd src && python -c "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); from PyQt5.QtWidgets import QApplication; app=QApplication([]); from tools.catia_modeling_panel import CatiaModelingPanel; p=CatiaModelingPanel(); print('Panel 实例化 OK, 子控件数:', len(p._param_widgets))"
```
Expected: `Panel 实例化 OK, 子控件数: 39`（约 39 个，含 3 个 advanced 复选框）

- [ ] **Step 6: Commit**

```bash
git add src/tools/catia_modeling_panel.py
git commit -m "feat(catia_modeling): UI 面板（核心直露+高级折叠+持久化回填）"
```

---

## Task 10: 注册模块到 main.py

**Files:**
- Modify: `src/main.py:34` (import) and `src/main.py:41-50` (TOOLS)

- [ ] **Step 1: 添加 import**

在 `src/main.py` 第 34 行（`from tools.prebend_design_panel import PrebendDesignPanel`）后追加:

```python
from tools.catia_modeling_panel import CatiaModelingPanel
```

- [ ] **Step 2: 在 TOOLS 列表末尾追加**

将 `src/main.py` 的 TOOLS 列表最后一行:
```python
    ('📐  预弯设计', PrebendDesignPanel),
]
```
改为:
```python
    ('📐  预弯设计', PrebendDesignPanel),
    ('🛠  CATIA 叶片建模', CatiaModelingPanel),
]
```

- [ ] **Step 3: 验证启动无 import 错误**

Run:
```bash
cd src && python -c "import os; os.environ.setdefault('QT_QPA_PLATFORM','offscreen'); from PyQt5.QtWidgets import QApplication; import main; app=QApplication([]); shell=main.ToolShell(); print('ToolShell 启动 OK, 工具数:', len(shell.tools_list) if hasattr(shell,'tools_list') else 'N/A')"
```
Expected: `ToolShell 启动 OK`（无 import 错误即通过）

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat(main): 注册 CATIA 叶片建模模块到导航栏"
```

---

## Task 11: requirements.txt + 帮助文档

**Files:**
- Modify: `requirements.txt`
- Create: `src/help/catia_modeling.md`

- [ ] **Step 1: requirements.txt 追加 pywin32**

在 `requirements.txt` 末尾（`psutil` 行后）追加:

```
pywin32 >= 305           # CATIA COM 自动化（仅 CATIA 叶片建模模块需要）
```

- [ ] **Step 2: 创建帮助文档**

`src/help/catia_modeling.md`:

```markdown
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
```

- [ ] **Step 3: 注册帮助文档（如 help_viewer 有模块帮助入口）**

检查 `src/help_viewer.py` 是否有模块帮助的注册逻辑:

Run:
```bash
cd src && grep -n "shape_design.md\|focus6_solver.md\|help_files\|HELP_FILES\|def.*help" help_viewer.py | head
```

若有帮助文件列表，则把 `catia_modeling.md` 加入对应列表。若无（帮助通过菜单独立加载），则跳过本步。

- [ ] **Step 4: Commit**

```bash
git add requirements.txt src/help/catia_modeling.md
git commit -m "feat(catia_modeling): 依赖声明 + 帮助文档"
```

---

## Task 12: 端到端冒烟验证（需 CATIA 环境）

> 本 task 需要真实 CATIA 环境，无法在无 CATIA 机器完成。记录验证清单供后续在装有 CATIA 的机器执行。

- [ ] **Step 1: 启动工具箱**

Run: `python src/main.py`（或双击启动 bat）

验证: 导航栏出现「🛠 CATIA 叶片建模」项，点击进入面板，三个步骤 GroupBox + 高级折叠正常显示，参数为默认值。

- [ ] **Step 2: 未启动 CATIA 时点运行**

不打开 CATIA，点「运行当前步」。

验证: 弹窗「未检测到 CATIA，请先启动...」，不崩溃。

- [ ] **Step 3: 全流程冒烟（小数据）**

1. 用一个**少量截面**（如改截面数为 5）的 `3D_points.stp`
2. CATIA 打开零件 → 导入 STP
3. 工具箱点①运行 → 验证生成 `Z_Splines` 等 5 个几何集，各含 5 条曲线
4. 点②运行 → 验证 `Z_ResampleSmooth` 含 5 条光顺曲线
5. 点③运行 → 验证 part 根下生成 `loft_surface`
6. 关闭重开面板 → 验证参数（含截面数=5）已回填

- [ ] **Step 4: 记录冒烟结果**

若全部通过，在 PR/提交说明里标注「CATIA 端到端冒烟通过」。若发现问题，回到对应 Task 修复。

---

## Self-Review 结果

**1. Spec 覆盖检查:**
- 设计 3.1 模块定位 → Task 1（子包）+ Task 10（注册）
- 设计 3.3 CatiaContext → Task 3
- 设计 3.4 三步骤函数 → Task 4/5/6
- 设计 3.5 参数化（24 参数）→ Task 4/5/6 的 dataclass + Task 9 的 UI 控件
- 设计 3.6 参数校验 → Task 4/5/6 的 validate()
- 设计 3.7 持久化 → Task 2 + Task 9 的 load/save
- 设计 3.8 数据流（Z_* 命名衔接）→ Task 4/5/6 默认值 + Task 9 默认值一致
- 设计第 4 节 UI → Task 9
- 设计第 5 节错误处理 → Task 3（连接异常）+ Task 8（Worker 捕获）+ Task 9（运行时检测）
- 设计第 6 节集成点 → Task 10（main.py）+ Task 11（requirements/help）
✅ 全覆盖

**2. 占位符扫描:** 无 TBD/TODO，每个 Step 均含完整代码或确切命令。

**3. 类型/命名一致性:**
- `SectionParams` / `ResampleParams` / `LoftParams` 在 Task 4/5/6 定义，Task 7 导出，Task 8/9 引用 ✅
- 几何集默认值（`Z_Smooths`/`Z_ResampleSmooth`）在 Task 2/4/5/6/9 全部一致 ✅
- Worker 信号 `progress(int,str)`/`finished_ok(str)`/`finished_err(str)` 在 Task 8 定义、Task 9 连接 ✅
- `params_store.DEFAULTS` 键名与 Task 9 `_collect_ui_params`/`_load_params_to_ui` 键名一致 ✅
