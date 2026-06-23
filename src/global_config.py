# -*- coding: utf-8 -*-
"""全局配置中心（ConfigCenter 单例）。

集中管理所有工具模块的输入/输出路径，持久化到 项目根/config/.paths.json。
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
                        extra_keys=None):
        """注册模块的默认路径（幂等）。

        - 若 JSON 中已有 module_id，保留用户已设值不动；
        - 否则用 default_input_sub / default_output_sub 拼绝对路径并写入。
        - extra_keys：可选的额外路径字段名列表（如求解器 exe 路径）。
          注册时初始化为空字符串，由 UI 让用户填写；set_extra 单独更新。
        """
        self._lock.lock()
        try:
            if module_id in self._data:
                return
            entry = {
                'input': os.path.join(INPUT_BASE, default_input_sub),
                'output': os.path.join(OUTPUT_BASE, default_output_sub),
            }
            if extra_keys:
                entry['extras'] = {k: '' for k in extra_keys}
            self._data[module_id] = entry
            self._save()
        finally:
            self._lock.unlock()

    def get_paths(self, module_id):
        """返回模块路径 dict。

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
                'input': entry.get('input') or os.path.join(INPUT_BASE, module_id),
                'output': entry.get('output') or os.path.join(OUTPUT_BASE, module_id),
            }
            extras = entry.get('extras')
            if isinstance(extras, dict):
                for k, v in extras.items():
                    result[k] = v
            return result
        finally:
            self._lock.unlock()

    def set_paths(self, module_id, input_path=None, output_path=None, extras=None):
        """设置模块路径 + 校验 + 持久化 + 广播。

        支持部分更新：``input_path`` / ``output_path`` / ``extras`` 任一为 None 时跳过该校验。
        ``extras`` 是 dict（如 ``{'farob_exe': '...'}``），只更新列出的字段，其他 extras 保留。

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
                entry['input'] = input_path
            if output_path is not None:
                entry['output'] = output_path
            if extras is not None:
                ext_dict = entry.get('extras')
                if not isinstance(ext_dict, dict):
                    ext_dict = {}
                    entry['extras'] = ext_dict
                ext_dict.update(extras)
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
        Returns: list[str] 校验错误（空列表 = 成功）。
        """
        if value and value.strip():
            errs = self._validate(value, 'extra')
            if errs:
                return [f'[{key}] {e}' for e in errs]
        else:
            value = ''
        self._lock.lock()
        try:
            entry = self._data.get(module_id) or {}
            ext_dict = entry.get('extras')
            if not isinstance(ext_dict, dict):
                ext_dict = {}
                entry['extras'] = ext_dict
            ext_dict[key] = value
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
        """读 JSON。文件不存在 → 空 dict；损坏 → 备份后空 dict。"""
        if not os.path.exists(CONFIG_PATH):
            return {}
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError('顶层不是 dict')
            return data
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
