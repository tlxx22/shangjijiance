# 商机监测智能体

基于 browser-use 的 AI 驱动招投标信息自动监测系统。提供 **SSE 流式 HTTP API**，自动访问招投标网站，智能筛选符合条件的招标信息，并完整截图保存。

## 功能特点

- ✅ **SSE 流式 API**：HTTP 服务实时返回爬取进度和结果
- ✅ **多 Worker 并发**：Gunicorn + FastAPI 支持同时处理多个请求
- ✅ **AI 智能筛选**：使用 LLM 理解页面内容，无需编写 CSS 选择器
- ✅ **自动登录**：智能检测并自动处理登录流程
- ✅ **完整截图**：支持中文字体渲染，确保截图无乱码
- ✅ **动态日期范围**：API 传入 date_start/date_end，支持任意时间范围
- ✅ **智能日期识别**：自动区分"发布日期"和"截止日期"筛选

## 系统要求

- Python >= 3.11
- Docker（推荐）或 Windows / Linux / macOS
- 网络连接
- BROWSER_USE_API_KEY（通过 .env 文件配置）

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 1. 配置 API 密钥
cp .env.example .env
# 编辑 .env，填入 BROWSER_USE_API_KEY

# 2. 启动服务
docker compose up --build -d

# 3. 查看日志
docker compose logs -f
```

### 方式二：本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt
uvx browser-use install

# 2. 配置 .env
cp .env.example .env
# 编辑填入 BROWSER_USE_API_KEY

# 3. 启动服务
uvicorn app:app --host 0.0.0.0 --port 8000
```

## API 使用

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

### 请求参数

| 字段 | 必填 | 说明 |
|------|------|------|
| site.name | 是 | 网站名称 |
| site.url | 是 | 招标列表页 URL |
| site.login_required | 否 | 是否需要登录（默认 false） |
| site.username | 条件 | 登录用户名 |
| site.password | 条件 | 登录密码 |
| date_start | 是 | 筛选开始日期 |
| date_end | 是 | 筛选结束日期 |
| category | 是 | 分类（对应 prompts/ 目录下的模板） |
| max_pages | 否 | 最大翻页数（默认 3） |
| timeout_seconds | 否 | 超时时间（默认 1800s） |
| headless | 否 | 无头模式（默认 true） |

### 错误码

| 状态码 | 说明 |
|-------|------|
| 200 | 成功（SSE 流） |
| 400 | 参数验证失败 |
| 429 | 当前 Worker 繁忙 |
| 500 | 服务器内部错误 |

## 配置说明

### 环境变量

| 变量 | 说明 |
|------|------|
| BROWSER_USE_API_KEY | browser-use API 密钥（必填） |
| WORKERS | Gunicorn Worker 数量（默认 5） |

### prompts/ 目录

提示词模板按分类存放，支持占位符：

- `{date_start}` - 开始日期
- `{date_end}` - 结束日期
- `{today}` - 今天日期
- `{site_name}` - 网站名称

### docker-compose.yml

关键配置：

- `WORKERS=5`：并发 Worker 数量
- `shm_size: 2g`：Chrome 共享内存
- 代码目录已挂载，改代码只需重启

## 输出结构

```
output/
└── 2026-01-09/
    └── 网站名称/
        ├── 项目A_2026-01-09.png   # 详情页截图
        └── 项目A_2026-01-09.json  # 元数据
```

### JSON 元数据格式

```json
{
  "title": "招标标题",
  "date": "2026-01-09",
  "bidopentime": "2026-01-15",
  "bidamount": "100万元",
  "area": "北京",
  "source_website": "某招标网站",
  "detail_url": "https://..."
}
```

## 运维命令

```bash
# 查看状态
docker compose ps

# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 重新构建
docker compose up --build -d

# 资源监控
docker stats
```

## 常见问题

**Q: 可以同时处理多个网站吗？**
A: 支持并发。每个 Worker 同时处理一个请求，默认 5 个 Worker。

**Q: 截图中文乱码怎么办？**
A: Docker 镜像已包含中文字体，需重新构建：`docker compose up --build`

**Q: Worker 繁忙怎么办？**
A: 增加 Worker 数量：编辑 `docker-compose.yml` 中 `WORKERS=10`，然后重启。

**Q: 如何添加新的分类？**
A: 在 `prompts/` 目录创建 `分类名.txt` 文件，API 请求时 `category` 填写文件名（不含扩展名）。

## 技术栈

- **FastAPI** + **Gunicorn**：HTTP API 服务
- **browser-use**：AI 浏览器自动化
- **Docker**：容器化部署
- **SSE**：Server-Sent Events 实时流

## 许可证

MIT License
