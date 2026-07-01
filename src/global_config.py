# -*- coding: utf-8 -*-
"""全局配置中心（ConfigCenter 单例）。

集中管理所有工具模块的输入/输出路径，持久化到 项目根/config/.paths.json。

**路径存储格式（v0.2.08+）**：
- 默认存**相对路径**（相对 PROJECT_ROOT，正斜杠分隔），工具箱整体迁移时自动跟随。
- 用户选的目录在 PROJECT_ROOT 之外（如 D:\\某外部目录）则存**绝对路径**。
- extras（求解器路径等系统级软件位置）始终存绝对路径。
- 老 JSON（绝对路径格式）启动时自动迁移：在 PROJECT_ROOT 内的转相对，否则保留绝对。

其他特性：
- 单例：全局共享一个 config_center 实例（在模块底部导出）。
- 信号：set_paths 成功后 emit paths_changed(module_id)，所有面板监听并刷新自身路径。
- 原子写：tempfile + os.replace + retry，规避 Windows 文件被占用。
- JSON 损坏兜底：把坏文件重命名为 .corrupt-{ts} 后返回空 dict。
- 线程安全：QMutex 锁住 _save / _load。

每个工具面板通过类属性声明 MODULE_ID + 默认子目录名，在 __init__ 里调
register_module() 注册（幂等），之后 get_paths()/set_paths() 读写自己的路径。
"""
import os
import json
import time
import shutil
from datetime import datetime

from PyQt5.QtCore import QObject, QMutex, pyqtSignal

from config import PROJECT_ROOT


CONFIG_DIR = os.path.join(PROJECT_ROOT, 'config')
CONFIG_PATH = os.path.join(CONFIG_DIR, '.paths.json')
INPUT_BASE = os.path.join(PROJECT_ROOT, '输入数据')
OUTPUT_BASE = os.path.join(PROJECT_ROOT, '输出')


def _to_stored(abs_path):
    """绝对路径 → 存储格式。

    - 在 PROJECT_ROOT 内：存相对路径（正斜杠），工具箱迁移时自动跟随
    - 在 PROJECT_ROOT 外（含跨盘符）：存绝对路径
    - 空串/None 原样返回 ''
    """
    if not abs_path:
        return ''
    try:
        rel = os.path.relpath(abs_path, PROJECT_ROOT)
        if rel.startswith('..'):
            # 在工具箱外，存绝对
            return os.path.normpath(abs_path).replace('\\', '/')
        return rel.replace('\\', '/')
    except (ValueError, OSError):
        # Windows 跨盘符 relpath 抛 ValueError
        return os.path.normpath(abs_path).replace('\\', '/')


def _from_stored(stored):
    """存储格式 → 绝对路径（给业务层用）。

    - 绝对路径：原样返回（用 OS 分隔符）
    - 相对路径：拼 PROJECT_ROOT
    - 空串：返回 ''
    """
    if not stored:
        return ''
    if os.path.isabs(stored):
        return os.path.normpath(stored)
    return os.path.normpath(os.path.join(PROJECT_ROOT, stored))


class ConfigCenter(QObject):
    """工具模块路径的中央注册表 + 持久化层。

    非强制单例：模块底部暴露一个全局实例 `config_center`，业务代码统一 import 它。
    直接 `ConfigCenter()` 会得到一个空的新实例（仅用于测试隔离）。
    """

    # 路径变更广播。参数 = 被改模块的 module_id；空串表示全量刷新（极少用）
    paths_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._lock = QMutex()
        self._data = self._load_raw()

    # ---------- 公开 API ----------

    def register_module(self, module_id, default_input_sub, default_output_sub,
                        extra_keys=None, default_extras=None):
        """注册模块的默认路径（幂等）。

        - 若 JSON 中已有 module_id，保留用户已设值不动；
        - 否则用 default_input_sub / default_output_sub（相对 PROJECT_ROOT 的子目录）
          作为相对路径直接写入存储。
        - extra_keys：可选的额外路径字段名列表（如求解器 exe 路径）。
          注册时初始化为空字符串，由 UI 让用户填写；set_extra 单独更新。
        - default_extras：可选 dict，给 extras 字段提供默认值（如
          ``{'appdata_path': '配置'}``）。
          用户已在 JSON 设过的值不动；只对空字段填默认。
        """
        self._lock.lock()
        try:
            if module_id in self._data:
                # 已注册：如果新版本加了新 extras 字段（如 appdata_path），补充默认值
                if default_extras:
                    entry = self._data[module_id]
                    ext_dict = entry.get('extras')
                    if not isinstance(ext_dict, dict):
                        ext_dict = {}
                        entry['extras'] = ext_dict
                    changed = False
                    for k, v in default_extras.items():
                        if k not in ext_dict or not ext_dict[k]:
                            ext_dict[k] = v
                            changed = True
                    if changed:
                        self._save()
                return
            entry = {
                # 存相对路径（如 '输入数据/wind_farm'）
                'input': f'输入数据/{default_input_sub}',
                'output': f'输出/{default_output_sub}',
            }
            if extra_keys or default_extras:
                ext_dict = {k: '' for k in (extra_keys or [])}
                if default_extras:
                    for k, v in default_extras.items():
                        ext_dict[k] = v
                entry['extras'] = ext_dict
            self._data[module_id] = entry
            self._save()
        finally:
            self._lock.unlock()

    def get_paths(self, module_id):
        """返回模块路径 dict（**绝对路径**，业务层直接用）。

        无 extras 时：``{'input': abs, 'output': abs}``
        有 extras 时：额外字段直接平铺到顶层，如
        ``{'input': ..., 'output': ..., 'farob_exe': ..., ...}``。
        未注册的模块返回基于 INPUT_BASE/OUTPUT_BASE 的兜底。
        """
        self._lock.lock()
        try:
            entry = self._data.get(module_id)
            if not entry:
                return {
                    'input': os.path.join(INPUT_BASE, module_id),
                    'output': os.path.join(OUTPUT_BASE, module_id),
                }
            result = {
                'input': _from_stored(entry.get('input')) or os.path.join(INPUT_BASE, module_id),
                'output': _from_stored(entry.get('output')) or os.path.join(OUTPUT_BASE, module_id),
            }
            extras = entry.get('extras')
            if isinstance(extras, dict):
                for k, v in extras.items():
                    # extras 也走相对/绝对路径转换（跟 input/output 一致）
                    result[k] = _from_stored(v) if v else ''
            return result
        finally:
            self._lock.unlock()

    def set_paths(self, module_id, input_path=None, output_path=None, extras=None):
        """设置模块路径 + 校验 + 持久化 + 广播。

        支持部分更新：``input_path`` / ``output_path`` / ``extras`` 任一为 None 时跳过该校验。
        ``extras`` 是 dict（如 ``{'farob_exe': '...'}``），只更新列出的字段，其他 extras 保留。

        **存储格式**：input/output 存相对路径（在 PROJECT_ROOT 内）或绝对路径（在外）。
        extras 始终存绝对路径。

        Returns: list[str] 校验错误信息（空列表 = 成功）。失败时不写盘不广播。
        """
        errs = []
        if input_path is not None:
            for e in self._validate(input_path, 'input'):
                errs.append(f'[输入] {e}')
        if output_path is not None:
            for e in self._validate(output_path, 'output'):
                errs.append(f'[输出] {e}')
        if extras is not None:
            for k, v in extras.items():
                for e in self._validate(v, 'extra'):
                    errs.append(f'[{k}] {e}')
        if errs:
            return errs

        self._lock.lock()
        try:
            entry = self._data.get(module_id) or {}
            if input_path is not None:
                entry['input'] = _to_stored(input_path)
            if output_path is not None:
                entry['output'] = _to_stored(output_path)
            if extras is not None:
                ext_dict = entry.get('extras')
                if not isinstance(ext_dict, dict):
                    ext_dict = {}
                    entry['extras'] = ext_dict
                # extras 也走相对/绝对存储（input/output 同逻辑）
                for k, v in extras.items():
                    ext_dict[k] = _to_stored(v) if v else ''
            self._data[module_id] = entry
            self._save()
        finally:
            self._lock.unlock()

        # 广播必须在锁外，避免 slot 中再调本类方法导致死锁
        self.paths_changed.emit(module_id)
        return []

    def set_extra(self, module_id, key, value):
        """单独更新一个 extra 字段（求解器 exe 路径用）。

        - 空串/None 视为「清空」，直接写入（用于移除已配置的路径）；
        - 非空时校验：父目录必须存在 + 可写（文件本身允许不存在，用户可能先填路径再装求解器）。

        **存储格式**：跟 input/output 一致，走 _to_stored（在 PROJECT_ROOT 内的存相对，外部存绝对）。

        Returns: list[str] 校验错误（空列表 = 成功）。
        """
        if value and value.strip():
            errs = self._validate(value, 'extra')
            if errs:
                return [f'[{key}] {e}' for e in errs]
            stored = _to_stored(value)
        else:
            stored = ''
        self._lock.lock()
        try:
            entry = self._data.get(module_id) or {}
            ext_dict = entry.get('extras')
            if not isinstance(ext_dict, dict):
                ext_dict = {}
                entry['extras'] = ext_dict
            ext_dict[key] = stored
            self._data[module_id] = entry
            self._save()
        finally:
            self._lock.unlock()
        self.paths_changed.emit(module_id)
        return []

    def list_modules(self):
        """返回已注册模块的 module_id 列表（按 JSON 中的出现顺序）。"""
        self._lock.lock()
        try:
            return list(self._data.keys())
        finally:
            self._lock.unlock()

    # ---------- 校验 ----------

    @staticmethod
    def _validate(path, role):
        """三层校验。role ∈ {'input', 'output'}。

        - input: 必须存在 + 是目录 + 可读
        - output: 父目录必须存在 + 可写（自身不存在时 pipeline 会自动 makedirs）
        """
        errs = []
        if not path or not path.strip():
            return ['路径为空']
        path = path.strip()

        if role == 'input':
            if not os.path.exists(path):
                errs.append(f'目录不存在: {path}')
            elif not os.path.isdir(path):
                errs.append(f'不是目录: {path}')
            elif not os.access(path, os.R_OK):
                errs.append(f'不可读: {path}')
        else:  # output
            parent = os.path.dirname(path.rstrip(os.sep)) or os.getcwd()
            if not os.path.isdir(parent):
                errs.append(f'父目录不存在: {parent}')
            elif not os.access(parent, os.W_OK):
                errs.append(f'父目录不可写: {parent}')
        return errs

    # ---------- 持久化 ----------

    def _load_raw(self):
        """读 JSON。文件不存在 → 空 dict；损坏 → 备份后空 dict。

        自动迁移：检测老格式（input/output 存绝对路径），如果在 PROJECT_ROOT 内
        则转相对，否则保留绝对。extras 不变（始终绝对）。
        """
        if not os.path.exists(CONFIG_PATH):
            return {}
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('顶层不是 dict')
            return self._migrate_legacy_paths(data)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            # 备份坏文件，避免下次还崩
            ts = datetime.now().strftime('%Y%m%d-%H%M%S')
            corrupt = CONFIG_PATH + f'.corrupt-{ts}'
            try:
                shutil.copy2(CONFIG_PATH, corrupt)
                os.remove(CONFIG_PATH)
            except OSError:
                pass   # 备份失败也不阻塞启动
            print(f'[ConfigCenter] 配置文件损坏已备份到 {corrupt}，原因: {e}')
            return {}

    @staticmethod
    def _migrate_legacy_paths(data):
        """把老格式的 input/output 绝对路径转成相对路径（仅当在 PROJECT_ROOT 内）。

       extras 字段不动（始终是绝对路径）。
        迁移后写回 JSON，保证只跑一次。
        """
        migrated = False
        for module_id, entry in data.items():
            if not isinstance(entry, dict):
                continue
            for key in ('input', 'output'):
                v = entry.get(key)
                if isinstance(v, str) and os.path.isabs(v):
                    new_v = _to_stored(v)
                    if new_v != v:
                        entry[key] = new_v
                        migrated = True
        if migrated:
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                tmp = CONFIG_PATH + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(json.dumps(data, ensure_ascii=False, indent=2))
                os.replace(tmp, CONFIG_PATH)
                print(f'[ConfigCenter] 老 JSON 已迁移到相对路径格式')
            except OSError as e:
                print(f'[ConfigCenter] JSON 迁移写盘失败（不阻塞启动）: {e}')
        return data

    def _save(self):
        """原子写。临时文件 + os.replace；Windows 被占用时 retry 3 次。

        注意：调用方必须已持锁。
        """
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + '.tmp'
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        last_err = None
        for _ in range(3):
            try:
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(payload)
                os.replace(tmp, CONFIG_PATH)   # 原子
                return
            except PermissionError as e:
                last_err = e
                time.sleep(0.1)
            except OSError as e:
                last_err = e
                break   # 非 PermissionError 不重试
        if last_err is not None:
            raise last_err

    # ---------- 测试专用 ----------

    def _reset_for_test(self):
        """单测重置用。生产代码不要调。"""
        self._lock.lock()
        try:
            self._data = {}
            if os.path.exists(CONFIG_PATH):
                os.remove(CONFIG_PATH)
        finally:
            self._lock.unlock()


# 全局单例：所有模块 import 它
config_center = ConfigCenter()


class ModuleActivityHub(QObject):
    """模块运行状态广播中心（全局单例 activity_hub）。

    各模块面板在 _set_running / _on_run / _on_finished 中 emit running_changed，
    MainWindow 监听以在左侧 nav_list 给运行中的模块加视觉提示
    （● 前缀 + 半透明气流青背景）。

    参数：(module_id: str, is_running: bool)
    """

    running_changed = pyqtSignal(str, bool)


# 全局单例：所有模块 import 它
activity_hub = ModuleActivityHub()
