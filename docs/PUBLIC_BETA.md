# SciPlot macOS 公测候选版

首发范围是 macOS 上的本地科学绘图，由外部 AI 理解需求，SciPlot 保留原始数据并生成可编辑图稿。
当前处于公测候选验证阶段。对外提供安装包前，还需完成 Developer ID 签名、公证、干净 Mac
安装和独立用户试用。当前包实际测试过的系统、架构和发行状态以随包 `release.json` 为准。

## 安装与第一次使用

1. 从维护者取得 ZIP、`SHA256SUMS` 和对应的 `release.json`。公开分发包应标明
   `channel: public`、`status: passed`、`public_distribution_ready: true`；`candidate`
   只表示本地候选包。校验 ZIP：在这两个文件所在目录运行 `shasum -a 256 -c SHA256SUMS`。
2. 解压，将完整的 `SciPlot.app` 放到固定目录（例如“应用程序”），然后双击。Python、Qt、
   Veusz 随应用提供。若系统阻止打开，向维护者反馈原始提示；不要关闭 Gatekeeper 或删除隔离标记。
3. 欢迎页显示环境检查，并提供包内命令路径和 MCP 配置片段。在支持本地 STDIO MCP 的外部
   AI 客户端添加 `sciplot` 服务，参数为 `mcp`。已有配置不会被应用自动改写。客户端需要有权
   读取原始数据目录；数据是否发送给模型取决于该客户端的配置。
4. 让 AI 使用 SciPlot 绘制自己的数据，例如：“用 SciPlot 绘制这个 FTIR 文件，保持样品名称
   和单位，先给我看图，再交付可编辑项目、PDF 和 300 dpi TIFF。”缺少单位或样品对应关系时，
   按真实实验信息回答，不能凭数值大小猜测。
5. 在原数据旁找到 `文件名_SciPlot/`。检查图形、样品、单位和范围，并保留同级隐藏的 `.sciplot/`
   工作区；它用于继续原项目。CSV、VSZ、PDF、TIFF 均在可见交付目录中。

## 调整、保存与恢复

- 双击 `Open_in_SciPlot.command`，选中曲线后调整外观；支持原生撤销/重做。
  **Save** 保存可编辑 VSZ；**Save and update delivery** 同时更新 PDF/TIFF。
- `Open_in_Veusz.command` 用于高级原生编辑。某些扩展设置（如圆角线连接）需要 SciPlot
  自带的运行时；不要用未经扩展的独立 Veusz 作为兼容性承诺。
- 下次让 AI“继续这个项目”，提供原始数据或交付目录。数据变更应走已有项目的源更新流程，
  先检查候选预览再接受。不要通过删除工作区或重建项目解决保存/导出问题。
- 已保存但导出失败时，让 AI 查询当前状态并重试导出，避免重复应用编辑。另一个同项目编辑
  窗口占用时，先保存并关闭它。交付副本单独改过时先处理差异，不能覆盖掉改动。
- 移动应用后重新生成 MCP 配置路径；旧交付的启动命令可能保留原应用路径，需继续受管项目并
  重新导出。只复制交付目录得到的是独立快照，不能据此认定原受管项目仍然可恢复。

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

候选命令在搬移后的独立副本执行环境检查、原生窗口、欢迎页、官方 SDK 的 MCP 发现/任务能力调用
及完整 runtime smoke。随后创建 ZIP、解压并逐文件校验，生成 `SHA256SUMS` 和 `release.json`。
所有输出目录必须是新目录；失败时保留报告及日志。`public_distribution_ready` 只报告技术发行
检查，不代替独立安装、真人试用或实际客户端验收。

已完成 Developer ID 签名和公证的应用使用同一入口加 `--public`。此开关验证身份、签名、
附加公证票据与 Gatekeeper，任一未通过都会阻止生成公开分发 ZIP。工具不会自动签名、上传到
Apple 或发布到互联网。签名需从嵌套代码向外进行，并启用 Hardened Runtime；由维护者持有的
Developer ID 和公证配置执行。具体要求依据 Apple 的
[代码签名说明](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac/)、
[公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)和
[分发打包说明](https://developer.apple.com/documentation/xcode/packaging-mac-software-for-distribution)。
