"""
自定义工具模块
提供公告正文原始内容提取、文件名处理等工具函数
"""

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any
import re

from browser_use import BrowserSession, ActionResult
from .logger_config import get_logger

logger = get_logger()


_MAX_FILENAME_COMPONENT_BYTES = 240  # conservative across Windows/Linux filesystems
_MAX_WINDOWS_PATH_CHARS = 240  # conservative to avoid Win32 MAX_PATH issues in some environments


def _truncate_to_utf8_bytes(text: str, max_bytes: int) -> str:
	"""
	Truncate a string so its UTF-8 encoded length is <= max_bytes.
	"""
	if max_bytes <= 0:
		return ""
	if len(text.encode("utf-8")) <= max_bytes:
		return text
	lo, hi = 0, len(text)
	while lo < hi:
		mid = (lo + hi + 1) // 2
		if len(text[:mid].encode("utf-8")) <= max_bytes:
			lo = mid
		else:
			hi = mid - 1
	return text[:lo]


def sanitize_filename(filename: str, max_length: int = 100) -> str:
	"""
	清理文件名中的非法字符

	Args:
		filename: 原始文件名
		max_length: 最大长度限制

	Returns:
		清理后的文件名
	"""
	# 替换非法字符
	replacements = {
		'/': '-',
		'\\': '-',
		':': '：',
		'*': '',
		'?': '',
		'"': "'",
		'<': '《',
		'>': '》',
		'|': '-',
	}

	for old, new in replacements.items():
		filename = filename.replace(old, new)

	# 移除首尾空格
	filename = filename.strip()

	# 限制长度
	if len(filename) > max_length:
		filename = filename[:max_length] + "..."

	return filename


def get_unique_filename(base_dir: Path, title: str, date: str) -> str:
	"""
	生成唯一的文件名，处理冲突

	Args:
		base_dir: 基础目录
		title: 招标标题
		date: 日期

	Returns:
		唯一的文件名（不含扩展名）
	"""
	# Keep the naming format unchanged: "<title>_<date>" (and optionally "_<counter>").
	# Only truncate the *title part* if needed to avoid filesystem/path length errors.
	safe_title = sanitize_filename(title)
	ext = ".json"

	def _fit_base(counter_suffix: str) -> str:
		# Component length limits (Linux: 255 bytes; Windows: 255 chars). Use conservative byte cap.
		reserved = f"_{date}{counter_suffix}".encode("utf-8")
		max_base_bytes = _MAX_FILENAME_COMPONENT_BYTES - len(ext.encode("utf-8"))
		allow_title_bytes = max_base_bytes - len(reserved)
		fitted_title = _truncate_to_utf8_bytes(safe_title, allow_title_bytes)
		base = f"{fitted_title}_{date}{counter_suffix}"

		# Extra guard for Windows full-path length limits in some environments.
		if os.name == "nt":
			full_path = base_dir / f"{base}{ext}"
			if len(str(full_path)) > _MAX_WINDOWS_PATH_CHARS:
				over = len(str(full_path)) - _MAX_WINDOWS_PATH_CHARS
				target_chars = max(0, len(fitted_title) - over - 8)
				base = f"{fitted_title[:target_chars]}_{date}{counter_suffix}"
		return base

	base_filename = _fit_base("")

	# 检查是否存在
	json_path = base_dir / f"{base_filename}{ext}"

	if not json_path.exists():
		return base_filename

	# 存在冲突，添加序号
	counter = 2
	while True:
		new_filename = _fit_base(f"_{counter}")
		json_path = base_dir / f"{new_filename}{ext}"

		if not json_path.exists():
			return new_filename

		counter += 1


async def get_browser_session(browser) -> BrowserSession:
	"""
	从Browser或BrowserSession对象获取BrowserSession实例

	Args:
		browser: Browser或BrowserSession实例

	Returns:
		BrowserSession实例
	"""
	# 如果已经是BrowserSession，直接返回
	if isinstance(browser, BrowserSession):
		return browser

	# 如果是Browser对象，获取它的session
	# Browser对象在browser-use v0.11中有session属性
	if hasattr(browser, 'session') and browser.session:
		return browser.session

	# 如果Browser还没有session，需要先启动
	if hasattr(browser, 'get_browser_session'):
		return await browser.get_browser_session()

	# 最后尝试直接返回，让后续代码处理错误
	return browser


async def capture_full_page_cdp(browser) -> str | None:
	"""
	使用CDP原生方式截取完整页面（改进版：调整视口大小以匹配页面）

	Args:
		browser: Browser或BrowserSession实例

	Returns:
		Base64编码的截图数据，失败返回None
	"""
	raise RuntimeError("Screenshot capture has been removed; use extract_page_content() instead.")
	try:
		# 获取BrowserSession实例
		browser_session = await get_browser_session(browser)

		# 使用BrowserSession的CDP会话直接截图
		cdp_session = await browser_session.get_or_create_cdp_session()

		# 0. 展开所有内部滚动容器和隐藏容器（解决vuescroll等自定义滚动组件的问题）
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': '''
					(() => {
						// 找到所有可能限制内容显示的容器并展开
						document.querySelectorAll('*').forEach(el => {
							const style = getComputedStyle(el);
							const overflow = style.overflow;
							const overflowY = style.overflowY;
							
							// 处理 scroll/auto 容器
							if (overflow === 'auto' || overflow === 'scroll' ||
								overflowY === 'auto' || overflowY === 'scroll') {
								if (el.scrollHeight > el.clientHeight) {
									el.style.overflow = 'visible';
									el.style.overflowY = 'visible';
									el.style.maxHeight = 'none';
									el.style.height = 'auto';
								}
							}
							
							// 处理 hidden 容器（vuescroll 等自定义滚动组件）
							if (overflow === 'hidden' || overflowY === 'hidden') {
								// 检查是否是滚动组件的父容器
								if (el.querySelector('[class*="__panel"]') || 
									el.classList.contains('__vuescroll') ||
									el.classList.contains('home') ||
									el.scrollHeight > el.clientHeight) {
									el.style.overflow = 'visible';
									el.style.overflowY = 'visible';
									el.style.maxHeight = 'none';
									el.style.height = 'auto';
								}
							}
						});
						
						// 强制 html 和 body 也展开
						document.documentElement.style.overflow = 'visible';
						document.documentElement.style.height = 'auto';
						document.body.style.overflow = 'visible';
						document.body.style.height = 'auto';
					})()
				''',
				'returnByValue': True
			},
			session_id=cdp_session.session_id
		)
		await asyncio.sleep(0.3)

		# 1. 先滚动到底部让懒加载内容加载
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'window.scrollTo(0, document.body.scrollHeight)',
				'returnByValue': True
			},
			session_id=cdp_session.session_id
		)
		await asyncio.sleep(1)  # 等待内容加载

		# 滚动回顶部
		await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'window.scrollTo(0, 0)',
				'returnByValue': True
			},
			session_id=cdp_session.session_id
		)
		await asyncio.sleep(0.5)

		# 2. 获取页面完整尺寸
		metrics_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """
					(() => ({
						width: Math.max(
							document.body.scrollWidth,
							document.documentElement.scrollWidth,
							document.body.offsetWidth,
							document.documentElement.offsetWidth,
							document.body.clientWidth,
							document.documentElement.clientWidth
						),
						height: Math.max(
							document.body.scrollHeight,
							document.documentElement.scrollHeight,
							document.body.offsetHeight,
							document.documentElement.offsetHeight,
							document.body.clientHeight,
							document.documentElement.clientHeight
						)
					}))()
				""",
				'returnByValue': True
			},
			session_id=cdp_session.session_id
		)

		metrics = metrics_result.get('result', {}).get('value', {})
		page_width = metrics.get('width', 1920)
		page_height = metrics.get('height', 1080)

		logger.debug(f"页面尺寸: {page_width}x{page_height}")

		# 3. 使用clip参数截取完整页面
		result = await cdp_session.cdp_client.send.Page.captureScreenshot(
			params={
				'format': 'png',
				'captureBeyondViewport': True,
				'clip': {
					'x': 0,
					'y': 0,
					'width': page_width,
					'height': page_height,
					'scale': 1
				}
			},
			session_id=cdp_session.session_id
		)

		if result and 'data' in result:
			return result['data']
		return None

	except Exception as e:
		logger.debug(f"CDP原生截图失败: {e}")
		return None


async def capture_full_page_stitch(browser) -> str | None:
	raise RuntimeError("Screenshot capture has been removed; use extract_page_content() instead.")
	"""
	使用滚动拼接方式截取完整页面（降级方案）

	Args:
		browser: Browser或BrowserSession实例

	Returns:
		Base64编码的截图数据，失败返回None
	"""
	try:
		# 获取BrowserSession实例
		browser_session = await get_browser_session(browser)

		# 获取CDP会话
		cdp_session = await browser_session.get_or_create_cdp_session()

		# 获取页面总高度和视口高度
		metrics_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """
					(() => ({
						totalHeight: document.documentElement.scrollHeight,
						viewportHeight: window.innerHeight,
						viewportWidth: window.innerWidth
					}))()
				""",
				'returnByValue': True
			},
			session_id=cdp_session.session_id
		)

		metrics = metrics_result.get('result', {}).get('value', {})
		total_height = metrics.get('totalHeight', 0)
		viewport_height = metrics.get('viewportHeight', 0)

		if not total_height or not viewport_height:
			logger.error("无法获取页面尺寸")
			return None

		# 如果页面不需要滚动，直接截图
		if total_height <= viewport_height:
			result = await cdp_session.cdp_client.send.Page.captureScreenshot(
				params={'format': 'png'},
				session_id=cdp_session.session_id
			)
			if result and 'data' in result:
				return result['data']

		# 分段截图
		screenshots = []
		scroll_position = 0

		while scroll_position < total_height:
			# 滚动到指定位置
			await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': f'window.scrollTo(0, {scroll_position})',
					'returnByValue': True
				},
				session_id=cdp_session.session_id
			)
			await asyncio.sleep(0.5)  # 等待渲染

			# 截取当前视口
			result = await cdp_session.cdp_client.send.Page.captureScreenshot(
				params={'format': 'png'},
				session_id=cdp_session.session_id
			)

			if result and 'data' in result:
				img_data = base64.b64decode(result['data'])
				img = Image.open(BytesIO(img_data))
				screenshots.append(img)

			scroll_position += viewport_height

		# 拼接图片
		if not screenshots:
			return None

		# 计算总高度
		total_width = screenshots[0].width
		combined_height = sum(img.height for img in screenshots)

		# 创建空白画布
		combined_image = Image.new('RGB', (total_width, combined_height))

		# 粘贴每张截图
		y_offset = 0
		for img in screenshots:
			combined_image.paste(img, (0, y_offset))
			y_offset += img.height

		# 转换为Base64
		buffered = BytesIO()
		combined_image.save(buffered, format="PNG")
		img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

		return img_base64

	except Exception as e:
		logger.error(f"拼接截图失败: {e}")
		return None


async def capture_full_page(browser, title: str) -> str | None:
	"""
	完整页面截图（混合方案）
	优先使用CDP原生，失败则降级到拼接方式

	Args:
		browser: Browser或BrowserSession实例
		title: 页面标题（用于日志）

	Returns:
		Base64编码的截图数据
	"""
	raise RuntimeError("Screenshot capture has been removed; use extract_page_content() instead.")
	# 方案1：尝试CDP原生
	logger.info(f"[{title}] 使用CDP原生方式截取完整页面...")
	screenshot = await capture_full_page_cdp(browser)

	if screenshot:
		logger.info(f"[{title}] ✓ CDP截图成功")
		return screenshot

	# 方案2：降级到拼接
	logger.warning(f"[{title}] ⚠️ CDP原生截图失败")
	logger.info(f"[{title}] 降级使用拼接方式截取...")

	screenshot = await capture_full_page_stitch(browser)

	if screenshot:
		logger.info(f"[{title}] ✓ 拼接截图成功")
		return screenshot

	logger.error(f"[{title}] ✗ 截图失败")
	return None


def save_screenshot(screenshot_base64: str, filepath: Path) -> bool:
	raise RuntimeError("Saving screenshots has been removed; save the JSON with announcementContent instead.")
	"""
	保存Base64截图到文件

	Args:
		screenshot_base64: Base64编码的图片
		filepath: 保存路径

	Returns:
		是否成功
	"""
	try:
		# 解码并保存
		img_data = base64.b64decode(screenshot_base64)
		with open(filepath, 'wb') as f:
			f.write(img_data)
		return True
	except Exception as e:
		logger.error(f"保存截图失败: {e}")
		return False


# ============ Agent 自定义工具 ============

import hashlib
import json
import yaml
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field
from browser_use import Agent
from browser_use.tools.service import Tools
from .config_manager import load_extract_fields, generate_extract_prompt
from .prompts import GLOBAL_RULES
from .address_normalizer import extract_admin_divisions_from_details
from .deepseek_langchain import invoke_structured
from .structured_schemas import build_extract_fields_model
from .field_schemas import (
	LotProducts,
	LotCandidates,
	try_normalize_announcement_type,
	_to_yuan,
	normalize_date_ymd,
	normalize_estimated_amount,
)
from .announcement_type_repair import repair_announcement_type


# 全局缓存字段配置和提示词（避免每次调用都读取文件）
_extract_fields_cache: dict[str, list] = {}
_extract_prompt_cache: dict[str, str] = {}


_CN_PROVINCES = [
	"北京市",
	"天津市",
	"上海市",
	"重庆市",
	"河北省",
	"山西省",
	"辽宁省",
	"吉林省",
	"黑龙江省",
	"江苏省",
	"浙江省",
	"安徽省",
	"福建省",
	"江西省",
	"山东省",
	"河南省",
	"湖北省",
	"湖南省",
	"广东省",
	"海南省",
	"四川省",
	"贵州省",
	"云南省",
	"陕西省",
	"甘肃省",
	"青海省",
	"台湾省",
	"内蒙古自治区",
	"广西壮族自治区",
	"西藏自治区",
	"宁夏回族自治区",
	"新疆维吾尔自治区",
	"香港特别行政区",
	"澳门特别行政区",
]

_COMMON_FOREIGN_COUNTRIES = [
	"马尔代夫",
	"美国",
	"英国",
	"日本",
	"韩国",
	"俄罗斯",
	"法国",
	"德国",
	"新加坡",
	"澳大利亚",
	"加拿大",
	"意大利",
	"西班牙",
	"印度",
	"越南",
	"泰国",
	"印度尼西亚",
	"印尼",
	"菲律宾",
	"阿联酋",
	"沙特",
	"巴西",
	"墨西哥",
	"南非",
	"埃及",
	"土耳其",
	"瑞士",
	"荷兰",
	"比利时",
	"瑞典",
	"挪威",
	"芬兰",
	"丹麦",
	"新西兰",
]


@dataclass(frozen=True)
class AddressParts:
	country: str = ""
	province: str = ""
	city: str = ""
	district: str = ""


def _extract_country_from_text(text: str) -> str:
	"""
	尽量从地址文本中提取国家信息；若无法识别返回空字符串。
	"""
	s = (text or "").strip()
	if not s:
		return ""
	if "中华人民共和国" in s or "中国" in s:
		return "中国"

	for name in _COMMON_FOREIGN_COUNTRIES:
		if name and name in s:
			return name
	return ""


def _parse_address_parts_from_detail(detail: str) -> AddressParts:
	"""
	从“详细地址（全地址）”中尽量解析出 country/province/city/district。
	规则偏向中国地址；解析失败则返回空字符串。
	"""
	text = (detail or "").strip()
	if not text:
		return AddressParts()

	# Country: explicit mention (or common foreign countries)
	country = _extract_country_from_text(text)
	# 若明确为非中国国家，则不再按中国行政区划规则解析省/市/区
	if country and country != "中国":
		return AddressParts(country=country, province="", city="", district="")

	province = ""
	for p in sorted(_CN_PROVINCES, key=len, reverse=True):
		if p in text:
			province = p
			break

	city = ""
	district = ""

	def _find_after(s: str, start_token: str, pattern: str) -> str:
		if not s or not start_token or start_token not in s:
			return ""
		after = s.split(start_token, 1)[1]
		m = re.search(pattern, after)
		return m.group(1) if m else ""

	# Municipality: city equals province
	if province in {"北京市", "天津市", "上海市", "重庆市"}:
		city = province
		district = _find_after(text, province, r"^(.{1,20}?(?:区|县|旗))")
	else:
		if province:
			city = _find_after(text, province, r"^(.{1,20}?(?:市|自治州|地区|盟))")
		if not city:
			m_city = re.search(r"(.{1,20}?(?:市|自治州|地区|盟))", text)
			city = m_city.group(1) if m_city else ""

		if city:
			district = _find_after(text, city, r"^(.{1,20}?(?:区|县|旗))")

	# 默认规则：当无法从 AddressDetail 识别国家信息时，默认中国
	if not country:
		country = "中国"

	return AddressParts(country=country, province=province, city=city, district=district)

TYPE_DEFAULTS = {
	"string": "",
	"number": None,
	"boolean": False,
	"array": [],
}


def compute_data_id(payload: dict) -> str:
	"""
	为单条返回数据生成稳定的唯一标识（用于同站点重复爬取去重）。

	说明：
	- 以 JSON 序列化后的内容为输入（sort_keys=True）计算 SHA256
	- 会忽略自身字段 `dataId`，避免递归
	"""
	data = dict(payload or {})
	data.pop("dataId", None)
	raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
	return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_extracted_text(text: str) -> str:
	"""
	将提取到的长文本做最小归一化（不改变语义）：
	- 统一换行符为 \\n
	- 去掉行尾多余空白
	- 连续空行压缩为最多 1 个空行
	"""
	s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
	# strip trailing spaces per line
	lines = [ln.rstrip() for ln in s.split("\n")]
	s = "\n".join(lines).strip()
	s = re.sub(r"\n{3,}", "\n\n", s)
	return s


def _unescape_control_chars_outside_strings(text: str) -> str:
	"""
	LLM/Agent 有时会把换行写成字面量 "\\n"（以及 "\\t"/"\\r"），导致整体不再是合法 JSON/YAML。

	此函数只在 *非字符串上下文* 下把这些转义序列还原为真实空白字符，
	避免把字符串值里的 "\\n" 变成真实换行从而破坏 JSON。
	"""
	out: list[str] = []
	in_string = False
	escape = False
	i = 0
	while i < len(text):
		ch = text[i]

		if in_string:
			out.append(ch)
			if escape:
				escape = False
			else:
				if ch == "\\":
					escape = True
				elif ch == '"':
					in_string = False
			i += 1
			continue

		# 非字符串上下文
		if ch == '"':
			in_string = True
			out.append(ch)
			i += 1
			continue

		# 处理 \\n/\\r/\\t（仅限非字符串）
		if ch == "\\" and i + 1 < len(text):
			nxt = text[i + 1]
			if nxt == "n":
				out.append("\n")
				i += 2
				continue
			if nxt == "r":
				out.append("\r")
				i += 2
				continue
			if nxt == "t":
				out.append("\t")
				i += 2
				continue

		out.append(ch)
		i += 1

	return "".join(out)


def get_extract_fields(stage: str) -> list:
	"""
	获取字段配置列表（按 stage 缓存）
	"""
	global _extract_fields_cache

	stage = (stage or "").strip() or "flat"
	if stage not in _extract_fields_cache:
		try:
			_extract_fields_cache[stage] = load_extract_fields(stage=stage)
		except FileNotFoundError:
			_extract_fields_cache[stage] = []

	return _extract_fields_cache[stage]


def get_extract_prompt(stage: str, *, product_category_table: str | None = None) -> str:
	"""
	获取字段提取提示词（按 stage 缓存）
	"""
	global _extract_prompt_cache

	stage = (stage or "").strip() or "flat"
	product_category_table = (product_category_table or "").strip() or None
	if product_category_table:
		# Per-request prompt override: do NOT cache to avoid cross-request leakage.
		fields = get_extract_fields(stage)
		return (
			generate_extract_prompt(fields, stage=stage, product_category_table=product_category_table)
			if fields
			else ""
		)
	if stage not in _extract_prompt_cache:
		fields = get_extract_fields(stage)
		_extract_prompt_cache[stage] = generate_extract_prompt(fields, stage=stage) if fields else ""

	return _extract_prompt_cache[stage]


async def extract_fields_from_page(
	browser_session,
	llm,
	site_name: str,
	stage: str,
	*,
	product_category_table: str | None = None,
) -> dict:
	"""
	使用 Agent 从当前详情页提取字段（V2）

	Args:
		browser_session: 浏览器会话
		llm: LLM 实例
		site_name: 网站名称
		stage: flat / lots

	Returns:
		提取的字段字典（已归一化），提取失败返回空值字典
	"""
	stage = (stage or "").strip() or "flat"
	extract_prompt = get_extract_prompt(stage, product_category_table=product_category_table)
	fields = get_extract_fields(stage)

	# 如果没有配置字段，返回空字典
	if not extract_prompt or not fields:
		return {}

	# 根据类型生成空值字典
	empty_result = {f.key: TYPE_DEFAULTS.get(f.type, "") for f in fields}

	try:
		logger.info(f"[{site_name}] 正在提取详情页字段（stage={stage}）...")

		extract_agent = Agent(
			task=f"""
{extract_prompt}

**重要提示：**
- 仔细阅读页面内容，提取上述所有字段
- 按类型填写空值（string填\"\"，number填null，array填[]）
- 金额字段单位为“元”，如页面为“万元/亿”需换算成“元”
- 日期字段格式为 YYYY-MM-DD（如 2026-02-16）
- 只返回 JSON，不要解释、不要代码块
- 不要执行任何点击或导航操作，只读取当前页面
			""",
			llm=llm,
			browser=browser_session,
			extend_system_message=GLOBAL_RULES,
			max_failures=5,
			step_timeout=600,
		)

		result = await extract_agent.run(max_steps=99999)
		output = result.final_result()

		if not output:
			logger.warning(f"[{site_name}] 字段提取无返回（stage={stage}）")
			return empty_result

		# 尝试解析 JSON
		try:
			output_str = str(output).strip()

			# 处理转义引号（Agent 输出可能包含 \\\" 而非 \"）
			if '\\"' in output_str:
				output_str = output_str.replace('\\"', '"')

			# 移除可能的 markdown 代码块标记
			output_str = re.sub(r'^```json\\s*', '', output_str)
			output_str = re.sub(r'^```\\s*', '', output_str)
			output_str = re.sub(r'\\s*```$', '', output_str)

			# 提取 JSON/YAML 片段：优先 {..}，否则 [..]，否则尝试整段解析
			obj_start = output_str.find('{')
			obj_end = output_str.rfind('}')
			arr_start = output_str.find('[')
			arr_end = output_str.rfind(']')

			if obj_start != -1 and obj_end > obj_start:
				snippet = output_str[obj_start:obj_end + 1]
			elif arr_start != -1 and arr_end > arr_start:
				snippet = output_str[arr_start:arr_end + 1]
			else:
				snippet = output_str

			# 去掉常见的结尾多余逗号（LLM 有时会输出 trailing comma）
			snippet = re.sub(r',(\s*[}\]])', r'\1', snippet)

			# 有些 Agent 会输出字面量 "\n"（而非真实换行），先做一次安全还原
			snippet = _unescape_control_chars_outside_strings(snippet)

			# 先按严格 JSON 解析，失败则降级为 YAML（容忍单引号/不加引号 key）
			try:
				extracted = json.loads(snippet)
			except json.JSONDecodeError as e_json:
				try:
					extracted = yaml.safe_load(snippet)
					if extracted is None:
						extracted = {}
				except Exception as e_yaml:
					logger.warning(
						f"[{site_name}] JSON/YAML 解析失败（stage={stage}）: {e_json} / {e_yaml}"
					)
					return empty_result

			# stage=lots 允许 LLM 直接返回数组，按内容推断属于哪个字段
			if stage == "lots" and isinstance(extracted, list):
				candidate_marker_keys = {"type", "candidates", "candidatePrices", "candidate_prices", "winner", "winningAmount", "winning_amount"}
				has_candidate_keys = any(
					isinstance(x, dict) and any(k in x for k in candidate_marker_keys)
					for x in extracted
				)
				extracted = {
					"lotProducts": [] if has_candidate_keys else extracted,
					"lotCandidates": extracted if has_candidate_keys else [],
				}

			if not isinstance(extracted, dict):
				logger.warning(f"[{site_name}] 解析结果不是对象（stage={stage}），返回空值")
				return empty_result

			# 顶层 key 容错：支持 snake_case（如 lot_products）
			for f in fields:
				if f.key in extracted:
					continue
				snake = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', f.key).lower()
				if snake in extracted:
					extracted[f.key] = extracted.get(snake)

			# 类型归一化
			normalized: dict = {}
			for f in fields:
				raw_value = extracted.get(f.key, TYPE_DEFAULTS.get(f.type, ""))
				normalized[f.key] = normalize_field_value(f.key, raw_value, f.type)

			logger.info(f"[{site_name}] ✓ 字段提取成功（stage={stage}）")
			return normalized

		except json.JSONDecodeError as e:
			logger.warning(f"[{site_name}] JSON 解析失败（stage={stage}）: {e}")
			return empty_result

	except Exception as e:
		logger.error(f"[{site_name}] 字段提取失败（stage={stage}）: {e}")
		return empty_result


def _sanitize_html_for_extraction(html: str, *, site_name: str, max_chars: int = 200_000) -> str:
	"""
	Lightweight, non-LLM HTML cleanup before sending to DeepSeek for field extraction.

	Goals:
	- Remove obvious noise (scripts/styles/nav/footer/meta/etc).
	- Strip attributes (style/class/id) that add tokens but not semantics.
	- Preserve structural tags, especially tables, so the model can read tabular data.
	"""
	html = (html or "").strip()
	if not html:
		return ""

	try:
		from bs4 import BeautifulSoup, Comment
	except Exception as e:  # pragma: no cover
		# Fallback: minimal cleanup without bs4.
		logger.warning(f"[{site_name}] bs4 不可用，跳过 HTML 清洗: {e}")
		return html[:max_chars] if max_chars and len(html) > max_chars else html

	soup = BeautifulSoup(html, "html.parser")

	# Some sites embed the real "announcement content" inside same-origin iframes via `srcdoc`.
	# If we later drop iframes (common cleanup step), we'd lose the main content entirely.
	# Inline meaningful `iframe[srcdoc]` content early so subsequent cleanup preserves it.
	for iframe in soup.find_all("iframe"):
		srcdoc_raw = ""
		with contextlib.suppress(Exception):
			srcdoc_raw = iframe.get("srcdoc") or ""
		srcdoc = str(srcdoc_raw).strip()
		if not srcdoc or len(srcdoc) < 1000:
			continue
		try:
			inner = BeautifulSoup(srcdoc, "html.parser")
			inner_root = inner.body or inner
			wrapper = soup.new_tag("div")
			for child in list(getattr(inner_root, "contents", []) or []):
				wrapper.append(child)
			iframe.replace_with(wrapper)
		except Exception:
			# As a last resort, keep plain text so we don't return an empty body.
			try:
				inner_text = BeautifulSoup(srcdoc, "html.parser").get_text(" ", strip=True)
			except Exception:
				inner_text = ""
			if inner_text:
				iframe.replace_with(soup.new_string(inner_text))
			else:
				iframe.decompose()

	# Remove comments.
	for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
		c.extract()

	# Remove very noisy / non-content tags.
	for el in soup.select(
		"script,style,noscript,svg,canvas,header,nav,footer,aside,"
		"form,input,button,select,option,textarea,meta,link,title,head"
	):
		el.decompose()

	# Remove hidden nodes.
	for el in soup.select('[hidden], [aria-hidden="true"], [role="dialog"], [aria-modal="true"]'):
		el.decompose()
	for el in soup.select("[style]"):
		style_raw = ""
		with contextlib.suppress(Exception):
			style_raw = el.get("style") or ""
		style = str(style_raw).replace(" ", "").lower()
		if "display:none" in style or "visibility:hidden" in style:
			el.decompose()

	# Drop inline/base64 images; keep alt text if present.
	for img in soup.find_all("img"):
		alt_raw = ""
		with contextlib.suppress(Exception):
			alt_raw = img.get("alt") or ""
		alt = str(alt_raw).strip()
		if alt:
			img.replace_with(soup.new_string(alt))
		else:
			img.decompose()

	# Unwrap token-heavy inline tags; keep their text/content.
	for tag_name in ("span", "font"):
		for el in soup.find_all(tag_name):
			el.unwrap()

	# Strip most attributes to reduce tokens; preserve a[href] and table cell spans.
	for el in soup.find_all(True):
		attrs = dict(el.attrs or {})
		keep: dict[str, str] = {}
		if el.name == "a":
			href = attrs.get("href")
			if href:
				keep["href"] = href
		if el.name in {"td", "th"}:
			for k in ("rowspan", "colspan"):
				v = attrs.get(k)
				if v is not None:
					keep[k] = str(v)
		el.attrs = keep

	# Normalize text nodes: collapse non-breaking spaces.
	for t in soup.find_all(string=True):
		if isinstance(t, str):
			t.replace_with(t.replace("\xa0", " "))

	clean = str(soup)

	# Merge adjacent formatting/paragraph tags to reduce token noise.
	# Example: <strong>..</strong><strong>..</strong> -> <strong>....</strong>
	# Example: <p>..</p><p>..</p> -> <p>....</p>
	clean = re.sub(r"</strong>\s*<strong>", "", clean, flags=re.IGNORECASE)
	clean = re.sub(r"</p>\s*<p>", "", clean, flags=re.IGNORECASE)
	# # Remove <br> line breaks to reduce token noise.
	# clean = re.sub(r"<br\s*/?>", "", clean, flags=re.IGNORECASE)
	# Remove full-width question marks commonly used as masking/placeholder separators in some tender pages.
	# Use a whitespace-tolerant pattern so "账 ？ 号" becomes "账号".
	clean = re.sub(r"\s*？\s*", "", clean)

	# Hard cap to avoid extremely large prompts.
	if max_chars and len(clean) > max_chars:
		logger.info(f"[{site_name}] HTML 清洗后仍过长，截断到 {max_chars} 字符用于字段抽取")
		clean = clean[:max_chars]

	return clean.strip()


async def extract_fields_from_html(
	html: str,
	*,
	site_name: str,
	stage: str,
	product_category_table: str | None = None,
) -> dict:
	"""
	Use DeepSeek-V3.2 (OpenAI protocol via SiliconFlow/SANY gateway) to extract fields from a single HTML blob.
	Only replaces the *detail field extraction* step; navigation still uses browser-use model.
	"""
	stage = (stage or "").strip() or "flat"
	extract_prompt = get_extract_prompt(stage, product_category_table=product_category_table)
	fields = get_extract_fields(stage)
	if not extract_prompt or not fields:
		return {}

	html = _sanitize_html_for_extraction(html, site_name=site_name)
	empty_result = {f.key: TYPE_DEFAULTS.get(f.type, "") for f in fields}
	if not html:
		return empty_result

	system_prompt = f"""
You are an information extraction engine.
You will be given an HTML snippet of a tender/notice detail page.
Extract the requested fields according to the schema below and return ONLY valid JSON.
No markdown, no code fences, no extra text.

{extract_prompt}

Rules:
- Fill missing fields with the correct empty value by type (string=\"\", number=null, array=[]).
- Special rule for estimatedAmount:
  - Only output estimatedAmount when announcementType is one of: 招标 / 询价 / 竞谈 / 单一 / 竞价 / 邀标. For other types, output empty string.
  - Priority (high -> low):
    1) If there is an explicit awarded/winning/transaction amount in the input (e.g. 中标金额/成交金额/定标金额/授标金额),
       set estimatedAmount to that amount in yuan as a single number string (no commas).
       Prefer the winning supplier's amount; if missing, use the first candidate's bid price as fallback.
    2) Otherwise, if procurement items / BOQ / service scope exist (标的物/采购清单/服务范围),
       estimate a reasonable amount in yuan as either a single number string or a range \"lo~hi\".
    3) Otherwise output empty string (do not guess).
  - The estimate MUST be derived mainly from the procurement items (标的物), quantities, specs, service scope, and similar signals.
    Do NOT use irrelevant fees (e.g. document price, service fee, deposit, CA/platform fees) as the estimate.
- Money amounts are in 单位“元” (convert 万/亿 to 元 if needed).
- Dates are YYYY-MM-DD.
""".strip()

	user_prompt = f"HTML:\\n{html}"

	try:
		Schema = build_extract_fields_model(fields, model_name=f"ExtractFields_{stage}")
		result = await asyncio.to_thread(
			invoke_structured,
			[
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
			Schema,
		)
	except Exception as e:
		logger.warning(f"[{site_name}] DeepSeek 字段提取调用失败（stage={stage}）: {e}")
		return empty_result

	extracted = result.model_dump() if hasattr(result, "model_dump") else {}
	normalized: dict = {}
	for f in fields:
		raw_value = extracted.get(f.key, TYPE_DEFAULTS.get(f.type, ""))
		normalized[f.key] = normalize_field_value(f.key, raw_value, f.type)

	logger.info(f"[{site_name}] ✓ 字段提取成功（stage={stage}）")
	return normalized


_ENGINEERING_MACHINERY_CLASSIFY_SYSTEM_PROMPT = """
You are a strict binary classifier.
Given a Chinese tender/notice 项目名称 (projectName) and optionally the 公告标题 (announcementTitle),
decide whether the project is related to 工程机械类 (engineering / construction machinery).

INCLUDE (examples, not exhaustive):
- Construction machinery /工程机械 equipment and related spare parts/services:
  挖掘机/装载机/推土机/压路机/摊铺机/铣刨机/平地机/履带式设备/工程车辆/矿卡/非公路矿用自卸车
- Lifting/hoisting machinery commonly considered engineering machinery:
  起重机/吊车/塔吊/履带吊/汽车吊/门式起重机/桥式起重机/架桥机
- Foundation/drilling/tunneling machinery:
  旋挖钻/钻机/打桩机/盾构/盾构机/TBM/隧道掘进机
- Concrete machinery:
  混凝土泵/泵车/搅拌站/拌合站/搅拌车
- Aerial work platforms and similar heavy equipment.
- The above equipment's 配件/备件/维修/保养/租赁/改造 that clearly targets such machinery.

EXCLUDE (examples):
- Pure civil works/施工 without a clear machinery procurement/service focus.
- General materials (钢材/食材/办公用品), IT/software, property/catering services, etc.
- Generic electrical equipment (电机/水泵/配电柜) unless clearly a part of engineering machinery.

Decision rule:
- If projectName clearly indicates engineering machinery: return true.
- If clearly unrelated: return false.
- If uncertain/too generic: return true (prefer keep to avoid false negatives).

Return ONLY valid JSON. No markdown, no code fences, no extra text.
Schema:
{"isEngineeringMachinery": true, "confidence": "high|medium|low", "reason": "short Chinese reason"}
""".strip()


class EngineeringMachineryClassification(BaseModel):
	isEngineeringMachinery: bool | None = None
	confidence: str = ""
	reason: str = ""


async def llm_is_engineering_machinery_project(
	project_name: str,
	*,
	title: str | None,
	site_name: str,
) -> tuple[bool | None, str]:
	"""
	LLM-based category judgement for 项目名称.

	Returns: (decision, reason)
	- decision=True: keep (工程机械类)
	- decision=False: skip (非工程机械类)
	- decision=None: unknown (callers should keep to avoid accidental data loss)
	"""
	project_name = (project_name or "").strip()
	title = (title or "").strip()
	if not project_name:
		return None, "empty_projectName"

	user_prompt = f"""projectName: {project_name}
announcementTitle: {title}""".strip()

	try:
		result = await asyncio.to_thread(
			invoke_structured,
			[
				{"role": "system", "content": _ENGINEERING_MACHINERY_CLASSIFY_SYSTEM_PROMPT},
				{"role": "user", "content": user_prompt},
			],
			EngineeringMachineryClassification,
		)
	except Exception as e:
		logger.warning(f"[{site_name}] 工程机械类判定 LLM 调用失败: {e}")
		return None, f"llm_error: {e}"

	decision = result.isEngineeringMachinery
	reason = (result.reason or "").strip()
	conf = (result.confidence or "").strip()
	if conf:
		reason = f"{conf}: {reason}".strip(": ").strip()
	if len(reason) > 200:
		reason = reason[:200]

	return decision, reason or ""


_ESTIMATED_AMOUNT_VALUE_RE = re.compile(r"^\d+(?:\.\d+)?(?:~\d+(?:\.\d+)?)?$")


def normalize_field_value(key: str, value: Any, field_type: str):
	"""
	根据字段类型归一化值（V2）
	"""
	if field_type == "array":
		if key == "lotProducts":
			items = LotProducts.model_validate(value).root
			return [i.model_dump() for i in items]
		if key == "lotCandidates":
			items = LotCandidates.model_validate(value).root
			return [i.model_dump() for i in items]

		if value is None:
			return []
		if isinstance(value, list):
			return value
		if isinstance(value, dict):
			return [value]
		if isinstance(value, str):
			s = value.strip()
			if s.lower() in {"", "[]", "null", "none", "无", "暂无"}:
				return []
			try:
				parsed = json.loads(s)
				if isinstance(parsed, list):
					return parsed
				if isinstance(parsed, dict):
					return [parsed]
			except Exception:
				return []
		return []

	if field_type == "number":
		return _to_yuan(value)

	if field_type == "boolean":
		if isinstance(value, bool):
			return value
		s = str(value).strip().lower()
		return s in {"true", "1", "yes", "是"}

	# string
	text = "" if value is None else str(value).strip()
	if key in {"announcementDate", "bidOpenDate"}:
		return normalize_date_ymd(text)
	if key == "estimatedAmount":
		return normalize_estimated_amount(text)
	return text


async def click_show_full_info(browser_session) -> bool:
	"""
	尝试点击"查看完整信息"按钮（如果存在）

	某些网站会隐藏联系人信息（显示为带星号的脱敏内容），
	需要点击按钮才能展开完整信息。

	Args:
		browser_session: 浏览器会话

	Returns:
		是否成功点击了按钮
	"""
	try:
		cdp_session = await browser_session.get_or_create_cdp_session()

		# 使用 JavaScript 查找并点击"查看完整信息"相关按钮
		click_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': """
					(() => {
						// 常见的"查看完整信息"按钮文本（精确匹配）
						const keywords = ['查看完整信息', '查看完整', '显示完整', '展开全部', '查看全部'];

						// 查找包含关键词的可点击元素（精确匹配，文本长度限制）
						const allElements = document.querySelectorAll('a, button, span, div');
						for (const el of allElements) {
							const text = el.textContent?.trim() || '';
							// 只匹配文本长度较短的元素（避免匹配到大容器）
							if (text.length > 20) continue;

							for (const keyword of keywords) {
								if (text === keyword || text.includes(keyword)) {
									el.click();
									return { clicked: true, text: text };
								}
							}
						}
						return { clicked: false };
					})()
				""",
				'returnByValue': True
			},
			session_id=cdp_session.session_id
		)

		result = click_result.get('result', {}).get('value', {})
		if result.get('clicked'):
			logger.info(f"✓ 已点击「{result.get('text', '查看完整信息')}」按钮")
			await asyncio.sleep(1)  # 等待内容加载
			return True
		return False

	except Exception as e:
		logger.debug(f"查找完整信息按钮时出错: {e}")
		return False


def _html_to_clean_markdown(html: str, site_name: str) -> str:
	"""
	Convert raw HTML to a cleaner Markdown:
	- Remove global chrome (header/nav/footer), hidden junk, and images
	- Prefer main content containers when possible
	- Keep tables/structure as much as markdownify allows
	"""
	if not html:
		return ""

	clean_html = html
	try:
		from bs4 import BeautifulSoup
	except Exception as e:  # pragma: no cover
		logger.warning(f"[{site_name}] bs4 不可用，跳过 HTML 清理: {e}")
		BeautifulSoup = None  # type: ignore[assignment]

	if BeautifulSoup is not None:
		soup = BeautifulSoup(html, "html.parser")

		# Drop non-content / noisy nodes.
		for el in soup.select(
			"script,style,noscript,svg,canvas,header,nav,footer,aside,"
			"form,input,button,select,option,textarea"
		):
			el.decompose()

		# Convert iframes to links (some sites embed the main content in an iframe).
		for iframe in soup.find_all("iframe"):
			src = (iframe.get("src") or "").strip()
			if not src:
				iframe.decompose()
				continue
			p = soup.new_tag("p")
			a = soup.new_tag("a", href=src)
			a.string = src
			p.append(a)
			iframe.replace_with(p)

		# Drop hidden elements (common for popups/captcha modals living in DOM).
		for el in soup.select('[hidden], [aria-hidden="true"], [role="dialog"], [aria-modal="true"]'):
			el.decompose()
		for el in soup.select("[style]"):
			style = (el.get("style") or "").replace(" ", "").lower()
			if "display:none" in style or "visibility:hidden" in style:
				el.decompose()

		# Remove images (especially base64/site icons) — keep alt text if present.
		for img in soup.find_all("img"):
			alt = (img.get("alt") or "").strip()
			if alt:
				img.replace_with(soup.new_string(alt))
			else:
				img.decompose()

		# Prefer the main content container if we can find one.
		body = soup.body or soup
		candidate_nodes = []
		for selector in (
			"article",
			"main",
			"[role='main']",
			"#content,.content",
			"#main,.main",
			"#detail,.detail",
			"#article,.article",
			"#post,.post",
		):
			candidate_nodes.extend(body.select(selector))

		# Fallback: scan common containers and pick by text-density score.
		if not candidate_nodes:
			candidate_nodes = list(body.find_all(["article", "main", "section", "div"]))

		# Large pages can contain tons of <div>; pre-filter to keep it fast enough.
		if len(candidate_nodes) > 800:
			ranked = []
			for node in candidate_nodes:
				tlen = len(node.get_text(" ", strip=True))
				if tlen >= 200:
					ranked.append((tlen, node))
			ranked.sort(key=lambda x: x[0], reverse=True)
			candidate_nodes = [n for _, n in ranked[:300]]

		def _score(node) -> int:
			text_len = len(node.get_text(" ", strip=True))
			if text_len < 200:
				return -10**9
			links = node.find_all("a")
			link_text_len = sum(len(a.get_text(" ", strip=True)) for a in links)
			num_links = len(links)
			num_li = len(node.find_all("li"))
			num_tables = len(node.find_all("table"))
			# Prefer rich text/tables; penalize navigation-y blocks dominated by links/lists.
			return text_len - link_text_len * 2 - num_links * 20 - num_li * 5 + num_tables * 80

		best = max(candidate_nodes, key=_score, default=None)
		clean_html = str(best) if best is not None else str(body)

	from markdownify import markdownify as html_to_md

	md = html_to_md(clean_html, heading_style="ATX", bullets="-")
	md = md.replace("\r\n", "\n")
	md = re.sub(r"\n{3,}", "\n\n", md).strip()
	if len(md) < 50 and clean_html != html:
		# Fallback: return the full-page conversion rather than an empty/near-empty result.
		md = html_to_md(html, heading_style="ATX", bullets="-")
		md = md.replace("\r\n", "\n")
		md = re.sub(r"\n{3,}", "\n\n", md).strip()
	return md


def _html_to_clean_content_html(html: str, site_name: str) -> str:
	"""
	Keep the original content (HTML) but aggressively remove non-content chrome.

	This preserves table structure for downstream processing, while avoiding
	markdown conversion artifacts.
	"""
	if not html:
		return ""
	try:
		from bs4 import BeautifulSoup, Comment
	except Exception as e:  # pragma: no cover
		logger.warning(f"[{site_name}] bs4 不可用，返回原始 HTML: {e}")
		return html

	soup = BeautifulSoup(html, "html.parser")

	# Some sites embed the real "announcement content" inside same-origin iframes via `srcdoc`.
	# If we later drop/convert iframes, we'd lose the main content entirely.
	# Inline meaningful `iframe[srcdoc]` content early so subsequent cleanup preserves it.
	for iframe in soup.find_all("iframe"):
		srcdoc_raw = ""
		with contextlib.suppress(Exception):
			srcdoc_raw = iframe.get("srcdoc") or ""
		srcdoc = str(srcdoc_raw).strip()
		if not srcdoc or len(srcdoc) < 1000:
			continue
		try:
			inner = BeautifulSoup(srcdoc, "html.parser")
			inner_root = inner.body or inner
			wrapper = soup.new_tag("div")
			for child in list(getattr(inner_root, "contents", []) or []):
				wrapper.append(child)
			iframe.replace_with(wrapper)
		except Exception:
			# As a last resort, keep plain text so we don't return an empty body.
			try:
				inner_text = BeautifulSoup(srcdoc, "html.parser").get_text(" ", strip=True)
			except Exception:
				inner_text = ""
			if inner_text:
				iframe.replace_with(soup.new_string(inner_text))
			else:
				iframe.decompose()

	# Remove comments.
	for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
		c.extract()

	# Remove noisy nodes.
	for el in soup.select(
		"script,style,noscript,svg,canvas,header,nav,footer,aside,"
		"form,input,button,select,option,textarea,meta,link,title,head"
	):
		el.decompose()

	# Drop hidden elements / dialogs.
	for el in soup.select('[hidden], [aria-hidden="true"], [role="dialog"], [aria-modal="true"]'):
		el.decompose()
	for el in soup.select("[style]"):
		style_raw = ""
		with contextlib.suppress(Exception):
			style_raw = el.get("style") or ""
		style = str(style_raw).replace(" ", "").lower()
		if "display:none" in style or "visibility:hidden" in style:
			el.decompose()

	# Remove images (base64/site icons etc) — keep alt if present.
	for img in soup.find_all("img"):
		alt_raw = ""
		with contextlib.suppress(Exception):
			alt_raw = img.get("alt") or ""
		alt = str(alt_raw).strip()
		if alt:
			img.replace_with(soup.new_string(alt))
		else:
			img.decompose()

	# Convert remaining iframes to links (best-effort); drop empty ones.
	for iframe in soup.find_all("iframe"):
		src_raw = ""
		with contextlib.suppress(Exception):
			src_raw = iframe.get("src") or ""
		src = str(src_raw).strip()
		if not src:
			iframe.decompose()
			continue
		p = soup.new_tag("p")
		a = soup.new_tag("a", href=src)
		a.string = src
		p.append(a)
		iframe.replace_with(p)

	# Unwrap token-heavy inline tags; keep their text/content.
	for tag_name in ("span", "font"):
		for el in soup.find_all(tag_name):
			el.unwrap()

	# Strip attributes (font/height/style/etc) to reduce noise. Preserve structural attrs.
	for el in soup.find_all(True):
		attrs = dict(el.attrs or {})
		keep: dict[str, str] = {}
		if el.name == "a":
			href = attrs.get("href")
			if href:
				keep["href"] = href
		if el.name in {"td", "th"}:
			for k in ("rowspan", "colspan"):
				v = attrs.get(k)
				if v is not None:
					keep[k] = str(v)
		el.attrs = keep

	# Normalize text nodes: collapse non-breaking spaces.
	for t in soup.find_all(string=True):
		if isinstance(t, str):
			t.replace_with(t.replace("\xa0", " "))

	# Return a clean HTML fragment.
	return str(soup)


async def extract_page_content(browser_session: BrowserSession, site_name: str) -> str:
	"""
	提取当前详情页的“正文容器”HTML（尽量保留表格/结构），不做 Markdown 转换。
	"""
	stage = "init"
	state_url: str | None = None
	try:
		stage = "browser_state_summary"
		with contextlib.suppress(Exception):
			state = await browser_session.get_browser_state_summary(include_screenshot=False)
			state_url = str(getattr(state, "url", "") or "").strip() or None

		stage = "get_or_create_cdp_session"
		cdp_session = await browser_session.get_or_create_cdp_session()
		html_result: Any | None = None
		stage = "runtime_evaluate"
		try:
			html_result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					"expression": """
(() => {
  // Try to extract the *detail content container* first.
  // Some sites render the main content inside same-origin iframes (e.g. srcdoc). In that case, prefer the iframe doc.
  // Some sites (e.g. sp.iccec.cn) have a huge navigation shell; returning full DOM makes Markdown very noisy.
  const keywords = ['公告内容', '公告标题', '项目编号', '发布时间', '附件列表', '物资信息', '相关公告列表'];
  const body = document.body || document.documentElement;
  if (!body) return '';

  // 0) Iframe-first: pick the iframe whose inner document has the most meaningful text.
  // (Parents' innerText won't include iframe document content, so the normal scorer would miss it.)
  const outerTextLen = (() => {
    try { return (body.innerText || '').trim().length; } catch (e) { return 0; }
  })();
  try {
    const iframes = Array.from(document.querySelectorAll('iframe'));
    let bestIframeHtml = '';
    let bestIframeTextLen = 0;
    for (const f of iframes) {
      // Same-origin / srcdoc iframe: read inner document directly.
      try {
        const doc = f.contentDocument;
        if (doc && doc.documentElement) {
          const t = ((doc.body && doc.body.innerText) ? doc.body.innerText : '').trim();
          const l = t.length;
          if (l > bestIframeTextLen) {
            const h = doc.documentElement.outerHTML || '';
            if (h && h.length > 500) {
              bestIframeTextLen = l;
              bestIframeHtml = h;
            }
          }
        }
      } catch (e) {}

      // If srcdoc exists, it's accessible even if contentDocument access is restricted.
      try {
        const srcdoc = f.getAttribute('srcdoc') || '';
        if (srcdoc && srcdoc.length > 1000) {
          // Rough text length estimate (strip tags).
          const l = srcdoc.replace(/<[^>]*>/g, ' ').replace(/\\s+/g, ' ').trim().length;
          if (l > bestIframeTextLen) {
            bestIframeTextLen = l;
            bestIframeHtml = srcdoc;
          }
        }
      } catch (e) {}
    }

    // Prefer iframe only when it is clearly more informative than the outer page.
    if (bestIframeHtml && bestIframeTextLen >= 800 && bestIframeTextLen >= outerTextLen * 2) {
      return bestIframeHtml;
    }
  } catch (e) {}

  function textOf(el) {
    try { return (el.innerText || '').trim(); } catch (e) { return ''; }
  }
  function count(el, selector) {
    try { return el.querySelectorAll(selector).length; } catch (e) { return 0; }
  }
  function score(el) {
    const t = textOf(el);
    const len = t.length;
    let hits = 0;
    for (const k of keywords) if (t.includes(k)) hits++;
    // Prefer containers that look like "detail" rather than nav menus.
    const links = count(el, 'a');
    const lis = count(el, 'li');
    const tables = count(el, 'table');
    return hits * 20000 + len + tables * 500 - links * 200 - lis * 50;
  }

  // 1) Fast path: common detail containers
  const selectorCandidates = [
    'article', 'main', "[role='main']",
    '#detail', '.detail', '.detail-content', '.detailCon', '.detail-con',
    '.notice-detail', '.noticeDetail', '.notice-detail-content',
    '#content', '.content', '#main', '.main'
  ];
  let best = null;
  let bestScore = -1e18;
  for (const sel of selectorCandidates) {
    const nodes = body.querySelectorAll(sel);
    for (const n of nodes) {
      const s = score(n);
      if (s > bestScore) { best = n; bestScore = s; }
    }
  }

  // 2) Keyword-driven: find nodes containing key labels and choose the best parent-like block
  if (!best) {
    const all = body.querySelectorAll('div,section,main,article');
    // pre-rank by text length to keep it fast
    const ranked = [];
    for (const n of all) {
      const t = textOf(n);
      ranked.push([t.length, n]);
    }
    ranked.sort((a,b) => b[0]-a[0]);
    const top = ranked.slice(0, 300).map(x => x[1]);
    for (const n of top) {
      const s = score(n);
      if (s > bestScore) { best = n; bestScore = s; }
    }
  }

  // 3) Fallback: full DOM snapshot then let Python-side cleanup handle it.
  const root = (best || document.documentElement || body).cloneNode(true);
  try { root.querySelectorAll('script,style,noscript').forEach(el => el.remove()); } catch (e) {}
  return root.outerHTML || '';
})()
""",
					"returnByValue": True,
				},
				session_id=cdp_session.session_id,
			)
		except Exception as eval_err:
			logger.debug(
				f"[{site_name}] Runtime.evaluate failed: {eval_err}"
				+ (f" url={state_url}" if state_url else "")
			)
			# Best-effort fallback: try a simpler outerHTML extraction.
			with contextlib.suppress(Exception):
				html_result = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={
						"expression": "(document.documentElement && document.documentElement.outerHTML) || ''",
						"returnByValue": True,
					},
					session_id=cdp_session.session_id,
				)

		stage = "parse_runtime_result"
		html = ""
		if isinstance(html_result, dict):
			exception_details = html_result.get("exceptionDetails")
			if exception_details:
				logger.debug(f"[{site_name}] Runtime.evaluate exceptionDetails: {exception_details}")
			r = html_result.get("result")
			if isinstance(r, dict):
				v = r.get("value")
				if isinstance(v, str):
					html = v
		elif html_result is None:
			logger.debug(
				f"[{site_name}] Runtime.evaluate returned None"
				+ (f" url={state_url}" if state_url else "")
			)
		elif html_result is not None:
			logger.debug(f"[{site_name}] Runtime.evaluate returned unexpected type: {type(html_result)}")

		if not html:
			return ""

		stage = "cleanup"
		try:
			return _html_to_clean_content_html(html, site_name=site_name).strip()
		except Exception as clean_err:
			logger.warning(
				f"[{site_name}] HTML cleanup failed, returning raw HTML: {clean_err}"
				+ (f" url={state_url}" if state_url else "")
			)
			return str(html).strip()
	except Exception:
		logger.exception(
			f"[{site_name}] 提取公告原文(HTML)失败: stage={stage}"
			+ (f" url={state_url}" if state_url else "")
		)
		return ""


class SaveDetailParams(BaseModel):
	"""保存详情页的参数"""
	title: str = Field(description="招标标题")
	date: str = Field(description="发布日期，格式 YYYY-MM-DD")


class OpenAndSaveParams(BaseModel):
	"""在列表页点击并保存详情页的参数（原子操作）"""
	index: int = Field(description="要点击的交互元素 index（通常为条目标题链接）")
	title: str = Field(description="招标标题（用于保存文件名与字段抽取）")
	date: str = Field(description="发布日期，格式 YYYY-MM-DD（用于保存文件名与字段抽取）")


def create_save_detail_tools(
	output_dir: Path,
	site_name: str,
	llm=None,
	on_item_saved=None,
	*,
	list_tab_target_id: str | None = None,
	list_url: str | None = None,
	product_category_table: str | None = None,
	engineering_machinery_only: bool = False,
) -> Tools:
	"""
	创建包含 save_detail action 的 Tools 实例

	Args:
		output_dir: 输出目录（如 output/2025-12-23/网站名称）
		site_name: 网站名称
		llm: LLM实例（用于字段提取Agent）
		on_item_saved: 可选回调函数，保存成功时调用 on_item_saved(json_data)
		list_tab_target_id: 列表页 tab 的 target_id（full id）；用于在保存后自动回收多余标签并回到列表页
		list_url: 列表页 URL（可选）；用于同标签打开详情时 go_back 的兜底校验/回退
		engineering_machinery_only: 是否在详情页落盘前，基于 DeepSeek 提取到的 projectName 做“工程机械类”二次筛选；不属于则直接跳过（不保存/不返回 SSE item）

	Returns:
		配置好的 Tools 实例
	"""
	# 注意：browser-use 的系统提示词会鼓励模型写 todo.md/results.md。
	# 我们不依赖这些文件产出，真正的“保存”必须通过 save_detail 完成并触发 SSE item。
	# 因此这里不禁用 file tools（禁用会导致模型在早期规划阶段产生大量无效 action schema），
	# 而是在提示词里明确禁止使用 file tools 作为业务输出。
	tools = Tools()
	seen_detail_keys: set[str] = set()
	_engineering_machinery_only = bool(engineering_machinery_only)
	_product_category_table = (product_category_table or "").strip() or None
	# 列表页 tab（用于保存后自动关闭详情页并切回列表页）
	_locked_list_target_id: str | None = list_tab_target_id
	_locked_list_url: str | None = (list_url or "").strip() or None

	async def _tab_gc(browser_session: BrowserSession) -> None:
		"""
		Best-effort tab garbage collection.

		Goal: after save_detail, keep only the list tab so the Agent can continue reliably.
		"""
		nonlocal _locked_list_target_id
		try:
			state = await browser_session.get_browser_state_summary(include_screenshot=False)
			tabs = list(getattr(state, "tabs", []) or [])
			if not tabs:
				return

			# Pick the "list tab" to keep.
			keep_id: str | None = None
			if _locked_list_target_id and any(getattr(t, "target_id", None) == _locked_list_target_id for t in tabs):
				keep_id = _locked_list_target_id
			elif _locked_list_url:
				for t in tabs:
					try:
						if (getattr(t, "url", "") or "").startswith(_locked_list_url):
							keep_id = getattr(t, "target_id", None)
							break
					except Exception:
						continue

			if not keep_id:
				# Fallback: keep current focused tab if possible.
				keep_id = getattr(browser_session, "agent_focus_target_id", None) or getattr(tabs[0], "target_id", None)

			if keep_id:
				_locked_list_target_id = keep_id

			# Close everything except keep_id.
			from browser_use.browser.events import CloseTabEvent

			for t in tabs:
				tid = getattr(t, "target_id", None)
				if not tid or tid == keep_id:
					continue
				try:
					ev = browser_session.event_bus.dispatch(CloseTabEvent(target_id=str(tid)))
					await ev
					await ev.event_result(raise_if_any=False, raise_if_none=False)
				except Exception:
					# Stale/invalid targets are fine; treat as already closed.
					continue

			# Ensure focus on list tab.
			if keep_id and getattr(browser_session, "agent_focus_target_id", None) != keep_id:
				from browser_use.browser.events import SwitchTabEvent

				try:
					ev = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=str(keep_id)))
					await ev
					await ev.event_result(raise_if_any=False, raise_if_none=False)
				except Exception:
					pass

		except Exception as e:
			logger.debug(f"[{site_name}] tab gc skipped: {e}")

	async def _return_to_list_after_save(browser_session: BrowserSession, *, current_url: str | None) -> None:
		"""
		After saving a detail page, return to list context:
		- If detail opened in new tab: close current tab and switch back to list tab.
		- If detail opened in same tab: go_back (best-effort) and keep only list tab.
		"""
		nonlocal _locked_list_target_id
		try:
			current_target_id = getattr(browser_session, "agent_focus_target_id", None)
			list_target_id = _locked_list_target_id

			if list_target_id and current_target_id and current_target_id != list_target_id:
				# Likely: detail in new tab -> close it then switch to list tab.
				from browser_use.browser.events import CloseTabEvent, SwitchTabEvent

				with contextlib.suppress(Exception):
					ev = browser_session.event_bus.dispatch(CloseTabEvent(target_id=str(current_target_id)))
					await ev
					await ev.event_result(raise_if_any=False, raise_if_none=False)

				with contextlib.suppress(Exception):
					ev = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=str(list_target_id)))
					await ev
					await ev.event_result(raise_if_any=False, raise_if_none=False)

			else:
				# Same-tab flow (or list tab unknown): go back only if we are NOT already on list_url.
				should_go_back = True
				if _locked_list_url and current_url and current_url.startswith(_locked_list_url):
					should_go_back = False
				if should_go_back:
					from browser_use.browser.events import GoBackEvent

					with contextlib.suppress(Exception):
						ev = browser_session.event_bus.dispatch(GoBackEvent())
						await ev

			# Final cleanup: keep only list tab (or current tab as fallback).
			await _tab_gc(browser_session)

			# Small wait to let list page settle after close/go_back.
			await asyncio.sleep(2)

		except Exception as e:
			logger.debug(f"[{site_name}] return-to-list skipped: {e}")

	@tools.action(
		'保存当前详情页的公告正文原始内容(HTML)和结构化字段到文件。在切换到详情页标签页后调用此工具。',
		param_model=SaveDetailParams
	)
	async def save_detail(params: SaveDetailParams, browser_session: BrowserSession):
		"""
		保存详情页公告正文原始内容(HTML)和JSON结构化数据

		会自动：
		1. 获取当前页面URL
		2. 抓取公告详情页正文原始内容（HTML，不转 Markdown）
		3. 使用Agent提取详情字段（flat + lots）
		4. 保存JSON文件（包含原文+字段）
		"""
		title = params.title
		date = params.date

		logger.info(f"[{site_name}] 保存详情页: {title[:40]}...")

		detail_url: str | None = None
		try:
			# 1. 确保输出目录存在
			output_dir.mkdir(parents=True, exist_ok=True)

			# 2. 获取当前页面URL
			try:
				cdp_session = await browser_session.get_or_create_cdp_session()
				url_result = await cdp_session.cdp_client.send.Runtime.evaluate(
					params={'expression': 'location.href', 'returnByValue': True},
					session_id=cdp_session.session_id
				)
				detail_url = url_result.get('result', {}).get('value', 'unknown')
			except Exception as e:
				logger.warning(f"获取URL失败: {e}")
				detail_url = "unknown"

			# 2.2 保护：如果还停留在列表页（URL 仍是列表页 URL），说明并未真正进入详情页。
			# 这种情况下继续保存会把“列表页 URL”写进去，导致去重误判、甚至把列表页当详情页保存。
			try:
				from urllib.parse import urlsplit

				if _locked_list_url and detail_url and detail_url not in ("unknown", ""):
					list_parts = urlsplit(_locked_list_url)
					cur_parts = urlsplit(detail_url)
					same_origin_path = (
						list_parts.scheme == cur_parts.scheme
						and list_parts.netloc == cur_parts.netloc
						and list_parts.path == cur_parts.path
					)
					# NOTE: Some SPA sites keep the same path and only change the fragment (#...).
					# In that case, treat it as "still on list page" ONLY when the fragment also matches.
					# Otherwise we'd incorrectly close the newly opened detail tab and report not_on_detail_page.
					if same_origin_path:
						list_frag = (list_parts.fragment or "").strip()
						cur_frag = (cur_parts.fragment or "").strip()
						if list_frag or cur_frag:
							same_fragment = (list_frag == cur_frag)
						else:
							same_fragment = True
						if not same_fragment:
							# Different fragment under same path: likely navigated within SPA (e.g. list -> detail).
							same_origin_path = False
					if same_origin_path:
						logger.warning(
							f"[{site_name}] ⚠️ save_detail 在列表页被调用（URL 未进入详情页）: {detail_url}"
						)
						with contextlib.suppress(Exception):
							await _tab_gc(browser_session)
						return ActionResult(
							extracted_content=(
								"当前仍在列表页（URL 未进入详情页），请改用 open_and_save(标题链接index, title, date) "
								"或先切换到真正的详情页标签后再调用 save_detail。"
							),
							error="not_on_detail_page",
						)
			except Exception:
				# 保护逻辑失败不应阻断正常保存
				pass

			# 2.5 去重：网站列表可能在爬取过程中从第一页插入新公告，导致后续页码内容“整体后移”并出现重复。
			# 这里以“详情页 URL”为主键去重；取不到 URL 时退化为 title+date。
			file_date = normalize_date_ymd(date) or str(date).replace("/", "-").replace(".", "-")
			dedup_key = (detail_url or "").strip()
			if not dedup_key or dedup_key == "unknown":
				dedup_key = f"{title.strip()}|{file_date}"

			if dedup_key in seen_detail_keys:
				logger.info(f"[{site_name}] ↩︎ 重复公告已跳过: {title[:40]}... ({dedup_key[:80]})")
				# 仍需回到列表页并回收多余 tab，避免 Agent 后续在详情页继续点 index 导致混乱
				with contextlib.suppress(Exception):
					await _return_to_list_after_save(browser_session, current_url=str(detail_url or ""))
				return ActionResult(
					extracted_content="skipped_duplicate",
					long_term_memory=f"重复公告已跳过: {title[:30]}..."
				)
			# 注意：不要在这里把 dedup_key 记入 seen_detail_keys。
			# 原因：save_detail 可能失败或被要求“重试 1 次”（全局规则），
			# 若提前记入会导致后续重试直接被当作 duplicate 跳过，造成漏抓。

			# 3. 尝试点击"查看完整信息"按钮（展开脱敏内容）
			await click_show_full_info(browser_session)
			# 一些站点详情内容是异步渲染的，点击后需要额外等待
			await asyncio.sleep(2)

			# 4. 提取公告原文（HTML，不做 Markdown 转换）
			announcement_content = await extract_page_content(browser_session, site_name)
			if not announcement_content:
				logger.warning(f"[{site_name}] 提取公告原文(HTML)失败: 内容为空")
				# 失败也要尽量回到列表页并回收 tab，避免后续 focus/index 混乱
				with contextlib.suppress(Exception):
					await _return_to_list_after_save(browser_session, current_url=str(detail_url or ""))
				return ActionResult(
					extracted_content=f"提取公告原文失败: {title}",
					error="提取公告原文失败"
				)

			# 5. 两次提取：flat + lots（如果提供了 llm）
			flat_fields: dict = {}
			lot_fields: dict = {"lotProducts": [], "lotCandidates": []}
			# 字段提取改用 DeepSeek-V3.2：将详情页正文 HTML 作为整体输入，让模型一次性解析输出字段 JSON
			# 仅替换“字段提取”步骤；页面操作/导航仍然由 browser-use Agent 完成。
			flat_fields = await extract_fields_from_html(
				announcement_content,
				site_name=site_name,
				stage="flat",
			)
			flat_fields.pop("updateDate", None)

			# 5.1 工程机械类二次筛选（基于 flat 提取到的 projectName）
			# 说明：此处只做“是否属于工程机械类”的判定，不做任何字段抽取；抽取仍然由 extract_fields_from_html 完成。
			if _engineering_machinery_only:
				project_name = str(flat_fields.get("projectName") or "").strip()
				if project_name:
					decision, reason = await llm_is_engineering_machinery_project(
						project_name,
						title=title,
						site_name=site_name,
					)
					if decision is False:
						# 明确判定为“非工程机械类”且本次开启了工程机械筛选：视为已处理，避免后续重复消耗。
						seen_detail_keys.add(dedup_key)
						logger.info(
							f"[{site_name}] ↩︎ 工程机械类筛选已跳过: {title[:40]}... "
							f"(projectName={project_name[:60]!r})"
							+ (f" reason={reason}" if reason else "")
						)
						# Skip means: do NOT save JSON, do NOT emit SSE item; but must return to list & clean tabs.
						await _return_to_list_after_save(browser_session, current_url=str(detail_url or ""))
						return ActionResult(
							extracted_content="skipped_non_gongchengjixie",
							long_term_memory=f"跳过（非工程机械类）: {title[:30]}...",
						)
					if decision is None:
						logger.warning(
							f"[{site_name}] 工程机械类判定无结果，默认保留: {title[:40]}... "
							+ (f" reason={reason}" if reason else "")
						)

			lot_fields = await extract_fields_from_html(
				announcement_content,
				site_name=site_name,
				stage="lots",
				product_category_table=_product_category_table,
			)

			# 兜底：确保数组字段存在
			lot_products = lot_fields.get("lotProducts") or []
			lot_candidates = lot_fields.get("lotCandidates") or []
			if not isinstance(lot_products, list):
				lot_products = []
			if not isinstance(lot_candidates, list):
				lot_candidates = []

			# 7. 生成唯一文件名（使用列表页日期做文件分组）
			filename = get_unique_filename(output_dir, title, file_date)

			# 组装最终返回结构（V2）
			result_data = {
				"announcementUrl": detail_url,
				"announcementName": title,
				"announcementContent": announcement_content,

				# LLM 字段
				**flat_fields,

				# 标段数组字段（LLM）
				"lotProducts": lot_products,
				"lotCandidates": lot_candidates,
			}

			# announcementDate：详情页优先，取不到用列表页兜底
			if not result_data.get("announcementDate"):
				result_data["announcementDate"] = normalize_date_ymd(date) or date

			# 公告类别（13 选 1）强校验：
			# - 不再“无法映射就兜底成招标”
			# - 如果初次抽取不在范围内：调用 DeepSeek 做一次“类型归一化/分类”修复（最多 3 次）
			raw_announcement_type = result_data.get("announcementType")
			normalized_type = try_normalize_announcement_type(raw_announcement_type)
			if not normalized_type:
				normalized_type = await repair_announcement_type(
					site_name=site_name,
					announcement_title=title,
					announcement_content=announcement_content,
					raw_announcement_type=str(raw_announcement_type or ""),
					max_retries=3,
				)

			if not normalized_type:
				# 达到上限仍失败：告警 + 跳过（不落盘/不输出 SSE item），避免错误类型污染下游。
				logger.warning(
					f"[{site_name}] 公告类别修复失败（已达上限 3 次），已跳过: {title[:60]}... "
					f"(raw={str(raw_announcement_type or '')!r}, url={str(detail_url or '')})"
				)
				# 视为“已处理”，避免本次 run 内重复消耗。
				seen_detail_keys.add(dedup_key)
				await _return_to_list_after_save(browser_session, current_url=str(detail_url or ""))
				return ActionResult(
					extracted_content="skipped_invalid_announcement_type",
					long_term_memory=f"跳过（公告类型无法归一化）: {title[:30]}...",
				)

			result_data["announcementType"] = normalized_type

			# estimatedAmount：仅当公告类型为【招标/询价/竞谈/单一/竞价/邀标】时才保留（由抽取阶段 DeepSeek 结合全文生成）。
			# 本阶段只做：类型 gating + 正则校验（不做任何兜底/推导/再调用）。
			try:
				atype = (result_data.get("announcementType") or "").strip()
				if atype not in {"招标", "询价", "竞谈", "单一", "竞价", "邀标"}:
					result_data["estimatedAmount"] = ""
				else:
					est_text = str(result_data.get("estimatedAmount") or "").strip()
					normalized = normalize_estimated_amount(est_text) if est_text else ""
					if normalized and not _ESTIMATED_AMOUNT_VALUE_RE.match(normalized):
						normalized = ""
					result_data["estimatedAmount"] = normalized
			except Exception as est_err:
				logger.warning(f"[{site_name}] estimatedAmount 处理失败（已跳过）: {est_err}")

			# 地址字段：不再用正则拆分；改为一次调用 LLM 从三组 AddressDetail 提取 12 个字段。
			# 规则：
			# - AddressDetail 为空：country="中国"，省市区为空字符串
			# - 整体最多重试 3 次；超过上限逐字段回退原值；只影响 12 个字段，不包含 AddressDetail
			try:
				addr = await extract_admin_divisions_from_details(
					buyer_address_detail=result_data.get("buyerAddressDetail", ""),
					project_address_detail=result_data.get("projectAddressDetail", ""),
					delivery_address_detail=result_data.get("deliveryAddressDetail", ""),
					original_item=result_data,
					max_retries=3,
				)
				result_data.update(addr)
			except Exception as norm_err:
				logger.warning(f"[{site_name}] 地址字段 LLM 提取失败（已跳过）: {norm_err}")

			# 为单条结果生成稳定唯一标识（用于去重）
			result_data["dataId"] = compute_data_id(result_data)

			json_path = output_dir / f"{filename}.json"
			with open(json_path, 'w', encoding='utf-8') as f:
				json.dump(result_data, f, ensure_ascii=False, indent=2)

			# 保存成功后再记入 dedup 集合：避免失败场景阻断重试
			seen_detail_keys.add(dedup_key)

			logger.info(f"[{site_name}] ✓ 元数据已保存: {json_path.name}")

			# 调用回调发送 item 数据到 SSE
			if on_item_saved:
				try:
					on_item_saved(result_data)
				except Exception as cb_err:
					logger.warning(f"[{site_name}] 回调执行失败: {cb_err}")

			# 保存成功后：自动关闭详情页并回到列表页，避免标签页堆积导致后续切错/重复保存。
			await _return_to_list_after_save(browser_session, current_url=str(detail_url or ""))

			return ActionResult(
				extracted_content=f"✓ 已保存: {filename}.json",
				long_term_memory=f"已保存详情页正文(HTML): {title[:30]}..."
			)

		except Exception as e:
			logger.error(f"[{site_name}] 保存详情页失败: {e}")
			# 失败也尝试回到列表页，避免卡在详情页导致标签页越来越多
			with contextlib.suppress(Exception):
				await _return_to_list_after_save(browser_session, current_url=str(detail_url or ""))
			return ActionResult(
				extracted_content=f"保存失败: {e}",
				error=str(e)
			)

	@tools.action(
		'在列表页原子化完成：点击指定 index 打开详情页（处理新标签/同标签两种情况）→ 调用 save_detail 保存 → 自动回到列表页并回收多余标签。',
		param_model=OpenAndSaveParams
	)
	async def open_and_save(params: OpenAndSaveParams, browser_session: BrowserSession):
		"""
		用于避免 Agent “点了但没保存/没切换标签/忘记 close” 等问题：
		- 通过 index 点击标题（或其它可打开详情的元素）
		- 检测是否打开了新标签或发生了同标签导航
		- 必要时自动 switch 到详情页
		- 调用 save_detail 完成保存（保存后会自动回到列表页并做 tab GC）
		"""
		index = int(params.index)
		title = params.title
		date = params.date

		# 记录点击前的 tab/URL 状态
		state_before = await browser_session.get_browser_state_summary(include_screenshot=False)
		if getattr(state_before, "dom_state", None) and getattr(state_before.dom_state, "selector_map", None):
			with contextlib.suppress(Exception):
				browser_session.update_cached_selector_map(state_before.dom_state.selector_map)

		tabs_before = [getattr(t, "target_id", None) for t in (getattr(state_before, "tabs", []) or [])]
		tabs_before_set = {t for t in tabs_before if t}
		url_before = getattr(state_before, "url", "") or ""

		# 找到要点击的节点
		node = await browser_session.get_dom_element_by_index(index)
		if not node:
			# 兜底：刷新一次 DOM 再尝试
			state_refresh = await browser_session.get_browser_state_summary(include_screenshot=False)
			if getattr(state_refresh, "dom_state", None) and getattr(state_refresh.dom_state, "selector_map", None):
				with contextlib.suppress(Exception):
					browser_session.update_cached_selector_map(state_refresh.dom_state.selector_map)
			node = await browser_session.get_dom_element_by_index(index)

		if not node:
			return ActionResult(
				extracted_content=f"index={index} 未找到可点击元素（DOM 可能已变化），请重新在当前页面选择正确的标题链接 index。",
				error="element_not_found",
			)

		# 点击
		from browser_use.browser.events import ClickElementEvent

		click_err: Exception | None = None
		try:
			ev = browser_session.event_bus.dispatch(ClickElementEvent(node=node))
			await ev
			await ev.event_result(raise_if_any=False, raise_if_none=False)
		except Exception as e:
			click_err = e
			logger.debug(f"[{site_name}] open_and_save click 失败: index={index}, err={e}")

		# 等待并检测是否打开了新 tab 或发生了同标签导航
		new_tab_id: str | None = None
		navigated_same_tab = False

		for _ in range(10):  # 最多等待约 5 秒
			await asyncio.sleep(0.5)
			state_after = await browser_session.get_browser_state_summary(include_screenshot=False)
			if getattr(state_after, "dom_state", None) and getattr(state_after.dom_state, "selector_map", None):
				with contextlib.suppress(Exception):
					browser_session.update_cached_selector_map(state_after.dom_state.selector_map)

			tabs_after = [getattr(t, "target_id", None) for t in (getattr(state_after, "tabs", []) or [])]
			new_tabs = [t for t in tabs_after if t and t not in tabs_before_set]
			if new_tabs:
				new_tab_id = new_tabs[-1]
				break

			url_after = getattr(state_after, "url", "") or ""
			if url_after and url_after != url_before:
				navigated_same_tab = True
				break

		if new_tab_id:
			from browser_use.browser.events import SwitchTabEvent

			try:
				ev = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=str(new_tab_id)))
				await ev
				await ev.event_result(raise_if_any=False, raise_if_none=False)
			except Exception as e:
				logger.debug(f"[{site_name}] open_and_save switch 失败: target_id={new_tab_id}, err={e}")
			await asyncio.sleep(1)

		elif not navigated_same_tab:
			# 没有打开新 tab，也没有发生导航：大概率点错了（例如点到了“进行中/已结束”状态列）。
			with contextlib.suppress(Exception):
				await _tab_gc(browser_session)
			return ActionResult(
				extracted_content=(
					"点击后未进入详情页（无新标签、URL 未变化）。"
					"请改为点击该条目的【标题链接】对应的 index，再调用 open_and_save 重试。"
					+ (f"（click_err: {click_err}）" if click_err else "")
				),
				error="detail_not_opened",
			)

		# 已进入详情页（或已切到新 tab）：直接复用 save_detail 的保存逻辑
		return await save_detail(params=SaveDetailParams(title=title, date=date), browser_session=browser_session)

	return tools
