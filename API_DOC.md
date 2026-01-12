# 商机监测爬虫 API 接口文档

## 接口概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/crawl` | 发起爬取任务（SSE 流式响应） |

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
data: {"type":"start","request_id":"a1b2c3d4","site_name":"安能招投标平台","url":"https://example.com","date_start":"2026-01-01","date_end":"2026-01-31","category":"fuwu"}
```

> ⚠️ 不包含 username/password

---

#### item - 单条数据

每抓取到一条详情页数据立即发送。

```json
data: {"type":"item","request_id":"a1b2c3d4","data":{"title":"xxx招标公告","date":"2026-01-06","detail_url":"https://...","projectname":"...","budget":"..."}}
```

---

#### heartbeat - 心跳

30 秒无任何输出时发送，表示连接仍存活。

```json
data: {"type":"heartbeat","request_id":"a1b2c3d4","ts":1736158200}
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
