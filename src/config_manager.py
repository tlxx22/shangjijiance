"""
配置管理模块
负责读取和验证配置文件（sites_config.yaml和prompt.txt）
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SiteConfig(BaseModel):
	"""单个网站配置"""
	name: str
	url: str
	login_required: bool = False
	username: str | None = None
	password: str | None = None


class ExtractField(BaseModel):
	"""单个提取字段定义"""
	key: str  # 字段键名（英文）
	name: str  # 字段中文名
	type: str = "string"  # 类型: string, number, boolean, array
	stage: str = "meta"  # 分组: meta | contacts | address_detail | lots | address_admin | estimated_amount
	required: bool = False  # 是否必填（用于 prompt 强约束）
	enum: list[str] | None = None  # 枚举值（用于 prompt 强约束）
	hint: str = ""  # 提取提示


class Config(BaseModel):
	"""全局配置"""
	websites: List[SiteConfig]
	prompt: str
	max_pages: int = 3  # 默认翻5页
	max_retries: int = 3  # 默认重试3次


# LEGACY: 以下函数仅供 CLI 模式（main.py）使用，API 模式不使用
def load_config(config_path: str = "sites_config.yaml", prompt_path: str = "prompt.txt") -> Config:
	"""
	[LEGACY - CLI only] 加载配置文件

	Args:
		config_path: 网站配置文件路径
		prompt_path: 提示词文件路径

	Returns:
		Config对象

	Raises:
		FileNotFoundError: 配置文件不存在
		ValueError: 配置文件格式错误
	"""
	# 读取网站配置
	config_file = Path(config_path)
	if not config_file.exists():
		raise FileNotFoundError(f"配置文件不存在: {config_path}")

	with open(config_file, 'r', encoding='utf-8') as f:
		raw_config = yaml.safe_load(f)

	# 读取提示词
	prompt_file = Path(prompt_path)
	if not prompt_file.exists():
		raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")

	with open(prompt_file, 'r', encoding='utf-8') as f:
		prompt = f.read()

	# 验证配置
	websites = []
	for site_data in raw_config.get('websites', []):
		# 验证必需字段
		if 'name' not in site_data or 'url' not in site_data:
			raise ValueError(f"网站配置缺少必需字段: {site_data}")

		# 验证登录配置
		if site_data.get('login_required') and (not site_data.get('username') or not site_data.get('password')):
			raise ValueError(f"网站 {site_data['name']} 需要登录但未提供账号密码")

		websites.append(SiteConfig(**site_data))

	if not websites:
		raise ValueError("配置文件中没有网站配置")

	return Config(websites=websites, prompt=prompt)


def get_user_data_dir(site_name: str, base_dir: str = ".browser-profiles") -> str:
	"""
	生成网站的user_data_dir路径

	Args:
		site_name: 网站名称
		base_dir: 基础目录

	Returns:
		user_data_dir路径
	"""
	# 清理网站名称中的非法字符
	safe_name = "".join(c for c in site_name if c.isalnum() or c in (' ', '-', '_')).strip()
	path = Path(base_dir) / safe_name
	path.mkdir(parents=True, exist_ok=True)
	return str(path)


def load_extract_fields(fields_path: str = "extract_fields.yaml", stage: str | None = None) -> List[ExtractField]:
	"""
	加载字段提取配置

	Args:
		fields_path: 字段配置文件路径
		stage: 可选，按 stage 过滤（meta/contacts/address_detail/lots/address_admin/estimated_amount）

	Returns:
		字段定义列表（可按 stage 过滤）

	Raises:
		FileNotFoundError: 配置文件不存在
	"""
	fields_file = Path(fields_path)
	if not fields_file.exists():
		raise FileNotFoundError(f"字段配置文件不存在: {fields_path}")

	with open(fields_file, 'r', encoding='utf-8') as f:
		raw_config = yaml.safe_load(f)

	fields: list[ExtractField] = []
	for field_data in raw_config.get('fields', []):
		if 'key' not in field_data or 'name' not in field_data:
			raise ValueError(f"字段配置缺少必需字段: {field_data}")
		field = ExtractField(**field_data)
		if stage is None or field.stage == stage:
			fields.append(field)

	return fields


def generate_extract_prompt(
	fields: List[ExtractField],
	stage: str,
	*,
	product_category_table: str | None = None,
) -> str:
	"""
	根据字段定义生成提取提示词

	Args:
		fields: 字段定义列表
		stage: meta / contacts / address_detail / lots / address_admin / estimated_amount

	Returns:
		提取提示词字符串
	"""
	lines = ["从输入内容中提取以下字段，返回 JSON：", ""]

	lines.append("**类型与空值规则：**")
	lines.append('- string: 找不到填 ""')
	lines.append("- number: 找不到填 null")
	lines.append("- boolean: 只能填 true 或 false")
	lines.append("- array: 找不到填 []")
	lines.append("- JSON 必须严格合法：key 必须使用双引号（\"\"），不能用单引号，不能省略引号")
	lines.append("")

	if stage == "meta":
		lines.append("**额外规则：**")
		lines.append("- 金额字段单位为“元”，无单位数字视为元；如带“万/亿”，请换算成元（小数位数尽量与页面一致）")
		lines.append("- 日期字段统一为 YYYY-MM-DD")
		lines.append("- 公告类别必须从枚举中选择一个")
		lines.append("")
	elif stage == "contacts":
		lines.append("**额外规则：**")
		lines.append("- 仅提取页面/输入中【明确标注】的单位/联系人/电话/邮箱；找不到填空值，不要编造")
		lines.append("- 注意区分：不要把地址/项目地点当成联系人或单位名称")
		lines.append("")
	elif stage == "address_detail":
		lines.append("**额外规则：**")
		lines.append("- 本阶段只提取三组详细地址（buyer/project/deliveryAddressDetail）原文字符串")
		lines.append("- 严禁把采购单位/代理机构地址回填到项目地址或交货地址")
		lines.append(
			"- 若缺少街道门牌等详细地址，但输入中有【明确给出】的省/市/区县信息，允许按“省→市→区县”拼接成最小 AddressDetail；否则填 \"\"（不要猜）"
		)
		lines.append("")
	elif stage == "lots":
		lines.append("**额外规则：**")
		lines.append("- lotProducts/lotCandidates 必须返回数组；未提及则返回 []")
		lines.append("- lotNumber 必须是“标段号”，格式为“标段一/标段二/...”；若页面未写明，填 \"标段一\"（不要留空）")
		lines.append("- 若当前公告里出现多个不同的原始标段/包件标识（如“标1包2”“标1包3”“标1包4”），它们必须视为不同 lot，绝不能合并成同一个 lotNumber；包号不同就是不同 lot")
		lines.append("- lotNumber 的“标段一/标段二/...”应按当前公告中不同原始 lot 首次出现的顺序依次编号；同一个原始标段/包件在 lotProducts 和 lotCandidates 中必须共用同一个 lotNumber")
		lines.append("- 判断 lot 是否相同，必须看完整的“标号+包号”组合，而不是只看“标号”；例如“标1包1/标1包2/标1包3/标1包4”分别是 4 个不同 lot")
		lines.append("- lotName 尽量保留原文中的标段/包件名称；若原文是“标1包2:XXX”，可以完整保留为 lotName，但不要因此把它和“标1包3”合并")
		lines.append("- 严禁把项目编号/招标编号/公告编号（如 CEZB****）填到 lotNumber")
		lines.append("- lotProducts：每个元素表示一条“标的物行”；其中 unitPrices 为 number(元) 或 null，其余如 subjects/models/quantities/productCategory 为 string；如有多条标的物，输出多个元素（可复用相同 lotNumber/lotName）")
		lines.append("- 即使是结果公示/评标结果公示/候选公示类正文，只要正文明确出现“包件/标段 + 设备名/物资名”，也必须同步输出对应的 lotProducts；不要只输出 lotCandidates")
		lines.append("- 抽取 lotProducts 时，不要求同时具备数量/单位/型号；只要设备名/物资名明确，就应先保留该标的物行，缺失字段留空")
		lines.append("- 抽取 lotProducts.subjects 时，必须综合标题、正文、项目名称、主要标的信息名称判断，不要只盯正文")
		lines.append("- 若正文主要是中标单位、金额、联系方式等结果信息，标的物线索较弱，但标题/项目名称/主要标的信息名称中已明确出现设备名/物资名，仍应提取该标的物，不要遗漏；例如“消防培训中心项目采购消防车辆标段四”应提取 subjects=\"消防车辆\"")
		lines.append("- subjects 只填写最直接的设备名/物资名，不要把整句标题、整句项目名称或整句主要标的信息名称原样照抄进 subjects")
		lines.append("- lotCandidates：每个元素表示一条“单位行”，包含 type（中标/中标候选人/非中标候选人）+ candidates(string) + candidatePrices(number(元) 或 null)；如有多行，输出多个元素")
		lines.append("- candidates 只允许填写明显的公司/组织名字符串（如有限公司、研究院、中心、学校、医院、厂、院、联合体等明确主体名称）；若原文对应位置不是明确的公司/组织名，而是“另行公告/待公告/另行通知/详见附件/排名第1”等占位词、说明语或其他非主体文本，则 candidates 必须填 \"\"")
		lines.append("- 若某个 lot 的候选单位名称缺失或 candidates 被判定为应填 \"\"，仍必须保留该 lot 的单位行；只允许将 candidates 置空，lotNumber/type/candidatePrices 等其他字段照常提取，不要丢掉该 lot")
		lines.append(
			"- unitPrices/candidatePrices 单位为“元”；如页面为“万/亿”，必须换算成“元”；如果无法解析为单一金额（如范围/多个值/非金额文本），请返回 null（不要编造）"
		)
		lines.append("- productCategory：只允许根据 subjects 本身与“具体产品表”匹配，直接填写表中与 subjects 语义最贴近、最具体的那个候选项本身。表中所有词都是平级候选项，换行仅为阅读方便，不表示首词优先；匹配不到填 \"\"")
		lines.append("- 严禁使用 models/型号/规格/配套说明/适用对象/用途说明 去推断 productCategory；尤其像“配XX设备用”“适用于XX设备”“XX安装”“XX维修”“XX运输”“XX施工服务”“XX海运费”“XX租赁”里的目标设备或服务对象，都不是本次采购标的的 productCategory")
		lines.append("- 如果 subjects 是‘阀芯组件/滤芯/密封件/配件/备件/组件’这类部件或通用物料词，且仅靠 subjects 本身无法在具体产品表中稳定匹配到明确品类，则 productCategory 必须返回 \"\"，不要因为 models 里出现了‘液压支架/采煤机/搅拌站/装载机’就回填这些设备品类")
		lines.append("- 示例：subjects=阀芯组件，models=配ZY15000/30/65D型掩护式液压支架用 => productCategory 必须是 \"\"")
		lines.append("- 示例：subjects=反冲洗滤芯，models=配ZY13000/24/50D型支撑掩护式液压支架用 => productCategory 必须是 \"\"")
		lines.append("")
		lines.append("**具体产品表（用于 productCategory 匹配）**")
		from .concrete_product_table import format_concrete_product_table_for_prompt
		lines.append(format_concrete_product_table_for_prompt(product_category_table))
		lines.append("")

	for i, field in enumerate(fields, 1):
		required_hint = "【必填】" if field.required else ""
		type_hint = f"（类型: {field.type}）"
		lines.append(f"{i}. {field.key} - {field.name} {type_hint} {required_hint}".strip())
		if field.hint:
			lines.append(f"   提示：{field.hint}")
		if field.enum:
			lines.append(f"   可选值：{', '.join(field.enum)}")

	lines.append("")
	lines.append("只返回 JSON，不要解释、不要代码块。")

	return "\n".join(lines)


# ============ LEGACY: 并发配置（仅 CLI 模式使用）============

class ConcurrencySettings(BaseModel):
	"""并发设置"""
	enabled: bool = False
	max_workers: int = 10
	timeout_per_site: int = 1200


class BrowserSettings(BaseModel):
	"""浏览器设置"""
	headless: bool = True


class LoggingSettings(BaseModel):
	"""日志设置"""
	worker_log_dir: str = "worker_logs"


class ConcurrencyConfig(BaseModel):
	"""并发配置（完整）"""
	concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
	browser: BrowserSettings = Field(default_factory=BrowserSettings)
	logging: LoggingSettings = Field(default_factory=LoggingSettings)


def load_concurrency_config(path: str = "concurrency_config.yaml") -> ConcurrencyConfig:
	"""
	加载并发配置文件

	Args:
		path: 配置文件路径

	Returns:
		ConcurrencyConfig 对象，文件不存在则返回默认值
	"""
	config_file = Path(path)
	if not config_file.exists():
		return ConcurrencyConfig()  # 返回默认值（并发关闭）

	with open(config_file, 'r', encoding='utf-8') as f:
		raw_config = yaml.safe_load(f)

	if not raw_config:
		return ConcurrencyConfig()

	return ConcurrencyConfig(**raw_config)
