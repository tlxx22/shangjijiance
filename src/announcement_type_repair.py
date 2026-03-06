from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel

from .deepseek_langchain import invoke_structured
from .field_schemas import ANNOUNCEMENT_TYPES
from .logger_config import get_logger

logger = get_logger()


AnnouncementTypeLiteral = Literal[
	"预审",
	"招标",
	"询价",
	"竞谈",
	"竞价",
	"邀标",
	"单一",
	"变更",
	"答疑",
	"候选",
	"中标",
	"合同",
	"终止",
]


class AnnouncementTypeRepairResult(BaseModel):
	announcementType: AnnouncementTypeLiteral


class AnnouncementTypeRepairError(RuntimeError):
	"""
	公告类型修复失败（重试用尽）。

	用于 /normalize_item 抛出 422，避免输出错误类型污染下游。
	"""

	def __init__(self, message: str, *, raw_type: str, max_retries: int):
		super().__init__(message)
		self.raw_type = raw_type
		self.max_retries = max_retries


_SYSTEM_PROMPT = """
You are a strict announcement-type classifier for Chinese tender/procurement notices.
Your task is to output the announcement type as EXACTLY one of the following 13 values:
预审, 招标, 询价, 竞谈, 竞价, 邀标, 单一, 变更, 答疑, 候选, 中标, 合同, 终止

Rules:
- Output ONLY valid JSON. No markdown, no code fences, no extra text.
- The JSON must follow schema: {"announcementType": "<one of the 13 values above>"}.
- Use semantic mapping examples:
  - 资格预审/预审公告 -> 预审
  - 招标公告/采购公告/公开招标 -> 招标
  - 询价/询价公告/询价采购 -> 询价
  - 竞争性谈判/竞争性磋商 -> 竞谈
  - 竞价/竞价公告 -> 竞价
  - 邀请招标 -> 邀标
  - 单一来源/单一来源公示 -> 单一
  - 更正/补遗/延期/变更 -> 变更
  - 澄清/澄清公告/澄清文件/澄清通知/答疑/答疑公告/疑问回复/问题答复 -> 答疑
- If the title or content contains clarification / Q&A wording such as "澄清公告", "澄清文件", "澄清通知", "答疑公告", "疑问回复", or "问题答复", classify it as 答疑 even if it also mentions 变更/更正.
  - 中标候选人公示/评标结果公示 -> 候选
  - 中标结果/中标公告/成交结果/成交公告/中选结果 -> 中标
  - 合同公告 -> 合同
  - 终止/废标/流标/失败 -> 终止
""".strip()


def _truncate(text: str, max_chars: int) -> str:
	s = (text or "").strip()
	if not s:
		return ""
	if len(s) <= max_chars:
		return s
	return s[:max_chars]


async def repair_announcement_type(
	*,
	site_name: str,
	announcement_title: str | None,
	announcement_content: str | None,
	raw_announcement_type: str | None,
	max_retries: int = 3,
) -> str | None:
	"""
	当初次抽取的 announcementType 不在 13 选 1 范围内时，调用 LLM 做一次“类型归一化/分类”修复。

	返回：
	- 成功：13 选 1 的类型字符串
	- 失败：None（由上层决定 skip 或 422）
	"""
	title = (announcement_title or "").strip()
	raw_type = (raw_announcement_type or "").strip()
	content = (announcement_content or "").strip()

	# Retry attempts use different excerpt sizes to reduce prompt-size related failures.
	excerpt_limits = [80_000, 30_000, 8_000]
	if max_retries <= 0:
		max_retries = 1

	last_err: Exception | None = None
	for attempt in range(1, max_retries + 1):
		max_chars = excerpt_limits[min(attempt - 1, len(excerpt_limits) - 1)]
		excerpt = _truncate(content, max_chars=max_chars)

		user_prompt = f"""announcementTitle: {title}
rawExtractedAnnouncementType: {raw_type}

contentExcerpt:
{excerpt}
""".strip()

		try:
			result = await asyncio.to_thread(
				invoke_structured,
				[
					{"role": "system", "content": _SYSTEM_PROMPT},
					{"role": "user", "content": user_prompt},
				],
				AnnouncementTypeRepairResult,
			)
			atype = (result.announcementType or "").strip()
			if atype in ANNOUNCEMENT_TYPES:
				return atype
			# Should not happen due to Literal, but keep a guard.
			last_err = ValueError(f"announcementType out of range: {atype!r}")
		except Exception as e:
			last_err = e
			logger.warning(f"[{site_name}] announcementType 修复失败 attempt {attempt}/{max_retries}: {e}")

	if last_err:
		logger.warning(f"[{site_name}] announcementType 修复失败：已达上限 {max_retries} 次（raw={raw_type!r}）")
	return None

