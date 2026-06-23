#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
定宽字段格式化工具

Focus6 MAC 文件中数值字段的宽度是硬上限。当原始值的字符数超过限定宽度时，
按"逐位减小数点精度 → 科学计数法"的优先级降级，直到能塞进宽度为止。
"""

from __future__ import annotations


def fit_width(value, max_width: int) -> str:
    """
    把 value 格式化到最多 max_width 个字符。

    策略（依次尝试，第一个能塞下的就返回）：
      1. 原值的字符串形式（"保持原样"——能塞下就不动）
      2. 解析为浮点数后，从当前小数位精度开始逐位减到 0
      3. 转科学计数法（大写 E），从高精度到低精度逐位减
      4. 都塞不下时返回原字符串（由调用方决定如何处理）

    Args:
        value: 输入值，可以是字符串、整数、浮点数等
        max_width: 字段的最大字符宽度

    Returns:
        格式化后的字符串（不含前后空格；不做右对齐填充，由调用方处理）
    """
    s = str(value).strip()
    if len(s) <= max_width:
        return s

    # 尝试解析为浮点数
    try:
        f = float(s)
    except (ValueError, TypeError):
        return s  # 非数值，无法压缩

    # 策略 2：逐位减小数精度
    # 先确定原字符串的小数位精度，作为起点
    if '.' in s and 'e' not in s.lower():
        dec_part = s.split('.', 1)[1]
        start_precision = len(dec_part)
    else:
        # 原值无小数（或已是科学计数法），从合理上限开始
        start_precision = 16

    for precision in range(start_precision, -1, -1):
        candidate = f"{f:.{precision}f}"
        if len(candidate) <= max_width:
            return candidate

    # 策略 3：科学计数法（大写 E，与 MAC 文件原格式一致）
    # Python 的 :e 默认 6 位小数 + 'e±XX'，共 12 字符起步
    for precision in range(15, -1, -1):
        candidate = f"{f:.{precision}e}".upper().replace("E+", "E+").replace("E-", "E-")
        if len(candidate) <= max_width:
            return candidate

    # 都塞不下，放弃压缩返回原值
    return s


def format_field(value, max_width: int) -> str:
    """
    把 value 格式化后右对齐填充到 max_width。

    与 fit_width 的区别：返回值长度一定等于 max_width（除非原值经所有降级后仍超长，
    此时返回降级后的最短形式，长度可能仍超过 max_width）。

    适用于 MAC 文件定宽字段的写回。
    """
    fitted = fit_width(value, max_width)
    if len(fitted) <= max_width:
        return fitted.rjust(max_width)
    return fitted


def normalize_number_str(value) -> str:
    """
    把数值字符串做"保持原样"风格的归一化。

    用于解决 Excel 把整数存为 float 的问题（如 76000 → 76000.0）：
      - 整数值（76000.0）→ "76000"
      - 浮点数（1.5, 0.293）→ 用 :g 紧凑表示
      - 科学计数法 → 大写 E（与 MAC 文件原格式一致）
      - 非数值 → str(value)
      - NaN/None → ""（空字符串）

    不改变本质上是非数值的字符串（如 "SKIN/Oi"）。
    """
    if value is None:
        return ''
    s = str(value).strip()
    if not s or s.lower() == 'nan':
        return ''
    try:
        f = float(s)
    except (ValueError, TypeError):
        return s
    if f == int(f):
        return str(int(f))
    out = f"{f:g}"
    if 'e' in out:
        out = out.upper().replace('e', 'E')
    return out
