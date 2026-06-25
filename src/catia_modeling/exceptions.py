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
