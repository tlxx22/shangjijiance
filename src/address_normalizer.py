import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from .extract_client import chat_completion
from .logger_config import get_logger

logger = get_logger()


_ALLOWED_CHARS_RE = re.compile(r"^[0-9A-Za-z\u4e00-\u9fff·（）()\-—\s]+$")

# 常见简称/单字缩写（要求：必须“完全命中”才判失败；例如“浙江省”不算失败）
_CN_ABBREV_TOKENS = {
	"京",
	"津",
	"沪",
	"渝",
	"冀",
	"豫",
	"云",
	"辽",
	"黑",
	"湘",
	"皖",
	"鲁",
	"新",
	"苏",
	"浙",
	"赣",
	"鄂",
	"桂",
	"甘",
	"晋",
	"蒙",
	"陕",
	"吉",
	"闽",
	"贵",
	"粤",
	"青",
	"藏",
	"川",
	"蜀",
	"宁",
	"琼",
	"港",
	"澳",
	"台",
	# 2~3字“非全称”常见写法
	"内蒙",
	"新疆",
	"广西",
	"宁夏",
}

_MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
_SAR = {"香港特别行政区", "澳门特别行政区"}
_AUTONOMOUS_REGIONS = {
	"内蒙古自治区",
	"广西壮族自治区",
	"宁夏回族自治区",
	"新疆维吾尔自治区",
	"西藏自治区",
}

_PROVINCE_SUFFIXES = ("省", "市", "自治区", "特别行政区")
_CITY_SUFFIXES = ("市", "州", "盟", "地区")
_DISTRICT_SUFFIXES = ("区", "县", "市", "旗")


@dataclass(frozen=True)
class AddressGroup:
	country: str
	province: str
	city: str
	district: str


def _is_illegal_text(s: str) -> bool:
	if not s:
		return False
	if not _ALLOWED_CHARS_RE.match(s):
		return True
	# Reject control chars.
	if any(ord(ch) < 32 for ch in s):
		return True
	return False


def _is_abbrev_token(s: str) -> bool:
	return s in _CN_ABBREV_TOKENS


def _validate_group(group: AddressGroup) -> tuple[bool, str]:
	"""
	轻量校验：
	- 非法字符：失败
	- 简称：必须“完全命中”才失败
	- 全称后缀：省/市/区县 等必须带后缀（中国场景）
	- 台湾：省字段必须为“中国台湾”，且国家为“中国”
	- 互相矛盾：直辖市 province 与 city 必须一致（非空时）
	"""
	country = (group.country or "").strip()
	province = (group.province or "").strip()
	city = (group.city or "").strip()
	district = (group.district or "").strip()

	for name, val in (("country", country), ("province", province), ("city", city), ("district", district)):
		if _is_illegal_text(val):
			return False, f"{name}_illegal_chars"
		if _is_abbrev_token(val):
			return False, f"{name}_abbrev"

	# 非中国场景：只做非法字符/简称校验（不强制后缀规则）
	if country and country != "中国":
		return True, "ok_non_cn"

	# 台湾规则
	if province in {"台湾", "台湾省"}:
		return False, "taiwan_must_be_cn_taiwan"
	if "台湾" in province and province != "中国台湾":
		return False, "taiwan_must_be_cn_taiwan"
	if province == "中国台湾":
		if country not in {"", "中国"}:
			return False, "taiwan_country_must_be_cn"

	# 省字段全称
	if province:
		if province in {"北京", "天津", "上海", "重庆"}:
			return False, "province_missing_suffix_municipality"
		if province not in _AUTONOMOUS_REGIONS and province not in _SAR and province not in _MUNICIPALITIES and province != "中国台湾":
			if not province.endswith(_PROVINCE_SUFFIXES):
				return False, "province_missing_suffix"

	# 市字段全称
	if city:
		if city in {"北京", "天津", "上海", "重庆"}:
			return False, "city_missing_suffix_municipality"
		if not city.endswith(_CITY_SUFFIXES):
			return False, "city_missing_suffix"

	# 区县字段全称
	if district:
		if not district.endswith(_DISTRICT_SUFFIXES):
			return False, "district_missing_suffix"

	# 互相矛盾：直辖市
	if province in _MUNICIPALITIES and city and city != province:
		return False, "municipality_city_mismatch"

	return True, "ok"


def _needs_llm_normalize(group: AddressGroup) -> bool:
	ok, _ = _validate_group(group)
	if ok:
		return False
	# 空值且无法判断时，不必 LLM；这里只在已有值但不合规时触发。
	return any((group.country or "").strip(), (group.province or "").strip(), (group.city or "").strip(), (group.district or "").strip())


def _strip_code_fences(text: str) -> str:
	s = (text or "").strip()
	if s.startswith("```"):
		s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
		s = re.sub(r"\s*```$", "", s)
	return s.strip()


async def normalize_address_group_with_deepseek(
	group: AddressGroup,
	max_retries: int = 3,
) -> AddressGroup:
	"""
	仅对 country/province/city/district 做二次标准化（不包含 AddressDetail）。
	- 轻量校验失败则重试，上限 max_retries
	- 达到上限仍失败：返回原值
	"""
	orig = AddressGroup(
		country=(group.country or "").strip(),
		province=(group.province or "").strip(),
		city=(group.city or "").strip(),
		district=(group.district or "").strip(),
	)

	if not _needs_llm_normalize(orig):
		return orig

	keys = ["country", "province", "city", "district"]
	system_prompt = """
You are an address normalization engine.
Normalize Chinese administrative division fields to FULL official names.

Rules:
- Output ONLY a single JSON object with keys: country, province, city, district.
- If an input field is empty, keep it empty.
- Do NOT use abbreviations (e.g., 京/沪/浙/皖/赣, etc.).
- Province must be full form:
  - Provinces end with “省”
  - Municipalities must be “北京市/天津市/上海市/重庆市”
  - Autonomous regions must be full names like “内蒙古自治区/广西壮族自治区/宁夏回族自治区/新疆维吾尔自治区/西藏自治区”
  - SAR must be “香港特别行政区/澳门特别行政区”
  - Taiwan MUST be “中国台湾” (province field), and country must be “中国”
- City must be full form and end with: 市/州/盟/地区 (when not empty).
- District must be full form and end with: 区/县/市/旗 (when not empty).
- If you cannot confidently normalize a non-empty field, keep the original value (do NOT guess).
""".strip()

	user_prompt = json.dumps(
		{
			"country": orig.country,
			"province": orig.province,
			"city": orig.city,
			"district": orig.district,
		},
		ensure_ascii=False,
	)

	last_reason = ""
	for attempt in range(1, max_retries + 1):
		out = await asyncio.to_thread(
			chat_completion,
			[
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
		)
		out = _strip_code_fences(out)

		try:
			parsed: Any = json.loads(out)
		except Exception:
			last_reason = "json_parse_failed"
			continue

		if not isinstance(parsed, dict):
			last_reason = "not_object"
			continue

		candidate = AddressGroup(
			country=str(parsed.get("country", "") or "").strip(),
			province=str(parsed.get("province", "") or "").strip(),
			city=str(parsed.get("city", "") or "").strip(),
			district=str(parsed.get("district", "") or "").strip(),
		)

		ok, reason = _validate_group(candidate)
		if ok:
			return candidate

		last_reason = reason

	logger.info(f"[address_normalizer] normalize failed after {max_retries} retries: {last_reason}")
	return orig


async def normalize_item_admin_divisions(item: dict[str, Any], max_retries: int = 3) -> dict[str, Any]:
	"""
	对 item 中 buyer/project/delivery 的 Country/Province/City/District 做二次标准化。
	不读写 AddressDetail；只覆盖这 12 个字段。
	"""
	out = dict(item)
	for prefix in ("buyer", "project", "delivery"):
		country_key = f"{prefix}Country"
		province_key = f"{prefix}Province"
		city_key = f"{prefix}City"
		district_key = f"{prefix}District"

		group = AddressGroup(
			country=str(out.get(country_key, "") or "").strip(),
			province=str(out.get(province_key, "") or "").strip(),
			city=str(out.get(city_key, "") or "").strip(),
			district=str(out.get(district_key, "") or "").strip(),
		)

		normalized = await normalize_address_group_with_deepseek(group, max_retries=max_retries)
		out[country_key] = normalized.country
		out[province_key] = normalized.province
		out[city_key] = normalized.city
		out[district_key] = normalized.district

	return out

