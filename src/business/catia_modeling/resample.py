# -*- coding: utf-8 -*-
"""步骤②: 对已有样条等距重采样 + 重新样条 + 光顺。

完整复刻参考代码 v0.2 1227-2opt.py，修复初版 bug：
1. 初版 bug：AddNewPointOnCurveFromDistance 第二参数应是「距离(mm)」，
   初版错传 ratio(0~1 比例)，导致点全挤在曲线起点。
   本版先测曲线长度 curve_length，再用 dist = i/num * curve_length 算真实距离。
2. 测点坐标并命名：每个采样点按 v0.2 规则命名 {z_mm/1000}_{序号}，
   便于后续步骤按 Z 排序。
3. 复用已生成点重建样条（v0.2 的 create_spline_from_points），不重复生成。

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
    num_points: int = 149              # 每条曲线等距采样点数
    smooth_max_deviation: float = 1.0  # 光顺阈值
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


def _create_spline_from_points(factory, points):
    """通过给定点列表创建样条（v0.2 同名函数）。"""
    if len(points) < 2:
        raise ValueError('点的数量不足，无法生成样条')
    spline = factory.AddNewSpline()
    spline.SetSplineType(0)   # 0 = 通过点
    spline.SetClosing(0)      # 不闭合
    for pt in points:
        # AddPointWithConstraintExplicit: (ref, dir, -1, 1, None, 0.0)
        spline.AddPointWithConstraintExplicit(pt, None, -1.0, 1, None, 0.0)
    return spline


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

    hybrid_shapes = source.HybridShapes
    count = hybrid_shapes.Count
    processed = 0
    failed = []

    if progress_cb:
        progress_cb(f'源几何集 {params.source_set} 含 {count} 条曲线，开始重采样...')

    for i in range(1, count + 1):
        try:
            src_curve = hybrid_shapes.Item(i)
            curve_ref = ctx.create_reference(src_curve)

            # ----- 1. 测曲线长度（修复初版 bug 的关键）-----
            curve_length = ctx.measure_length(curve_ref)
            if progress_cb:
                progress_cb(f'  曲线 {i}/{count}: {src_curve.Name}, '
                            f'长度 {curve_length:.3f}mm')

            # 当前曲线的点子集（每条曲线一个子几何集）
            curve_point_set = point_bodies.HybridBodies.Add()
            curve_point_set.Name = f'Curve_{i}_Points'

            # ----- 2. 等距重采样：dist = k/num * length（真实距离，非比例）-----
            points = []
            for k in range(params.num_points + 1):
                dist = k / params.num_points * curve_length
                pt = factory.AddNewPointOnCurveFromDistance(
                    curve_ref, dist, False)
                curve_point_set.AppendHybridShape(pt)
                points.append(pt)

            part.InWorkObject = curve_point_set
            part.Update()

            # ----- 3. 测点坐标并命名（{z_mm/1000}_{序号}）-----
            for idx, pt in enumerate(points):
                try:
                    coord = ctx.measure_point(ctx.create_reference(pt))
                    if coord == [0.0, 0.0, 0.0]:
                        continue  # 零坐标点跳过命名
                    z_mm = round(coord[2], 3)
                    pt.Name = f'{z_mm / 1000.0}_{idx + 1}'
                except Exception:
                    continue

            # ----- 4. 用采样点生成原始样条（复用 points，不重复生成）-----
            # 需要把点对象转成 reference 喂给样条
            pt_refs = [ctx.create_reference(pt) for pt in points]
            orig_spline = factory.AddNewSpline()
            orig_spline.SetSplineType(0)
            orig_spline.SetClosing(0)
            for r in pt_refs:
                orig_spline.AddPointWithConstraintExplicit(
                    r, None, -1.0, 1, None, 0.0)
            original_bodies.AppendHybridShape(orig_spline)
            part.InWorkObject = original_bodies
            part.Update()

            # ----- 5. 光顺样条 -----
            spline_ref = ctx.create_reference(orig_spline)
            curve_smooth = factory.AddNewCurveSmooth(spline_ref)
            curve_smooth.SetTangencyThreshold(params.tangency_threshold)
            curve_smooth.CurvatureThresholdActivity = False
            curve_smooth.MaximumDeviationActivity = True
            curve_smooth.SetMaximumDeviation(params.smooth_max_deviation)
            curve_smooth.TopologySimplificationActivity = False
            curve_smooth.CorrectionMode = params.correction_mode
            smooth_bodies.AppendHybridShape(curve_smooth)
            part.InWorkObject = smooth_bodies
            part.Update()

            processed += 1
            if progress_cb:
                progress_cb(f'  ✓ 曲线 {i}/{count}: 重采样 '
                            f'{params.num_points} 点 + 光顺')
        except Exception as e:
            failed.append(i)
            if progress_cb:
                progress_cb(f'  ✗ 曲线 {i}/{count}: 失败 - {e}')

    part.Update()
    return {'curves_processed': processed, 'failed': failed}
