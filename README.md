# SciPlot

SciPlot 是面向材料科研日常出图的本地、可复现、AI-enhanced 工作流。它把原始仪器数据变成
可继续编辑的 `studio/document.vsz`，由 Veusz 完成生产渲染，并交付 PDF、300 dpi TIFF、
数据工作簿、分析记录和机器可读 QA。Luna/Codex 用于理解新的科学意图、长尾数据和复杂
视觉修改；已覆盖路径必须在没有 AI 时独立工作。

正式渲染器只有 Veusz。当前完整 Veusz GUI 仍是高级编辑和恢复入口，但产品路线已经确定：
SciPlot 将用聚焦科研任务的原生实时 Canvas 取代 Veusz `MainWindow` 作为默认前端，同时保留
Veusz `Document`、`PlotWindow`、命令接口、VSZ 和导出内核。SciPlot 不开发第二个渲染器，
也不重造覆盖任意 Veusz 属性的通用高级编辑器。

完整阶段、架构边界和验收门见
[DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)。原生前端的操作流、窗口结构和视觉原则见
[docs/SCIPLOT_OPERATION_FLOW_PLAN.md](docs/SCIPLOT_OPERATION_FLOW_PLAN.md)。

## 产品方向：AI-enhanced Canvas

未来的日常工作台遵循三个分工：

- 用户在实时画布上选择、拖动、对齐、圈选、批注和拼图；
- AI 把自然语言、选择上下文和批注转换为经过验证的结构化数据映射或画布操作；
- 确定性程序执行数据变换、Veusz 文档修改、撤销/恢复、QA、导出和交付。

AI 和用户必须经过同一套操作接口。AI 不通过鼠标点击 Veusz GUI，不直接把 VSZ 当任意文本
改写，也不把不可追溯的“最终清洗数据”作为交付结果。重复成功的 AI 决策应固化为规则、
fixture、策略或 QA，使下一次能够少用或不用 AI。

项目的目标不是提高 AI 占比，而是让 AI 只处理未知性。对于已验收的数据和绘图规则，
程序应直接返回 `ready_to_use=true`，无需 AI 看图；不确定时必须停在确认或修复状态。

当前完成到 M2 的基础层：统一 Canvas 会话、类型化操作、审阅批注和数据映射合同已经建立；
原生 Qt Canvas shell 已能嵌入 `PlotWindow`，处理选择、可见文字编辑、撤销/重做、保存、
恢复、精确导出、QA 和项目交付。界面现已支持系统 palette 驱动的明暗/高对比主题、窄窗口
浮动检查器、`Tab` Canvas-only、菜单/快捷键对等、可访问名称和跨重开界面状态持久化。
50 次连续实时操作门禁以及多类真实/代表性工程回归均已通过。M2 仍需补齐日常页面/轴/曲线/
图例检查器、审阅覆盖层、批注晋升和直接操作，因此当前 `studio` 默认入口暂不切换。

## 日常主流程

首次或交付前检查：

```bash
skill/scripts/sciplot doctor --json
```

要求 `status=ready`。随后，一条命令完成识别、VSZ 生成、导出、QA 与交付：

```bash
skill/scripts/sciplot studio PATH \
  --out outputs/projects \
  --export pdf,tiff_300 \
  --json
```

这是 Luna 应优先使用的入口。成功的科研交付必须同时满足：

- 用户/Luna 显式选择或程序识别命中本地注册表中的 `ready` 规则；
- `studio/document.vsz` 已生成且是视觉权威；
- PDF 与 300 dpi TIFF 成对存在；
- `qa.status=passed`；
- `delivery.complete=true`；
- 导出记录中的 VSZ SHA-256 与当前文档一致。

项目返回三种稳定状态：

- `ready`：可直接使用交付包；
- `needs_human_confirmation`：科学含义、样品分组或列角色需要人确认；
- `needs_rule_repair`：解析、规则、转换或 QA 阻断，此时才让 Luna/Codex 修规则或数据。

程序不会用占位曲线或假数据工作簿伪造成功。

用户已经选好实验类型或直接告诉 Luna/Codex 要画什么时，不必强行依赖自动识别：

```bash
skill/scripts/sciplot studio PATH \
  --rule swelling_curve \
  --template point_line \
  --out outputs/projects \
  --export pdf,tiff_300 \
  --json
```

`--rule` 是明确的科学语义选择，会绕过自动猜测；`--template` 是明确的呈现选择，可单独使用，
也可省略并采用该规则的默认模板。Luna/Codex 可以根据用户自然语言直接填写这两个参数。

## 原生 Canvas（M2 基础实验入口）

对已有 SciPlot project、`plot_request.json` 或独立 VSZ 进行实时编辑：

```bash
skill/scripts/sciplot canvas PROJECT_OR_VSZ
```

也可以传入 Studio 能准备的原始数据路径，并用 `--out`、`--rule`、`--template` 和 `--name`
提供显式项目意图。Canvas 不构造 Veusz `MainWindow`；它直接加载 exact-current VSZ，在
SciPlot 窗口中显示实时画布和从属检查器。当前高频能力包括：

- 页面与缩放导航；
- PlotWindow 点击选择和可见文本编辑；
- Save、Undo、Redo；
- PDF/TIFF exact-current Export + QA；
- QA/export revision 状态；
- 显式未保存恢复；
- `F9` 收起检查器；
- `Tab` 进入 Canvas-only，`Esc` 恢复界面；
- 系统 palette 驱动的明暗与高对比应用 chrome；
- 窄窗口检查器自动浮动，保持画布宽度；
- 界面状态、菜单/快捷键和可访问名称门禁；
- `More` 中的 Advanced Editor 恢复入口。

这是 M2 基础层，不代表 M2 的完整日常编辑器。页面、轴、曲线、图例、外观、批注、数据点
选择和直接操作仍在下一批。日常自动绘图与交付目前仍优先使用 `studio`。

## 高级修图（过渡期恢复入口）

需要高级修正时，打开项目内的 `Open_in_Veusz.command`，或运行：

```bash
skill/scripts/sciplot studio PROJECT/studio/document.vsz --advanced-editor
```

在完整 Veusz 中修改对象树、轴、图例、字体、标注和排版并保存。然后精确导出当前文档：

```bash
skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
```

这一步不会重新生成 VSZ。手工保存的 `.vsz` 是视觉权威；显式再生成前会先归档旧文档。
该入口将在 SciPlot Canvas 覆盖实时编辑、批注、AI 操作和拼图并通过真实日常使用验收后，
退为隐藏的恢复/开发入口。

对于不带 SciPlot project/request 的独立 Veusz master，可直接导出到指定目录：

```bash
skill/scripts/sciplot studio FIGURE.vsz \
  --out outputs/standalone_export \
  --export pdf,tiff_300 \
  --json
```

成功时命令返回 `0`，并写出 `standalone_export_receipt.json`、`qa_report.json` 和
`figures/`。receipt 会记录 exact-current VSZ 哈希、请求格式、制品 QA，以及缺失
`.spec.json` 时的真实状态。spec sidecar 只用于 SciPlot 再生成，不是 Veusz 重开或
精确导出的前提。standalone receipt 不宣称原始数据 provenance、transform ledger
或完整 project delivery 已建立。

生成的 `Open_in_*.command` 和 `Export_Edited_Veusz.command` 可在 delivery 移动后
通过 `SCIPLOT_REPO`、上级目录或已安装的 `sciplot` 自动定位运行时；给启动器传
`--check` 可使用真实 Veusz Qt 加载路径完成无交互检查。

开发 worktree 可以用 `SCIPLOT_RUNTIME_REPO` 指向另一个持有已编译 Veusz helper 和
`.venv` 的可信 checkout，同时通过 `SCIPLOT_SOURCE_ROOT` 执行当前分支源码。源码根、
Veusz/Python 运行时根和交付项目路径因此不再混为一个概念。

## 输出结构

典型项目包含：

```text
PROJECT/
  plot_request.json
  intake_manifest.json
  studio/
    document.vsz
    Open_in_Veusz.command
  runs/
    run_001/
      manifest.json
      analysis_report.md
      review.html
      request_snapshot.json
      publication_intent.json
      transform_ledger.json
      publication_qa.json
      tables/analysis_metrics.csv
      raw/
      figures/
      delivery/
```

交付前读取 `manifest.json`、`review.html`、`tables/analysis_metrics.csv`、QA 和 `delivery/`；
不要仅凭命令退出码或空预览判断成功。

## 已实现能力

- CSV、TSV、TXT、XLS/XLSX 与常见仪器文件夹的本地检查和读取；
- 材料实验语义识别、单位/轴别名、样品顺序和 recipe 自动选择；
- 拉伸、冲击强度、流变/DMA、DSC/TGA/DTG、FTIR/UV-Vis、XRD/SAXS、
  GPC/SEC、扭矩和溶胀等生产规则；
- 同指标多样品比较、谱图堆叠、replicate 处理和事件段选择；
- Veusz `.vsz` 生成、完整 Veusz 高级编辑和 exact-current export；
- M0 Canvas 内核合同、稳定对象 ID、恢复快照和冲突门禁；
- M1 原生 Qt Canvas shell、实时选择/文字编辑、50 次连续操作门禁、精确导出和显式恢复；
- M2 palette-backed 明暗/高对比主题、适应式检查器、Canvas-only、可访问性和界面状态持久化；
- 60/120/180 mm 单图尺寸以及 183 mm 组合图布局；
- publication intent、transform ledger、研究模型和证据绑定；
- PDF 页面/字体/尺寸/可见墨迹、TIFF 分辨率、PDF-TIFF 配对和哈希 QA；
- 基于 exact-current VSZ 的固定画框、语义标签、完整可解析线宽审计，以及绑定
  最终 PDF 颜色的非颜色编码、灰度和三类色觉缺陷模拟；
- 可携带 `delivery/`，包含图、数据工作簿、项目文件与内部审计材料；
- `intervention_request.json`、`assisted_cleanup_request.json`、
  `cleanup_result.json` 和 `revision_brief.md` 组成的可审计辅助修复链；
- 文件夹 batch、用户本地数据 acceptance 和扭矩专项 curation。

`impact_metric` 保留每一个原始观测值：`n=1` 只画真实散点，`n>=2` 才叠加
Veusz 原生 median/IQR 箱线摘要；也可显式选择 `raw_only`，SciPlot 不生成伪重复样。

未验收的 pending 规则不会自动进入绘图。完整验收语料和本地参考数据不属于 GitHub
发布内容；规则验收只在持有相应授权材料的开发工作区进行。

## 浏览器兼容入口

当用户明确需要在浏览器确认样品分组、图例名称、顺序、尺寸或导出格式时使用：

```bash
skill/scripts/sciplot app --out outputs/intake_projects
```

浏览器只负责数据确认与导出请求，不提供 Matplotlib/WebAgg 实时绘图器。Source、Inspect 和 Samples
是 data-confirmation stages, not plot-preview stages。Result Review 只在 Export 或辅助修复产生真实制品后出现。
Do not use an empty plot preview as a placeholder during import, inspection, or grouping.

## 辅助修复边界

前端默认独立运行，没有用户可见的模式切换。正常路径不依赖 Codex。只有以下情况才允许助手介入：

- `needs_rule_repair` 或 `needs_ai_intervention`；
- `intervention_request.json` 或 `assisted_cleanup_request.json` 出现；
- 用户明确要求 Luna/Codex 修改规则、清洗数据或调整 recipe。

助手必须先保存原始输入，写出可验证的 `cleanup_result.json` 或 recipe/rule 补丁，在本地完成验证，
再回到同一确定性工作流重跑。不得要求用户“切换模式”，也不得静默改变科学含义。

## 专家与验收命令

```bash
# 查看程序如何理解输入
skill/scripts/sciplot inspect PATH --json

# 查看生产规则
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show rheology_temperature_sweep --json

# 已确认 request 的可复现运行
skill/scripts/sciplot run plot_request.json

# 不依赖私有验收语料的运行时生命周期门禁
skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json

# 稳定脚本包与批量处理
skill/scripts/sciplot autoplot PATH --out outputs/autoplot_projects --json
skill/scripts/sciplot batch INPUT_DIR --out outputs/batch --mode smoke
skill/scripts/sciplot batch INPUT_DIR --out outputs/batch --mode all --tensile-root PATH
skill/scripts/sciplot acceptance 3dpa PATH --out outputs/acceptance --json

# 扭矩事件段整理
skill/scripts/sciplot curate torque PATH --name PROJECT_NAME \
  --out outputs/curation_projects --json

# 单独复核输出
skill/scripts/sciplot qa OUTPUT_DIR --strict-publication
```

`autoplot`、`run`、`batch` 和 recipe/render 是专家与兼容接口；日常新任务优先走 `studio`。
`smoke` 在运行时生成明确标记的合成 FTIR 合同表以及 SAXS、GPC、多工作表 Impact 和显式
意图 swelling 等解析合同，检查语义选择、原生 Canvas 21 项应用合同、VSZ 重开与人工编辑
保留、精确导出、PDF/TIFF 配对、交付哈希及哈希失败门禁；它不属于真实数据证据。完整规则
矩阵依赖本地验收数据，因此不属于 GitHub 最小运行发行版。

## 安装

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[studio]'
```

代码职责：

- `src/sciplot_core/_paths.py`、`_utils.py`：仓库/本地数据路径与共享 IO；
- `src/sciplot_core/materials_rules.py`：实验族、轴/单位语义与规则 readiness；
- `src/sciplot_core/semantic.py`：识别和预处理；
- `src/sciplot_core/studio.py`：VSZ 生命周期、Veusz 打开/导出与 Studio 交付；
- `src/sciplot_core/canvas_app_probe.py`：原生 Canvas 用户路径、视觉与恢复门禁；
- `src/sciplot_core/launchers.py`：可移动项目和 delivery 的启动器发现合同；
- `src/sciplot_core/workflow.py`：request 编排和辅助修复闭环；
- `src/sciplot_core/qa.py`、`delivery.py`：制品 QA 与交付门禁；
- `src/sciplot_core/publication.py`、`study_model.py`：出版与证据合同；
- `src/sciplot_recipes/`：经过测试的实验族 recipe；
- `src/sciplot_gui/`：SciPlot Qt shell、workspace、DocumentController 和 Veusz Canvas adapter；
- `src/sciplot_core/_vendor/`：迁移兼容层，默认不直接修改；
- `third_party/veusz/`：固定版本的上游生产渲染器与高级编辑器。

第三方许可见 [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。GitHub 仓库只发布运行所需内容
和产品方向合同；本地参考数据、详细开发日志及私有验收材料保留在开发工作区，不进入最小运行
发行版。

`skill/scripts/sciplot` 会把当前 checkout 的 `src/` 加入 Python 导入路径，因此普通
Git worktree 即使没有自己的 `.venv`，也能使用系统 Python 或 `SCIPLOT_PYTHON`
直接运行本分支代码。高级开发环境可用 `SCIPLOT_SOURCE_ROOT` 显式指定源码树。在 macOS
上，包装器还会从已编译 Veusz helper 的链接信息推导匹配的 Qt framework；`doctor` 会实际
导入该 helper，避免只检查到 PyQt 包存在却无法启动 GUI。
