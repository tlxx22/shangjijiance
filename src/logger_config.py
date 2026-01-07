"""
日志配置模块
提供统一的日志配置，支持控制台和文件双输出
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(name: str = "shangjijiance", log_dir: str = "output") -> logging.Logger:
	"""
	配置并返回logger实例

	Args:
		name: logger名称
		log_dir: 日志文件存放目录

	Returns:
		配置好的logger实例
	"""
	logger = logging.getLogger(name)
	logger.setLevel(logging.INFO)

	# 避免重复添加handler
	if logger.hasHandlers():
		return logger

	# 创建今天的日志目录
	today = datetime.now().strftime('%Y-%m-%d')
	log_path = Path(log_dir) / today
	log_path.mkdir(parents=True, exist_ok=True)

	# 日志格式
	formatter = logging.Formatter(
		'[%(asctime)s] [%(levelname)s] %(message)s',
		datefmt='%H:%M:%S'
	)

	# 控制台handler（详细输出）
	console_handler = logging.StreamHandler(sys.stdout)
	console_handler.setLevel(logging.INFO)
	console_handler.setFormatter(formatter)
	logger.addHandler(console_handler)

	# 文件handler（完整日志）
	file_handler = logging.FileHandler(
		log_path / 'run_log.txt',
		encoding='utf-8'
	)
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(formatter)
	logger.addHandler(file_handler)

	return logger


def get_logger(name: str = "shangjijiance") -> logging.Logger:
	"""
	获取已配置的logger实例
	"""
	return logging.getLogger(name)


def setup_worker_logger(
	worker_id: int,
	log_dir: Path,
	name: str = "shangjijiance"
) -> logging.Logger:
	"""
	为特定 Worker 创建独立日志文件

	Args:
		worker_id: Worker 编号
		log_dir: 日志目录 (如 output/2026-01-04/worker_logs)
		name: logger 名称前缀

	Returns:
		配置好的 logger
	"""
	logger_name = f"{name}.worker_{worker_id}"
	logger = logging.getLogger(logger_name)
	logger.setLevel(logging.INFO)
	logger.propagate = False  # 不传播到父 logger，只写入独立日志文件

	# 避免重复添加handler
	if logger.hasHandlers():
		return logger

	# 确保目录存在
	log_dir.mkdir(parents=True, exist_ok=True)

	# 日志格式（包含 Worker ID）
	formatter = logging.Formatter(
		f'[%(asctime)s] [Worker-{worker_id}] [%(levelname)s] %(message)s',
		datefmt='%H:%M:%S'
	)

	# 文件 handler
	file_handler = logging.FileHandler(
		log_dir / f'worker_{worker_id}.log',
		encoding='utf-8'
	)
	file_handler.setLevel(logging.DEBUG)
	file_handler.setFormatter(formatter)
	logger.addHandler(file_handler)

	return logger

