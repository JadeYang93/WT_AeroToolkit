# -*- coding: utf-8 -*-
"""首次启动路径迁移助手。

仅当 项目根/config/.paths.json 不存在时执行一次：
- 把散落在 项目根/输入数据/ 顶层的旧文件移入 输入数据/{module}/ 子目录
- 为每个模块在 输出/ 下预创建子目录（pipeline 会自动 makedirs，这里只是兜底）

迁移成功后由 ConfigCenter.register_module() 写出 .paths.json，下次启动不再迁移。
任何一步失败都不抛异常，仅打印警告——用户可用「设置」对话框手动指。
"""
import os
import shutil

from global_config import CONFIG_PATH, CONFIG_DIR, INPUT_BASE, OUTPUT_BASE


def migrate_legacy_paths(modules):
    """首启迁移。

    Args:
        modules: iterable of (module_id, default_input_subdir, default_output_subdir)
    """
    if os.path.exists(CONFIG_PATH):
        return  # 已初始化过

    os.makedirs(CONFIG_DIR, exist_ok=True)

    for module_id, in_sub, out_sub in modules:
        # 输入：把散在 INPUT_BASE 顶层的文件移到 INPUT_BASE/{in_sub}/
        # 仅当目标子目录还不存在时做（避免重复迁移）
        if in_sub and os.path.isdir(INPUT_BASE):
            target = os.path.join(INPUT_BASE, in_sub)
            if not os.path.exists(target):
                loose = [
                    f for f in os.listdir(INPUT_BASE)
                    if f != in_sub and not f.startswith('.')
                ]
                if loose:
                    try:
                        os.makedirs(target, exist_ok=True)
                        for f in loose:
                            shutil.move(os.path.join(INPUT_BASE, f),
                                        os.path.join(target, f))
                        print(f'[migration] {module_id}: moved {len(loose)} '
                              f'items into {target}')
                    except OSError as e:
                        print(f'[migration] {module_id}: input move failed: {e}')

        # 输出：预创建子目录
        if out_sub and os.path.isdir(OUTPUT_BASE):
            try:
                os.makedirs(os.path.join(OUTPUT_BASE, out_sub), exist_ok=True)
            except OSError as e:
                print(f'[migration] {module_id}: output mkdir failed: {e}')


def migrate_extras_between_modules(src_module, dst_module, key):
    """跨模块一次性 extras 迁移。

    若 .paths.json 已存在（非首启场景），且 dst_module 的 extra ``key`` 为空、
    src_module 有值，则把值复制过去。用于模块拆分时把 extras 跟着业务迁走，
    不让用户重复配置。

    Args:
        src_module: 源模块 id（如 ``'blade_converter'``）
        dst_module: 目标模块 id（如 ``'focus6_solver'``）
        key: extras 字段名（如 ``'modules_path'``）
    """
    import json
    if not os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    src_v = (data.get(src_module, {}) or {}).get('extras', {}).get(key, '')
    dst_v = (data.get(dst_module, {}) or {}).get('extras', {}).get(key, '')
    if src_v and not dst_v:
        data.setdefault(dst_module, {}).setdefault('extras', {})[key] = src_v
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f'[migration] copied {key}: {src_module} → {dst_module}')
        except OSError as e:
            print(f'[migration] extras copy failed: {e}')
