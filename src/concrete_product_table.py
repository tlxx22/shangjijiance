from __future__ import annotations

import re

_RAW_CONCRETE_PRODUCT_TABLE = """
挖机、液压挖掘机、反铲挖掘机、履带式挖掘机、轮式挖掘机、挖掘机械、土方机械、勾机、微型挖掘机、新能源挖掘机
挖掘机、挖机、反铲挖掘机、液压挖掘机、钩机、多功能挖掘机、多功能挖掘机、无人挖掘机、遥控挖掘机、智能挖掘机、步履式挖掘机、长臂挖掘机、水陆两栖挖掘机、船挖、抓钢机
汽车起重机,越野起重机,全地面起重机
桁架臂履带起重机,伸缩臂履带起重机,多功能履带起重机,风电专用履带起重机
平头塔式起重机,动臂式塔式起重机
直臂式随车起重机,折臂式随车起重机
混凝土泵车,电动泵车,混合动力泵车,搅拌泵车
电动车载泵,柴油车载泵
电动拖泵,柴油拖泵,砂浆泵,湿喷机,充填泵
混凝土搅拌车,新能源搅拌车,干混砂浆搅拌车
混凝土搅拌站,干混砂浆搅拌站,砂浆 / 混凝土双用搅拌站,原再生一体式沥青搅拌站
沥青摊铺机,多功能摊铺机,无人驾驶摊铺机
双钢轮压路机,单钢轮压路机,轮胎压路机,轻型压路机
土方平地机,矿用平地机,无人驾驶平地机
路面铣刨机,大型铣刨机
沥青搅拌设备,智能沥青搅拌站
微型旋挖钻机,小型旋挖钻机,中型旋挖钻机,大型旋挖钻机,入岩旋挖钻机,电动旋挖钻机
连续墙抓斗,双轮铣槽机
搓管钻机,水平定向钻
工程自卸车,城建渣土自卸车,矿用自卸车,电动自卸车,混合动力自卸车
剪叉式高空作业平台,直臂式高空作业平台,曲臂式高空作业平台
散装水泥运输车,粉粒物料车,干混砂浆背罐车
煤炭掘进机,工程掘进机,掘锚机,智能掘进机
薄煤层采煤机,中厚煤层采煤机,大功率智能化采煤机
刮板输送机,转载机
掩护式液压支架,支撑掩护式液压支架,放顶煤液压支架
燃油正面吊,电动正面吊,重型正面吊
集装箱空箱堆高机,集装箱重箱堆高机,电动堆高机
平衡重式叉车,重型叉车,伸缩臂叉车
门式回转起重机,岸边集装箱起重机,轨道式集装箱门式起重机
小型轮式装载机,中型轮式装载机,大型轮式装载机,电动轮式装载机
挖掘装载机,多功能挖掘装载机
纯电动洗扫车,洒水车,吸尘车,压缩空气泡沫车
餐厨垃圾车,生活垃圾收运车,医疗垃圾转运车
伸缩臂检修车,管道疏通车
举高喷射消防车,登高平台消防车,重型抢险救援消防车,专勤类消防车
救援机器人,无人机,移动模块化救援器材箱
隧道救援车,高速公路救援车,桥梁事故救援车
陆上风力发电机组,海上风力发电机组,超低风速风力发电机组,中低风速风力发电机组,中高风速风力发电机组
风力发电机,风电主控系统,风电混塔
电动牵引车,氢燃料牵引车,港口牵引车,长途干线牵引车
矿山自卸车,城建自卸车,换电版自卸车
混凝土搅拌车,粉粒物料运输车
碱性电解水制氢装备,PEM 电解水制氢装备,制加氢一体站
高效光伏组件,光伏电池,N 型硅片,单晶硅棒
工商业储能一体柜,储能集装箱,智能微网系统
空腔墙数字生产线,空腔柱柔性生产线,拆布模机器人,智能涂油划线一体机
AAC 板材生产线,AAC 砌块生产线
PC 钢筋部品生产成套装备,智能钢筋生产线
预制件专用运输车
魔塔电池,方形铝壳锂离子电池,动力 PACK
工商业储能一体柜,储能集装箱,电塔储能系统
电兔电源车,便携式储能电源
玲珑换电站,天马换电站
""".strip()


def _parse_table(raw: str) -> list[list[str]]:
	rows: list[list[str]] = []
	for line in raw.splitlines():
		line = line.strip()
		if not line:
			continue

		parts = [p.strip() for p in re.split(r"[、,，]+", line) if p.strip()]
		flat_parts: list[str] = []
		for part in parts:
			flat_parts.extend([x.strip() for x in re.split(r"\s*/\s*", part) if x.strip()])

		seen: set[str] = set()
		row: list[str] = []
		for part in flat_parts:
			if part not in seen:
				seen.add(part)
				row.append(part)

		if row:
			rows.append(row)

	return rows


CONCRETE_PRODUCT_TABLE: list[list[str]] = _parse_table(_RAW_CONCRETE_PRODUCT_TABLE)


def _build_alias_map(table: list[list[str]]) -> dict[str, str]:
	alias_map: dict[str, str] = {}
	for row in table:
		if not row:
			continue
		canonical = row[0]
		for alias in row:
			alias = alias.strip()
			if alias and alias not in alias_map:
				alias_map[alias] = canonical
	return alias_map


CONCRETE_PRODUCT_ALIAS_TO_CANONICAL: dict[str, str] = _build_alias_map(CONCRETE_PRODUCT_TABLE)
CONCRETE_PRODUCT_ALIASES_BY_LENGTH: list[str] = sorted(
	CONCRETE_PRODUCT_ALIAS_TO_CANONICAL.keys(),
	key=len,
	reverse=True,
)


def format_concrete_product_table_for_prompt() -> str:
	"""
	用于提示词展示的“具体产品表”。

	每行第一个词为标准名称（建议 `productCategory` 填写该值）。
	"""
	lines: list[str] = []
	for row in CONCRETE_PRODUCT_TABLE:
		if not row:
			continue
		lines.append(f"- {row[0]}：{'、'.join(row)}")
	return "\n".join(lines)


def normalize_concrete_product_name(value: str) -> str:
	"""
	将输入归一化为具体产品“标准名称”（若能匹配到表；匹配不到返回空串）。
	"""
	text = (value or "").strip()
	if not text:
		return ""
	if text in CONCRETE_PRODUCT_ALIAS_TO_CANONICAL:
		return CONCRETE_PRODUCT_ALIAS_TO_CANONICAL[text]

	# 容错：如果传入的是逗号分隔等，取第一个能匹配的
	for part in [p.strip() for p in re.split(r"[、,，/\\s]+", text) if p.strip()]:
		if part in CONCRETE_PRODUCT_ALIAS_TO_CANONICAL:
			return CONCRETE_PRODUCT_ALIAS_TO_CANONICAL[part]

	# 容错：子串匹配（长词优先）
	for alias in CONCRETE_PRODUCT_ALIASES_BY_LENGTH:
		if alias and alias in text:
			return CONCRETE_PRODUCT_ALIAS_TO_CANONICAL[alias]

	return ""


def match_concrete_product_from_subject(subject: str) -> str:
	"""
	从标的物文本中尝试匹配具体产品标准名称；匹配不到返回空串。
	"""
	text = (subject or "").strip()
	if not text:
		return ""
	for alias in CONCRETE_PRODUCT_ALIASES_BY_LENGTH:
		if alias and alias in text:
			return CONCRETE_PRODUCT_ALIAS_TO_CANONICAL[alias]
	return ""
