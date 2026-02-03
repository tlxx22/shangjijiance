"""
字段 Schema 与归一化工具（V2）

- 公告类别（13 选 1）归一化
- 金额单位统一为“万元”
- lotProducts / lotCandidates Pydantic 模型（容错输入 + 统一输出）
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, RootModel, AliasChoices, field_validator, model_validator

from .logger_config import get_logger
from .concrete_product_table import match_concrete_product_from_subject, normalize_concrete_product_name

logger = get_logger()

_EMPTY_STRINGS = {"", "[]", "null", "none", "-", "无", "暂无", "不详"}
_SEP = r"[,，;；、\n]+"


# ===== 公告类别（13 选 1）=====

ANNOUNCEMENT_TYPES = {
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
}

ANNOUNCEMENT_TYPE_MAPPING = {
	# 预审
	"资格预审": "预审",
	"预审公告": "预审",
	# 招标
	"招标公告": "招标",
	"采购公告": "招标",
	# 询价
	"询价公告": "询价",
	"询价采购": "询价",
	# 竞谈
	"竞争性谈判": "竞谈",
	# 竞价
	"竞价公告": "竞价",
	# 邀标
	"邀请招标": "邀标",
	# 单一
	"单一来源": "单一",
	"单一来源公示": "单一",
	# 变更（含延期/更正/补遗）
	"变更公告": "变更",
	"延期公告": "变更",
	"更正公告": "变更",
	"补遗": "变更",
	# 答疑（含澄清）
	"答疑公告": "答疑",
	"澄清公告": "答疑",
	"澄清": "答疑",
	# 候选
	"候选人公示": "候选",
	"评标结果公示": "候选",
	# 中标（含成交 → 中标）
	"中标公告": "中标",
	"中标结果": "中标",
	"招标结果": "中标",
	"成交公告": "中标",
	"成交结果": "中标",
	"成交结果公告": "中标",
	"成交": "中标",
	# 合同
	"合同公告": "合同",
	# 终止（含废标/流标/失败）
	"终止公告": "终止",
	"废标": "终止",
	"流标": "终止",
	"招标失败": "终止",
}


def normalize_announcement_type(raw: Any) -> str:
	"""
	将 LLM/页面文本归一化为 13 选 1 的公告类别
	"""
	text = ("" if raw is None else str(raw)).strip()
	if not text:
		return "招标"
	if text in ANNOUNCEMENT_TYPES:
		return text

	for key in sorted(ANNOUNCEMENT_TYPE_MAPPING.keys(), key=len, reverse=True):
		if key in text:
			return ANNOUNCEMENT_TYPE_MAPPING[key]

	logger.warning(f"公告类别无法映射: {text!r}，兜底为 '招标'")
	return "招标"


# ===== 金额（万元）=====

def _to_wan_yuan(v: Any) -> Optional[float]:
	"""
	转换为万元，保留两位小数

	规则：
	- 数字/纯数字字符串：视为“万元”
	- 含“亿”：换算为万元（1 亿 = 10000 万元）
	- 含“万”：视为万元
	- 含“元”：换算为万元（1 元 = 0.0001 万元）
	"""
	if v is None:
		return None
	if isinstance(v, (int, float)):
		return round(float(v), 2)

	s = str(v).strip()
	if not s:
		return None
	s = s.replace(",", "").replace("，", "")
	s = s.replace("人民币", "").replace("￥", "").replace("¥", "")

	# 纯数字：视为万元
	if re.match(r"^\d+(\.\d+)?$", s):
		return round(float(s), 2)

	# 范围值不应进入 number 字段
	if "~" in s or "～" in s or "-" in s:
		return None

	multiplier = 1.0
	if "亿" in s:
		multiplier = 10000.0
		s = s.replace("亿", "")
	if "万" in s:
		multiplier = 1.0
		s = s.replace("万", "")
	if "元" in s:
		# 仅当未出现“万/亿”时才按元处理
		if multiplier == 1.0:
			multiplier = 0.0001
		s = s.replace("元", "")

	m = re.search(r"(\d+(?:\.\d+)?)", s)
	if not m:
		return None
	return round(float(m.group(1)) * multiplier, 2)


def normalize_estimated_amount(v: Any) -> str:
	"""
	归一化 estimatedAmount 为 \"下限~上限\"（万元，两位小数）
	"""
	if v is None:
		return ""
	s = str(v).strip()
	if not s or s.lower() in _EMPTY_STRINGS:
		return ""

	s = s.replace("～", "~")
	parts = [p.strip() for p in s.split("~") if p.strip()]
	if len(parts) != 2:
		return s

	lo = _to_wan_yuan(parts[0])
	hi = _to_wan_yuan(parts[1])
	if lo is None or hi is None:
		return s
	return f"{lo:.2f}~{hi:.2f}"


def normalize_date_ymd(v: Any) -> str:
	"""
	将常见日期字符串归一化为 YYYY-MM-DD；无法识别则原样返回（去空白）
	"""
	if v is None:
		return ""
	s = str(v).strip()
	if not s or s.lower() in _EMPTY_STRINGS:
		return ""

	# 常见格式：2026-2-16 / 2026/2/16 / 2026.2.16 / 2026年2月16日
	m = re.search(r"(?P<y>\d{4})\s*[年./-]\s*(?P<m>\d{1,2})\s*[月./-]\s*(?P<d>\d{1,2})", s)
	if not m:
		m = re.search(r"(?P<y>\d{4})\s*[./-]\s*(?P<m>\d{1,2})\s*[./-]\s*(?P<d>\d{1,2})", s)
	if not m:
		return s

	year = int(m.group("y"))
	month = int(m.group("m"))
	day = int(m.group("d"))
	if not (1 <= month <= 12 and 1 <= day <= 31):
		return s
	return f"{year:04d}-{month:02d}-{day:02d}"


def _join_list(v: Any) -> str:
	if v is None:
		return ""
	if isinstance(v, list):
		items = []
		for x in v:
			s = ("" if x is None else str(x)).strip()
			if s and s.lower() not in _EMPTY_STRINGS:
				items.append(s)
		return ",".join(items)
	return str(v).strip()


def _normalize_price_list_str(v: Any) -> str:
	"""
	将 \"100万,200万\" / [100,200] 归一化为 \"100.00,200.00\"（万元）
	"""
	raw = _join_list(v)
	if not raw:
		return ""
	parts = [p.strip() for p in re.split(_SEP, raw) if p.strip()]
	out: list[str] = []
	for p in parts:
		val = _to_wan_yuan(p)
		out.append(f"{val:.2f}" if val is not None else p)
	return ",".join(out)


def _normalize_int_list_str(v: Any) -> str:
	raw = _join_list(v)
	if not raw:
		return ""
	parts = [p.strip() for p in re.split(_SEP, raw) if p.strip()]
	out: list[str] = []
	for p in parts:
		m = re.search(r"\d+", p)
		if m:
			out.append(str(int(m.group())))
		else:
			out.append(p)
	return ",".join(out)


def _to_str_list(v: Any) -> list[str]:
	"""
	将输入归一化为字符串数组。

	容错：
	- "A,B" / "A，B" / "A\\nB" -> ["A","B"]
	- ["A","B"] -> ["A","B"]
	- '[\"A\",\"B\"]' -> ["A","B"]
	"""
	if v is None:
		return []

	if isinstance(v, list):
		out: list[str] = []
		for x in v:
			out.extend(_to_str_list(x))
		return out

	if isinstance(v, str):
		s = v.strip()
		if not s or s.lower() in _EMPTY_STRINGS:
			return []

		# 允许字符串形式的 JSON 数组/对象（尽量容错）
		if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
			try:
				parsed = json.loads(s)
				return _to_str_list(parsed)
			except Exception:
				pass

		parts = [p.strip() for p in re.split(_SEP, s) if p.strip()]
		return [p for p in parts if p.lower() not in _EMPTY_STRINGS]

	s = str(v).strip()
	if not s or s.lower() in _EMPTY_STRINGS:
		return []
	return [s]


def _normalize_price_list(v: Any) -> list[str]:
	"""
	将 \"100万,200万\" / [100,200] 归一化为 [\"100.00\",\"200.00\"]（万元）
	"""
	parts = _to_str_list(v)
	out: list[str] = []
	for p in parts:
		val = _to_wan_yuan(p)
		out.append(f"{val:.2f}" if val is not None else p)
	return out


def _normalize_int_list(v: Any) -> list[str]:
	parts = _to_str_list(v)
	out: list[str] = []
	for p in parts:
		m = re.search(r"\d+", p)
		if m:
			out.append(str(int(m.group())))
		else:
			out.append(p)
	return out


def _normalize_wan_yuan_number(v: Any) -> Optional[float]:
	"""
	容错地从标量/列表/逗号分隔字符串中提取一个金额（万元）。
	"""
	for part in _to_str_list(v):
		val = _to_wan_yuan(part)
		if val is not None:
			return val
	return _to_wan_yuan(v)


# ===== lotProducts =====

class LotProduct(BaseModel):
	"""标段采购产品"""

	model_config = ConfigDict(extra="ignore")

	lotNumber: str = Field(default="标段一", validation_alias=AliasChoices("lotNumber", "标段号", "lot_number"))
	lotName: str = Field(default="", validation_alias=AliasChoices("lotName", "标段名", "lot_name"))
	subjects: str = Field(default="", validation_alias=AliasChoices("subjects", "标的物"))
	productCategory: str = Field(default="", validation_alias=AliasChoices("productCategory", "二级产品"))
	models: str = Field(default="", validation_alias=AliasChoices("models", "标的物型号", "型号"))
	unitPrices: str = Field(default="", validation_alias=AliasChoices("unitPrices", "标的物单价", "单价"))
	quantities: str = Field(default="", validation_alias=AliasChoices("quantities", "标的物数量", "数量"))

	@field_validator("lotNumber", mode="before")
	@classmethod
	def _lot_number(cls, v: Any) -> str:
		# 约定：某个详情页一定属于某个标段；若页面未写明，则兜底为“标段一”
		text = _join_list(v)
		return text or "标段一"

	@field_validator("lotName", mode="before")
	@classmethod
	def _strip_text(cls, v: Any) -> str:
		return _join_list(v)

	@field_validator("unitPrices", mode="before")
	@classmethod
	def _unit_prices(cls, v: Any) -> str:
		parts = _normalize_price_list(v)
		return parts[0] if parts else ""

	@field_validator("quantities", mode="before")
	@classmethod
	def _quantities(cls, v: Any) -> str:
		parts = _normalize_int_list(v)
		return parts[0] if parts else ""

	@field_validator("subjects", "productCategory", "models", mode="before")
	@classmethod
	def _text_single(cls, v: Any) -> str:
		if isinstance(v, str):
			s = v.strip()
			return "" if (not s or s.lower() in _EMPTY_STRINGS) else s
		parts = _to_str_list(v)
		return parts[0] if parts else ""


class LotProducts(RootModel[list[LotProduct]]):
	@model_validator(mode="before")
	@classmethod
	def _normalize(cls, v: Any):
		def _as_list(raw: Any) -> list[dict]:
			if raw is None:
				return []
			if isinstance(raw, list):
				return [x for x in raw if isinstance(x, dict)]
			if isinstance(raw, dict):
				return [raw]
			if isinstance(raw, str):
				s = raw.strip()
				if s.lower() in _EMPTY_STRINGS:
					return []
				try:
					parsed = json.loads(s)
					return _as_list(parsed)
				except Exception:
					return []
			return []

		def _pick(parts: list[str], idx: int) -> str:
			if not parts:
				return ""
			if len(parts) == 1:
				return parts[0]
			return parts[idx] if idx < len(parts) else ""

		items = _as_list(v)
		out: list[dict] = []
		for item in items:
			lot_number = _join_list(item.get("lotNumber")) or "标段一"
			lot_name = _join_list(item.get("lotName"))

			subjects = _to_str_list(item.get("subjects"))
			if not subjects:
				desc = _join_list(item.get("description"))
				subjects = [desc] if desc else []
			product_categories = _to_str_list(item.get("productCategory"))
			models = _to_str_list(item.get("models"))
			unit_prices = _normalize_price_list(item.get("unitPrices"))
			quantities = _normalize_int_list(item.get("quantities"))

			row_count = max(
				len(subjects),
				len(product_categories),
				len(models),
				len(unit_prices),
				len(quantities),
			)
			if row_count <= 0:
				continue

			for idx in range(row_count):
				subject_value = _pick(subjects, idx)
				product_category_value = _pick(product_categories, idx)
				if product_category_value:
					product_category_value = normalize_concrete_product_name(product_category_value) or match_concrete_product_from_subject(
						subject_value
					)
				else:
					product_category_value = match_concrete_product_from_subject(subject_value)

				out.append(
					{
						"lotNumber": lot_number,
						"lotName": lot_name,
						"subjects": subject_value,
						"productCategory": product_category_value,
						"models": _pick(models, idx),
						"unitPrices": _pick(unit_prices, idx),
						"quantities": _pick(quantities, idx),
					}
				)

		return out


# ===== lotCandidates =====

class LotCandidate(BaseModel):
	"""标段：中标/中标候选人/非中标候选人信息（按行展开）"""

	model_config = ConfigDict(extra="ignore")

	lotNumber: str = Field(default="标段一", validation_alias=AliasChoices("lotNumber", "标段号", "lot_number"))
	lotName: str = Field(default="", validation_alias=AliasChoices("lotName", "标段名", "lot_name"))
	type: str = Field(default="", validation_alias=AliasChoices("type", "类型", "候选类型", "中标类型"))
	candidates: str = Field(default="", validation_alias=AliasChoices("candidates", "候选单位"))
	candidatePrices: str = Field(default="", validation_alias=AliasChoices("candidatePrices", "候选单位报价", "报价"))

	@field_validator("lotNumber", mode="before")
	@classmethod
	def _lot_number(cls, v: Any) -> str:
		text = _join_list(v)
		return text or "标段一"

	@field_validator("lotName", mode="before")
	@classmethod
	def _strip_text(cls, v: Any) -> str:
		return _join_list(v)

	@field_validator("type", mode="before")
	@classmethod
	def _candidate_type(cls, v: Any) -> str:
		s = _join_list(v)
		if not s:
			return ""
		s = s.strip()
		if s in {"中标", "中标候选人", "非中标候选人"}:
			return s
		# Heuristic normalization (no guessing beyond the label itself).
		if "否决" in s or "无效" in s or "未中标" in s or "落标" in s or "不通过" in s or "未通过" in s:
			return "非中标候选人"
		if "候选" in s:
			return "中标候选人"
		if "中标" in s or "成交" in s or "中选" in s:
			return "中标"
		return ""

	@field_validator("candidatePrices", mode="before")
	@classmethod
	def _candidate_prices(cls, v: Any) -> str:
		parts = _normalize_price_list(v)
		return parts[0] if parts else ""

	@field_validator("candidates", mode="before")
	@classmethod
	def _text_single(cls, v: Any) -> str:
		parts = _to_str_list(v)
		return parts[0] if parts else ""


class LotCandidates(RootModel[list[LotCandidate]]):
	@model_validator(mode="before")
	@classmethod
	def _normalize(cls, v: Any):
		def _as_list(raw: Any) -> list[dict]:
			if raw is None:
				return []
			if isinstance(raw, list):
				return [x for x in raw if isinstance(x, dict)]
			if isinstance(raw, dict):
				return [raw]
			if isinstance(raw, str):
				s = raw.strip()
				if s.lower() in _EMPTY_STRINGS:
					return []
				try:
					parsed = json.loads(s)
					return _as_list(parsed)
				except Exception:
					return []
			return []

		def _pick(parts: list[str], idx: int) -> str:
			if not parts:
				return ""
			if len(parts) == 1:
				return parts[0]
			return parts[idx] if idx < len(parts) else ""

		items = _as_list(v)
		out: list[dict] = []
		for item in items:
			lot_number = _join_list(item.get("lotNumber")) or "标段一"
			lot_name = _join_list(item.get("lotName"))
			declared_type = _join_list(item.get("type"))

			# Backward compatibility: old schema fields (winner/winningAmount) may still appear.
			winner = _join_list(item.get("winner"))
			winning_amount = _normalize_wan_yuan_number(item.get("winningAmount"))

			candidates = _to_str_list(item.get("candidates"))
			candidate_prices = _normalize_price_list(item.get("candidatePrices"))

			row_count = max(len(candidates), len(candidate_prices))
			keep_one = row_count > 0 or bool(winner) or (winning_amount is not None)
			if not keep_one:
				continue

			# Old pages sometimes only have winner without an explicit candidate list.
			# Convert that into one row (no guessing beyond extracted fields).
			if row_count <= 0 and winner:
				candidates = [winner]
				if winning_amount is not None:
					candidate_prices = [f"{winning_amount:.2f}"]
				else:
					candidate_prices = [""]
				row_count = 1
			if row_count <= 0:
				row_count = 1

			for idx in range(row_count):
				candidate_value = _pick(candidates, idx)
				type_value = declared_type
				if not type_value and winner:
					# Deterministic mapping from old fields: if this row matches the winner, mark as "中标",
					# otherwise it's part of the candidate list.
					type_value = "中标" if (candidate_value and candidate_value == winner) else "中标候选人"
				out.append(
					{
						"lotNumber": lot_number,
						"lotName": lot_name,
						"type": type_value,
						"candidates": candidate_value,
						"candidatePrices": _pick(candidate_prices, idx),
					}
				)
		return out
