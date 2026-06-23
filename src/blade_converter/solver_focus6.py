#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
FOCUS6求解器工作线程

负责FOCUS6求解器的集成，包括准备工作、生成配置文件、执行求解器、监控进程状态
"""

import re
import pandas as pd
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

from .bc_config import (
    SOLVER_FAROB, SOLVER_FRBEX, DEFAULT_MODULES_PATH, DEFAULT_MAC_FILE,
    FRBEX_DEFAULT_DRMX, FUNCTION_READ_MAC, FUNCTION_PARSE_MAC,
    FUNCTION_STRAIN, FUNCTION_FREQUENCY, FUNCTION_TIP_DEFLECTION, FUNCTION_WEIGHT,
    FUNCTION_LOAD_CONVERSION, FUNCTION_FOLDER_NAMES, LOG_SEPARATOR
)


class Focus6SolverThread(QThread):
    """FOCUS6求解器工作线程"""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()
    progress_signal = pyqtSignal(int, int)  # current, total

    def _get_function_folder_name(self, function_name):
        """获取功能对应的文件夹名称（英文）

        Args:
            function_name: 功能名称（中文）

        Returns:
            str: 文件夹名称（英文）
        """
        return FUNCTION_FOLDER_NAMES.get(function_name, function_name)

    def _find_function_folder(self, sum_folder, solver_type, function_name):
        """查找功能文件夹，支持旧的中文名称和新的英文名称

        Args:
            sum_folder: SUM文件夹路径
            solver_type: 求解器类型
            function_name: 功能名称（中文）

        Returns:
            Path: 文件夹路径，如果都不存在返回None
        """
        # 优先使用新的英文名称
        new_folder_name = f"{solver_type}_{self._get_function_folder_name(function_name)}"
        new_folder = sum_folder / new_folder_name
        if new_folder.exists():
            return new_folder

        # 如果新名称不存在，尝试旧的中文名称
        old_folder_name = f"{solver_type}_{function_name}"
        old_folder = sum_folder / old_folder_name
        if old_folder.exists():
            return old_folder

        # 都不存在，返回新名称（用于创建新文件夹）
        return new_folder

    def __init__(self, params, skip_prepare=False, generate_csv=True):
        super().__init__()
        self.params = params
        self.skip_prepare = skip_prepare  # 是否跳过准备步骤（默认False）
        self.generate_csv = generate_csv  # 是否生成CSV文件（默认True）
        self.process = None
        self.monitor_timer = None
        self.is_monitoring = False
        self.load_convert_folder = None  # 载荷转化文件夹（应变计算功能）
        self.strain_calc_folder = None  # 应变计算文件夹（应变计算功能）

    def _get_hidden_window_startupinfo(self):
        """获取隐藏窗口的STARTUPINFO（Windows专用）"""
        import subprocess
        import platform

        if platform.system() == 'Windows':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            return startupinfo
        else:
            return None

    def _cleanup_frbex_db_cache(self, buffer_folder):
        """清理FOCUS6数据库缓存文件，避免弹出提示框

        Args:
            buffer_folder: BUFFER文件夹路径
        """
        if buffer_folder is None or not buffer_folder.exists():
            return

        frbex_dbf = buffer_folder / "FRBEX.DBF"
        if frbex_dbf.exists():
            try:
                frbex_dbf.unlink()
                self.log_signal.emit(f"   ✓ 已清理数据库缓存文件: FRBEX.DBF")
            except Exception as e:
                self.log_signal.emit(f"   ⚠ 警告：无法删除FRBEX.DBF: {str(e)}")

    def stop(self):
        """停止正在运行的求解器进程"""
        try:
            import psutil

            # 停止主进程
            if self.process and self.process.poll() is None:
                # 进程还在运行
                try:
                    # 尝试优雅终止
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except:
                        # 如果3秒后还没结束，强制杀死
                        self.process.kill()

                    self.log_signal.emit(f"\n✓ 求解器进程已终止")
                except Exception as e:
                    self.log_signal.emit(f"   ⚠ 警告：无法终止进程: {str(e)}")

                    # 尝试使用psutil强制终止
                    try:
                        parent = psutil.Process(self.process.pid)
                        children = parent.children(recursive=True)
                        for child in children:
                            child.kill()
                        parent.kill()
                        self.log_signal.emit(f"   ✓ 已强制终止求解器进程及子进程")
                    except:
                        pass

            # 停止监控定时器
            if self.monitor_timer and self.monitor_timer.isActive():
                self.monitor_timer.stop()
                self.is_monitoring = False

        except Exception as e:
            self.log_signal.emit(f"   ⚠ 停止计算时出错: {str(e)}")

    def run(self):
        """主流程"""
        try:
            self.log_signal.emit(LOG_SEPARATOR)
            function_name = self.params['function']
            solver_type = self.params['solver_type']

            self.log_signal.emit(f"开始FOCUS6求解器任务")
            self.log_signal.emit(f"求解器: {solver_type}")
            self.log_signal.emit(f"计算功能: {function_name}")
            self.log_signal.emit(LOG_SEPARATOR)

            # 重量计算：直接执行，不需要准备工作
            if function_name == FUNCTION_WEIGHT:
                self.log_signal.emit(f"\n开始重量计算...")
                if not self.perform_weight_calculation():
                    return
                return

            # 载荷转化：单独执行（仅调用 UserLoadcaseConverter，不需要 farob/frbex 求解器）
            if function_name == FUNCTION_LOAD_CONVERSION:
                self.log_signal.emit(f"\n开始载荷转化（独立模式）...")
                if not self._run_load_conversion_only():
                    return
                return

            # 判断是否跳过准备步骤
            if not self.skip_prepare:
                # 完整流程：准备 + 计算
                self.log_signal.emit(f"\n开始准备工作...")

                # 准备工作阶段
                if not self.prepare_work_directory():
                    return

                # 生成配置文件
                if function_name == FUNCTION_READ_MAC:
                    config_file = self.generate_parse_frb()
                    if not config_file:
                        return
                    # 执行求解器
                    self.execute_solver(config_file)
                elif function_name == FUNCTION_PARSE_MAC:
                    config_file = self.generate_build_database_frb()
                    if not config_file:
                        return
                    # 检查BUFFER是否为空并给出警告
                    self.check_and_warn_buffer_empty()
                    # 执行求解器
                    self.execute_solver(config_file)
                elif function_name == FUNCTION_STRAIN:
                    # 应变计算 - 载荷转化
                    if not self.convert_loadcase():
                        return
                elif function_name == FUNCTION_FREQUENCY:
                    # 频率计算
                    if not self.perform_frequency_calculation():
                        return
                elif function_name == FUNCTION_TIP_DEFLECTION:
                    # 叶尖挠度计算
                    if not self.perform_tip_deflection_calculation():
                        return
                else:
                    self.log_signal.emit(f"\n✗ 错误：该功能暂未实现")
                    self.finished_signal.emit()
                    return
            else:
                # 跳过准备步骤，直接执行计算
                self.log_signal.emit(f"\n✓ 检测到准备工作已完成，跳过准备步骤")
                self.log_signal.emit(f"   直接执行计算...")

                # 设置工作文件夹路径
                self._set_work_folder_from_params()

                # 执行计算（重量计算不会进入这里，因为在前面已经处理）
                if function_name == FUNCTION_READ_MAC:
                    config_file = self.work_folder / "parse.frb"
                    self.execute_solver(str(config_file))
                elif function_name == FUNCTION_PARSE_MAC:
                    # 根据求解器类型选择正确的配置文件
                    if solver_type == SOLVER_FRBEX:
                        config_file = self.work_folder / "frbex_build_blade_database.frb"
                    else:  # SOLVER_FAROB
                        config_file = self.work_folder / "build_database.frb"
                    # 检查BUFFER是否为空并给出警告
                    self.check_and_warn_buffer_empty()
                    self.execute_solver(str(config_file))
                elif function_name == FUNCTION_STRAIN:
                    # 应变计算 - 载荷转化
                    if not self.convert_loadcase():
                        return
                elif function_name == FUNCTION_FREQUENCY:
                    # 频率计算
                    if not self.perform_frequency_calculation():
                        return
                elif function_name == FUNCTION_TIP_DEFLECTION:
                    # 叶尖挠度计算
                    if not self.perform_tip_deflection_calculation():
                        return
                else:
                    self.log_signal.emit(f"\n✗ 错误：该功能暂未实现")
                    self.finished_signal.emit()
                    return

        except Exception as e:
            self.log_signal.emit(f"\n{LOG_SEPARATOR}")
            self.log_signal.emit(f"错误: {str(e)}")
            self.log_signal.emit(f"{LOG_SEPARATOR}")
            import traceback
            self.log_signal.emit(f"详细错误信息:\n{traceback.format_exc()}")
        finally:
            self.finished_signal.emit()

    def prepare_work_directory(self):
        """准备工作目录"""
        try:
            import shutil
            import os

            solver_type = self.params['solver_type']
            function_name = self.params['function']
            sum_folder = Path(self.params['sum_folder'])
            mac_file = Path(self.params['mac_file'])
            solver_path = Path(self.params['solver_path'])

            self.log_signal.emit(f"\n1. 准备工作目录...")
            self.log_signal.emit(f"   SUM文件夹: {sum_folder}")

            # 应变计算功能需要同时创建两个工作文件夹
            if function_name == FUNCTION_STRAIN:
                load_convert_folder_name = f"{solver_type}_LoadConversion"
                strain_calc_folder_name = f"{solver_type}_CalcStrain"

                self.load_convert_folder = sum_folder / load_convert_folder_name
                self.strain_calc_folder = sum_folder / strain_calc_folder_name
                self.work_folder = self.load_convert_folder  # 设置为载荷转化文件夹，用于载荷转化步骤

                self.log_signal.emit(f"   载荷转化文件夹: {load_convert_folder_name}")
                self.log_signal.emit(f"   应变计算文件夹: {strain_calc_folder_name}")
            else:
                # 其他功能：工作文件夹名称：求解器_功能英文名
                folder_name = self._get_function_folder_name(function_name)
                work_folder_name = f"{solver_type}_{folder_name}"
                self.work_folder = sum_folder / work_folder_name
                self.log_signal.emit(f"   工作文件夹: {work_folder_name}")

            # 根据功能类型检查不同的文件
            if function_name == FUNCTION_STRAIN:
                # 应变计算：检查载荷文件
                load_file = Path(self.params.get('load_file', ''))
                if not load_file.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到载荷文件: {load_file}")
                    return False
                self.log_signal.emit(f"   ✓ 载荷文件检查通过")

                # 检查utils路径（用于UserLoadcaseConverter.exe）
                utils_path = solver_path.parent / "utils"
                if not utils_path.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到utils文件夹: {utils_path}")
                    return False
                converter_exe = utils_path / "UserLoadcaseConverter.exe"
                if not converter_exe.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到UserLoadcaseConverter.exe: {converter_exe}")
                    return False
                self.log_signal.emit(f"   ✓ 载荷转换工具检查通过")
            else:
                # 其他功能：检查mac文件
                # 1. 检查mac文件
                if not mac_file.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到mac文件: {mac_file}")
                    return False
                self.log_signal.emit(f"   ✓ mac文件检查通过")

                # 2. 检查求解器路径
                if not solver_path.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到求解器路径: {solver_path}")
                    return False
                self.log_signal.emit(f"   ✓ 求解器路径检查通过")

                # 3. 检查求解器可执行文件
                solver_exe_name = f"{solver_type}.exe"
                solver_exe = solver_path / solver_exe_name
                if not solver_exe.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到求解器: {solver_exe}")
                    return False
                self.log_signal.emit(f"   ✓ 求解器检查通过 ({solver_exe_name})")

            # 检查macros文件夹（可选，仅非应变计算功能）
            if function_name != FUNCTION_STRAIN:
                solver_macros = solver_path / "macros"
                if not solver_macros.exists():
                    self.log_signal.emit(f"   ⚠ 警告：找不到macros文件夹: {solver_macros}")

                # 复制mac文件到SUM文件夹
                mac_file_in_sum = sum_folder / mac_file.name
                if not mac_file_in_sum.exists():
                    shutil.copy2(mac_file, mac_file_in_sum)
                    self.log_signal.emit(f"   ✓ 复制mac文件到SUM文件夹")

            # 创建工作文件夹
            if function_name == FUNCTION_STRAIN:
                # 应变计算：创建两个工作文件夹
                # 1. 创建载荷转化文件夹（不创建BUFFER，不需要）
                # 注意：不删除已存在的载荷转化文件夹，避免破坏阶段1生成的LOAD.LD1
                if not self.load_convert_folder.exists():
                    self.load_convert_folder.mkdir(parents=True, exist_ok=True)
                    self.log_signal.emit(f"   ✓ 创建载荷转化文件夹")
                else:
                    self.log_signal.emit(f"   ✓ 使用已存在的载荷转化文件夹")

                # 2. 创建应变计算文件夹
                if self.strain_calc_folder.exists():
                    shutil.rmtree(self.strain_calc_folder)
                self.strain_calc_folder.mkdir(parents=True, exist_ok=True)
                self.log_signal.emit(f"   ✓ 创建应变计算文件夹")

                # 3. 在应变计算文件夹中复制BUFFER（从解析mac文件文件夹）
                parse_mac_folder = self._find_function_folder(sum_folder, solver_type, FUNCTION_PARSE_MAC)
                source_buffer = parse_mac_folder / "BUFFER"
                target_buffer = self.strain_calc_folder / "BUFFER"

                if not source_buffer.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到BUFFER文件夹: {source_buffer}")
                    self.log_signal.emit(f"   提示：请先执行'解析mac文件'功能")
                    return False

                # 检查BUFFER文件夹是否有文件
                buffer_files = list(source_buffer.glob('*'))
                if not buffer_files:
                    self.log_signal.emit(f"\n✗ 错误：BUFFER文件夹为空: {source_buffer}")
                    return False

                shutil.copytree(source_buffer, target_buffer)
                self.log_signal.emit(f"   ✓ 复制BUFFER文件夹（{len(buffer_files)}个文件）")

                # 4. 创建子文件夹
                subfolders = ["FATDATA", "LOADS", "PROFILES"]
                for folder in subfolders:
                    folder_path = self.strain_calc_folder / folder
                    folder_path.mkdir(parents=True, exist_ok=True)
                self.log_signal.emit(f"   ✓ 创建子文件夹: {', '.join(subfolders)}")

                # 5. 复制LOAD.LD1文件（从载荷转化文件夹）
                load_convert_folder = sum_folder / f"{solver_type}_LoadConversion"
                load_ld1_source = load_convert_folder / "LOAD.LD1"
                load_ld1_target = self.strain_calc_folder / "LOAD.LD1"

                if not load_ld1_source.exists():
                    self.log_signal.emit(f"\n✗ 错误：找不到载荷文件: {load_ld1_source}")
                    self.log_signal.emit(f"   提示：请先执行载荷转化（阶段1）")
                    return False

                shutil.copy2(load_ld1_source, load_ld1_target)
                self.log_signal.emit(f"   ✓ 复制载荷文件: LOAD.LD1")

                # 6. 复制MACROS文件夹
                solver_macros = solver_path / "macros"
                work_macros = self.strain_calc_folder / "MACROS"
                if solver_macros.exists():
                    shutil.copytree(solver_macros, work_macros)
                    self.log_signal.emit(f"   ✓ 复制MACROS文件夹")
                else:
                    self.log_signal.emit(f"   ⚠ 警告：找不到macros文件夹: {solver_macros}")

            else:
                # 其他功能：创建单个工作文件夹
                if not self.work_folder.exists():
                    self.work_folder.mkdir(parents=True, exist_ok=True)
                    self.log_signal.emit(f"   ✓ 创建工作文件夹")

                # 频率计算功能：从解析mac文件文件夹复制BUFFER
                if function_name == FUNCTION_FREQUENCY:
                    parse_mac_folder = self._find_function_folder(sum_folder, solver_type, FUNCTION_PARSE_MAC)
                    source_buffer = parse_mac_folder / "BUFFER"
                    target_buffer = self.work_folder / "BUFFER"

                    if not source_buffer.exists():
                        self.log_signal.emit(f"\n✗ 错误：找不到BUFFER文件夹: {source_buffer}")
                        self.log_signal.emit(f"   提示：请先执行'解析mac文件'功能")
                        return False

                    # 检查BUFFER文件夹是否有文件
                    buffer_files = list(source_buffer.glob('*'))
                    if not buffer_files:
                        self.log_signal.emit(f"\n✗ 错误：BUFFER文件夹为空: {source_buffer}")
                        return False

                    # 如果目标BUFFER已存在，先删除
                    if target_buffer.exists():
                        shutil.rmtree(target_buffer)
                        self.log_signal.emit(f"   ✓ 清除旧的BUFFER文件夹")

                    shutil.copytree(source_buffer, target_buffer)
                    self.log_signal.emit(f"   ✓ 复制BUFFER文件夹（{len(buffer_files)}个文件）")

                # 叶尖挠度计算功能：从解析mac文件文件夹复制BUFFER，并复制载荷文件
                elif function_name == FUNCTION_TIP_DEFLECTION:
                    # 1. 从解析mac文件夹复制BUFFER
                    parse_mac_folder = self._find_function_folder(sum_folder, solver_type, FUNCTION_PARSE_MAC)
                    source_buffer = parse_mac_folder / "BUFFER"
                    target_buffer = self.work_folder / "BUFFER"

                    if not source_buffer.exists():
                        self.log_signal.emit(f"\n✗ 错误：找不到BUFFER文件夹: {source_buffer}")
                        self.log_signal.emit(f"   提示：请先执行'解析mac文件'功能")
                        return False

                    # 检查BUFFER文件夹是否有文件
                    buffer_files = list(source_buffer.glob('*'))
                    if not buffer_files:
                        self.log_signal.emit(f"\n✗ 错误：BUFFER文件夹为空: {source_buffer}")
                        return False

                    # 如果目标BUFFER已存在，先删除
                    if target_buffer.exists():
                        shutil.rmtree(target_buffer)
                        self.log_signal.emit(f"   ✓ 清除旧的BUFFER文件夹")

                    shutil.copytree(source_buffer, target_buffer)
                    self.log_signal.emit(f"   ✓ 复制BUFFER文件夹（{len(buffer_files)}个文件）")

                    # 2. 检查并复制载荷转化文件（LOAD.LD1）
                    load_convert_folder = sum_folder / f"{solver_type}_LoadConversion"
                    load_ld1_source = load_convert_folder / "LOAD.LD1"
                    load_ld1_target = self.work_folder / "LOAD.LD1"

                    if not load_ld1_source.exists():
                        self.log_signal.emit(f"\n✗ 错误：找不到载荷文件: {load_ld1_source}")
                        self.log_signal.emit(f"   提示：请先执行应变计算的载荷转化步骤")
                        return False

                    shutil.copy2(load_ld1_source, load_ld1_target)
                    self.log_signal.emit(f"   ✓ 复制载荷文件: LOAD.LD1")

            # 复制macros文件夹（仅非应变计算、非重量计算功能）
            if function_name != FUNCTION_STRAIN and function_name != FUNCTION_WEIGHT:
                # 所有使用farob求解器的功能（读取mac、解析mac、频率）：从求解器子文件夹复制MACROS
                solver_macros = solver_path / "macros"
                work_macros = self.work_folder / "MACROS"

                if solver_macros.exists():
                    # 如果目标MACROS已存在，先删除
                    if work_macros.exists():
                        shutil.rmtree(work_macros)
                        self.log_signal.emit(f"   ✓ 清除旧的MACROS文件夹")
                    shutil.copytree(solver_macros, work_macros)
                    self.log_signal.emit(f"   ✓ 复制MACROS文件夹（从{solver_path.name}）")
                else:
                    self.log_signal.emit(f"   ⚠ 警告：找不到{solver_path}/macros文件夹")

                # 创建子文件夹
                if function_name == FUNCTION_WEIGHT:
                    # 重量计算：不需要创建任何子文件夹
                    subfolders = []
                    self.log_signal.emit(f"   ✓ 重量计算不需要子文件夹")
                elif function_name == FUNCTION_FREQUENCY:
                    # 频率计算：不需要创建BUFFER（已复制），只创建其他子文件夹
                    subfolders = ["FATDATA", "LOADS", "PROFILES"]
                else:
                    # 其他功能：创建所有子文件夹
                    subfolders = ["BUFFER", "FATDATA", "LOADS", "PROFILES"]

                if subfolders:  # 只有当有子文件夹需要创建时才执行
                    for folder in subfolders:
                        folder_path = self.work_folder / folder
                        if not folder_path.exists():
                            folder_path.mkdir(parents=True, exist_ok=True)
                    self.log_signal.emit(f"   ✓ 创建子文件夹: {', '.join(subfolders)}")

            # 复制mac文件到工作文件夹（仅读取mac文件功能需要）
            if function_name == FUNCTION_READ_MAC:
                mac_file_in_work = self.work_folder / "blade_geometry.mac"
                if not mac_file_in_work.exists():
                    shutil.copy2(mac_file, mac_file_in_work)
                    self.log_signal.emit(f"   ✓ 复制mac文件到工作文件夹（重命名为blade_geometry.mac）")

            # 对于解析mac文件功能，额外复制读取mac文件功能的BUFFER
            if function_name == FUNCTION_PARSE_MAC:
                read_mac_folder = self._find_function_folder(sum_folder, solver_type, FUNCTION_READ_MAC)
                source_buffer = read_mac_folder / "BUFFER"
                target_buffer = self.work_folder / "BUFFER"

                if source_buffer.exists():
                    # 删除现有BUFFER并复制
                    if target_buffer.exists():
                        shutil.rmtree(target_buffer)
                    shutil.copytree(source_buffer, target_buffer)
                    self.log_signal.emit(f"   ✓ 复制BUFFER文件夹（从读取mac文件）")

            self.log_signal.emit(f"\n   工作目录准备完成")
            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 准备工作目录失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def _set_work_folder_from_params(self):
        """从参数中设置工作文件夹路径（用于跳过准备步骤时）"""
        solver_type = self.params['solver_type']
        function_name = self.params['function']
        sum_folder = Path(self.params['sum_folder'])

        # 根据功能类型确定工作文件夹
        if function_name == FUNCTION_STRAIN:
            load_convert_folder_name = f"{solver_type}_LoadConversion"
            strain_calc_folder_name = f"{solver_type}_CalcStrain"

            self.load_convert_folder = sum_folder / load_convert_folder_name
            self.strain_calc_folder = sum_folder / strain_calc_folder_name
            self.work_folder = self.load_convert_folder
        else:
            folder_name = self._get_function_folder_name(function_name)
            work_folder_name = f"{solver_type}_{folder_name}"
            self.work_folder = sum_folder / work_folder_name

        self.log_signal.emit(f"   工作文件夹: {self.work_folder}")

    def read_config_template(self, template_name):
        """读取配置文件模板"""
        try:
            import os
            # 获取当前脚本所在目录的上级目录
            current_dir = Path(__file__).parent.parent.parent
            template_path = current_dir / "config_templates" / template_name

            if not template_path.exists():
                self.log_signal.emit(f"\n✗ 错误：找不到配置模板文件: {template_path}")
                return None

            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()

        except Exception as e:
            self.log_signal.emit(f"\n✗ 读取配置模板失败: {str(e)}")
            return None

    def generate_parse_frb(self):
        """生成parse.frb文件（读取mac文件功能）"""
        try:
            self.log_signal.emit(f"\n2. 生成配置文件: parse.frb")

            # 从模板文件读取
            config_content = self.read_config_template("parse.frb.template")
            if config_content is None:
                return None

            config_file = self.work_folder / "parse.frb"
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)

            self.log_signal.emit(f"   ✓ 配置文件已生成")
            return str(config_file)

        except Exception as e:
            self.log_signal.emit(f"\n✗ 生成配置文件失败: {str(e)}")
            return None

    def generate_build_database_frb(self):
        """生成build_database.frb文件（解析mac文件功能）"""
        try:
            solver_type = self.params['solver_type']

            if solver_type == SOLVER_FRBEX:
                # Frbex求解器：使用frbex_build_blade_database.frb和.json
                return self.generate_frbex_build_database()
            else:
                # Farob求解器：使用build_database.frb
                return self.generate_farob_build_database()

        except Exception as e:
            self.log_signal.emit(f"\n✗ 生成配置文件失败: {str(e)}")
            return None

    def generate_farob_build_database(self):
        """生成farob的build_database.frb文件"""
        try:
            self.log_signal.emit(f"\n2. 生成配置文件: build_database.frb")

            # 获取半径参数（从界面传入，单位：mm）
            radius = self.params.get('radius')

            # 检查radius是否存在
            if radius is None:
                self.log_signal.emit(f"   ✗ 错误：未找到叶片半径参数")
                self.log_signal.emit(f"   提示：请确保mac文件中包含 'DEF PARA, RADIUS=xxxxx' 定义")
                return None

            self.log_signal.emit(f"   叶片半径: {radius} mm")
            self.log_signal.emit(f"   叶片长度: {int(radius)/1000:.1f} m")

            # 从模板文件读取并替换radius
            config_content = self.read_config_template("build_database.frb.template")
            if config_content is None:
                return None

            # 替换radius参数
            config_content = config_content.replace("{radius}", str(radius))

            config_file = self.work_folder / "build_database.frb"
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_content)

            self.log_signal.emit(f"   ✓ 配置文件已生成")
            return str(config_file)

        except Exception as e:
            self.log_signal.emit(f"\n✗ 生成配置文件失败: {str(e)}")
            return None

    def generate_frbex_build_database(self):
        """生成frbex的frbex_build_blade_database.frb和.json文件"""
        try:
            self.log_signal.emit(f"\n2. 生成配置文件: frbex_build_blade_database")

            # 获取drmx参数（从界面传入）
            drmx = self.params.get('drmx')

            # 检查drmx是否存在
            if drmx is None:
                self.log_signal.emit(f"   ✗ 错误：未找到截面间距阈值参数")
                self.log_signal.emit(f"   提示：请在界面中输入截面间距阈值")
                return None

            self.log_signal.emit(f"   截面间距阈值: {drmx}")

            # 生成.frb文件
            frb_content = self.read_config_template("frbex_build_blade_database.frb.template")
            if frb_content is None:
                return None

            frb_file = self.work_folder / "frbex_build_blade_database.frb"
            with open(frb_file, 'w', encoding='utf-8') as f:
                f.write(frb_content)

            self.log_signal.emit(f"   ✓ frbex_build_blade_database.frb已生成")

            # 生成.json文件
            json_content = self.read_config_template("frbex_build_blade_database.json.template")
            if json_content is None:
                return None

            # 替换drmx参数
            json_content = json_content.replace("{drmx}", str(drmx))

            json_file = self.work_folder / "frbex_build_blade_database.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                f.write(json_content)

            self.log_signal.emit(f"   ✓ frbex_build_blade_database.json已生成")

            return str(frb_file)

        except Exception as e:
            self.log_signal.emit(f"\n✗ 生成配置文件失败: {str(e)}")
            return None

    def execute_solver(self, config_file):
        """执行求解器"""
        try:
            import subprocess
            import psutil
            import time
            from datetime import timedelta

            solver_path = Path(self.params['solver_path'])
            solver_type = self.params['solver_type']
            solver_exe = solver_path / f"{solver_type}.exe"
            function_name = self.params['function']

            self.log_signal.emit(f"\n3. 启动求解器...")
            self.log_signal.emit(f"   求解器类型: {solver_type}")

            # 构建命令（根据后台运行选项选择 /F6 或 /F6Q）
            background_run = self.params.get('background_run', False)
            # /F6Q = 后台运行（不显示窗口），/F6 = 显示GUI窗口
            f6_option = '/F6Q' if background_run else '/F6'
            command = f'"{solver_exe}" {f6_option} "{config_file}"'
            self.log_signal.emit(f"   命令: {command}")
            if background_run:
                self.log_signal.emit(f"   模式: 后台运行（/F6Q，不显示窗口）")
            else:
                self.log_signal.emit(f"   模式: 前台运行（/F6，显示GUI窗口）")

            # 创建运行命令文件（用于手动调试）
            run_file = self.work_folder / "run.bat"
            with open(run_file, 'w', encoding='utf-8') as f:
                f.write(command)
            self.log_signal.emit(f"   ✓ 已生成运行命令文件: run.bat")

            # 清理FOCUS6数据库缓存文件，避免弹出提示框
            buffer_folder = self.work_folder / "BUFFER"
            self._cleanup_frbex_db_cache(buffer_folder)

            # 记录开始时间
            start_time = time.time()

            # 启动进程（不显示命令行窗口，不捕获输出以提高性能）
            startupinfo = self._get_hidden_window_startupinfo()

            self.process = subprocess.Popen(
                command,
                cwd=str(self.work_folder),
                shell=True,
                stdout=subprocess.DEVNULL,  # 不捕获stdout，避免阻塞
                stderr=subprocess.DEVNULL,  # 不捕获stderr，避免阻塞
                startupinfo=startupinfo
            )

            self.log_signal.emit(f"   ✓ 求解器已启动 (PID: {self.process.pid})")
            self.log_signal.emit(f"   开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

            # 不监控进程，避免轮询开销

            # 等待进程结束
            self.process.wait()

            # 记录结束时间
            end_time = time.time()
            elapsed_time = end_time - start_time

            # 格式化耗时
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.2f} 秒"
            else:
                minutes = int(elapsed_time // 60)
                seconds = elapsed_time % 60
                time_str = f"{minutes} 分 {seconds:.2f} 秒"

            self.log_signal.emit(f"\n   ✓ 求解器进程已结束")
            self.log_signal.emit(f"   结束时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
            self.log_signal.emit(f"   求解耗时: {time_str}")

        except Exception as e:
            self.log_signal.emit(f"\n✗ 执行求解器失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")

    def _run_load_conversion_only(self):
        """单独执行载荷转化（function == FUNCTION_LOAD_CONVERSION）。

        不依赖 farob/frbex 求解器；只需要：
        - modules_path 下有 utils/UserLoadcaseConverter.exe
        - load_file 存在
        - radius 已从 mac 提取

        与 prepare_work_directory 解耦，避免强制检查 solver_path/solver.exe。
        """
        try:
            import shutil
            solver_type = self.params['solver_type']
            sum_folder = Path(self.params['sum_folder'])
            load_convert_folder_name = f"{solver_type}_LoadConversion"
            self.load_convert_folder = sum_folder / load_convert_folder_name

            # 1. 创建/复用载荷转化文件夹（不破坏已有 LOAD.LD1）
            if not self.load_convert_folder.exists():
                self.load_convert_folder.mkdir(parents=True, exist_ok=True)
                self.log_signal.emit(f"   ✓ 创建载荷转化文件夹: {load_convert_folder_name}")
            else:
                self.log_signal.emit(f"   ✓ 使用已存在的载荷转化文件夹")

            # 2. 检查 UserLoadcaseConverter.exe
            modules_path = Path(self.params.get('modules_path', ''))
            converter_exe = modules_path / "utils" / "UserLoadcaseConverter.exe"
            if not converter_exe.exists():
                self.log_signal.emit(f"\n✗ 错误：找不到 UserLoadcaseConverter.exe: {converter_exe}")
                self.log_signal.emit(f"   提示：请在「⚙ 设置」里确认 FOCUS6 Modules 目录配置正确")
                return False
            self.log_signal.emit(f"   ✓ 载荷转换工具检查通过")

            # 3. 检查 load_file
            load_file = Path(self.params.get('load_file', ''))
            if not load_file or not load_file.exists():
                self.log_signal.emit(f"\n✗ 错误：找不到载荷文件: {load_file}")
                self.log_signal.emit(f"   提示：载荷文件应为 7 列格式（x/fx/fy/fz/mx/my/mz）")
                return False
            self.log_signal.emit(f"   ✓ 载荷文件检查通过: {load_file.name}")

            # 4. 委托给 convert_loadcase（auto_perform_strain=False 仅做转化）
            return self.convert_loadcase(auto_perform_strain=False)

        except Exception:
            import traceback
            self.log_signal.emit(f"\n✗ 载荷转化异常:")
            self.log_signal.emit(traceback.format_exc())
            return False

    def convert_loadcase(self, auto_perform_strain=True):
        """应变计算 - 载荷转化

        Args:
            auto_perform_strain: 是否在载荷转化完成后自动执行应变计算（默认True）
                              设置为False时，只执行载荷转化，不执行应变计算
        """
        try:
            import subprocess
            import time
            import shutil
            from datetime import timedelta

            # 初始化载荷转化文件夹（如果还没有初始化）
            if self.load_convert_folder is None:
                solver_type = self.params['solver_type']
                sum_folder = Path(self.params['sum_folder'])
                load_convert_folder_name = f"{solver_type}_LoadConversion"
                self.load_convert_folder = sum_folder / load_convert_folder_name

                # 创建载荷转化文件夹（仅在文件夹不存在时创建，避免破坏已有的LOAD.LD1文件）
                if not self.load_convert_folder.exists():
                    self.load_convert_folder.mkdir(parents=True, exist_ok=True)
                    self.log_signal.emit(f"\n1. 准备工作目录...")
                    self.log_signal.emit(f"   ✓ 创建载荷转化文件夹")
                else:
                    self.log_signal.emit(f"\n1. 准备工作目录...")
                    self.log_signal.emit(f"   ✓ 使用已存在的载荷转化文件夹")

            load_file = Path(self.params['load_file'])
            solver_path = Path(self.params['solver_path'])
            radius = self.params.get('radius')

            # 检查半径参数
            if radius is None:
                self.log_signal.emit(f"\n✗ 错误：未找到叶片半径参数")
                self.log_signal.emit(f"   提示：请先在'读取mac文件'或'解析mac文件'功能中选择mac文件")
                return False

            # 转换半径从mm到m
            radius_m = float(radius) / 1000.0

            self.log_signal.emit(f"\n2. 载荷转化...")
            self.log_signal.emit(f"   载荷文件: {load_file.name}")
            self.log_signal.emit(f"   叶片半径: {radius_m} m")
            self.log_signal.emit(f"   工作文件夹: {self.load_convert_folder.name}")

            # 读取载荷文件
            self.log_signal.emit(f"\n3. 读取载荷文件...")
            self.log_signal.emit(f"   文件路径: {load_file}")
            self.log_signal.emit(f"   文件存在: {load_file.exists()}")

            load_data = self.read_load_file(load_file)
            if load_data is None:
                self.log_signal.emit(f"   ✗ 读取载荷文件失败")
                return False

            self.log_signal.emit(f"   ✓ 读取到 {len(load_data)} 行数据")

            # 生成foculf.txt
            self.log_signal.emit(f"\n4. 生成foculf.txt...")
            foculf_txt_path = self.load_convert_folder / "foculf.txt"
            if not self.generate_foculf_txt(foculf_txt_path, load_data, radius_m):
                self.log_signal.emit(f"   ✗ 生成foculf.txt失败")
                return False

            # 验证foculf.txt是否生成
            if not foculf_txt_path.exists():
                self.log_signal.emit(f"   ✗ foculf.txt文件不存在")
                return False

            self.log_signal.emit(f"   ✓ foculf.txt已生成")
            self.log_signal.emit(f"   文件大小: {foculf_txt_path.stat().st_size} bytes")

            # 执行载荷转换
            self.log_signal.emit(f"\n5. 执行载荷转换...")

            # 记录开始时间
            start_time = time.time()

            # 构建命令（从modules路径派生）
            modules_path = Path(self.params.get('modules_path', ''))
            converter_path = modules_path / "utils"
            converter_exe = converter_path / "UserLoadcaseConverter.exe"
            command = f'"{converter_exe}" foculf.txt'

            self.log_signal.emit(f"   命令: {command}")
            self.log_signal.emit(f"   工作目录: {self.load_convert_folder}")
            self.log_signal.emit(f"   转换工具: {converter_exe}")
            self.log_signal.emit(f"   工具存在: {converter_exe.exists()}")

            # 创建运行命令文件（用于手动调试）
            run_file = self.load_convert_folder / "run.bat"
            with open(run_file, 'w', encoding='utf-8') as f:
                f.write(command)
            self.log_signal.emit(f"   ✓ 已生成运行命令文件: run.bat")

            self.log_signal.emit(f"   开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

            # 执行转换（不显示命令行窗口，不捕获输出以提高性能）
            startupinfo = self._get_hidden_window_startupinfo()
            process = subprocess.Popen(
                command,
                cwd=str(self.load_convert_folder),
                shell=True,
                stdout=subprocess.DEVNULL,  # 不捕获stdout，避免阻塞
                stderr=subprocess.DEVNULL,  # 不捕获stderr，避免阻塞
                startupinfo=startupinfo
            )

            self.log_signal.emit(f"   ✓ 转换进程已启动 (PID: {process.pid})")

            # 等待进程结束
            return_code = process.wait()
            self.log_signal.emit(f"   ✓ 转换进程已结束")
            self.log_signal.emit(f"   返回码: {return_code}")

            # 记录结束时间
            end_time = time.time()
            elapsed_time = end_time - start_time

            # 格式化耗时
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.2f} 秒"
            else:
                minutes = int(elapsed_time // 60)
                seconds = elapsed_time % 60
                time_str = f"{minutes} 分 {seconds:.2f} 秒"

            self.log_signal.emit(f"   结束时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
            self.log_signal.emit(f"   转换耗时: {time_str}")

            # 检查LOAD.LD1文件是否生成
            load_ld1_path = self.load_convert_folder / "LOAD.LD1"
            self.log_signal.emit(f"\n6. 检查输出文件...")
            self.log_signal.emit(f"   期望文件: {load_ld1_path.name}")
            self.log_signal.emit(f"   文件存在: {load_ld1_path.exists()}")

            if not load_ld1_path.exists():
                self.log_signal.emit(f"\n✗ 错误：载荷转换未生成LOAD.LD1文件")
                self.log_signal.emit(f"   期望路径: {load_ld1_path}")

                # 列出文件夹中的所有文件
                if self.load_convert_folder.exists():
                    files = list(self.load_convert_folder.glob('*'))
                    self.log_signal.emit(f"   文件夹中的文件:")
                    for f in files:
                        self.log_signal.emit(f"     - {f.name} ({f.stat().st_size} bytes)")
                return False

            file_size = load_ld1_path.stat().st_size
            self.log_signal.emit(f"   ✓ LOAD.LD1文件已生成")
            self.log_signal.emit(f"   文件大小: {file_size} bytes")

            # 如果设置了自动执行应变计算，则继续执行
            if auto_perform_strain:
                # 继续执行应变计算
                if not self.perform_strain_calculation(load_ld1_path):
                    return False

            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 载荷转化失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def read_load_file(self, load_file):
        """
        读取载荷文件

        支持格式：xlsx, csv, dat, txt
        返回：列表，每行是7个浮点数 [位置, FX, FY, FZ, MX, MY, MZ]
        """
        try:
            import pandas as pd

            file_ext = load_file.suffix.lower()

            if file_ext == '.xlsx':
                # Excel文件
                df = pd.read_excel(load_file)
                data = df.values.tolist()
            elif file_ext == '.csv':
                # CSV文件
                df = pd.read_csv(load_file)
                data = df.values.tolist()
            elif file_ext in ['.dat', '.txt']:
                # 文本文件
                with open(load_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    data = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            values = line.split()
                            if len(values) >= 7:
                                try:
                                    row = [float(v) for v in values[:7]]
                                    data.append(row)
                                except ValueError:
                                    continue
            else:
                self.log_signal.emit(f"   ✗ 不支持的文件格式: {file_ext}")
                return None

            # 验证数据
            if not data or len(data) == 0:
                self.log_signal.emit(f"   ✗ 载荷文件为空")
                return None

            # 验证每行是否有7列
            for i, row in enumerate(data):
                if len(row) < 7:
                    self.log_signal.emit(f"   ✗ 第{i+1}行数据不足7列: {row}")
                    return None

            return data

        except Exception as e:
            self.log_signal.emit(f"   ✗ 读取载荷文件失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"   详细错误:\n{traceback.format_exc()}")
            return None

    def generate_foculf_txt(self, output_path, load_data, radius_m):
        """
        生成foculf.txt文件

        Args:
            output_path: 输出文件路径
            load_data: 载荷数据列表，每行是7个浮点数
            radius_m: 叶片半径（单位：m）

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                # 写入固定格式
                f.write("Loadcase name           LOAD\n")
                f.write("Loadcase description                                              None\n")
                f.write(f"blade_span                            {radius_m}\n")
                f.write("nr_blades                              3\n")
                f.write("blade_root_radius                    0.0\n")
                f.write("start_table load_table\n")

                # 写入数据行（使用分号分隔，无空格）
                for row in load_data:
                    # 确保7列数据
                    if len(row) >= 7:
                        # 格式化数据，保留足够的精度
                        line = ";".join([f"{v:.6g}" for v in row[:7]])
                        f.write(line + "\n")

                f.write("end_table load_table\n")

            return True

        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成foculf.txt失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"   详细错误:\n{traceback.format_exc()}")
            return False

    def perform_strain_calculation(self, load_ld1_path):
        """执行应变计算"""
        try:
            import subprocess
            import shutil
            import time

            solver_path = Path(self.params['solver_path'])
            solver_type = self.params['solver_type']
            radius_mm = self.params.get('radius')
            zspan_file = Path(self.params.get('zspan_file', ''))

            self.log_signal.emit(f"\n6. 开始应变计算...")
            self.log_signal.emit(f"   工作文件夹: {self.strain_calc_folder.name}")
            self.log_signal.emit(f"   求解器类型: {solver_type}")

            # 根据求解器类型执行不同的流程
            if solver_type == SOLVER_FRBEX:
                return self.perform_frbex_strain_calculation(load_ld1_path, solver_path)
            else:
                return self.perform_farob_strain_calculation(load_ld1_path, solver_path, radius_mm, zspan_file)

        except Exception as e:
            self.log_signal.emit(f"\n✗ 应变计算失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def perform_farob_strain_calculation(self, load_ld1_path, solver_path, radius_mm, zspan_file):
        """Farob求解器应变计算"""
        try:
            import subprocess
            import shutil
            import time

            # 读取ZSPAN文件
            self.log_signal.emit(f"\n7. 读取展向位置文件（ZSPAN）...")
            zspan_data = self.read_zspan_file(zspan_file)
            if zspan_data is None:
                return False
            self.log_signal.emit(f"   ✓ 读取到 {len(zspan_data)} 个展向位置")

            # 生成配置文件
            self.log_signal.emit(f"\n8. 生成配置文件...")

            # 生成farob_geometry.mac
            farob_geom_path = self.strain_calc_folder / "farob_geometry.mac"
            if not self.generate_farob_geometry_mac(farob_geom_path):
                return False
            self.log_signal.emit(f"   ✓ farob_geometry.mac")

            # 生成location.frb
            location_frb_path = self.strain_calc_folder / "location.frb"
            if not self.generate_location_frb(location_frb_path, zspan_data):
                return False
            self.log_signal.emit(f"   ✓ location.frb")

            # 生成points.def
            points_def_path = self.strain_calc_folder / "points.def"
            if not self.generate_points_def(points_def_path):
                return False
            self.log_signal.emit(f"   ✓ points.def")

            # 生成structural_analysis.frb
            structural_frb_path = self.strain_calc_folder / "structural_analysis.frb"
            radius_m = float(radius_mm) / 1000.0
            if not self.generate_structural_analysis_frb(structural_frb_path, radius_m):
                return False
            self.log_signal.emit(f"   ✓ structural_analysis.frb")

            # 执行应变计算
            self.log_signal.emit(f"\n9. 执行应变计算...")

            # 记录开始时间
            start_time = time.time()

            # 构建命令（根据后台运行选项选择 /F6 或 /F6Q）
            background_run = self.params.get('background_run', False)
            f6_option = '/F6Q' if background_run else '/F6'
            solver_exe = solver_path / "farob.exe"
            command = f'"{solver_exe}" {f6_option} "{structural_frb_path.name}"'
            self.log_signal.emit(f"   命令: {command}")
            if background_run:
                self.log_signal.emit(f"   模式: 后台运行（/F6Q，不显示窗口）")
            self.log_signal.emit(f"   工作目录: {self.strain_calc_folder}")

            # 创建运行命令文件（用于手动调试）
            run_file = self.strain_calc_folder / "run.bat"
            with open(run_file, 'w', encoding='utf-8') as f:
                f.write(command)
            self.log_signal.emit(f"   ✓ 已生成运行命令文件: run.bat")

            # 清理FOCUS6数据库缓存文件，避免弹出提示框
            buffer_folder = self.strain_calc_folder / "BUFFER"
            self._cleanup_frbex_db_cache(buffer_folder)

            self.log_signal.emit(f"   开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

            # 启动进程（不显示命令行窗口，不捕获输出以提高性能）
            startupinfo = self._get_hidden_window_startupinfo()
            process = subprocess.Popen(
                command,
                cwd=str(self.strain_calc_folder),
                shell=True,
                stdout=subprocess.DEVNULL,  # 不捕获stdout，避免阻塞
                stderr=subprocess.DEVNULL,  # 不捕获stderr，避免阻塞
                startupinfo=startupinfo
            )

            # 不监控进程，避免轮询开销

            # 等待进程结束
            process.wait()

            # 记录结束时间
            end_time = time.time()
            elapsed_time = end_time - start_time

            # 格式化耗时
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.2f} 秒"
            else:
                minutes = int(elapsed_time // 60)
                seconds = elapsed_time % 60
                time_str = f"{minutes} 分 {seconds:.2f} 秒"

            self.log_signal.emit(f"\n   ✓ 应变计算完成")
            self.log_signal.emit(f"   结束时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
            self.log_signal.emit(f"   计算耗时: {time_str}")

            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ Farob应变计算失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def perform_frbex_strain_calculation(self, load_ld1_path, solver_path):
        """Frbex求解器应变计算"""
        try:
            import subprocess
            import shutil
            import time
            import json

            self.log_signal.emit(f"\n7. 读取展向位置文件（ZSPAN）...")
            zspan_file = Path(self.params.get('zspan_file', ''))
            zspan_data = self.read_zspan_file(zspan_file)
            if zspan_data is None:
                return False
            self.log_signal.emit(f"   ✓ 读取到 {len(zspan_data)} 个展向位置")

            # 生成配置文件
            self.log_signal.emit(f"\n8. 生成配置文件...")

            # 生成frbex_structural_analysis.frb
            frb_content = self.read_config_template("frbex_structural_analysis.frb.template")
            if frb_content is None:
                return False

            frb_file = self.strain_calc_folder / "frbex_structural_analysis.frb"
            with open(frb_file, 'w', encoding='utf-8') as f:
                f.write(frb_content)
            self.log_signal.emit(f"   ✓ frbex_structural_analysis.frb")

            # 生成frbex_structural_analysis.json
            json_content = self.read_config_template("frbex_structural_analysis.json.template")
            if json_content is None:
                return False

            # 格式化s参数（展向位置列表，单位：mm）
            s_positions_str = json.dumps(zspan_data)

            # 替换json中的占位符
            work_folder_str = str(self.strain_calc_folder).replace('\\', '/')
            json_content = json_content.replace("{s_positions}", s_positions_str)
            json_content = json_content.replace("{work_folder}", work_folder_str)

            json_file = self.strain_calc_folder / "frbex_structural_analysis.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                f.write(json_content)
            self.log_signal.emit(f"   ✓ frbex_structural_analysis.json")

            # 执行应变计算
            self.log_signal.emit(f"\n9. 执行应变计算...")

            # 记录开始时间
            start_time = time.time()

            # 构建命令（根据后台运行选项选择 /F6 或 /F6Q）
            background_run = self.params.get('background_run', False)
            f6_option = '/F6Q' if background_run else '/F6'
            solver_exe = solver_path / "frbex.exe"
            command = f'"{solver_exe}" {f6_option} "{frb_file.name}"'
            self.log_signal.emit(f"   命令: {command}")
            if background_run:
                self.log_signal.emit(f"   模式: 后台运行（/F6Q，不显示窗口）")
            self.log_signal.emit(f"   工作目录: {self.strain_calc_folder}")

            # 创建运行命令文件（用于手动调试）
            run_file = self.strain_calc_folder / "run.bat"
            with open(run_file, 'w', encoding='utf-8') as f:
                f.write(command)
            self.log_signal.emit(f"   ✓ 已生成运行命令文件: run.bat")

            # 清理FOCUS6数据库缓存文件，避免弹出提示框
            buffer_folder = self.strain_calc_folder / "BUFFER"
            self._cleanup_frbex_db_cache(buffer_folder)

            self.log_signal.emit(f"   开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

            # 启动进程（不显示命令行窗口，不捕获输出以提高性能）
            startupinfo = self._get_hidden_window_startupinfo()
            process = subprocess.Popen(
                command,
                cwd=str(self.strain_calc_folder),
                shell=True,
                stdout=subprocess.DEVNULL,  # 不捕获stdout，避免阻塞
                stderr=subprocess.DEVNULL,  # 不捕获stderr，避免阻塞
                startupinfo=startupinfo
            )

            # 不监控进程，避免轮询开销

            # 等待进程结束
            process.wait()

            # 记录结束时间
            end_time = time.time()
            elapsed_time = end_time - start_time

            # 格式化耗时
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.2f} 秒"
            else:
                minutes = int(elapsed_time // 60)
                seconds = elapsed_time % 60
                time_str = f"{minutes} 分 {seconds:.2f} 秒"

            self.log_signal.emit(f"\n   ✓ 应变计算完成")
            self.log_signal.emit(f"   结束时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
            self.log_signal.emit(f"   计算耗时: {time_str}")

            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ Frbex应变计算失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def read_zspan_file(self, zspan_file):
        """
        读取展向位置文件（ZSPAN）

        支持格式：xlsx, csv, dat, txt
        返回：列表，每个元素是展向位置（单位：mm）

        单位检测：
        - 如果最大值 > 200，单位是 mm，不转换
        - 如果最大值 ≤ 200，单位是 m，转换为 mm
        """
        try:
            import pandas as pd

            file_ext = zspan_file.suffix.lower()

            if file_ext == '.xlsx':
                # Excel文件
                df = pd.read_excel(zspan_file)
                data = df.iloc[:, 0].values.tolist()  # 读取第一列
            elif file_ext == '.csv':
                # CSV文件
                df = pd.read_csv(zspan_file)
                data = df.iloc[:, 0].values.tolist()
            elif file_ext in ['.dat', '.txt']:
                # 文本文件
                with open(zspan_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                    data = []
                    for line in lines:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            try:
                                value = float(line)
                                data.append(value)
                            except ValueError:
                                continue
            else:
                self.log_signal.emit(f"   ✗ 不支持的文件格式: {file_ext}")
                return None

            # 验证数据
            if not data or len(data) == 0:
                self.log_signal.emit(f"   ✗ 展向位置文件为空")
                return None

            # 检测单位并转换（统一转换为mm）
            max_value = max(data)
            if max_value > 200:
                # 单位是 mm，不转换
                self.log_signal.emit(f"   检测到单位为 mm")
            else:
                # 单位是 m，转换为 mm
                self.log_signal.emit(f"   检测到单位为 m，转换为 mm")
                data = [v * 1000.0 for v in data]

            return data

        except Exception as e:
            self.log_signal.emit(f"   ✗ 读取展向位置文件失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"   详细错误:\n{traceback.format_exc()}")
            return None

    def generate_farob_geometry_mac(self, output_path):
        """生成farob_geometry.mac文件"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("USE MACRO blade_geometry.mac\n")
            return True
        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成farob_geometry.mac失败: {str(e)}")
            return False

    def generate_location_frb(self, output_path, zspan_data):
        """
        生成location.frb文件

        Args:
            output_path: 输出文件路径
            zspan_data: 展向位置列表（单位：mm）
        """
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("### This file is generated by FOCUS, do not alter manually.\n")
                f.write("### modify the Global file table blade_stations instead\n")

                # 为每个展向位置生成ACTIVE Z-VALUE和USE MACRO行
                for z_value in zspan_data:
                    f.write(f"ACTIVE Z-VALUE      {z_value:.3f}\n")
                    f.write("USE MACRO MACROS\\SECTION.MAC\n")

            return True
        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成location.frb失败: {str(e)}")
            return False

    def generate_points_def(self, output_path):
        """生成points.def文件"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("* Fatigue calculation:\n")
                f.write("####### initial settings #########################################\n")
                f.write("STRESS FACTORS       1           1        1\n")
                f.write("PARAMETER BINSIZE        0.1\n")
                f.write("##################################################################\n")
                f.write("DEF STRING $opt     /P/F/X\n")

            return True
        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成points.def失败: {str(e)}")
            return False

    def generate_structural_analysis_frb(self, output_path, radius_m):
        """
        生成structural_analysis.frb文件

        Args:
            output_path: 输出文件路径
            radius_m: 叶片半径（单位：m）
        """
        try:
            radius_mm = int(radius_m * 1000)

            config_content = f"""####################################
##This file is generated by FOCUS ##
##Do not alter manually           ##
####################################
DEF STRING $DO_BUCK             no
PARAMETER BLADE               1
PARAMETER V                   0
SET BLADE ROOT               0
PARAMETER RADIUS          {radius_mm}
DEF GENERATOR       RADIUS    /DG     0.0
DEF STRING TITLE              blade
PARAMETER strain                         1
PARAMETER strainplt                      0
PLOTTER NONE
PARAMETER XMIN                    -2000.
PARAMETER XMAX                      2000.
PARAMETER YMIN                  -2000.
PARAMETER %meta                  0.85
SERVICE LIFE          1.0
### fixed parameters:###
SURFACE NAME `TITLE`
### Miscellanious plot settings.
PARAMETER FMIN      223.
PARAMETER FMAX      300.
PARAMETER MMIN      -500.
PARAMETER MMAX      1000.
PARAMETER OMMIN     0.
PARAMETER OMMAX     3.
PARAMETER AZMIN     0.
PARAMETER AZMAX     6.
PARAMETER PIMIN     0.
PARAMETER PIMAX     15.
PARAMETER FTICK     100.
PARAMETER FSUBTICK  10
PARAMETER MTICK     100.
PARAMETER MSUBTICK  5
PARAMETER CTICK     1
PARAMETER CSUBTICK  2
PARAMETER XSPMIN    1.
PARAMETER XSPMAX    1.E10
PARAMETER YSPMIN    0
PARAMETER YSPMAX    40
PARAMETER GLDFCT    1.0
DEF STRING $W
**************************** LOAD File Definition****************************
DEF STRING LoadType    fatigue
DEF FOCUS4 SIGNALS
 path name        : .
 file type        : binary
 dead load factor : 0.0
 save load element: FZ_L
 save load element: MX_L
 save load element: MY_L
 save load element: FX_B
 save load element: FY_B
 save load element: MZ_B
 file extension   : .LD1
 load case        : LOAD,times per year =
END DEF
**************************** FATIGUE CALCULATION ****************************
PROCESS IF EXIST strain
PROCESS IF strain .EQ. 1

TEXT TO FILE /PR    buffer\\strain_summary_BLD.txt
# Blade `TITLE`
# summary normal and shear strain analyses
#
# n=normal strain, s= shear strain.
#In case of a material the reserve factor is given, otherwise the strain.
#
#  R   norm/shr  material     minimum   maximum        lc_min   istep_min   lc_max    istep_max
END TEXT TO FILE
END PROCESS IF
END PROCESS IF
* Start of the fatigue calculation:
USE MACRO LOCATION.FRB
PRINT TIME
FINISH  /nopause
"""
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(config_content)

            return True
        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成structural_analysis.frb失败: {str(e)}")
            return False

    def perform_frequency_calculation(self):
        """执行频率计算（频率计算统一使用farob求解器）"""
        try:
            import subprocess
            import time

            solver_path = Path(self.params['solver_path'])
            solver_type = self.params['solver_type']

            # 频率计算统一使用farob求解器
            solver_exe = solver_path / "farob.exe"

            self.log_signal.emit(f"\n2. 生成配置文件...")
            self.log_signal.emit(f"   求解器类型: {solver_type}")
            self.log_signal.emit(f"   频率计算使用: farob.exe")

            # 根据求解器类型生成对应的配置文件
            if solver_type == SOLVER_FRBEX:
                # frbex求解器：使用 frbex_eigenfrequencies.frb
                config_path = self.work_folder / "frbex_eigenfrequencies.frb"
                if not self.generate_frbex_eigenfrequencies_frb(config_path):
                    return False
                self.log_signal.emit(f"   ✓ frbex_eigenfrequencies.frb")
            else:
                # farob求解器：使用 eigenfr.frb
                config_path = self.work_folder / "eigenfr.frb"
                if not self.generate_eigenfr_frb(config_path):
                    return False
                self.log_signal.emit(f"   ✓ eigenfr.frb")

            # 生成 farob_geometry.mac
            farob_geom_path = self.work_folder / "farob_geometry.mac"
            if not self.generate_farob_geometry_mac(farob_geom_path):
                return False
            self.log_signal.emit(f"   ✓ farob_geometry.mac")

            # 执行求解器（统一使用farob.exe）
            self.log_signal.emit(f"\n3. 启动求解器...")

            # 记录开始时间
            start_time = time.time()

            # 构建命令（根据后台运行选项选择 /F6 或 /F6Q）
            background_run = self.params.get('background_run', False)
            f6_option = '/F6Q' if background_run else '/F6'
            command = f'"{solver_exe}" {f6_option} "{config_path.name}"'
            self.log_signal.emit(f"   命令: {command}")
            if background_run:
                self.log_signal.emit(f"   模式: 后台运行（/F6Q，不显示窗口）")
            self.log_signal.emit(f"   工作目录: {self.work_folder}")

            # 创建运行命令文件（用于手动调试）
            run_file = self.work_folder / "run.bat"
            with open(run_file, 'w', encoding='utf-8') as f:
                f.write(command)
            self.log_signal.emit(f"   ✓ 已生成运行命令文件: run.bat")

            self.log_signal.emit(f"   开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

            # 执行计算（不显示命令行窗口，不捕获输出以提高性能）
            startupinfo = self._get_hidden_window_startupinfo()
            process = subprocess.Popen(
                command,
                cwd=str(self.work_folder),
                shell=True,
                stdout=subprocess.DEVNULL,  # 不捕获stdout，避免阻塞
                stderr=subprocess.DEVNULL,  # 不捕获stderr，避免阻塞
                startupinfo=startupinfo
            )

            # 等待进程结束
            process.wait()

            # 记录结束时间
            end_time = time.time()
            elapsed_time = end_time - start_time

            # 格式化耗时
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.2f} 秒"
            else:
                minutes = int(elapsed_time // 60)
                seconds = elapsed_time % 60
                time_str = f"{minutes} 分 {seconds:.2f} 秒"

            self.log_signal.emit(f"   ✓ 频率计算完成")
            self.log_signal.emit(f"   结束时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
            self.log_signal.emit(f"   计算耗时: {time_str}")

            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 频率计算失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def generate_eigenfr_frb(self, output_path):
        """
        生成eigenfr.frb文件

        Args:
            output_path: 输出文件路径

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            config_content = """####################################
##This file is generated by FOCUS ##
##Do not alter manually           ##
####################################
DEF STRING TITLE              blade
### fixed parameters:###
DEF STRING TITLE  blade
SURFACE NAME blade
PARAMETER plotmode      0
FILE NAME            FREQUENCY TABLE
freq_coupled.txt
EIGEN FR/ms/PR      0         40
PROCESS IF plotmode.EQ.1
USE MACRO macros/plotCfreq.mac
END PROCESS IF1
FILE NAME            FREQUENCY TABLE
freq_uncoupled.txt
EIGEN FR/u/ms/PR    0         40
PROCESS IF plotmode.EQ.1
USE MACRO macros/plotUCfreq.mac
END PROCESS IF1
FINISH  /nopause
"""
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(config_content)

            return True

        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成eigenfr.frb失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"   详细错误:\n{traceback.format_exc()}")
            return False

    def generate_frbex_eigenfrequencies_frb(self, output_path):
        """
        生成frbex_eigenfrequencies.frb文件（frbex求解器频率计算配置文件）

        Args:
            output_path: 输出文件路径

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            # 直接读取模板文件并写入（模板文件已经包含完整内容，无需替换占位符）
            config_content = self.read_config_template("frbex_eigenfrequencies.frb.template")
            if config_content is None:
                return False

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(config_content)

            return True

        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成frbex_eigenfrequencies.frb失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"   详细错误:\n{traceback.format_exc()}")
            return False

    def perform_tip_deflection_calculation(self):
        """执行叶尖挠度计算（仅frbex求解器）"""
        try:
            import subprocess
            import shutil
            import time

            solver_path = Path(self.params['solver_path'])
            solver_type = self.params['solver_type']

            # 检查求解器类型
            if solver_type != SOLVER_FRBEX:
                self.log_signal.emit(f"\n✗ 错误：叶尖挠度计算仅支持frbex求解器")
                self.log_signal.emit(f"   当前求解器: {solver_type}")
                return False

            self.log_signal.emit(f"\n2. 生成配置文件...")
            self.log_signal.emit(f"   求解器类型: {solver_type}")

            # 生成配置文件（不需要读取ZSPAN，s字段为空数组）
            self.log_signal.emit(f"\n3. 生成配置文件...")

            # 生成 frbex_tip_deflection.frb
            frb_content = self.read_config_template("frbex_tip_deflection.frb.template")
            if frb_content is None:
                return False

            frb_file = self.work_folder / "frbex_tip_deflection.frb"
            with open(frb_file, 'w', encoding='utf-8') as f:
                f.write(frb_content)
            self.log_signal.emit(f"   ✓ frbex_tip_deflection.frb")

            # 生成 frbex_tip_deflection.json（s字段为空数组，不需要替换）
            json_content = self.read_config_template("frbex_tip_deflection.json.template")
            if json_content is None:
                return False

            # 注意：模板中s字段已设为空数组[]，不需要进行s_positions_m替换

            json_file = self.work_folder / "frbex_tip_deflection.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                f.write(json_content)
            self.log_signal.emit(f"   ✓ frbex_tip_deflection.json (s字段为空数组)")

            # 执行叶尖挠度计算
            self.log_signal.emit(f"\n4. 执行叶尖挠度计算...")

            # 记录开始时间
            start_time = time.time()

            # 构建命令（根据后台运行选项选择 /F6 或 /F6Q）
            background_run = self.params.get('background_run', False)
            f6_option = '/F6Q' if background_run else '/F6'
            solver_exe = solver_path / "frbex.exe"
            command = f'"{solver_exe}" {f6_option} "{frb_file.name}"'
            self.log_signal.emit(f"   命令: {command}")
            if background_run:
                self.log_signal.emit(f"   模式: 后台运行（/F6Q，不显示窗口）")
            self.log_signal.emit(f"   工作目录: {self.work_folder}")

            # 创建运行命令文件（用于手动调试）
            run_file = self.work_folder / "run.bat"
            with open(run_file, 'w', encoding='utf-8') as f:
                f.write(command)
            self.log_signal.emit(f"   ✓ 已生成运行命令文件: run.bat")

            self.log_signal.emit(f"   开始时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))}")

            # 启动进程（不显示命令行窗口，不捕获输出以提高性能）
            startupinfo = self._get_hidden_window_startupinfo()
            process = subprocess.Popen(
                command,
                cwd=str(self.work_folder),
                shell=True,
                stdout=subprocess.DEVNULL,  # 不捕获stdout，避免阻塞
                stderr=subprocess.DEVNULL,  # 不捕获stderr，避免阻塞
                startupinfo=startupinfo
            )

            # 不监控进程，避免轮询开销

            # 等待进程结束
            process.wait()

            # 记录结束时间
            end_time = time.time()
            elapsed_time = end_time - start_time

            # 格式化耗时
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.2f} 秒"
            else:
                minutes = int(elapsed_time // 60)
                seconds = elapsed_time % 60
                time_str = f"{minutes} 分 {seconds:.2f} 秒"

            self.log_signal.emit(f"\n   ✓ 叶尖挠度计算完成")
            self.log_signal.emit(f"   结束时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
            self.log_signal.emit(f"   计算耗时: {time_str}")

            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 叶尖挠度计算失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def check_and_warn_buffer_empty(self):
        """
        检查BUFFER文件夹是否为空，并给出友好提示

        仅用于"解析mac文件"功能

        Returns:
            bool: 总是返回True（允许继续执行）
        """
        # 只对解析mac文件功能进行检查
        if self.params['function'] != FUNCTION_PARSE_MAC:
            return True

        # 检查BUFFER文件夹是否存在
        buffer_folder = self.work_folder / "BUFFER"
        if not buffer_folder.exists():
            # BUFFER文件夹不存在，不需要警告
            return True

        # 检查BUFFER文件夹是否为空
        buffer_files = list(buffer_folder.glob('*'))
        # 过滤掉 .gitkeep 等隐藏文件
        buffer_files = [f for f in buffer_files if not f.name.startswith('.')]

        if buffer_files:
            # BUFFER不为空，正常情况
            return True

        # BUFFER为空，给出警告
        solver_type = self.params['solver_type']

        self.log_signal.emit(f"\n{LOG_SEPARATOR}")
        self.log_signal.emit(f"⚠️  警告：BUFFER文件夹为空")
        self.log_signal.emit(f"{LOG_SEPARATOR}")

        if solver_type == SOLVER_FRBEX:
            self.log_signal.emit(f"当前使用的是 frbex 求解器")
            self.log_signal.emit(f"")
            self.log_signal.emit(f"说明：")
            self.log_signal.emit(f"  • frbex求解器构建blade_db时，通常需要BUFFER数据")
            self.log_signal.emit(f"  • BUFFER数据由'读取mac文件'功能生成")
            self.log_signal.emit(f"  • 如果BUFFER为空，求解器可能会失败")
            self.log_signal.emit(f"")
            self.log_signal.emit(f"建议：")
            self.log_signal.emit(f"  1. 先执行'读取mac文件'功能生成BUFFER数据")
            self.log_signal.emit(f"  2. 然后再执行'解析mac文件'功能")
            self.log_signal.emit(f"")
            self.log_signal.emit(f"是否继续执行？")
            self.log_signal.emit(f"  • 如果继续，求解器可能会报错")
            self.log_signal.emit(f"  • 如果失败，请按建议先执行'读取mac文件'功能")
        else:  # SOLVER_FAROB
            self.log_signal.emit(f"当前使用的是 farob 求解器")
            self.log_signal.emit(f"")
            self.log_signal.emit(f"说明：")
            self.log_signal.emit(f"  • farob求解器可能会直接读取blade_geometry.mac文件")
            self.log_signal.emit(f"  • 即使BUFFER为空，也有可能成功")
            self.log_signal.emit(f"")
            self.log_signal.emit(f"提示：")
            self.log_signal.emit(f"  • 如果求解器失败，请先执行'读取mac文件'功能")

        self.log_signal.emit(f"{LOG_SEPARATOR}")
        self.log_signal.emit(f"")

        # 允许继续执行
        return True

    def perform_weight_calculation(self):
        """执行重量计算（读取blade_db.xls的MASS列最后一行得到总重量）"""
        try:
            import pandas as pd

            solver_type = self.params['solver_type']
            sum_folder = Path(self.params['sum_folder'])
            function_name = self.params['function']

            self.log_signal.emit(f"\n执行重量计算...")

            # 1. 查找blade_db.xls文件
            parse_mac_folder = self._find_function_folder(sum_folder, solver_type, FUNCTION_PARSE_MAC)
            blade_db_file = parse_mac_folder / "blade_db.xls"

            if not blade_db_file.exists():
                self.log_signal.emit(f"\n✗ 错误：找不到blade_db.xls文件")
                self.log_signal.emit(f"   路径：{blade_db_file}")
                self.log_signal.emit(f"   提示：请先执行'解析mac文件'功能")
                return False

            self.log_signal.emit(f"   ✓ 找到blade_db.xls文件")
            self.log_signal.emit(f"\n读取blade_db.xls...")
            try:
                df = pd.read_csv(blade_db_file, sep='\t', encoding='utf-8')
                self.log_signal.emit(f"   ✓ 成功读取文件")
                self.log_signal.emit(f"   数据维度: {df.shape[0]} 个截面 × {df.shape[1]} 个属性")
            except Exception as e:
                self.log_signal.emit(f"\n✗ 读取文件失败: {str(e)}")
                self.log_signal.emit(f"   提示：请确保文件是制表符分隔的文本格式")
                return False

            # 4. 查找Mass列（不区分大小写）
            mass_column = None
            mass_col_name = None

            for possible_name in ['MASS', 'Mass', 'mass', 'MASS [kg/m]', 'Mass [kg/m]', 'mass [kg/m]']:
                if possible_name in df.columns:
                    mass_column = df[possible_name]
                    mass_col_name = possible_name
                    break

            if mass_column is None:
                # 如果还是找不到，显示可用列并失败
                self.log_signal.emit(f"\n✗ 错误：blade_db.xls中没有找到Mass/MASS/mass列")
                self.log_signal.emit(f"   可用列：{', '.join(df.columns.tolist())}")
                return False

            self.log_signal.emit(f"   ✓ 找到{mass_col_name}列")

            # 5. 读取Mass列最后一行数据（总重量）
            self.log_signal.emit(f"\n读取总重量...")

            # 清理数据：删除NaN值并转换为数值
            mass_values = mass_column.dropna()
            mass_values = pd.to_numeric(mass_values, errors='coerce').dropna()

            if len(mass_values) == 0:
                self.log_signal.emit(f"\n✗ 错误：{mass_col_name}列没有有效数据")
                return False

            # 读取最后一行数据（总重量）
            total_weight = mass_values.iloc[-1]

            self.log_signal.emit(f"   ✓ 数据截面数: {len(mass_values)}")
            self.log_signal.emit(f"   ✓ 叶片总重量: {total_weight:.2f} kg")

            # 6. 保存到CSV文件（如果需要）
            if self.generate_csv:
                import csv
                csv_file = work_folder / "重量统计.csv"

                # 使用UTF-8 with BOM编码，Excel才能正确识别中文
                with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # 写入表头（只有ID号和重量）
                    writer.writerow(['ID号', '重量'])
                    # 写入数据
                    writer.writerow([1, f'{total_weight:.2f}'])

                self.log_signal.emit(f"   ✓ 已保存至: {csv_file.name}")
                self.log_signal.emit(f"   路径: {csv_file}")
            self.log_signal.emit(f"\n✓ 重量计算完成")
            self.log_signal.emit(f"   叶片总重量: {total_weight:.2f} kg")

            # 返回重量值，供后续步骤使用
            return total_weight

        except Exception as e:
            self.log_signal.emit(f"\n✗ 重量计算失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return None
