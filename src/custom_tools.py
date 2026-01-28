"""
自定义工具模块
提供公告正文原始内容提取、文件名处理等工具函数
"""

import asyncio
import os
from pathlib import Path
from typing import Any
import re

from browser_use import BrowserSession, ActionResult
from .logger_config import get_logger

logger = get_logger()


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
	# 清理文件名
	safe_title = sanitize_filename(title)
	base_filename = f"{safe_title}_{date}"

	# 检查是否存在
	json_path = base_dir / f"{base_filename}.json"

	if not json_path.exists():
		return base_filename

	# 存在冲突，添加序号
	counter = 2
	while True:
		new_filename = f"{base_filename}_{counter}"
		json_path = base_dir / f"{new_filename}.json"

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
from datetime import datetime
from pydantic import BaseModel, Field
from browser_use import Agent
from browser_use.tools.service import Tools
from .config_manager import load_extract_fields, generate_extract_prompt
from .field_schemas import (
	LotProducts,
	LotCandidates,
	normalize_announcement_type,
	_to_wan_yuan,
	normalize_date_ymd,
	normalize_estimated_amount,
)


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


def get_extract_prompt(stage: str) -> str:
	"""
	获取字段提取提示词（按 stage 缓存）
	"""
	global _extract_prompt_cache

	stage = (stage or "").strip() or "flat"
	if stage not in _extract_prompt_cache:
		fields = get_extract_fields(stage)
		_extract_prompt_cache[stage] = generate_extract_prompt(fields, stage=stage) if fields else ""

	return _extract_prompt_cache[stage]


async def extract_fields_from_page(browser_session, llm, site_name: str, stage: str) -> dict:
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
	extract_prompt = get_extract_prompt(stage)
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
- 金额字段单位为“万元”，无单位数字视为万元
- 日期字段格式为 YYYY-MM-DD（如 2026-02-16）
- 只返回 JSON，不要解释、不要代码块
- 不要执行任何点击或导航操作，只读取当前页面
			""",
			llm=llm,
			browser=browser_session,
			max_steps=2,
			step_timeout=240,
		)

		result = await extract_agent.run()
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
				candidate_marker_keys = {"candidates", "candidatePrices", "candidate_prices", "winner", "winningAmount", "winning_amount"}
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
		return _to_wan_yuan(value)

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
		from bs4 import BeautifulSoup
	except Exception as e:  # pragma: no cover
		logger.warning(f"[{site_name}] bs4 不可用，返回原始 HTML: {e}")
		return html

	soup = BeautifulSoup(html, "html.parser")

	# Remove noisy nodes.
	for el in soup.select(
		"script,style,noscript,svg,canvas,header,nav,footer,aside,"
		"form,input,button,select,option,textarea"
	):
		el.decompose()

	# Drop hidden elements / dialogs.
	for el in soup.select('[hidden], [aria-hidden="true"], [role="dialog"], [aria-modal="true"]'):
		el.decompose()
	for el in soup.select("[style]"):
		style = (el.get("style") or "").replace(" ", "").lower()
		if "display:none" in style or "visibility:hidden" in style:
			el.decompose()

	# Remove images (base64/site icons etc) — keep alt if present.
	for img in soup.find_all("img"):
		alt = (img.get("alt") or "").strip()
		if alt:
			img.replace_with(soup.new_string(alt))
		else:
			img.decompose()

	# Convert iframes to links (some sites embed content in an iframe).
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

	# Return a clean HTML fragment.
	return str(soup)


async def extract_page_content(browser_session: BrowserSession, site_name: str) -> str:
	"""
	提取当前详情页的“正文容器”HTML（尽量保留表格/结构），不做 Markdown 转换。
	"""
	try:
		cdp_session = await browser_session.get_or_create_cdp_session()
		html_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				"expression": """
(() => {
  // Try to extract the *detail content container* first.
  // Some sites (e.g. sp.iccec.cn) have a huge navigation shell; returning full DOM makes Markdown very noisy.
  const keywords = ['公告内容', '公告标题', '项目编号', '发布时间', '附件列表', '物资信息', '相关公告列表'];
  const body = document.body || document.documentElement;
  if (!body) return '';

  function textOf(el) {
    try { return (el.innerText || '').trim(); } catch (e) { return ''; }
  }
  function count(el, selector) {
    try { return el.querySelectorAll(selector).length; } catch (e) { return 0; }
  }
  function score(el) {
    const t = textOf(el);
    const len = t.length;
    if (len < 300) return -1e18;
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
    // pre-filter by text length to keep it fast
    const ranked = [];
    for (const n of all) {
      const t = textOf(n);
      if (t.length >= 300) ranked.push([t.length, n]);
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

		html = html_result.get("result", {}).get("value") or ""
		if not html:
			return ""

		return _html_to_clean_content_html(html, site_name=site_name).strip()
	except Exception as e:
		logger.warning(f"[{site_name}] 提取公告原文(HTML)失败: {e}")
		return ""


class SaveDetailParams(BaseModel):
	"""保存详情页的参数"""
	title: str = Field(description="招标标题")
	date: str = Field(description="发布日期，格式 YYYY-MM-DD")


def create_save_detail_tools(output_dir: Path, site_name: str, llm=None, on_item_saved=None) -> Tools:
	"""
	创建包含 save_detail action 的 Tools 实例

	Args:
		output_dir: 输出目录（如 output/2025-12-23/网站名称）
		site_name: 网站名称
		llm: LLM实例（用于字段提取Agent）
		on_item_saved: 可选回调函数，保存成功时调用 on_item_saved(json_data)

	Returns:
		配置好的 Tools 实例
	"""
	# 注意：browser-use 的系统提示词会鼓励模型写 todo.md/results.md。
	# 我们不依赖这些文件产出，真正的“保存”必须通过 save_detail 完成并触发 SSE item。
	# 因此这里不禁用 file tools（禁用会导致模型在早期规划阶段产生大量无效 action schema），
	# 而是在提示词里明确禁止使用 file tools 作为业务输出。
	tools = Tools()

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

			# 3. 尝试点击"查看完整信息"按钮（展开脱敏内容）
			await click_show_full_info(browser_session)
			# 一些站点详情内容是异步渲染的，点击后需要额外等待
			await asyncio.sleep(2)

			# 4. 提取公告原文（HTML，不做 Markdown 转换）
			announcement_content = await extract_page_content(browser_session, site_name)
			if not announcement_content:
				return ActionResult(
					extracted_content=f"提取公告原文失败: {title}",
					error="提取公告原文失败"
				)

			# 5. 两次提取：flat + lots（如果提供了 llm）
			flat_fields: dict = {}
			lot_fields: dict = {"lotProducts": [], "lotCandidates": []}
			if llm is not None:
				flat_fields = await extract_fields_from_page(browser_session, llm, site_name, stage="flat")
				lot_fields = await extract_fields_from_page(browser_session, llm, site_name, stage="lots")
				flat_fields.pop("updateDate", None)

			# 兜底：确保数组字段存在
			lot_products = lot_fields.get("lotProducts") or []
			lot_candidates = lot_fields.get("lotCandidates") or []
			if not isinstance(lot_products, list):
				lot_products = []
			if not isinstance(lot_candidates, list):
				lot_candidates = []

			# 7. 生成唯一文件名（使用列表页日期做文件分组）
			file_date = normalize_date_ymd(date) or str(date).replace("/", "-").replace(".", "-")
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

			# 公告类别归一化（13 选 1）
			result_data["announcementType"] = normalize_announcement_type(result_data.get("announcementType"))

			# 地址字段：以“详细地址(全地址)”为唯一来源解析国家/省/市/区
			for prefix in ("buyer", "project", "delivery"):
				detail_key = f"{prefix}AddressDetail"
				country_key = f"{prefix}Country"
				province_key = f"{prefix}Province"
				city_key = f"{prefix}City"
				district_key = f"{prefix}District"

				detail = (result_data.get(detail_key) or "").strip()
				if not detail:
					# 规则：当无法从 AddressDetail 识别国家信息时，国家默认“中国”（包含 AddressDetail 为空的情况）
					result_data[country_key] = "中国"
					result_data[province_key] = ""
					result_data[city_key] = ""
					result_data[district_key] = ""
				else:
					parts = _parse_address_parts_from_detail(detail)
					# 规则：country 从 AddressDetail 识别不到时默认中国（_parse 已兜底）
					result_data[country_key] = parts.country or "中国"
					result_data[province_key] = parts.province
					result_data[city_key] = parts.city
					result_data[district_key] = parts.district

			# 为单条结果生成稳定唯一标识（用于去重）
			result_data["dataId"] = compute_data_id(result_data)

			json_path = output_dir / f"{filename}.json"
			with open(json_path, 'w', encoding='utf-8') as f:
				json.dump(result_data, f, ensure_ascii=False, indent=2)

			logger.info(f"[{site_name}] ✓ 元数据已保存: {json_path.name}")

			# 调用回调发送 item 数据到 SSE
			if on_item_saved:
				try:
					on_item_saved(result_data)
				except Exception as cb_err:
					logger.warning(f"[{site_name}] 回调执行失败: {cb_err}")

			return ActionResult(
				extracted_content=f"✓ 已保存: {filename}.json",
				long_term_memory=f"已保存详情页正文(HTML): {title[:30]}..."
			)

		except Exception as e:
			logger.error(f"[{site_name}] 保存详情页失败: {e}")
			return ActionResult(
				extracted_content=f"保存失败: {e}",
				error=str(e)
			)

	return tools
