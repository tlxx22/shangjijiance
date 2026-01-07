"""
自定义工具模块
提供完整页面截图、文件名处理等工具函数
"""

import asyncio
import base64
from pathlib import Path
from typing import Optional
from PIL import Image
from io import BytesIO
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
	png_path = base_dir / f"{base_filename}.png"
	json_path = base_dir / f"{base_filename}.json"

	if not png_path.exists() and not json_path.exists():
		return base_filename

	# 存在冲突，添加序号
	counter = 2
	while True:
		new_filename = f"{base_filename}_{counter}"
		png_path = base_dir / f"{new_filename}.png"
		json_path = base_dir / f"{new_filename}.json"

		if not png_path.exists() and not json_path.exists():
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


async def capture_full_page_cdp(browser) -> Optional[str]:
	"""
	使用CDP原生方式截取完整页面（改进版：调整视口大小以匹配页面）

	Args:
		browser: Browser或BrowserSession实例

	Returns:
		Base64编码的截图数据，失败返回None
	"""
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


async def capture_full_page_stitch(browser) -> Optional[str]:
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


async def capture_full_page(browser, title: str) -> Optional[str]:
	"""
	完整页面截图（混合方案）
	优先使用CDP原生，失败则降级到拼接方式

	Args:
		browser: Browser或BrowserSession实例
		title: 页面标题（用于日志）

	Returns:
		Base64编码的截图数据
	"""
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

import json
from datetime import datetime
from pydantic import BaseModel, Field
from browser_use import Agent
from browser_use.tools.service import Tools
from .config_manager import load_extract_fields, generate_extract_prompt


# 全局缓存字段配置和提示词（避免每次调用都读取文件）
_extract_fields_cache = None
_extract_prompt_cache = None


def get_extract_prompt() -> str:
	"""
	获取字段提取提示词（带缓存）
	"""
	global _extract_fields_cache, _extract_prompt_cache

	if _extract_prompt_cache is None:
		try:
			_extract_fields_cache = load_extract_fields()
			_extract_prompt_cache = generate_extract_prompt(_extract_fields_cache)
		except FileNotFoundError:
			# 如果配置文件不存在，返回空（不提取字段）
			_extract_prompt_cache = ""

	return _extract_prompt_cache


def get_extract_field_keys() -> list:
	"""
	获取所有字段的 key 列表（用于生成空值字典）
	"""
	global _extract_fields_cache

	if _extract_fields_cache is None:
		try:
			_extract_fields_cache = load_extract_fields()
		except FileNotFoundError:
			return []

	return [f.key for f in _extract_fields_cache]


async def extract_fields_from_page(browser_session, llm, site_name: str) -> dict:
	"""
	使用 Agent 从当前详情页提取字段

	Args:
		browser_session: 浏览器会话
		llm: LLM 实例
		site_name: 网站名称

	Returns:
		提取的字段字典，提取失败返回空值字典
	"""
	extract_prompt = get_extract_prompt()
	field_keys = get_extract_field_keys()

	# 如果没有配置字段，返回空字典
	if not extract_prompt or not field_keys:
		return {}

	# 生成空值字典作为默认值
	empty_result = {key: "" for key in field_keys}

	try:
		logger.info(f"[{site_name}] 正在提取详情页字段...")

		extract_agent = Agent(
			task=f"""
{extract_prompt}

**重要提示：**
- 仔细阅读页面内容，提取上述所有字段
- 找不到的字段填空字符串 ""
- 金额字段只填数字，不要带单位（如果是万元，转换为元）
- 日期字段格式为 YYYY-MM-DD
- 只返回 JSON，不要有其他内容
- 不要执行任何点击或导航操作，只读取当前页面
""",
			llm=llm,
			browser=browser_session,
			max_steps=2  # 只需要读取页面，不需要操作
		)

		result = await extract_agent.run()
		output = result.final_result()

		if not output:
			logger.warning(f"[{site_name}] 字段提取无返回")
			return empty_result

		# 尝试解析 JSON
		try:
			# 清理输出，提取 JSON 部分
			output_str = str(output).strip()

			# 处理转义引号（Agent 输出可能包含 \" 而非 "）
			if '\\"' in output_str:
				output_str = output_str.replace('\\"', '"')

			# 移除可能的 markdown 代码块标记
			output_str = re.sub(r'^```json\s*', '', output_str)
			output_str = re.sub(r'^```\s*', '', output_str)
			output_str = re.sub(r'\s*```$', '', output_str)

			# 尝试找到 JSON 对象（支持嵌套）
			json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', output_str, re.DOTALL)
			if json_match:
				extracted = json.loads(json_match.group())
				# 合并提取结果和空值字典（确保所有字段都有值）
				for key in field_keys:
					if key not in extracted:
						extracted[key] = ""
				logger.info(f"[{site_name}] ✓ 字段提取成功")
				return extracted
			else:
				logger.warning(f"[{site_name}] 无法从输出中提取 JSON")
				return empty_result

		except json.JSONDecodeError as e:
			logger.warning(f"[{site_name}] JSON 解析失败: {e}")
			return empty_result

	except Exception as e:
		logger.error(f"[{site_name}] 字段提取失败: {e}")
		return empty_result


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
	tools = Tools()

	@tools.action(
		'保存当前详情页的截图和元数据到文件。在切换到详情页标签页后调用此工具。',
		param_model=SaveDetailParams
	)
	async def save_detail(params: SaveDetailParams, browser_session: BrowserSession):
		"""
		保存详情页截图和JSON元数据

		会自动：
		1. 获取当前页面URL
		2. 截取完整页面截图
		3. 使用Agent提取详情字段
		4. 保存截图文件
		5. 保存JSON元数据（包含提取的字段）
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

			# 4. 截取完整页面截图
			screenshot_base64 = await capture_full_page(browser_session, title)

			if not screenshot_base64:
				return ActionResult(
					extracted_content=f"截图失败: {title}",
					error="截图失败"
				)

			# 5. 提取详情字段（如果提供了 llm）
			extracted_fields = {}
			if llm is not None:
				extracted_fields = await extract_fields_from_page(browser_session, llm, site_name)

			# 6. 生成唯一文件名
			filename = get_unique_filename(output_dir, title, date)

			# 7. 保存截图
			png_path = output_dir / f"{filename}.png"
			if not save_screenshot(screenshot_base64, png_path):
				return ActionResult(
					extracted_content=f"保存截图失败: {title}",
					error="保存截图失败"
				)

			logger.info(f"[{site_name}] ✓ 截图已保存: {png_path.name}")

			# 8. 保存JSON元数据（合并提取的字段）
			json_data = {
				"title": title,
				"date": date,
				"screenshot_path": f"{filename}.png",
				"captured_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
				"source_website": site_name,
				"detail_url": detail_url,
				**extracted_fields  # 合并提取的字段
			}

			json_path = output_dir / f"{filename}.json"
			with open(json_path, 'w', encoding='utf-8') as f:
				json.dump(json_data, f, ensure_ascii=False, indent=2)

			logger.info(f"[{site_name}] ✓ 元数据已保存: {json_path.name}")

			# 统计提取了多少字段
			extracted_count = len([v for v in extracted_fields.values() if v])
			total_fields = len(extracted_fields)
			if total_fields > 0:
				logger.info(f"[{site_name}] ✓ 提取字段: {extracted_count}/{total_fields} 个有值")

			# 调用回调发送 item 数据到 SSE
			if on_item_saved:
				try:
					on_item_saved(json_data)
				except Exception as cb_err:
					logger.warning(f"[{site_name}] 回调执行失败: {cb_err}")

			return ActionResult(
				extracted_content=f"✓ 已保存: {filename}.png 和 {filename}.json",
				long_term_memory=f"已保存详情页截图: {title[:30]}..."
			)

		except Exception as e:
			logger.error(f"[{site_name}] 保存详情页失败: {e}")
			return ActionResult(
				extracted_content=f"保存失败: {e}",
				error=str(e)
			)

	return tools
