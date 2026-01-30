"""
列表页处理模块
边扫描边处理：发现符合条件的条目立即点击处理
使用自定义工具让Agent自行完成公告原文(MD)提取和保存
"""

import json
import asyncio
from pathlib import Path
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from browser_use import Agent
from .logger_config import get_logger
from .custom_tools import create_save_detail_tools
from .prompts import GLOBAL_RULES

logger = get_logger()


class ProcessResult(BaseModel):
	"""Agent 处理结果的结构化输出模型"""
	saved_count: int = Field(description="保存的条目数量")
	pages_processed: int = Field(description="处理的页数")
	titles: List[str] = Field(default_factory=list, description="已保存的标题列表")
	risk_control: bool = Field(default=False, description="是否触发风控")


def count_saved_files(output_dir: Path) -> int:
	"""
	统计输出目录中已保存的 JSON 文件数量

	Args:
		output_dir: 输出目录路径

	Returns:
		JSON 文件数量
	"""
	if not output_dir.exists():
		return 0
	return len(list(output_dir.glob("*.json")))


def save_analysis_log(result, output_dir: Path, site_name: str) -> None:
	"""
	从Agent运行结果中提取分析日志并保存到txt文件

	Args:
		result: Agent运行结果（AgentHistory对象）
		output_dir: 输出目录
		site_name: 网站名称
	"""
	try:
		from datetime import datetime

		# 确保目录存在
		output_dir.mkdir(parents=True, exist_ok=True)

		# 提取Memory信息
		analysis_lines = []
		analysis_lines.append(f"{'='*60}")
		analysis_lines.append(f"网站: {site_name}")
		analysis_lines.append(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
		analysis_lines.append(f"{'='*60}\n")

		# 从history中提取每一步的Memory
		if hasattr(result, 'history') and result.history:
			for i, step in enumerate(result.history, 1):
				# 提取memory信息
				if hasattr(step, 'model_output') and step.model_output:
					memory = getattr(step.model_output, 'current_state', None)
					if memory and hasattr(memory, 'memory'):
						memory_text = memory.memory
						# 只保存包含分析内容的Memory（通常包含条目分析）
						if any(keyword in memory_text for keyword in [
							'Analysis', 'Exclude', 'Include', 'Match', '排除', '符合',
							'Page', '页', 'item', 'Items', '条目'
						]):
							analysis_lines.append(f"--- Step {i} ---")
							analysis_lines.append(memory_text)
							analysis_lines.append("")

		# 如果没有提取到分析内容，记录原因
		if len(analysis_lines) <= 4:
			analysis_lines.append("（未提取到条目分析日志）")

		# 保存到文件
		log_path = output_dir / "analysis_log.txt"
		with open(log_path, 'w', encoding='utf-8') as f:
			f.write('\n'.join(analysis_lines))

		logger.info(f"[{site_name}] ✓ 分析日志已保存: {log_path.name}")

	except Exception as e:
		logger.warning(f"[{site_name}] 保存分析日志失败: {e}")


async def process_entire_site(
	browser,
	llm,
	filter_prompt: str,
	site_name: str,
	output_dir: Path,
	max_pages: int = 5,
	max_items_per_page: int = 10,
	on_item_saved=None,
	date_start: str | None = None,
	date_end: str | None = None
) -> Dict:
	"""
	单个 Agent 处理整个网站的所有页面

	Args:
		browser: 浏览器实例
		llm: LLM实例
		filter_prompt: 筛选提示词
		site_name: 网站名称
		output_dir: 输出目录
		max_pages: 最大翻页数
		max_items_per_page: 每页最多处理的条目数

	Returns:
		字典 {"items_found": N, "pages_processed": M}
	"""
	logger.info(f"[{site_name}] 开始处理网站，最多 {max_pages} 页...")

	# 创建自定义工具（传入 llm 用于字段提取，传入回调用于 SSE 输出）
	tools = create_save_detail_tools(output_dir, site_name, llm=llm, on_item_saved=on_item_saved)

	# 日期筛选指令（使用 API 传入的日期，否则默认近2天）
	from datetime import datetime, timedelta
	if date_start and date_end:
		start_date = date_start
		end_date = date_end
	else:
		today = datetime.now()
		yesterday = today - timedelta(days=1)
		start_date = yesterday.strftime('%Y-%m-%d')
		end_date = today.strftime('%Y-%m-%d')

	# 构建Agent任务（全局规则已通过 extend_system_message 注入）
	task = f"""
{filter_prompt}

---

IMPORTANT:
- Do NOT use `write_file` / `replace_file` / `read_file` (e.g., todo.md/results.md) as business output or progress tracking.
- The ONLY valid way to save/output an announcement is to call `save_detail` on the detail page.

**【第一步：筛选操作】**

在开始处理条目之前，请先进行以下筛选（如果页面有这些选项）：
### 如果有关于筛选的"重置"按钮, 优先点击"重置"按钮再进行筛选
1. **业务类型**：点击"不限"
2. **信息类型**：点击"不限"（获取所有类型的公告）
3. **日期筛选**（需判断筛选字段类型）：
   - **首先观察**筛选控件的标签：是"发布日期"还是"截止日期/开标时间"？
   - **如果是"发布日期"类筛选**：
     - 优先点击快捷按钮（如"近一天"、"近三天"）
     - 或使用日历选择 {start_date} 到 {end_date}
     - ?? **务必确认年份正确**：不要把 {end_date} 选成上一年（如 2025），选完后检查输入框显示的年份与 {start_date}/{end_date} 一致
   - **如果是"截止日期/开标时间"类筛选**：
     - ⚠️ 不要用 {start_date}~{end_date} 去筛选
     - 可以选择"从 {end_date} 开始"或干脆不做日期筛选
     - 让后续的条目判断规则来过滤
   - 如果日历弹窗有"确定"按钮，选完日期后要点击"确定"

完成筛选后点击"搜索"或"查询"按钮。

---

**【第二步：处理所有页面的条目】**

你需要处理 **最多 {max_pages} 页** 的招标条目。

**对于每一页，重复以下流程：**

1. **滚动查看**当前页面，找到符合条件的招标条目
2. **提取信息**：记录标题和发布日期
3. **点击标题**打开详情页（会在新标签页打开）
4. **按全局规则执行标签页操作**：switch → wait → save_detail → close → switch → wait
5. **继续处理**当前页面的下一个条目
6. **当前页处理完后**，点击"下一页"翻到下一页
7. **重复**直到处理完 {max_pages} 页或没有更多页面

**⚠️ 重要提示：**
- 每个条目只点击一次，不要重复处理
- 每页最多处理 {max_items_per_page} 个条目
- **翻页限制**：最多翻 {max_pages} 页，达到后用 done 返回结果
- 如果没有"下一页"按钮或已到最后一页，也用 done 返回结果

---

**【返回格式】**

处理完成后用 done 返回 JSON：
```json
{{"saved_count": N, "pages_processed": M, "titles": ["标题1", "标题2", ...]}}
```
- N: 保存的条目总数
- M: 处理的页数
- titles: 已保存的标题列表
"""

	try:
		# 计算 max_steps：每页条目数 * 每条目步数 * 页数 + 筛选步数 + 验证码余量
		max_steps = max_pages * max_items_per_page * 8 + 50

		agent = Agent(
			task=task,
			llm=llm,
			browser=browser,
			tools=tools,
			output_model_schema=ProcessResult,
			extend_system_message=GLOBAL_RULES,
			max_steps=max_steps,
			step_timeout=240,
		)

		result = await agent.run()

		# 保存分析日志到txt文件
		save_analysis_log(result, output_dir, site_name)

		# 统计实际保存的文件数（兜底）
		actual_saved = count_saved_files(output_dir)

		# 优先使用结构化输出
		if result.structured_output:
			structured = result.structured_output
			saved_count = structured.saved_count
			pages_processed = structured.pages_processed
			titles = structured.titles
			risk_control = structured.risk_control
			# 使用 Agent 返回值和文件计数的较大值
			final_count = max(saved_count, actual_saved)

			if risk_control:
				logger.warning(f"[{site_name}] ⚠️ 检测到风控，已处理 {pages_processed} 页，保存 {final_count} 条")
			else:
				logger.info(f"[{site_name}] 处理完成：{pages_processed} 页，保存 {final_count} 条（结构化输出）")

			for title in titles:
				logger.info(f"  - {title[:50]}...")
			return {"items_found": final_count, "pages_processed": pages_processed, "risk_control": risk_control}

		# 结构化输出失败，尝试解析原始输出
		output_raw = result.final_result()
		if output_raw:
			result_data = parse_item_from_output(output_raw)
			if result_data:
				# 检测是否触发风控
				if result_data.get('risk_control'):
					logger.warning(f"[{site_name}] ⚠️ 检测到风控/反爬机制，停止处理")
					return {
						"items_found": actual_saved,
						"pages_processed": result_data.get('pages_processed', 1),
						"risk_control": True
					}
				saved_count = result_data.get('saved_count', 0)
				pages_processed = result_data.get('pages_processed', 1)
				titles = result_data.get('titles', [])
				risk_control = result_data.get('risk_control', False)
				final_count = max(saved_count, actual_saved)

				if risk_control:
					logger.warning(f"[{site_name}] ⚠️ 检测到风控，已处理 {pages_processed} 页，保存 {final_count} 条")
				else:
					logger.info(f"[{site_name}] 处理完成：{pages_processed} 页，保存 {final_count} 条（JSON解析）")

				for title in titles:
					logger.info(f"  - {title[:50]}...")
				return {"items_found": final_count, "pages_processed": pages_processed, "risk_control": risk_control}

		# 都失败了，用文件计数兜底
		if actual_saved > 0:
			logger.info(f"[{site_name}] 解析失败，但实际保存了 {actual_saved} 个文件")
		else:
			logger.info(f"[{site_name}] 没有匹配条目")
		return {"items_found": actual_saved, "pages_processed": 1, "risk_control": False}

	except Exception as e:
		logger.error(f"[{site_name}] 处理失败: {e}")
		# 即使出错也统计已保存的文件
		actual_saved = count_saved_files(output_dir)
		if actual_saved > 0:
			logger.info(f"[{site_name}] 虽然出错，但已保存 {actual_saved} 个文件")
		return {"items_found": actual_saved, "pages_processed": 0, "risk_control": False}


async def process_all_page_items(
	browser,
	llm,
	filter_prompt: str,
	site_name: str,
	output_dir: Path,
	page_num: int,
	is_first_page: bool = False,
	max_items_per_page: int = 10
) -> int:
	"""
	处理当前页面的所有符合条件的条目（Agent自主完成全部流程）

	Args:
		browser: 浏览器实例
		llm: LLM实例
		filter_prompt: 筛选提示词
		site_name: 网站名称
		output_dir: 输出目录（如 output/2025-12-23/网站名称）
		page_num: 当前页码
		is_first_page: 是否是第一页
		max_items_per_page: 每页最多处理的条目数

	Returns:
		成功保存的条目数量
	"""
	logger.info(f"[{site_name}] 第 {page_num} 页：开始处理所有匹配条目...")

	# 创建自定义工具（传入 llm 用于字段提取）
	tools = create_save_detail_tools(output_dir, site_name, llm=llm)

	# 构建日期筛选指令（仅第一页）
	date_filter_instruction = ""
	if is_first_page:
		from datetime import datetime, timedelta
		today = datetime.now()
		yesterday = today - timedelta(days=1)
		start_date = yesterday.strftime('%Y-%m-%d')
		end_date = today.strftime('%Y-%m-%d')
		date_filter_instruction = f"""
**【仅限第一页】筛选操作：**

**1. 业务类型筛选（如有）：**
如果页面有"业务类型"、"项目类型"等筛选选项，请点击"不限"（确保不遗漏任何类型的招标信息）。

**2. 信息类型筛选（如有）：**
如果页面有"信息类型"、"公告类型"等筛选选项，请点击"不限"（获取所有类型的公告）。

**3. 日期筛选（如有）：**
- **优先点击快捷按钮**：如"近一天"、"近三天"、"今天"等按钮（推荐）
- 如果没有快捷按钮，尝试点击日期输入框旁边的日历图标选择日期
- 最后才尝试直接输入日期 {start_date} 到 {end_date}
- ?? 选完后检查年份是否正确（不要选成上一年）

完成所有筛选后点击"搜索"或"查询"按钮，等待页面刷新后再分析筛选结果。
"""

	# 构建Agent任务
	task = f"""
🚫🚫🚫 **【最高优先级约束 - 违反即失败】** 🚫🚫🚫

**绝对禁止翻页！！！**
- 禁止点击"下一页"、"下页"、">"、页码数字
- 禁止点击任何分页按钮或链接
- 翻页由外部程序控制，你只负责当前页面！

🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫

---

{filter_prompt}

{date_filter_instruction}

---

**你的任务：处理当前页面（第 {page_num} 页）的所有符合条件的招标条目**

**完整处理流程（对每个符合条件的条目重复执行）：**

1. **滚动查看**：在当前列表页滚动查看，找到一个符合筛选条件的条目
2. **记录信息**：提取该条目的【完整标题】和【发布日期】（格式 YYYY-MM-DD）
3. **点击打开**：点击该条目的标题链接（会在新标签页打开）
4. **切换标签**：使用 `switch` 动作切换到新打开的详情页标签
5. **保存详情**：调用 `save_detail` 工具（抓取公告原文MD + 字段），传入标题和日期参数
6. **关闭标签**：使用 `close` 动作关闭当前详情页标签（会自动回到列表页）
7. **继续处理**：回到步骤1，寻找下一个符合条件的条目

**⚠️ 重要提示：**
- 每个条目【只点击一次】，不要重复点击同一个条目
- 在详情页记得等待页面加载完成再提取原文
- 最多处理 {max_items_per_page} 个条目
- 当前页面所有符合条件的条目都处理完后，用 done 返回结果

**关于标签页操作：**
- `switch` 动作：切换到指定标签页（通过 tab_id）
- `close` 动作：关闭指定标签页
- 新标签页打开后，你需要查看 browser_state 中的 tabs 列表找到新标签的 tab_id

**返回格式（JSON）：**
```json
{{"saved_count": N, "titles": ["标题1", "标题2", ...]}}
```
其中 N 是成功保存的条目数量，titles 是已保存的标题列表。
如果没有符合条件的条目，返回：
```json
{{"saved_count": 0, "titles": []}}
```
"""

	try:
		agent = Agent(
			task=task,
			llm=llm,
			browser=browser,
			tools=tools,
			extend_system_message=GLOBAL_RULES,
			max_steps=max_items_per_page * 8,  # 每个条目大约需要8步：滚动+点击+switch+等待+save_detail+close+返回列表+下一个
			step_timeout=240,
		)

		result = await agent.run()
		output_raw = result.final_result()

		# 处理None的情况
		if not output_raw:
			logger.warning(f"[{site_name}] Agent未返回有效输出")
			return 0

		# 解析JSON
		result_data = parse_item_from_output(output_raw)

		if result_data:
			saved_count = result_data.get('saved_count', 0)
			titles = result_data.get('titles', [])
			logger.info(f"[{site_name}] 第 {page_num} 页处理完成，保存了 {saved_count} 个条目")
			for title in titles:
				logger.info(f"  - {title[:50]}...")
			return saved_count
		else:
			logger.info(f"[{site_name}] 第 {page_num} 页没有匹配条目")
			return 0

	except Exception as e:
		logger.error(f"[{site_name}] 第 {page_num} 页处理失败: {e}")
		return 0


async def find_and_click_next_item(
	browser,
	llm,
	filter_prompt: str,
	processed_titles: List[str],
	site_name: str,
	page_num: int,
	is_first_page: bool = False
) -> Optional[Dict]:
	"""
	在当前页面找到下一个符合条件的条目并点击进入详情页

	Args:
		browser: 浏览器实例
		llm: LLM实例
		filter_prompt: 筛选提示词
		processed_titles: 已处理过的标题列表（用于跳过）
		site_name: 网站名称
		page_num: 当前页码
		is_first_page: 是否是第一页

	Returns:
		匹配的条目信息 {title, date}，如果没有更多条目返回 None
	"""
	logger.info(f"[{site_name}] 第 {page_num} 页：寻找下一个匹配条目...")

	# 构建已处理条目的提示
	skip_instruction = ""
	if processed_titles:
		skip_list = "\n".join([f"- {t[:50]}..." if len(t) > 50 else f"- {t}" for t in processed_titles])
		skip_instruction = f"""
**⚠️ 已处理过的条目（必须跳过）：**
{skip_list}

请在页面中找到一个【不在上述列表中】的符合条件的条目。
"""

	# 构建日期筛选指令（仅第一页）
	date_filter_instruction = ""
	if is_first_page:
		from datetime import datetime, timedelta
		today = datetime.now()
		yesterday = today - timedelta(days=1)
		start_date = yesterday.strftime('%Y-%m-%d')
		end_date = today.strftime('%Y-%m-%d')
		date_filter_instruction = f"""
**【仅限第一页】日期筛选操作：**
如果页面上有日期筛选功能（如"发布时间"筛选框），请先设置日期范围为 {start_date} 到 {end_date}，然后点击搜索。
完成日期筛选后再分析筛选结果。
注意：如果使用日历控件选择日期，务必确认年份与 {start_date}/{end_date} 一致（不要选成上一年）。
"""

	# 构建Agent任务
	task = f"""
🚫🚫🚫 **【最高优先级约束 - 违反即失败】** 🚫🚫🚫

**绝对禁止翻页！！！**
- 禁止点击"下一页"、"下页"、">"、页码数字
- 禁止点击任何分页按钮或链接
- 如果当前页面没有符合条件的条目，直接返回 {{"found": false}}
- 翻页由外部程序控制，你只负责当前页面！

🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫🚫

---

{filter_prompt}

{date_filter_instruction}

{skip_instruction}

---

**你的任务：在【当前页面】找到并点击一个符合条件的招标条目**

步骤：
1. 只在当前页面滚动查看条目（禁止翻页！）
2. 找到一个符合筛选条件的条目（日期在最近2天内，且类型匹配）
3. 点击该条目的标题链接，然后立即返回结果

**⚠️⚠️⚠️ 关于点击操作（极其重要）：**
- 链接会在**新标签页**中打开，当前页面不会变化
- **只点击一次！** 点击后任务就结束了
- **点击后不要再执行任何操作**，直接用done返回结果
- 如果你已经点击过了，**绝对不要再点击**，直接返回结果
- ⛔ 每个任务只能点击一次，多次点击=任务失败

**约束：**
- 只处理【一个】条目，只点击【一次】
- 跳过"已处理过的条目"列表中的条目
- ⛔ **禁止翻页！当前页面没有就返回found:false**

**返回格式（JSON）：**
```json
{{"found": true, "title": "完整的招标标题", "date": "YYYY-MM-DD"}}
```
或
```json
{{"found": false}}
```
"""

	try:
		agent = Agent(
			task=task,
			llm=llm,
			browser=browser,
			extend_system_message=GLOBAL_RULES,
			max_steps=3,  # 滚动(1) + 点击(1) + 返回(1)，无翻页余地
			step_timeout=240,
		)

		result = await agent.run()
		output_raw = result.final_result()

		# 处理None的情况
		if not output_raw:
			logger.warning(f"[{site_name}] Agent未返回有效输出")
			return None

		# 解析JSON
		item = parse_item_from_output(output_raw)

		if item and item.get('found'):
			logger.info(f"[{site_name}] ✓ 找到并点击: {item.get('title', '')[:50]}...")
			return {
				'title': item.get('title', ''),
				'date': item.get('date', '')
			}
		else:
			logger.info(f"[{site_name}] 当前页面没有更多匹配条目")
			return None

	except Exception as e:
		logger.error(f"[{site_name}] 查找条目失败: {e}")
		return None


def parse_item_from_output(output: str) -> Optional[Dict]:
	"""
	从Agent输出中解析单个条目的JSON

	Args:
		output: Agent的输出文本

	Returns:
		解析后的字典，失败返回None
	"""
	import re

	# 方法1: 尝试直接解析
	try:
		data = json.loads(output)
		if isinstance(data, dict):
			return data
	except:
		pass

	# 方法2: 处理转义字符
	try:
		unescaped = output.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
		data = json.loads(unescaped)
		if isinstance(data, dict):
			return data
	except:
		pass

	# 方法3: 查找 ```json ... ``` 或 {...} 格式
	json_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```|(\{[\s\S]*?\})'
	matches = re.findall(json_pattern, output)

	for match in matches:
		json_str = match[0] or match[1]
		try:
			data = json.loads(json_str)
			if isinstance(data, dict):
				return data
		except:
			pass
		# 尝试处理转义字符
		try:
			unescaped = json_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
			data = json.loads(unescaped)
			if isinstance(data, dict):
				return data
		except:
			continue

	logger.warning("无法从输出中解析JSON")
	return None


async def goto_next_page(browser, llm, site_name: str, current_page: int) -> bool:
	"""
	翻到下一页

	Args:
		browser: 浏览器实例
		llm: LLM实例
		site_name: 网站名称
		current_page: 当前页码

	Returns:
		是否成功翻页
	"""
	try:
		logger.info(f"[{site_name}] 正在翻到第 {current_page + 1} 页...")

		agent = Agent(
			task=f"""
			当前在第 {current_page} 页，请翻到第 {current_page + 1} 页。

			可能的方式：
			1. 点击"下一页"按钮
			2. 点击页码"{current_page + 1}"
			3. 在页码输入框中输入"{current_page + 1}"并回车

			请选择合适的方式翻页。
			""",
			llm=llm,
			browser=browser,
			extend_system_message=GLOBAL_RULES,
			max_steps=3,
			step_timeout=240,
		)

		await agent.run()

		# 等待页面加载
		await asyncio.sleep(2)

		logger.info(f"[{site_name}] ✓ 成功翻到第 {current_page + 1} 页")
		return True

	except Exception as e:
		logger.error(f"[{site_name}] 翻页失败: {e}")
		return False


# ============ 以下是旧的函数，保留用于向后兼容 ============

async def analyze_and_filter_page(
	browser,
	llm,
	filter_prompt: str,
	site_name: str,
	page_num: int,
	is_first_page: bool = False
) -> List[Dict]:
	"""
	[旧版函数 - 保留向后兼容]
	分析当前页面的所有招标条目，筛选符合条件的

	Args:
		browser: 浏览器实例
		llm: LLM实例
		filter_prompt: 筛选提示词
		site_name: 网站名称
		page_num: 当前页码
		is_first_page: 是否是第一页（仅第一页允许使用网站日期筛选功能）

	Returns:
		匹配的条目列表，每个条目包含：
		{
			"title": "招标标题",
			"date": "2025-12-18"
		}
	"""
	logger.warning(f"[{site_name}] 使用旧版 analyze_and_filter_page 函数")

	# 构建日期筛选指令（仅第一页）
	date_filter_instruction = ""
	if is_first_page:
		from datetime import datetime, timedelta
		today = datetime.now()
		yesterday = today - timedelta(days=1)
		start_date = yesterday.strftime('%Y-%m-%d')
		end_date = today.strftime('%Y-%m-%d')
		date_filter_instruction = f"""
**【仅限第一页】日期筛选操作：**
如果页面上有日期筛选功能（如"发布时间"筛选框），请先设置日期范围为 {start_date} 到 {end_date}，然后点击搜索。
完成日期筛选后再分析筛选结果。
注意：如果使用日历控件选择日期，务必确认年份与 {start_date}/{end_date} 一致（不要选成上一年）。
"""
	else:
		date_filter_instruction = """
**⚠️ 这不是第一页，禁止使用日期筛选功能！日期筛选已在第一页完成。**
"""

	# 构建Agent任务
	task = f"""
{filter_prompt}

{date_filter_instruction}

---

**⚠️ 严格约束（违反将导致任务失败）：**

🚫 **绝对禁止的操作：**
1. **禁止点击"下一页"、"下页"、页码数字或任何分页按钮** - 翻页由外部程序控制！
2. **禁止滚动后继续翻页** - 你只能分析当前页面！
3. **禁止循环遍历多个页面** - 只处理第 {page_num} 页！

✅ **允许的操作：**
1. **多次滚动**查看当前页的所有条目（必须从头滚到尾）
2. 使用extract工具提取当前页内容
3. 分析完成后立即用done返回结果

---

**你的任务：分析当前页面（第 {page_num} 页）的招标信息**

步骤：
1. **完整滚动页面**：先滚动到页面底部，再滚动回顶部，确保看到所有条目
2. 使用extract提取所有招标条目的标题和日期
3. **仔细检查每一条的日期**，筛选出符合条件的条目：
   - title: 招标标题（必须完整准确）
   - date: 发布日期，格式YYYY-MM-DD

4. **立即**用done返回JSON结果，格式如下：
```json
[
	{{"title": "某某工程招标公告", "date": "2025-12-18"}},
	...
]
```

**关键提醒：**
- ⚠️ **日期判断要仔细**：逐条检查日期，不要遗漏符合日期条件的条目！
- 如果没有符合条件的条目，返回 `[]`
- 只返回纯JSON，不要有任何说明文字
- **分析完当前页后必须立即返回，不要翻页！**
"""

	try:
		agent = Agent(
			task=task,
			llm=llm,
			browser=browser,
			extend_system_message=GLOBAL_RULES,
			max_steps=8,
			step_timeout=240,
		)

		result = await agent.run()
		output_raw = result.final_result()

		# 处理None的情况
		if not output_raw:
			logger.warning(f"[{site_name}] Agent未返回有效输出")
			return []

		# 解析JSON
		items = parse_json_from_output(output_raw)
		logger.info(f"[{site_name}] 第 {page_num} 页找到 {len(items)} 条匹配")

		return items

	except Exception as e:
		logger.error(f"[{site_name}] 第 {page_num} 页分析失败: {e}")
		return []


def parse_json_from_output(output: str) -> List[Dict]:
	"""
	从Agent输出中解析JSON列表

	Args:
		output: Agent的输出文本

	Returns:
		解析后的列表
	"""
	import re

	# 方法1: 尝试直接解析
	try:
		data = json.loads(output)
		if isinstance(data, list):
			return data
	except:
		pass

	# 方法2: 处理转义字符
	try:
		unescaped = output.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
		data = json.loads(unescaped)
		if isinstance(data, list):
			return data
	except:
		pass

	# 方法3: 查找 ```json ... ``` 或 [...] 格式
	json_pattern = r'```(?:json)?\s*(\[[\s\S]*?\])\s*```|(\[[\s\S]*?\])'
	matches = re.findall(json_pattern, output)

	for match in matches:
		json_str = match[0] or match[1]
		try:
			data = json.loads(json_str)
			if isinstance(data, list):
				return data
		except:
			pass
		# 尝试处理转义字符
		try:
			unescaped = json_str.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
			data = json.loads(unescaped)
			if isinstance(data, list):
				return data
		except:
			continue

	logger.warning("无法从输出中解析JSON，返回空列表")
	return []
