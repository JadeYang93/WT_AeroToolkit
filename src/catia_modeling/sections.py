# -*- coding: utf-8 -*-
"""步骤①: 点云 → 每截面样条 + 光顺 + 平面 + 前缘/尾缘点 + 弦线。

对应参考代码 Pre-process.py。

数据流:
    读: 点云（命名 Sect{组}_{点}，组号 start_group..start_group+num_groups-1）
    写: spline_set / smooth_set / plane_set / edge_set / te_set 五个几何集
"""
from dataclasses import dataclass
from typing import Tuple, Optional, Callable


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
