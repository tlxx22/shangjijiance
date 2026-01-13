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
configMap.put("BUILD_COMMAND", "uv sync && sed -i \"s/valid_models = \\['bu-latest', 'bu-1-0'\\]/valid_models = ['bu-latest', 'bu-1-0', 'bu-30b-a3b-preview']/g\" \$UV_PROJECT_ENVIRONMENT/lib/python3.11/site-packages/browser_use/llm/browser_use/chat.py && PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright PLAYWRIGHT_BROWSERS_PATH=\$UV_PROJECT_ENVIRONMENT/browsers uv run browser-use install")  // 构建命令
configMap.put("APP_RUN_COMMAND", "sh -c 'echo \"export BROWSER_USE_API_KEY=\\\"bu_nszi-qXtoojLHwRvUl4aGA4FM4aVFITi512ExsdrZ3I\\\"\" >> /etc/profile && echo \"export PLAYWRIGHT_BROWSERS_PATH=\$UV_PROJECT_ENVIRONMENT/browsers\" >> /etc/profile && BROWSER_USE_API_KEY=\"bu_Knxmi4asdasdmapjAQxKBAvsNGpQyLE_TMrptArfXI\" PLAYWRIGHT_BROWSERS_PATH=\$UV_PROJECT_ENVIRONMENT/browsers exec \$UV_PROJECT_ENVIRONMENT/bin/gunicorn -c gunicorn.conf.py app:app'")  // 程序启动命令
configMap.put("DOCKERFILE_BASE_IMAGE", "yaowu-registry-vpc.cn-shanghai.cr.aliyuncs.com/pulic/crawler-agent-base:stable")  // 爬虫基础镜像

hello(configMap)
