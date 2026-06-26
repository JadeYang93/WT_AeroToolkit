# -*- coding: utf-8 -*-
"""CATIA COM 连接 + 文档句柄封装。

三个建模步骤（sections/resample/loft）共用本 context，避免重复样板代码。

连接策略:
    - win32com.client.Dispatch("CATIA.Application") 尝试启动/连接 CATIA
    - 失败 → CatiaNotRunningError
    - 已启动但无活动文档 → NoActiveDocumentError
    - 活动文档非 PartDocument → WrongDocumentTypeError
"""

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
