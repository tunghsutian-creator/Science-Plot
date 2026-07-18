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
[docs/SCIPLOT_OPERATION_FLOW_PLAN.md](docs/SCIPLOT_OPERATION_FLOW_PLAN.md)；确定性数据映射的
安全边界与验收证据见
[docs/SCIPLOT_DATA_MAPPING_M3_AUDIT.md](docs/SCIPLOT_DATA_MAPPING_M3_AUDIT.md)；Assistant
请求生命周期与界面审计见
[docs/SCIPLOT_CANVAS_M3_PROVIDER_UI_AUDIT.md](docs/SCIPLOT_CANVAS_M3_PROVIDER_UI_AUDIT.md)。
原生拼图模型、编译、画板和交付证据见
[docs/SCIPLOT_COMPOSITION_M4_AUDIT.md](docs/SCIPLOT_COMPOSITION_M4_AUDIT.md)；
确定性 `ready_to_use` 的证书、权威边界和验收证据见
[docs/SCIPLOT_READINESS_M5_AUDIT.md](docs/SCIPLOT_READINESS_M5_AUDIT.md)。

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

当前已完成 M0/M1、M2 的工程内核，以及 M3 的可逆 Assistant 事务内核、确定性数据映射
执行内核、provider-neutral 请求生命周期和生产 OpenAI Responses adapter：统一
Canvas 会话、封闭的类型化操作、选择驱动的页面/图区/轴/曲线/箱线/图例/标量场/标注
检查器、数据点选择、直接标注拖动、结构 QA、审阅批注、`DataMappingProposal` v2、
独立确认收据和 transform ledger 已经建立。原生 Qt
Canvas 直接嵌入 `PlotWindow`，处理选择、编辑、撤销/重做、保存、恢复、精确导出、QA
和项目交付。界面支持系统 palette 驱动的明暗/高对比主题、窄窗口浮动检查器、`Tab`
Canvas-only、菜单/快捷键对等、可访问名称和跨重开状态持久化。

M2 的非导出审阅层也已实现：五种工具、五类坐标锚点、独立 sidecar、关闭重开、审阅到
Veusz 原生标注的类型化晋升，以及撤销/重做和精确导出门禁均已通过。当前仍需至少十次
真实日常编辑/审阅会话和用户批准的 `studio` 默认入口切换，因此不把自动探针冒充真人验收。

M3 的 Assistant 现在是 Inspector 中的第三个自适应工作区，而不是第二个侧栏或伪聊天框。
类型化 `CanvasOperationBatch` 可以先完整预览 Before/After，再暂停、接受、拒绝、逐批撤销、
提交或整轮回滚；事务关闭重开、apply 中断、冲突、日志重试、页面/缩放变化和 exact-current
导出均有自动门禁。没有 AI provider 时，普通 Canvas 编辑、审阅、QA、保存和导出仍完整
可用。注入 provider 后，请求输入、线程化进度、停止、理解摘要、警告和完整提案都在同一
工作区显示；响应绑定完整请求哈希，取消后的迟到结果会被丢弃。数据映射现在从同一个
Assistant 工作区完成零写入预览、显式用户确认、精确哈希收据、后台原子执行和新 Canvas
交接；原 Canvas、原始 VSZ 和原始数据保持不变。来源无法唯一推导时必须由用户定位，
收据同时绑定规范化的源根、请求路径和输出根。关闭重开不会凭空产生同意，真实持久化的
`executing` 状态会恢复为同一收据下的可继续状态；交接和提交前重新验证执行清单、映射 VSZ
及原 VSZ。旧 v1 无路径收据只能审计，必须显式重新确认 v2 后才能执行或交接。候选工程仍
通过标准 Studio、执行清单防篡改、确定性输出复算、样本覆盖门禁和完整交付。生产 adapter
已经接入，但当前开发环境没有 API key；真实端点、真实模型质量和六项自然语言验收尚未
完成，因此 M3 仍处于开发中。

M4 原生 Composition Board 的工程基线也已实现。`composition.json` 记录精确 183 mm
布局、不可变源模块、独立变体和 exact-current 合成文档权威；Qt 画板提供毫米标尺、模块
缩略图、槽位吸附、交换、键盘移动、撤销/重做和右侧实时原生 Veusz 预览。五种出版布局
都编译为一个 page、一个 grid 和原生 graph/text 对象，不使用最终位图拼接。编译器统一
图区边距、字体、线宽和 panel label，并记录共享轴/共享图例资格。手工修改后的 composite
VSZ 不会被一次拖放静默覆盖，必须显式归档后再生成。PDF、300 dpi TIFF、物理尺寸、文本/
矢量保留、源哈希和 delivery parity 已进入自动门禁。合成 probe 当前通过 `11/11`；它是
合成合同证据，不替代后续跨真实图族的日常使用验收。runtime smoke version 17 当前通过
`33/33`，其中包含这条原生 composition 生命周期门禁。当前 version 18 已扩展为
`34/34`，并加入 deterministic-readiness 门禁。

M5 的确定性 Ready 基线也已实现。源码证书绑定每条规则的识别条件、完整语义/渲染合同和
版本化运行时请求策略；
新输入还必须通过 source/mapping 身份、置信度、严格 QA、exact-current export 和 delivery
门禁。AI、自定义请求、旧 manifest 或只有相同 `rule_id` 的篡改载荷都不能自报 ready。
当前 23/23 ready 规则已经用授权真实数据重新跑完 version-3 生命周期和最终尺寸视觉审阅；
纯视觉样式覆盖可留在自动包络内，换模板、直连 recipe、改变轴域/尺度/标签、数据筛选/
变换、拟合、科学标注或 split policy 则必须退出自动资格。readiness 对抗 probe 通过
`29/29`，runtime smoke version 18 通过 `34/34`。其中 13 条证据
拥有注册 fixture/source/units，2 条缺 source-unit 注册，8 条仍是 computed-unregistered
fixture hash；这些来源强度差异会保留显示。M5 的真实晋升结果以及 M6 的真人日常
会话和默认入口切换仍未完成；M3 的真实生产模型六项自然语言任务也仍需实测，不能用内存
wire fixture 冒充。M5a 的审阅式晋升机制已经实现，但当前没有伪造任何真实晋升：它只从
交付门 G0 复验通过的 executed mapping 或 committed Canvas transaction 收集规范化决策；路径、
provider、时间、实例 ID、原始值和自由文本不会参与比较。候选必须同时来自至少三个不同的
真实会话和三个不同的自然任务指纹，而且三次必须属于同一个已见证 owner；候选本身永远
不能影响运行时。工作区外预登记公钥签名的 owner receipt、普通源码审阅、从指定 Git
commit 私有只读快照执行的候选专属 probe，以及在执行前绑定候选/计划/行为断言、运行同一
冻结提交并由最终 manifest 暴露完整 canonical candidate、从重开 VSZ 核对每个 Canvas
operation，或对 mapping proposal、变换、输出和最终 source lineage 做独立重放的无 AI
真实生命周期缺一不可。验证 receipt 还必须签住每个会话截至 completion 的 ledger
字节前缀、三类 event hash 和当前 authority artifact hash；路径别名不能重复计数。
`state=ready` 等通用健康字段不能充当候选效果。
生产 trust registry 固定到 OS account 路径，
拒绝环境重定向、symlink 和不安全 owner/mode，并在 macOS 要求 user-immutable。
Git 审核固定使用 root-owned 绝对可执行文件，清除环境中的 `GIT_*` 重定向，拒绝
`assume-unchanged`/`skip-worktree`，并把每个 tracked worktree 文件直接与目标 commit
blob 对比；SHA-1 与 SHA-256 仓库都使用完整 object ID。签名回执中的 probe 路径必须是
解析后的规范绝对路径，词法别名直接拒绝。runtime smoke version 21 现通过 `37/37`，
其中晋升对抗门为 `28/28`；模拟阈值记录和 synthetic
ledger 均不计作真实候选。正式路线下一步完成 M3
“任务—类型化能力”矩阵，然后运行真实模型、五类探索会话并修复完整性/P0/P1 缺口。代码
与运行时冻结为一个候选版本后，重新累计每类至少三次、合计至少十五次合格会话；探索次数
不凑正式指标，冻结后任何运行时代码变化都会重新计数。该候选本身已包含最终 Canvas 默认
入口；只有用户审阅证据并明确批准后，才把同一提交/同一包原样晋升到正常工作区并运行可
回滚 canary，不在验收后另改入口或清理代码；所有正常路径清理必须已经包含在被冻结并完成
十五次验收的候选中。Veusz `MainWindow` 保留为低频高级编辑和恢复入口。M7 分发不在当前
目标内。

交付门 G0 的会话证据合同现已落为 `sciplot sessions`。正式 M3/M6 轮次必须在操作前把自然任务、
授权来源哈希、owner、统一 `round_id`、入口、干净 Git 提交、冻结 wheel/package、规则
registry、Veusz runtime、provider/model 和期望证据写入同一个共享 JSONL；完成保存、
PDF/TIFF、QA 与 delivery 后，由 owner 真正关闭并重开 Canvas 或 Composition Board，再
分别记录 `witness` 和 `complete`。程序会复验 final revision、VSZ、日志后缀、未撤销 AI
提交/精确回滚、review promotion、mapping、native composition 和交付哈希。账本加 companion
head 能发现普通改写、重排、删除和截尾，但它不是签名或身份认证；GUI 重开事实仍是 owner
attestation。不同 round/provider/model/frozen build 不会混算，synthetic、discovery、
failed/abandoned、fallback、agent-only 或被撤销的结果不能凑 M6。完整命令与封闭枚举见
`docs/SESSION_EVIDENCE.md`。

`sessions freeze-build` 只接受干净提交并验证 wheel `RECORD` 与当前导入源码逐文件一致；
`sessions status --require m3|m6` 才是自动门禁。若 append 在 JSONL 与 companion head 之间
中断，状态会 fail closed，只有 `sessions recover` 能在三种可证明状态下完成恢复。对
`data_mapping`，预注册来源必须是确认 proposal 使用的完整 `source_root` 目录，最终
transform ledger 必须以该确认步骤开头并以实际绘图数据快照结束。`auto`、显式 recipe
和直接 render 都记录真实送入 renderer 的终端快照；多表目录输入必须列出全部终端表，
不能用一个目录路径或单个成员掩盖遗漏。每条真实进入 Veusz 的曲线、分类组或标量场还
绑定源文件规范路径与 SHA-256；多输出 mapping 必须逐输出贡献至少一个 rendered unit，
显示标签和总系列数不能充当覆盖证据。完成门会从私有只读快照重开 exact-current VSZ：
只把 spec 期望值量化一次到 Veusz 实际持久化的 `.6e` token，重开值必须精确相等；每个
预期单元还必须有真实可见的线、点、填充、原生 boxplot 或标量图像，额外可见 data
plotter 会被拒绝。终端表会独立重放为 renderer units，并与 spec 和重开 VSZ 三方核对，
并且终端表本身也只从 `O_NOFOLLOW` 捕获的私有只读快照重放；返回前会重新核对原文件身份。
三方签名同时绑定系列名称、显示标签、x/y 数据集身份和顺序；轴标签、方向、数值/分类模式、
线性/对数尺度、范围、刻度格式、主/次刻度及其可见性、字体大小、线宽和刻度宽长，以及
重开的 legend、direct label、全部可见 label、categorical label、XY/boxplot 顺序也必须
精确一致；direct label 还绑定位置、对齐、字号、文字色、背景、边框和对象顺序，不能把
来源正确的曲线改造成误导性文字遮罩。标量场还从权威请求和私有终端表重建完整视觉合同，
绑定 z 范围/尺度/刻度、至少两个不同且完全不透明的颜色、颜色图
及反转、像素映射、颜色条文字/线/刻度尺寸和等高线；重开的 image、自定义 colormap、
colorbar 与 contour inventory 必须逐项一致。自动来源证据还使用闭合的 shape inventory：
除页面背景、受限且来源签名绑定的参考带、精确几何/线宽/线型绑定的原生参考线，以及
高透明度局部 colorbar 背景外，额外 rect、ellipse、line、polygon、image 或 SVG overlay
都会阻断；背景和参考带不能成为全幅不透明遮罩。参考带在 log 轴上按对数空间计算中心与
覆盖比例，参考线使用真正的 Veusz `line`，不再以窄矩形近似。
外部 request 无权自称“终端数据已
预处理”，manifest 中声明的终端请求也没有证明权：验证器从确认的权威请求和私有终端表
快照重新构造闭合终端请求，再把 manifest 声明仅作为待核对副本。显式 split policy 会
重建完整分面计划；未确认的 auto split 和尚无独立 panel plan 的 multi-metric bundle
停止产生正式来源证据。若前两行元数据都像单位，程序会停止并要求规则修复，不再猜测哪行
是样品名；重复显示标签也会在 label-based selection 或 split 之前阻断。未知或全隐藏的
系列选择直接阻断，不能静默恢复为全部曲线。所以
协同篡改 request/spec/VSZ、换样品或轴标签、增加误导文字、调换系列顺序、隐藏 mark/box、
改变标量颜色语义、额外 plotter 和审计期间换文件均 fail closed。
通过正常 wheel 安装运行时，`freeze-build` 和正式 `preregister` 必须显式传入
`--repo` 与 `--veusz-root`；程序不会把 `site-packages` 猜成 Git checkout 或 Veusz
runtime。
冻结候选还必须通过一个 `formal_contract_probe`：从普通安装位置运行同一 wheel，完整走过
预注册、真实 Veusz 产物、关闭/重开见证和完成校验；该 scope 强制干净提交与运行时身份，
但使用明确的 synthetic fixture，永不进入 M3/M6 计数。

M5 学习闭环的交付门 G1 现已落为 `sciplot learning`。`collect` 会重新验证 session chain/head、
witness journal 边界、mapping execution 或最终 Canvas authority；证据损坏会 fail
closed。`build` 只生成 `observed` 或 `ready_for_review` 的无执行权候选。`decide` 与
`verify` 只接受工作区外 trust registry 中 owner 公钥验证通过的签名 receipt；程序不会
生成私钥、签名或 receipt，也不会替用户批准自己。批准还会锁定允许改动的源码/probe 和
真实生命周期 lane/行为断言；验证会从审阅 Git commit 的私有源码快照运行 probe，后续
session 必须在执行前绑定同一 candidate/decision/plan/assertion 集，由最终 manifest
暴露完整 canonical candidate，并从重开 VSZ 逐项证明 Canvas 效果，或从确认 execution
重放 mapping 的 proposal、输出、变换和最终绘图 lineage。`learning session-binding`
会输出 owner verification receipt 应签名的精确 ledger/event/authority 事实，但不会
生成签名或 receipt。mapping 候选的复验同时预登记 `provider_disabled` 与
`data_mapping`：execution 中保留最初映射来源身份，但复验运行本身不得声明
provider/model、不得产生任何 Assistant 活动，而由确定性执行与最终 lineage 证明行为。
完整状态机、receipt
字段和限制见
`docs/SCIPLOT_REVIEWED_PROMOTION.md`。后续 G3/G4 如果没有自然重复，正确结果就是零候选。

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

检查当前安装是否仍覆盖全部已验收输入范围：

```bash
skill/scripts/sciplot readiness status --json
```

要求 `status=ready` 且 `ready_without_ai_rule_count` 等于当前 ready 规则数。修改规则识别、
轴/单位、recipe、template、分析或 render contract 后，证书会立即变成 stale；必须重新运行
全量授权真实数据 acceptance、显式审阅 contact sheets，并用 `readiness certify` 生成候选
证书。旧工程仍可打开，但缺少当前 envelope 的旧 one-step/autoplot 状态不能继续宣称
`ready_to_use=true`。

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

## 确定性数据映射（M3 受控入口）

AI 或规则只能生成封闭的 `DataMappingProposal` JSON，不能自我授权执行。先做零写入预览，
再由独立确认收据绑定提案 SHA、请求 SHA、每个源文件 SHA 以及规范化的源根、请求和写入
路径，最后由程序执行：

```bash
skill/scripts/sciplot mapping preview proposal.json \
  --source-root RAW_DIR --request plot_request.json --json

skill/scripts/sciplot mapping confirm proposal.json \
  --source-root RAW_DIR --request plot_request.json \
  --execution-root outputs/mapped_projects \
  --by USER_OR_OPERATOR --out confirmation.json --json

skill/scripts/sciplot mapping execute proposal.json \
  --confirmation confirmation.json \
  --source-root RAW_DIR --request plot_request.json \
  --out outputs/mapped_projects --json
```

旧版 v1 收据缺少路径权威，只允许 `mapping show` 审计。必须用当前源根、请求路径和一个新的
输出根再次运行 `mapping confirm`，程序不会把旧同意静默升级为可执行权限。

执行结果是隔离的新项目目录，入口仍是标准 `plot_request.json`；它保留旧请求的原始 `input`
权威，通过 `execution.json` 指向哈希验证后的映射数据。后续直接运行
`sciplot studio MAPPED_PROJECT --export pdf,tiff_300 --json`。任何旧 transform ledger 都只
作为已取代证据归档，新活动链路必须从确认映射开始。消费前还会重新执行已确认的数据变换，
核对映射输出、活动谱系、请求补丁和有效输入，执行清单不能把渲染静默重定向到其他数据。
隔离项目还保存与确认 SHA 完全一致的 `base_request.json`，因此即使有人同时修改种子、
谱系和清单里的相邻哈希，也不能改写原始输入权威或伪造活动链路。
当前支持 rename、select、exclude、drop-missing、sort、单位换算、比值派生、基线归一化和
显式 replicate 聚合；外部变换必须携带稳定 ID，声明为逗号小数的数值列会按数值语义归一化
和排序，所有文本字段拒绝布尔值/数字偷转字符串；不接受 Python、shell、表达式或任意脚本。
如果变换后只剩 category、变成 0 行、x/y/z/value 仍是文本，或不存在有限数值，预览会在
确认前阻断，不把无效候选交给后续绘图器兜底。

## 原生 Canvas（M2 + M3 事务内核受控入口）

对已有 SciPlot project、`plot_request.json` 或独立 VSZ 进行实时编辑：

```bash
skill/scripts/sciplot canvas PROJECT_OR_VSZ
```

普通 Canvas 不需要 AI。若要在同一窗口启用 OpenAI Assistant，只在 shell 环境提供密钥；
不要把密钥写进仓库、请求文件或项目目录：

```bash
export SCIPLOT_OPENAI_API_KEY='YOUR_KEY'
# 可选；默认模型和推理强度由当前 SciPlot provider 配置决定
export SCIPLOT_OPENAI_MODEL='gpt-5.6'
export SCIPLOT_OPENAI_REASONING_EFFORT='medium'
skill/scripts/sciplot canvas PROJECT_OR_VSZ
```

也兼容标准 `OPENAI_API_KEY`。存在密钥时 provider 自动出现在 Assistant 工作区；不存在
密钥时不会发起网络请求，普通编辑、Review、保存、QA、导出和交付路径完全不变。AI 收到
的是有上限的选择、对象统计、Review、QA 摘要；它可提出的操作只来自当前选择对象的封闭
可编辑字段目录，不接收原始数据数组或绝对文档路径。模型返回的目标、字段和值还要经过
本地类型、范围、旧值和修订校验，并在用户接受前停留于零修改预览。
若密钥存在但 provider 配置无效，Canvas 会明确警告并继续以无 AI 状态打开，不让可选能力
阻断确定性工作流。

## 原生拼图与实时 Composition Board

用一个或多个独立 VSZ 新建 183 mm 合成工程：

```bash
skill/scripts/sciplot compose FIGURE_A.vsz FIGURE_B.vsz \
  --out outputs/composition_projects \
  --name Figure_2
```

也可以重新打开已有工程：

```bash
skill/scripts/sciplot compose outputs/composition_projects/Figure_2
```

确定性自动化或 AI 调用不必打开 GUI：

```bash
skill/scripts/sciplot compose outputs/composition_projects/Figure_2 \
  --export --json
```

左侧画板显示真实毫米标尺和支持的出版槽位；模块可直接拖动、交换或放回 module tray。
右侧同步显示重新编译后的 exact-current 原生 Veusz composite。工具栏可选择
`single_180`、`double_equal_90`、`double_120_60`、`double_60_120` 和
`triple_equal_60`，调整精确页高、图例策略、独立 variant，并执行 `Export + QA`。

新工程会把每个输入 VSZ 复制为哈希锁定的不可变 source snapshot。最终 composite 位于
`variants/VARIANT/studio/document.vsz`；每个 variant 有独立的编译、归档、导出和 delivery
目录。缩略图只用于交互预览，不是出版权威。交付包包含 `composition.json`、source
manifest、操作日志、源 VSZ snapshots、exact-current composite VSZ、PDF、300 dpi TIFF、
QA 和 zip。`ready_to_use=true` 只表示该次 native composition lifecycle 与 exact-current
artifact QA 通过，不宣称更广泛期刊合规。

也可以传入 Studio 能准备的原始数据路径，并用 `--out`、`--rule`、`--template` 和 `--name`
提供显式项目意图。Canvas 不构造 Veusz `MainWindow`；它直接加载 exact-current VSZ，在
SciPlot 窗口中显示实时画布和从属检查器。当前高频能力包括：

- 页面与缩放导航；
- PlotWindow 点击选择、数据点选择和选择边界；
- 页面、图区、轴、XY、箱线、图例、image、contour、colorbar 和原生 label 的封闭检查器；
- 安全字段即时应用，其余字段明确 Apply/Revert；
- 原生 label 直接拖动并写入类型化操作日志；
- Review 工作区：Note、Arrow、Box、Oval、Pen，以及 page、normalized page、graph、data、
  selected object 五类锚点；
- 未晋升审阅只写入 `.sciplot_canvas/review_annotations.json`，不会改变 VSZ 或 PDF/TIFF；
- 文字、箭头、矩形和椭圆可晋升为原生 Veusz 对象；freehand 保持 review-only；
- Save、Undo、Redo；
- PDF/TIFF exact-current Export + QA；
- QA/export revision 状态；
- 显式未保存恢复；
- `F9` 收起检查器；
- `Ctrl+Shift+R` 打开 Review 工作区；
- `Ctrl+Shift+A` 打开 Assistant 工作区；没有密钥/provider 时显示明确的 AI-optional 空状态；
- 配置密钥后自动加载生产 provider，显示真实请求输入、共享上下文说明、就地进度和 Stop；
- 类型化 Assistant 提案完整展示 Before/After，接受前不改变 VSZ、修订或实时渲染；
- Assistant 回合支持暂停/恢复、拒绝提案、逐批撤销、提交、关闭重开和整轮精确回滚；
- 活动 Assistant 回合独占文档变更，普通编辑、review promotion、Save、Export + QA 和
  Advanced Editor 必须先提交或回滚；
- `Tab` 进入 Canvas-only，`Esc` 恢复界面；
- 系统 palette 驱动的明暗与高对比应用 chrome；
- 窄窗口检查器自动浮动，保持画布宽度；
- 界面状态、菜单/快捷键和可访问名称门禁；
- `More` 中的 Advanced Editor 低频/暂未支持属性与恢复入口。

SciPlot 只吸收日常高频编辑，不在第一阶段复制 Veusz 的完整属性树。遇到少见对象属性或
暂未进入类型化网关的高级操作时，用户可以显式打开 Advanced Editor；该回退会被记录，
但不会把 Veusz MainWindow 重新变成普通主流程。

技术功能已进入 M2 受控日常使用阶段，但默认前端切换仍由真实会话零丢失门禁控制。日常
自动绘图与交付目前仍优先使用 `studio`；`canvas` 用于积累真实编辑/审阅证据。

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
- M2 选择驱动的十类对象检查器、数据点选择、原生 label 拖动、结构 QA、五工具审阅层、
  五类锚点和四类原生标注晋升；
- M3 provider-neutral Assistant 面板、`CanvasSession` v6 事务状态机、哈希绑定请求记录、
  线程化进度/取消、零修改预览、实时
  apply、暂停/拒绝/逐批撤销/提交/整轮回滚、冲突与中断恢复、幂等日志 outbox；
- M3 `DataMappingProposal` v2、外部确认收据、零写预览、封闭确定性变换、原子候选项目、
  来源歧义回退、后台执行、崩溃恢复、独立新 Canvas、transform ledger、映射样本覆盖门禁，
  以及 run/Studio/QA/delivery 接入；
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

# 正式会话账本状态与 G0 合成对抗门禁
skill/scripts/sciplot sessions freeze-build \
  --out /absolute/path/to/frozen_builds \
  --repo /absolute/path/to/clean/sciplot-checkout \
  --veusz-root /absolute/path/to/veusz-runtime --json
skill/scripts/sciplot sessions status /absolute/path/to/round.jsonl \
  --require m6 --json
skill/scripts/sciplot session-evidence-probe \
  --out .tmp_verify/session_evidence --json

# 审阅式经验收集；候选不影响运行时
skill/scripts/sciplot learning schema --json
skill/scripts/sciplot learning collect /absolute/path/to/round.jsonl \
  --out promotion_collection.json --json
skill/scripts/sciplot learning build promotion_collection.json \
  --out promotion_candidates.json --json

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
意图 swelling 等解析合同，检查语义选择、原生 Canvas、Review、Assistant、Composition
Board、VSZ 重开与人工编辑保留、精确导出、PDF/TIFF 配对、交付哈希及哈希失败门禁；它
不属于真实数据证据。完整规则矩阵依赖本地验收数据，因此不属于 GitHub 最小运行发行版。

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
- `src/sciplot_core/canvas/composition.py`、`composition_workspace.py`：精确拼图模型、变体、
  immutable source 和类型化操作持久化；
- `src/sciplot_core/composition_delivery.py`、`composition_probe.py`：合成图物理 QA、交付和
  全生命周期回归门；
- `src/sciplot_core/launchers.py`：可移动项目和 delivery 的启动器发现合同；
- `src/sciplot_core/promotion.py`、`promotion_probe.py`：G1 在 G0 冻结证据之上的重放、
  无权候选、owner 决策/实现验证状态机和对抗门禁；
- `src/sciplot_core/source_coverage.py`：逐 Veusz 系列/标量场绑定真实源路径与 SHA-256，
  并在正式会话完成时独立重放多源覆盖；
- `src/sciplot_core/workflow.py`：request 编排和辅助修复闭环；
- `src/sciplot_core/qa.py`、`delivery.py`：制品 QA 与交付门禁；
- `src/sciplot_core/publication.py`、`study_model.py`：出版与证据合同；
- `src/sciplot_recipes/`：经过测试的实验族 recipe；
- `src/sciplot_gui/`：SciPlot Qt shell、Canvas adapter、Composition Board、controller 和
  原生 Veusz composition compiler；
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
