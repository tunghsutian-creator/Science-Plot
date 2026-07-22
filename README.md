# SciPlot

SciPlot 是面向材料科研日常出图的本地工作流：读取原始数据，按确定性规则生成可编辑的
`studio/document.vsz`，在 Veusz 中完成调整，并交付 PDF、300 dpi TIFF、绘图数据、QA
和可追溯运行记录。

## 文档与产品真相

- 本文是用户工作流和产品边界的唯一说明；
- `skill/SKILL.md` 是自动化代理的操作合同，不另定义产品；
- `docs/ARCHITECTURE.md` 只定义模块所有权和依赖边界；
- `DEVELOPMENT_ROADMAP.md` 只记录尚未完成的维护优先级；
- `AGENTS.md` 是本机开发约束的薄覆盖；
- `DEVELOPMENT_LOG.md` 和 Git 只保存历史与验证记录，不覆盖当前产品真相。

如果说明发生冲突，先以实际 CLI、本文和 source-controlled 合同为准，再修正文档漂移。

## 产品边界

原生 Veusz `MainWindow` 是唯一日用绘图前端和高级编辑器。SciPlot 在同一个 Veusz
`Document` 上增加两个默认隐藏、可关闭的 dock：

- `SciPlot Project`：来源、映射、当前制品、QA 和交付状态；
- `SciPlot AI`：可选的当前选中对象助手。

对象树、属性编辑器、Datasets、画布、菜单、快捷键、Save 和 Undo/Redo 都沿用 Veusz。
SciPlot 不维护第二套前端、第二个文档模型、独立 Canvas、Composition Board 或 Veusz
属性编辑器的复制品。手工和 AI 修改共享同一个文档和原生 Undo 历史；保存后的 `.vsz`
是视觉权威。

AI 不是日用必需依赖。没有 provider 或 API key 时，受支持输入的识别、绘图、人工编辑、
保存、QA、导出和交付仍应完整工作。

浏览器 `app` 只是可选的首次确认面，用于 source、grouping、命名、顺序、尺寸和导出格式，并可
只读查看已经生成的结果。它不是精修前端，不应在渲染后提供样式、坐标轴或 series 编辑；
所有视觉精修都在 Veusz 中完成。`app` 只允许 loopback 访问；浏览器传入的本地路径必须
来自当前 CLI session 或 SciPlot 输出根目录。

## 交互与 exact-current 主命令族：Studio

首次使用或交付前：

```bash
skill/scripts/sciplot doctor --json
```

要求 `status=ready`。

交互式日常入口会准备项目并打开原生 Veusz：

```bash
skill/scripts/sciplot studio PATH --out outputs/projects
```

已知实验规则或展示类型时，可以在同一命令族中直接表达意图：

```bash
skill/scripts/sciplot studio PATH \
  --rule RULE_ID \
  --template TEMPLATE_ID \
  --out outputs/projects
```

无需打开 GUI 的自动准备、导出和机器可读结果仍使用 `studio`：

```bash
skill/scripts/sciplot studio PATH \
  --out outputs/projects \
  --export pdf,tiff_300 \
  --json
```

`--json` 表示 headless，不会打开 Veusz。交互入口和 headless 导出是同一个 Studio
生命周期的两种调用方式，不是两套绘图系统。

日常流程是：

```text
原始数据
  -> 确定性检查与科学语义映射
  -> 只确认无法唯一确定的含义
  -> studio/document.vsz
  -> 原生 Veusz MainWindow
  -> 人工微调 / 可选 AI
  -> 保存 exact-current VSZ
  -> PDF/TIFF + QA + delivery
```

## 打开和精确导出

打开已有 VSZ 直接使用 Studio；不需要另一个“高级编辑器”入口：

```bash
skill/scripts/sciplot studio FIGURE.vsz
```

保存后精确导出当前项目，不重新生成 VSZ：

```bash
skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
```

独立 Veusz 文档也可以按 exact-current 路线导出：

```bash
skill/scripts/sciplot studio FIGURE.vsz \
  --out outputs/standalone_export \
  --export pdf,tiff_300 \
  --json
```

独立 VSZ 的 receipt 只证明当前文档和导出制品；它不自动建立原始数据 provenance、
transform lineage 或完整 SciPlot 项目交付。显式重新生成前必须归档人工保存的 VSZ；
打开和导出项目不得静默覆盖人工修改。

## 其它命令的角色

- `app`：仅在需要首次浏览器确认时使用；不是绘图或精修前端。
- `autoplot`：唯一公开的程序化全自动项目入口。它内部复用
  `one-step`/`run_request`，并负责稳定 summary、QA 和 delivery；它不是第三个
  renderer。
- `run`：重放已经确认的 `plot_request.json`。
- `render`、`recipe`：供开发、测试和已知低层合同使用的原语。
- `curate torque`：只负责转矩事件选择、复核资料和 Studio 项目准备；最终编辑、导出和
  delivery 仍回到 `studio`。
- `batch`、`smoke`、`acceptance`：开发与回归验证路线，不是另一种用户自动出图入口；
  `batch` 因此不出现在正常帮助中。
- `readiness`、`cleanup`、`mapping`：证据登记或显式维护工具，不创建另一套绘图生命周期。
- `publication`：只查看 profile 和确定性版面元数据；不提供 Composition 编辑器、拼图器或
  独立 renderer。
- `one-step`：内部状态/manifest 合同，不是用户命令。

需要从原始路径直接生成自动化项目、QA 和 delivery 时：

```bash
skill/scripts/sciplot autoplot PATH \
  --out outputs/autoplot_projects \
  --json
```

生产绘图最终都由同一 Veusz 路线完成。不同编排入口不表示存在另一个前端、renderer 或
视觉权威。

## 模板与全局绘图契约

生产 Veusz 文档构建器只接受六种已完成语义验证的模板：

- `curve`
- `point_line`
- `stacked_curve`
- `box`
- `box_strip`
- `heatmap`

其它模板必须在请求边界明确失败，不能悄悄退化成曲线图。全局硬样式由
`src/sciplot_core/policy.py` 统一定义，并与 vendored `plot_contract.json` 保持一致。
模板只拥有图形语义和允许编辑的选项；热图标量色带、等高线和色条配色是显式的语义例外。

## 可选 AI

AI dock 只处理当前选中的受支持对象。模型只能提出经过验证的 `set_setting` 操作；过期
revision、越权目标、未知 setting、错误类型或超范围值必须整体拒绝。提案默认由用户确认，
接受后形成一个 Veusz 原生 Undo 步骤。它不能修改原始科学数据、执行任意 Python/VSZ
代码或替代 Veusz 属性编辑器。

被阻塞的数据清理或共享规则修复是另一类外部维护工作，不应与 in-app selected-object AI
混成用户可见的模式切换。

## 状态与交付

日用项目结果状态为 `editing`、`exporting`、`ready` 或 `needs_fix`。准备/自动化状态为
`ready`、`needs_human_confirmation` 或 `needs_rule_repair`。两组状态属于不同层级，不能
互相替代；来源审计 `pending` 也不能被误写成当前制品失效。

用户可见的最小交付只有：

```text
delivery/
  data/*.csv
  pdf/*.pdf
  tiff/*_300dpi.tiff
  project/*.vsz
  Open_in_Veusz.command
```

manifest、raw archive、分析表、QA、publication intent 和 transform ledger 留在运行目录。
交付前应检查 `manifest.json`、`review.html`、QA、最终制品和 `delivery/`，不能只看退出码。

## 检查与首次确认

查看程序如何理解输入：

```bash
skill/scripts/sciplot inspect PATH --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show RULE_ID --json
```

只有明确需要浏览器首次确认时才使用：

```bash
skill/scripts/sciplot app PATH --out outputs/intake_projects
```

确认完成后回到 Studio/Veusz；浏览器结果页保持只读。

## 工程验证与证据边界

非平凡修改至少运行：

```bash
python -m pytest -q
skill/scripts/sciplot doctor --json
skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json
git diff --check
```

共享样式、渲染、规则、QA 或 delivery 合同变化还必须运行：

```bash
skill/scripts/sciplot acceptance rules --out outputs/acceptance --json
```

`acceptance rules` 会机器校验 PDF 物理尺寸、TIFF DPI 和交付副本一致性；生成的
contact sheets 只是未校准的缩略预览，用于检查裁切、遮挡、线型/标记区分和空白或损坏，
不能据此声称“按最终物理尺寸可读”。逐张检查这些预览后用
`skill/scripts/sciplot acceptance visual-review PATH/final_size_visual_review/final_size_visual_review.json --decision passed|failed --reviewer NAME --json`
记录可审计结论。未记录时只能声明自动尺寸检查通过；最终尺寸可读性仍需另行在校准显示器
或打印件上检查并保留证据，本命令不提供该证明。

runtime smoke 是明确标记的 synthetic 变化门，不是真实数据证据。生命周期通过、
exact-current artifact QA、provenance、人工日用验证和期刊合规是不同声明。

## 安装与代码入口

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[studio,dev]'
skill/scripts/sciplot doctor --json
```

当前维护优先级见 [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)，模块所有权见本地
`docs/ARCHITECTURE.md`；第三方许可见
[THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。
