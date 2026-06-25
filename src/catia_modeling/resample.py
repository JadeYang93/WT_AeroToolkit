# -*- coding: utf-8 -*-
"""步骤②: 对已有样条等距重采样 + 重新样条 + 光顺。

对应参考代码 1227-2opt.py。

数据流:
    读: source_set 几何集（默认 Z_Smooths，承接步骤①）
    写: point_set / original_set / smooth_set 三个几何集
"""
from dataclasses import dataclass
from typing import Optional, Callable


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
