#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
一键运行工作线程 - 串行版本

依次执行 FOCUS6 计算步骤（任一步失败立即停止）：
1. 读取 mac 文件
2. 解析 mac 文件
3. 计算重量
4. 计算频率
5. 计算应变（含载荷转化，需提供 zspan + 载荷文件）
6. 计算叶尖挠度（仅 frbex 求解器）
"""

import re
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

from .solver_config import (
    SOLVER_FRBEX, FUNCTION_READ_MAC, FUNCTION_PARSE_MAC,
    FUNCTION_WEIGHT, FUNCTION_FREQUENCY, FUNCTION_STRAIN,
    FUNCTION_TIP_DEFLECTION, LOG_SEPARATOR, DEFAULT_MODULES_PATH,
    FRBEX_DEFAULT_DRMX, FUNCTION_FOLDER_NAMES
)


class OneClickRunThread(QThread):
    """一键运行工作线程"""

    # 信号定义
    log_signal = pyqtSignal(str)  # 日志信号
    progress_signal = pyqtSignal(int, int)  # 进度信号（当前步骤，总步骤）
    step_signal = pyqtSignal(str)  # 步骤名称信号
    finished_signal = pyqtSignal(bool, str)  # 完成信号（是否成功，消息）

    def __init__(self, params, summarize_only=False):
        super().__init__()
        self.params = params
        self.summarize_only = summarize_only  # True=仅汇总数据，False=完整计算
        self.total_steps = 6  # 总步骤数
        self.current_step = 0

    def run(self):
        """主流程 - 串行版本（依次执行 6 步）"""
        import time

        # 创建日志文件
        log_file = None
        try:
            # 记录开始时间
            self.start_time = time.time()

            # 提取基本参数
            solver_type = self.params.get('solver_type', SOLVER_FRBEX)
            mac_file = Path(self.params['mac_file'])
            base_sum_folder = Path(self.params['sum_folder'])
            modules_path = Path(self.params.get('modules_path', DEFAULT_MODULES_PATH))
            # 注意：frbex求解器在farob文件夹里，所以solver_path统一指向farob
            solver_path = modules_path / "farob"
            zspan_file = Path(self.params.get('zspan_file', ''))
            load_file = Path(self.params.get('load_file', ''))
            background_run = self.params.get('background_run', False)
            drmx = self.params.get('drmx', FRBEX_DEFAULT_DRMX)
            radius = self.params.get('radius', '')

            # 首先创建"opt"文件夹（必须在创建日志文件之前）
            optimization_folder = base_sum_folder / "opt"
            if not optimization_folder.exists():
                optimization_folder.mkdir(parents=True, exist_ok=True)

            # 生成日志文件名：YYYY-MM-DD_HH-MM-SS_一键运行.log
            start_time_str = time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(self.start_time))
            log_filename = f"{start_time_str}_一键运行.log"
            log_file_path = optimization_folder / log_filename

            # 打开日志文件
            log_file = open(log_file_path, 'w', encoding='utf-8')

            # 创建一个写入文件的槽函数
            def write_to_file(message):
                """写入日志到文件（立即写入）"""
                if log_file:
                    log_file.write(message + '\n')
                    log_file.flush()

            # 连接文件写入槽到log_signal
            # 使用DirectConnection确保立即写入，不排队
            from PyQt5.QtCore import Qt
            self.log_signal.connect(write_to_file, Qt.DirectConnection)

            self.log_signal.emit(LOG_SEPARATOR)
            self.log_signal.emit(f"开始一键运行 - 串行版本")
            self.log_signal.emit(f"日志文件: {log_filename}")
            self.log_signal.emit(f"开始时间: {start_time_str}")
            self.log_signal.emit(LOG_SEPARATOR)

            self.log_signal.emit(f"求解器类型: {solver_type}")
            self.log_signal.emit(f"求解器路径: {solver_path}")
            self.log_signal.emit(LOG_SEPARATOR)

            self.log_signal.emit(f"✓ 创建输出文件夹: {optimization_folder}")
            self.log_signal.emit(f"  所有计算结果将保存在此文件夹下")
            self.log_signal.emit(LOG_SEPARATOR)

            # 检查是否为汇总模式
            if self.summarize_only:
                # 汇总模式：跳过所有计算，直接汇总数据
                self.log_signal.emit(f"✓ 汇总模式：仅汇总已有数据，不重新运行计算")
                self.log_signal.emit(LOG_SEPARATOR)

                # 直接跳转到汇总数据部分
                success = self._summarize_all_data(optimization_folder, solver_type)

                # 关闭日志文件
                if log_file:
                    log_file.close()

                # 发送完成信号
                if success:
                    self.finished_signal.emit(True, "✓ 数据汇总完成！")
                else:
                    self.finished_signal.emit(False, "✗ 数据汇总失败")
                return

            # 读取mac文件获取半径
            if not radius:
                radius = self._extract_radius_from_mac(mac_file)

            # 检查应变计算的前置条件（zspan + 载荷文件必须同时存在）
            has_strain_calculation = bool(zspan_file) and zspan_file.exists() and bool(load_file) and load_file.exists()
            if not has_strain_calculation:
                self.log_signal.emit(f"\n⚠ 提示: 未提供 zspan 文件或载荷文件，步骤 5（应变）和步骤 6（叶尖挠度）的依赖会缺失")
                self.log_signal.emit(f"     应变计算将被跳过；叶尖挠度仍可尝试独立执行（仅 frbex）")

            # ========== 步骤 1/6：读取 mac 文件 ==========
            if not self._run_step(1, "读取mac文件", FUNCTION_READ_MAC, {
                'solver_type': solver_type,
                'mac_solver_type': solver_type,
                'function': FUNCTION_READ_MAC,
                'modules_path': str(modules_path),
                'solver_path': str(solver_path),
                'sum_folder': str(optimization_folder),
                'mac_file': str(mac_file),
                'radius': radius,
                'background_run': background_run
            }):
                self._finish(False, "步骤 1 失败：读取 mac 文件")
                return

            # ========== 步骤 2/6：解析 mac 文件 ==========
            if not self._run_step(2, "解析mac文件", FUNCTION_PARSE_MAC, {
                'solver_type': solver_type,
                'mac_solver_type': solver_type,
                'function': FUNCTION_PARSE_MAC,
                'modules_path': str(modules_path),
                'solver_path': str(solver_path),
                'sum_folder': str(optimization_folder),
                'mac_file': str(mac_file),
                'radius': radius,
                'drmx': drmx,
                'background_run': background_run
            }):
                self._finish(False, "步骤 2 失败：解析 mac 文件")
                return

            # ========== 步骤 3/6：计算重量 ==========
            if not self._run_step(3, "计算重量", FUNCTION_WEIGHT, {
                'solver_type': solver_type,
                'function': FUNCTION_WEIGHT,
                'modules_path': str(modules_path),
                'sum_folder': str(optimization_folder),
                'mac_file': str(mac_file),
                'radius': radius
            }):
                self._finish(False, "步骤 3 失败：计算重量")
                return

            # ========== 步骤 4/6：计算频率 ==========
            if not self._run_step(4, "计算频率", FUNCTION_FREQUENCY, {
                'solver_type': solver_type,
                'mac_solver_type': solver_type,
                'function': FUNCTION_FREQUENCY,
                'modules_path': str(modules_path),
                'solver_path': str(solver_path),
                'sum_folder': str(optimization_folder),
                'mac_file': str(mac_file),
                'radius': radius,
                'drmx': drmx,
                'background_run': background_run
            }):
                self._finish(False, "步骤 4 失败：计算频率")
                return

            # ========== 步骤 5/6：计算应变（含载荷转化）==========
            if has_strain_calculation:
                # 注意：skip_loadcase_conversion=False（默认），_run_step 会先做载荷转化再做应变计算
                if not self._run_step(5, "计算应变", FUNCTION_STRAIN, {
                    'solver_type': solver_type,
                    'function': FUNCTION_STRAIN,
                    'modules_path': str(modules_path),
                    'solver_path': str(solver_path),
                    'sum_folder': str(optimization_folder),
                    'mac_file': str(mac_file),
                    'radius': radius,
                    'load_file': str(load_file),
                    'zspan_file': str(zspan_file),
                    'background_run': background_run
                }):
                    self._finish(False, "步骤 5 失败：计算应变")
                    return
            else:
                self.log_signal.emit(f"\n⚠ 步骤 5/6 跳过：计算应变（缺少 zspan 或载荷文件）")
                self.current_step = 5
                self.progress_signal.emit(5, self.total_steps)

            # ========== 步骤 6/6：计算叶尖挠度（仅 frbex）==========
            if solver_type == SOLVER_FRBEX:
                if not self._run_step(6, "计算叶尖挠度", FUNCTION_TIP_DEFLECTION, {
                    'solver_type': solver_type,
                    'mac_solver_type': solver_type,
                    'function': FUNCTION_TIP_DEFLECTION,
                    'modules_path': str(modules_path),
                    'solver_path': str(solver_path),
                    'sum_folder': str(optimization_folder),
                    'mac_file': str(mac_file),
                    'radius': radius,
                    'drmx': drmx,
                    'background_run': background_run
                }):
                    self._finish(False, "步骤 6 失败：计算叶尖挠度")
                    return
            else:
                self.log_signal.emit(f"\n⚠ 步骤 6/6 跳过：计算叶尖挠度（仅 frbex 求解器执行）")
                self.current_step = 6
                self.progress_signal.emit(6, self.total_steps)

            # ========== 阶段4: 生成汇总文件 ==========
            self.log_signal.emit(f"\n{LOG_SEPARATOR}")
            self.log_signal.emit("开始生成汇总文件...")
            self.log_signal.emit(LOG_SEPARATOR)

            if not self._generate_summary_files(optimization_folder, solver_type):
                self._finish(False, "生成汇总文件失败")
                return

            # 所有步骤完成
            # 计算总耗时
            end_time = time.time()
            elapsed_time = end_time - self.start_time

            # 格式化时间显示
            if elapsed_time >= 60:
                minutes = int(elapsed_time // 60)
                seconds = int(elapsed_time % 60)
                time_str = f"{minutes}分{seconds}秒"
            else:
                time_str = f"{elapsed_time:.1f}秒"

            self.log_signal.emit(f"\n{LOG_SEPARATOR}")
            self.log_signal.emit("✓ 所有计算步骤已完成！")
            self.log_signal.emit(f"总耗时: {time_str}")
            self.log_signal.emit(f"输出文件夹: {optimization_folder}")
            self.log_signal.emit(LOG_SEPARATOR)
            self._finish(True, "一键运行完成（串行）")

        except Exception as e:
            self.log_signal.emit(f"\n{LOG_SEPARATOR}")
            self.log_signal.emit(f"错误: {str(e)}")
            self.log_signal.emit(f"{LOG_SEPARATOR}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            self._finish(False, f"一键运行失败: {str(e)}")

        finally:
            # 关闭日志文件
            if log_file:
                try:
                    log_file.close()
                except:
                    pass

    def _run_step(self, step_num, step_name, function_name, params, skip_loadcase_conversion=False):
        """运行单个步骤

        Args:
            step_num: 步骤编号
            step_name: 步骤名称
            function_name: 功能名称
            params: 参数字典
            skip_loadcase_conversion: 是否跳过载荷转化（True=只做应变计算，假定 LOAD.LD1 已就绪）

        Returns:
            bool: 成功返回True，失败返回False
        """
        self.current_step = step_num
        self.step_signal.emit(step_name)
        self.progress_signal.emit(step_num, self.total_steps)

        self.log_signal.emit(f"\n{LOG_SEPARATOR}")
        self.log_signal.emit(f"步骤 {step_num}/{self.total_steps}: {step_name}")
        self.log_signal.emit(LOG_SEPARATOR)

        # 按需导入求解器线程（懒加载）
        from .solver_focus6 import Focus6SolverThread

        # 创建线程实例但不启动新线程，直接调用其方法
        thread = Focus6SolverThread(params, skip_prepare=False, generate_csv=False)
        # 连接日志信号：thread的日志 → OneClickRunThread的日志
        thread.log_signal.connect(self.log_signal)

        # 根据功能类型执行不同的逻辑
        try:
            if function_name == FUNCTION_READ_MAC:
                # 读取mac文件：准备 + 执行求解器
                if not thread.prepare_work_directory():
                    return False
                config_file = thread.generate_parse_frb()
                if not config_file:
                    return False
                thread.execute_solver(config_file)

            elif function_name == FUNCTION_PARSE_MAC:
                # 解析mac文件：准备 + 执行求解器
                if not thread.prepare_work_directory():
                    return False
                config_file = thread.generate_build_database_frb()
                if not config_file:
                    return False
                thread.check_and_warn_buffer_empty()
                thread.execute_solver(str(config_file))

            elif function_name == FUNCTION_WEIGHT:
                # 重量计算：直接调用方法，不生成单独的CSV文件（会在汇总文件中生成）
                if not thread.perform_weight_calculation():
                    return False

            elif function_name == FUNCTION_FREQUENCY:
                # 频率计算：准备 + 执行求解器
                if not thread.prepare_work_directory():
                    return False
                if not thread.perform_frequency_calculation():
                    return False

            elif function_name == FUNCTION_STRAIN:
                # 应变计算：准备工作 + (可选)载荷转化 + 应变计算
                if not thread.prepare_work_directory():
                    return False

                # 如果没有跳过载荷转化，则执行
                if not skip_loadcase_conversion:
                    # 执行载荷转化，但不自动执行应变计算（因为下面会手动调用）
                    if not thread.convert_loadcase(auto_perform_strain=False):
                        return False

                    # 获取LOAD.LD1路径
                    load_ld1_path = thread.load_convert_folder / "LOAD.LD1"
                    if not load_ld1_path.exists():
                        self.log_signal.emit(f"\n✗ 错误：载荷转化未生成LOAD.LD1文件")
                        return False

                    # 手动执行应变计算（LOAD.LD1已在prepare_work_directory中复制）
                    if not thread.perform_strain_calculation(load_ld1_path):
                        return False
                else:
                    # 跳过载荷转化，直接执行应变计算
                    self.log_signal.emit(f"\n⚭ 跳过载荷转化（已在阶段1完成）")
                    self.log_signal.emit(f"   LOAD.LD1已在prepare_work_directory中复制")

                    # LOAD.LD1路径（prepare_work_directory已复制到工作文件夹）
                    load_ld1_path = thread.strain_calc_folder / "LOAD.LD1"

                    # 直接调用应变计算（不包含载荷转化）
                    if not thread.perform_strain_calculation(load_ld1_path):
                        return False

                    return True

            elif function_name == FUNCTION_TIP_DEFLECTION:
                # 叶尖挠度计算：准备 + 执行求解器
                if not thread.prepare_work_directory():
                    return False
                if not thread.perform_tip_deflection_calculation():
                    return False

            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 步骤失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def _extract_radius_from_mac(self, mac_file):
        """从mac文件中提取半径参数

        Args:
            mac_file: mac文件路径

        Returns:
            str: 半径值（字符串格式）
        """
        try:
            with open(mac_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 查找半径定义
            match = re.search(r'DEF\s+PARA\s*,\s*RADIUS\s*=\s*(\d+\.?\d*)', content, re.IGNORECASE)
            if match:
                radius = match.group(1)
                self.log_signal.emit(f"从mac文件提取半径: {radius} mm")
                return radius
            else:
                self.log_signal.emit(f"⚠ 未在mac文件中找到RADIUS参数，使用默认值")
                return "50000"  # 默认50m

        except Exception as e:
            self.log_signal.emit(f"⚠ 读取mac文件失败: {str(e)}，使用默认半径50000mm")
            return "50000"

    def _run_convert_loadcase_only(self, opt_folder, solver_type, modules_path, load_file, zspan_file, radius):
        """只执行载荷转化（不执行应变计算）

        Args:
            opt_folder: opt文件夹路径
            solver_type: 求解器类型
            modules_path: modules路径
            load_file: 载荷文件路径
            zspan_file: ZSPAN文件路径
            radius: 半径

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            self.log_signal.emit(f"\n{'='*80}")
            self.log_signal.emit(f"独立执行: 载荷转化")
            self.log_signal.emit(f"{'='*80}")

            # 按需导入求解器线程
            from .solver_focus6 import Focus6SolverThread

            # 创建参数
            params = {
                'solver_type': solver_type,
                'function': FUNCTION_STRAIN,
                'modules_path': str(modules_path),
                'solver_path': str(modules_path / "farob"),
                'sum_folder': str(opt_folder),
                'mac_file': '',  # 不需要mac文件
                'radius': radius,
                'load_file': load_file,
                'zspan_file': str(zspan_file),
                'background_run': False  # 载荷转化不需要后台运行
            }

            # 创建线程实例
            thread = Focus6SolverThread(params, skip_prepare=False, generate_csv=False)
            thread.log_signal.connect(self.log_signal)

            # 只执行载荷转化，不执行应变计算
            # convert_loadcase(auto_perform_strain=False)只执行载荷转化，完成后不自动执行应变计算
            if not thread.convert_loadcase(auto_perform_strain=False):
                self.log_signal.emit(f"\n✗ 载荷转化失败")
                return False

            self.log_signal.emit(f"\n✓ 载荷转化完成")
            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 载荷转化异常: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def _finish(self, success, message):
        """完成处理

        Args:
            success: 是否成功
            message: 完成消息
        """
        self.finished_signal.emit(success, message)

    def _generate_summary_files(self, opt_folder, solver_type):
        """生成汇总文件（结构属性.csv 和 应变.csv）

        Args:
            opt_folder: opt文件夹路径
            solver_type: 求解器类型

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            import pandas as pd
            import csv

            # 1. 读取重量数据
            self.log_signal.emit(f"\n1. 读取重量数据...")
            weight_data = self._read_weight_data(opt_folder, solver_type)
            if weight_data is None:
                return False

            # 2. 读取叶尖挠度数据
            self.log_signal.emit(f"\n2. 读取叶尖挠度数据...")
            tip_deflection_data = self._read_tip_deflection_data(opt_folder, solver_type)
            if tip_deflection_data is None:
                return False

            # 3. 读取频率数据
            self.log_signal.emit(f"\n3. 读取频率数据...")
            frequency_data = self._read_frequency_data(opt_folder, solver_type)
            if frequency_data is None:
                return False

            # 4. 读取应变数据
            self.log_signal.emit(f"\n4. 读取应变数据...")
            strain_data = self._read_strain_data(opt_folder, solver_type)
            if strain_data is None:
                return False

            # 5. 生成结构属性.csv
            self.log_signal.emit(f"\n5. 生成结构属性.csv...")
            if not self._generate_structure_properties_csv(opt_folder, weight_data, tip_deflection_data, frequency_data):
                return False

            # 6. 生成应变.csv
            self.log_signal.emit(f"\n6. 生成应变.csv...")
            if not self._generate_strain_csv(opt_folder, strain_data):
                return False

            self.log_signal.emit(f"\n✓ 汇总文件生成完成")
            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 生成汇总文件失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def _read_weight_data(self, opt_folder, solver_type):
        """读取重量数据（从blade_db.xls的MASS列最后一行）

        Args:
            opt_folder: opt文件夹路径
            solver_type: 求解器类型

        Returns:
            float: 重量值（kg），失败返回None
        """
        try:
            import pandas as pd

            # 查找blade_db.xls
            parse_mac_folder_name = f"{solver_type}_{FUNCTION_FOLDER_NAMES[FUNCTION_PARSE_MAC]}"
            parse_mac_folder = opt_folder / parse_mac_folder_name
            blade_db_file = parse_mac_folder / "blade_db.xls"

            if not blade_db_file.exists():
                self.log_signal.emit(f"   ✗ 找不到blade_db.xls文件: {blade_db_file}")
                return None

            # 读取文件
            df = pd.read_csv(blade_db_file, sep='\t', encoding='utf-8')

            # 查找MASS列
            mass_column = None
            for possible_name in ['MASS', 'Mass', 'mass']:
                if possible_name in df.columns:
                    mass_column = df[possible_name]
                    break

            if mass_column is None:
                self.log_signal.emit(f"   ✗ blade_db.xls中没有找到MASS列")
                return None

            # 读取最后一行数据
            mass_values = mass_column.dropna()
            mass_values = pd.to_numeric(mass_values, errors='coerce').dropna()

            if len(mass_values) == 0:
                self.log_signal.emit(f"   ✗ MASS列没有有效数据")
                return None

            weight_kg = mass_values.iloc[-1]
            self.log_signal.emit(f"   ✓ 重量: {weight_kg:.2f} kg")
            return weight_kg

        except Exception as e:
            self.log_signal.emit(f"   ✗ 读取重量数据失败: {str(e)}")
            return None

    def _read_tip_deflection_data(self, opt_folder, solver_type):
        """读取叶尖挠度数据（从deflection_TIPD_MAX_LOAD_blade1.txt）

        Args:
            opt_folder: opt文件夹路径
            solver_type: 求解器类型

        Returns:
            float: 叶尖挠度值（m），失败返回None
        """
        try:
            # 查找叶尖挠度计算文件夹
            tip_folder_name = f"{solver_type}_{FUNCTION_FOLDER_NAMES[FUNCTION_TIP_DEFLECTION]}"
            tip_folder = opt_folder / tip_folder_name
            tip_file = tip_folder / "deflection_TIPD_MAX_LOAD_blade1.txt"

            if not tip_file.exists():
                self.log_signal.emit(f"   ✗ 找不到叶尖挠度文件: {tip_file}")
                return None

            # 读取文件
            with open(tip_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            if len(lines) < 3:
                self.log_signal.emit(f"   ✗ 文件行数不足3行")
                return None

            # 读取第三行第二个数据
            third_line = lines[2].strip().split()
            if len(third_line) < 2:
                self.log_signal.emit(f"   ✗ 第三行数据格式错误")
                return None

            try:
                tip_deflection = float(third_line[1])
                self.log_signal.emit(f"   ✓ 叶尖挠度: {tip_deflection:.6f} m")
                return tip_deflection
            except ValueError:
                self.log_signal.emit(f"   ✗ 叶尖挠度数据格式错误")
                return None

        except Exception as e:
            self.log_signal.emit(f"   ✗ 读取叶尖挠度数据失败: {str(e)}")
            return None

    def _read_frequency_data(self, opt_folder, solver_type):
        """读取频率数据（从freq_coupled.txt）

        Args:
            opt_folder: opt文件夹路径
            solver_type: 求解器类型

        Returns:
            list: 12个频率值的列表，失败返回None
        """
        try:
            import pandas as pd

            # 查找频率计算文件夹
            freq_folder_name = f"{solver_type}_{FUNCTION_FOLDER_NAMES[FUNCTION_FREQUENCY]}"
            freq_folder = opt_folder / freq_folder_name
            freq_file = freq_folder / "freq_coupled.txt"

            if not freq_file.exists():
                self.log_signal.emit(f"   ✗ 找不到频率文件: {freq_file}")
                return None

            # 读取文件，从第9行开始（索引8）读取两列数据
            df = pd.read_csv(freq_file, sep=r'\s+', skiprows=8, header=None, encoding='utf-8')

            if df.shape[1] < 2:
                self.log_signal.emit(f"   ✗ 频率文件列数不足2列")
                return None

            # 读取第二列的12个频率值
            frequencies = df.iloc[:12, 1].tolist()

            # 转换为数值
            frequencies = [float(f) for f in frequencies]

            self.log_signal.emit(f"   ✓ 读取了 {len(frequencies)} 个频率值")
            return frequencies

        except Exception as e:
            self.log_signal.emit(f"   ✗ 读取频率数据失败: {str(e)}")
            return None

    def _read_strain_data(self, opt_folder, solver_type):
        """读取应变数据（从CalcStrain/BUFFER/strain_xxx_BLD1.txt）

        Args:
            opt_folder: opt文件夹路径
            solver_type: 求解器类型

        Returns:
            dict: {展向位置: {拉应变, 压应变}}，失败返回None
        """
        try:
            import pandas as pd
            import re

            # 查找应变计算文件夹
            strain_folder = opt_folder / f"{solver_type}_CalcStrain"
            buffer_folder = strain_folder / "BUFFER"

            if not buffer_folder.exists():
                self.log_signal.emit(f"   ✗ 找不到BUFFER文件夹: {buffer_folder}")
                return None

            # 查找所有strain_xxx_BLD1.txt文件
            strain_files = list(buffer_folder.glob("strain_*_BLD1.txt"))

            if not strain_files:
                self.log_signal.emit(f"   ✗ 找不到strain_xxx_BLD1.txt文件")
                return None

            self.log_signal.emit(f"   ✓ 找到 {len(strain_files)} 个应变文件")

            strain_data = {}
            for strain_file in sorted(strain_files):
                # 从文件名提取展向位置
                match = re.search(r'strain_(\d+)_BLD1\.txt', strain_file.name)
                if not match:
                    continue

                position_mm = int(match.group(1))  # 提取的xxx部分，单位mm

                try:
                    # 读取文件
                    # header=5: 跳过前5行，从第6行开始读取（前5行是注释）
                    # sep=r'\s+': 使用空白字符分隔
                    df = pd.read_csv(strain_file, sep=r'\s+', encoding='utf-8', header=5)

                    # 第14列是normal_crit（索引13）
                    if df.shape[1] < 14:
                        self.log_signal.emit(f"   ⚠ 文件 {strain_file.name} 列数不足14列，跳过")
                        continue

                    normal_crit = df.iloc[:, 13].dropna()  # 第14列

                    if len(normal_crit) == 0:
                        continue

                    # 找最大正值为拉应变，最小负值为压应变
                    max_tensile = normal_crit.max()
                    max_compressive = normal_crit.min()

                    # 单位转换：ε → με（×10^6）
                    max_tensile_micro = max_tensile * 1e6
                    max_compressive_micro = max_compressive * 1e6

                    strain_data[position_mm] = {
                        '拉应变': max_tensile_micro,
                        '压应变': max_compressive_micro
                    }

                except Exception as e:
                    self.log_signal.emit(f"   ⚠ 读取文件 {strain_file.name} 失败: {str(e)}")
                    continue

            if not strain_data:
                self.log_signal.emit(f"   ✗ 没有有效的应变数据")
                return None

            self.log_signal.emit(f"   ✓ 读取了 {len(strain_data)} 个截面的应变数据")
            return strain_data

        except Exception as e:
            self.log_signal.emit(f"   ✗ 读取应变数据失败: {str(e)}")
            return None

    def _summarize_all_data(self, opt_folder, solver_type):
        """汇总所有计算数据并生成CSV文件

        Args:
            opt_folder: opt文件夹路径
            solver_type: 求解器类型

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            # 1. 读取重量数据
            self.log_signal.emit(f"\n1. 读取重量数据...")
            weight_data = self._read_weight_data(opt_folder, solver_type)
            if weight_data is None:
                self.log_signal.emit(f"   ⚠ 警告：重量数据读取失败，将使用占位符")
                weight_data = 0  # 使用占位符

            # 2. 读取挠度数据
            self.log_signal.emit(f"\n2. 读取挠度数据...")
            tip_deflection_data = self._read_tip_deflection_data(opt_folder, solver_type)
            if tip_deflection_data is None:
                self.log_signal.emit(f"   ⚠ 警告：挠度数据读取失败，将使用占位符")
                tip_deflection_data = 0  # 使用占位符

            # 3. 读取频率数据
            self.log_signal.emit(f"\n3. 读取频率数据...")
            frequency_data = self._read_frequency_data(opt_folder, solver_type)
            if frequency_data is None:
                self.log_signal.emit(f"   ⚠ 警告：频率数据读取失败，将使用占位符")
                frequency_data = [0] * 12  # 使用占位符

            # 4. 读取应变数据
            self.log_signal.emit(f"\n4. 读取应变数据...")
            strain_data = self._read_strain_data(opt_folder, solver_type)
            if strain_data is None:
                self.log_signal.emit(f"   ⚠ 警告：应变数据读取失败，将跳过应变.csv")
                strain_data = {}  # 空数据

            # 5. 生成结构属性.csv
            self.log_signal.emit(f"\n5. 生成结构属性.csv...")
            if not self._generate_structure_properties_csv(opt_folder, weight_data, tip_deflection_data, frequency_data):
                return False

            # 6. 生成应变.csv（如果有应变数据）
            if strain_data:
                self.log_signal.emit(f"\n6. 生成应变.csv...")
                if not self._generate_strain_csv(opt_folder, strain_data):
                    return False

            # 7. 生成变桨中心.xlsx（从mac文件提取）
            self.log_signal.emit(f"\n7. 生成变桨中心.xlsx...")
            mac_file = Path(self.params.get('mac_file', ''))
            if mac_file.exists():
                if not self._generate_pitch_center_xlsx(opt_folder, mac_file):
                    return False
            else:
                self.log_signal.emit(f"   ⚠ 警告：mac文件不存在，跳过变桨中心.xlsx生成")

            # 8. 生成focus2blade.xlsx（使用blade_db.xls + 变桨中心.xlsx）
            self.log_signal.emit(f"\n8. 生成focus2blade.xlsx...")
            blade_db_file = opt_folder / f"{solver_type}_{FUNCTION_FOLDER_NAMES[FUNCTION_PARSE_MAC]}" / "blade_db.xls"
            pitch_center_xlsx = opt_folder / "计算结果" / "变桨中心.xlsx"

            if blade_db_file.exists() and pitch_center_xlsx.exists():
                if not self._generate_focus2blade_xlsx(opt_folder, blade_db_file, pitch_center_xlsx):
                    return False
            else:
                if not blade_db_file.exists():
                    self.log_signal.emit(f"   ⚠ 警告：blade_db.xls不存在，跳过focus2blade.xlsx生成")
                elif not pitch_center_xlsx.exists():
                    self.log_signal.emit(f"   ⚠ 警告：变桨中心.xlsx不存在，跳过focus2blade.xlsx生成")

            return True

        except Exception as e:
            self.log_signal.emit(f"\n✗ 数据汇总失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"详细错误:\n{traceback.format_exc()}")
            return False

    def _extract_pitch_data_from_mac(self, mac_file):
        """从mac文件中提取DEF SHAPE数据（展向位置和变桨位置）

        Args:
            mac_file: mac文件路径

        Returns:
            dict: {展向位置: 变桨位置}，失败返回None
        """
        try:
            import re

            pitch_data = {}

            # 读取mac文件
            with open(mac_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            # 匹配 DEF SHAPE 行
            # 格式：DEF SHAPE R_2.5     0.4827    0.0
            # 提取：shape名称（R_2.5）和变桨位置（0.4827）
            pattern = r'DEF\s+SHAPE\s+(\S+)\s+([\d.]+)'
            matches = re.findall(pattern, content, re.IGNORECASE)

            for match in matches:
                shape_name = match[0]  # 如 R_2.5
                pitch_position = float(match[1])  # 如 0.4827

                # 从shape名称中提取展向位置（米）
                # R_2.5 -> 2.5
                position_match = re.search(r'[\d.]+', shape_name)
                if position_match:
                    position_m = float(position_match.group())
                    pitch_data[position_m] = pitch_position

            if not pitch_data:
                self.log_signal.emit(f"   ⚠ 警告：未在mac文件中找到DEF SHAPE数据")
                return None

            # 按展向位置排序
            sorted_positions = sorted(pitch_data.keys())
            self.log_signal.emit(f"   ✓ 从mac文件提取到 {len(sorted_positions)} 个截面的变桨中心数据")

            # 显示前几个数据点
            for pos in sorted_positions[:3]:
                self.log_signal.emit(f"      展向位置 {pos}m → 变桨位置 {pitch_data[pos]}")

            if len(sorted_positions) > 3:
                self.log_signal.emit(f"      ...")

            return pitch_data

        except Exception as e:
            self.log_signal.emit(f"   ✗ 从mac文件提取变桨中心数据失败: {str(e)}")
            return None

    def _generate_pitch_center_xlsx(self, opt_folder, mac_file):
        """生成变桨中心.xlsx文件

        Args:
            opt_folder: opt文件夹路径
            mac_file: mac文件路径

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            import pandas as pd

            # 创建计算结果文件夹
            result_folder = opt_folder / "计算结果"
            if not result_folder.exists():
                result_folder.mkdir(parents=True, exist_ok=True)

            xlsx_file = result_folder / "变桨中心.xlsx"

            # 提取变桨中心数据
            pitch_data = self._extract_pitch_data_from_mac(mac_file)
            if pitch_data is None:
                return False

            # 按展向位置排序
            sorted_positions = sorted(pitch_data.keys())

            # 创建DataFrame（列名必须与ConversionThread期望的一致）
            data = {
                'ZSPAN': sorted_positions,  # 展向位置（米）
                'pitchaxis': [pitch_data[pos] for pos in sorted_positions]  # 变桨中心位置
            }
            df = pd.DataFrame(data)

            # 保存为Excel文件
            with pd.ExcelWriter(xlsx_file, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Sheet1')

            self.log_signal.emit(f"   ✓ 已保存: {xlsx_file.name}")
            self.log_signal.emit(f"   ✓ 包含 {len(sorted_positions)} 个截面的变桨中心数据")
            return True

        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成变桨中心.xlsx失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"   详细错误:\n{traceback.format_exc()}")
            return False

    def _generate_focus2blade_xlsx(self, opt_folder, blade_db_file, pitch_center_xlsx):
        """生成focus2blade.xlsx文件（按照第一个标签页的逻辑）

        Args:
            opt_folder: opt文件夹路径
            blade_db_file: blade_db.xls文件路径
            pitch_center_xlsx: 变桨中心.xlsx文件路径

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            import pandas as pd

            # 创建计算结果文件夹
            result_folder = opt_folder / "计算结果"
            if not result_folder.exists():
                result_folder.mkdir(parents=True, exist_ok=True)

            output_file = result_folder / "focus2blade.xlsx"

            # 1. 读取blade_db文件
            self.log_signal.emit(f"   1. 读取blade_db文件...")
            self.log_signal.emit(f"      文件路径: {blade_db_file}")
            self.log_signal.emit(f"      文件存在: {blade_db_file.exists()}")
            # 指定引擎：.xls文件使用xlrd引擎
            df_blade = pd.read_excel(blade_db_file, engine='xlrd')
            self.log_signal.emit(f"   ✓ 数据维度: {df_blade.shape[0]} 个截面 × {df_blade.shape[1]} 个属性")

            # 2. 读取变桨中心数据
            self.log_signal.emit(f"   2. 读取变桨中心数据...")
            self.log_signal.emit(f"      文件路径: {pitch_center_xlsx}")
            self.log_signal.emit(f"      文件存在: {pitch_center_xlsx.exists()}")
            # 指定引擎：.xlsx文件使用openpyxl引擎
            df_pitch = pd.read_excel(pitch_center_xlsx, engine='openpyxl')
            df_pitch = df_pitch.sort_values('ZSPAN').reset_index(drop=True)
            target_distances_m = df_pitch['ZSPAN'].values
            pitch_axis = df_pitch['pitchaxis'].values
            self.log_signal.emit(f"   ✓ 截面数量: {len(target_distances_m)}")
            self.log_signal.emit(f"   ✓ 截面位置范围: {target_distances_m[0]:.1f}m ~ {target_distances_m[-1]:.1f}m")
            self.log_signal.emit(f"   ✓ pitchaxis范围: {pitch_axis.min():.2f}% ~ {pitch_axis.max():.2f}%")

            # 3. 计算blade_db的截面属性
            self.log_signal.emit(f"   3. 计算blade_db的截面属性...")
            from blade_db_to_focus2blade_wisdem import compute_section_properties_blade_db
            props_blade = compute_section_properties_blade_db(df_blade)
            self.log_signal.emit(f"   ✓ 计算了 {len(props_blade)} 个属性")

            # 4. 插值到目标截面位置
            self.log_signal.emit(f"   4. 插值到目标截面位置...")
            from blade_db_to_focus2blade_wisdem import interpolate_to_target_sections
            props_interp = interpolate_to_target_sections(props_blade, target_distances_m)
            self.log_signal.emit(f"   ✓ 插值完成")

            # 5. 计算局部坐标
            self.log_signal.emit(f"   5. 计算局部坐标...")
            from blade_db_to_focus2blade_wisdem import compute_local_coordinates
            props_interp = compute_local_coordinates(props_interp, pitch_axis)
            self.log_signal.emit(f"   ✓ 计算完成")

            # 6. 创建输出DataFrame
            self.log_signal.emit(f"   6. 创建输出数据...")
            df_output = pd.DataFrame(props_interp)
            self.log_signal.emit(f"   ✓ 输出数据维度: {df_output.shape[0]} 个截面 × {df_output.shape[1]} 个属性")

            # 7. 保存输出文件
            self.log_signal.emit(f"   7. 保存输出文件...")
            self.log_signal.emit(f"      输出路径: {output_file}")
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                df_output.to_excel(writer, index=False, sheet_name='Sheet1')

            self.log_signal.emit(f"   ✓ 已保存: {output_file.name}")
            self.log_signal.emit(f"   ✓ 包含 {len(df_output)} 个截面的完整数据")
            return True

        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成focus2blade.xlsx失败: {str(e)}")
            import traceback
            self.log_signal.emit(f"   详细错误:\n{traceback.format_exc()}")
            return False

    def _generate_structure_properties_csv(self, opt_folder, weight_data, tip_deflection_data, frequency_data):
        """生成结构属性.csv

        Args:
            opt_folder: opt文件夹路径
            weight_data: 重量数据（kg）
            tip_deflection_data: 叶尖挠度数据（m）
            frequency_data: 频率数据列表（12个值）

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            import csv

            # 创建计算结果文件夹
            result_folder = opt_folder / "计算结果"
            if not result_folder.exists():
                result_folder.mkdir(parents=True, exist_ok=True)

            csv_file = result_folder / "结构属性.csv"

            # 写入CSV文件（UTF-8 with BOM）
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)

                # 写入表头
                writer.writerow(['ID号', '重量（kg）', '叶尖挠度（m）'] + [f'频率{i}' for i in range(1, 13)])

                # 写入数据行
                row_data = [1, f'{weight_data:.2f}', f'{tip_deflection_data:.6f}'] + [f'{freq:.6f}' for freq in frequency_data]
                writer.writerow(row_data)

            self.log_signal.emit(f"   ✓ 已保存: {csv_file.name}")
            return True

        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成结构属性.csv失败: {str(e)}")
            return False

    def _generate_strain_csv(self, opt_folder, strain_data):
        """生成应变.csv

        Args:
            opt_folder: opt文件夹路径
            strain_data: {展向位置: {拉应变, 压应变}}

        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            import csv

            # 创建计算结果文件夹
            result_folder = opt_folder / "计算结果"
            if not result_folder.exists():
                result_folder.mkdir(parents=True, exist_ok=True)

            csv_file = result_folder / "应变.csv"

            # 按展向位置排序
            sorted_positions = sorted(strain_data.keys())

            # 写入CSV文件（UTF-8 with BOM）
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)

                # 写入表头
                writer.writerow(['展向位置（mm）', '拉应变', '压应变'])

                # 写入每个展向位置的数据
                for position in sorted_positions:
                    row_data = [
                        position,
                        f'{strain_data[position]["拉应变"]:.6f}',
                        f'{strain_data[position]["压应变"]:.6f}'
                    ]
                    writer.writerow(row_data)

            self.log_signal.emit(f"   ✓ 已保存: {csv_file.name}")
            self.log_signal.emit(f"   ✓ 包含 {len(sorted_positions)} 个截面的应变数据")
            return True

        except Exception as e:
            self.log_signal.emit(f"   ✗ 生成应变.csv失败: {str(e)}")
            return False

