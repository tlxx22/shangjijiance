#!groovy
library 'sharelib-remake'
def configMap = [:]

// =================General settings==================
configMap.put("SERVICE", "crawler-agent")  // 项目名字
configMap.put("PLATFORMS", "global-platform")  // 平台

// =================Advanced settings=================
// ***************************************************
// -------------------python settings-----------------
configMap.put("BUILD_METHOD", "uv")  // 构建方案：uv
configMap.put("PACKAGE_REGISTRY", "https://nexus3.yaowutech.cn/repository/pipy/simple")  // 依赖包管理服务器地址
configMap.put("BUILD_COMMAND", "uv sync && sed -i \"s/valid_models = \\['bu-latest', 'bu-1-0'\\]/valid_models = ['bu-latest', 'bu-1-0', 'bu-30b-a3b-preview']/g\" \$UV_PROJECT_ENVIRONMENT/lib/python3.11/site-packages/browser_use/llm/browser_use/chat.py")  // 构建命令
configMap.put("APP_RUN_COMMAND", "sh -c 'mkdir -p /root/.cache/ms-playwright && ln -sf /mnt/.devops_uv_cache/venv/browsers/* /root/.cache/ms-playwright/ && [ -d /root/.cache/ms-playwright/chromium-1200/chrome-linux64 ] && ln -sf /root/.cache/ms-playwright/chromium-1200/chrome-linux64 /root/.cache/ms-playwright/chromium-1200/chrome-linux; exec /mnt/.devops_uv_cache/venv/bin/gunicorn -c gunicorn.conf.py app:app'")  // 程序启动命令
configMap.put("DOCKERFILE_BASE_IMAGE", "yaowu-registry-vpc.cn-shanghai.cr.aliyuncs.com/pulic/crawler-agent-base:stable")  // 爬虫基础镜像

hello(configMap)
