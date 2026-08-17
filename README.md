# SciPlot

SciPlot 是面向材料科研日常出图的本地工作流：读取原始数据，按确定性规则生成可编辑的
`studio/document.vsz`，在 Veusz 中完成调整，并交付 PDF、300 dpi TIFF、绘图数据、QA
和可追溯运行记录。

## 文档与产品真相

- 本文是用户工作流和产品边界的唯一说明；
- `skill/SKILL.md` 是自动化代理的操作合同，不另定义产品；
- `docs/ARCHITECTURE.md` 只定义代码结构、模块所有权和依赖边界；
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

绘图交付不要写进 SciPlot 软件或代码仓库内部的 `outputs/`。处理原始数据时优先省略
`--out`，让 SciPlot 在原数据旁创建 `SOURCE_SciPlot/`；确需自定义目录时，也应把
`--out` 指向原数据所在位置附近的专用交付目录。仓库内的 `.tmp_verify/` 只用于开发验证。

交互式日常入口会准备项目并打开原生 Veusz：

```bash
skill/scripts/sciplot studio PATH
```

已知实验规则或展示类型时，可以在同一命令族中直接表达意图：

```bash
skill/scripts/sciplot studio PATH \
  --rule RULE_ID \
  --template TEMPLATE_ID
```

无需打开 GUI 的自动准备、导出和机器可读结果仍使用 `studio`：

```bash
skill/scripts/sciplot studio PATH \
  --export pdf,tiff_300 \
  --json
```

`--json` 表示 headless，不会打开 Veusz。交互入口和 headless 导出是同一个 Studio
生命周期的两种调用方式，不是两套绘图系统。

当 `PATH` 是原始文件或尚未建项的数据目录时，规则、展示模板、项目名和交付目录会先
收敛到一次 Intake 建项，再只执行一次生成式 Studio 准备。成功后的规范请求、Study
Model、VSZ/spec、项目清单和初始 ZIP 属于同一代结果。若这次生成失败，命令仍返回失败，
但可以保留一个明确标记为 `blocked` 的 Intake 项目及诊断 ZIP；它用于排错，不能当作
`ready` 交付。

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

对 task-aware 的普通 `curve`/`box_strip` 图集，Project dock 的 `Samples`
区可以预览、隐藏、加回或重排来源中已经存在的样品。`Apply` 只在当前 Veusz
`Document` 中创建一个原生 Undo 步骤；保存、`Commit figure set` 或
`Save && Export` 才把同一 `active_order` 原子提交到整套 VSZ、spec、规范请求和
figure-set registry。完整 `spec.series`、FigurePlan、原始数值与既有颜色不会因视觉隐藏而
删除或重算。提交后的原生 Undo 会重新成为待提交修订；有待提交修订时 `Save As` 会先要求
提交或撤销，避免产生没有配套项目合同的孤立 VSZ。直接标签和 factorized 自定义图例暂不在
这条窄修订路径内。

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
  --out /原始文件所在目录/Standalone_Export \
  --export pdf,tiff_300 \
  --json
```

独立 VSZ 的 receipt 只证明当前文档和导出制品；它不自动建立原始数据 provenance、
transform lineage 或完整 SciPlot 项目交付。显式重新生成前必须归档人工保存的 VSZ；
打开和导出项目不得静默覆盖人工修改。

## 其它命令的角色

- `plan`：只读解析当前源的有效规则、模板、完整 FigurePlan，以及适用时的
  source-bound `scientific_transform`，供人或本机助手在执行前查看；它不渲染、
  不建项目、不写交付物。
- `app`：仅在需要首次浏览器确认时使用；不是绘图或精修前端。
- `autoplot`：唯一公开的程序化全自动项目入口。它内部复用
  `one-step`/`run_request`，并负责稳定 summary、QA 和 delivery；它不是第三个
  renderer。
- `run`：重放已经确认的 `plot_request.json`。
- `render`、`recipe`：供开发、测试和已知低层合同使用的原语。
- `verify --changed`：公开的开发变更验证入口；按 source-controlled owner 映射选择
  最小测试，不参与绘图、Veusz 编辑或交付。
- `curate torque`：只负责转矩事件选择、复核资料和 Studio 项目准备；最终编辑、导出和
  delivery 仍回到 `studio`。
- `batch`、`smoke`、`acceptance`：开发与回归验证路线，不是另一种用户自动出图入口；
  `batch` 因此不出现在正常帮助中。
- `readiness`、`cleanup`、`mapping`：证据登记或显式维护工具，不创建另一套绘图生命周期。
- `publication`：只查看 profile 和确定性版面元数据；不提供 Composition 编辑器、拼图器或
  独立 renderer。
- `one-step`：内部状态/manifest 合同，不是用户命令。

`run`/`autoplot` 会在已确认的 mapping 或 cleanup 补丁应用后，只根据当时请求中的
`recipe`/`template` 判定一次 auto、命名 recipe 或直接 render。之后即使规则解析补写了
默认模板，也不会把 auto 请求改成直接 render，或绕过语义准备与干预门。命名 recipe
仍允许带显式模板覆盖；字段存在但不是非空文本时会在渲染前失败。

进入 auto 渲染后，规范 `rule_id` 只选择一个执行家族：performance、impact、
mechanical、DMA temperature、rheology 或普通 generic。DSC 现在属于 generic
单任务路径。SciPlot 不再用“逐个尝试
bundle”的方式
判断归属，因此拉伸曲线不会先进入 impact 的模板校验，普通 `point_line` 规则也不会被
impact 路径截走。未知、畸形或带首尾空格的非空规则在任何家族解析或写盘前失败；没有
规则的低层 direct render 仍走 generic。选中的专用 adapter 若明确不接管，只能回退
generic，不能继续探测另一个专用家族；但请求已经选定 `ResolvedFigurePlan` 时必须
失败关闭，不能用 generic 图替代计划任务。
专用或 generic adapter 的选择来自同一 `SemanticRule`，Workflow 不再维护另一张
rule→family 表；这个执行适配器字段不替代独立的 FigurePlan 任务选择。
需要 FigurePlan 的规则同样由该 `SemanticRule` 选择一个内部 plan adapter；解析器不再
按原始 rule ID 维护另一棵家族判断树。独立的低层
`REQUIRED_FIGURE_PLAN_RULE_IDS` 只表达持久化不变量：这些规则必须保存完整计划并走
task-aware 全图集发布门。两者不是同一个概念，当前成员由聚焦合同保持一致；plan adapter
不进入公开 rule payload、调用参数或认证哈希。没有 plan adapter 的规则在读取或哈希源
目录之前即返回“无 FigurePlan”。

需要从原始路径直接生成自动化项目、QA 和 delivery 时：

```bash
skill/scripts/sciplot autoplot PATH \
  --rule RULE_ID \
  --template TEMPLATE_ID \
  --json
```

`--rule` 与 `--template` 会原样进入唯一的 `plot_request.json`，因此外部 AI 可以先用
`rules show` / `plan` 选择意图，再让 Autoplot 执行同一规则和展示模板。显式 rule 为空或
不规范时直接失败，不会悄悄退回自动分类；未传 `--rule` 时才允许现有自动识别。
机器 `invocation.required_arguments` 要求 AI 同时传入 `input` 和 `template`；建议值来自同一规则的
`template.default`，不是 AI 猜测。`plan --template` 和 `autoplot --template` 都记为同一种显式选择，
所以 performance 等可多图规则的预览与执行不会一个返回全图集、另一个只返回单模板。
人类仍可以省略 template 使用现有自动默认；这只是要求外部 AI 走可重现的显式路线。
显式规则还会在读取科学源之前检查当前 validated envelope：current 才继续；missing 或
stale 时，`rules list/show`、`plan` 与 `autoplot` 返回同一组既有 repair reason。
此时 Autoplot 不创建项目、不调用 runner，也不写 summary。认证通过后若输入不存在，
只在 runner 前做一次路径存在性检查，不会先写出半个项目。

对 `rheology_frequency_sweep`、`rheology_temperature_sweep`、
`rheology_stress_relaxation`、`dma_temperature_sweep`、`tensile_curve`、
`compression_curve`、`flexural_curve`、
`impact_metric`、`performance_comparison`、`dsc_curve`、`tga_curve`、`dtg_curve`、
`uvvis_spectrum`、`xrd_pattern`、`saxs_profile`、`gpc_sec_chromatogram` 和
`swelling_curve`，Studio 与
Autoplot 在渲染前共同解析
一份 `ResolvedFigurePlan`。它固定本次选中的
逻辑图 ID、顺序、指标、模板、条件/样品轴、兼容输出文件名和准备时的源内容指纹；
渲染器只执行这些任务，不能再自行增删图。保存过的计划若与当前规则、模板、Study
Model 或源文件字节不一致，复用旧 VSZ 或直接发布都会停止，而不是沿用旧的 ready
结果。显式重新生成可在同一规则内根据当前源重新解析计划，但不能跨规则静默刷新。

语义准备也只选择一个内部 adapter：rheology、curve-family、mechanical，或明确的
identity。SciPlot 不再按固定顺序调用三个 handler 来猜谁接管；`SemanticRule` 选择一次，
该 handler 返回 `None` 就直接使用统一 identity，不再尝试下一家。只提供旧式
`semantic_family` 的内部调用仍通过现有 catalog 唯一匹配规则，不维护第二张 family 表。
这项元数据不进入公开 rules payload 或认证哈希。已登记的单曲线规则，包括
`dsc_curve`，由 curve-family adapter 直接物化同一个 resolved transform，不再进入
图族专用拒绝或二次解析分支。

机械 FigurePlan 由一套共享合同生成，不能再由 Study Model、Studio 和 Workflow 各自
解释。拉伸依次交付应力–应变曲线、强度、断裂伸长率、模量和韧性五张图；压缩和弯曲
各交付一张曲线与一张强度图。曲线默认选择“保留强度距组内中位数最近”的真实试样，
拉伸同距时再比较断裂伸长率，最后按源顺序决定；可以显式选择逐试样曲线，但不允许把
曲线静默平均。所有汇总任务固定为 `box_strip`，使用线性四分位数、median/IQR、1.5 IQR
须线和可见原始点，不显示 mean 或 sample-SD。终端证据逐任务绑定原始源哈希、准备表、
绘图表、样品顺序、重复数、指标、单位、模板、调色板解析和实际 series encoding；任何
冲突都使整组失败并回滚，而不是留下部分图。当前登记数据为拉伸 `E0 2MM` n=9、压缩
`Conventional PU foam` n=6、弯曲 `A_HA56` n=6；这些 n 来自明确试样身份，不从普通
数字标签猜测重复关系。

温度流变扫描固定生成两张 `point_line` 图：先生成
`storage_modulus_vs_temperature`，再生成稳定身份为
`tan_delta_vs_temperature`、机器指标为规范 `loss_factor` 的第二张图。两张图共享
源文件派生的样品顺序和同一次语义准备；Studio 与 Autoplot 都必须保留精确任务证据，
并整体交付两份 VSZ、两份 PDF 和两份 300-dpi TIFF。任一任务、源指纹或终端证据不一致
时整组失败，不留下部分 ready 结果。
该图族在一次事务中只解析一次原始多指标数据：同一个内存中 typed domain 同时保存
raw samples、按请求合并/排序的 prepared samples、样品与重复事实。FigurePlan 和语义准备
消费同一对象，不得各自重读、重新合并或重新排序。这不是单 y 科学变换，因此
`plan` 仍诚实返回 `scientific_transform: null`，不伪造 dummy transform。

DMA 温度扫描是独立合同，不借用温度流变的双图解析器。它固定生成一张
`storage_modulus_vs_temperature` `point_line` 图，横轴为温度，纵轴只允许储能模量
E-prime；tan delta/损耗因子不能匹配该任务。源模量单位必须明确为 Pa、kPa、MPa 或
GPa，先统一到规范 Pa，再以 MPa 写入绘图表和坐标轴。语义准备保留源中所有有限
测量点，包括合法的负响应值；点数和值只从当前输入读取。VSZ spec 的
`axis_data_visibility` 同时记录规则
默认 `y_min=0` 以下的潜在点数和最终有效轴实际裁掉的点数；自动放宽边界不能再把
“可能受默认值影响”误写成“已经裁点”。Studio 与 Autoplot 共享同一源指纹、样品顺序、
准备证明、终端任务和一份 VSZ/PDF/300-dpi TIFF 结果。

Workflow 中显式命名的 `recipe: rheology_dma` 只在规则已经解析为
`dma_temperature_sweep` 且存在上述精确 FigurePlan 时进入同一执行路径。manifest 仍记录
`route=recipe` 和 `final_recipe=rheology_dma`，但该路径没有独立 `curve` 默认、复制后模板
推荐或第二次数据选择；它复用 auto 的语义准备、源证明、密封终端表和单任务安装器。
渲染前会核对 recipe/规则、计划任务、源指纹、样品顺序、指标、单位以及会裁掉原始点的
显式轴范围；冲突不会产生 processed、figure、manifest 或 delivery 制品。两条入口都
记录同一份 route-neutral DMA 执行证据，其哈希覆盖终端数据、单位、编码和
`axis_data_visibility`。其他带 FigurePlan 的命名 recipe 仍失败关闭。

当前 `dsc_curve` 是 shared registered paired-curve 规则。它从普通 CSV 或
XLSX 中唯一匹配的 Temperature/Heat Flow 配对表读取显式单位、样品身份、
源顺序和实测值，再由 shared `registered_single_curve` 计划生成一张
`dsc_heat_flow_vs_temperature` `curve` 图。Workflow 与 Studio 都执行普通
generic 单任务生命周期，整体交付一份 VSZ、一份 PDF 和一份 300-dpi TIFF。

登记 fixture 旁的 `digitization_provenance.json` 只是该 fixture 的来源与数字化
证据，不是普通 DSC 输入的 runtime 附件；用户自己的 CSV/XLSX 不需要
DOI、论文字段或相邻 provenance 才能解析。源绑定使用共享 source-tree 身份。
一个 workbook 若有多个 worksheet 同时匹配登记坐标轴，则作为歧义失败关闭，
不会暗自选择 cooling/heating、展开相位或切换到 `stacked_curve`。一条普通
DSC 曲线也不能自动宣称 Tg、熔融/结晶峰身份、焓或结晶度；真正的仪器
循环语义仍需独立、有真实协议证据的规则。

流变频率扫描保留 Study Model 现有的四张默认图：储能模量、损耗模量、损耗因子和复数黏度。
若当前工作簿还含有受支持且旧 Autoplot 路线会输出的复数模量列，该图也进入同一计划，
不会因入口不同而被静默遗漏。抗冲击强度的非 `point_line` 多工作表输入仍按每个条件
生成一张独立图；条件的逻辑 ID 不依赖工作表排列，并兼容中文、空格和标点。
`point_line` 仍是把已确认的兼容条件合并为一张比较图。

DMA 频率扫描当前只声明并生成源文件明确提供的储能模量—角频率单图；解析后的
FigurePlan 会替换 Study Model 的预解析占位任务，并绑定同一任务的最终制品。

分类重复数据的科学识别与图形表达彼此独立。规则负责样品、重复值、单位和指标语义；
presentation contract 负责允许的图形。以抗冲击强度为例，同一数据可显式选择：

```bash
skill/scripts/sciplot autoplot PATH --template bar --out /原始数据所在目录/bar_SciPlot
skill/scripts/sciplot autoplot PATH --template box --out /原始数据所在目录/box_SciPlot
skill/scripts/sciplot autoplot PATH --template box_strip --out /原始数据所在目录/box_strip_SciPlot
skill/scripts/sciplot autoplot PATH --template point_line --out /原始数据所在目录/point_line_SciPlot
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

材料性能对比共用一个由 `performance_comparison/` 和对应测试共同约束的长表合同。
每行只能表示一个“材料–指标”数值，不能把重复行静默平均。必需列和常用可选列为：

| 列 | 含义 |
| --- | --- |
| `Material` | 材料或样品名。 |
| `Role` | `sample` 表示本工作样品，`reference` 表示文献/参照材料。 |
| `Metric`, `Value`, `Unit` | 指标 ID、有限数值和单位；同一指标的元数据与单位必须一致。 |
| `Group` | 本工作样品的包络组；同组样品共享色系和浅色包络。 |
| `EnvelopeInclude` | 可选的 `true/false`；控制材料是否参与浅色包络，默认样品纳入、参考材料不纳入。样品按 `Group` 分组；参考材料按 `LegendGroup` 分组。 |
| `DisplayLabel` | 轴上显示的指标名。 |
| `ScatterAxis` | 散点图中恰好一个指标写 `x`、一个指标写 `y`。 |
| `ScatterMin`, `ScatterMax` | 可选的散点轴显示边界；允许只声明一侧，但不得裁掉任何绘制数据。 |
| `RadarOrder` | 雷达轴顺序；至少三个指标，正整数不得重复。 |
| `Direction` | `higher` 或 `lower`，统一为“越外越优”。 |
| `ScaleMin`, `ScaleMax` | 雷达归一化的声明边界；数据越界时拒绝绘图。 |
| `Journal`, `Year`, `DOI` | 参考材料的文献元数据；未给显式 `LegendLabel` 时，期刊和年份显示在右侧索引。 |
| `MaterialOrder`, `Marker` | 可选的索引顺序和显式 marker。 |
| `MarkerLineColor` | 可选的 marker/多边形轮廓色，必须是 `#RRGGBB`；可让同一文献大类共享轮廓色，同时保留不同 marker。 |
| `MarkerFillColor` | 可选的散点及右侧图例 marker 内部色，必须是 `#RRGGBB`；参考材料默认白色，本工作样品默认使用样品蓝色。雷达图不采用这个覆盖。 |
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
这个区域只表示已观察样品范围，不是置信区间。参考材料默认保持中性、空心且可由
marker 区分；也可用显式 `MarkerLineColor` 给同一大类设置共同轮廓色。需要强调读者
分组时，可用同一个显式 `MarkerFillColor` 填充一组 marker，
并将该组设为 `EnvelopeInclude=true`。模板会按 `LegendGroup` 生成无边框、透明度更高
的同色参考包络；单点和双点分组分别形成小色斑和细长包络，同时保留中性轮廓与 marker
形状冗余。模板提供十六个 Veusz 原生 marker；全局唯一约束作用于
`LegendIdentity`，同一
材料身份的多个观测点可以共用 marker 并合并为一个索引条目。每列行距按条目数在固定
高度内确定性计算；需要压缩本工作样品图例时，可在同一分组内显式设置每行两个条目。
当散点源已经归并为不超过四个大类，并且每个条目的
`LegendIdentity`、`LegendLabel`、`LegendGroup` 三者同名且不需要自动追加文献时，
模板改用全局图内图例自动避让契约，整图保持 `60x55` mm；其余详细索引仍保留右侧
`60x55` mm 模块。

雷达图把 `RadarOrder=1` 的轴置顶，后续轴按逆时针顺序排列。本工作样品是闭合的
marker 多边形：轮廓使用样品主色，填充使用对应浅色并保持 35% 透明度。参考材料只在
确有数据的指标轴上标 marker，不补齐或连成虚构多边形；`MarkerLineColor` 可按大类
着色轮廓，但内部仍保持白色空心。单行轴名使用左 `60x55` mm 绘图模块；只要任一轴名
包含显式换行，就以 6 pt 的逐行原生 Veusz label 绘制。存在参考材料、文献信息或较多
本工作样品时，右侧保留另一个标准 `60x55` mm 索引模块，因此一列索引的雷达图总图幅
为 `120x55` mm，并可与其它 60 mm 图模块对齐。径向分度使用与雷达轴数一致的浅灰
虚线多边形；不使用圆形网格。每个外顶点旁单独显示纯数字端点：`higher` 指标取
`ScaleMax`，`lower` 指标取 `ScaleMin`；轴标题和单位排在数字外侧，不添加
`Max`、`Range` 或方向箭头。

source-controlled 示例仍只承担确定性合同回归；本机验收使用经用户授权并完成日常使用
确认的 m-rPA/rPA 真实数据摘要。`performance_comparison` 已通过 scatter 与
`polar_curve` 的完整 acceptance 并进入 `ready`。只有严格满足上述长表合同的数据才会
被自动识别。未显式选择模板时，同一计划按 scatter、`polar_curve` 顺序生成两份
独立可编辑 VSZ，并在一次 exact-current 发布中交付各自的 PDF 和 300-dpi TIFF；
scatter 是唯一主图 presentation identity。显式选择模板时计划只含对应的一项任务。
需要明确选择图形时可使用：

```bash
skill/scripts/sciplot studio PATH \
  --rule performance_comparison \
  --template scatter \
  --out /原始数据所在目录/material_scatter_SciPlot

skill/scripts/sciplot studio PATH \
  --rule performance_comparison \
  --template polar_curve \
  --out /原始数据所在目录/material_radar_SciPlot
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
Direction、ScaleMin、ScaleMax 归一化到 0-1（越外越优）；第一轴置顶，后续轴逆时针
排列。每个 Role=sample 必须包含全部雷达指标，画闭合填充多边形并保留 marker；
Role=reference 缺少的指标不要插值，只在实际存在的指标轴上标 marker。单行轴名使用
左侧 60x55 mm 绘图模块；有显式换行时使用逐行 6 pt 原生 label。参考材料及
Journal/Year 放在右侧标准 60x55 mm 索引区，使一列索引的总图幅保持 120x55 mm。
分度背景使用与轴数一致的浅灰虚线多边形，不使用圆环。每个外顶点只显示与声明边界
一致的纯数字端点，指标名和单位置于其外侧。输出可编辑 VSZ、PDF 和 300 dpi TIFF，
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
`src/sciplot_core/policy/` 统一定义，并与包内的 `plot_contract.json` 保持一致。
模板只拥有图形语义和允许编辑的选项；热图标量色带、等高线和色条配色是显式的语义例外。

普通序列颜色也只有一个权威链：请求中显式声明的 `palette_preset` 或
`palette_colors` 优先；直接低层请求中实际提供的颜色选项视为显式选择；其余情况统一使用
共享 `control_first_bright`。`jama_editorial`、`npg_modern` 和 `tol_bright`
仍可显式选择，但不会再被模板或历史请求静默提升为当前意图。每个 Veusz spec 都记录
`palette_resolution`（最终 palette、色值、选择来源及优先级），`doctor --json` 同时审计
Python 默认、`plot_contract.json`、样式、模板和 ready rule 是否一致。

普通 XY 序列的颜色、线型、marker 与 marker 填充也只解析一次。最终序列顺序确定后，
显式 `line_style_sequence` 和 `marker_sequence` 按该顺序逐项绑定；`series_styles` 的逐序列
覆盖和 `marker_fill_mode` 在同一解析器中合并。每个 Veusz spec 保存顶层
`series_encoding_contract` 以及每条序列的 versioned `encoding`，VSZ 写入器只消费这份结果，
不再自行猜颜色或线型。exact-current 审计会逐项核对请求明确拥有的颜色、线型、marker、
填充色和轮廓色；未由请求锁定的通道仍可在原生 Veusz 中手工调整。性能散点/雷达图和热图
继续使用各自的语义图形合同，不借用普通 XY 序列编码。

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

规范 `plot_request.json` 的顶层 `rule_id` 是 Studio 发布时唯一的规则身份。每次发布都会
重新查询当前中央规则：项目保留的 `pending_rule_review=true` 或当前规则状态不是
`ready`，任一条件都使最终发布成为 `needs_rule_repair`。

规则型项目成功生成时，还会在同一回滚事务中把版本化
`studio_rule_contract_binding` 写入规范请求；它记录准备时的完整/语义规则哈希，以及当时
validated-envelope 认证的 current、missing 或 stale 状态。普通“打开并沿用现有 VSZ”
只保留这份证据，不会按后来变化的中央规则偷偷刷新。发布会在收集图和分配运行目录之前，
比较准备时合同、当前中央合同和当前认证合同：三者不一致、当前认证缺失/过期，或旧规则
项目没有 binding，都允许继续编辑，但不能作为 ready 结果交付，必须重新准备。空规则
兼容路径不要求 binding。

`pending_rule_review` 仍只表示规则审阅问题；纯合同过期使用独立的
`publication_rule_blocked` 和结构化 blocker，不伪装成 pending。相同 v2 证据贯穿 exported
semantic、result、manifest、最终 payload、项目 registry 和原生状态；首次写入前若投影
分裂，finalizer 会拒绝。在 managed 发布证据及 exact-current artifact QA 仍然当前时，
Project 状态面板显示具体修复原因；即时导出警告仍是通用提示。制品 QA 即使通过，也不能
单独把规则或合同受阻项目变成可交付的 `ready`。

Intake recognition 只保留与规范 `rule_id` 相符的历史解释和轴契约，不能覆盖当前规则的
生产状态、干预要求或缺失条件；请求没有规则身份时，旧 recognition 也不能把它恢复出来。
空规则兼容路径仍保留，未知非空规则以及畸形的规则/审阅字段会在分配发布运行目录之前
失败。显式改选规则或模板会先使旧 binding 失效，只有随后成功重新生成才会写入新
binding；仅改项目名保留原证据。以上操作都不能绕过阻断。

浏览器 Intake catalog 只维护分组、标签、图标和唯一 `rule_id` 等导航信息；模板、支持的
呈现选项、渲染默认值和重复模式均由当前 `SemanticRule` payload 投影。同一非空规则不能
出现在两个可选入口中，不支持的 `torque_offset_stack` 不再作为独立能力公开。浏览器没有
隐藏的 `replicate_mode=mean` 开关：未显式提交时使用规则推荐（例如力学曲线的
`representative`），显式 API 选择原样保留，未知选择会在写项目之前失败而不是静默回退。

Studio 每次准备或发布还会从规范请求和当前规则的 presentation contract 解析一份版本化
`presentation_identity`，由 `rule_id` 和本次选中的 `template` 组成。显式支持的模板优先
于同规则 recognition 保存的历史默认；未指定时才采用当前规则默认并写回规范请求。
`presentation_identity` 只约束本次主图；一个 `ResolvedFigurePlan` 可以包含使用其他
模板的副图，每份 VSZ spec 都必须携带并匹配自己的完整 `FigureTask`。新生成的多图项目
使用严格的 figure-set registry v2，按计划顺序绑定每个任务、最终文档路径和 spec；
旧 registry v1 仍可读取，但不作为精确任务证据。任务、模板或路径分裂会在第一次文件
替换或 run 分配前失败。手工或旧版 exact-current VSZ 可以没有 spec，发布证据会把主图
身份与 VSZ 当前哈希并列绑定，而不从 VSZ 内容反推模板。exported semantic、result、
manifest、最终 payload 和项目 registry 携带同一主图身份；semantic 普通字段中的
`template` 仍描述认证规则默认，不会因本次呈现选择而改写科学合同。

`--out` 表示最终用户可见的专用交付目录，而不是软件内部工作目录；省略时，SciPlot 在
数据源旁创建 `SOURCE_SciPlot/`。manifest、raw archive、分析表、QA、publication intent、
transform ledger 和运行历史进入同级隐藏 `.sciplot/`，不再堆在显眼的 `outputs/` 下。

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
放进这一个可见交付目录。每个计划任务必须精确绑定一份 VSZ、一份 PDF 和一份
`_300dpi.tiff`；跨任务错配、路径复用、快照或哈希不一致以及任一计划图缺失都会阻止
完整状态，不能发布只含主图的半套交付。
交付前应检查隐藏运行区的 `manifest.json`、`review.html`、QA，以及最终可见交付，不能只看退出码。

## 检查与首次确认

查看程序如何理解输入：

```bash
skill/scripts/sciplot inspect PATH --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show RULE_ID --json
```

`rules list --json` 与 `rules show --json` 的 `invocation` 共用同一投影。静态操作、参数和
模板选项来自一个 `SemanticRule`；动态 `availability` 与 `reason_codes` 来自当前
validated-envelope certification。它声明当前规则是否可生产调用、只读预览使用 `plan`、
稳定出图使用 `autoplot`、必需的 `input`、固定 `rule_id`，以及 `template` 的默认值和合法选项。
外部 AI 应只执行 `availability=ready` 的规则，并把同一组 rule/template 先交给 preview、
再交给 render；不能从样品名、文件名或提示词自行发明另一套调用参数。

普通外部 AI 的稳定调用闭环只有一条：从 `rules list/show` 读取一个
`availability=ready` 的 `invocation`，把其中同一组 `rule_id` 和 `template` 交给
`plan`，仅在预览未阻断时再原样交给 `autoplot`。最终只接受机器结果中的
`state=ready`；`blocked`、`needs_human_confirmation` 或 `needs_rule_repair` 应直接报告
其结构化原因，不能换规则、猜单位、改样品身份或绕过认证。

查看程序在真正执行前会选择哪些图、以及 source-bound 科学变换，不创建项目或交付物：

```bash
skill/scripts/sciplot plan PATH --json
skill/scripts/sciplot plan PATH --rule RULE_ID --template TEMPLATE_ID --json
```

空或未知规则、不支持的模板、缺失输入和可预期的源检查错误都会返回同一个 v1
`status=blocked` 机器 payload 与非零退出码；不会改成散落的 stderr 文本，也不会吞掉
真正的程序错误。

对其他显式带 `--json` 的公开命令，参数解析成功后的运行期失败也会
在 stdout 返回唯一 `sciplot_cli_runtime_error` v1 payload 并以 1 退出，
不会途中切换成 stderr 的 `Error:` 文本。路径、编码、JSON、I/O 与明确值错误
标记为 `expected_runtime_failure`；断言、类型、键错误及其他意外异常标记为
`internal_error`，不会伪装成科学源输入有误。未带 `--json` 时保留原有人类文本与
恢复提示；argparse usage 仍为 usage 文本和退出码 2，`plan` 仍使用上述专用
blocked v1 合同。

`planned` 返回完整 FigurePlan 任务集；`not_applicable` 只表示该源不使用 FigurePlan，
不表示科学变换不可用。应力松弛会在同一 v1 payload 的 `scientific_transform` 中预览
实际 Time / Shear Stress / Shear Strain 列、单位、每组锚点与 σ₀、归一化、真实时间策略、
锚点保留、轴兼容性、点数和排除原因；随后 semantic preparation 使用同一个 resolved
transform 写表，并把同一合同放入既有 `semantic_preparation` step。锚点时间和值只能
来自当前源或显式用户选择；程序没有固定 onset 时间，`0.077` 也不是任何默认值或算法常量。
带 result/interval 身份的应力松弛源以最终共同 interval 的第一个实际对齐点作为源边界，
不会再用尾部百分比、固定点数、漂移容差或“平台”经验门槛挑 onset；有限值、时间身份、
非零归一化基线和 log-time 正域等通用不变量仍会严格检查。当前 interval 的单位只从
表头到首个数值行之间、所选 Time/response/control 列的显式证据读取；时间必须等价于
`s`，响应与控制必须等价于已支持的规则单位。缺失、冲突或需要尚未实现换算的 `min`、
`kPa` 等单位会在变换前阻断，不会靠固定行偏移、首个数值或默认标签伪造单位。
DMA temperature 在
同一字段中预览每组 Temperature / Storage Modulus 列、MPa→Pa→MPa 单位路径、原始行序、
候选/保留/空尾行以及线性登记轴与数学 log 兼容性的区别；它明确报告 anchor 和 scientific
normalizer 不适用。DMA 的同一次 plan 解析同时供 transform 与 source-bound FigurePlan
使用，不会为两个 payload 重读源表。DSC、TGA、DTG、UV-Vis、XRD 和 SAXS 共用 registered
paired-curve transform/FigurePlan 骨架：一个受支持表文件中的一组或多组配对列、显式且与
规则等价的单位、源生样品身份、点数、坐标顺序和行排除都从当前源读取；缺少单位或尚未实现
转换的单位会阻断，不会靠默认单位改标签。TGA 生成 `temperature → mass`；DTG 生成
`temperature → derivative_mass` 并原样保留响应正负号，绝不从 TGA 重新求导；UV-Vis
生成 `wavelength → absorbance`，保留每个样品独立且可降序的波长坐标；XRD 生成
`diffraction_angle → intensity`，保留各序列独立网格，其最大观测强度位置只作描述。
PANalytical Data Collector 的混合宽度 CSV 由 `[Measurement conditions]` 和 `[Scan points]`
结构提供角度、原始 detector counts 与声明点数证据；程序逐点保留原始强度数值、不做
归一化，并按登记的 `Intensity (a.u.)` 轴展示。声明点数与扫描行或有限点不一致时会阻断。
SAXS
生成 `q → intensity`，保留线性 q 坐标与源中正的 log-y 显示域，仅排除 log-y 不允许的
非正响应，不额外执行 log10/ln、排序、插值或结构归属。DSC 生成
`temperature → heat_flow`，同样不从数值推断热转变身份。semantic preparation 只物化同一个
snapshot，Workflow 与 Studio 再复用通用单任务、Veusz、QA 和交付生命周期。该共享 owner
不拥有固定样品名、固定点数、固定首末值、峰位、锚点、onset 时间或归一化常量。GPC/SEC
也使用同一个通用单任务下游，但只增加薄的 Agilent 校准分布源适配：样品名保持工作簿原文，
横轴直接读取 Slice Table 的 `Mw (g/mol)`，纵轴直接读取 `dW/dLogM`，并用同表 `LogM`
逐点核对分子量坐标；源行序和值原样保留，横轴按登记合同作对数显示。程序不会添加
`Sample` 前缀、改成 `a.u.`、重新归一化，或从 RT/RI 原始色谱自行推断分子量、Mn、Mw、Đ；
缺少显式校准分布列时会停止。
FTIR 也进入同一个单任务下游，但使用薄的 FTIR source adapter：每个实际文件只读一次，
headerless 两列数据保留全部有限点、零值、源坐标和源行序，响应身份保持中性的
`Spectral response`；只有源表头明确声明时才使用 Transmittance 或 Absorbance，单位缺失不会
补猜。显式 Transmittance 只报告观测最小值位置，显式 Absorbance 只报告观测最大值位置，
未知响应跳过该分析。程序没有 `%T` 数值阈值、固定 400–4000 输入域、固定峰位、FTIR 专用
renderer 或第二 request/schema；坐标反向仅是可编辑显示策略，不改变源点顺序。
swelling 也进入同一个单任务下游。它要求唯一受支持文件和唯一匹配的有标签表；每组
Time/ratio 列只保留其首个有标签数值段；只有整行不含结构文本的孤立格式空行可以桥接，
长断段或非数值结构
会终止该段，后续无标签数值只记录为排除证据而不会重新拼回曲线。时间只接受表头或相邻
单位行明确且不冲突地声明的秒、分钟或小时并统一换算到小时，裸 `Time` 不会被猜成小时；
数值分隔符只由已选中的首段判断，断开数据不能反向解释保留值；condition、replicate、
样品顺序和每个保留点都保留当前源身份。该 transform、单任务 FigurePlan、prepared
CSV、Workflow bundle 与 Studio queue 复用同一 snapshot，不另设 swelling renderer 或 schema。
其他专用准备器也遵守同一证据原则：
torque 在没有显式 curation 时保留完整源曲线和绝对时间，自动 peak/drop 只作为用户主动
`curate torque` 的建议，而且时间必须显式声明为秒、分钟或小时、响应必须明确为等价的
`N·m`；Index、裸 Time 或缺失扭矩单位不能进入终端表。Impact 缺少明确单位时在写表前
阻断，不能默认成 `kJ m⁻²`。
其他尚未接入声明式变换的规则返回
`scientific_transform: null`。`blocked` 返回稳定阻断原因并使用非零退出码。
该结果是只读意图预览，不是渲染或交付证明。

一次 `autoplot`、`run` 或 Studio preparation 事务会先形成一个 typed
`ResolvedScientificSource`，把当前源身份、图族 domain 和适用的 FigurePlan 一起传到准备与
渲染；后续路由不得重新解析该图族。auto、显式 template 和 named recipe 都遵守这条
边界。是否需要这个快照由同一 `SemanticRule` 的内部 scientific-source adapter 决定；
共享 resolver 不再按 raw rule ID 猜图族，pending 与普通规则也不会提前读取数据。
这个 domain 可以是带声明式合同的单曲线科学变换，也可以是不序列化的多指标源快照；公共
request、preview、ledger 和认证哈希不因内部 domain 类型增加字段。
anchor 的时间和值只能来自当前源的检测结果或显式请求，不存在任何测试样本时间
默认值；任何某次实验出现的具体坐标都只是数据，不进入程序策略。单独执行的 `plan` 与稍后执行命令共享同一 resolver 和合同，但跨命令、跨 HTTP
确认不会伪称保留同一个 Python 对象。
adapter 可预期的数据失败只通过既有 `reason_code + message` 对外报告；Plan、Studio 与
Workflow 消费同一个 typed 内部错误。其它 `ValueError` 不再被兜底伪装成数据问题。

私有 terminal-source binding 在父进程只由 `seal()` 校验一次并捕获 request hash，在 worker
入口再做一次跨进程当前态校验；同一 worker 内的 Studio/series 消费者只检查样品顺序、点数
和 source-artifact 结构，不重复整套文件哈希。归档、重开、安装和发布仍是独立 authority
边界，不能用这条同事务去重绕过。

目录形式的 rheology temperature 与 rheology frequency 共用一个进程内
`ResolvedRheologySweepDomain`。它只解析 parser 实际选择的原始文件一次，并把相同的
样品顺序、重复数和准备后多指标数据同时交给 FigurePlan 与 semantic preparation。频扫
目录中的邻接分析工作簿不会替代原始文本；只有每个已选样品都至少含一个配对数值点的
指标才会进入任务和准备工作簿，显式或由 G′/G″ 计算得到的 complex modulus 遵守同一
条件。单个 plot-ready XLS/XLSX 仍保留原有直接路径。显式选择 frequency rule 时不会先跑
temperature shape detector。这个共享 domain 不序列化，也不新增 cache、receipt 或 hash
ledger。
流变文本的小数分隔符只从 parser 已经选中的坐标/响应列判断，不扫描备注或其它表格；
一两个 `0,5` 值也能被正确解析。点/逗号小数明确混用或没有其它证据的歧义分组会阻断，
不会再用“至少几个点”或多数票猜 locale 并静默放大数值。

浏览器 Result Review 只投影本次 run-local manifest 中已经落盘的合同；尚未运行的 prepared
项目则只投影 canonical `plot_request.json`。Veusz Studio 的只读项目状态使用同一纯投影，
切换到另一份 VSZ 后立即清空旧 review。上述界面不重读原始数据，不另建 review ledger；
真正需要绘图前审阅时使用 `plan`。

只有明确需要浏览器首次确认时才使用：

```bash
skill/scripts/sciplot app PATH --out /原始数据所在目录/SOURCE_SciPlot
```

确认完成后回到 Studio/Veusz；浏览器结果页保持只读。

## 工程验证与证据边界

日常代码迭代默认从当前 `HEAD` 的 staged、unstaged 和 untracked 变化出发：

```bash
skill/scripts/sciplot verify --changed --json
```

该命令合并变化一次，并按 source-controlled owner 表稳定选择检查：对仍存在的已改 Python
文件运行一次 Ruff，对显式 owner targets 运行一次 `pytest -m focused`，只在命中
`pyproject.toml` 已声明的类型范围时运行一次 mypy，并做一次 tracked diff whitespace
检查。未知 production/configuration 路径会
直接失败并要求补齐 owner；它不会因未知影响范围退回全量 focused、comprehensive、full、
smoke 或 acceptance，也不生成或修改 VSZ。

测试分为单模块、进程内的 `focused` 层和跨 Veusz/导出/Studio 生命周期的
`comprehensive` 层。迭代从最小相关测试开始，按影响范围逐级扩大：

```bash
.venv/bin/python -m pytest -q tests/test_x.py::test_y
.venv/bin/python -m pytest -q -m focused
.venv/bin/python -m pytest -q -m comprehensive
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy
```

`mypy` 当前只对 `pyproject.toml` 明确列出的 `foundation/`、
`json_contract.py`、`figure_plan/`、`delivery/plan_binding.py`、
`delivery/package_builder.py`、`delivery/package_validation.py`、
`study_model/package_contract.py`、`publish_state.py` 和
`autoplot/publish_integrity.py`、`autoplot/evidence.py`、
`autoplot/summary.py` 42 个文件执行严格基线检查，不表示全仓已经完成静态类型覆盖。

完整 `pytest` 和 acceptance 是 release/merge gate，不是未知 owner 的自动兜底。
具体 owner 选择与升级规则由 `skill/SKILL.md` 和 source-controlled 验证合同统一定义。

命令或运行时合同变化在 handoff 时运行一次 Doctor；跨 Studio、renderer、worker、export、
QA 或 delivery 的工作只在最终跨边界 milestone 运行一次 smoke：

```bash
skill/scripts/sciplot doctor --json
skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json
git diff --check
```

共享样式、渲染、规则、QA 或 delivery 合同的 acceptance 只在 release/merge gate 运行：

```bash
skill/scripts/sciplot acceptance rules --out .tmp_verify/acceptance --json
```

`acceptance rules` 会机器校验 PDF 尺寸、TIFF DPI 和交付副本一致性；contact sheet
只是用于检查裁切、遮挡和损坏的未校准预览，不能证明最终尺寸可读性。检查后用
`skill/scripts/sciplot acceptance visual-review PATH/final_size_visual_review/final_size_visual_review.json --decision passed|failed --reviewer NAME --json`
记录结论；最终尺寸可读性仍需校准显示器或打印件证据。

完整基线认证仍使用 `readiness certify`。当只有少数规则合同变化且已有当前全规则基线时，
维护者可把一次已通过人工视觉复核的 scoped acceptance 合并进同一 registry schema：

```bash
skill/scripts/sciplot readiness merge BASE_REGISTRY ACCEPTANCE_SUMMARY \
  --out CANDIDATE_REGISTRY \
  --json
skill/scripts/sciplot readiness status --registry CANDIDATE_REGISTRY --json
```

`merge` 只替换本次 `selected_rule_ids` 的严格验收条目；每个未选条目的基础认证必须仍与当前
规则合同一致，否则失败。registry v2 的 lineage records 必须无重叠地覆盖全部条目，并分别
保留实际 acceptance summary 的身份。旧 registry v1 仍可读取，但新建和合并结果统一写 v2。
该命令只生成候选 registry，不自动安装、不重跑未选规则，也不建立第二套认证目录或手工哈希。

runtime smoke 是 synthetic 变化门，不是真实数据证据；生命周期、artifact QA、
provenance、人工日用验证和期刊合规仍是不同声明。

## 当前本机开发环境与代码入口

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[studio,dev]'
skill/scripts/sciplot doctor --json
```

已有 `.venv/bin/python` 时统一使用它；缺失时只探测一次 `python3` 并按上面创建。
环境故障和重复问题的记录规则见 `skill/SKILL.md`。
这里描述的是当前源码开发环境；安装版和分发工作只是暂缓，不是对 SciPlot 长期产品形态
的重新定义。

当前维护优先级见 [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)，代码和模块边界见
`docs/ARCHITECTURE.md`，第三方许可见 [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。
