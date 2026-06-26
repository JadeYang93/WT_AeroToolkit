# -*- coding: utf-8 -*-
"""步骤①: 点云 → 每截面样条 + 光顺 + 平面 + 前缘/尾缘点 + 弦线。

完整复刻参考代码 v0.2 Pre-process.py，主要改进（相对初版占位实现）：
1. 参数缓存：一次性遍历 Parameters 构建 name→param 缓存，主循环 O(1) 查找
2. 四段光顺：光顺阈值按组号四等分自动分配（前1/4用4、2/4用3...），自动处理余数
3. Z 坐标命名：读前缘点(200号)Z 坐标，样条/光顺/平面/前后缘点都带 Z 命名
4. 尾缘点：取 1号与399号点中点（而非直接用端点）
5. 弦线：前缘点 ↔ 尾缘中点（正确弦线，初版错用尾1↔尾399）
6. 平面：AddNewPlane1Curve（过样条的真实平面，初版用 XY 偏移占位）
7. 回滚：每组失败时删除已生成几何，避免半成品残留
8. 组号自动识别：从缓存键正则提取实际组号，不依赖连续 range

数据流:
    读: 点云（命名 Sect{组}_{点}，组号自动识别，点号 1~399，200号=前缘）
    写: spline_set / smooth_set / plane_set / edge_set / te_set 五个几何集
"""
import re
from dataclasses import dataclass, field
from typing import Tuple, Optional, Callable, Dict, List

from .exceptions import PointNamingError


@dataclass
class SectionParams:
    """步骤①参数。默认值见 params_store.DEFAULTS['sections']。"""
    start_group: int = 1                 # 只处理 >= 该组号的截面
    smooth_thresholds: Tuple[float, float, float, float] = (4, 3, 2, 1)
    le_point_num: int = 200              # 前缘点号（同时读 Z 坐标）
    te_point1_num: int = 1               # 尾缘点 1
    te_point2_num: int = 399             # 尾缘点 2
    max_point_num: int = 399             # 点号上限（与原 range(1,400) 一致）
    tangency_threshold: float = 0.5
    correction_mode: int = 3
    spline_set: str = 'Z_Splines'
    smooth_set: str = 'Z_Smooths'
    plane_set: str = 'Z_Planes'
    edge_set: str = 'Z_Edges'            # 前缘点 + 弦线
    te_set: str = 'Z_TrailingEdges'      # 尾缘点单独存放

    def validate(self):
        """基本校验，失败抛 ValueError。"""
        if self.start_group < 1:
            raise ValueError('起始组号必须 >= 1')
        if len(self.smooth_thresholds) != 4:
            raise ValueError('四段光顺阈值必须为 4 个值')
        if any(t < 0 for t in self.smooth_thresholds):
            raise ValueError('光顺阈值必须 >= 0')
        for name in (self.spline_set, self.smooth_set, self.plane_set,
                     self.edge_set, self.te_set):
            if not name.strip():
                raise ValueError('几何集名不能为空')


# 前缘点命名正则：Sect{组}_200
_LE_RE = re.compile(r'Sect(\d+)_200$')
# 组内点命名正则：Sect{组}_{点号}
_GROUP_PT_RE_TEMPLATE = r'Sect{group}_(\d+)$'


def _format_z_name(z: float) -> str:
    """Z 坐标标准化命名：30.0 → '30_0'（避免小数点在 CATIA 名里）。"""
    return f'{z:.1f}'.replace('.', '_')


def _detect_group_numbers(cache: Dict[str, object]) -> List[int]:
    """从参数缓存键提取所有 Sect{n}_200 组号（升序）。"""
    return sorted({int(m.group(1)) for k in cache
                   if (m := _LE_RE.fullmatch(k))})


def _compute_boundaries(num_groups: int) -> List[int]:
    """四等分边界（自动处理余数）。返回 [b1, b2, b3, b4] 累积边界。"""
    part_size = num_groups // 4
    remainder = num_groups % 4
    boundaries, acc = [], 0
    for i in range(4):
        acc += part_size + (1 if i < remainder else 0)
        boundaries.append(acc)
    return boundaries


def _smooth_threshold_for(group_num: int, thresholds, boundaries) -> float:
    """根据组号返回对应段的光顺阈值。"""
    for i, bound in enumerate(boundaries):
        if group_num <= bound:
            return thresholds[i]
    return thresholds[-1]


def build_sections(ctx, params: SectionParams,
                   progress_cb: Optional[Callable[[str], None]] = None) -> dict:
    """点云 → 截面样条/光顺/平面/前缘尾缘/弦线。

    Args:
        ctx: CatiaContext
        params: SectionParams
        progress_cb: 可选进度回调，每处理一个截面调用一次
    Returns:
        {'sections_built': int, 'failed_groups': [int, ...], 'groups': [int,...]}
    """
    params.validate()

    part = ctx.part
    factory = ctx.hybrid_shape_factory

    # 预创建输出几何集
    geo_splines = ctx.ensure_hybrid_body(params.spline_set)
    geo_smooths = ctx.ensure_hybrid_body(params.smooth_set)
    geo_planes = ctx.ensure_hybrid_body(params.plane_set)
    geo_edges = ctx.ensure_hybrid_body(params.edge_set)
    geo_te = ctx.ensure_hybrid_body(params.te_set)

    # ===== 参数缓存（一次性遍历，避免逐点 COM 查找）=====
    if progress_cb:
        progress_cb('正在构建参数缓存（遍历 Parameters，可能耗时数十秒）...')
    cache = ctx.build_param_cache(prefix='Sect')
    if not cache:
        raise PointNamingError(
            '未缓存到任何 Sect 点。请确认点云命名规则为 Sect{组}_{点}。')

    detected = _detect_group_numbers(cache)
    if not detected:
        raise PointNamingError('未检测到任何 Sect{n}_200 前缘点。')
    target_groups = [g for g in detected if g >= params.start_group]
    if progress_cb:
        progress_cb(f'识别到 {len(detected)} 个截面组，'
                    f'处理 {len(target_groups)} 个（>= 组 {params.start_group}）。')

    # 四段光顺阈值边界
    boundaries = _compute_boundaries(detected[-1])

    sections_built = 0
    failed_groups = []

    for group_num in target_groups:
        # ----- 1. 读 Z 坐标（前缘点 200 号）-----
        le_key = f'Sect{group_num}_{params.le_point_num}'
        le_param = cache.get(le_key)
        if le_param is None:
            failed_groups.append(group_num)
            if progress_cb:
                progress_cb(f'  ⚠ Sect{group_num}: 缺前缘点 {le_key}，跳过')
            continue
        try:
            le_ref = ctx.create_reference(le_param)
            le_coord = ctx.measure_point(le_ref)  # 毫米
        except Exception as e:
            failed_groups.append(group_num)
            if progress_cb:
                progress_cb(f'  ⚠ Sect{group_num}: 测前缘点失败 {e}，跳过')
            continue
        z_value = round(le_coord[2] / 1000.0, 3)  # 毫米→米
        z_str = _format_z_name(z_value)

        # 该组实际点号范围（从缓存键提取，上限锁定 max_point_num）
        pt_re = re.compile(_GROUP_PT_RE_TEMPLATE.format(group=group_num))
        group_pt_nums = sorted(int(m.group(1)) for k in cache
                               if (m := pt_re.fullmatch(k)))
        max_pt = min(group_pt_nums[-1] if group_pt_nums else 0,
                     params.max_point_num)

        created = []  # 本组已创建几何，失败时回滚用
        try:
            # ----- 2. 样条（通过点）-----
            spline = factory.AddNewSpline()
            spline.SetSplineType(0)
            spline.SetClosing(0)
            spline.Name = f'Spline_Z{z_str}_G{group_num}'
            for pn in range(1, max_pt + 1):
                pt = cache.get(f'Sect{group_num}_{pn}')
                if pt is None:
                    continue
                ref = ctx.create_reference(pt)
                spline.AddPointWithConstraintExplicit(ref, None, -1, 1, None, 0.0)
            geo_splines.AppendHybridShape(spline)
            created.append(spline)

            # ----- 3. 光顺（四段阈值）-----
            spline_ref = ctx.create_reference(spline)
            curve_smooth = factory.AddNewCurveSmooth(spline_ref)
            curve_smooth.Name = f'Smooth_Z{z_str}_G{group_num}'
            curve_smooth.SetTangencyThreshold(params.tangency_threshold)
            curve_smooth.CurvatureThresholdActivity = False
            curve_smooth.MaximumDeviationActivity = True
            threshold = _smooth_threshold_for(group_num, params.smooth_thresholds,
                                              boundaries)
            curve_smooth.SetMaximumDeviation(threshold)
            curve_smooth.TopologySimplificationActivity = False
            curve_smooth.CorrectionMode = params.correction_mode
            geo_smooths.AppendHybridShape(curve_smooth)
            created.append(curve_smooth)

            # ----- 4. 平面（过样条的真实平面）-----
            plane = factory.AddNewPlane1Curve(spline_ref)
            plane.Name = f'Plane_Z{z_str}_G{group_num}'
            geo_planes.AppendHybridShape(plane)
            created.append(plane)

            # 样条→光顺→平面 一次性全量更新（光顺不是 plane 下游，需全量刷新）
            part.Update()

            # ----- 5. 前缘点 + 尾缘点 + 弦线 -----
            te1 = cache.get(f'Sect{group_num}_{params.te_point1_num}')
            te2 = cache.get(f'Sect{group_num}_{params.te_point2_num}')
            if te1 is None or te2 is None:
                raise PointNamingError(
                    f'Sect{group_num} 缺尾缘点 '
                    f'({params.te_point1_num}号 或 {params.te_point2_num}号)')

            te_coord1 = ctx.measure_point(ctx.create_reference(te1))
            te_coord2 = ctx.measure_point(ctx.create_reference(te2))

            # 前缘点（Z_Edges）
            le_point = factory.AddNewPointCoord(*le_coord)
            le_point.Name = f'LE_Z{z_str}_G{group_num}'
            geo_edges.AppendHybridShape(le_point)
            created.append(le_point)

            # 尾缘点（1号与2号中点，放 Z_TrailingEdges）
            mid = [(c1 + c2) / 2 for c1, c2 in zip(te_coord1, te_coord2)]
            te_point = factory.AddNewPointCoord(*mid)
            te_point.Name = f'TE_Z{z_str}_G{group_num}'
            geo_te.AppendHybridShape(te_point)
            created.append(te_point)

            # 弦线（前缘点 ↔ 尾缘中点）
            chord = factory.AddNewLinePtPt(
                ctx.create_reference(le_point), ctx.create_reference(te_point))
            chord.Name = f'Chord_Z{z_str}_G{group_num}'
            geo_edges.AppendHybridShape(chord)
            created.append(chord)

            part.Update()
            sections_built += 1
            if progress_cb:
                progress_cb(f'  ✓ Sect{group_num} (Z={z_value}m, '
                            f'阈值={threshold}, 点数={max_pt})')

        except Exception as e:
            failed_groups.append(group_num)
            if progress_cb:
                progress_cb(f'  ✗ Sect{group_num}: 失败 - {e}，回滚本组几何')
            # 回滚：删掉本组已创建的几何，避免半成品残留
            for obj in reversed(created):
                try:
                    factory.DeleteHybridShape(ctx.create_reference(obj))
                except Exception:
                    pass

    return {
        'sections_built': sections_built,
        'failed_groups': failed_groups,
        'groups': target_groups,
    }
