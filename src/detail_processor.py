"""
详情页处理模块
截图并保存详情页内容

使用 browser-use 内置的标签页管理API，避免与内部SessionManager冲突
"""

import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
from browser_use import Agent, BrowserSession
from browser_use.browser.events import SwitchTabEvent, CloseTabEvent, GoBackEvent
from browser_use.browser.views import TabInfo
from .custom_tools import capture_full_page, get_unique_filename, save_screenshot, get_browser_session
from .logger_config import get_logger

logger = get_logger()


async def get_all_tabs(browser, site_name: str) -> List[TabInfo]:
	"""
	获取浏览器中所有标签页的信息（使用browser-use内置API）

	Args:
		browser: 浏览器实例（BrowserSession）
		site_name: 网站名称

	Returns:
		标签页列表 [TabInfo(url, title, target_id), ...]
	"""
	try:
		browser_session = await get_browser_session(browser)
		tabs = await browser_session.get_tabs()
		logger.info(f"[{site_name}] 当前有 {len(tabs)} 个标签页: {[t.url[:40] for t in tabs]}")
		return tabs

	except Exception as e:
		logger.error(f"[{site_name}] 获取标签页列表失败: {e}")
		return []


async def switch_to_newest_tab(browser, old_tabs: List[TabInfo], site_name: str) -> bool:
	"""
	切换到最新打开的标签页（详情页）- 使用browser-use内置API

	Args:
		browser: 浏览器实例（BrowserSession）
		old_tabs: 点击前的标签页列表
		site_name: 网站名称

	Returns:
		是否成功切换
	"""
	try:
		# 获取当前所有标签页
		new_tabs = await get_all_tabs(browser, site_name)

		logger.info(f"[{site_name}] 标签页对比: 之前 {len(old_tabs)} 个, 现在 {len(new_tabs)} 个")

		if len(new_tabs) <= len(old_tabs):
			logger.warning(f"[{site_name}] 没有检测到新标签页（数量未增加）")
			return False

		# 找出新打开的标签页
		old_ids = {tab.target_id for tab in old_tabs}
		new_tab = None

		for tab in new_tabs:
			if tab.target_id not in old_ids:
				new_tab = tab
				break

		if not new_tab:
			logger.warning(f"[{site_name}] 未找到新标签页（ID未变化）")
			return False

		logger.info(f"[{site_name}] 检测到新标签页: {new_tab.url[:60]}...")

		# 使用 browser-use 的 SwitchTabEvent 切换标签页
		# target_id=None 表示切换到最新打开的标签页
		browser_session = await get_browser_session(browser)
		event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=new_tab.target_id))
		await event

		await asyncio.sleep(1)
		logger.info(f"[{site_name}] ✓ 已切换到详情页标签页")
		return True

	except Exception as e:
		logger.error(f"[{site_name}] 切换到新标签页失败: {e}")
		import traceback
		logger.debug(traceback.format_exc())
		return False


async def process_detail_page(
	item: Dict,
	browser,
	llm,
	output_dir: Path,
	site_name: str
) -> bool:
	"""
	处理当前详情页（假设已经在详情页上）
	截图并保存元数据

	Args:
		item: 条目信息 {title, date}
		browser: 浏览器实例
		llm: LLM实例（保留参数，可能用于提取信息）
		output_dir: 输出目录
		site_name: 网站名称

	Returns:
		是否成功处理
	"""
	title = item['title']
	date = item.get('date', datetime.now().strftime('%Y-%m-%d'))

	logger.info(f"[{site_name}] 正在处理详情页: {title[:50]}...")

	try:
		# 等待页面加载完成
		await asyncio.sleep(2)

		# 1. 获取当前页面URL
		detail_url = await get_current_url_cdp(browser, site_name)
		logger.info(f"[{site_name}] 详情页URL: {detail_url[:60]}...")

		# 2. 完整截图
		screenshot_base64 = await capture_full_page(browser, title)

		if not screenshot_base64:
			logger.error(f"[{site_name}] [{title[:30]}] 截图失败")
			return False

		# 3. 生成唯一文件名
		filename = get_unique_filename(output_dir, title, date)

		# 4. 保存截图
		png_path = output_dir / f"{filename}.png"
		if not save_screenshot(screenshot_base64, png_path):
			logger.error(f"[{site_name}] [{title[:30]}] 保存截图失败")
			return False

		logger.info(f"[{site_name}] ✓ 截图已保存: {png_path.name}")

		# 5. 保存JSON元数据
		json_data = {
			"title": title,
			"date": date,
			"screenshot_path": f"{filename}.png",
			"captured_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			"source_website": site_name,
			"detail_url": detail_url
		}

		json_path = output_dir / f"{filename}.json"
		with open(json_path, 'w', encoding='utf-8') as f:
			json.dump(json_data, f, ensure_ascii=False, indent=2)

		logger.info(f"[{site_name}] ✓ 元数据已保存: {json_path.name}")
		logger.info(f"[{site_name}] ✓ 处理完成: {title[:30]}...")

		return True

	except Exception as e:
		logger.error(f"[{site_name}] [{title[:30]}] 处理失败: {e}")
		return False


async def close_current_tab(browser, site_name: str) -> bool:
	"""
	关闭最新打开的标签页（详情页），自动切换回列表页
	使用 browser-use 内置的 CloseTabEvent

	简化逻辑：直接关闭最后一个标签页，因为详情页总是最后打开的

	Args:
		browser: 浏览器实例（BrowserSession）
		site_name: 网站名称

	Returns:
		是否成功
	"""
	try:
		browser_session = await get_browser_session(browser)

		# 1. 获取所有标签页
		tabs = await get_all_tabs(browser, site_name)

		if len(tabs) < 2:
			logger.warning(f"[{site_name}] 只有 {len(tabs)} 个标签页，使用后退代替关闭")
			return await go_back_cdp(browser, site_name)

		# 2. 简化逻辑：关闭最后一个标签页（最新打开的，即详情页）
		# 保留第一个标签页（列表页）
		detail_tab = tabs[-1]  # 最新打开的
		list_tab = tabs[0]     # 第一个标签页（原始列表页）

		logger.info(f"[{site_name}] 关闭标签页: {detail_tab.url[:50]}...")
		logger.info(f"[{site_name}] 保留标签页: {list_tab.url[:50]}...")

		# 3. 先切换到列表页
		event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=list_tab.target_id))
		await event
		await asyncio.sleep(0.5)

		# 4. 关闭详情页
		event = browser_session.event_bus.dispatch(CloseTabEvent(target_id=detail_tab.target_id))
		await event

		await asyncio.sleep(1)
		logger.info(f"[{site_name}] ✓ 已关闭详情页，返回列表页（剩余 {len(tabs)-1} 个标签页）")
		return True

	except Exception as e:
		logger.error(f"[{site_name}] 关闭标签页失败: {e}")
		import traceback
		logger.debug(traceback.format_exc())
		# 尝试后退作为降级方案
		try:
			await go_back_cdp(browser, site_name)
			return True
		except:
			return False


async def go_back_cdp(browser, site_name: str) -> bool:
	"""
	使用 browser-use 的 GoBackEvent 执行浏览器后退

	Args:
		browser: 浏览器实例（BrowserSession）
		site_name: 网站名称

	Returns:
		是否成功
	"""
	try:
		browser_session = await get_browser_session(browser)
		event = browser_session.event_bus.dispatch(GoBackEvent())
		await event

		await asyncio.sleep(2)
		logger.debug(f"[{site_name}] ✓ 已执行后退")
		return True

	except Exception as e:
		logger.error(f"[{site_name}] 后退失败: {e}")
		return False


async def cleanup_extra_tabs(browser, site_name: str, expected_list_url: str = None) -> bool:
	"""
	清理多余的标签页，只保留列表页

	Args:
		browser: 浏览器实例（BrowserSession）
		site_name: 网站名称
		expected_list_url: 期望的列表页URL片段（用于识别列表页）

	Returns:
		是否成功
	"""
	try:
		browser_session = await get_browser_session(browser)
		tabs = await get_all_tabs(browser, site_name)

		if len(tabs) <= 1:
			logger.debug(f"[{site_name}] 只有1个标签页，无需清理")
			return True

		# 找到列表页（第一个标签页通常是列表页）
		list_tab = tabs[0]
		tabs_to_close = tabs[1:]

		logger.warning(f"[{site_name}] ⚠️ 检测到 {len(tabs)} 个标签页，需要关闭 {len(tabs_to_close)} 个多余标签页")
		for i, tab in enumerate(tabs):
			logger.debug(f"[{site_name}]   标签页 {i}: {tab.url[:60]}...")

		# 先切换到列表页
		event = browser_session.event_bus.dispatch(SwitchTabEvent(target_id=list_tab.target_id))
		await event
		await asyncio.sleep(0.5)

		# 逐个关闭其他标签页（从后向前关闭，避免索引变化问题）
		closed_count = 0
		for tab in reversed(tabs_to_close):
			try:
				logger.debug(f"[{site_name}] 正在关闭: {tab.url[:50]}...")
				event = browser_session.event_bus.dispatch(CloseTabEvent(target_id=tab.target_id))
				await event
				closed_count += 1
				await asyncio.sleep(0.3)
			except Exception as e:
				logger.warning(f"[{site_name}] 关闭标签页失败: {e}")

		# 验证清理结果
		remaining_tabs = await get_all_tabs(browser, site_name)
		logger.info(f"[{site_name}] ✓ 已清理 {closed_count} 个多余标签页，剩余 {len(remaining_tabs)} 个")

		return len(remaining_tabs) == 1

	except Exception as e:
		logger.error(f"[{site_name}] 清理标签页失败: {e}")
		return False


async def get_current_url_cdp(browser, site_name: str) -> str:
	"""
	使用CDP获取当前页面URL

	Args:
		browser: 浏览器实例
		site_name: 网站名称

	Returns:
		当前页面URL
	"""
	try:
		browser_session = await get_browser_session(browser)
		cdp_session = await browser_session.get_or_create_cdp_session()

		result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={
				'expression': 'location.href',
				'returnByValue': True
			},
			session_id=cdp_session.session_id
		)

		if result and 'result' in result:
			url = result['result'].get('value', '')
			if url and url.startswith('http'):
				return url

		return "unknown"

	except Exception as e:
		logger.error(f"[{site_name}] 获取URL失败: {e}")
		return "unknown"


# ============ 以下是旧版函数，保留用于向后兼容 ============

async def process_detail(
	item: Dict,
	browser,
	llm,
	output_dir: Path,
	site_name: str
) -> bool:
	"""
	[旧版函数 - 保留向后兼容]
	处理单个详情页（包含点击进入详情页的逻辑）

	Args:
		item: 列表页提取的条目信息 {title, date}
		browser: 浏览器实例
		llm: LLM实例
		output_dir: 输出目录
		site_name: 网站名称

	Returns:
		是否成功处理
	"""
	logger.warning(f"[{site_name}] 使用旧版 process_detail 函数")

	title = item['title']
	pre_extracted_url = item.get('url', '')

	logger.info(f"[{site_name}] 正在处理: {title}")

	try:
		# 1. 点击标题进入详情页
		logger.info(f"[{site_name}] 点击标题进入详情页...")
		click_result = await click_title_to_detail(browser, llm, title, site_name, pre_extracted_url)

		if not click_result["success"]:
			logger.error(f"[{site_name}] [{title}] 无法点击进入详情页")
			return False

		opened_new_tab = click_result["opened_new_tab"]

		# 2. 获取当前页面的URL
		await asyncio.sleep(1)
		detail_url = await get_current_url(browser, llm, site_name)
		logger.info(f"[{site_name}] [{title}] 详情页URL: {detail_url}")

		# 3. 完整截图
		screenshot_base64 = await capture_full_page(browser, title)

		if not screenshot_base64:
			logger.error(f"[{site_name}] [{title}] 截图失败")
			await go_back_to_list(browser, llm, opened_new_tab)
			return False

		# 4. 生成唯一文件名
		filename = get_unique_filename(output_dir, title, item['date'])

		# 5. 保存截图
		png_path = output_dir / f"{filename}.png"
		if not save_screenshot(screenshot_base64, png_path):
			logger.error(f"[{site_name}] [{title}] 保存截图失败")
			await go_back_to_list(browser, llm, opened_new_tab)
			return False

		logger.info(f"[{site_name}] [{title}] ✓ 截图已保存: {png_path.name}")

		# 6. 保存JSON元数据
		json_data = {
			"title": title,
			"date": item['date'],
			"screenshot_path": f"{filename}.png",
			"captured_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			"source_website": site_name,
			"detail_url": detail_url
		}

		json_path = output_dir / f"{filename}.json"
		with open(json_path, 'w', encoding='utf-8') as f:
			json.dump(json_data, f, ensure_ascii=False, indent=2)

		logger.info(f"[{site_name}] [{title}] ✓ 元数据已保存: {json_path.name}")

		# 7. 返回列表页
		await go_back_to_list(browser, llm, opened_new_tab)

		logger.info(f"[{site_name}] [{title}] ✓ 处理完成")
		return True

	except Exception as e:
		logger.error(f"[{site_name}] [{title}] 处理失败: {e}")
		try:
			await go_back_to_list(browser, llm)
		except:
			pass
		return False


async def click_title_to_detail(browser, llm, title: str, site_name: str, pre_extracted_url: str = '') -> dict:
	"""
	[旧版函数]
	点击标题进入详情页

	Args:
		browser: 浏览器实例
		llm: LLM实例
		title: 招标标题
		site_name: 网站名称
		pre_extracted_url: 预提取的链接URL（可选）

	Returns:
		字典: {"success": bool, "opened_new_tab": bool}
	"""
	result = {
		"success": False,
		"opened_new_tab": False
	}

	try:
		# 获取点击前的标签页数量
		tabs_before = await get_tab_count(browser, site_name)

		# 如果有预提取的URL，直接导航
		if pre_extracted_url:
			logger.info(f"[{site_name}] 使用预提取链接: {pre_extracted_url[:60]}...")
			nav_agent = Agent(
				task=f"请使用navigate工具访问这个URL: {pre_extracted_url}",
				llm=llm,
				browser=browser,
				max_steps=2
			)
			await nav_agent.run()
			await asyncio.sleep(2)
			result["success"] = True
			return result

		# 使用Agent点击标题
		logger.info(f"[{site_name}] 点击标题: {title[:50]}...")
		agent = Agent(
			task=f"""
			请在当前页面找到并点击以下标题的链接：

			标题：{title}

			要求：
			- 找到包含上述标题的链接
			- 点击该链接
			- 点击后立即返回

			禁止：
			- 禁止下载文件
			- 禁止重复点击
			""",
			llm=llm,
			browser=browser,
			max_steps=5
		)

		await agent.run()
		await asyncio.sleep(2)

		# 检查是否打开了新标签页
		tabs_after = await get_tab_count(browser, site_name)
		if tabs_after > tabs_before:
			result["opened_new_tab"] = True
			logger.info(f"[{site_name}] 检测到新标签页打开")

		result["success"] = True
		return result

	except Exception as e:
		logger.error(f"[{site_name}] 点击标题失败: {e}")
		return result


async def get_tab_count(browser, site_name: str) -> int:
	"""
	获取当前标签页数量

	Args:
		browser: 浏览器实例
		site_name: 网站名称

	Returns:
		标签页数量
	"""
	try:
		browser_session = await get_browser_session(browser)
		cdp_session = await browser_session.get_or_create_cdp_session()

		result = await cdp_session.cdp_client.send(
			'Target.getTargets',
			params={},
		)

		count = 0
		if result and 'targetInfos' in result:
			for target in result['targetInfos']:
				if target.get('type') == 'page':
					count += 1

		return count

	except Exception as e:
		logger.debug(f"[{site_name}] 获取标签页数量失败: {e}")
		return 1


async def get_current_url(browser, llm, site_name: str) -> str:
	"""
	[旧版函数]
	获取当前页面的URL

	Args:
		browser: 浏览器实例
		llm: LLM实例（保留参数但不使用）
		site_name: 网站名称

	Returns:
		当前页面URL
	"""
	return await get_current_url_cdp(browser, site_name)


async def go_back_to_list(browser, llm, opened_new_tab: bool = False) -> bool:
	"""
	[旧版函数]
	返回列表页

	Args:
		browser: 浏览器实例
		llm: LLM实例（保留参数但不使用）
		opened_new_tab: 是否在新标签页打开了详情页

	Returns:
		是否成功
	"""
	try:
		browser_session = await get_browser_session(browser)
		cdp_session = await browser_session.get_or_create_cdp_session()

		if opened_new_tab:
			# 关闭当前标签页
			logger.debug("详情页在新标签页，执行关闭...")
			try:
				await cdp_session.cdp_client.send.Page.close(
					params={},
					session_id=cdp_session.session_id
				)
				await asyncio.sleep(1)
			except Exception as e:
				logger.debug(f"关闭标签页失败，尝试后退: {e}")
				await cdp_session.cdp_client.send.Runtime.evaluate(
					params={
						'expression': 'window.history.back()',
						'returnByValue': True
					},
					session_id=cdp_session.session_id
				)
				await asyncio.sleep(2)
		else:
			# 使用后退
			logger.debug("详情页在同一标签页，执行后退...")
			await cdp_session.cdp_client.send.Runtime.evaluate(
				params={
					'expression': 'window.history.back()',
					'returnByValue': True
				},
				session_id=cdp_session.session_id
			)
			await asyncio.sleep(2)

		logger.debug("✓ 已返回列表页")
		return True

	except Exception as e:
		logger.error(f"返回列表页失败: {e}")
		return False
