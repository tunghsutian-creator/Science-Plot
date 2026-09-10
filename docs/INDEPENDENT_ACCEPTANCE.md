# 独立用户、安装与外部 AI 效率验收

状态：验收方案与空白记录格式；本文件不表示已完成任何干净机器、真人或真实客户端验收。

本方案用于检验 [未完成路线图](../DEVELOPMENT_ROADMAP.md) 的第 1、4 项是否达到完成条件。固定一个 macOS
构建、一个真实外部 AI 客户端和一组任务，再采集安装、使用和效率证据。
[README](../README.md) 与[公开接口指南](../skill/references/external-control.md) 仍是操作入口；
本文件不增加运行命令、科学选择类型或认证状态。

## 1. 先冻结对象与证据目录

填写以下记录后开始试验。每次更换应用构建、系统、客户端或模型配置都建立新的记录；
不把不同配置的结果合并成同一次验收。记录放在 `.tmp_verify/independent_acceptance/RUN_ID/`；
真实绘图交付仍在原数据旁，原始输入不改写。只收集受试者同意保留的任务与会话证据。

```yaml
acceptance_id:
status: not_started
started_at:
finished_at:
build:
  app_path:
  source_revision:
  build_manifest_path:
  build_manifest_sha256:
  distribution_file:
  distribution_sha256:
  developer_id_signed: null
  notarized: null
host:
  machine_id:
  macos_version:
  architecture:
  clean_machine: null
  python_qt_homebrew_inventory_evidence:
client:
  name:
  version:
  transport:
  model:
  model_settings:
  connection_configuration_evidence:
  token_telemetry_available: null
evidence_index:
```

`null` 表示未知；不得替换为零或通过。模型设置包括客户端实际可见的推理配置、缓存状态、
已启用工具和影响任务的提示配置；不可见项目保持未知。构建身份以实际分发文件和
build manifest 为准，不能只用当前仓库版本代替已经生成的应用。

## 2. 独立完成干净 Mac 安装验收

使用另一台没有事先安装 Python、Qt 或 Homebrew 的 Mac，记录完整系统版本和 CPU 架构。
在开发机清除环境变量、使用新账户或移动应用，只能记为各自的局部验证。

按预定分发方式取得并放置完整应用，经过真实首次打开流程，生成欢迎页并在固定客户端
建立连接。记录 Gatekeeper、文件访问和客户端连接的实际结果。随后用一份允许使用的
原始数据创建图、查看预览并导出，确认新会话还能找到项目。不要用官方 MCP SDK 的发现测试
替代实际客户端配置与使用。

| 安装步骤 | 开始/结束时间 | 结果（通过/失败/未执行） | 实际错误或操作 | 维护者介入 | 证据路径 |
| --- | --- | --- | --- | --- | --- |
| 接收分发文件并核对身份 | | | | | |
| 固定位置安装及首次打开 | | | | | |
| 欢迎页与 Doctor 检查 | | | | | |
| 真实 AI 客户端连接 | | | | | |
| 创建、查看并导出图稿 | | | | | |
| 新会话继续原项目 | | | | | |

安装出口分别报告：依赖是否封闭、干净机器是否通过、该系统/架构是否通过、发行身份签名
和公证是否完成。若向其他 Mac 正式分发，Developer ID 签名、公证与首次打开验证属于发行
出口；ad-hoc 签名不代表完成它们。没有相应证书、账户或机器时记录具体阻塞，不扩大支持范围。
详细构建约束见 [macOS 分发说明](../distribution/macos/README.md)。

## 3. 3–5 名独立用户完成同一任务链

受试者没有参与 SciPlot 开发，每人使用自己的数据，并获得相同版本的安装和使用说明。
观察者记录问题、完成时间和介入，不替受试者挑选项目或回答科学问题。先保存首次尝试，
需要帮助后再建立一次有介入的继续记录；失败不能被重试成功覆盖。

| 任务 | 受试者需要完成的行为 | 检查与证据 |
| --- | --- | --- |
| T1 安装连接 | 放置应用，在指定外部 AI 客户端连接 SciPlot | 客户端和应用身份、步骤记录；已安装者记录不适用，不重复计入安装成功 |
| T2 自有数据首图 | 描述绘图需求，确认样品和单位，取得首图 | 原始数据哈希、请求、任务/项目路径、图稿、源数据对应关系 |
| T3 真实歧义 | 根据原始实验信息回答一次真实规则或源列选择问题并继续 | 原始问题、证据、回答、恢复结果；未自然出现歧义则记录未覆盖 |
| T4 注释及预览 | 请求一个受支持的参考线、文字或观测峰注释，查看实际候选图后继续 | 单位/对象绑定、候选 PNG、实际变更与科学审计、接受或修订记录 |
| T5 最终导出 | 取得 PDF、300 dpi TIFF、CSV、可编辑 VSZ | QA、当前/导出/交付 VSZ 身份、数据对应关系、实际文件可打开 |
| T6 隔日恢复 | 次日启动新会话，找到原项目并完成一次修改或导出 | 恢复输入、候选项目、实际选择、当前项目身份、是否误建第二个项目 |

T3 可使用公开 `task` 的规则选择，或受支持 CSV/TSV 的一对源列选择；后者必须绑定当前
`expected_question_id` 并核对原始单元格。需要工作表选择、其他布局、缺失单位或不明确样品
对应关系的数据，记录原始证据与不支持的环节；不得把这些事实塞进 `rule_id`，
也不得用合成问题宣称真人已经遇到并解决真实歧义。至少一份独立来源的真实任务覆盖 T3，
否则该任务链的歧义验收仍未关闭。

每位受试者、每次任务尝试使用一条记录：

```yaml
participant_id:
prior_sciplot_development: false
task_id:
attempt:
status: not_started
source_sha256:
request_evidence:
task_path:
project_path:
started_at:
finished_at:
active_user_seconds: null
waiting_seconds: null
maintainer_interventions: null
intervention_details:
mistaken_project_choices: null
scientific_questions:
avoidable_workflow_questions:
failure_or_blocker:
recovery_attempt:
preview_review_evidence:
source_values_preserved: null
sample_and_unit_check_passed: null
qa_current: null
delivery_current: null
artifact_evidence:
```

人工观看候选图、最终尺寸可读性和原始科学信息核对分别记载。
Doctor ready、自动测试通过和历史任务 complete 不替代这些记录或当前交付检查。

## 4. 在同一真实客户端记录效率，随后才做前后对照

先保留未经优化的基线尝试。根据反复出现的具体问题实施改进后，使用相同任务范围、原始
数据与请求，匹配模型、客户端、工具配置和交付要求复测。为两种条件分配独立输出和任务
历史，避免因已经创建项目或图稿本来就满足请求而缩短第二次任务。确需测量热启动或
`unchanged` 行为时，将其列为明确的独立场景。

效率对照中每个配置和任务至少保留 3 次客户端尝试，用中位数、范围和逐次记录描述结果；
这些对照尝试单独记录，不要求每位受试者重复全部任务。3–5 名用户的小样本不代表人群
统计结论。受试者重复任务可能产生学习效应，记录执行顺序，
在可能时交替先后；不同构建之间未匹配的条件明确列为限制。

| 指标 | 统一口径 |
| --- | --- |
| 完成与失败 | 按 T1–T6 记录；失败尝试仍计入总尝试、耗时和调用 |
| 模型轮数 | 来自真实客户端日志的模型响应轮数；观察不到时为 null |
| 工具调用 | 包括 capabilities、任务操作、完整结果读取、PNG 读取、失败与重试；区分接口名称 |
| 返回文本字节 | 实际客户端工具响应文本的 UTF-8 字节数；能力发现与结果资源单独列项，保留总量 |
| 图片字节 | 解码后的 PNG 等图片字节单列；不把 base64 字符数当作图片字节，也不估算视觉 token |
| 总时延 | 用户提交请求至收到经过检查的任务结果；安装与隔日等待分别计量，不混入绘图时延 |
| 用户时间与等待 | 实际操作/回答时间、系统等待时间分别记录，保留总时长 |
| 用户问题与介入 | 真实科学问题、可以避免的流程问题、维护者介入分别记录 |
| Token | 仅使用客户端实际输入/输出及可见缓存遥测，记录统计范围；不可见时为 null |
| 质量检查 | 原始值、样品与单位、实际预览、科学审计、QA、交付当前性与任务范围匹配 |

若只能测得本地 CLI stdout、Python 对象的压缩 JSON 或 SDK 回放数据，单独标为本地测量，
不得填入“实际客户端返回文本”或 token 栏。JSON 压缩率、较少的 CLI 调用或 SciPlot 自身
`model_calls_by_sciplot=0` 都不等于外部客户端 token 节省。所有改变必须保留视觉检查和
真实科学问题；少做了这两步的运行不能作为效率改善样本。

```yaml
measurement_id:
acceptance_id:
participant_id:
task_id:
condition:
attempt:
client_trace_path:
client_trace_sha256:
scope_matches_comparison: null
quality_checks_passed: null
model_rounds: null
tool_calls_total: null
tool_calls_failed: null
tool_calls_retried: null
returned_text_bytes_total: null
capabilities_text_bytes: null
result_resource_text_bytes: null
decoded_image_bytes: null
total_latency_ms: null
user_active_ms: null
waiting_ms: null
scientific_question_count: null
avoidable_workflow_question_count: null
maintainer_interventions: null
token_usage:
  input: null
  output: null
  cached_input: null
  telemetry_source:
  reported_scope:
outcome:
limitations:
```

## 5. 关闭报告与阻塞

最终报告逐项列出构建、安装配置、3–5 人的完整任务结果、成功与失败次数、耗时、介入、
项目误选和证据索引。不能只公布总体成功率。至少覆盖干净 Mac 的真实客户端连接、一次
真实歧义、注释预览与隔日恢复；出现数据改变、科学信息错误或错误项目应用时，保留失败，
修复后重跑受影响任务，未解决前不关闭对应验收。

前后对照须给出匹配任务与质量检查、逐次测量、中位数及变化，公开未知项与配置差异。
没有 token 遥测可以关闭已有可观测指标的比较，但不能声称 token 节省。

| 未满足条件 | 状态及下一步 |
| --- | --- |
| 没有独立测试者或干净机器 | 安装/真人验收待外部条件，不用开发者或代理回放替代 |
| 没有真实客户端日志或匹配任务 | 端到端效率证据未完成，已有本地字节测量仍只作局部证据 |
| 构建身份、原始数据或最终质量不可核对 | 该次结果无效；保留失败原因并补齐后重新测量 |
| 当前 task 不支持所需科学回答 | 明确记录功能阻塞，进入相应科学功能工作，不绕过验证 |
| 发行签名、公证或跨版本测试未完成 | 仅报告实际测试的配置与发行阶段，不扩大兼容声明 |

本方案建立后，验收默认仍为 `not_started`。只有以上真实记录与对应证据完成后，才能在
报告中把某一项改为通过；路线图完成状态应依据该报告另行更新。
