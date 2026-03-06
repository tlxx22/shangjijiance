"""
字段 Schema 与归一化工具（V2）

- 公告类别（13 选 1）归一化
- 金额单位统一为“元”
- lotProducts / lotCandidates Pydantic 模型（容错输入 + 统一输出）
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, RootModel, AliasChoices, field_validator, model_validator

from .logger_config import get_logger

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
	"答疑文件": "答疑",
	"答疑通知": "答疑",
	"答疑澄清": "答疑",
	"澄清公告": "答疑",
	"澄清文件": "答疑",
	"澄清通知": "答疑",
	"澄清答疑": "答疑",
	"疑问回复": "答疑",
	"问题回复": "答疑",
	"问题答复": "答疑",
	"澄清": "答疑",
	"答疑": "答疑",
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
	normalized = try_normalize_announcement_type(raw)
	if normalized:
		return normalized
	text = ("" if raw is None else str(raw)).strip()
	if text:
		logger.warning(f"公告类别无法映射: {text!r}，将返回空字符串等待上层修复/跳过")
	return ""


def try_normalize_announcement_type(raw: Any) -> str | None:
	"""
	严格归一化公告类别（13 选 1）。

	- 能映射：返回枚举值
	- 映射不了：返回 None（不再兜底为“招标”，避免静默污染数据）
	"""
	text = ("" if raw is None else str(raw)).strip()
	if not text:
		return None
	if text in ANNOUNCEMENT_TYPES:
		return text

	for key in (
		"答疑澄清",
		"澄清答疑",
		"澄清公告",
		"澄清文件",
		"澄清通知",
		"答疑公告",
		"答疑文件",
		"答疑通知",
		"疑问回复",
		"问题回复",
		"问题答复",
		"答疑",
		"澄清",
	):
		if key in text:
			return "答疑"

	for key in sorted(ANNOUNCEMENT_TYPE_MAPPING.keys(), key=len, reverse=True):
		if key in text:
			return ANNOUNCEMENT_TYPE_MAPPING[key]

	return None


# ===== 金额（元）=====

def _parse_money_to_yuan_decimal(v: Any) -> Optional[tuple[Decimal, int]]:
	"""
	将金额解析并换算为“元”，同时保留原始数值的小数位数。

	规则：
	- 数字/纯数字字符串：视为“元”
	- 含“亿”：换算为元（1 亿 = 100000000 元）
	- 含“万”：换算为元（1 万 = 10000 元）
	- 含“元”：视为元
	"""
	if v is None:
		return None
	if isinstance(v, (int, float, Decimal)):
		sv = str(v)
		dp = 0
		if "." in sv:
			dp = len(sv.split(".", 1)[1])
		try:
			dec = Decimal(sv)
		except InvalidOperation:
			return None
		if dp > 0:
			quant = Decimal(1).scaleb(-dp)
			dec = dec.quantize(quant, rounding=ROUND_HALF_UP)
		else:
			dec = dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
		return dec, dp

	s = str(v).strip()
	if not s:
		return None

	# 范围/多值保护：number 字段只允许单一金额。
	# e.g. "1~2万" / "100-200" / "97.00,98.50" 都应视为无效并返回 None。
	if "~" in s or "～" in s or "-" in s:
		return None

	# 先在“未去逗号”的文本上判断是否存在多个金额数字，避免把 "97.00,98.50" 错误合并成一个数。
	# 注意：千分位写法如 "97,000" 只应识别为一个数字。
	s_num_check = s.replace("，", ",")
	num_tokens = re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", s_num_check)
	if len(num_tokens) > 1:
		return None

	# 统一去掉货币符号/千分位逗号（此时已经确认最多只有一个数字 token）。
	s = s.replace(",", "").replace("，", "")
	s = s.replace("人民币", "").replace("￥", "").replace("¥", "")

	multiplier = Decimal(1)
	if "亿" in s:
		multiplier = Decimal("100000000")
		s = s.replace("亿", "")
	elif "万" in s:
		multiplier = Decimal("10000")
		s = s.replace("万", "")
	s = s.replace("元", "")

	m = re.search(r"(\d+(?:\.\d+)?)", s)
	if not m:
		return None
	num_str = m.group(1)
	dp = 0
	if "." in num_str:
		dp = len(num_str.split(".", 1)[1])
	try:
		num_dec = Decimal(num_str)
	except InvalidOperation:
		return None

	val = num_dec * multiplier
	if dp > 0:
		quant = Decimal(1).scaleb(-dp)
		val = val.quantize(quant, rounding=ROUND_HALF_UP)
	else:
		val = val.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
	return val, dp


def _to_yuan(v: Any) -> Optional[float]:
	parsed = _parse_money_to_yuan_decimal(v)
	if not parsed:
		return None
	val, _dp = parsed
	try:
		return float(val)
	except Exception:
		return None


def _to_yuan_str(v: Any) -> Optional[str]:
	parsed = _parse_money_to_yuan_decimal(v)
	if not parsed:
		return None
	val, _dp = parsed
	return format(val, "f")


def normalize_estimated_amount(v: Any) -> str:
	"""
	归一化 estimatedAmount 为 \"下限~上限\"（元；小数位数尽量与页面一致）
	"""
	if v is None:
		return ""
	s = str(v).strip()
	if not s or s.lower() in _EMPTY_STRINGS:
		return ""

	def _detect_unit(text: str) -> str:
		# precedence matters: "亿元" contains both "亿" and "元"
		if "亿" in text:
			return "亿"
		if "万" in text:
			return "万"
		if "元" in text:
			return "元"
		return ""

	def _share_unit(lo_raw: str, hi_raw: str) -> tuple[str, str]:
		lo_u = _detect_unit(lo_raw)
		hi_u = _detect_unit(hi_raw)
		if not lo_u and hi_u:
			return f"{lo_raw}{hi_u}", hi_raw
		if lo_u and not hi_u:
			return lo_raw, f"{hi_raw}{lo_u}"
		return lo_raw, hi_raw

	def _split_range(text: str) -> tuple[str, str] | None:
		# Normalize common range separators.
		t = text.replace("～", "~").replace("－", "-").replace("—", "-").replace("–", "-")
		if "~" not in t:
			t = t.replace("至", "~").replace("到", "~")

		if "~" in t:
			parts = [p.strip() for p in t.split("~") if p.strip()]
			if len(parts) == 2:
				return parts[0], parts[1]
			return None

		# Dash range: only treat as range when there's exactly one dash and not a date-like string.
		if t.count("-") == 1 and not re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", t):
			lo_raw, hi_raw = [p.strip() for p in t.split("-", 1)]
			if any(ch.isdigit() for ch in lo_raw) and any(ch.isdigit() for ch in hi_raw):
				return lo_raw, hi_raw

		return None

	range_parts = _split_range(s)
	if range_parts:
		lo_raw, hi_raw = _share_unit(range_parts[0], range_parts[1])
		lo = _to_yuan_str(lo_raw)
		hi = _to_yuan_str(hi_raw)
		if lo is not None and hi is not None:
			return f"{lo}~{hi}"

	# Always return a range string when we can parse a single amount.
	# If only one amount is known, normalize to "x~x" (still a valid range).
	single = _to_yuan_str(s)
	return f"{single}~{single}" if single is not None else s


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
	将 \"100万,200万\" / [100,200] 归一化为 \"1000000,2000000\"（元；小数位数与页面一致）
	"""
	raw = _join_list(v)
	if not raw:
		return ""
	parts = [p.strip() for p in re.split(_SEP, raw) if p.strip()]
	out: list[str] = []
	for p in parts:
		val = _to_yuan_str(p)
		out.append(val if val is not None else p)
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
	将 \"100万,200万\" / [100,200] 归一化为 [\"1000000\",\"2000000\"]（元；小数位数与页面一致）
	"""
	parts = _to_str_list(v)
	out: list[str] = []
	for p in parts:
		val = _to_yuan_str(p)
		out.append(val if val is not None else p)
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


def _normalize_yuan_number(v: Any) -> Optional[float]:
	"""
	容错地从标量/列表/逗号分隔字符串中提取一个金额（元）。
	"""
	for part in _to_str_list(v):
		val = _to_yuan(part)
		if val is not None:
			return val
	return _to_yuan(v)


_LOT_NUMBER_TOKEN = r"[零〇一二三四五六七八九十百千万两\d]+"
_LOT_BID_NUMBER_PATTERNS = (
	re.compile(rf"(?:标段|标包|标)\s*第?\s*(?P<num>{_LOT_NUMBER_TOKEN})"),
	re.compile(rf"第?\s*(?P<num>{_LOT_NUMBER_TOKEN})\s*(?:标段|标包|标)"),
)
_LOT_PACKAGE_NUMBER_PATTERNS = (
	re.compile(rf"(?:包件|包)\s*第?\s*(?P<num>{_LOT_NUMBER_TOKEN})"),
	re.compile(rf"第?\s*(?P<num>{_LOT_NUMBER_TOKEN})\s*(?:包件|包)"),
)
_LOT_NAME_MARKER_RE = re.compile(
	rf"(?:(?:标段|标包|标|包件|包)\s*第?\s*{_LOT_NUMBER_TOKEN}|第?\s*{_LOT_NUMBER_TOKEN}\s*(?:标段|标包|标|包件|包))\s*[：:、.．）)】-]*\s*"
)
_CHINESE_DIGIT_MAP = {
	"零": 0,
	"〇": 0,
	"一": 1,
	"二": 2,
	"两": 2,
	"三": 3,
	"四": 4,
	"五": 5,
	"六": 6,
	"七": 7,
	"八": 8,
	"九": 9,
}
_CHINESE_UNIT_MAP = {
	"十": 10,
	"百": 100,
	"千": 1000,
	"万": 10000,
}


def _chinese_numeral_to_int(text: str) -> int | None:
	token = (text or "").strip()
	if not token:
		return None
	if token.isdigit():
		return int(token)
	if any(ch not in _CHINESE_DIGIT_MAP and ch not in _CHINESE_UNIT_MAP for ch in token):
		return None
	if not any(ch in _CHINESE_UNIT_MAP for ch in token):
		digits = [str(_CHINESE_DIGIT_MAP[ch]) for ch in token]
		return int("".join(digits)) if digits else None

	total = 0
	section = 0
	number = 0
	for ch in token:
		if ch in _CHINESE_DIGIT_MAP:
			number = _CHINESE_DIGIT_MAP[ch]
			continue
		unit = _CHINESE_UNIT_MAP.get(ch)
		if unit is None:
			return None
		if unit == 10000:
			section = (section + (number or 0)) * unit
			total += section
			section = 0
			number = 0
			continue
		if number == 0:
			number = 1
		section += number * unit
		number = 0
	return total + section + number


def _section_to_chinese(section: int) -> str:
	digits = "零一二三四五六七八九"
	units = ["", "十", "百", "千"]
	out = ""
	unit_pos = 0
	while section > 0:
		digit = section % 10
		if digit == 0:
			if out and not out.startswith("零"):
				out = "零" + out
		else:
			out = digits[digit] + units[unit_pos] + out
		unit_pos += 1
		section //= 10
	return out.rstrip("零")


def _int_to_chinese(num: int) -> str:
	if num <= 0:
		return ""
	parts: list[str] = []
	big_units = ["", "万", "亿"]
	unit_pos = 0
	need_zero = False
	while num > 0:
		section = num % 10000
		if section:
			part = _section_to_chinese(section)
			if need_zero and section < 1000:
				part = "零" + part
			parts.insert(0, part + (big_units[unit_pos] if unit_pos < len(big_units) else ""))
			need_zero = section < 1000
		elif parts:
			need_zero = True
		num //= 10000
		unit_pos += 1
	text = "".join(parts).strip("零")
	if text.startswith("一十"):
		text = text[1:]
	return text


def _normalize_lot_number_token(text: str) -> str | None:
	num = _chinese_numeral_to_int(text)
	if num is None or num <= 0:
		return None
	chinese = _int_to_chinese(num)
	if not chinese:
		return None
	return f"标段{chinese}"


def _infer_lot_number_from_text(text: Any) -> str | None:
	raw = _join_list(text)
	if not raw:
		return None
	for patterns in (_LOT_BID_NUMBER_PATTERNS, _LOT_PACKAGE_NUMBER_PATTERNS):
		for pattern in patterns:
			match = pattern.search(raw)
			if not match:
				continue
			lot_number = _normalize_lot_number_token(match.group("num"))
			if lot_number:
				return lot_number
	return _normalize_lot_number_token(raw)


def _extract_subject_from_lot_name(text: Any) -> str:
	raw = _join_list(text)
	if not raw:
		return ""
	matches = list(_LOT_NAME_MARKER_RE.finditer(raw))
	if matches:
		subject = raw[matches[-1].end():]
	else:
		subject = re.split(r"[：:]", raw)[-1]
	subject = re.split(r"[\r\n]+", subject)[0]
	subject = re.sub(r"^[\s：:、,，;；._-]+|[\s：:、,，;；._-]+$", "", subject)
	return subject.strip()


def _normalize_lot_dedupe_text(text: Any) -> str:
	return re.sub(r"[\s：:、,，;；._-]+", "", _join_list(text))

# ===== lotProducts =====

class LotProduct(BaseModel):
	"""标段采购产品"""

	model_config = ConfigDict(extra="ignore")

	lotNumber: str = Field(default="标段一", validation_alias=AliasChoices("lotNumber", "标段号", "lot_number"))
	lotName: str = Field(default="", validation_alias=AliasChoices("lotName", "标段名", "lot_name"))
	subjects: str = Field(default="", validation_alias=AliasChoices("subjects", "标的物"))
	productCategory: str = Field(default="", validation_alias=AliasChoices("productCategory", "二级产品"))
	models: str = Field(default="", validation_alias=AliasChoices("models", "标的物型号", "型号"))
	unitPrices: float | None = Field(default=None, validation_alias=AliasChoices("unitPrices", "标的物单价", "单价"))
	quantities: str = Field(default="", validation_alias=AliasChoices("quantities", "标的物数量", "数量"))
	quantityUnit: str = Field(default="", validation_alias=AliasChoices("quantityUnit", "quantity_unit", "数量单位", "单位"))

	@model_validator(mode="before")
	@classmethod
	def _infer_lot_fields(cls, v: Any):
		if not isinstance(v, dict):
			return v
		nv = dict(v)
		lot_number_raw = nv.get("lotNumber") or nv.get("lot_number") or nv.get("标段号")
		lot_name_raw = nv.get("lotName") or nv.get("lot_name") or nv.get("标段名")
		if not _join_list(lot_number_raw):
			inferred_lot_number = _infer_lot_number_from_text(lot_name_raw)
			if inferred_lot_number:
				nv["lotNumber"] = inferred_lot_number
		subjects_raw = nv.get("subjects") or nv.get("标的物") or nv.get("description")
		if not _join_list(subjects_raw):
			inferred_subject = _extract_subject_from_lot_name(lot_name_raw)
			if inferred_subject:
				nv["subjects"] = inferred_subject
		return nv

	@model_validator(mode="before")
	@classmethod
	def _infer_quantity_unit(cls, v: Any):
		"""
		Backward-compatible parsing:
		- If quantityUnit is missing but quantities looks like "1台"/"2 套", extract the trailing unit.
		"""
		if not isinstance(v, dict):
			return v

		unit_raw = v.get("quantityUnit") or v.get("quantity_unit") or v.get("数量单位") or v.get("单位")
		unit_text = ("" if unit_raw is None else str(unit_raw)).strip()
		if unit_text and unit_text.lower() not in _EMPTY_STRINGS:
			return v

		q_raw = v.get("quantities") or v.get("数量") or v.get("标的物数量")
		if isinstance(q_raw, str):
			s = q_raw.strip()
			# e.g. "1台", "2 套", "3m"
			m = re.search(r"\d+(?:\.\d+)?\s*([^\d\s]+)$", s)
			if m:
				unit = m.group(1).strip()
				if unit and unit.lower() not in _EMPTY_STRINGS:
					nv = dict(v)
					nv["quantityUnit"] = unit
					return nv

		return v

	@field_validator("lotNumber", mode="before")
	@classmethod
	def _lot_number(cls, v: Any) -> str:
		# 约定：某个详情页一定属于某个标段；若页面未写明，则兜底为“标段一”
		text = _infer_lot_number_from_text(v)
		return text or "标段一"

	@field_validator("lotName", mode="before")
	@classmethod
	def _strip_text(cls, v: Any) -> str:
		return _join_list(v)

	@field_validator("unitPrices", mode="before")
	@classmethod
	def _unit_prices(cls, v: Any) -> float | None:
		# Money fields are floats in yuan; invalid inputs become None.
		if v is None:
			return None
		if isinstance(v, list):
			for x in v:
				val = _to_yuan(x)
				if val is not None:
					return val
			return None
		return _to_yuan(v)

	@field_validator("quantities", mode="before")
	@classmethod
	def _quantities(cls, v: Any) -> str:
		parts = _normalize_int_list(v)
		return parts[0] if parts else ""

	@field_validator("subjects", "productCategory", "models", "quantityUnit", mode="before")
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

		def _pick_unit_price(raw: Any) -> float | None:
			"""
			Parse ONE money value (yuan) from common LLM outputs.
			- list: pick the first parseable value
			- stringified JSON array: parse and pick first parseable value
			- otherwise: parse as scalar
			"""
			if raw is None:
				return None
			if isinstance(raw, list):
				for x in raw:
					val = _to_yuan(x)
					if val is not None:
						return val
				return None
			if isinstance(raw, (int, float, Decimal)):
				return _to_yuan(raw)
			if isinstance(raw, dict):
				return None
			if isinstance(raw, str):
				s = raw.strip()
				if not s or s.lower() in _EMPTY_STRINGS:
					return None
				if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
					try:
						parsed = json.loads(s)
						return _pick_unit_price(parsed)
					except Exception:
						pass
				return _to_yuan(s)
			return _to_yuan(raw)

		items = _as_list(v)
		out: list[dict] = []
		for item in items:
			lot_number_raw = _join_list(item.get("lotNumber"))
			lot_name = _join_list(item.get("lotName"))
			lot_number = _infer_lot_number_from_text(lot_number_raw) or _infer_lot_number_from_text(lot_name) or "标段一"

			subjects = _join_list(item.get("subjects"))
			if not subjects:
				subjects = _join_list(item.get("description"))
			if not subjects:
				subjects = _extract_subject_from_lot_name(lot_name)
			product_category = _join_list(item.get("productCategory"))
			models = _join_list(item.get("models"))
			unit_price = _pick_unit_price(item.get("unitPrices"))
			quantities = _join_list(item.get("quantities"))
			quantity_unit = _join_list(
				item.get("quantityUnit") or item.get("quantity_unit") or item.get("数量单位") or item.get("单位")
			)

			keep = any(
				[
					bool(lot_number_raw),
					bool(lot_name),
					bool(subjects),
					bool(product_category),
					bool(models),
					unit_price is not None,
					bool(quantities),
					bool(quantity_unit),
				]
			)
			if not keep:
				continue

			out.append(
				{
					"lotNumber": lot_number,
					"lotName": lot_name,
					"subjects": subjects,
					"productCategory": product_category,
					"models": models,
					"unitPrices": unit_price,
					"quantities": quantities,
					"quantityUnit": quantity_unit,
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
	candidatePrices: float | None = Field(default=None, validation_alias=AliasChoices("candidatePrices", "候选单位报价", "报价"))

	@model_validator(mode="before")
	@classmethod
	def _infer_lot_fields(cls, v: Any):
		if not isinstance(v, dict):
			return v
		nv = dict(v)
		lot_number_raw = nv.get("lotNumber") or nv.get("lot_number") or nv.get("标段号")
		lot_name_raw = nv.get("lotName") or nv.get("lot_name") or nv.get("标段名")
		if not _join_list(lot_number_raw):
			inferred_lot_number = _infer_lot_number_from_text(lot_name_raw)
			if inferred_lot_number:
				nv["lotNumber"] = inferred_lot_number
		return nv

	@field_validator("lotNumber", mode="before")
	@classmethod
	def _lot_number(cls, v: Any) -> str:
		text = _infer_lot_number_from_text(v)
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
	def _candidate_prices(cls, v: Any) -> float | None:
		# Money fields are floats in yuan; invalid inputs become None.
		if v is None:
			return None
		if isinstance(v, list):
			for x in v:
				val = _to_yuan(x)
				if val is not None:
					return val
			return None
		return _to_yuan(v)

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

		def _pick(parts: list[Any], idx: int, default: Any = "") -> Any:
			if not parts:
				return default
			if len(parts) == 1:
				return parts[0]
			return parts[idx] if idx < len(parts) else default

		def _money_list(raw: Any) -> list[float | None]:
			"""
			Parse a list of money values (yuan) from common LLM outputs.
			- Returns list[float|None]; invalid values become None.
			- Supports thousand separators and 万/亿 units.
			"""
			if raw is None:
				return []
			if isinstance(raw, list):
				return [_to_yuan(x) for x in raw]
			if isinstance(raw, (int, float, Decimal)):
				val = _to_yuan(raw)
				return [val] if val is not None else []
			if isinstance(raw, dict):
				return []
			if isinstance(raw, str):
				s = raw.strip()
				if not s or s.lower() in _EMPTY_STRINGS:
					return []
				if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
					try:
						parsed = json.loads(s)
						return _money_list(parsed)
					except Exception:
						pass

				single = _to_yuan(s)
				if single is not None:
					return [single]

				s2 = s.replace("，", ",")
				out: list[float | None] = []
				for m in re.finditer(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(亿|万))?", s2):
					token = m.group(1) + (m.group(2) or "")
					out.append(_to_yuan(token))
				return out

			val = _to_yuan(raw)
			return [val] if val is not None else []

		items = _as_list(v)
		out: list[dict] = []
		for item in items:
			lot_name = _join_list(item.get("lotName"))
			lot_number = _infer_lot_number_from_text(item.get("lotNumber")) or _infer_lot_number_from_text(lot_name) or "标段一"
			declared_type = _join_list(item.get("type"))

			# Backward compatibility: old schema fields (winner/winningAmount) may still appear.
			winner = _join_list(item.get("winner"))
			winning_amount = _to_yuan(item.get("winningAmount"))

			candidates = _to_str_list(item.get("candidates"))
			candidate_prices = _money_list(item.get("candidatePrices"))

			row_count = max(len(candidates), len(candidate_prices))
			keep_one = row_count > 0 or bool(winner) or (winning_amount is not None)
			if not keep_one:
				continue

			# Old pages sometimes only have winner without an explicit candidate list.
			# Convert that into one row (no guessing beyond extracted fields).
			if row_count <= 0 and winner:
				candidates = [winner]
				candidate_prices = [winning_amount] if winning_amount is not None else [None]
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
						"candidatePrices": _pick(candidate_prices, idx, None),
					}
				)
		return out

def supplement_lot_products_from_candidates(lot_products: Any, lot_candidates: Any) -> list[dict[str, Any]]:
	"""
	When result/candidate notices only extract lotCandidates rows, deterministically backfill
	lotProducts from explicit "标/包 + 设备名/物资名" lotName text.
	"""
	products = [item.model_dump() for item in LotProducts.model_validate(lot_products).root]
	candidates = [item.model_dump() for item in LotCandidates.model_validate(lot_candidates).root]

	existing_subject_keys: set[tuple[str, str]] = set()
	existing_name_keys: set[tuple[str, str]] = set()
	for product in products:
		lot_number = _infer_lot_number_from_text(product.get("lotNumber")) or _infer_lot_number_from_text(product.get("lotName")) or "标段一"
		product["lotNumber"] = lot_number
		if not _join_list(product.get("subjects")):
			product["subjects"] = _extract_subject_from_lot_name(product.get("lotName"))
		subject_key = _normalize_lot_dedupe_text(product.get("subjects"))
		name_key = _normalize_lot_dedupe_text(product.get("lotName"))
		if subject_key:
			existing_subject_keys.add((lot_number, subject_key))
		if name_key:
			existing_name_keys.add((lot_number, name_key))

	for candidate in candidates:
		lot_name = _join_list(candidate.get("lotName"))
		if not lot_name:
			continue
		lot_number = _infer_lot_number_from_text(candidate.get("lotNumber")) or _infer_lot_number_from_text(lot_name) or "标段一"
		subjects = _extract_subject_from_lot_name(lot_name)
		if not subjects:
			continue
		subject_key = _normalize_lot_dedupe_text(subjects)
		name_key = _normalize_lot_dedupe_text(lot_name)
		if (subject_key and (lot_number, subject_key) in existing_subject_keys) or (name_key and (lot_number, name_key) in existing_name_keys):
			continue
		products.append(
			{
				"lotNumber": lot_number,
				"lotName": lot_name,
				"subjects": subjects,
				"productCategory": "",
				"models": "",
				"unitPrices": None,
				"quantities": "",
				"quantityUnit": "",
			}
		)
		if subject_key:
			existing_subject_keys.add((lot_number, subject_key))
		if name_key:
			existing_name_keys.add((lot_number, name_key))

	return products
