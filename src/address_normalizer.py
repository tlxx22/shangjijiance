import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from .deepseek_langchain import invoke_structured
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


class NormalizedAddress(BaseModel):
	model_config = ConfigDict(extra="ignore")

	country: str = ""
	province: str = ""
	city: str = ""
	district: str = ""


class AdminDivisions(BaseModel):
	model_config = ConfigDict(extra="ignore")

	buyerCountry: str = ""
	buyerProvince: str = ""
	buyerCity: str = ""
	buyerDistrict: str = ""
	projectCountry: str = ""
	projectProvince: str = ""
	projectCity: str = ""
	projectDistrict: str = ""
	deliveryCountry: str = ""
	deliveryProvince: str = ""
	deliveryCity: str = ""
	deliveryDistrict: str = ""


def _is_illegal_text(s: str) -> bool:
	if not s:
		return False
	# Only reject control chars; allow any language (including non-ASCII like ñ) and punctuation.
	# NOTE: upstream inputs are not controllable, so we intentionally do NOT enforce a strict charset whitelist.
	if any(ord(ch) < 32 for ch in s):
		return True
	return False


def _is_abbrev_token(s: str) -> bool:
	return s in _CN_ABBREV_TOKENS


def _fold_place_text(text: str) -> str:
	"""
	Normalize place strings for robust matching:
	- lower-case
	- strip diacritics (e.g. Biñan -> Binan)
	"""
	s = (text or "").strip()
	if not s:
		return ""
	s = unicodedata.normalize("NFKD", s)
	s = "".join(ch for ch in s if not unicodedata.combining(ch))
	return s.lower()


_PH_HINT_RE = re.compile(r"\b(brgy|barangay)\b")


def _infer_country_from_places(*, detail: str, province: str, city: str, district: str) -> str:
	"""
	Infer country when it's missing but address contains strong location hints.

	This is a best-effort heuristic (inputs are not controllable).
	Return empty string when unsure.
	"""
	combined = " ".join([detail or "", province or "", city or "", district or ""]).strip()
	folded = _fold_place_text(combined)
	if not folded:
		return ""

	# Philippines (high-confidence signals)
	if "philippines" in folded:
		return "菲律宾"
	if _PH_HINT_RE.search(folded):
		return "菲律宾"
	if ("laguna" in folded) and ("binan" in folded):
		return "菲律宾"

	return ""


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
	return bool(
		(group.country or "").strip()
		or (group.province or "").strip()
		or (group.city or "").strip()
		or (group.district or "").strip()
	)
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
		try:
			result = await asyncio.to_thread(
				invoke_structured,
				[
					{"role": "system", "content": system_prompt},
					{"role": "user", "content": user_prompt},
				],
				NormalizedAddress,
			)
		except Exception:
			last_reason = "llm_call_failed"
			continue

		parsed = result.model_dump()

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


def _field_ok_country(country: str) -> bool:
	s = (country or "").strip()
	if not s:
		return True
	if _is_illegal_text(s) or _is_abbrev_token(s):
		return False
	# allow "中国" or foreign country names
	return True


def _field_ok_province(country: str, province: str) -> bool:
	c = (country or "").strip()
	p = (province or "").strip()
	if not p:
		return True
	if _is_illegal_text(p) or _is_abbrev_token(p):
		return False

	# Taiwan rule
	if "台湾" in p and p != "中国台湾":
		return False
	if p == "中国台湾" and c not in {"", "中国"}:
		return False

	if c and c != "中国":
		# non-CN: do not enforce suffix rules
		return True

	if p in {"北京", "天津", "上海", "重庆"}:
		return False
	if p in _MUNICIPALITIES or p in _SAR or p in _AUTONOMOUS_REGIONS or p == "中国台湾":
		return True
	return p.endswith(_PROVINCE_SUFFIXES)


def _field_ok_city(country: str, city: str) -> bool:
	c = (country or "").strip()
	ct = (city or "").strip()
	if not ct:
		return True
	if _is_illegal_text(ct) or _is_abbrev_token(ct):
		return False
	if c and c != "中国":
		return True
	if ct in {"北京", "天津", "上海", "重庆"}:
		return False
	return ct.endswith(_CITY_SUFFIXES)


def _field_ok_district(country: str, district: str) -> bool:
	c = (country or "").strip()
	d = (district or "").strip()
	if not d:
		return True
	if _is_illegal_text(d) or _is_abbrev_token(d):
		return False
	if c and c != "中国":
		return True
	return d.endswith(_DISTRICT_SUFFIXES)


def _apply_field_level_fallback(orig: AddressGroup, cand: AddressGroup) -> AddressGroup:
	"""
	逐字段回退：每个字段只要不合规就回退原值；保留合规字段。
	最后再处理直辖市省市一致性与台湾 country=中国 规则。
	"""
	out_country = cand.country if _field_ok_country(cand.country) else orig.country
	out_province = cand.province if _field_ok_province(out_country, cand.province) else orig.province
	out_city = cand.city if _field_ok_city(out_country, cand.city) else orig.city
	out_district = cand.district if _field_ok_district(out_country, cand.district) else orig.district

	# Municipality: province/city should match when city is present.
	if out_province in _MUNICIPALITIES:
		if out_city and out_city != out_province:
			# Prefer reverting to orig city; if orig empty, force match to province.
			out_city = orig.city if orig.city else out_province

	# Taiwan: ensure country is China when province is 中国台湾.
	if out_province == "中国台湾" and out_country not in {"", "中国"}:
		out_country = "中国"

	return AddressGroup(country=out_country, province=out_province, city=out_city, district=out_district)


async def extract_admin_divisions_from_details(
	*,
	buyer_address_detail: str,
	project_address_detail: str,
	delivery_address_detail: str,
	original_item: dict[str, Any] | None = None,
	max_retries: int = 3,
) -> dict[str, str]:
	"""
	一次调用 LLM，从三组 AddressDetail 中提取生成 12 个字段：
	  buyer/project/delivery 的 Country/Province/City/District。

	整体重试：任意一组校验失败则重试（最多 max_retries）。
	超过上限：逐字段回退到 original_item 对应字段（或默认值）。

	默认规则：当该组 AddressDetail 为空时，country="中国"，省市区=""。
	"""
	orig_item = original_item or {}

	def _orig_group(prefix: str) -> AddressGroup:
		return AddressGroup(
			country=str(orig_item.get(f"{prefix}Country", "") or "").strip(),
			province=str(orig_item.get(f"{prefix}Province", "") or "").strip(),
			city=str(orig_item.get(f"{prefix}City", "") or "").strip(),
			district=str(orig_item.get(f"{prefix}District", "") or "").strip(),
		)

	orig_buyer = _orig_group("buyer")
	orig_project = _orig_group("project")
	orig_delivery = _orig_group("delivery")

	# If all details are empty, apply defaults without LLM.
	buyer_detail = (buyer_address_detail or "").strip()
	project_detail = (project_address_detail or "").strip()
	delivery_detail = (delivery_address_detail or "").strip()
	if not (buyer_detail or project_detail or delivery_detail):
		return {
			"buyerCountry": "中国",
			"buyerProvince": "",
			"buyerCity": "",
			"buyerDistrict": "",
			"projectCountry": "中国",
			"projectProvince": "",
			"projectCity": "",
			"projectDistrict": "",
			"deliveryCountry": "中国",
			"deliveryProvince": "",
			"deliveryCity": "",
			"deliveryDistrict": "",
		}

	expected_keys = [
		"buyerCountry",
		"buyerProvince",
		"buyerCity",
		"buyerDistrict",
		"projectCountry",
		"projectProvince",
		"projectCity",
		"projectDistrict",
		"deliveryCountry",
		"deliveryProvince",
		"deliveryCity",
		"deliveryDistrict",
	]

	system_prompt = """
You are an address extraction engine.
You will be given three detailed address strings (buyer/project/delivery).
Extract and output ONLY a single JSON object with EXACTLY the following keys:
buyerCountry,buyerProvince,buyerCity,buyerDistrict,
projectCountry,projectProvince,projectCity,projectDistrict,
deliveryCountry,deliveryProvince,deliveryCity,deliveryDistrict

Rules:
- For each group, ONLY use that group's AddressDetail as the source; do NOT use other group details.
- If a group's AddressDetail is empty, output country=\"中国\" and province/city/district as empty strings.
- Output fields in Chinese or the original language.
- China rules (when the address is in China OR you set country=\"中国\"):
  - Do NOT use abbreviations (e.g., 京/沪/浙/皖/赣/内蒙/广西/宁夏/新疆/西藏...).
  - Names must be full-form:
    - Provinces: “xx省”; Municipalities: “北京市/天津市/上海市/重庆市”
    - Autonomous regions must be full names like “内蒙古自治区/广西壮族自治区/宁夏回族自治区/新疆维吾尔自治区/西藏自治区”
    - SAR: “香港特别行政区/澳门特别行政区”
    - Taiwan MUST be “中国台湾” (province), and country must be “中国”
    - Cities end with 市/州/盟/地区 when applicable
    - Districts end with 区/县/市/旗 when present
- Non-China rules (when the address is clearly outside China OR you set a non-China country):
  - Do NOT enforce the China suffix rules above.
  - If country is not explicitly mentioned, you MAY infer the country from clear city/province clues when unambiguous.
- If you cannot confidently extract a field, output \"\".
""".strip()

	payload = {
		"buyerAddressDetail": buyer_detail,
		"projectAddressDetail": project_detail,
		"deliveryAddressDetail": delivery_detail,
	}
	user_prompt = json.dumps(payload, ensure_ascii=False)

	best_cand: dict[str, str] | None = None
	for _ in range(max_retries):
		try:
			result = await asyncio.to_thread(
				invoke_structured,
				[
					{"role": "system", "content": system_prompt},
					{"role": "user", "content": user_prompt},
				],
				AdminDivisions,
			)
		except Exception:
			continue

		parsed = result.model_dump()

		cand: dict[str, str] = {}
		for k in expected_keys:
			v = parsed.get(k, "")
			cand[k] = "" if v is None else str(v).strip()

		# Apply per-group defaults when detail empty.
		if not buyer_detail:
			cand.update({"buyerCountry": "中国", "buyerProvince": "", "buyerCity": "", "buyerDistrict": ""})
		if not project_detail:
			cand.update({"projectCountry": "中国", "projectProvince": "", "projectCity": "", "projectDistrict": ""})
		if not delivery_detail:
			cand.update({"deliveryCountry": "中国", "deliveryProvince": "", "deliveryCity": "", "deliveryDistrict": ""})

		# Best-effort: infer missing/incorrect country for foreign addresses when hints are strong.
		if buyer_detail:
			inferred = _infer_country_from_places(
				detail=buyer_detail,
				province=cand.get("buyerProvince", ""),
				city=cand.get("buyerCity", ""),
				district=cand.get("buyerDistrict", ""),
			)
			if inferred and (cand.get("buyerCountry", "") or "").strip() in {"", "中国"}:
				cand["buyerCountry"] = inferred
		if project_detail:
			inferred = _infer_country_from_places(
				detail=project_detail,
				province=cand.get("projectProvince", ""),
				city=cand.get("projectCity", ""),
				district=cand.get("projectDistrict", ""),
			)
			if inferred and (cand.get("projectCountry", "") or "").strip() in {"", "中国"}:
				cand["projectCountry"] = inferred
		if delivery_detail:
			inferred = _infer_country_from_places(
				detail=delivery_detail,
				province=cand.get("deliveryProvince", ""),
				city=cand.get("deliveryCity", ""),
				district=cand.get("deliveryDistrict", ""),
			)
			if inferred and (cand.get("deliveryCountry", "") or "").strip() in {"", "中国"}:
				cand["deliveryCountry"] = inferred

		buyer_group = AddressGroup(
			country=cand["buyerCountry"],
			province=cand["buyerProvince"],
			city=cand["buyerCity"],
			district=cand["buyerDistrict"],
		)
		project_group = AddressGroup(
			country=cand["projectCountry"],
			province=cand["projectProvince"],
			city=cand["projectCity"],
			district=cand["projectDistrict"],
		)
		delivery_group = AddressGroup(
			country=cand["deliveryCountry"],
			province=cand["deliveryProvince"],
			city=cand["deliveryCity"],
			district=cand["deliveryDistrict"],
		)

		ok_buyer, _ = _validate_group(buyer_group)
		ok_project, _ = _validate_group(project_group)
		ok_delivery, _ = _validate_group(delivery_group)

		best_cand = cand
		if ok_buyer and ok_project and ok_delivery:
			return cand

	# Exceeded retries: field-level fallback from best candidate to original.
	best = best_cand or {k: "" for k in expected_keys}
	fb_buyer = _apply_field_level_fallback(
		orig_buyer,
		AddressGroup(best.get("buyerCountry", ""), best.get("buyerProvince", ""), best.get("buyerCity", ""), best.get("buyerDistrict", "")),
	)
	fb_project = _apply_field_level_fallback(
		orig_project,
		AddressGroup(best.get("projectCountry", ""), best.get("projectProvince", ""), best.get("projectCity", ""), best.get("projectDistrict", "")),
	)
	fb_delivery = _apply_field_level_fallback(
		orig_delivery,
		AddressGroup(best.get("deliveryCountry", ""), best.get("deliveryProvince", ""), best.get("deliveryCity", ""), best.get("deliveryDistrict", "")),
	)

	# Apply defaults when detail empty.
	if not buyer_detail:
		fb_buyer = AddressGroup(country="中国", province="", city="", district="")
	if not project_detail:
		fb_project = AddressGroup(country="中国", province="", city="", district="")
	if not delivery_detail:
		fb_delivery = AddressGroup(country="中国", province="", city="", district="")

	return {
		"buyerCountry": fb_buyer.country,
		"buyerProvince": fb_buyer.province,
		"buyerCity": fb_buyer.city,
		"buyerDistrict": fb_buyer.district,
		"projectCountry": fb_project.country,
		"projectProvince": fb_project.province,
		"projectCity": fb_project.city,
		"projectDistrict": fb_project.district,
		"deliveryCountry": fb_delivery.country,
		"deliveryProvince": fb_delivery.province,
		"deliveryCity": fb_delivery.city,
		"deliveryDistrict": fb_delivery.district,
	}
