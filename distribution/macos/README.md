# macOS 本地分发构建

此目录构建带 Python、Qt、Veusz 和 Python 运行依赖的 `SciPlot.app`。
双击应用只打开中文连接和使用说明；科研任务继续由外部 AI 驱动现有公开接口。
CLI 和 MCP 的命令是包内 `Contents/MacOS/sciplot`，MCP 参数是 `mcp`。
程序不安装内部模型，不写入 Codex 或其它 AI 工具的配置。

在当前已通过 Doctor 的 macOS 开发环境中构建：

```bash
.venv/bin/python -m distribution.macos.build \
  --out .tmp_verify/macos_distribution/build/SciPlot.app \
  --verify .tmp_verify/macos_distribution/verification --smoke
```

构建器不下载依赖，也不复制整台机器或整个仓库。它读取 `pyproject.toml` 的运行依赖与
`studio` 和 `mcp` extras，并带上 Veusz 使用的 Matplotlib、Setuptools；递归解析当前环境中
已安装的依赖与所选 extras，记录确切版本。复制标准库、应用源码、公开 skill、Veusz
源码、界面资源及依赖许可证，排除 editable `.pth`、缓存、项目和原始实验数据。
Qt 分发范围限定为 Veusz 的 Widgets/SVG/打印栈及其依赖，不带 QML、多媒体模块。
源码在复制前后比较身份，复制期间发生修改会中止构建。包内保留构建工具源码，
移除 editable 安装元数据中的开发机源路径；原始 Python 工具链构建配置仍是历史元数据，
运行时不借此加载外部库，也不将本包作为开发编译环境。

所有非系统 Mach-O 依赖都会复制到包内并改成相对 `@loader_path` 引用（必要时通过包内
短链接，适配没有 linker header padding 的扩展）；Veusz helpers
与 PyQt 使用同一份包内 Qt。构建器拒绝任何缺失依赖、出包链接或残留的非系统绝对库路径，
修改后的二进制使用 ad-hoc 签名。原开发环境和第三方源二进制不改写。
Finder 入口由本机 Clang 编译为一个只转发到包内 CLI 的小型启动程序，构建需要
Apple Command Line Tools；终端用户不需要编译器。
这个版本提供可重复执行的构建过程与版本/源码身份清单，不宣称字节级可重现。

`--out` 必须是尚不存在的 `.app`，不会覆盖用户已放好的应用。验证用新 evidence 目录，
清除继承的 Python/Qt/SciPlot 路径，并把 PATH 限制为系统目录；随后运行 Doctor、原生
窗口 smoke、欢迎页生成、官方 MCP 客户端的 stdio 发现与能力调用，以及显式选择的
现有完整 runtime smoke。验证不调用模型。
构建成功本身不等于验证通过，应查看 `verification.json`。

要验证搬移后的包：

```bash
.venv/bin/python -m distribution.macos.build --verify-existing \
  --out '/新位置/SciPlot.app' --verify .tmp_verify/macos_distribution/moved
```

首次放置应用后双击它；或以 `Contents/MacOS/sciplot --welcome --no-open --out DIR`
生成可审阅的中文说明、环境检查和两种 MCP 配置片段。移动应用后应重新生成配置路径。
欢迎页默认只写入临时目录；不会安装配置、登录账户或调用付费模型。

应用应先放到固定位置再生成科研项目。当前交付包的 `Open_in_Veusz.command` 会记录
生成时的包内 wrapper 作为后备路径；本分发器不安装系统 PATH 命令。应用移动后，
旧交付 launcher 不会自动找到新位置：先更新 AI 的 MCP 连接，再由 AI 继续原受管项目并
重新导出。移动应用与移动科研交付包是两件事；后者仍按既有独立 VSZ 快照合同处理。

验证范围必须分别记录：本机启动与依赖封闭审计、另一台没有 Python/Qt/Homebrew 的干净
Mac、macOS 版本/架构兼容、Developer ID 签名与公证、真实小白任务测试。这里生成的包
没有 Developer ID 签名或公证；ad-hoc 签名不能替代发行身份认证。本机成功不能替代
干净机器或小白验收，也不承诺其它 macOS 版本及 CPU 架构。

技术依据：[Qt 官方部署说明](https://doc.qt.io/qt-6/macos-deployment.html)、
[Python 官方 macOS 说明](https://docs.python.org/3.13/using/mac.html)、
[官方 MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。
