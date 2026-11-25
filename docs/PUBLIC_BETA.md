# SciPlot macOS 公测候选版

首发范围是 macOS 上的本地科学绘图，由外部 AI 理解需求，SciPlot 保留原始数据并生成可编辑图稿。
当前处于公测候选验证阶段。对外提供安装包前，还需完成 Developer ID 签名、公证、干净 Mac
安装和独立用户试用。当前包实际测试过的系统、架构和发行状态以随包 `release.json` 为准。

## 安装与第一次使用

1. 从维护者取得 ZIP、`SHA256SUMS` 和对应的 `release.json`。公开分发包应标明
   `channel: public`、`status: passed`、`public_distribution_ready: true`；
   `candidate` 只表示本地候选包。在 ZIP 所在目录运行 `shasum -a 256 -c SHA256SUMS`。
2. 解压，将完整的 `SciPlot.app` 放到固定目录（例如“应用程序”），然后双击。
   Python、Qt 和 Veusz 随应用提供。若系统阻止打开，向维护者反馈原始提示；
   不要关闭 Gatekeeper 或删除隔离标记。
3. 在应用生成的 **开始使用** 页下载本次安装位置的 MCP 配置，按你的客户端说明手动添加。
   应用不会自动连接或修改配置；移动应用后需用新路径更新配置。欢迎页的本地就绪检查
   不等于客户端已连通，请在实际客户端执行一次 SciPlot 能力查询并查看真实工具结果。
4. 从欢迎页下载双样品合成 CSV，先按示例完成一张图，不必提供私人实验数据。面对纵轴选择，
   练习可回答「用 Mass」，再看实际图、PDF 和 TIFF。保存 AI 返回的可续编项目路径，
   换会话时用它接着编辑，不拿交付用的 VSZ 当原项目。无 AI 时可用欢迎页的命令行入口。

安装指南到这里结束：后续以当前应用生成的欢迎页为准，不运行交付中的历史启动文件。
PDF、TIFF 和 VSZ 快照用于查看与交付；只复制交付目录不等于迁移可续编的工程。

## 反馈问题

重新打开应用，从欢迎页下载 `feedback.json`，审阅后连同下列文字交给维护者：

```text
发生时间：
使用的 AI 客户端和版本：
我进行的操作：
预期结果：
实际结果（包括完整错误提示；发送前检查是否含私人路径或信息）：
能否重复，最短步骤：
是否影响原始数据、样品/单位、保存或最终导出：
```

应用生成的摘要仅含构建身份与环境检查状态，不含实验数据、样品名、文件路径、错误全文、
AI 配置或密钥，也不会自动上传。原始实验文件仅在你明确同意后提供；优先提供可公开的最小
复现数据。发现值、单位、样品身份不一致时停止使用该图，保留当前文件和失败记录。

## 公测边界

- 仅报告实际验证的 macOS/CPU 配置；Windows、Linux、其它 macOS 版本和架构尚未获得安装承诺。
- 本机环境就绪、自动测试和合成 smoke 不代表干净机器、真人易用性或期刊验收完成。
- 不承诺端到端一秒成图；本地处理、外部 AI 推理、网络与人工确认分别计时。
- 升级前保留旧应用和项目副本，新版使用不同文件名或目录验证后再切换 MCP 路径。删除应用
  不会自动删除原始数据或 `.sciplot/`，不要将清除项目作为卸载步骤。

维护者按 `docs/INDEPENDENT_ACCEPTANCE.md` 招募 3–5 位未参与开发的用户，记录首次安装、
自有数据首图、真实歧义、注释预览、导出和隔日恢复。失败、介入和未知项都要保留。
至少用另一台未安装 Python/Qt/Homebrew 的 Mac 完成首次打开、连接和绘图。

## 维护者构建入口

从源码仓库运行：

```bash
.venv/bin/python -m distribution.macos.build --out .tmp_verify/beta/build/SciPlot.app
.venv/bin/python -m distribution.macos.release --app .tmp_verify/beta/build/SciPlot.app --out .tmp_verify/beta/candidate
```

候选命令在搬移后的独立副本生成欢迎页，执行环境检查与完整的无界面原生 runtime smoke，
并由官方 MCP SDK 使用欢迎页生成的 daily 配置发现工具、读取任务能力。定向首图测试还会用
欢迎页的同一份合成 CSV 走完选列、实际导出并重开项目。它不调用模型，也不替代真实 AI
客户端完成首图和续编。随后创建 ZIP、解压并逐文件校验，
生成 `SHA256SUMS` 和 `release.json`。
所有输出目录必须是新目录；失败时保留报告及日志。`public_distribution_ready` 只报告技术发行
检查，不代替独立安装、真人试用或实际客户端验收。

已完成 Developer ID 签名和公证的应用使用同一入口加 `--public`。此开关验证身份、签名、
附加公证票据与 Gatekeeper，任一未通过都会阻止生成公开分发 ZIP。工具不会自动签名、上传到
Apple 或发布到互联网。签名需从嵌套代码向外进行，并启用 Hardened Runtime；由维护者持有的
Developer ID 和公证配置执行。具体要求依据 Apple 的
[代码签名说明](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac/)、
[公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)和
[分发打包说明](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)。
