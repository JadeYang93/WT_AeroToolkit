# -*- coding: utf-8 -*-
"""步骤③: 多条截面曲线 → 多截面曲面（Loft）。

完整复刻参考代码 v0.2 lin2surface.py，相对初版改进：
1. 曲线筛选：只取 Spline/Line 类型或 Smooth_/Spline/Line 命名的曲线，
   跳过点/平面等无关元素（初版取集合里所有元素，会误纳入点导致 loft 失败）。
2. 按 Z 坐标排序：放样前按曲线 Z 排序，避免顺序错乱导致曲面扭曲。
   优先从曲线名解析 Z（命名格式 Smooth_Z{z}_G{n}，零 COM 调用），
   名称无规律时回退到测量（沿曲线中点建临时点测 Z，测完删除）。
3. 正确的 loft 参数：AddSectionToLoft(ref, 1, None)（初版第二参数用 0），
   SectionCoupling/Relimitation/CanonicalDetection 直接属性赋值（v0.2 同款）。

数据流:
    读: source_set 几何集（默认 Z_ResampleSmooth，承接步骤②）
    写: source_set 内新增 loft_surface
"""
import re
from dataclasses import dataclass
from typing import Optional, Callable, List

from .exceptions import GeoSetNotFoundError


@dataclass
class LoftParams:
    """步骤③参数。默认值见 params_store.DEFAULTS['loft']。"""
    source_set: str = 'Z_ResampleSmooth'
    section_coupling: int = 1     # 1 = 顶点耦合
    relimitation: int = 1         # 1 = 用截面重新限定曲面
    canonical_detection: int = 2  # 2 = 不检测规范元素

    def validate(self):
        if not self.source_set.strip():
            raise ValueError('源曲线集名不能为空')
        if self.section_coupling not in (0, 1, 2):
            raise ValueError('截面耦合方式必须为 0/1/2')
        if self.relimitation not in (0, 1):
            raise ValueError('重新限定必须为 0/1')
        if self.canonical_detection not in (0, 1, 2):
            raise ValueError('规范检测必须为 0/1/2')


# 曲线名 Z 坐标解析：Smooth_Z30_0_G5 → 30.0（米）
_NAME_Z_RE = re.compile(r'_Z(\d+)_(\d+)_G\d+')


def _curve_z_from_name(curve) -> Optional[float]:
    """从曲线名解析 Z 坐标（米）。命名格式 *_Z{整数}_{小数}_G{n}。
    命名规律明确时首选此法：零 COM 调用、零临时几何。"""
    try:
        name = curve.Name
    except Exception:
        return None
    m = _NAME_Z_RE.search(name)
    if m:
        return float(f'{m.group(1)}.{m.group(2)}')
    return None


def _is_section_curve(shape) -> bool:
    """判断几何集元素是否为截面曲线（样条/线）。筛掉点、平面等。"""
    try:
        shape_type = shape.GetType()
    except Exception:
        shape_type = ''
    try:
        name = shape.Name
    except Exception:
        name = ''
    return ('Spline' in shape_type or 'Line' in shape_type
            or 'Spline' in name or 'Line' in name
            or '样条线' in name or name.startswith('Smooth_'))


def _measure_curve_z(ctx, curve, fallback_set) -> float:
    """获取曲线 Z 坐标（米）。优先名称解析；无规律时建临时点测量后删除。"""
    z = _curve_z_from_name(curve)
    if z is not None:
        return z
    # 回退：沿曲线中点建临时点测 Z，测完删除（结构树无痕）
    part = ctx.part
    factory = ctx.hybrid_shape_factory
    curve_ref = ctx.create_reference(curve)
    length = ctx.measure_length(curve_ref)
    tmp_pt = factory.AddNewPointOnCurveFromDistance(curve_ref, length / 2.0, False)
    fallback_set.AppendHybridShape(tmp_pt)
    part.InWorkObject = fallback_set
    part.UpdateObject(tmp_pt)
    try:
        coord = ctx.measure_point(ctx.create_reference(tmp_pt))
        return coord[2] / 1000.0  # 毫米→米
    finally:
        try:
            factory.DeleteHybridShape(ctx.create_reference(tmp_pt))
            part.UpdateObject(fallback_set)
        except Exception:
            pass


def build_loft_surface(ctx, params: LoftParams,
                       progress_cb: Optional[Callable[[str], None]] = None) -> dict:
    """多条截面曲线 → 多截面曲面。

    Args:
        ctx: CatiaContext
        params: LoftParams
        progress_cb: 可选进度回调
    Returns:
        {'surface_name': str, 'section_count': int, 'z_sorted': bool}
    Raises:
        GeoSetNotFoundError: source_set 不存在
        ValueError: 筛选后曲线数 < 2
    """
    params.validate()

    source = ctx.get_hybrid_body(params.source_set)  # 不存在即抛
    part = ctx.part
    factory = ctx.hybrid_shape_factory

    hybrid_shapes = source.HybridShapes
    count = hybrid_shapes.Count

    # ----- 1. 筛选截面曲线（只取 Spline/Line）-----
    curves: List = []
    for i in range(1, count + 1):
        shape = hybrid_shapes.Item(i)
        if _is_section_curve(shape):
            curves.append(shape)
            if progress_cb:
                progress_cb(f'  ✔ 选中: {shape.Name}')
        else:
            if progress_cb:
                progress_cb(f'  ✘ 跳过: {getattr(shape, "Name", "?")}')

    if len(curves) < 2:
        raise ValueError(
            f'筛选后截面曲线数 {len(curves)} < 2，无法生成多截面曲面。'
            f'（集合 {params.source_set} 共 {count} 个元素）')

    if progress_cb:
        progress_cb(f'筛到 {len(curves)} 条曲线，按 Z 坐标排序...')

    # ----- 2. 按 Z 坐标排序（避免放样顺序错乱致曲面扭曲）-----
    curve_z = {}
    for c in curves:
        try:
            curve_z[id(c)] = _measure_curve_z(ctx, c, source)
        except Exception as e:
            if progress_cb:
                progress_cb(f'  ⚠ 测 {c.Name} Z 失败 {e}，按 0 处理')
            curve_z[id(c)] = 0.0
    curves.sort(key=lambda c: curve_z[id(c)])
    for idx, c in enumerate(curves):
        if progress_cb:
            progress_cb(f'  排序[{idx + 1}] {c.Name} '
                        f'Z={curve_z[id(c)]:.4f}')

    # ----- 3. 创建多截面曲面（Loft）-----
    loft = factory.AddNewLoft()
    loft.SectionCoupling = params.section_coupling
    loft.Relimitation = params.relimitation
    loft.CanonicalDetection = params.canonical_detection

    for spline in curves:
        try:
            ref = ctx.create_reference(spline)
            loft.AddSectionToLoft(ref, 1, None)
        except Exception as e:
            if progress_cb:
                progress_cb(f'  ⚠ 添加截面 {spline.Name} 失败: {e}')

    source.AppendHybridShape(loft)
    part.InWorkObject = loft
    part.Update()

    surface_name = 'loft_surface'
    loft.Name = surface_name
    if progress_cb:
        progress_cb(f'  ✓ 多截面曲面生成: {len(curves)} 个截面 → {surface_name}')

    return {
        'surface_name': surface_name,
        'section_count': len(curves),
        'z_sorted': True,
    }
