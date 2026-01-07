"""
登录处理模块
智能检测登录状态并自动处理登录流程
"""

from browser_use import Agent, BrowserSession
from .config_manager import SiteConfig
from .logger_config import get_logger

logger = get_logger()


async def smart_login(site_config: SiteConfig, browser, llm) -> bool:
	"""
	智能登录处理
	检测页面是否需要登录，并根据配置决定如何处理

	Args:
		site_config: 网站配置
		browser_session: 浏览器会话
		llm: LLM实例

	Returns:
		是否成功（True=可以继续，False=需要跳过该网站）
	"""
	site_name = site_config.name

	logger.info(f"[{site_name}] 正在检测页面状态...")

	# 使用Agent检测页面状态
	detection_agent = Agent(
		task=f"""
		请先访问这个网站：{site_config.url}

		然后检查当前页面状态，返回以下之一：
		- 'ok': 可以看到招标列表/采购信息/公告列表，无需登录
		- 'need_login': 明确看到登录表单/登录按钮/"请先登录"提示
		- 'unknown': 页面空白、报错

		判断规则：
		1. 只有明确看到登录相关元素才返回 'need_login'
		2. 页面空白、加载失败、错误页面 → 返回 'unknown'
		3. 能看到招标/采购信息列表 → 返回 'ok'
		""",
		llm=llm,
		browser=browser,
		max_steps=3
	)

	try:
		result = await detection_agent.run()
		page_status_raw = result.final_result()

		# 处理None的情况
		if page_status_raw:
			page_status = page_status_raw.strip().lower()
		else:
			page_status = 'unknown'

		# 规范化输出
		if page_status == 'ok' or page_status.endswith("'ok'") or page_status.startswith("ok"):
			page_status = 'ok'
		elif 'need_login' in page_status or 'login' in page_status:
			page_status = 'need_login'
		elif 'unknown' in page_status or 'error' in page_status or 'blank' in page_status:
			page_status = 'unknown'
		else:
			# 无法识别的状态，标记为 unknown 而不是默认 need_login
			page_status = 'unknown'

	except Exception as e:
		# 直接抛出原始错误，不要误报为"需要登录"
		logger.error(f"[{site_name}] 页面状态检测失败: {e}")
		raise  # 让调用方处理实际的错误

	# 根据检测结果和配置决策

	# 【优先检查】如果配置了 login_required=true 且有账号密码，强制登录
	if site_config.login_required and site_config.username and site_config.password:
		if page_status == 'ok':
			logger.info(f"[{site_name}] 页面可访问，但配置要求登录，执行强制登录...")
		else:
			logger.info(f"[{site_name}] 检测到需要登录，使用配置的账号...")
		return await auto_login(site_config, browser, llm)

	# 配置了 login_required 但没有账号密码
	if site_config.login_required:
		logger.error(f"[{site_name}] ⚠️ 配置要求登录，但未提供账号密码")
		logger.info(f"[{site_name}] 跳过该网站")
		return False

	# 未配置 login_required，根据页面状态判断
	if page_status == 'ok':
		logger.info(f"[{site_name}] 页面无需登录，直接抓取")
		return True
	elif page_status == 'need_login':
		# 页面确实需要登录但没配置账号
		logger.error(f"[{site_name}] ⚠️ 检测到登录页面，但配置未提供账号密码")
		logger.info(f"[{site_name}] 跳过该网站")
		return False
	else:
		# unknown: 页面异常（空白、报错、非招标网站等）
		logger.error(f"[{site_name}] ⚠️ 页面状态异常（空白/报错/），跳过")
		return False


async def auto_login(site_config: SiteConfig, browser, llm) -> bool:
	"""
	自动登录

	Args:
		site_config: 网站配置
		browser_session: 浏览器会话
		llm: LLM实例

	Returns:
		是否登录成功
	"""
	site_name = site_config.name
	max_retries = 3

	for attempt in range(1, max_retries + 1):
		try:
			logger.info(f"[{site_name}] 尝试登录 (第{attempt}/{max_retries}次)...")

			# 使用Agent执行登录
			login_agent = Agent(
				task=f"""
				请帮我登录这个网站：

				用户名：{site_config.username}
				密码：{site_config.password}

				步骤：
				1. 找到用户名输入框并填写用户名
				2. 找到密码输入框并填写密码
				3. 如果有验证码，尝试识别并填写（使用vision能力）
				4. 点击登录按钮
				5. 等待页面跳转
				6. 检查是否登录成功（能看到招标列表就算成功）

				如果登录失败，请返回失败原因。
				""",
				llm=llm,
				browser=browser,
				use_vision=True,  # 启用vision用于验证码识别
				max_steps=10
			)

			result = await login_agent.run()

			# 检查是否成功
			# 简单判断：如果Agent没有报错且完成了任务，认为成功
			if result.is_done():
				logger.info(f"[{site_name}] ✓ 登录成功")
				return True
			else:
				logger.warning(f"[{site_name}] 登录可能失败，尝试继续...")
				return True  # 宽松策略：即使不确定也继续

		except Exception as e:
			logger.error(f"[{site_name}] 登录失败 (第{attempt}次): {e}")

			if attempt < max_retries:
				logger.info(f"[{site_name}] 重试中...")
				continue
			else:
				logger.error(f"[{site_name}] 达到最大重试次数，放弃登录")
				return False

	return False
