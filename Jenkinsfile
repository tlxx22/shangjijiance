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
configMap.put("BUILD_COMMAND", "uv sync && uv run browser-use install")  // 构建命令
configMap.put("APP_RUN_COMMAND", "gunicorn -c gunicorn.conf.py app:app")  // 程序启动命令
configMap.put("DOCKERFILE_BASE_IMAGE", "yaowu-registry-vpc.cn-shanghai.cr.aliyuncs.com/pulic/crawler-agent-base:stable")  // 爬虫基础镜像（含 Chrome + 中文字体）

hello(configMap)
