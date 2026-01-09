# 商机监测智能体 Docker 镜像
# 基于 Python 3.11，手动安装 Playwright 和 Chromium

FROM python:3.11-slim
WORKDIR /app

# 安装 Chromium 运行所需的系统依赖 + 中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxkbcommon0 \
    fonts-liberation \
    fonts-noto-cjk \
    xvfb \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（提供 uvx 命令，browser-use 需要）
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 使用 uvx 预装 Chrome（browser-use 库会查找这个路径）
RUN uvx playwright install chrome

# 复制项目代码
COPY . .

# 暴露端口
EXPOSE 8000

# 使用 gunicorn 启动 FastAPI
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
