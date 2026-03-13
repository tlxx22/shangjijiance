"""
网站处理主流程模块
协调单个网站的完整处理流程
"""

import asyncio
import contextlib
import os
from pathlib import Path
from datetime import datetime
from typing import Dict
from browser_use import Browser, BrowserSession, Agent
from trans import build_llm

from .config_manager import SiteConfig, get_user_data_dir
from .login_handler import smart_login
from .list_processor import process_entire_site
from .prompts import GLOBAL_RULES
from .logger_config import get_logger
from .browser_use_budget import BudgetExceededError, get_budget

logger = get_logger()

DEFAULT_HEADLESS_USER_AGENT = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
	"AppleWebKit/537.36 (KHTML, like Gecko) "
	"Chrome/122.0.0.0 Safari/537.36"
)


def get_browser_user_agent(headless: bool) -> str | None:
	"""
	部分站点会对 headless UA（包含 'HeadlessChrome'）返回空白/错误页面。
	因此在 headless 模式下默认使用一个非 Headless 的 UA，并允许通过环境变量覆盖。
	"""
	override = os.getenv("BROWSER_USER_AGENT")
	if override:
		return override.strip()

	if headless:
		return DEFAULT_HEADLESS_USER_AGENT
	return None


async def get_iframe_url(browser, llm, site_name: str) -> str:
	"""
	获取列表页iframe的src URL

	Args:
		browser: 浏览器实例
		llm: LLM实例
		site_name: 网站名称

	Returns:
		iframe的URL，如果失败返回空字符串
	"""
	try:
		# 使用Agent读取iframe URL
		extract_agent = Agent(
			task="""
			检查页面是否使用iframe加载招标列表。

			**首先检查 browser_state 中的 iframes 数量**：
			- 如果显示 "0 iframes"，说明页面没有使用iframe，直接用 done 返回 "no_iframe"
			- 如果有 iframe，执行下面的代码提取所有 URL

			```javascript
			(function() {
				const urls = [];
				document.querySelectorAll('iframe').forEach(iframe => {
					if (iframe.src && iframe.src.startsWith('http')) {
						urls.push(iframe.src);
					}
				});
				return urls.join(' ||| ');
			})();
			```

			**如果有多个 URL**（用 ||| 分隔），请判断哪个最可能是招标列表页：
			- 招标页面 URL 通常包含：ggzy、zfcg、jyxx、zbcg、tender、notice、list 等关键词
			- 排除明显不相关的：党建(12371)、统计、广告、社交分享等

			用 done 返回你认为最可能的那个 URL。如果只有一个就直接返回。

			**重要**：不要重复尝试，执行一次就返回结果。
			""",
			llm=llm,
			browser=browser,
			extend_system_message=GLOBAL_RULES,
			max_failures=5,
			step_timeout=600,
		)

		result = await extract_agent.run(max_steps=99999)
		iframe_url_raw = result.final_result()

		# 从返回结果中提取URL
		if iframe_url_raw:
			import re
			url_pattern = r'(https?://[^\s\u4e00-\u9fff]+)'
			matches = re.findall(url_pattern, str(iframe_url_raw))

			if matches:
				iframe_url = matches[0].strip()
				logger.info(f"[{site_name}] ✓ 找到iframe URL: {iframe_url}")
				return iframe_url
			elif isinstance(iframe_url_raw, str) and iframe_url_raw.startswith('http'):
				logger.info(f"[{site_name}] ✓ 找到iframe URL: {iframe_url_raw}")
				return iframe_url_raw.strip()

		logger.warning(f"[{site_name}] 未找到有效的iframe URL")
		return ""

	except BudgetExceededError:
		raise
	except Exception as e:
		logger.error(f"[{site_name}] 获取iframe URL失败: {e}")
		return ""


async def check_page_security(browser, llm, site_name: str) -> bool:
	"""
	统一的页面安全检查：检测风控和无法处理的验证码

	检查当前页面是否安全可继续：
	- 风控页面（403、WAF、访问被拒等）→ False
	- 复杂验证码（滑块、拼图等无法自动处理）→ False
	- 简单验证码（文字、数学题等可以处理）→ True
	- 正常页面 → True

	Args:
		browser: 浏览器实例
		llm: LLM实例
		site_name: 网站名称

	Returns:
		True: 安全，可以继续
		False: 需要跳过该网站
	"""
	try:
		logger.info(f"[{site_name}] 正在检查页面安全状态...")

		security_agent = Agent(
			task="""
			检查当前页面是否存在以下问题：

			**1. 风控/拦截页面（最优先）：**
			- 页面标题包含：Error、403、404、Access Denied、Forbidden、拒绝访问
			- 页面内容显示：访问被拒绝、请求频繁、IP被封、访问异常、WAF拦截
			- 页面变成空白或只有错误提示

			**2. 无法自动处理的验证码：**
			- **滑块验证码**（需要拖动滑块）
			- **拼图验证码**（需要拖动拼图块）
			- **行为验证**（需要按顺序点击图片等复杂操作）
			- 任何你认为无法自动完成的验证机制

			**3. 可以自动处理的验证码（不算问题）：**
			- 简单的文字验证码（4-6位数字或字母）
			- 数学题验证码（1+1=?）
			- 这些你可以识别并填写，不算问题

			**返回规则：**
			- 如果发现第1或第2类问题，返回 "unsafe"
			- 如果只有第3类验证码或没有任何问题，返回 "safe"
			- 只返回一个单词，不要解释

			**重要：不要尝试处理任何验证码，只需要判断并返回结果！**
			""",
			llm=llm,
			browser=browser,
			extend_system_message=GLOBAL_RULES,
			max_failures=5,
			step_timeout=600,
		)

		result = await security_agent.run(max_steps=99999)
		output = result.final_result()

		if output:
			output_lower = output.strip().lower()

			if 'unsafe' in output_lower:
				logger.warning(f"[{site_name}] ⚠️ 检测到风控或无法处理的验证码，跳过该网站")
				return False
			else:
				logger.info(f"[{site_name}] ✓ 页面安全检查通过")
				return True

		# 如果没有输出，保守处理，认为安全
		logger.info(f"[{site_name}] 页面安全检查无明确结果，默认继续")
		return True

	except BudgetExceededError:
		raise
	except Exception as e:
		logger.error(f"[{site_name}] 页面安全检查失败: {e}")
		# 出错时保守处理，继续执行
		return True


async def enter_list_page(browser, llm, site_name: str) -> bool:
	"""
	检测并进入列表页（处理"更多"按钮）

	如果页面有"更多"按钮，点击进入列表页，并关闭原主页标签。
	如果没有"更多"按钮，说明当前已是列表页，不做任何操作。

	Args:
		browser: 浏览器实例
		llm: LLM实例
		site_name: 网站名称

	Returns:
		True: 成功
		False: 失败
	"""
	try:
		logger.info(f"[{site_name}] 检测是否有'更多'按钮...")

		enter_agent = Agent(
			task="""
			检查当前页面是否有"更多"、"更多>>"、"查看更多"、"更多公告"等按钮或链接。

			**判断方法：**
			- 这类按钮通常在招标信息预览区域的右上角或底部
			- 文字包含"更多"二字
			- 可能是链接(<a>)或按钮(<button>)

			**如果找到了"更多"按钮：**
			1. 点击该按钮（会在新标签页打开列表页）
			2. 查看 browser_state 中的 tabs 列表，找到新标签页的 tab_id
			3. 使用 switch_tab 切换到新标签页
			4. 使用 close_tab 关闭原来的主页标签（tab_id 较小的那个）
			5. 用 done 返回 "entered"

			**如果没有找到"更多"按钮：**
			- 说明当前页面已经是列表页
			- 直接用 done 返回 "already_list"

			**重要：只执行一次检测，不要重复尝试！**
			""",
			llm=llm,
			browser=browser,
			extend_system_message=GLOBAL_RULES,
			max_failures=5,
			step_timeout=600,
		)

		result = await enter_agent.run(max_steps=99999)
		output = result.final_result()

		if output:
			output_lower = output.strip().lower()

			if 'entered' in output_lower:
				logger.info(f"[{site_name}] ✓ 已通过'更多'按钮进入列表页")
			else:
				logger.info(f"[{site_name}] 当前已是列表页，无需点击'更多'")

		return True

	except BudgetExceededError:
		raise
	except Exception as e:
		logger.error(f"[{site_name}] 进入列表页失败: {e}")
		return False  # 出错时返回 False


async def process_site(
	site_config: SiteConfig,
	filter_prompt: str,
	browser: Browser | None = None,
	headless: bool = False,
	max_pages: int = 5,
	max_retries: int = 3,
	on_item_saved=None,
	date_start: str | None = None,
	date_end: str | None = None,
	product_category_table: str | None = None,
	engineering_machinery_only: bool = False,
) -> Dict:
	"""
	处理单个网站

	新流程：边扫描边处理
	- 发现符合条件的条目 → 点击打开（新标签页自动跳转）
	- 在新标签页处理（公告原文MD、字段提取等）
	- 关闭新标签页（自动回到列表页）
	- 继续浏览列表页，找下一个
	- 翻页，重复

	Args:
		site_config: 网站配置
		filter_prompt: 筛选提示词
		browser: 外部传入的浏览器实例（并发模式使用）
		headless: 无头模式
		max_pages: 最大翻页数
		max_retries: 最大重试次数

	Returns:
		统计信息字典：{
			"status": "success" | "failed",
			"items_found": 整数,
			"pages_processed": 整数,
			"error": 错误信息（如果有）
		}
	"""
	site_name = site_config.name
	logger.info(f"[{site_name}] ========== 开始处理 ==========")

	# 创建输出目录
	today = datetime.now().strftime('%Y-%m-%d')
	output_base = Path("output") / today
	output_dir = output_base / site_name
	output_dir.mkdir(parents=True, exist_ok=True)

	# 初始化LLM
	llm = get_budget().wrap_llm(build_llm())

	# 标记浏览器是否由本函数创建（用于决定是否关闭）
	browser_created_here = browser is None
	retries = 0

	while retries < max_retries:
		try:
			# 创建浏览器实例（如果外部未传入）
			if browser is None:
				logger.info(f"[{site_name}] 正在创建浏览器实例...")
				user_agent = get_browser_user_agent(headless=headless)
				browser = Browser(
					headless=headless,
					user_agent=user_agent,
					keep_alive=True,
					auto_download_pdfs=False,
					enable_default_extensions=False,
				)

			# 访问列表页
			logger.info(f"[{site_name}] 正在访问: {site_config.url}")

			# 智能登录处理
			login_success = await smart_login(site_config, browser, llm)

			if not login_success:
				# 关闭浏览器后再返回（仅当本函数创建时）
				if browser_created_here:
					logger.info(f"[{site_name}] 正在关闭浏览器...")
					try:
						await browser.kill()
						logger.info(f"[{site_name}] ✓ 浏览器已关闭")
					except Exception as e:
						logger.warning(f"[{site_name}] 关闭浏览器时出错: {e}")
				return {
					"status": "failed",
					"items_found": 0,
					"pages_processed": 0,
					"error": "页面状态检测失败（需要登录/页面异常/验证码）"
				}

			logger.info(f"[{site_name}] 跳过网站筛选，将由LLM进行日期筛选")

			# 【安全检查1】smart_login 之后检查页面安全
			if not await check_page_security(browser, llm, site_name):
				# 关闭浏览器并跳过（仅当本函数创建时）
				if browser_created_here:
					logger.info(f"[{site_name}] 正在关闭浏览器...")
					try:
						await browser.kill()
						logger.info(f"[{site_name}] ✓ 浏览器已关闭")
					except Exception as e:
						logger.warning(f"[{site_name}] 关闭浏览器时出错: {e}")
				return {
					"status": "failed",
					"items_found": 0,
					"pages_processed": 0,
					"error": "页面风控或无法处理的验证码"
				}

			# 读取iframe的src并直接访问（绕过跨域限制）
			logger.info(f"[{site_name}] 正在获取列表页iframe URL...")
			iframe_url = await get_iframe_url(browser, llm, site_name)

			if iframe_url:
				logger.info(f"[{site_name}] 直接访问iframe URL: {iframe_url}")
				# 使用 initial_actions 预置导航动作，无需 LLM 推理
				nav_agent = Agent(
					task="""
					页面导航已由 initial_actions 完成。

					**你的唯一任务**：立即用 done 返回 "ok"

					⚠️ 禁止执行任何其他操作：
					- 禁止提取数据
					- 禁止点击任何按钮
					- 禁止翻页
					- 禁止写文件

					直接返回 "ok"！
					""",
					llm=llm,
					browser=browser,
					extend_system_message=GLOBAL_RULES,
					initial_actions=[{'navigate': {'url': iframe_url}}],
					max_failures=5,
					step_timeout=600,
				)
				await nav_agent.run(max_steps=99999)

				# 【安全检查2】iframe 导航后检查页面安全
				if not await check_page_security(browser, llm, site_name):
					# 关闭浏览器并跳过（仅当本函数创建时）
					if browser_created_here:
						logger.info(f"[{site_name}] 正在关闭浏览器...")
						try:
							await browser.kill()
							logger.info(f"[{site_name}] ✓ 浏览器已关闭")
						except Exception as e:
							logger.warning(f"[{site_name}] 关闭浏览器时出错: {e}")
					return {
						"status": "failed",
						"items_found": 0,
						"pages_processed": 0,
						"error": "iframe页面风控或无法处理的验证码"
					}
			else:
				logger.warning(f"[{site_name}] 无法获取iframe URL，继续处理")

			# ========== [暂不启用] 检测并进入列表页（处理"更多"按钮） ==========
			# 产品侧提供的入口 URL 已经是列表页，先跳过：
			# 1) 判断是否在列表页
			# 2) 检查并点击“更多”进入列表页
			#
			# enter_success = await enter_list_page(browser, llm, site_name)
			# if not enter_success:
			# 	# enter_list_page 执行失败，关闭浏览器并跳过（仅当本函数创建时）
			# 	if browser_created_here:
			# 		logger.info(f"[{site_name}] 正在关闭浏览器...")
			# 		try:
			# 			await browser.kill()
			# 			logger.info(f"[{site_name}] ✓ 浏览器已关闭")
			# 		except Exception as e:
			# 			logger.warning(f"[{site_name}] 关闭浏览器时出错: {e}")
			# 	return {
			# 		"status": "failed",
			# 		"items_found": 0,
			# 		"pages_processed": 0,
			# 		"error": "进入列表页失败"
			# 	}

			# 【安全检查3】进入列表页后检查页面安全
			if not await check_page_security(browser, llm, site_name):
				# 关闭浏览器并跳过（仅当本函数创建时）
				if browser_created_here:
					logger.info(f"[{site_name}] 正在关闭浏览器...")
					try:
						await browser.kill()
						logger.info(f"[{site_name}] ✓ 浏览器已关闭")
					except Exception as e:
						logger.warning(f"[{site_name}] 关闭浏览器时出错: {e}")
				return {
					"status": "failed",
					"items_found": 0,
					"pages_processed": 0,
					"error": "列表页风控或无法处理的验证码"
				}

			# ========== 单 Agent 处理整个网站 ==========
			result = await process_entire_site(
				browser=browser,
				llm=llm,
				filter_prompt=filter_prompt,
				site_name=site_name,
				output_dir=output_dir,
				max_pages=max_pages,
				on_item_saved=on_item_saved,
				date_start=date_start,
				date_end=date_end,
				product_category_table=product_category_table,
				engineering_machinery_only=engineering_machinery_only,
			)
			total_items = result.get("items_found", 0)
			pages_processed = result.get("pages_processed", 0)
			risk_control = result.get("risk_control", False)
			risk_message = result.get("risk_message", "")

			# 关闭浏览器（仅当本函数创建时）
			if browser_created_here:
				logger.info(f"[{site_name}] 正在关闭浏览器...")
				try:
					await browser.kill()
					logger.info(f"[{site_name}] ✓ 浏览器已关闭")
				except Exception as e:
					logger.warning(f"[{site_name}] 关闭浏览器时出错: {e}")

			# 检测到风控，返回特殊状态
			if risk_control:
				logger.warning(f"[{site_name}] ========== 触发风控，提前结束 ==========")
				logger.warning(f"[{site_name}] 已处理 {pages_processed} 页，保存 {total_items} 条")
				return {
					"status": "risk_control",
					"items_found": total_items,
					"pages_processed": pages_processed,
					"error": "触发风控/反爬机制，已停止处理",
					"risk_message": risk_message,
				}

			# 处理完成
			if total_items == 0:
				logger.info(f"[{site_name}] 该网站未匹配到相应投标")
				if output_dir.exists() and not any(output_dir.iterdir()):
					output_dir.rmdir()

			logger.info(f"[{site_name}] ========== 处理完成 ==========")
			logger.info(f"[{site_name}] 共处理 {pages_processed} 页，找到 {total_items} 条匹配")

			return {
				"status": "success",
				"items_found": total_items,
				"pages_processed": pages_processed,
				"error": None
			}

		except BudgetExceededError as e:
			# Budget exceeded: stop immediately, do NOT retry.
			logger.error(f"[{site_name}] 日预算已达上限，停止爬取: {e}")
			if browser and browser_created_here:
				with contextlib.suppress(Exception):
					await browser.kill()
				browser = None
			return {
				"status": "budget_exceeded",
				"items_found": 0,
				"pages_processed": 0,
				"error": str(e),
			}

		except Exception as e:
			retries += 1
			logger.error(f"[{site_name}] 处理失败 (第{retries}/{max_retries}次): {e}")

			if browser and browser_created_here:
				try:
					await browser.kill()
					logger.info(f"[{site_name}] ✓ 浏览器已关闭（异常处理）")
				except:
					pass
				browser = None  # 重置以便重试时重新创建

			if retries < max_retries:
				logger.info(f"[{site_name}] 正在重试...")
				await asyncio.sleep(5)
			else:
				logger.error(f"[{site_name}] 达到最大重试次数，放弃处理")
				return {
					"status": "failed",
					"items_found": 0,
					"pages_processed": 0,
					"error": str(e)
				}

	return {
		"status": "failed",
		"items_found": 0,
		"pages_processed": 0,
		"error": "未知错误"
	}
