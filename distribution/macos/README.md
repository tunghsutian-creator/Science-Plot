# macOS 本地分发构建

此目录构建带 Python、Qt、Veusz 和 Python 运行依赖的 `SciPlot.app`。
双击应用打开中文连接和使用说明；科研任务继续由外部 AI 驱动现有公开接口。
应用将 `.sciplot` 声明为可编辑的文档类型。关联到本应用的文件走 Qt 文件打开事件。
单图项目直接打开；多图项目在窗口里选图，不会自动打开第一张图。核对后可把坐标轴标题或主刻度写回同一个文件。
普通 XY 图可按曲线 ID 改线色；「文件」菜单可单独导出当前图的 PDF 或 300 dpi TIFF，不改项目原文件。
已知图 ID 时，也可以用 `sciplot plot editor 文件 --figure 图ID` 直接打开对应的图。
CLI 和 MCP 使用包内 `Contents/MacOS/sciplot`；用户按欢迎页生成的连接配置操作。
程序不安装内部模型，不写入 Codex 或其它 AI 工具的配置。

在当前已通过 Doctor 的 macOS 开发环境中构建。把产物和验证输出放在仓库外。准备发行时先只构建，由下面的 release 命令统一验证搬移后的最终包：

```bash
artifact_root=$(mktemp -d "$HOME/SciPlot-release.XXXXXX")
"${SCIPLOT_PYTHON:-.venv/bin/python}" -m distribution.macos.build \
  --out "$artifact_root/SciPlot.app"
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
Finder 入口由本机 Clang 编译为一个在同一进程中启动包内 Qt 文件入口的小型启动程序，构建需要
Apple Command Line Tools；终端用户不需要编译器。
这个版本提供可重复执行的构建过程与版本/源码身份清单，不宣称字节级可重现。

`--out` 必须是尚不存在的 `.app`，不会覆盖用户已放好的应用。验证用新 evidence 目录，
清除继承的 Python/Qt/SciPlot 路径，并把 PATH 限制为系统目录；随后运行 Doctor、生成
欢迎页、运行现有的无界面 Qt 导出 smoke，并用官方 MCP SDK 读取欢迎页生成的连接配置，
实际发现 daily 工具和调用能力接口。默认跑 quick smoke；加 `--smoke` 则改跑完整
runtime smoke，不重复跑 quick。验证不调用模型，也不等于真实 AI 客户端完成用户任务。
构建成功本身不等于验证通过，应查看 `verification.json`。
验证在启动包内代码前检查源文件身份和原生依赖，并在结束后比较应用的完整文件内容、
权限与内部链接。任何检查失败、异常退出或超时都会保留失败报告；退出码为零但 JSON
状态失败同样不能通过。欢迎页提供不含数据、路径、
错误全文或密钥的 `feedback.json`；本地页面下载用内嵌内容，避免浏览器阻止 file 链接下载。

开发机另可用已安装的 Codex CLI 验证实际客户端。将欢迎页生成的两个配置文件放入同一目录，
把 `--output` 指向尚不存在的目录：

```bash
python -m distribution.macos.codex_probe \
  --codex "$(command -v codex)" \
  --connection-directory "$welcome_directory" \
  --command "$app/Contents/MacOS/sciplot" \
  --output "$artifact_root/codex-first-figure"
```

探针使用临时 Codex 配置目录，通过 Codex App Server 调用工具而不启动模型回合。
它用合成 CSV 完成列选择、首图导出和重开同一项目。它不使用当前客户配置，也不代表
正式客户端对话、独立用户或干净 Mac 验收。

公测候选归档使用独立的新目录：

```bash
"${SCIPLOT_PYTHON:-.venv/bin/python}" -m distribution.macos.release \
  --app "$artifact_root/SciPlot.app" \
  --out "$artifact_root/candidate"
```

此命令复制应用、核对身份、在搬移后的副本执行全部本地验证和 runtime smoke，随后生成 ZIP，
解压并逐文件复核，输出 `release.json`、`SHA256SUMS` 和新用户说明。失败记录不被重试覆盖。
默认渠道是 candidate，不表示已具备公开分发身份。已由维护者完成签名/公证的应用可加
`--public`，强制验证 Developer ID、附加公证票据和 Gatekeeper；不通过则不生成公开 ZIP。
命令不会签名、上传或发布。公开包的技术门槛和独立用户/干净机器验收必须分别记录。
完整边界与用户指南见 [PUBLIC_BETA.md](../../docs/PUBLIC_BETA.md)。

要验证搬移后的包：

```bash
verify_root=$(mktemp -d "$HOME/SciPlot-verify.XXXXXX")
"${SCIPLOT_PYTHON:-.venv/bin/python}" -m distribution.macos.build --verify-existing \
  --out '/新位置/SciPlot.app' --verify "$verify_root/moved"
```

首次放置应用后双击它；或以 `Contents/MacOS/sciplot --welcome --no-open --out DIR`
生成可审阅的中文说明、环境检查和两种 MCP 配置片段。移动应用后应重新生成配置路径。
欢迎页默认只写入临时目录；不会安装配置、登录账户或调用付费模型。

使用流程以应用生成的欢迎页为准。历史包内 launcher 仍可做静态识别和完整性检查，
不再作为欢迎页的操作步骤。移动应用需要更新 MCP 路径；移动交付快照不是工程迁移。

离屏 Qt 文件事件和原生编辑测试不等于安装后在 Finder 双击的验收。
验证范围必须分别记录：本机启动与依赖封闭审计、另一台没有 Python/Qt/Homebrew 的干净
Mac、macOS 版本/架构兼容、Developer ID 签名与公证、真实小白任务测试。这里生成的包
没有 Developer ID 签名或公证；ad-hoc 签名不能替代发行身份认证。本机成功不能替代
干净机器或小白验收，也不承诺其它 macOS 版本及 CPU 架构。

技术依据：[Qt 官方部署说明](https://doc.qt.io/qt-6/macos-deployment.html)、
[Python 官方 macOS 说明](https://docs.python.org/3.13/using/mac.html)、
[官方 MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。
