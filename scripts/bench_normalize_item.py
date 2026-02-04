from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


SAMPLE_SOURCE_TEXT = """<div><p>中铁十一局集团有限公司第三分公司2026年度浙江杭州地区扣件尼龙件框架协议采购公告</p><p>采购编号：CR1103-KJJC-2026-014</p><p>现对中铁十一局集团有限公司第三分公司所辖浙江杭州地区范围内项目的扣件尼龙件进行2026年度区域框架协议公开招标采购，欢迎有意向的供应商参与。</p><p><strong>1．</strong><strong>公司</strong><strong>概况</strong><strong>、</strong><strong>采购</strong><strong>范围</strong></p><p>1.1项目概况：</p><p>中铁十一局集团有限公司第三分公司是世界500强企业—中国铁建股份有限公司下属的三级法人单位，前身为中国人民解放军铁道兵一师三团，2008年随中国铁建股份公司整体上市。公司综合实力连续14次入选中国铁建工程公司20强，连续2次入选中国铁建“专精特新”企业，被国家领导人称为“铺架劲旅”公司注册资本注册资金10.01亿元。公司具有铁路、公路、市政、建筑、矿山、机电工程6项施工总承包资质，桥梁、隧道、公路路基、铁路铺轨架梁、环保工程5项专业承包资质，形成主业突出，多元发展的产业结构，年施工能力在100亿元以上。</p><p>公司施工的工程获中国建筑工程鲁班奖6项，中国土木工程詹天佑奖11项，国家优质工程奖32项，中国市政金杯示范工程奖3项，国家科技进步特等奖1项，省部级科技进步奖12项，国家级工法5项，省部级工法27项，发明专利28项，实用新型191项，软件著作权15项，主持或参与编制各类标准规范39项。公司被认定为湖北省高新技术企业，公司技术中心被评定为湖北省企业技术中心、铁路铺架工程技术研究中心。依托公司铺架优势，集团公司被认定为中国铁建铺架技术及装备研发中心。</p><p>1.1.1工程概况：项目位于浙江杭州片区，铺轨20.148km(不含断链)：普通整体道床9.66km（含配线1.638km）、减振垫道床5.898km、可调框架板道床0.69km、钢弹簧浇浮置板道床3.9km。另铺设 60kg/m 钢轨 9 号单开道岔6 组，60kg/m 钢轨 9 号单开道岔 5m 交叉渡线 1 组，60kg/m 钢轨 9 号单开道岔14m 交叉渡线 1 组。</p><p>此次招标依据为：</p><p>（1）《中华人民共和国招标投标法》；</p><p>（2）《中华人民共和国招标投标法实施条例》（国务院第613号令）；</p><p>（3）《铁路建设物资采购供应管理办法》（铁总物资[2015]116号）；</p><p>（4）《评标委员会和评标方法暂行规定》（国家发展改革委等七部委令第12号）；</p><p>（5）《中国铁建股份有限公司物资采购管理规定（试行）》（中国铁建供应链〔2025〕106号）；</p><p>（6）《中铁十一局集团有限公司物资采购管理办法》（物设[2025]505号）；</p><p>（7）其他相关法律、法规、规章。</p><p>1.2采购内容：</p><p>1.2.1 扣件尼龙件，具体内容详见采购公告附件1《采购物资包件清单》。</p><p>1.2.2本次框架协议采购各包件内采购数量不作为实际供应依据，仅针对供应商报价及评审需要，具体以浙江杭州地区所属单位实际需求为准。</p><p>1.3框架协议有效期：自协议签订之日至2026年12月31日。</p><p><strong>2．</strong><strong>供应商</strong><strong>资格要求</strong></p><p><strong>扣件尼龙件</strong></p><p>1.营业范围要求：本次招标要求投标人须在中华人民共和国境内依法注册，符合投标项目经营范围；具有招标物资生产能力和供货经验；具有法人资格能独立承担民事责任；具备一般纳税人资格，能开具增值税专用发票。</p><p>2.生产能力要求：生产能力应满足招标人施工进度的要求；具有相应的专业技术人员和符合国家规定的专业生产设备、检测设备。</p><p>3.财务能力要求：财务状况良好，提供近2023-2025年其中2年的经过注册会计师事务所出具的审计报告或者财务报告。期间成立的公司（不足1年）须提供成立以后的相关财务报表。</p><p>4.质量保证能力要求：生产厂家必须具有同类零部件CRCC认证；其它行业颁发的生产许可证需经过招标人特别认可。投标的产品在近两年内未发生过重大质量责任事故；投标物资（或同类产品）须具有检测机构出具的产品检验合格报告。生产厂家必须具有同类零部件CRCC认证；其它行业颁发的生产许可证需经过招标人特别认可。</p><p>5.供货业绩要求：具有近5年内国内车型、线路、速度等工况类似的城市轨道交通或高铁项目正线上类似扣件（所供扣件的技术要求应达到或超过本《技术规格书》中陈述的要求）的供货业绩（数量不少于3条线），且能提供业主运营部门出具的使用情况证明和相关证明材料（附中标通知书、供货合同复印件或发票等供货业绩证明文件）。</p><p>6.投标人应有良好的履约能力和信誉；不接受近一年内在铁路建设工程网公布有违法行为记录及物资供应不良记录的供货商；不接受被中国铁路总公司限制投标或已清退出铁路市场的供货商；中铁十一局集团有限公司供应商不良行为名录内的供货商。不接受贸易商报价。供应商及法定代表人自递交响应文件之日起前 1 年不得存在中国裁判文书网 (http://Twenshu.court.gov.cn/)上行犯罪录;供应商不得在国家企业信用信息公示系统被列入严重违法失信企业名单，不得在“信用中国”网站 (www.creditchina.gov.cn)上被列为失信被执行人。    </p><p><strong>其他要求：</strong></p><p><strong>（</strong><strong>1</strong><strong>）</strong><strong>本次</strong><strong>采购</strong><strong>不接受联合体</strong><strong>参与</strong><strong>。</strong></p><p><strong>（</strong><strong>2</strong><strong>）</strong><strong>法定代表人或单位负责人为同一个人的两个及以上供应商或母公司、全资子公司存在控股、管理关系的，不得参与同一个包件。</strong></p><p><strong>（</strong><strong>3</strong><strong>）</strong><strong>不接受代理单位参与。</strong></p><p><strong>3．采购文件的获取</strong></p><p>3.1凡有意参加者，请登陆中国铁建云链平台（www.crccep.cn）注册会员，查询拟参与包件，完成网上报名、支付对应包件采购文件费用、下载电子采购文件（具体操作参见“小鹿课堂”-“铁建云链-供方子门户操作手册”）。</p><p>3.2采购文件售卖时间为2026年2月5日至2026年2月10日，售卖截止时间为2026年2月10日17时00分。潜在供应商须在采购文件售卖截止时间前完成中国铁建云链平台（www.crccep.cn）注册报名，并申请办理CA锁用于电子响应文件的签章、加密及解密（CA办理所需资料及程序详见中国铁建云链平台首页-小鹿课堂-帮助中心-铁建云链平台数字证书办理流程）或咨询铁建云链客服。</p><p>3.3本次采购包件划分情况见采购公告附件1《采购物资包件清单》。</p><p>3.4采购文件每包件售价见采购公告附件1《采购物资包件清单》，付款单位名称必须与供应商名称保持一致（不接受个人汇款），<strong>付</strong><strong>款时须注明“采购编号+包件号”</strong>，<strong>售后不退。</strong>购买采购文件汇入银行信息：</p><p>账户名：中铁十一局集团有限公司杭州市城市轨道交通4号线三期工程铺轨工程施工项目经理部</p><p>账  号：1202021139801100604</p><p>开户行：中国工商银行股份有限公司杭州分行营业部</p><p>行  号：102331002116</p><p>3.5购买采购文件发票的获取方式：汇款完成后请及时开票事宜。</p><p>3.6本次购买采购文件的发票统一采用电子发票并在开标后发送至供应商报名时指定邮箱。</p><p><strong>4．响应文件的递交</strong></p><p>4.1此次供应商需制作电子响应文件，并使用CA锁对响应文件进行加密，在递交截止时间前线上递交响应文件。</p><p>4.2响应文件递交截止时间：2026年3月4日10时00分。</p><p>4.3响应文件递交地点：中国铁建云链平台（www.crccep.cn），供应商须登陆该平台，在响应文件递交截止时间前完成所有响应文件的上传。响应文件递交截止时间前未完成响应文件传输的，视为放弃参加资格。CA加解密详见“中国铁建云链平台首页-小鹿课堂-帮助中心-CA加解密操作手册”或咨询铁建云链客服。</p><p>4.4如采购人有需求，被评为入围候选人的供应商应无偿提供纸质版响应文件，纸质版响应文件内容须与电子版文件内容完全一致。</p><p><strong>5．</strong><strong>开标</strong></p><p>5.1开标时间：2026年3月4日10时00分。</p><p>5.2电子响应文件的解密</p><p>（1）电子响应文件解密时间：2026年3月4日10时00分至12时00分。</p><p>（2）各供应商必须在规定的响应文件解密时间内登录中国铁建云链平台（www.crccep.cn）完成响应文件解密，如因供应商自身原因导致所递交的响应文件无法在规定的时间内解密的，视为无效响应文件，后果及责任由供应商自行负责。</p><p><strong>6．发布公告的媒介</strong></p><p>本次采购公告同时在中国招标投标公共服务平台(www.cebpubservice.com)、中国铁建云链平台（www.crccep.cn）上发布。</p><p><strong>7．联系方式</strong></p><p><strong>7.1采购人</strong></p><p>中铁十一局集团有限公司第三分公司</p><p>招标人代表：谈茂芳</p><p>联系电话：18120580880</p><p><strong>7.2</strong><strong>采购组织单位</strong><strong>信息</strong></p><p>采购组织单位：中铁十一局集团有限公司物资设备集中采购管理中心第三分中心</p><p>联系人：薛先生</p><p>电话： 15285114767</p><p>地址：江苏省南京市溧水区新望大厦</p><p>采购文件售卖、发票开具及保证金退还联系人：谈茂芳  电话：18120580880</p><p><strong>7.3 </strong><strong>协助单位</strong><strong>信息</strong></p><p>铁建云链平台技术支持：400 6296 8888</p><p> </p><p>二〇二六年二月四日</p><p><br/> </p><p>附件1：</p><p><strong>采购物资包件清单</strong></p><table><tbody><tr><td><p><strong>包件号</strong></p></td><td><p><strong>物资名称</strong></p></td><td><p><strong>规格型号</strong></p></td><td><p><strong>计量单位</strong></p></td><td><p><strong>数量</strong></p></td><td><p><strong>供货区域</strong></p></td><td><p><strong>采购人名称</strong></p></td><td><p><strong>文件售价（元）</strong></p></td><td><p><strong>备注</strong></p></td></tr><tr><td rowspan=\"3\"><p><strong>NL01</strong></p></td><td><p>尼龙套管</p></td><td><p>DTVI2-1型</p></td><td><p>个</p></td><td><p>136192</p></td><td rowspan=\"3\"><p>杭州地区</p></td><td rowspan=\"3\"><p>中铁十一局集团第三分公司杭州地区所属项目</p></td><td rowspan=\"3\"><p>1000</p></td><td rowspan=\"3\"><br/></td></tr><tr><td><p>8号中间轨距垫</p></td><td><p>DTVI2-1型</p></td><td><p>个</p></td><td><p>53236</p></td></tr><tr><td><p>10号中间轨距垫</p></td><td><p>DTVI2-1型</p></td><td><p>个</p></td><td><p>53236</p></td></tr></tbody></table><p> </p><p>注：以上物资数量只用作报价参考，实际采购数量以供货区域内项目采购需求为准。</p><p><br/></p></div>",
"""


def _now_iso() -> str:
	# Keep it dependency-free and stable for logs.
	return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_text_arg(text: str | None, file_path: str | None) -> str:
	if text is not None:
		return text
	if file_path:
		return Path(file_path).read_text(encoding="utf-8", errors="ignore")
	# stdin
	if not sys.stdin.isatty():
		return sys.stdin.read()
	return ""


async def _run_once(
	source_text: str,
	*,
	max_retries: int,
	with_address: bool,
	with_full_pipeline: bool,
) -> dict[str, Any]:
	# Import lazily so this script can show a clear error if deps/env missing.
	from src.llm_transform import _extract_normalize_item_meta_flat, _normalize_item_to_crawler_schema
	from src.custom_tools import TYPE_DEFAULTS
	from src.config_manager import load_extract_fields
	from src.custom_tools import extract_fields_from_html
	from src.address_normalizer import extract_admin_divisions_from_details

	stats: dict[str, Any] = {"ts": _now_iso()}

	# Stage 1: meta + flat
	t0 = time.perf_counter()
	flat = await _extract_normalize_item_meta_flat(source_text)
	t1 = time.perf_counter()

	# Stage 2: lots
	lots = await extract_fields_from_html(source_text, site_name="normalize_item", stage="lots")
	t2 = time.perf_counter()

	# Stage 2.5: schema normalization (non-LLM, should be fast)
	# IMPORTANT: do NOT call normalize_source_json_to_item() here, because it would call LLM again.
	# Build a minimal template with correct empty defaults, then apply the same schema normalizer.
	flat_fields = load_extract_fields(stage="flat", fields_path="normalize_item_meta_flat_fields.yaml")
	lots_fields = load_extract_fields(stage="lots", fields_path="extract_fields.yaml")
	all_fields = list(flat_fields) + list(lots_fields)
	item: dict[str, Any] = {f.key: TYPE_DEFAULTS.get(f.type, "") for f in all_fields}
	item.update(flat or {})
	item["lotProducts"] = (lots or {}).get("lotProducts") or []
	item["lotCandidates"] = (lots or {}).get("lotCandidates") or []
	item = _normalize_item_to_crawler_schema(item)
	t3 = time.perf_counter()

	addr_fields: dict[str, str] = {}
	if with_address:
		addr_fields = await extract_admin_divisions_from_details(
			buyer_address_detail=item.get("buyerAddressDetail", "") or "",
			project_address_detail=item.get("projectAddressDetail", "") or "",
			delivery_address_detail=item.get("deliveryAddressDetail", "") or "",
			original_item=item,
			max_retries=max_retries,
		)
		item.update(addr_fields)
	t4 = time.perf_counter()

	stats["durations_s"] = {
		"meta_flat_llm": round(t1 - t0, 3),
		"lots_llm": round(t2 - t1, 3),
		"normalize_schema_non_llm": round(t3 - t2, 3),
		"address_llm": round(t4 - t3, 3),
		"total": round(t4 - t0, 3),
	}

	# Minimal payload so the report stays readable.
	stats["outputs"] = {
		"flat_keys": sorted(list((flat or {}).keys())),
		"lots_counts": {
			"lotProducts": len((lots or {}).get("lotProducts") or []),
			"lotCandidates": len((lots or {}).get("lotCandidates") or []),
		},
		"address_keys": sorted(list(addr_fields.keys())),
	}

	if with_full_pipeline:
		stats["item_preview"] = {
			"announcementName": item.get("announcementName", ""),
			"announcementDate": item.get("announcementDate", ""),
			"announcementType": item.get("announcementType", ""),
			"buyerName": item.get("buyerName", ""),
			"buyerProvince": item.get("buyerProvince", ""),
			"buyerCity": item.get("buyerCity", ""),
			"projectName": item.get("projectName", ""),
		}

	return stats


async def main() -> int:
	parser = argparse.ArgumentParser(
		description="Benchmark /normalize_item internal stages (meta+flat, lots, address) without starting uvicorn."
	)
	parser.add_argument("--text", help="Input sourceJson text", default=None)
	parser.add_argument("--file", help="Read input text from file", default=None)
	parser.add_argument("--runs", type=int, default=1, help="Number of runs (default: 1)")
	parser.add_argument("--max-retries", type=int, default=3, help="Address LLM overall retries (default: 3)")
	parser.add_argument("--no-address", action="store_true", help="Skip address extraction stage")
	parser.add_argument(
		"--full",
		action="store_true",
		help="Include a small item preview (NOT the full item) in output",
	)
	args = parser.parse_args()

	# Keep behavior consistent with app.py on Windows.
	if sys.platform == "win32":
		asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

	# Ensure repo root is importable even when executed from scripts/ directory.
	repo_root = Path(__file__).resolve().parents[1]
	if str(repo_root) not in sys.path:
		sys.path.insert(0, str(repo_root))

	# Load repo root .env (BROWSER_USE / DeepSeek keys, base_url, etc.)
	load_dotenv(repo_root / ".env")

	source_text = _read_text_arg(args.text, args.file).strip()
	used_sample = False
	if not source_text:
		source_text = SAMPLE_SOURCE_TEXT
		used_sample = True

	out: dict[str, Any] = {
		"ts": _now_iso(),
		"cwd": str(Path.cwd()),
		"route": getattr(__import__("trans"), "ROUTE", None),
		"env": {
			"SANY_AI_GATEWAY_BASE_URL": os.getenv("SANY_AI_GATEWAY_BASE_URL", ""),
			"SILICONFLOW_BASE_URL": os.getenv("SILICONFLOW_BASE_URL", ""),
			"SANY_EXTRACT_MODEL": os.getenv("SANY_EXTRACT_MODEL", ""),
			"SILICONFLOW_EXTRACT_MODEL": os.getenv("SILICONFLOW_EXTRACT_MODEL", ""),
		},
		"runs": [],
		"used_sample": used_sample,
	}

	for i in range(args.runs):
		stats = await _run_once(
			source_text,
			max_retries=args.max_retries,
			with_address=not args.no_address,
			with_full_pipeline=args.full,
		)
		stats["i"] = i + 1
		out["runs"].append(stats)

	# Print json for easy copy/paste and log comparisons.
	print(json.dumps(out, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(asyncio.run(main()))
