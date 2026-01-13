"""
配置管理模块
负责读取和验证配置文件（sites_config.yaml和prompt.txt）
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SiteConfig(BaseModel):
	"""单个网站配置"""
	name: str
	url: str
	login_required: bool = False
	username: str | None = None
	password: str | None = None


class ExtractField(BaseModel):
	"""单个提取字段定义"""
	key: str  # 字段键名（英文）
	name: str  # 字段中文名
	hint: str  # 提取提示


class Config(BaseModel):
	"""全局配置"""
	websites: List[SiteConfig]
	prompt: str
	max_pages: int = 3  # 默认翻5页
	max_retries: int = 3  # 默认重试3次


# LEGACY: 以下函数仅供 CLI 模式（main.py）使用，API 模式不使用
def load_config(config_path: str = "sites_config.yaml", prompt_path: str = "prompt.txt") -> Config:
	"""
	[LEGACY - CLI only] 加载配置文件

	Args:
		config_path: 网站配置文件路径
		prompt_path: 提示词文件路径

	Returns:
		Config对象

	Raises:
		FileNotFoundError: 配置文件不存在
		ValueError: 配置文件格式错误
	"""
	# 读取网站配置
	config_file = Path(config_path)
	if not config_file.exists():
		raise FileNotFoundError(f"配置文件不存在: {config_path}")

	with open(config_file, 'r', encoding='utf-8') as f:
		raw_config = yaml.safe_load(f)

	# 读取提示词
	prompt_file = Path(prompt_path)
	if not prompt_file.exists():
		raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")

	with open(prompt_file, 'r', encoding='utf-8') as f:
		prompt = f.read()

	# 验证配置
	websites = []
	for site_data in raw_config.get('websites', []):
		# 验证必需字段
		if 'name' not in site_data or 'url' not in site_data:
			raise ValueError(f"网站配置缺少必需字段: {site_data}")

		# 验证登录配置
		if site_data.get('login_required') and (not site_data.get('username') or not site_data.get('password')):
			raise ValueError(f"网站 {site_data['name']} 需要登录但未提供账号密码")

		websites.append(SiteConfig(**site_data))

	if not websites:
		raise ValueError("配置文件中没有网站配置")

	return Config(websites=websites, prompt=prompt)


def get_user_data_dir(site_name: str, base_dir: str = ".browser-profiles") -> str:
	"""
	生成网站的user_data_dir路径

	Args:
		site_name: 网站名称
		base_dir: 基础目录

	Returns:
		user_data_dir路径
	"""
	# 清理网站名称中的非法字符
	safe_name = "".join(c for c in site_name if c.isalnum() or c in (' ', '-', '_')).strip()
	path = Path(base_dir) / safe_name
	path.mkdir(parents=True, exist_ok=True)
	return str(path)


def load_extract_fields(fields_path: str = "extract_fields.yaml") -> List[ExtractField]:
	"""
	加载字段提取配置

	Args:
		fields_path: 字段配置文件路径

	Returns:
		字段定义列表

	Raises:
		FileNotFoundError: 配置文件不存在
	"""
	fields_file = Path(fields_path)
	if not fields_file.exists():
		raise FileNotFoundError(f"字段配置文件不存在: {fields_path}")

	with open(fields_file, 'r', encoding='utf-8') as f:
		raw_config = yaml.safe_load(f)

	fields = []
	for field_data in raw_config.get('fields', []):
		if 'key' not in field_data or 'name' not in field_data:
			raise ValueError(f"字段配置缺少必需字段: {field_data}")
		fields.append(ExtractField(**field_data))

	return fields


def generate_extract_prompt(fields: List[ExtractField]) -> str:
	"""
	根据字段定义生成提取提示词

	Args:
		fields: 字段定义列表

	Returns:
		提取提示词字符串
	"""
	lines = ["从当前详情页提取以下字段，找不到的填空字符串：", ""]

	for i, field in enumerate(fields, 1):
		lines.append(f"{i}. {field.key} - {field.name}")
		if field.hint:
			lines.append(f"   提示：{field.hint}")

	lines.append("")
	lines.append("返回 JSON 格式，示例：")

	# 生成示例 JSON
	example_fields = ', '.join([f'"{f.key}": "..."' for f in fields[:3]])
	lines.append(f'{{{example_fields}, ...}}')

	return "\n".join(lines)


# ============ LEGACY: 并发配置（仅 CLI 模式使用）============

class ConcurrencySettings(BaseModel):
	"""并发设置"""
	enabled: bool = False
	max_workers: int = 10
	timeout_per_site: int = 1200


class BrowserSettings(BaseModel):
	"""浏览器设置"""
	headless: bool = True


class LoggingSettings(BaseModel):
	"""日志设置"""
	worker_log_dir: str = "worker_logs"


class ConcurrencyConfig(BaseModel):
	"""并发配置（完整）"""
	concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
	browser: BrowserSettings = Field(default_factory=BrowserSettings)
	logging: LoggingSettings = Field(default_factory=LoggingSettings)


def load_concurrency_config(path: str = "concurrency_config.yaml") -> ConcurrencyConfig:
	"""
	加载并发配置文件

	Args:
		path: 配置文件路径

	Returns:
		ConcurrencyConfig 对象，文件不存在则返回默认值
	"""
	config_file = Path(path)
	if not config_file.exists():
		return ConcurrencyConfig()  # 返回默认值（并发关闭）

	with open(config_file, 'r', encoding='utf-8') as f:
		raw_config = yaml.safe_load(f)

	if not raw_config:
		return ConcurrencyConfig()

	return ConcurrencyConfig(**raw_config)

