"""
商机监测智能体 - 主程序入口
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console

from src.logger_config import setup_logger
from src.config_manager import load_config, load_concurrency_config
from src.site_processor import process_site
from src.concurrent_processor import run_concurrent

# 加载.env文件中的环境变量
load_dotenv()

console = Console()


async def main():
	"""主程序入口"""

	# 初始化日志
	logger = setup_logger()

	# 打印欢迎信息
	console.print("\n[bold cyan]========================================[/bold cyan]")
	console.print("[bold cyan]    商机监测智能体 v1.0[/bold cyan]")
	console.print("[bold cyan]========================================[/bold cyan]\n")

	try:
		# 加载配置
		logger.info("正在加载配置文件...")
		config = load_config()
		concurrency_config = load_concurrency_config()

		website_count = len(config.websites)
		logger.info(f"已加载 {website_count} 个网站配置")
		logger.info(f"筛选条件已加载（共 {len(config.prompt)} 字符）")

		# 创建输出目录
		today = datetime.now().strftime('%Y-%m-%d')
		output_dir = Path("output") / today
		output_dir.mkdir(parents=True, exist_ok=True)

		# 判断运行模式
		if concurrency_config.concurrency.enabled:
			# ========== 并发模式 ==========
			console.print(f"[bold green]运行模式: 并发[/bold green]")
			console.print(f"Worker 数量: {concurrency_config.concurrency.max_workers}")
			console.print(f"单站超时: {concurrency_config.concurrency.timeout_per_site} 秒")
			console.print(f"无头模式: {concurrency_config.browser.headless}\n")

			logger.info(f"\n开始并发处理 {website_count} 个网站...")

			results = await run_concurrent(
				websites=config.websites,
				filter_prompt=config.prompt,
				config=concurrency_config,
				max_pages=config.max_pages,
				max_retries=config.max_retries
			)
		else:
			# ========== 串行模式（原有逻辑） ==========
			console.print(f"[bold yellow]运行模式: 串行[/bold yellow]\n")

			logger.info(f"\n开始处理 {website_count} 个网站...")
			results = []

			# 使用rich进度条
			with Progress(
				SpinnerColumn(),
				TextColumn("[progress.description]{task.description}"),
				BarColumn(),
				TaskProgressColumn(),
				console=console
			) as progress:

				task = progress.add_task(
					f"[cyan]处理网站",
					total=website_count
				)

				for idx, site_config in enumerate(config.websites, 1):
					# 更新进度条描述
					progress.update(
						task,
						description=f"[cyan]处理网站 ({idx}/{website_count}): {site_config.name}"
					)

					# 处理单个网站
					result = await process_site(
						site_config=site_config,
						filter_prompt=config.prompt,
						max_pages=config.max_pages,
						max_retries=config.max_retries
					)

					# 添加网站名称到结果
					result['name'] = site_config.name
					results.append(result)

					# 更新进度
					progress.update(task, advance=1)

		# 生成汇总报告
		logger.info("\n正在生成汇总报告...")
		summary = generate_summary(results)

		# 保存summary.json
		summary_path = output_dir / "summary.json"
		with open(summary_path, 'w', encoding='utf-8') as f:
			json.dump(summary, f, ensure_ascii=False, indent=2)

		logger.info(f"✓ 汇总报告已保存: {summary_path}")

		# 打印最终统计
		print_final_stats(summary)

		logger.info("\n========== 全部完成 ==========")

	except FileNotFoundError as e:
		logger.error(f"配置文件错误: {e}")
		logger.error("请确保 sites_config.yaml 和 prompt.txt 文件存在")
		return 1

	except ValueError as e:
		logger.error(f"配置文件格式错误: {e}")
		return 1

	except Exception as e:
		logger.error(f"程序执行出错: {e}", exc_info=True)
		return 1

	return 0


def generate_summary(results: list) -> dict:
	"""
	生成汇总报告

	Args:
		results: 所有网站的处理结果

	Returns:
		汇总字典
	"""
	total_websites = len(results)
	successful = sum(1 for r in results if r['status'] == 'success')
	failed = total_websites - successful
	total_items = sum(r['items_found'] for r in results)

	# 按网站统计
	by_website = []
	for result in results:
		by_website.append({
			"name": result['name'],
			"status": result['status'],
			"items_found": result['items_found'],
			"pages_processed": result.get('pages_processed', 0),
			"error": result.get('error')
		})

	summary = {
		"date": datetime.now().strftime('%Y-%m-%d'),
		"generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
		"summary": {
			"total_websites": total_websites,
			"successful": successful,
			"failed": failed,
			"total_items_found": total_items
		},
		"by_website": by_website
	}

	return summary


def print_final_stats(summary: dict):
	"""
	打印最终统计信息

	Args:
		summary: 汇总字典
	"""
	stats = summary['summary']

	console.print("\n[bold green]========== 执行统计 ===========[/bold green]")
	console.print(f"[green]处理网站总数:[/green] {stats['total_websites']}")
	console.print(f"[green]成功:[/green] {stats['successful']}")
	console.print(f"[red]失败:[/red] {stats['failed']}")
	console.print(f"[yellow]找到匹配条目:[/yellow] {stats['total_items_found']}")
	console.print("[bold green]================================[/bold green]\n")

	# 显示每个网站的详情
	if stats['failed'] > 0:
		console.print("[yellow]失败的网站：[/yellow]")
		for site in summary['by_website']:
			if site['status'] == 'failed':
				console.print(f"  - {site['name']}: {site['error']}")
		console.print()


def run():
	"""CLI入口点"""
	try:
		exit_code = asyncio.run(main())
		return exit_code
	except KeyboardInterrupt:
		console.print("\n[yellow]程序被用户中断[/yellow]")
		return 130


if __name__ == "__main__":
	exit(run())
