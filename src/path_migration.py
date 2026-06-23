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
