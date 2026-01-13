#!groovy
library 'sharelib-remake'
def configMap = [:]

// =================General settings==================
configMap.put("SERVICE", "shangjijiance-crawler")  // 项目名字
configMap.put("PLATFORMS", "global-platform")  // 平台

// =================Advanced settings=================
// ***************************************************
// -------------------python settings-----------------
configMap.put("BUILD_METHOD", "pip")  // 构建方案：pip
configMap.put("PACKAGE_REGISTRY", "https://nexus3.yaowutech.cn/repository/pipy/simple")  // 依赖包管理服务器地址
configMap.put("BUILD_COMMAND", "pip install -r requirements.txt && playwright install chromium")  // 构建命令：安装依赖 + Playwright Chromium
configMap.put("APP_RUN_COMMAND", "gunicorn -c gunicorn.conf.py app:app")  // 程序启动命令
configMap.put("DOCKERFILE_BASE_IMAGE", "yaowu-registry-vpc.cn-shanghai.cr.aliyuncs.com/pulic/python:3.11-slim")  // python镜像版本

hello(configMap)
