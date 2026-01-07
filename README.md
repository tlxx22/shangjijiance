# 商机监测智能体

基于browser-use的AI驱动招投标信息自动监测系统。自动访问多个招投标网站，智能筛选符合条件的招标信息，并完整截图保存。

## 功能特点

- ✅ **AI智能筛选**：使用LLM理解页面内容，无需编写CSS选择器
- ✅ **自动登录**：智能检测并自动处理登录流程
- ✅ **完整截图**：混合方案（CDP原生 + 拼接降级）确保完整页面截图
- ✅ **多网站支持**：通过简单配置支持任意数量的招标网站
- ✅ **Cookie持久化**：自动保存登录状态，无需重复登录
- ✅ **智能容错**：重试机制、降级策略，最大化成功率

## 系统要求

- Python >= 3.11
- Windows / Linux / macOS
- 网络连接
- BROWSER_USE_API_KEY（通过.env文件配置）

## 快速开始

### 1. 安装依赖

```bash
# 安装Python依赖
pip install -r requirements.txt

# 安装browser-use的浏览器
uvx browser-use install
```

### 2. 配置API密钥

在项目根目录已有 `.env` 文件模板，请编辑它并填入您的API密钥：

```env
BROWSER_USE_API_KEY=your_api_key_here
```

**注意**：请将 `your_api_key_here` 替换为您的实际browser-use API密钥。`.env` 文件已添加到 `.gitignore`，不会被提交到版本控制系统。

### 3. 配置网站

编辑 `sites_config.yaml`，添加要监控的招标网站：

```yaml
websites:
  - name: "天津采购网"
    url: "https://example.com/tender/list"
    login_required: true
    username: "your_username"
    password: "your_password"

  - name: "北京招投标"
    url: "https://example2.com/list"
    login_required: false
```

### 4. 配置筛选条件

编辑 `prompt.txt`，设置您的筛选条件：

```
关键领域：建筑相关
时间范围：近两天内发布
```

### 5. 运行程序

```bash
python main.py
```

## 配置说明

### sites_config.yaml

| 字段 | 必填 | 说明 |
|------|------|------|
| name | 是 | 网站名称（用于日志和输出目录） |
| url | 是 | 招标列表页URL（不是首页！） |
| login_required | 是 | 是否需要登录（true/false） |
| username | 条件 | 用户名（login_required为true时必填） |
| password | 条件 | 密码（login_required为true时必填） |

### prompt.txt

详细描述您的筛选条件，包括：
- 关键领域（如"建筑"、"IT设备"等）
- 时间范围
- 包含哪些类型
- 排除哪些类型

示例见 [prompt.txt](prompt.txt)

## 输出结构

```
output/
└── 2025-12-18/                    # 按日期组织
    ├── 天津采购网/
    │   ├── 项目A_2025-12-18.png   # 详情页完整截图
    │   ├── 项目A_2025-12-18.json  # 元数据
    │   ├── 项目B_2025-12-18.png
    │   └── 项目B_2025-12-18.json
    ├── 北京招投标/
    │   └── ...
    ├── summary.json                # 汇总报告
    └── run_log.txt                 # 执行日志
```

### JSON元数据格式

```json
{
  "title": "招标标题",
  "date": "2025-12-18",
  "screenshot_path": "项目A_2025-12-18.png",
  "captured_at": "2025-12-18 14:30:25",
  "source_website": "天津采购网",
  "detail_url": "https://..."
}
```

### summary.json格式

```json
{
  "date": "2025-12-18",
  "summary": {
    "total_websites": 20,
    "successful": 15,
    "failed": 5,
    "total_items_found": 127
  },
  "by_website": [
    {
      "name": "天津采购网",
      "status": "success",
      "items_found": 23,
      "pages_processed": 5
    },
    ...
  ]
}
```

## 高级配置

### 修改最大页数

编辑 `src/config_manager.py` 中的默认值：

```python
max_pages: int = 5  # 改为你需要的数字
```

### 修改重试次数

```python
max_retries: int = 3  # 改为你需要的数字
```

### 无头模式（headless）

编辑 `src/site_processor.py`：

```python
browser = Browser(
    headless=True,  # 改为True则不显示浏览器窗口
)
```

## 故障排查

### 1. 登录失败

**问题**：网站需要登录但自动登录失败

**解决方案**：
1. 检查 sites_config.yaml 中的账号密码是否正确
2. 第一次运行时手动登录一次，Cookie会自动保存
3. 如果网站有复杂验证码，考虑使用 `login_required: false`

### 2. 找不到匹配条目

**问题**：运行完成但没有找到任何匹配

**解决方案**：
1. 检查 prompt.txt 中的筛选条件是否过于严格
2. 检查网站列表页URL是否正确
3. 查看 `output/YYYY-MM-DD/run_log.txt` 日志了解详情

### 3. 截图失败

**问题**：程序报告"截图失败"

**解决方案**：
1. 检查网络连接
2. 查看日志确认是CDP失败还是拼接失败
3. 尝试增加页面加载等待时间

### 4. 浏览器崩溃

**问题**：浏览器频繁崩溃或无响应

**解决方案**：
1. 检查系统内存是否充足
2. 减少 `max_pages` 数值
3. 使用无头模式（headless=True）

## 项目结构

```
shangjijiance/
├── src/
│   ├── __init__.py
│   ├── logger_config.py        # 日志配置
│   ├── config_manager.py       # 配置管理
│   ├── custom_tools.py         # 自定义工具（截图等）
│   ├── login_handler.py        # 登录处理
│   ├── list_processor.py       # 列表页分析
│   ├── detail_processor.py     # 详情页处理
│   └── site_processor.py       # 网站处理主流程
│
├── main.py                     # 程序入口
├── sites_config.yaml           # 网站配置
├── prompt.txt                  # 筛选条件
├── requirements.txt            # 依赖列表
└── README.md                   # 本文件
```

## 常见问题

**Q: 可以同时处理多个网站吗？**
A: 目前是顺序处理（一次一个网站），保证稳定性。未来版本可能支持并发。

**Q: 支持哪些网站？**
A: 理论上支持所有招投标网站，只需在配置文件中添加URL。

**Q: 如何修改筛选条件？**
A: 编辑 `prompt.txt` 文件，保存后下次运行自动生效。

**Q: 为什么有些网站没有结果？**
A: 可能原因：1) 该网站确实没有符合条件的招标 2) 网站需要登录但未配置 3) 网站有反爬虫限制

**Q: 可以定时自动运行吗？**
A: 程序本身不包含调度功能，建议使用系统定时任务：
- Windows: 任务计划程序
- Linux: crontab
- 云服务: 云函数定时触发器

## 技术栈

- **browser-use**: AI浏览器自动化框架
- **Pydantic**: 数据验证
- **PyYAML**: 配置文件解析
- **Pillow**: 图像处理
- **Rich**: CLI美化

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

## 支持

如有问题，请查看日志文件 `output/YYYY-MM-DD/run_log.txt`
