# 商机监测爬虫 API 接口文档

## 接口概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/crawl` | 发起爬取任务（SSE 流式响应） |
| POST | `/embedding` | 文本向量化（返回 embedding 向量） |
| POST | `/content_to_md` | 公告原文转 Markdown |
| POST | `/normalize_item` | 任意来源 JSON 映射统一模板 |
| POST | `/parent_org_name` | 联网搜索最接近上级组织 |

---

## GET /health

健康检查接口。

**响应**

```json
{"status": "ok"}
```

---

## POST /crawl

发起爬取任务，返回 SSE 流式响应。

### 请求

**Content-Type**: `application/json`

**请求体**

```json
{
  "site": {
    "name": "安能招投标平台",
    "url": "https://example.com",
    "login_required": true,
    "username": "xxx",
    "password": "yyy"
  },
  "date_start": "2026-01-01",
  "date_end": "2026-01-31",
  "category": "fuwu",
  "productCategoryTable": "挖机、液压挖掘机\n汽车起重机、越野起重机",
  "engineering_machinery_only": false,
  "timeout_seconds": 1200,
  "max_pages": 3
}
```

**字段说明**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| site.name | string | ✅ | 网站名称 |
| site.url | string | ✅ | 招标列表页 URL |
| site.login_required | boolean | ❌ | 是否需要登录（默认 false） |
| site.username | string | 条件 | 登录用户名（login_required=true 时必填） |
| site.password | string | 条件 | 登录密码（login_required=true 时必填） |
| date_start | string | ✅ | 筛选开始日期，格式 YYYY-MM-DD |
| date_end | string | ✅ | 筛选结束日期，格式 YYYY-MM-DD |
| category | string | ✅ | 分类（对应 prompts/ 目录下的模板名） |
| productCategoryTable | string | ❌ | 可选：具体产品匹配表（raw string）。存在时覆盖默认“具体产品表”，注入到 lotProducts.productCategory 的匹配提示词中；不传则使用内置表。 |
| engineering_machinery_only | boolean | ❌ | 是否仅保留工程机械类公告（默认 false；在详情页基于 projectName 做二次判定，不符合则跳过不落盘/不返回 SSE item） |
| timeout_seconds | integer | ❌ | 超时时间（默认 1200s） |
| max_pages | integer | ❌ | 最大翻页数（默认 3） |

**校验规则**

- date_start > date_end → 400
- category 模板不存在 → 400
- login_required=true 但未提供 username/password → 400

---

### 响应

#### SSE 流式响应（200）

**响应头**

```
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**响应体格式**

每条消息为一帧：`data: <json>\n\n`

---

### 事件类型

#### start - 开始处理

```json
data: {"type":"start","request_id":"a1b2c3d4","site_name":"安能招投标平台","url":"https://example.com"}
```

> ⚠️ 不包含 username/password

---

#### item - 单条数据

每抓取到一条详情页数据立即发送。

```json
data: {"type":"item","request_id":"a1b2c3d4","data":{"dataId":"<sha256>","announcementUrl":"https://example.com/detail/123","announcementName":"某某项目招标公告","announcementContent":"<div>（此处为详情页正文原始 HTML，包含表格结构等）</div>","projectName":"某某项目","projectId":"CEZB250209959","announcementDate":"2026-01-19","bidOpenDate":"2026-01-26","budgetAmount":5000000.0,"winnerAmount":970000.0,"estimatedAmount":"4000000.00~6000000.00","buyerCountry":"中国","buyerProvince":"北京市","buyerCity":"北京市","buyerDistrict":"朝阳区","buyerAddressDetail":"中国北京市朝阳区XX路1号","projectCountry":"中国","projectProvince":"内蒙古自治区","projectCity":"鄂尔多斯市","projectDistrict":"","projectAddressDetail":"内蒙古自治区鄂尔多斯市XX矿区","deliveryCountry":"中国","deliveryProvince":"内蒙古自治区","deliveryCity":"鄂尔多斯市","deliveryDistrict":"","deliveryAddressDetail":"内蒙古自治区鄂尔多斯市XX煤矿","buyerName":"国能（北京）跨境电商有限公司","buyerContact":"张三","buyerPhone":"010-12345678","buyerEmail":"buyer@example.com","agency":"国家能源集团国际工程咨询有限公司","announcementType":"招标","isEquipment":true,"lotProducts":[{"lotNumber":"标段一","lotName":"三山岛金矿","subjects":"液压挖掘机","productCategory":"挖机","models":"XE490DK","unitPrices":2800000.0,"quantities":"2","quantityUnit":"台"}],"lotCandidates":[{"lotNumber":"标段一","lotName":"三山岛金矿","type":"中标候选人","candidates":"A公司","candidatePrices":970000.0}]}}
```

说明：
- `dataId` 为单条数据的稳定唯一标识（基于字段内容计算的 SHA256），可用于同站点去重
- `announcementContent` 为详情页正文原始内容（HTML 字符串），不做 Markdown 转换，包含表格结构等
- `budgetAmount` 单位为“元”；取不到填 `null`（小数位数尽量与原页面保持一致）
- `winnerAmount` 单位为“元”；取不到填 `null`（小数位数尽量与原页面保持一致）
- `lotCandidates[].candidatePrices` 单位为“元”；类型为 number；取不到/不合法填 `null`
- `lotProducts[].unitPrices` 单位为“元”；类型为 number；取不到/不合法填 `null`
- `lotProducts[].quantityUnit` 为数量单位（如 `台/套/个`），取不到填 `""`
- `estimatedAmount` 与公告类型无关；仅由“中标金额/候选人报价/标的物”决定；格式必须为 `"下限~上限"`（元；若只有单值金额则输出为 `"X~X"`）；取不到填 `""`
- `isEquipment` 用于判断是否为“设备采购类”相关；不确定时默认 `true`（召回优先）
- 地址字段已拆分为 3 组 * 5 个扁平字段（取不到填 `""`；`*Country` 默认为 `"中国"`）：
  - `buyerCountry/buyerProvince/buyerCity/buyerDistrict/buyerAddressDetail`
  - `projectCountry/projectProvince/projectCity/projectDistrict/projectAddressDetail`
  - `deliveryCountry/deliveryProvince/deliveryCity/deliveryDistrict/deliveryAddressDetail`
- `lotProducts` / `lotCandidates` 无内容时返回 `[]`
- `lotProducts`/`lotCandidates` 中单条元素为“一行”；如有多个值请输出多条元素，不要在字段里输出数组

---

#### heartbeat - 心跳

30 秒无任何输出时发送，表示连接仍存活。

```json
data: {"type":"heartbeat","request_id":"a1b2c3d4","ts":"2026-01-19T09:30:00Z"}
```

---

#### done - 正常结束

```json
data: {"type":"done","request_id":"a1b2c3d4","items_found":5,"pages_processed":3}
```

---

#### error - 异常结束

```json
data: {"type":"error","request_id":"a1b2c3d4","message":"timeout"}
```

发送后立即断开连接。

---

### 非 SSE 响应

以下情况直接返回 JSON，不会有 SSE 流：

| 状态码 | 场景 | 响应示例 |
|-------|------|---------|
| 400 | 参数校验失败 | `{"detail": [{"loc":["body","date_start"],"msg":"...","type":"..."}]}` |
| 400 | category 不存在 | `{"detail": "未知 category: xxx"}` |
| 429 | Worker 繁忙 | `{"detail": "Worker busy"}` |
| 429 | browser-use 日预算已达上限 | `{"detail": "Daily browser-use budget exceeded: spent=$50.3456, limit=$50.00"}` |

---

## 使用示例

### curl

```bash
curl -N -X POST http://localhost:8000/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "site": {"name": "测试网站", "url": "https://example.com", "login_required": false},
    "date_start": "2026-01-08",
    "date_end": "2026-01-09",
    "category": "fuwu"
  }'
```

### Python

```python
import requests

url = "http://localhost:8000/crawl"
payload = {
    "site": {"name": "测试网站", "url": "https://example.com", "login_required": False},
    "date_start": "2026-01-08",
    "date_end": "2026-01-09",
    "category": "fuwu"
}

with requests.post(url, json=payload, stream=True) as r:
    for line in r.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                data = json.loads(line[6:])
                print(data)
                if data['type'] in ('done', 'error'):
                    break
```

---

## 备注

- **并发控制**：每个内部 Worker 同时只处理一个爬取任务；生产环境通常由外层 Nginx/网关将 `/crawl` 分发到不同 uvicorn Worker，全部忙时仍返回 429
- **日预算熔断（browser-use）**：按天累计导航/规划阶段的 LLM 调用成本；达到阈值后新 `/crawl` 直接 429，进行中的任务也可能在下一次 LLM 调用前中止并通过 SSE `type=error` 返回（并发下可能略微超额）
  - 默认阈值：50 USD（可用 `BROWSER_USE_DAILY_BUDGET_USD` 调整）
  - 状态存储：`output/browser_use_budget.sqlite`（可用 `BROWSER_USE_BUDGET_DB_PATH` 调整；按 `BROWSER_USE_BUDGET_TZ` 分日，默认 Asia/Shanghai）
  - 计费：使用本地价格表 `pricing/token_cost_pricing.json`（可用 `BROWSER_USE_PRICING_DATA_PATH` 覆盖）；usage 缺失按 0 计
  - 告警（可选）：配置飞书群机器人 Webhook 后，达到阈值会在群里发送一次告警（同一天只发一次）
    - `FEISHU_BUDGET_ALERT_WEBHOOK_URL`：机器人 webhook 地址
    - `FEISHU_BUDGET_ALERT_WEBHOOK_SECRET`：可选，安全密钥（签名）
    - `FEISHU_BUDGET_ALERT_AT_ALL`：可选，是否 @所有人（true/1 开启）
- **三一正式环境启动通知**：当 `environment=sany_official` 时，统一由 `deploy/entrypoint.sh` 在容器启动阶段发送一次“启动通知”（webhook 写死在代码中）；与 `SERVER_MODE` 无关
- **结束判断**：收到 `type=done` 或 `type=error` 即结束；若未收到就断开则视为失败/取消
- **超时**：默认 1200s，超时后发送 `type=error` 并断开
- **心跳**：30s 无任何输出才发送，用于保持连接

---

## POST /embedding

将输入文本向量化并返回 embedding 向量。

### 请求

**Content-Type**: `application/json`

```json
{
  "text": "公告名称",
  "model": "Qwen/Qwen3-Embedding-8B",
  "dimension": 2048
}
```


说明：
- `model` 可选；不传会根据 `trans.py` 的 `ROUTE` 选择默认模型：
  - `ROUTE="sany"`：默认 `text-embedding-v4`（三一网关 Ali embeddings）
  - 其他（`official`/`openai`）：默认 `Qwen/Qwen3-Embedding-8B`（硅基流动）
- `dimension` 可选，默认 `2048`；服务端会尽量透传到上游 `dimensions` 参数，若上游不支持则回退并对向量进行截断/补零以保证维度一致
- 兼容要务后端：当 `ROUTE!="sany"` 且传入 `model="text-embedding-v4"` 时，会自动映射为 `Qwen/Qwen3-Embedding-8B`
- 需在服务端配置环境变量（按路由选择其一）：
  - `ROUTE="official"`/`"openai"`：`SILICONFLOW_API_KEY`，可选 `SILICONFLOW_BASE_URL`/`SILICONFLOW_EMBEDDING_MODEL`/`SILICONFLOW_EMBEDDING_DIMENSIONS`/`SILICONFLOW_EMBEDDING_ENCODING_FORMAT`
  - `ROUTE="sany"`：`SANY_AI_GATEWAY_KEY`、`SANY_AI_GATEWAY_BASE_URL`，可选 `SANY_EMBEDDING_MODEL`/`SANY_EMBEDDING_DIMENSIONS`/`SANY_EMBEDDING_ENCODING_FORMAT`
- 路由行为：
  - `ROUTE="official"`/`"openai"`：服务端调用 `SiliconFlow` 的 OpenAI 协议 embeddings（`{SILICONFLOW_BASE_URL}/embeddings`）
  - `ROUTE="sany"`：服务端调用三一网关 embeddings（`{SANY_AI_GATEWAY_BASE_URL}/ai-api/ali/embeddings`，OpenAI 协议：`base_url` 设为 `{SANY_AI_GATEWAY_BASE_URL}/ai-api/ali`）

### 响应（200）

```json
{
  "model": "Qwen/Qwen3-Embedding-8B",
  "embedding": [0.123, -0.456, 0.789]
}
```

### 调用示例

```bash
# 调用本服务（不关心后端走 official 还是 sany）
curl -X POST http://localhost:8000/embedding \
  -H "Content-Type: application/json" \
  -d '{"text":"中交三航三公司集采中心采购（安全带）","model":null}'
```

在某些终端/控制台不支持多行粘贴时，推荐使用“一行 JSON”的写法（最稳定）：

```bash
curl -v --max-time 15 -X POST 'http://localhost:80/embedding' -H 'Content-Type: application/json' --data-binary '{"text":"液压挖掘机采购招标公告"}'
```

如果遇到返回 `{"detail":"There was an error parsing the body"}`，可改用纯文本 body（本服务支持 `text/plain` 兜底）：

```bash
curl -X POST http://localhost:8000/embedding \
  -H "Content-Type: text/plain; charset=utf-8" \
  --data-binary "液压挖掘机采购招标公告"
```

---

## POST /content_to_md

将后端传入的 **已清洗** `announcementContent` 转换为结构清晰的 Markdown 文本（由 DeepSeek 生成）。

### 请求

**Content-Type**: `application/json`

```json
{
  "announcementContent": "<div>...</div>"
}
```

说明：
- 也支持 `text/plain`：直接把 body 当作 `announcementContent`
- 路由：同字段抽取一样由 `trans.py` 的 `ROUTE` 控制（`official`/`sany`）

### 响应（200）

```json
{
  "markdown": "# 标题\n\n..."
}
```

---

## POST /normalize_item

将任意来源（第三方 API / Excel 导入等）的文本映射为本项目的 **统一 item 模板**（由 DeepSeek 生成）。

推荐将 `sourceJson` 组织为“中文标签的结构化 Markdown 文本”（使用 `###` 小节标题承载字段名），便于模型稳定提取。

### 请求

**Content-Type**: `application/json`

```json
{
  "sourceJson": "### 标题\n...\n\n### 正文\n...\n\n### 发布时间\n2026-02-16\n",
  "productCategoryTable": "挖机、液压挖掘机\n汽车起重机、越野起重机"
}
```

说明：
- `sourceJson` 是其它来源数据的文本（推荐：中文标签 Markdown 文本；服务端按“纯文本”处理，不要求是合法 JSON）
- `productCategoryTable` 可选：具体产品匹配表（raw string）。存在时覆盖默认“具体产品表”，注入到 lotProducts.productCategory 的匹配提示词中；不传则使用内置表。
- 路由：同字段抽取一样由 `trans.py` 的 `ROUTE` 控制（`official`/`sany`）

### 响应（200）

```json
{
  "data": {
    "dataId": "....",
    "announcementUrl": "",
    "announcementName": "",
    "announcementContent": "",
    "projectName": "",
    "projectId": "",
    "announcementDate": "",
    "bidOpenDate": "",
    "budgetAmount": null,
    "winnerAmount": null,
    "estimatedAmount": "",
    "buyerCountry": "中国",
    "buyerProvince": "",
    "buyerCity": "",
    "buyerDistrict": "",
    "buyerAddressDetail": "",
    "projectCountry": "中国",
    "projectProvince": "",
    "projectCity": "",
    "projectDistrict": "",
    "projectAddressDetail": "",
    "deliveryCountry": "中国",
    "deliveryProvince": "",
    "deliveryCity": "",
    "deliveryDistrict": "",
    "deliveryAddressDetail": "",
    "buyerName": "",
    "buyerContact": "",
    "buyerPhone": "",
    "buyerEmail": "",
    "agency": "",
    "announcementType": "招标",
    "isEquipment": true,
    "lotProducts": [],
    "lotCandidates": []
  }
}
```

### 响应（422）

当公告类别 `announcementType` 无法归一化到 13 选 1 的枚举范围内时，服务会调用模型进行最多 3 次“类型修复/归一化”。如果达到上限仍失败，为避免输出错误类型污染下游，将返回 422。

```json
{
  "detail": {
    "message": "announcementType invalid after 3 attempts",
    "rawType": "公开招标",
    "maxRetries": 3
  }
}
```

---

## POST /parent_org_name

根据输入的公司/组织名称，先识别其“所属公司”，再联网搜索并判断其“最接近上级”组织。

### 请求

**Content-Type**: `application/json`

```json
{
  "orgName": "中国化学工程第三建设有限公司山东分公司"
}
```

说明：
- `affiliateOrgName` 是前置节点识别出的“所属公司”名称：
  - `xxx公司采购部` → `xxx公司`
  - `xxx公司` → `xxx公司`
  - `xxx公司山东分公司` / `xxx有限公司北京办事处` → 保留完整名称
  - 无法稳定识别时回退为原始输入
- `parentOrgName` 直接返回模型原始输出；服务端不做 trim，也不会因为与输入相同而清空。
- `confidence` 为 `0~1` 浮点数。
- `sources` 来自服务端本地调用博查 Web Search API 的真实搜索结果，并按模型返回的 `sourceUrls` 做校验和映射，不是模型自由编造的来源。
- 如果模型返回的 `sourceUrls` 与服务端实际搜索结果一个都匹配不上，接口不再报 502，而是返回占位值：`[{"title":"匹配失败","url":"匹配失败"}]`。
- 内部实现分两步：
  1. 先用一个不联网的 LLM 节点识别 `affiliateOrgName`
  2. 再由服务端接入博查搜索，并通过 `chat/completions` + 自定义 function tool `bocha_web_search` 让模型判断最近上级组织
- 路由选择：
  - `ROUTE="openai"`：使用 `OPENAI_BASE_URL` + `OPENAI_API_KEY` + `OPENAI_MODEL`（若配置了 `OPENAI_PARENT_ORG_MODEL` 则优先使用它）。
  - `ROUTE="sany"`：使用 `SANY_AI_GATEWAY_BASE_URL` + `SANY_AI_GATEWAY_KEY`，模型优先取 `SANY_PARENT_ORG_MODEL`，否则回退到 `SANY_EXTRACT_MODEL`，并自动注入 `X-ai-server`。
  - `ROUTE="official"`：当前不支持该接口，会返回 500。
- 该接口依赖环境变量 `BOCHA_API_KEY`，服务端会调用 `POST https://api.bochaai.com/v1/web-search`。

### 响应 200

```json
{
  "affiliateOrgName": "中国化学工程第三建设有限公司山东分公司",
  "parentOrgName": "中国化学工程第三建设有限公司",
  "confidence": 0.82,
  "sources": [
    {
      "title": "中国化学工程第三建设有限公司山东分公司 - 企查查",
      "url": "https://example.com/a"
    },
    {
      "title": "中国化学工程第三建设有限公司",
      "url": "https://example.com/b"
    }
  ]
}
```

### 响应 400

```json
{
  "detail": "1 validation error for ParentOrgNameRequest ..."
}
```

### 响应 500

```json
{
  "detail": "parent_org_name web search is only supported when ROUTE is 'openai' or 'sany'"
}
```

### 响应 502

```json
{
  "detail": "Upstream parent_org_name error: parent_org_name model did not call bocha_web_search"
}
```
