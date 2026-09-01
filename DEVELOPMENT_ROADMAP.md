# SciPlot AI-efficient Local Automation 总纲与开发路线

Status: R0 complete; paused before R1 authorization.

Planning baseline: 2026-08-31.

本文只记录尚未完成的目标、依赖、阶段交付物和退出条件。它不改变
`README.md` 中的当前产品行为，不替代 `docs/ARCHITECTURE.md` 的模块边界。R0 的测量与
合同冻结已经关闭并记录到 `DEVELOPMENT_LOG.md`；R1 及后续运行时实现尚未授权。

## 一、总纲

### 使命

把 SciPlot 建成一条 AI-efficient 的本地自动化工作流：尽可能由确定性本地程序完成
数据识别、科学语义约束、计划、绘图、QA、导出和交付；只在自然语言意图无法直接映射到
既有能力，或用户主动要求视觉微调时调用 AI，并让本地合同决定 AI 提案是否可执行。

北极星结果不是“AI 做了更多”，而是：

> 每次模型调用都只解决一个本地规则无法解决的窄问题，其余工作由可重放、可验证、
> 可撤销的本地自动化完成；最终只有本地证据可以把结果判为 `ready`。

### 两个关键词

**AI-efficient** 表示：

1. 能由规则、类型、哈希和本地工具决定的事项不调用模型；
2. 模型只接收完成当前决策所需的最小、结构化、带版本上下文；
3. 一次升级只产生一种受支持的 typed proposal，不进行开放式工具循环；
4. 本地验证失败就停止，不通过换规则、重试模型或放宽门槛追求“成功”；
5. 以“每次模型调用完成了多少可验证本地工作”衡量效率，而不是只统计 token。

**Local Automation** 表示执行、原始数据、项目状态、证据和交付默认留在用户机器上。
它不等于“必须使用本地模型”：没有模型、使用 loopback 本地 provider，或经用户配置使用
远程 provider，都不得改变确定性主干的能力和结果合同。

### 产品承诺

- 对受支持且语义唯一的输入，完成路径应为零次 AI 调用；
- 对不唯一的科学含义，只问一个能解除阻断的最小问题，不让模型猜单位、样品身份或实验含义；
- 对视觉编辑，AI 只能提出当前选中对象、当前 revision 下目录允许的 `set_setting`；
- 所有写入都经过现有请求、Studio、Veusz、QA 和 delivery 边界；
- provider 缺失、超时、取消或输出非法时，本地绘图和人工编辑仍完整可用；
- `.vsz`、原始数值、规则合同和交付哈希的权威关系不因 AI 接入而改变。

## 二、当前基线与待解决问题

### 已有基础，不重复建设

截至本规划基线，当前 checkout 的 `doctor --json` 为 `status=ready`，24 个 ready 规则均有
current validated envelope。现有主干已经具备：

- `rules list/show`：提供 ready capability、固定 `rule_id`、合法 template 和调用参数；
- `inspect` 与 `plan`：本地识别、只读 FigurePlan 和 source-bound transform 预览；
- `studio` 与 `autoplot`：共用确定性准备、Veusz、QA、导出和 delivery 生命周期；
- `ready`、`needs_human_confirmation`、`needs_rule_repair`：封闭的自动化状态；
- 原生 Veusz `MainWindow`：唯一日用绘图和高级编辑前端；
- provider-neutral Assistant 合同：无 raw dataset arrays、带 revision 的当前对象上下文、
  typed `set_setting` batch、本地确认、原生 Undo 和持久化历史；
- exact-current VSZ、manifest、QA 和 delivery hash gate：最终结果权威。

因此，本路线不建立第二个前端、renderer、规则目录、request schema、document model、cache、
receipt 或 hash ledger，也不复活已经删除的浏览器精修/Canvas/Composition 路线。

### 2026-08-31 规划审计快照

当前 pretty-printed JSON 的单次字符量为：

| 机器输出 | 字符数 | 规划含义 |
| --- | ---: | --- |
| `doctor --json` | 8,690 | 会话 readiness 很完整，但不应在每次模型决策中重复发送 |
| `rules list --json` | 22,912 | catalog 适合本地程序消费，AI 只需要 invocation 子集 |
| `rules show xrd_pattern --json` | 3,174 | 单规则仍含不少与路由无关的呈现细节 |
| XRD `inspect --json` | 23,937 | 诊断信息完整，但不能直接等同于最小 AI 上下文 |
| XRD `plan --json` | 7,844 | 是执行前权威预览，仍需要派生窄决策摘要 |

这些是字符量而非 token 或性能结论，仅用于说明第一个实现目标应是“派生紧凑视图”，
而不是让模型反复读取完整诊断 payload。R0 已用四类可重放场景建立正式基线；当前量测
合同与未来控制草案见 `docs/AUTOMATION_CONTROL_CONTRACT.md`。

### 当前缺口

1. 完整机器 payload 面向审计，外部 AI 若原样读取会重复接收静态合同和无关字段；
2. `doctor → rules → inspect/plan → autoplot → handoff` 的决策策略分散在调用方，尚无一个
   纯本地、封闭状态的轻量 conductor；
3. 调用预算已在 R0 设计合同冻结，但尚未由一个本地 conductor 作为运行时硬门执行；
4. selected-object 安全闭环已有 R0 单事务基线，但还没有持续的产品级效率与拒绝率观测；
5. provider 数据边界和一致性政策已冻结为设计，尚未成为可执行的 text/visual 路由合同。

## 三、采用的总体架构

### 唯一闭环

```text
用户意图 + 本地源
  -> 本地 readiness / capability / source evidence
  -> 紧凑 Automation Brief（派生视图，不是新权威）
  -> 本地决策路由
       ready + 唯一意图 ----------> 0 次 AI -> plan -> autoplot / studio
       可由既有 catalog 选择意图 -> 最多 1 次 AI -> 本地 plan 复核
       科学含义不唯一 -----------> 1 个最小人工确认问题 -> 重新 plan
       规则或合同缺陷 ------------> needs_rule_repair -> 独立维护工作
       当前对象视觉微调 ----------> 最多 1 次 AI -> typed proposal -> 人工确认
  -> 本地执行、revision/hash/QA 校验
  -> ready 交付，或带结构化原因停止
```

### 五层职责

| 层 | 复用/新增职责 | 允许 | 禁止 |
| --- | --- | --- | --- |
| Evidence | 复用 `doctor`、rules、inspect、plan、manifest 和 QA | 读取一次当前事实并形成 typed snapshot | 让 AI 重新解析原始数据或发明证据 |
| Brief | 新增一个纯派生、版本化、有限大小的 Automation Brief | 只投影当前状态、合法动作、阻断原因和证据引用 | 另建 catalog、request、receipt 或持久化真相 |
| Control | 新增纯本地 conductor 和封闭决策表 | 选择零调用、问人、维护或一次 AI 升级 | 猜单位、静默换规则、无限重试或绕过状态 |
| Execution | 复用 `studio`、`autoplot`、`run` 和 Veusz | 执行已经验证的现有请求并保持事务性 | 新 renderer、新编辑器或鼠标自动化 Veusz |
| Integrity | 复用 revision、Undo、exact-current、QA 和 delivery | 只由本地证据判定 `ready` | 接受模型的“已完成”声明作为交付证明 |

### Automation Brief 的边界

Brief 是完整本地 payload 的窄投影，计划包含以下信息：

- `kind`、`version` 和本次源/文档的非敏感身份；
- 当前自动化状态及一个明确 `next_action`；
- 已认证的 `rule_id`、template 选项和现有 invocation 参数；
- 适用时的 plan/request/revision/hash 身份，而非数据数组；
- 封闭 reason codes、一个最小确认问题或一个维护 handoff；
- 完成后必要的 artifact/QA 摘要和本地 evidence references。

它必须由现有 owner 的同一个内存结果派生，不二次读取源、不二次分类、不复制业务规则，
也不作为跨命令 cache。完整诊断仍保留给人和维护者；Brief 只服务自动化决策。

### 权限矩阵

| 决策 | 最终权威 | AI 角色 |
| --- | --- | --- |
| ready rule、合法 template 和参数 | source-controlled catalog + certification | 只能从给定选项中选择 |
| 样品、列、单位、锚点和科学身份 | 原始源证据 + SemanticRule + 人工确认 | 不得推断缺失事实 |
| 是否执行本次计划 | 本地 conductor + `plan` 结果 | 可解释，不可绕过 |
| 当前对象视觉设置 | setting catalog + 当前 revision + 用户确认 | 只提 typed `set_setting` |
| 是否完成交付 | exact-current VSZ + QA + manifest/delivery hashes | 无判定权 |
| 规则修复或代码修改 | 独立开发任务及其验证 gate | 可生成维护 brief，不在运行时自行修复 |

## 四、效率、隐私与失败政策

### 调用预算

- 显式 rule/template 或本地唯一识别：0 次模型调用；
- 自然语言只需在 ready catalog 中选择：最多 1 次文本调用；
- 当前选中对象的单个用户意图：最多 1 次视觉调用；
- 同一次调用可以返回同一对象、同一 revision 的一个 typed operation batch；
- stale、非法、取消、超时或 provider failure 后不自动重新提问模型；
- `needs_rule_repair` 不进入换模型、换规则或“试试看”循环。

### 上下文政策

- 路由 AI 只接收 Automation Brief，不接收完整 raw file、工作簿或逐点数组；
- 视觉 AI 只在用户主动请求时接收 exact-current 页面预览、选中对象、允许字段和必要 QA；
- 静态 schema、目录和 provider instructions 在 provider 侧只发送一次所需版本，不在对话中累积；
- context、图片、proposal 和历史都绑定同一个 document/revision/hash；
- API key、provider secret、本地绝对源路径和隐藏工作区内容不得进入模型输出或持久化日志；
- 无 provider 模式必须是完整、持续测试的正常模式，而不是异常降级模式。

### 失败与恢复

- 本地证据不完整：返回结构化 blocker，保持源和既有项目不变；
- 科学含义不唯一：停止并问人，回答后从 plan 重新验证；
- provider 不可用：保留零 AI 主干和原生 Veusz 手工路径；
- proposal 越权或 revision 过期：整体拒绝，零部分写入；
- 已接受视觉提案：一个 Veusz 原生 Undo 步骤，保存前仍可撤销；
- 执行或交付失败：使用现有事务、manifest 和项目状态恢复，不新增模型会话 cache；
- 重复出现同一阻断：转为中心规则/合同维护，不能积累 source-specific workaround。

## 五、成功指标与硬门

### 正确性和科学完整性

- false-ready：0；
- 原始值、样品身份、单位和顺序的静默改变：0；
- AI 直接修改 raw data、request authority 或 delivery evidence：0；
- 受支持且语义唯一的输入，直接 Autoplot 与 conductor 路线的请求、FigurePlan 和终端制品
  身份必须一致；
- 所有 AI 提案要么在写入前通过 typed/revision/capability 验证，要么零写入拒绝。

### AI 效率

- 受支持且语义唯一的成功任务：模型调用数恒为 0；
- 需要 AI 的已完成任务：模型调用中位数不超过 1，P95 不超过 2；
- R1 的 Automation Brief 在 ready、科学确认和视觉三类基准中，相比组成同一决策所需的
  完整 JSON 至少减少 70%；小分母 repair 场景至少减少 55% 且不超过 1,280 bytes，同时
  状态、动作、reason code 和证据身份完全一致；
- 不允许以删除诊断、QA 或 provenance 的方式实现压缩；
- 记录 context bytes、图片 bytes、输入/输出 token、调用耗时、provider、拒绝原因和最终状态，
  但不记录 secrets 或 raw arrays。

### 人工负担与可恢复性

- 每个 `needs_human_confirmation` 只提出一个能解除当前阻断的问题；
- stale/越权 proposal 拒绝率必须为 100%；
- 已应用视觉提案必须 100% 对应一个原生 Undo 单元；
- provider 离线时，当前 24 个 ready rule 的确定性 readiness 不得下降；
- R1–R5 的运行时实现阶段只在 owner-focused tests、相应运行门和该阶段要求的真实数据
  证据通过后关闭；R0 是固定 synthetic contract fixture 的可移植测量/设计冻结，不冒充
  真实数据验收，真实研究工作试点由 R5 明确负责。

R0 已记录 wall time、峰值内存、payload/context/image bytes、调用数和 token 可用性。
这些 P50/P95 是当前平台的回归参考，不冒充跨平台毫秒承诺；调用预算、8 KiB Brief 上限和
三类 70% 相对压缩门与 repair 的 55% + 1,280-byte 双门已冻结在
`docs/AUTOMATION_CONTROL_CONTRACT.md`，并由同一决策、完整字段 feasibility fixture
证明可达。分母是现场 producer 对当前 owner 内存对象做的路径归一化量测；历史 JSON
仅作回归参考，R1 退出门必须在同一运行中重算 full/Brief，不能信任离线报告自身作为
防篡改凭证。

## 六、开发路线

R0 已于 2026-08-31 关闭。四类基线、测量定义、威胁模型、Brief 草案、决策表、权限和
未来 owner/test map 已冻结在 `docs/AUTOMATION_CONTROL_CONTRACT.md`；运行证据只保留在
`.tmp_verify/`，关闭记录在 `DEVELOPMENT_LOG.md`。这项完成不授权 R1。

### R1 — 紧凑 Automation Brief

目标：让本地程序读取完整事实，让 AI 只读取最小决定性投影。

交付物：

- 一个纯函数式、版本化 Brief projector，复用现有 rules/plan/result 对象；
- 在现有 JSON 命令族中提供同一紧凑投影选择，不增加第二条绘图入口；
- payload 大小、闭集字段、reason-code/state 等价和无 raw arrays gate；
- full payload 与 Brief 的差分/等价测试及四类基准报告。

退出条件：

- ready、科学确认和视觉达到至少 70% 缩减，repair 达到至少 55% 且不超过 1,280 bytes；
- full 与 compact 对所有基准作出完全相同的允许/停止决定；
- projector 不读取源、不解析规则、不写项目、不建立 cache 或 receipt；
- provider 仍为可选依赖。

### R2 — Deterministic Local Conductor

目标：把现有命令组合成一个封闭、本地、可测试的决策循环，同时保留现有用户入口。

交付物：

- 纯决策状态机：`ready`、`needs_human_confirmation`、`needs_rule_repair`；
- 复用 `plan` 后原样调用 `autoplot`/`studio` 的薄 orchestration seam；
- 终端只接受 `state=ready`，其它状态保留结构化原因；
- 取消、重复调用、部分失败和现有 manifest 恢复测试；
- direct route 与 conductor route 的 request/plan/artifact identity 测试。

退出条件：

- 所有 ready/唯一意图基准为零 AI；
- 不存在隐式规则切换、二次源解析或新 renderer；
- 同源同意图的制品与直接 Autoplot 路线一致；
- provider failure 不影响确定性结果。

### R3 — 一次性 AI 意图升级与 provider 路由

目标：只在 ready catalog 选择确实需要自然语言理解时使用一次模型。

交付物：

- 输入只含 Brief 和合法候选的 typed intent-selection proposal；
- 模型返回值只允许既有 `rule_id`、template 或停止状态；
- 本地 `plan` 对模型选择进行第二次、也是最终的执行前验证；
- 无模型、loopback 本地 provider 和显式远程 provider 共享能力声明与回放 fixture；
- 固定调用预算、无自动 fallback、secret redaction 和 provider observability。

退出条件：

- 非法选择、未知能力、科学歧义和 provider failure 全部零写入停止；
- 远程与本地 provider 不能改变本地状态机和 ready 判据；
- ready/唯一意图任务的调用数仍为 0；
- AI-assisted 基准的调用中位数不超过 1。

### R4 — Selected-object AI 效率闭环

目标：优化已经存在的当前对象助手，不扩大其科学或文档权限。

交付物：

- 只发送当前对象真正可编辑的 capability delta 和必要视觉上下文；
- 同一 revision 的单个 typed `set_setting` batch、本地预览、人工确认和一个 Undo；
- apply 后 render hash、局部 QA delta、history 完整性和 no-op 检测；
- context/image bytes、拒绝原因、用户接受/撤销和最终保存状态指标。

退出条件：

- 越权、过期、类型错误、重复 path 和超范围值 100% 在 mutation 前拒绝；
- 自动应用默认关闭，用户确认仍是正常路径；
- 视觉调用不接收 raw arrays，也不能修改 dataset、规则、request 或 delivery；
- 在真实高频视觉任务证明需要前，不新增 `set_setting` 之外的 operation kind。

### R5 — 真实数据试点与核心收口

目标：用研究者真实工作而非 synthetic demo 决定核心路线是否成立。

试点矩阵至少覆盖：

- 单曲线仪器数据；
- 多样品/重复测量 FigurePlan；
- 一次真实 `needs_human_confirmation`；
- 一次真实 `needs_rule_repair` 维护 handoff；
- 轴、图例或 series 的 selected-object 视觉微调；
- provider 离线、取消和 stale revision。

退出条件：

- false-ready、静默科学身份改变和 raw-array 外发均为 0；
- 支持且唯一的任务 100% 零 AI 完成；
- mixed pilot 的 first-pass ready、人工确认轮数、AI 调用数、总耗时和撤销率达到 R0 冻结目标；
- source-adjacent VSZ/PDF/TIFF/CSV/launcher 与 exact-current hashes 完整；
- 用户日用复核通过后，核心 initiative 才可标记完成。

### R6 — 本地分发与运行管理（R5 后独立放行）

目标：在核心路线被真实使用证明后，再解决干净机器上的可安装和 provider 配置体验。

候选交付物包括 clean-wheel/install、签名/公证、可诊断的本地 provider 配置、升级/回滚和
跨平台范围。R6 不属于 R0–R5 核心闭环的完成条件，也不得提前挤占正确性、类型和真实数据
验证。没有单独授权时，它保持 deferred。

## 七、顺序与放行规则

```text
R0 baseline (complete)
  -> R1 compact evidence
  -> R2 zero-AI conductor
  -> R3 optional intent AI
  -> R4 in-app visual efficiency
  -> R5 real-data closeout
  -> R6 optional distribution
```

- 不跳过 R0 直接实现模型路由；
- 不在 R1 完成前让模型消费更多完整 payload；
- 不在 R2 证明零 AI 路线前扩展 provider；
- 不在真实 friction 证明需要前扩展 operation kind；
- 每个阶段关闭后停止，下一阶段需明确授权；
- documentation-only 规划不自动升级为实现授权。

当前唯一候选下一步是 R1，尚未授权。R2–R6 仅是已排序 backlog，不是并行开发任务。

## 八、主要风险与约束措施

| 风险 | 约束措施 |
| --- | --- |
| AI 读取完整诊断导致 token 膨胀 | Brief projector、大小门、full/compact 等价测试 |
| AI 发明规则、单位或对象 path | 闭集 catalog、typed proposal、本地二次验证 |
| “自动成功”掩盖科学歧义 | `needs_human_confirmation` 单独状态和零写入停止 |
| rule repair 与日用助手混合 | 运行时只生成维护 handoff，修复进入独立开发 gate |
| 新 conductor 变成第二套产品 | 只编排现有 plan/autoplot/studio，不拥有 renderer/request/receipt |
| provider 失败影响日用能力 | 无 provider 是持续测试的正常模式 |
| stale UI 提案污染当前文档 | revision、selection、expected value 和 capability 四重检查 |
| 压缩上下文损失审计信息 | 完整 payload 继续本地保存，Brief 只作决策投影 |
| local provider 被误认为更可信 | 本地和远程输出使用相同不信任、验证和日志边界 |
| 过早投入分发或平台扩张 | R6 独立放行，R0–R5 先证明核心价值 |

## 九、总体完成定义

R0–R5 同时满足以下条件时，AI-efficient Local Automation 核心目标才完成：

1. 受支持且语义唯一的任务无需 AI，且与直接 SciPlot 路线产生同一权威结果；
2. AI 只在已定义的 intent selection 或 selected-object edit 两个窄边界出现；
3. 模型没有原始数据、科学身份、直接写入或 ready 判定权；
4. 每个 AI 提案都可验证、可拒绝、可审计，视觉写入可由一个 Undo 撤销；
5. provider 缺失不降低确定性日用能力；
6. context/call/latency 指标达到 R0 冻结预算，且正确性硬门零妥协；
7. 真实数据试点和 source-adjacent editable delivery 通过人工复核；
8. README、Architecture、Skill、Roadmap 和 Development Log 继续各守其责。

## 十、保持 deferred 的其它方向

- instrument-cycle DSC 仍只在有授权真实 workbook 和 protocol metadata 时重新开启；
- cloud collaboration、通用桌面 RPA、鼠标驱动 Veusz 和第二前端不属于本计划；
- generalized multi-figure composition 仍不替代当前确定性 metadata；
- broader platform support 与安装分发只在 R6 单独授权后开始；
- 新图族仍必须是现有 rule、typed source、FigurePlan、Studio、QA 和 delivery 主干的薄增量。

## 完成纪律

实现阶段使用 `skill/SKILL.md` 的 changed-owner gate，并按风险升级 Doctor、smoke、full suite
和 acceptance。每个非平凡实现回合更新 `DEVELOPMENT_LOG.md`；路线图只保留未完成目标，
完成证据移入日志和 Git，不能把历史重新当成当前产品说明。
