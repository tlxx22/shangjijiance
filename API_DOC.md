# 商机监测爬虫 API 接口文档

## 接口概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/crawl` | 发起爬取任务（SSE 流式响应） |
| POST | `/embedding` | 文本向量化（返回 embedding 向量） |

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
data: {"type":"item","request_id":"a1b2c3d4","data":{"dataId":"<sha256>","announcementUrl":"https://example.com/detail/123","announcementName":"某某项目招标公告","announcementContent":"<div>（此处为详情页正文原始 HTML，包含表格结构等）</div>","projectName":"某某项目","projectId":"CEZB250209959","announcementDate":"2026-01-19","bidOpenDate":"2026-01-26","budgetAmount":500.0,"estimatedAmount":"400.00~600.00","buyerCountry":"中国","buyerProvince":"北京市","buyerCity":"北京市","buyerDistrict":"朝阳区","buyerAddressDetail":"中国北京市朝阳区XX路1号","projectCountry":"中国","projectProvince":"内蒙古自治区","projectCity":"鄂尔多斯市","projectDistrict":"","projectAddressDetail":"内蒙古自治区鄂尔多斯市XX矿区","deliveryCountry":"中国","deliveryProvince":"内蒙古自治区","deliveryCity":"鄂尔多斯市","deliveryDistrict":"","deliveryAddressDetail":"内蒙古自治区鄂尔多斯市XX煤矿","buyerName":"国能（北京）跨境电商有限公司","buyerContact":"张三","buyerPhone":"010-12345678","agency":"国家能源集团国际工程咨询有限公司","announcementType":"招标","lotProducts":[{"lotNumber":"标段一","lotName":"三山岛金矿","subjects":"液压挖掘机","productCategory":"挖机","models":"XE490DK","unitPrices":"280.00","quantities":"2"}],"lotCandidates":[{"lotNumber":"标段一","lotName":"三山岛金矿","type":"中标候选人","candidates":"A公司","candidatePrices":"97.00"}]}}
```

说明：
- `dataId` 为单条数据的稳定唯一标识（基于字段内容计算的 SHA256），可用于同站点去重
- `announcementContent` 为详情页正文原始内容（HTML 字符串），不做 Markdown 转换，包含表格结构等
- `budgetAmount` 单位为“万元”，保留两位小数；取不到填 `null`
- `lotCandidates[].candidatePrices` 单位为“万元”，两位小数；取不到填 `""`
- `estimatedAmount` 格式为 `"下限~上限"`（万元，两位小数）；取不到填 `""`
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

- **并发控制**：每个 Worker 同时只处理一个爬取任务，超出时返回 429
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
  "model": "Qwen/Qwen3-Embedding-8B"
}
```


说明：
- `model` 可选；不传会根据 `trans.py` 的 `ROUTE` 选择默认模型：
  - `ROUTE="official"`：默认 `Qwen/Qwen3-Embedding-8B`（硅基流动）
  - `ROUTE="sany"`：默认 `text-embedding-v4`（三一网关 Ali embeddings）
- embedding 向量维度：默认返回 **1024 维**（不论 `official` 还是 `sany` 路由）。
- 需在服务端配置环境变量（按路由选择其一）：
  - `ROUTE="official"`：`SILICONFLOW_API_KEY`，可选 `SILICONFLOW_BASE_URL`/`SILICONFLOW_EMBEDDING_MODEL`/`SILICONFLOW_EMBEDDING_DIMENSIONS`/`SILICONFLOW_EMBEDDING_ENCODING_FORMAT`
  - `ROUTE="sany"`：`SANY_AI_GATEWAY_KEY`、`SANY_AI_GATEWAY_BASE_URL`，可选 `SANY_EMBEDDING_MODEL`/`SANY_EMBEDDING_DIMENSIONS`/`SANY_EMBEDDING_ENCODING_FORMAT`
- 路由行为：
  - `ROUTE="official"`：服务端调用 `SiliconFlow` 的 OpenAI 协议 embeddings（`{SILICONFLOW_BASE_URL}/embeddings`）
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
