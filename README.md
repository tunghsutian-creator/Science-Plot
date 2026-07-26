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
skill/scripts/sciplot studio PATH --out /path/to/Visible_Figure_Project
```

已知实验规则或展示类型时，可以在同一命令族中直接表达意图：

```bash
skill/scripts/sciplot studio PATH \
  --rule RULE_ID \
  --template TEMPLATE_ID \
  --out /path/to/Visible_Figure_Project
```

无需打开 GUI 的自动准备、导出和机器可读结果仍使用 `studio`：

```bash
skill/scripts/sciplot studio PATH \
  --out /path/to/Visible_Figure_Project \
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
  --out /path/to/Visible_Figure_Project \
  --json
```

分类重复数据的科学识别与图形表达彼此独立。规则负责样品、重复值、单位和指标语义；
presentation contract 负责允许的图形。以抗冲击强度为例，同一数据可显式选择：

```bash
skill/scripts/sciplot autoplot PATH --template bar --out /path/to/bar_project
skill/scripts/sciplot autoplot PATH --template box --out /path/to/box_project
skill/scripts/sciplot autoplot PATH --template box_strip --out /path/to/box_strip_project
skill/scripts/sciplot autoplot PATH --template point_line --out /path/to/point_line_project
```

未指定时使用规则记录的默认图形；显式选择不会改变数据类型、统计原始值或单位。
抗冲击强度工作簿选择 `point_line` 时，同一样品轴的多个条件会形成均值点–线比较，
误差棒采用与柱状图相同的均值 ± 样本标准差（分母 `n-1`）定义。全部原始重复值
以条件同色系的半透明浅色点叠加，并按箱线图的稳定伪随机槽位在各条件均值位置两侧
混排。多个条件只在类别中心附近作小幅、对称的水平错位（两条件时为 `-0.05/+0.05`），
使误差棒可辨而不改变类别归属；原始点跟随所属条件。原始点比均值点小 12.5%，透明度
为 0.50；均值点带 0.70 pt 白色描边。样品位置使用稳定的不同 marker。四个样品默认采用
`60x55` mm 图幅。默认选取
条件数最多、样品轴最完整的一组兼容工作表；已确认的请求也可用
`condition_order` 和 `condition_label_mapping` 固定条件顺序与图例文字。

`bar` 还接受明确的长表组成数据：`Sample`、`Component` 和唯一一个数值列。
这一路径把每个样品绘制为加和堆叠柱，不把组成值误当成重复测量，也不生成误差线。
不同样品沿用普通柱状图的控制组优先色序（首样品为近黑色），同一样品内的组成段只通过
不透明的同色相明度阶梯区分。组分图例按可见堆叠顺序从上到下排列，并将每个图例色块
切分为全部样品颜色，避免用单一样品的深浅色冒充多色柱。

## 材料性能散点图和雷达图

材料性能对比共用一个长表合同；示例见
[`tests/fixtures/performance_comparison/material_performance_long.csv`](tests/fixtures/performance_comparison/material_performance_long.csv)。
每行只能表示一个“材料–指标”数值，不能把重复行静默平均。必需列和常用可选列为：

| 列 | 含义 |
| --- | --- |
| `Material` | 材料或样品名。 |
| `Role` | `sample` 表示本工作样品，`reference` 表示文献/参照材料。 |
| `Metric`, `Value`, `Unit` | 指标 ID、有限数值和单位；同一指标的元数据与单位必须一致。 |
| `Group` | 本工作样品的包络组；同组样品共享色系和浅色包络。 |
| `EnvelopeInclude` | 可选的 `true/false`；控制该样品是否参与 `Group` 的浅色包络，默认样品纳入、参考材料不纳入。 |
| `DisplayLabel` | 轴上显示的指标名。 |
| `ScatterAxis` | 散点图中恰好一个指标写 `x`、一个指标写 `y`。 |
| `ScatterMin`, `ScatterMax` | 可选的散点轴显示边界；允许只声明一侧，但不得裁掉任何绘制数据。 |
| `RadarOrder` | 雷达轴顺序；至少三个指标，正整数不得重复。 |
| `Direction` | `higher` 或 `lower`，统一为“越外越优”。 |
| `ScaleMin`, `ScaleMax` | 雷达归一化的声明边界；数据越界时拒绝绘图。 |
| `Journal`, `Year`, `DOI` | 参考材料的文献元数据；未给显式 `LegendLabel` 时，期刊和年份显示在右侧索引。 |
| `MaterialOrder`, `Marker` | 可选的索引顺序和显式 marker。 |
| `LegendLabel`, `LegendGroup` | 可选的右侧显示文字和分组标题；显式文字不会自动追加期刊/年份。 |
| `LegendIdentity` | 多个观测点可共享一个材料身份、marker 和索引条目。 |
| `LegendColumn` | `1` 或 `2`；两列索引使用两个并排的 `60x55` mm 模块。 |
| `LegendItemsPerRow` | `1` 或 `2`；控制同一图例分组内每行放置一个或两个条目。 |

散点图左侧是 `60x55` mm 图模块，实际坐标绘图区为 `41.5x38.5` mm；右侧保留另一个
`60x55` mm 索引列；显式使用两列时总图幅扩展为 `180x55` mm。索引只显示分组标题和
条目，不另加总标题。本工作中源密度相同的点使用以源哈希绑定的对称伪随机横向错位，
源密度仍保存在交付数据中。`ScatterMin`/`ScatterMax` 只控制显示范围，不改变或裁剪
数据。`EnvelopeInclude=true` 的样品按 `Group` 生成无边框、确定性平滑的不规则浅色
包络；未纳入的样品仍正常绘制，并保留其原始数据和图例身份。
这个区域只表示已观察样品范围，不是置信区间。参考材料保持中性、空心且可由 marker
区分。模板提供十六个 Veusz 原生 marker；全局唯一约束作用于 `LegendIdentity`，同一
材料身份的多个观测点可以共用 marker 并合并为一个索引条目。每列行距按条目数在固定
高度内确定性计算；需要压缩本工作样品图例时，可在同一分组内显式设置每行两个条目。

雷达图使用同样的左 `60x55` mm 绘图模块。本工作样品是闭合、半透明填充的 marker
多边形；参考材料只在确有数据的指标轴上标 marker，不补齐或连成虚构多边形。只要存在
参考材料、文献信息或较多本工作样品，就使用右侧保留索引模块，避免图内图例挤压约
`40x38` mm 的有效雷达区域。

当前 source-controlled 示例是 `instrument_shaped_fixture`，不是用户真实测量数据，因此
`performance_comparison` 规则在第一份授权真实数据完成 acceptance 前保持 `pending`。
功能可通过显式 Studio 请求使用，但不会被 `autoplot` 静默自动选择：

```bash
skill/scripts/sciplot studio PATH \
  --rule performance_comparison \
  --template scatter \
  --out /path/to/material_scatter

skill/scripts/sciplot studio PATH \
  --rule performance_comparison \
  --template polar_curve \
  --out /path/to/material_radar
```

需要 Codex 代为绘图时，可直接使用下面这种指令；把路径和材料名换成自己的即可：

```text
请用 SciPlot 读取 /绝对路径/material_performance_long.csv。
显式使用 rule=performance_comparison。
先生成 template=scatter：ScatterAxis=x 是 density，ScatterAxis=y 是
specific_impact_strength；Role=sample 的同一 Group 用与 marker 同色系的浅色包络，
Role=reference 只画真实数据点。图幅必须是左侧 60x55 mm 绘图模块加右侧
60x55 mm 材料索引，总计 120x55 mm；索引显示材料、marker、Journal 和 Year。
不要平均重复的 Material-Metric 行；若单位、轴定义或数值不完整就停止并报告。
用原生 Veusz 对象生成可编辑 VSZ，并导出 PDF 和 300 dpi TIFF。
```

```text
请用同一数据生成 template=polar_curve。只使用有 RadarOrder 的指标，并严格按
Direction、ScaleMin、ScaleMax 归一化到 0-1（越外越优）。每个 Role=sample 必须
包含全部雷达指标，画闭合填充多边形并保留 marker；Role=reference 缺少的指标不要
插值，只在实际存在的指标轴上标 marker。左侧绘图模块 60x55 mm，参考材料及
Journal/Year 放在右侧保留的 60x55 mm 索引区。输出可编辑 VSZ、PDF 和 300 dpi TIFF，
并检查 exact-current QA 与 transform ledger。
```

生产绘图最终都由同一 Veusz 路线完成。不同编排入口不表示存在另一个前端、renderer 或
视觉权威。

## 模板与全局绘图契约

生产 Veusz 文档构建器只接受九种已完成语义验证的模板：

- `curve`
- `point_line`
- `stacked_curve`
- `bar`
- `box`
- `box_strip`
- `heatmap`
- `scatter`
- `polar_curve`

其它模板必须在请求边界明确失败，不能悄悄退化成曲线图。全局硬样式由
`src/sciplot_core/policy.py` 统一定义，并与 vendored `plot_contract.json` 保持一致。
模板只拥有图形语义和允许编辑的选项；热图标量色带、等高线和色条配色是显式的语义例外。

单位显示也属于全局绘图契约：仪器输入仍兼容 `/`，但坐标轴、色条、图内文字、图例
单位限定、交付绘图数据和分析指标统一使用“单位因子相乘 + Unicode 负上标”，不显示
单位除号，例如 `kJ/m2 → kJ m⁻²`、`W/g → W g⁻¹`、`1/Pa → Pa⁻¹`。
无量纲变量比值不是单位，`σ/σ₀`、`G′/G′ₘ` 等数学表达保留除号。exact-current
VSZ 的 publication QA 会把违反这一规则的可见单位文字作为阻塞问题。

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

`--out` 表示最终用户可见的专用交付目录；省略时，SciPlot 在数据源旁创建
`SOURCE_SciPlot/`。manifest、raw archive、分析表、QA、publication intent、transform
ledger 和运行历史进入同级隐藏 `.sciplot/`，不再堆在显眼的 `outputs/` 下。

用户可见的最小交付只有：

```text
SOURCE_SciPlot/  # 或 --out 指定目录
  data/*.csv
  figures/*.pdf
  figures/*_300dpi.tiff
  project/*.vsz
  Open_in_Veusz.command
```

`project/*.vsz` 内嵌当前全部绘图数据和 Veusz 对象，是可移动、可继续完整改图的
视觉权威，作用上接近单文件科研绘图工程。隐藏运行区保留重新识别、重算、追溯和
验收所需的内部证据，但不属于用户交付。
一个项目登记了多张独立图时，同一次交付必须把全部 ready 图的 VSZ 和对应 PDF/TIFF
放进这一个可见交付目录；任一计划图缺失时，不发布只含主图的半套交付。
交付前应检查隐藏运行区的 `manifest.json`、`review.html`、QA，以及最终可见交付，不能只看退出码。

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
.venv/bin/python -m pytest -q
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

已有 `.venv/bin/python` 时，开发、测试和安装命令统一使用该解释器，不再重复尝试
系统 `python`。如果虚拟环境不存在，只探测一次 `python3` 并按上面的安装步骤创建；
一旦发现解释器缺失、版本不兼容或必须切换执行路径，应在工作更新和
`DEVELOPMENT_LOG.md` 中记录“症状、根因、固定处理方式和验证”，后续任务直接复用，
避免重复产生相同报错。绘图或开发中同一问题经过两次修改仍未解决时，也应停止继续
试参数，先查明根因，再把可复用结论写入当前使用规范或开发文档，并补相应测试。

当前维护优先级见 [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)，模块所有权见本地
`docs/ARCHITECTURE.md`；第三方许可见
[THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。
