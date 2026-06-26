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
        """测量点 Reference 的坐标 [x, y, z]（毫米）。

        优先用 VBA 注入式（V5R21 已验证可靠），失败回退 GetMeasurable。
        """
        try:
            return self.measure_point_vba(reference)
        except Exception:
            # 回退：部分版本 VBA 注入受限，用官方 API
            measurable = self.spa_workbench.GetMeasurable(reference)
            coords = measurable.GetCoordinates(3)
            return list(coords)

    def measure_point_vba(self, reference):
        """VBA 注入式测点（毫米）—— 与参考脚本一致，V5R21 已验证。

        SystemService.Evaluate 注入一段 VBA Function，用 GetMeasurable.GetPoint
        取坐标。比 Python 直接调 GetCoordinates 在老版本更稳定。
        """
        code = '''Function MeasurePoint(Wb, Ref)
                 Dim mes, Coord(2)
                 Set mes = Wb.GetMeasurable(Ref)
                 mes.GetPoint Coord
                 MeasurePoint = Coord
                 End Function'''
        srv = self.catia.SystemService
        coord = srv.Evaluate(code, 0, 'MeasurePoint',
                             (self.spa_workbench, reference))
        return [coord[i] for i in range(3)] if coord else [0.0, 0.0, 0.0]

    def measure_length(self, reference):
        """测量曲线/边 Reference 的长度。"""
        measurable = self.spa_workbench.GetMeasurable(reference)
        return float(measurable.Length)

    # ------------------------------------------------------------
    # 参数缓存 —— sections 步骤用，避免逐点 COM 线性扫描
    # ------------------------------------------------------------
    def build_param_cache(self, prefix='Sect'):
        """一次性遍历 Parameters 集合，构建 name→param 缓存。

        v0.2 改进：原脚本靠 FindObjectByName 逐点查（O(n²)），这里一次性
        遍历所有参数（带 .Name 路径前缀处理），主循环 O(1) 查找，大幅加速。
        Returns:
            dict: {短名(如 Sect1_200): param 对象}
        """
        params = self.part.Parameters
        cache = {}
        n = params.Count
        for i in range(1, n + 1):
            try:
                p = params.Item(i)
                # V5R21 的 .Name 可能带路径前缀（如 Part1\\...），取最后一段
                short = p.Name.rsplit('\\', 1)[-1]
                if short.startswith(prefix):
                    cache[short] = p
            except Exception:
                continue
        return cache

    def update(self):
        """触发 Part 更新（等价 CATIA 的 Update）。"""
        self.part.Update()
