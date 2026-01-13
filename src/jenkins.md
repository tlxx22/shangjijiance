devops jenkin 发布流水线使用说明

 使用场景 

本公司在持续集成（CI）流程中采用了Jenkins作为核心工具。当您的项目需要通过流水线实现自动化部署时，可以利用这一平台来完成相关任务。

 使用方法 

在您的项目的根目录下，请创建一个名为“Jenkinsfile”的文件（注意，该文件名的首字母“J”应为大写）。接下来，您可以通过定义不同的构建参数来编写此Jenkinsfile，从而指导流水线按照指定配置对您的项目执行构建过程。

针对环境发布，您需要为项目分别创建四个环境分支：开发（dev）、测试（test）、预发布（pre）和生产（prod）。每个分支对应于软件开发生命周期中的不同阶段。一旦在特定分支上提交代码变更，持续集成/持续部署（CI/CD）流水线将自动触发，并将该分支的最新代码部署至相应的环境中。这种方法确保了从开发到生产的整个过程既高效又可靠。

 配置说明 

在Jenkinsfile中定义了两类参数：[通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV)与[构建参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#CkRZ7)。[通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV)指的是那些无论采用何种构建策略，其配置方式保持一致的参数；而[构建参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#CkRZ7)则根据所选择的具体构建方法的不同而有所变化。

 通用参数 

| 参数                  | 必须 | 默认值     | 说明                                                         |
| --------------------- | ---- | ---------- | ------------------------------------------------------------ |
| SERVICE               | 是   | 无         | 应用名称，如：h-oms、g-server                                |
| PLATFORMS             | 是   | 无         | 平台名称，可选参数： g-platform：中国大陆项目部署 global-platform：国际项目部署 volcengine-shanghai：火山引擎上海区部署 可同时配置多个，中间用空格隔开，完整配置： configMap.put("PLATFORMS", "g-platform global-platform") |
| DEVOPS_K8S_CONTROLLER | 否   | deployment | 在Kubernetes中部署应用程序时，您可以选择使用不同的控制器类型。请指定您希望采用的控制器种类。可选值包括： deployment：无状态 statefulSet：有状态 job：部署一次性执行任务 cronjob：部署定期执行任务 |

 构建参数 

根据不同构建场景，流水线支持特定的构建参数。请点击相应的方法名以快速访问相关配置。

[Java（maven）](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Cxf6R)

[Java（GraalVM）](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#mM7Nd)

[npm/yarn](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#UbJqI)

[python（pip）](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#e13Es)

[python（uv）](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#uSDTi)

[仅复制](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#YfseS)

 Java（maven） 

 示例 



在示例中，部分非必需参数未被列出。请根据您的实际需求，并参考以下参数说明自行添加相应的参数。

 参数说明 

在Jenkins Pipeline的上下文中，参数的引用遵循特定的语法规范。具体而言，采用configMap.put("<参数名>", "<参数值>")的形式来添加或更新配置映射中的条目，其中<参数名>应当全部使用大写字母表示。此外，若需引用先前已定义的参数值，则应采取${configMap.<参数名>}这样的格式。 值得注意的是，在Jenkinsfile中定义这些参数时，无需顾虑它们声明的具体顺序；当流水线实际执行过程中，系统将自动解析并应用这些参数。如果存在同名参数的情况，则最后被设定的那个值将作为最终有效值参与计算和处理。

| 参数                             | 必须 | 默认值                                                       | 说明                                                         |
| -------------------------------- | ---- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| COMPILED_TARGET_PATH             | 是   | 无                                                           | 编译后生成的JAR文件应存放于以项目根目录为基准的指定路径下，该路径描述时不应以斜杠("/")作为起始字符。 |
| BUILD_COMMAND                    | 是   | 无                                                           | 编译指令应通过"&&"操作符进行串联，采用Bash Shell语法编写。   |
| BUILD_METHOD                     | 是   | 无                                                           | 构建方案。这里可选的参数是： maven：适用于Java8运行环境的项目，maven版本为：3.5.3 maven-388：适用于Java17运行环境的项目，maven版本为：3.8.8 |
| DOCKERFILE_BASE_IMAGE            | 是   | 无                                                           | 在运行应用程序时，所需的底层镜像包括但不限于JDK和Node.js等。需要注意的是，如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| BUILD_ENV                        | 否   | 当前发布的分支名                                             | 应用部署的环境。此参数可指定发布的分支部署至指定的环境上     |
| DEPLOY_API_COMMAND               | 否   | 关闭                                                         | [开启编译时maven项目API自动打包上传功能](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/fqrut3of6baz88o9) |
| DEVOPS_TEST_REPORT_HISTORY_LIMIT | 否   | 3                                                            | 该参数的有效范围为[1,5]，用于设定覆盖率报告的历史记录数量。系统默认配置保留最近的三份历史报告。若调整此参数值，可能会导致部分历史记录被删除。特别是当新设置的数值小于现有配置时，系统将即刻按照新的配置值对历史报告数量进行调整，从而可能导致部分旧报告丢失。详情请查看[覆盖路报告使用说明](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/vz0m2xu13itf98ue)文档 |
| APP_RUN_COMMAND                  | 否   | java \${JAVA_OPTS} -Djava.security.egd=file:/dev/./urandom  -jar *.jar | 自定义 JAVA 程序启动命令。若使用环境变量，需要转义$符，如: \${JAVA_OPTS}。如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| DEVOPS_K8S_CRONJOB_SCHEDULE      | 否   | 无                                                           | 当在 [通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV) 中DEVOPS_K8S_CONTROLLER的值设置为cronjob时，必须填写此参数。该参数用于指定CronJob的定期执行时间，并且其格式应遵循Crontab标准： |

 Java（GraalVM） 

 示例 



在示例中，部分非必需参数未被列出。请根据您的实际需求，并参考以下参数说明自行添加相应的参数。

 参数说明 

在Jenkins Pipeline的上下文中，参数的引用遵循特定的语法规范。具体而言，采用configMap.put("<参数名>", "<参数值>")的形式来添加或更新配置映射中的条目，其中<参数名>应当全部使用大写字母表示。此外，若需引用先前已定义的参数值，则应采取${configMap.<参数名>}这样的格式。 值得注意的是，在Jenkinsfile中定义这些参数时，无需顾虑它们声明的具体顺序；当流水线实际执行过程中，系统将自动解析并应用这些参数。如果存在同名参数的情况，则最后被设定的那个值将作为最终有效值参与计算和处理。

| 参数                             | 必须 | 默认值              | 说明                                                         |
| -------------------------------- | ---- | ------------------- | ------------------------------------------------------------ |
| COMPILED_TARGET_PATH             | 是   | 无                  | 编译后生成的二进制文件应存放于以项目根目录为基准的指定路径下，该路径描述时不应以斜杠("/")作为起始字符。 |
| BUILD_COMMAND                    | 是   | 无                  | 编译指令应通过"&&"操作符进行串联，采用Bash Shell语法编写。   |
| BUILD_METHOD                     | 是   | 无                  | 构建方案。这里可选的参数是：maven-graalvm                    |
| DOCKERFILE_BASE_IMAGE            | 是   | 无                  | 在运行应用程序时，所需的底层镜像包括但不限于JDK和Node.js等。需要注意的是，如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| BUILD_ENV                        | 否   | 当前发布的分支名    | 应用部署的环境。此参数可指定发布的分支部署至指定的环境上     |
| DEPLOY_API_COMMAND               | 否   | 关闭                | [开启编译时maven项目API自动打包上传功能](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/fqrut3of6baz88o9) |
| DEVOPS_TEST_REPORT_HISTORY_LIMIT | 否   | 3                   | 该参数的有效范围为[1,5]，用于设定覆盖率报告的历史记录数量。系统默认配置保留最近的三份历史报告。若调整此参数值，可能会导致部分历史记录被删除。特别是当新设置的数值小于现有配置时，系统将即刻按照新的配置值对历史报告数量进行调整，从而可能导致部分旧报告丢失。详情请查看[覆盖路报告使用说明](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/vz0m2xu13itf98ue)文档 |
| APP_RUN_COMMAND                  | 否   | ./app \${JAVA_OPTS} | 自定义 JAVA 程序启动命令。若使用环境变量，需要转义$符，如: \${JAVA_OPTS}。如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| DEVOPS_K8S_CRONJOB_SCHEDULE      | 否   | 无                  | 当在 [通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV) 中DEVOPS_K8S_CONTROLLER的值设置为cronjob时，必须填写此参数。该参数用于指定CronJob的定期执行时间，并且其格式应遵循Crontab标准： |

使用 GraalVM 项目中的 native-image 工具将java项目编译成二进制执行文件。
此构建方式有以下几点使用限制：
●应用jdk版本需升级至jdk17及以上
●springBoot建议升级至3版本及以上。Spring Boot 3 对 GraalVM Native Image 的内置支持可以轻松地将 Spring Boot 3 应用程序编译为本机可执行文件
●目前此功能仅支持通过[maven插件](https://github.com/graalvm/graalvm-demos/tree/master/spring-native-image#default-native-build-configuration)实现，详情可查阅[官方说明](https://github.com/graalvm/graalvm-demos/tree/master/spring-native-image#native-executable)

 NPM/YARN 

 示例 



在示例中，部分非必需参数未被列出。请根据您的实际需求，并参考以下参数说明自行添加相应的参数。

 参数说明 

在Jenkins Pipeline的上下文中，参数的引用遵循特定的语法规范。具体而言，采用configMap.put("<参数名>", "<参数值>")的形式来添加或更新配置映射中的条目，其中<参数名>应当全部使用大写字母表示。此外，若需引用先前已定义的参数值，则应采取${configMap.<参数名>}这样的格式。 值得注意的是，在Jenkinsfile中定义这些参数时，无需顾虑它们声明的具体顺序；当流水线实际执行过程中，系统将自动解析并应用这些参数。如果存在同名参数的情况，则最后被设定的那个值将作为最终有效值参与计算和处理。

| 参数                        | 必须 | 默认值           | 说明                                                         |
| --------------------------- | ---- | ---------------- | ------------------------------------------------------------ |
| NODE_VERSION                | 是   | 无               | 使用Nodejs的版本。容器内部会使用n命令进行切换                |
| BUILD_COMMAND               | 是   | 无               | 编译指令应通过"&&"操作符进行串联，采用Bash Shell语法编写。   |
| PACKAGE_REGISTRY            | 是   | 无               | 依赖包管理服务器的地址通常配置为我司Nexus私有仓库的地址。若项目根目录中存在.npmrc文件，则此参数将不会生效。此外，原参数NPM_REGISTRY已被弃用。 |
| COMPILED_TARGET_PATH        | 是   | 无               | 编译后生成的静态文件应存放于以项目根目录为基准的指定路径下，该路径描述时不应以斜杠("/")作为起始字符。 |
| DOCKERFILE_BASE_IMAGE       | 是   | 无               | 在运行应用程序时，所需的底层镜像包括但不限于JDK和Node.js等。需要注意的是，如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| BUILD_METHOD                | 是   | 无               | 构建方案。这里可选的参数是：npm\|yarn                        |
| BUILD_ENV                   | 否   | 当前发布的分支名 | 应用部署的环境。此参数可指定发布的分支部署至指定的环境上     |
| DEVOPS_K8S_CRONJOB_SCHEDULE | 否   | 无               | 当在 [通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV) 中DEVOPS_K8S_CONTROLLER的值设置为cronjob时，必须填写此参数。该参数用于指定CronJob的定期执行时间，并且其格式应遵循Crontab标准： |

 Python（pip） 

 示例 



●默认拉取项目根目录下所有文件，但排除以下文件： venv .venv .vscode .idea .DS_Store __pycache__ .gitignore
●在示例中，部分非必需参数未被列出。请根据您的实际需求，并参考以下参数说明自行添加相应的参数。

 参数说明 

在Jenkins Pipeline的上下文中，参数的引用遵循特定的语法规范。具体而言，采用configMap.put("<参数名>", "<参数值>")的形式来添加或更新配置映射中的条目，其中<参数名>应当全部使用大写字母表示。此外，若需引用先前已定义的参数值，则应采取${configMap.<参数名>}这样的格式。 值得注意的是，在Jenkinsfile中定义这些参数时，无需顾虑它们声明的具体顺序；当流水线实际执行过程中，系统将自动解析并应用这些参数。如果存在同名参数的情况，则最后被设定的那个值将作为最终有效值参与计算和处理。

| 参数                        | 必须 | 默认值           | 说明                                                         |
| --------------------------- | ---- | ---------------- | ------------------------------------------------------------ |
| BUILD_METHOD                | 是   | 无               | 构建方案。这里可选的参数是：pip                              |
| PACKAGE_REGISTRY            | 是   | 无               | 依赖包管理服务器的地址通常配置为我司Nexus私有仓库的地址。如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| BUILD_COMMAND               | 是   | 无               | pip 拉取命令。指令应通过"&&"操作符进行串联，采用Bash Shell语法编写。 |
| APP_RUN_COMMAND             | 是   | 无               | python程序启动命令。如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| DOCKERFILE_BASE_IMAGE       | 是   | 无               | 该值定义了指定Python项目的编译与运行环境。您可以在 [阿里云镜像仓库](https://cr.console.aliyun.com/repository/cn-shanghai/cri-176wr11x9h4xj625/pulic/python/images) 中查阅当前可用的Python版本信息。需要注意的是，如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| DEVOPS_PIP_CACHE            | 否   | true             | 布尔值（true\|false）。该设置用于确定是否启用pip缓存功能。对于同一项目中的同一环境，流水线仅会保留与当前使用的Python版本相匹配的pip包缓存；一旦更改了Python版本，则先前版本相关的pip缓存将被自动清除。此外，如果在项目的源代码根目录下检测到Dockerfile文件的存在，此选项将被强制设为false。 |
| BUILD_ENV                   | 否   | 当前发布的分支名 | 应用部署的环境。此参数可指定发布的分支部署至指定的环境上     |
| DEVOPS_K8S_CRONJOB_SCHEDULE | 否   | 无               | 当在 [通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV) 中DEVOPS_K8S_CONTROLLER的值设置为cronjob时，必须填写此参数。该参数用于指定CronJob的定期执行时间，并且其格式应遵循Crontab标准： |

 Python（uv） 

 示例 



●默认拉取项目根目录下所有文件，但排除以下文件： venv .venv .vscode .idea .DS_Store __pycache__ .gitignore
●在示例中，部分非必需参数未被列出。请根据您的实际需求，并参考以下参数说明自行添加相应的参数。

 参数说明 

在Jenkins Pipeline的上下文中，参数的引用遵循特定的语法规范。具体而言，采用configMap.put("<参数名>", "<参数值>")的形式来添加或更新配置映射中的条目，其中<参数名>应当全部使用大写字母表示。此外，若需引用先前已定义的参数值，则应采取${configMap.<参数名>}这样的格式。 值得注意的是，在Jenkinsfile中定义这些参数时，无需顾虑它们声明的具体顺序；当流水线实际执行过程中，系统将自动解析并应用这些参数。如果存在同名参数的情况，则最后被设定的那个值将作为最终有效值参与计算和处理。

| 参数                        | 必须 | 默认值           | 说明                                                         |
| --------------------------- | ---- | ---------------- | ------------------------------------------------------------ |
| BUILD_METHOD                | 是   | 无               | 构建方案。这里可选的参数是：uv                               |
| PACKAGE_REGISTRY            | 是   | 无               | 依赖包管理服务器的地址通常配置为我司Nexus私有仓库的地址。如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| BUILD_COMMAND               | 是   | 无               | uv 拉取命令。指令应通过"&&"操作符进行串联，采用Bash Shell语法编写。Python虚拟环境流水线会自行维护，你无需使用 uv venv 等命令自行创建虚拟环境，否则可能会导致应用编译失败或启动异常 |
| APP_RUN_COMMAND             | 是   | 无               | python程序启动命令。推荐使用 uv run 命令来启动 Python 应用程序。若未采用此方法，可能会由于虚拟环境配置不当而导致无法识别所需的 Python 模块。如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| DOCKERFILE_BASE_IMAGE       | 是   | 无               | 该值定义了指定Python项目的编译与运行环境。UV工具需在特定的镜像环境中运行，您可以在 [阿里云镜像仓库](https://cr.console.aliyun.com/repository/cn-shanghai/cri-176wr11x9h4xj625/pulic/uv/images) 中查阅当前可用的UV及Python版本信息。鉴于UV环境的独特性，目前我们尚无法对Python环境的补丁版本做出具体指定。如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| DEVOPS_UV_CACHE             | 否   | true             | 布尔值（true\|false）。该设置用于确定是否启用uv缓存功能。对于同一项目中的同一环境，流水线仅会保留与当前使用的Python版本相匹配的uv包缓存；一旦更改了Python版本，则先前版本相关的uv缓存将被自动清除。此外，如果在项目的源代码根目录下检测到Dockerfile文件的存在，此选项将被强制设为false。 |
| BUILD_ENV                   | 否   | 当前发布的分支名 | 应用部署的环境。此参数可指定发布的分支部署至指定的环境上     |
| DEVOPS_K8S_CRONJOB_SCHEDULE | 否   | 无               | 当在 [通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV) 中DEVOPS_K8S_CONTROLLER的值设置为cronjob时，必须填写此参数。该参数用于指定CronJob的定期执行时间，并且其格式应遵循Crontab标准： |

 仅复制 

 示例 



●默认拉取项目根目录下所有文件，但排除以下文件： venv .venv .vscode .idea .DS_Store __pycache__ .gitignore
●在示例中，部分非必需参数未被列出。请根据您的实际需求，并参考以下参数说明自行添加相应的参数。

 参数说明 

在Jenkins Pipeline的上下文中，参数的引用遵循特定的语法规范。具体而言，采用configMap.put("<参数名>", "<参数值>")的形式来添加或更新配置映射中的条目，其中<参数名>应当全部使用大写字母表示。此外，若需引用先前已定义的参数值，则应采取${configMap.<参数名>}这样的格式。 值得注意的是，在Jenkinsfile中定义这些参数时，无需顾虑它们声明的具体顺序；当流水线实际执行过程中，系统将自动解析并应用这些参数。如果存在同名参数的情况，则最后被设定的那个值将作为最终有效值参与计算和处理。

| 参数                        | 必须 | 默认值           | 说明                                                         |
| --------------------------- | ---- | ---------------- | ------------------------------------------------------------ |
| BUILD_METHOD                | 是   | 无               | 构建方案。这里可选的参数是：copy-only                        |
| DOCKERFILE_BASE_IMAGE       | 是   | 无               | 在运行应用程序时，所需的底层镜像包括但不限于JDK和Node.js等。需要注意的是，如果项目源代码的根目录中已存在Dockerfile文件，则上述指定的镜像配置将不会生效。建议参考[基于自定义Dockerfile发布](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/sc3xfaow2bgv2xig)以获取更多信息。 |
| APP_RUN_COMMAND             | 否   | 无               | 启动程序命令。对于仅采用复制方式的项目，若需自定义容器运行指令，可通过此参数进行指定。需要注意的是，如果项目源代码的根目录中已存在Dockerfile文件，则通过上述方法配置的镜像设置将不会生效。 |
| DEVOPS_COPY_SRC_PATH        | 否   | 无               | 在以项目根目录为基准的相对路径下指定文件时，若未进行具体配置，则默认会复制所有文件（但排除 venv, .venv, .vscode, .idea, .DS_Store, __pycache__, 以及 .gitignore）。需要注意的是，在描述这些路径时，不应使用斜杠("/")作为起始字符。多个源文件可通过空格分隔列出，例如：configMap.put("DEVOPS_COPY_SRC_PATH", "README.md pom.xml src")。此外，如果项目源代码的根目录中已存在 Dockerfile 文件，则上述定义的镜像配置将不会生效。 |
| DEVOPS_COPY_DEST_PATH       | 否   | 无               | 在指定源文件复制到容器内部的目标位置时，若未进行配置，则默认目标位置为 /home。请注意，您只能指定单一的目标地址。如果指定的目标地址中的文件或文件夹不存在，系统将自动创建所需目录结构。此外，如果项目源代码的根目录中已存在 Dockerfile 文件，则通过上述方式定义的镜像配置将不会生效。 |
| BUILD_ENV                   | 否   | 当前发布的分支名 | 应用部署的环境。此参数可指定发布的分支部署至指定的环境上     |
| DEVOPS_K8S_CRONJOB_SCHEDULE | 否   | 无               | 当在 [通用参数](https://yaowuteam.yuque.com/staff-uoggdg/hm6bxr/wwrtk73goslo1xwp#Y88oV) 中DEVOPS_K8S_CONTROLLER的值设置为cronjob时，必须填写此参数。该参数用于指定CronJob的定期执行时间，并且其格式应遵循Crontab标准： 12345678# 计划任务定义的例子:# .---------------- 分 (0 - 59)# \|  .------------- 时 (0 - 23)# \|  \|  .---------- 日 (1 - 31)# \|  \|  \|  .------- 月 (1 - 12)# \|  \|  \|  \|  .---- 星期 (0 - 7) (星期日可为0或7)# \|  \|  \|  \|  \|# *  *  *  *  * 执行的命令 |



