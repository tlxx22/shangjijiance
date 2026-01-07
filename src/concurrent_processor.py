"""
并发处理模块
使用 asyncio.Queue 动态分配任务，多 Worker 并发执行
"""

import asyncio
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from browser_use import Browser

from .config_manager import SiteConfig, ConcurrencyConfig, get_user_data_dir
from .site_processor import process_site
from .logger_config import setup_worker_logger, get_logger

main_logger = get_logger()


class Worker:
	"""单个 Worker，负责循环处理任务队列中的网站"""

	def __init__(
		self,
		worker_id: int,
		task_queue: asyncio.Queue,
		filter_prompt: str,
		config: ConcurrencyConfig,
		output_base: Path,
		results: List[Dict],
		max_pages: int = 3,
		max_retries: int = 3
	):
		self.worker_id = worker_id
		self.task_queue = task_queue
		self.filter_prompt = filter_prompt
		self.config = config
		self.output_base = output_base
		self.results = results
		self.max_pages = max_pages
		self.max_retries = max_retries
		self.processed_count = 0

		# 创建 Worker 专用 logger
		log_dir = output_base / config.logging.worker_log_dir
		self.logger = setup_worker_logger(worker_id, log_dir)

	async def run(self):
		"""Worker 主循环"""
		self.logger.info(f"Worker {self.worker_id} 启动")
		
		# 记录每个网站的处理结果
		site_results = []

		while True:
			# 尝试从队列获取任务
			try:
				site_config = self.task_queue.get_nowait()
			except asyncio.QueueEmpty:
				break  # 队列空了，退出

			# 处理网站（带超时）
			result = await self.process_one_site(site_config)
			result['name'] = site_config.name
			result['worker_id'] = self.worker_id
			self.results.append(result)
			self.processed_count += 1
			self.task_queue.task_done()
			
			# 记录结果用于汇总
			site_results.append({
				'name': site_config.name,
				'status': result.get('status', 'unknown'),
				'items_found': result.get('items_found', 0),
				'error': result.get('error', '')
			})

		# Worker 结束时输出详细汇总
		self.logger.info(f"")
		self.logger.info(f"========== Worker {self.worker_id} 处理汇总 ==========")
		self.logger.info(f"共处理 {self.processed_count} 个网站")
		
		success_count = sum(1 for r in site_results if r['status'] == 'success')
		failed_count = sum(1 for r in site_results if r['status'] == 'failed')
		total_items = sum(r['items_found'] for r in site_results)
		
		self.logger.info(f"成功: {success_count}, 失败: {failed_count}, 共找到 {total_items} 条匹配")
		self.logger.info(f"")
		
		# 详细列出每个网站的结果
		for r in site_results:
			if r['status'] == 'success':
				self.logger.info(f"  ✓ {r['name']}: 成功, 找到 {r['items_found']} 条")
			else:
				error_msg = r['error'][:100] if r['error'] else '未知错误'
				self.logger.info(f"  ✗ {r['name']}: 失败 - {error_msg}")
		
		self.logger.info(f"========================================")
		self.logger.info(f"")

	async def process_one_site(self, site_config: SiteConfig) -> Dict:
		"""处理单个网站，带超时控制"""
		site_name = site_config.name
		timeout = self.config.concurrency.timeout_per_site
		headless = self.config.browser.headless

		self.logger.info(f"开始处理: {site_name}")

		browser = None
		try:
			# 1. 创建浏览器
			browser = Browser(
				headless=headless,
				keep_alive=True,
				auto_download_pdfs=False,
				enable_default_extensions=False,
			)

			# 2. 带超时执行
			result = await asyncio.wait_for(
				process_site(
					site_config=site_config,
					filter_prompt=self.filter_prompt,
					browser=browser,
					headless=headless,
					max_pages=self.max_pages,
					max_retries=self.max_retries
				),
				timeout=timeout
			)

			self.logger.info(f"✓ 完成: {site_name}, 找到 {result.get('items_found', 0)} 条")
			return result

		except asyncio.TimeoutError:
			self.logger.error(f"⏰ 超时: {site_name} (超过 {timeout} 秒)")
			return {
				"status": "failed",
				"items_found": 0,
				"pages_processed": 0,
				"error": f"处理超时（{timeout}秒）"
			}

		except Exception as e:
			self.logger.error(f"❌ 失败: {site_name} - {e}")
			return {
				"status": "failed",
				"items_found": 0,
				"pages_processed": 0,
				"error": str(e)
			}

		finally:
			# 3. 无论如何都关闭浏览器
			if browser:
				try:
					await browser.kill()
					self.logger.info(f"浏览器已关闭: {site_name}")
				except Exception as e:
					self.logger.warning(f"关闭浏览器失败: {e}")


async def run_concurrent(
	websites: List[SiteConfig],
	filter_prompt: str,
	config: ConcurrencyConfig,
	max_pages: int = 3,
	max_retries: int = 3
) -> List[Dict]:
	"""
	并发处理所有网站

	Args:
		websites: 网站配置列表
		filter_prompt: 筛选提示词
		config: 并发配置
		max_pages: 每个网站最大翻页数
		max_retries: 每个网站最大重试次数

	Returns:
		所有网站的处理结果
	"""
	main_logger.info(f"启动并发模式：{config.concurrency.max_workers} 个 Worker")
	main_logger.info(f"待处理网站：{len(websites)} 个")
	main_logger.info(f"单站超时：{config.concurrency.timeout_per_site} 秒")

	# 创建输出目录
	today = datetime.now().strftime('%Y-%m-%d')
	output_base = Path("output") / today
	output_base.mkdir(parents=True, exist_ok=True)

	# 创建任务队列并填充
	task_queue = asyncio.Queue()
	for site in websites:
		await task_queue.put(site)

	# 共享结果列表（线程安全，因为是单线程 asyncio）
	results = []

	# 创建 Workers（数量不超过网站数）
	num_workers = min(config.concurrency.max_workers, len(websites))
	workers = [
		Worker(
			worker_id=i + 1,
			task_queue=task_queue,
			filter_prompt=filter_prompt,
			config=config,
			output_base=output_base,
			results=results,
			max_pages=max_pages,
			max_retries=max_retries
		)
		for i in range(num_workers)
	]

	# 并发执行所有 Workers
	main_logger.info(f"启动 {num_workers} 个 Worker...")
	await asyncio.gather(*[w.run() for w in workers])

	main_logger.info(f"所有 Worker 完成，共处理 {len(results)} 个网站")

	return results
