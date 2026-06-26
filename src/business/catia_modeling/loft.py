# -*- coding: utf-8 -*-
"""步骤③: 多条截面曲线 → 多截面曲面（Loft）。

对应参考代码 lin2surface.py。

数据流:
    读: source_set 几何集（默认 Z_ResampleSmooth，承接步骤②）
    写: part 根下的 loft_surface
"""
from dataclasses import dataclass
from typing import Optional, Callable


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
