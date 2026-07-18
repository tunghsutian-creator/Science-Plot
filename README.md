# SciPlot

SciPlot 是面向材料科研日常出图的本地、可复现、AI-enhanced 工作流。它把原始仪器数据转换为
可继续编辑的 `studio/document.vsz`，由 Veusz 完成生产渲染，并交付 PDF、300 dpi TIFF、
绘图数据、机器可读 QA 和可追溯运行记录。

## 产品边界

正式渲染器和唯一日常前端都是原生 Veusz `MainWindow`。SciPlot 保留 Veusz 的对象树、
属性编辑器、Datasets、画布、菜单、快捷键和 Undo/Redo，并在同一个 Veusz `Document` 上
增加：

- `SciPlot Project`：按需显示的项目、来源、映射、QA 和交付状态；
- `SciPlot AI`：按需显示、只修改当前选中对象安全属性的视觉助手；
- exact-current PDF/TIFF、QA 和 delivery 动作。

所有 SciPlot dock 默认隐藏，可以关闭，不改变 Veusz 原有布局。人工和 AI 修改共享同一个
文档、同一个原生 Undo/Redo 历史和同一个 VSZ 权威。SciPlot 不开发第二个渲染器、第二套
文档模型或 Veusz 属性编辑器的复制品。

完整阶段与工程门见 [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)。

## 当前阶段

M6 Veusz-first 合成基线已在 `352049d` 关闭：

- `studio` 和项目启动器打开原生 Veusz `MainWindow`；
- Project/AI dock 接入同一个 live `Document`；
- AI 能查看 exact-current 当前页面，并通过封闭类型化操作修改当前选中对象；
- AI 修改立即显示，并形成一个 Veusz 原生 Undo 步骤；
- 人工修改、保存、关闭重开、PDF/TIFF、QA 和 delivery 绑定 exact-current VSZ；
- 23 条 ready 规则的授权真实数据生命周期已经重新认证；
- 多余工作树和已合并分支已经清理。

当前里程碑是 **M6.1 日用收敛**。重点不是增加编辑器功能，而是用真实项目证明日用效率，
修复真实 P0/P1 摩擦，并验证真实模型是否在轴、曲线和图例等高频微调上比手工更省时间。
Standalone Canvas、Composition Board 和旧十五会话 Canvas-cutover 合同只保留兼容回归，
不再构成产品路线或日用 readiness 依赖。

## 最短日常路线

首次使用或交付前：

```bash
skill/scripts/sciplot doctor --json
```

要求 `status=ready`。随后从原始文件、文件夹或现有项目进入 Studio：

```bash
skill/scripts/sciplot studio PATH \
  --out outputs/projects \
  --export pdf,tiff_300 \
  --json
```

这条路线执行：

```text
原始数据
  -> 确定性检查与科学语义映射
  -> 仅在含义有歧义时确认
  -> studio/document.vsz
  -> 原生 Veusz MainWindow
  -> 人工微调 / 可选 AI
  -> 保存 exact-current VSZ
  -> PDF/TIFF + QA + delivery
```

如果实验类型和展示方式已经明确，优先显式传入意图，不强迫程序猜测：

```bash
skill/scripts/sciplot studio PATH \
  --rule RULE_ID \
  --template TEMPLATE_ID \
  --out outputs/projects \
  --export pdf,tiff_300 \
  --json
```

`--rule` 必须命中 ready 规则；`--template` 是独立可选的展示选择。高置信度 ready 输入直接进入
Veusz，只有样品分组、列含义或科学意图无法唯一确定时才停在确认状态。

## Veusz 内的日用编辑

在 Veusz 中直接完成：

- 对象选择、对齐、位置、尺寸和标注；
- 轴、图例、字体、线型、点型和颜色属性；
- Datasets 编辑；
- Save、Undo/Redo 和低频任意属性修改。

SciPlot 只处理自己的差异能力：

- Project dock 显示当前文档、来源审计、映射、制品 QA 和 delivery 状态；
- `Save & Export PDF/TIFF` 保存当前文档并导出，不重新生成 VSZ；
- 结果入口打开当前 PDF、delivery，或在文件管理器中定位当前 VSZ；
- AI dock 把当前渲染页作为视觉上下文，但只向模型开放当前选中对象的封闭属性目录。

手工保存的 `.vsz` 是视觉权威。显式重新生成前必须归档旧文档；打开项目和导出项目都不得
静默覆盖人工修改。

## 可选 AI

没有 API key 时，全部确定性绘图、Veusz 编辑、QA、导出和 delivery 仍正常工作。配置
provider 后，AI dock 只在用户显式打开时出现：

```bash
export SCIPLOT_OPENAI_API_KEY='YOUR_KEY'
# 也兼容 OPENAI_API_KEY
skill/scripts/sciplot studio PROJECT
```

AI 请求包含：

- exact-current 当前渲染页的有界 PNG；
- 当前文档 revision；
- 当前选中对象 ID、类型和安全可编辑属性目录；
- 不包含完整原始数据数组、API key 或任意 VSZ/Python 执行能力。

模型只能返回当前选中对象的 `set_setting` 类型化操作。SciPlot 会再次验证目标、setting
path、旧值、类型、范围、request hash 和 revision；过期响应整体拒绝。提案默认停在人工
确认，应用后形成一个原生 Veusz Undo 步骤。

轻量 `assistant_history.jsonl` 只保存请求/操作状态、规范化值哈希、before/after render
哈希和 revision，不保存 PNG/base64、密钥、绝对路径、自然语言意图、模型理解文本或隐藏
推理。它是本地日用审计，不是签名或远程身份凭证。

## 项目状态

日用结果状态与深度审计状态分开：

- `editing`：文档有未交付修改，或尚未产生当前导出；
- `exporting`：保存、PDF/TIFF、QA 和 delivery 正在执行；
- `ready`：当前 VSZ、PDF/TIFF 和交付制品一致，可以使用；
- `needs_fix`：当前 QA、导出或 delivery 已失败、缺失或被篡改。

深度来源审计另行显示：

- `current`：来源、映射和运行证据已重新验证；
- `pending`：结果可以是当前的，但尚未重新执行完整来源审计；
- `stale` / `failed`：来源、映射或证据确实发生变化或验证失败；
- `not_applicable`：独立 VSZ 只证明 exact-current 导出，不建立原始来源谱系。

“尚未重算审计”不会再被错误显示为“交付已陈旧”。

## 继续编辑现有 VSZ

项目交付中的 `Open_in_Veusz.command`，或下面的命令，会打开 exact-current 文档：

```bash
skill/scripts/sciplot studio PROJECT/studio/document.vsz --advanced-editor
```

编辑并保存后，精确导出当前项目：

```bash
skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
```

对于不带 SciPlot request 的独立 Veusz master：

```bash
skill/scripts/sciplot studio FIGURE.vsz \
  --out outputs/standalone_export \
  --export pdf,tiff_300 \
  --json
```

成功时读取 `standalone_export_receipt.json` 和 `qa_report.json`。独立 VSZ receipt 证明当前
文档导出和制品 QA，不宣称原始数据 provenance、transform lineage 或完整项目 delivery。

## 确定性规则与阻塞状态

查看程序如何理解输入：

```bash
skill/scripts/sciplot inspect PATH --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show RULE_ID --json
```

稳定结果状态：

- `ready`：可以继续检查和交付；
- `needs_human_confirmation`：只询问尚未解决的科学含义；
- `needs_rule_repair`：修复共享语义、recipe、policy 或 QA 后重跑。

已覆盖的确定性路径不需要 AI 看图。AI 的职责是处理新意图和歧义；重复成功的 AI 决策应
在真实使用中重复出现后再固化为材料规则、fixture、policy 或 QA。

## 交付合同

用户可见的最小 `delivery/` 只包含：

```text
delivery/
  data/*.csv
  pdf/*.pdf
  tiff/*_300dpi.tiff
  project/*.vsz
  Open_in_Veusz.command
```

manifest、raw archive、分析表、QA、publication intent 和 transform ledger 保留在运行目录，
不混入最小用户交付。交付前必须检查 `manifest.json`、`review.html`、QA、最终制品和
`delivery/`，不能只凭命令退出码报告成功。

## 浏览器兼容入口

只有用户明确需要浏览器确认样品分组、图例名称、顺序、尺寸或导出格式时使用：

```bash
skill/scripts/sciplot app --out outputs/intake_projects
```

浏览器是数据确认兼容面，不是第二个绘图器。高级任意编辑仍由 Veusz 完成。

## 专家和验证命令

```bash
# 已确认 request 的可复现运行
skill/scripts/sciplot run plot_request.json

# 稳定脚本包与批量处理
skill/scripts/sciplot autoplot PATH --out outputs/autoplot_projects --json
skill/scripts/sciplot batch INPUT_DIR --out outputs/batch --mode smoke
skill/scripts/sciplot acceptance rules --out outputs/acceptance --json

# 运行时变化门
skill/scripts/sciplot doctor --json
skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json

# 单独检查输出
skill/scripts/sciplot qa OUTPUT_DIR --strict-publication
```

历史 Canvas、Composition 和旧证据探针命令仍可直接调用以复查兼容性，但从普通
`sciplot --help` 隐藏，也不构成 M6.1 日用验收。

## 验收边界

- runtime smoke 使用明确标记的 synthetic contract fixture，不是真实数据证据；
- 23 条 ready 规则的生命周期证书不等于每个新输入自动正确；
- exact-current artifact QA 不等于通用期刊合规；
- 自动探针不计作人工日用验证；
- 当前仍需用五个真实项目完成 M6.1 日用收敛；
- 真实 OpenAI 端点和模型效率必须与人工微调分别评估，不能用离线 wire fixture 冒充。

## 安装

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[studio]'
skill/scripts/sciplot doctor --json
```

主要职责：

- `materials_rules.py`、`semantic.py`：实验族、轴/单位和确定性准备；
- `policy.py`、`publication.py`：共享图形与出版合同；
- `studio.py`：项目、VSZ、Veusz 打开和 exact-current 导出；
- `studio_project.py`：Veusz Project dock 与结果状态；
- `studio_assistant.py`：Veusz 当前选择对象的受限 AI；
- `qa.py`、`delivery.py`：制品 QA 与最小交付；
- `third_party/veusz/`：固定版本的上游渲染器和日常编辑器；
- `_vendor/`：迁移兼容层，默认最后才修改。

第三方许可见 [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。GitHub 只发布运行所需
源码、法律文件和明确放行的兼容合同；授权数据、输出、开发日志和历史审计留在本地工作区。
