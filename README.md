# 商机监测爬虫 API

基于 browser-use 的 AI 驱动招投标信息自动监测系统。提供 **SSE 流式 HTTP API**，自动访问招投标网站，智能筛选符合条件的招标信息，并抓取公告原文（Markdown）保存。

## 功能特点

- ✅ **SSE 流式 API**：HTTP 服务实时返回爬取进度和结果
- ✅ **多 Worker 并发**：Gunicorn + FastAPI 支持同时处理多个请求
- ✅ **AI 智能筛选**：使用 LLM 理解页面内容，无需编写 CSS 选择器
- ✅ **自动登录**：智能检测并自动处理登录流程
- ✅ **动态日期范围**：API 传入 date_start/date_end，支持任意时间范围
- ✅ **智能日期识别**：自动区分"发布日期"和"截止日期"筛选

## 系统要求

- Python >= 3.11
- Ubuntu / Linux（生产环境）
- Chrome/Chromium 浏览器
- BROWSER_USE_API_KEY（通过 .env 文件配置）

## 快速开始

### 本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt
playwright install chromium

# 2. 配置 .env
cp .env.example .env
# 编辑填入 BROWSER_USE_API_KEY

# 3. 启动服务（开发模式）
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 生产部署（Jenkins + K8s）

通过 `Jenkinsfile` 自动部署到 K8s：

1. 提交代码到对应分支（dev/test/pre/prod）
2. Jenkins 流水线自动触发
3. 部署到对应环境

## API 使用

详细文档见 [API_DOC.md](API_DOC.md)

### 健康检查

```bash
curl http://localhost:8000/health
```

### 发起爬取请求

```bash
curl -X POST http://localhost:8000/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "site": {
      "name": "某招标网站",
      "url": "https://example.com/tender/list",
      "login_required": false
    },
    "date_start": "2026-01-08",
    "date_end": "2026-01-09",
    "category": "fuwu",
    "max_pages": 3
  }'
```

### SSE 事件类型

| 事件类型 | 说明 |
|---------|------|
| `start` | 开始爬取 |
| `item` | 每条数据实时输出 |
| `heartbeat` | 每 30 秒心跳保活 |
| `done` | 爬取完成 |
| `error` | 出错/超时 |

## 配置说明

### 环境变量

| 变量 | 说明 |
|------|------|
| BROWSER_USE_API_KEY | browser-use API 密钥（必填） |
| BROWSER_USER_AGENT | 可选：统一覆盖浏览器 UA（对 headless/headful 都生效） |

### prompts/ 目录

提示词模板按分类存放，支持占位符：

- `{date_start}` - 开始日期
- `{date_end}` - 结束日期
- `{today}` - 今天日期
- `{site_name}` - 网站名称

### gunicorn.conf.py

Gunicorn 配置文件，关键参数：

- `workers`：Worker 数量（通过环境变量 WORKERS 配置）
- `timeout`：请求超时时间
- `worker_class`：使用 uvicorn.workers.UvicornWorker

## 输出结构

```
output/
└── 2026-01-09/
    └── 网站名称/
        └── 项目A_2026-01-09.json  # 结构化数据（含公告原文 Markdown：announcementContentMd）
```

## 日志

日志统一写入 `logs/app.log`：

- JSON 格式（适合 SLS 采集）
- 按大小轮转（100MB）
- 保留 5 个归档
- 自动注入 request_id

## 常见问题

**Q: 可以同时处理多个网站吗？**
A: 支持并发。每个 Worker 同时处理一个请求。

**Q: 如何添加新的分类？**
A: 在 `prompts/` 目录创建 `分类名.txt` 文件，API 请求时 `category` 填写文件名（不含扩展名）。

**Q: 如何增加 Worker 数量？**
A: 设置环境变量 `WORKERS=10`。

## 技术栈

- **FastAPI** + **Gunicorn**：HTTP API 服务
- **browser-use**：AI 浏览器自动化
- **Loguru**：日志系统
- **SSE**：Server-Sent Events 实时流

## 许可证

MIT License
