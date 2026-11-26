# SciPlot 全项目开发路线图与任务拆解

**拍板：做成科研图的日常工作台。** 从真实实验数据出图，把科学选择说清楚；用户隔天打开同一张图，人工或 AI 都能编辑，最后只拿他想要的成果。优先闭合这条实际工作流，再删重复实现与验证。**单文件只是交付线的一个任务组，不是项目总主线，也不是其他功能的前置条件。**

## 终点与五条并行主责

| 主责 | 用户最后能做什么 | 保留的工程权属 |
|---|---|---|
| A 科研制图 | 原数据到图；明确就出图，需要用户决策才问；能核对样品、单位、原始点、转换、图稿。 | 原始来源/确认 → 科学规则 → Managed 文档/PlotIR → Veusz/Qt → 科学及发布 QA。普通输入逐族合一；专业套图有独立价值的继续支持。 |
| B 持久编辑 | 找回同图、审核再提交、恢复中断；可以人工或让 AI 改同一项目，互相可见且不覆盖。旧图能打开重画，想用新功能显式转换。 | 回执负责下一步，Store 负责版本，导出证据负责交付。CLI、MCP、真正编辑窗口调用同一个 typed 用例，不建第二张状态表。 |
| C 文件与交付 | 交稿、搬项目、另存、导出各有准确动作；单文件通过后像 OPJU 一样双击一个普通 .sciplot 文件进入真实编辑窗口，AI 指向它。 | 论文快照不是项目、位置不是身份、另存不是移动。单文件复用 Store 闭包与私有工作区，其他项目入口暂继续使用。 |
| D 工程减负 | 小改有短反馈，冻结版才统一长验收；新能力改一个明确的 owner，而非三个界面各实现一遍。 | 证实重复再删，迁完真实调用才关旧路。不能为了速度去掉独立科学、真实环境或数据边界。 |
| E 实际发布 | 新人按指南安装、出图、隔日续编和交稿，不需要维护者接手；失败能区分没保存与没交付。 | 同版本源码、独立真实科学、Mac 发包和真人分开取证。正式公开另有开发者签名、公证及 Gatekeeper。 |

**不变原则。** 原始数值、单位、样品、科学数据身份、图修订和发布产物有各自事实来源。观察本身不写入、不偷恢复。项目历史唯一由 ProjectCommands/FileProjectStore 维护；Veusz 保存不是项目提交。可以改产品默认动作，但不能复制一个新 Store、渲染器或 AI 输入层。大决策应减少重复职责，小 PR 使其中每个决定都能验证。

## 当前起点

这是开发任务和完成条件的唯一队列。[README](README.md) 描述已交付的产品；
[架构](docs/ARCHITECTURE.md) 记录代码归属，[复杂度证据](docs/COMPLEXITY_REDUCTION_PLAN.md)
保留设计边界和实测历史。External AI is the task interface；CLI、MCP 和真实编辑器都使用同一应用层。

- 科研制图：已绑定两条实际验收用例，选定的原始列、数值及单位均已有本地证据。显式
  FTIR 选样可叠放不同长度的原始谱，不补点、不跨缺口；真实外部客户端与独立科研验收仍待。
- 项目与交付：可将多图及其历史存为一个普通 `.sciplot` 文件，离线搬移后仍用原图 ID。
  已验证从命令行、日用 MCP 和离屏原生编辑器在同一文件修改选定图轴标题，保存后可单独导出
  选定图的 PDF/TIFF。尚未在真实 Finder 或独立 Mac 验收，默认入口不切换。
- 工程与发行：普通修改用所属短测，冻结候选才统一发版验收。现有可用 Mac 画图版保留；
  当前路线图源码、独立 Mac 候选和主干发行不是同一版本。下一批优先实际客户端闭环、
  归档编辑耗时及 Mac 原生交接，不重复已通过的旧版 CI。

## 节点、开工与 PR 规则

| 阶段 | 收口条件 | 先后和并行 |
|---|---|---|
| M0 收拢已做成果 | 当前版本和验证是谁的一清二楚，接回真实会话恢复，用户指南用真实动作。 | **先并行 08（合并已证恢复/修首页）、01（选真实科研用例）、23（短反馈基线）**。20 单文件 PoC 可另开隔离树，不抢本批核心 owner。 |
| M1 日常闭环 | 原始数据、明确科学选择、实际审核、隔天开同图、一次失败恢复、取所要的成果；至少一条现实研究轨迹。 | A 02–05、B 09–12、C 16–18、D 24–26；E 28 可前置。单文件可以独立收口，不阻塞 M1。 |
| M2 减重并冻结候选 | 一个普通家族一条核心实现，删除的调用和证据明确；编写短验证并证明未丢关键反例；形成审查就绪批。 | 只做测出来的重复。20–22 如果验证成熟，作为被选入发布的功能；未熟则继续用已证入口。 |
| M3 真正发布 | 同一确切候选有 Linux 完整检查、真实科学、实际可安装 Mac 包、真实客户端/独立用户；公开标志对应真签名、公证及 Gatekeeper。 | 冻结后取一次官方证据，不并行重复一个职责。不把「单文件没做完」当其他能力发不了的理由。 |

**工作切法**：一张卡一份 PR 意图，一个负责 owner、一个用户或开发者可见结果。隔离相互冲突的文件；共享 receipt、保存或编辑入口先合并上游再开下游。短反馈在本地完成，不把每个小提交推到会触发 full 的 integration ref。复核差异、实测与实际删除，再决定合入。涉及科学、写入和原始数据的约定先写正反例再改；不为跨过行数、无环或分类门去改门。source-only 白名单不是所有文档，别凭文件扩展判断远端开销。

## 工作卡（33 张）

### A · 科研制图（01–07）

| 卡 / 前置 | Owner、输入→输出及增删范围 | 短验收 / 失败语义 |
|---|---|---|
| **01 P0 定两条现实研究轨迹**（无） | 科研 owner；优先复用已做合规验证的双样品 FTIR，第二条从有实用需求的流变/力学专用族中选，写入已有科学验收用例。公开负例用合成数据，不共享实验原件。 | 每条给原列、物理单位、样品、X、缺失、预期结果；至少一次真实歧义。无私有授权先用合成，明确真实未验。 |
| **02 P0 只问当前科学决策**（01） | task_semantic_creation.py、来源与 table selection：已选源和列→当前问题/选项；绑定一次原始字节和问题 ID，去与当前任务无关的提示。 | 合成首图的实际 Mass/Weight 任务只问一次，双源映射不串；未答不提交，源或 question 变动拒绝原回答；不能猜单位。 |
| **03 P0 输出能核对首图**（02） | 复用现有合成首图、QA 与真实 STDIO；首图提供原样品、轴单位、当前图和续编入口，删不必要的再次 inspect 提示。 | 既有双组原始数值断言外，核样品标签、秒/百分比；真 PDF/TIFF 及实际 300dpi。源含义不成立没有假图。 |
| **04 P1 普通 XY 只一条创建本体**（02/03） | task_control.py:95–186 和 task_semantic_creation.py：旧 source-only 公开形状可留作薄译，普通 CSV/表格走同一来源、Managed/IR、恢复；删除被取代的内部 raw/Studio 调度。不把专用套图一锅端。 | 两入口同数据、重复 X、缺失值、单位、log 域、结果与恢复一致；已有旧请求仍恢复；不凭 fallback 偷换算法。 |
| **05 P1 原始数据追加/更新**（02/03） | source_append / task_source_execution：同图明确追加一组或版本化更新其来源，复用已有科学审阅；样品实体与显示名分开。 | 原曲线值不动、新曲线保留独立网格和单位；未审/取消/旧版本不写；重复的数据映射不能偷偷变新增。 |
| **06 P1 只迁一个真正在用的科研族**（01/04） | 由 01 的现用族挑一条，现有 reader、规则 owner、ProjectCommands 合共享源码；独立科学能力仍留。不同时迁两族。 | 同输入、同 runtime 审真实图/数据保真；保持已支持的内部检验。只保确有价值的改法，不见收益就停。 |
| **07 P1 样品体系的组图/比较**（03/05） | 已有组图/managed_comparison/paper：两张实际图→排序、候选和交付；复用已完成的候选资产，不再重算相同版本。 | 审核的是交出去的版；指定次图不改另一图，需比较的候选不改 head；取消或 stale 不声称完成。 |

### B · 续编、人工/AI 编辑与旧图（08–15）

| 卡 / 前置 | Owner、输入→输出及增删范围 | 短验收 / 失败语义 |
|---|---|---|
| **08 P0 合入已证待审重连**（已本地验证） | 已合入待审恢复；Welcome 使用实际经过审核的显示名例。沿现有下一步/预览，不添加强制审核新参数框架。 | 同一候选跨会话可读、明确确认前 0、后 1；原数据不变、文件存在。只跑有冲突或有新变化的短测。 |
| **09 P0 打开的一直是同一张图**（08） | task_saved_work.py、target_adapter.py：返回 exact 图+当前修订，使用有限搜索和显式选择；删由旧任务投影代替当前图的残余调用。 | 真实两图选第二；改名、别名、重名/多候选不误写或偷偷创建；已有 cold saved-work 原生测试。 |
| **10 P0 已存未出图就只补导出**（08/09） | project_lifecycle/receipts.py、recovery、export owner：复用原操作键；把「已存」「导出失败」「可交付」分开。 | 注入第一次导出失败/丢回复；真实重试只有一个科学修订，补 PDF 后实际版本一致；过期候选不被重新采用。 |
| **11 P1 人工真实窗口接同一事务**（08/09） | 复用已随包的 Qt/Veusz；先给当前 Managed 图一个能写的动作（如改轴标题），走现有 typed patch/必要审核；不用重写编辑器，**不等单文件**。 | 真做一个人工编辑，AI 读到同修订；AI 再改时窗口刷新，旧窗口后写不覆盖。只有截图/只读预览不算完成。 |
| **12 P1 未知原生变更不给项目提交**（10/11） | managed_external.py、managed_description.py 当前只检查、不自动采纳。若一项实际属性有完整科学/原生等价，按现有 typed 事务接入；否则只保暂存、另存 VSZ 或显式丢弃。 | 支持项真实可写；混入未表示原生对象或科学变化就不改项目。关窗说明未保存，不把 native Save 偷当项目保存。 |
| **13 P1 归档最小兼容**（09/1c80db8e） | legacy_saved_plot.py / legacy_conversion.py：现有归档只读、原样重画、受支持 XY 显式转换；保留已经密封的历史恢复和真实 NativeSuite，按实际 authority 而非 LegacyPlot 字样。 | 像素等价、原树字节不变；不支持的重画仍可做且不会产生新成品项目；历史已提交请求只补以前例程的效果。 |
| **14 P1 错误直接告诉人怎么继续**（09/10/12） | 按现有 owner 错误投影；MCP、task、Welcome只覆盖找不到源、权限、过期、已存待导出、原生不支持；删被替代的英文子串猜测，不采集遥测。 | 五类真反例能说清状态与下一步；可显式导出摘要不含原始值、绝对路径、样品、凭据；不自动外发。 |
| **15 P2 退役一条有证据的旧写分支**（13） | Legacy owner 逐个追 CLI/MCP、task、backend、已保存恢复的消费者；无人使用且已有替代才删这一条；旧史和保留承诺不删。 | 给历史正例、无写反例、替代调用者；没有完整证据暂不删，不能用模糊的“都过时”。 |

### C · 文件与交付，单文件仅占 20–22（16–22）

| 卡 / 前置 | Owner、输入→输出及增删范围 | 短验收 / 失败语义 |
|---|---|---|
| **16 P0 只产生用户点名的输出**（03/10） | output_contract.py、既有 per-plot export：公开只写所选格式，必要 QA 和中间件留现有私有区。先在现有支持项目上给好结果，不等单文件。 | PDF 只写 PDF；PDF+TIFF 只两种，真实 300 dpi；目标已存在不自动覆盖；失败不使已存项目倒退。 |
| **17 P0 交稿、搬迁、另存分明**（2be96e2c/16） | 沿既有 plot_deliver、project bundle export/import、project_save_as，以通用词表及回执说明三个动作。不要再写搬迁代码。 | 快照能交稿不是项目；移动保原 ID/代际/历史及权限边界；另存新 ID、不改原档。沿用已过定向原生场景。 |
| **18 P1 专项产物显式导出**（16/17） | 保留原有绘图 CSV、独立 VSZ、论文包及明确诊断入口；从确切修订出发，删默认“顺手多写”。 | 真文件可开、原始样本及单位可追，错版本/路径拒绝；没有创建默认散件。 |
| **19 P1 现有目录的离线续编**（17） | portable.py、relocation.py 的流式闭包与离线恢复不重写；把「原路径已不可达」的报错和用户动作收口，不继承旧外部导出或 host grants。 | 清除原数据/以前项目路径，移动后继续原项目、同 ID/历史并写新目的地。原外部交付位置不变。 |
| **20 P1 普通单文件闭包 PoC**（与 01/08/23 可并行） | project_lifecycle 中薄 file adapter。选普通 <项目>.sciplot / ZIP64 版本化容器，封现有 Store 可达的来源、项目历史、命令和必要原生证据；私有工作区可重建。不是看似单件的 Finder package，也不重写 SQLite/Store。 | 单图关闭后只拎这一文件，清旧源和缓存后同 ID、原数值、两代历史；坏清单/重复/截断拒绝。保存同目录临时校验刷盘再原子换、基线变则拒绝；中断最多旧/新之一，不得生成半项目或重复应用。先由 root 复核文件边界。 |
| **21 P1 单文件真实窗口+AI**（20/11/12） | 现有 macOS entrypoints/launcher 目前固定 Welcome 且无文档关联；做类型和实际 FileOpen 入口，用 bundled Veusz 窗口。公开 handle 是文件+图 ID+修订，人/AI 复用同 typed 事务。保存只发布经接受的修订，不让原生 Save 覆盖 Store。若项目文件没替换成功，用户可见版本仍是上一版，明确提示「未保存」并给再次保存或恢复的动作。 | 真双击、手动一改、AI 同档再改；离线移到新目录仍可续编。过期窗口、替换失败、未知编辑得明确提示和处理，不覆盖有效文件。外侧只出现 .sciplot 及所选产物，未完成实际使用或独立安装，不报通过。 |
| **22 P2 单文件扩展及默认切换**（21） | 多图、超大资料的读写和兼容扩展按真实样本逐个切；先测峰值空间/耗时，不为猜测加缓存/数据库。21 通过才在新项目默认引导，并保留明确旧入口。 | 两图不得默认写第一张；格式新旧有清楚动作，保存仍同一权属。若没过，照常交付其他线。 |

### D · 技术债与验证（23–27）

| 卡 / 前置 | Owner、输入→输出及增删范围 | 短验收 / 失败语义 |
|---|---|---|
| **23 P0 作者一个短测入口**（无） | verification/changed.py、reviewed_feedback.py 与开发指南；现有 verify --changed，比较文档、普通叶、共享科学边界三例。未知补映射或记全量未走，不假造覆盖。 | 普通修改加所属测试能选对，移动/删除与未知可说明；执行段和未覆盖可见；不在所有工作树机械长测。 |
| **24 P1 删一项有实证的重复验证**（23） | 保持现有共享 staging 和两个隔离 pytest 程序；找临时 wheel/实际制作的包或重复源码断言的一处，等价才删第二次。 | 已知坏 wheel/路径真实拒绝、覆盖不降；实测量诚实，少了步骤不是一定省几个小时。不重开同 SHA 证明。 |
| **25 P1 大证据只保存必要表示**（23） | 读 docs/COMPLEXITY_REDUCTION_PLAN.md 中 4.97 GB 派生实例及实际外部操作链，不能假定 production 有三次复审。确认消费者后归并操作者的重复视图；保原始捕获、访问事实和原错误。 | 同失败值和反证不丢；按同输入比较实际次数、大小或时间；不另建通用认证框架或删除历史证据。 |
| **26 P1 删除真正替代了的旧 owner**（04/09/16 任一结束） | 一次只收普通创建、旧结果投影、或实证的重复 renderer 调用之一；真实调用迁完才删旧路、废文档和等价测试。 | 老/新实际入口与错输入回归；分别列删掉的代码和留下的合同，保持无环和行数门。从现在架构删真正重复，不添 façade 冒充。 |
| **27 P1 合批及开发残留清理**（23/24） | root 维护 exact SHA、工件和证据，在末端审真实合并树、必要才长测；明确一条集成分支。只清授权可重建物，不动用户脏工作树、实验数据与有效证据。 | 短门、大门、Mac/科学的结果分开；正常 fast-forward 后核实远端。删除前核实对象和身份，大小和年龄不作证据。 |

### E · 真科研、真用户、真发行（28–33）

| 卡 / 前置 | Owner、输入→输出及增删范围 | 验收 / 失败语义 |
|---|---|---|
| **28 P0 准备真实客户端试用**（01/08） | 保留现有官方 MCP SDK 的合成例，用 docs/INDEPENDENT_ACCEPTANCE.md 给实际用户轨迹。只用获准的隔离客户端配置，不改用户现用设置、不上传私有实验、不调用未授权付费模型。 | 协议、配置在真客户端、开发机移址、干净机分开记；没有真实客户端就明确没做，不能替代。 |
| **29 P1 开发环境完成现实纵向**（M1） | 用确切构建和同一真实客户端，真实作图、询问、待审、隔日回来、一次故障恢复、选定格式交付。选择已证入口，不以单文件为前提。 | 记录第一次尝试、真实失败与维护者介入；原始值不改、文件可开、重开仍同图。使重复发生的卡点排未来优先。 |
| **30 P1 真实科学和稿件验证**（01/29） | 独立科学 owner：指定获准真实源、实际版本、转换及现有私有 access/evidence（需要时）；公开汇报不含实验原件。 | 实测原值/行/单位/样品、两族独立关键指标以及实际 300dpi/矢量；合成例不能充代，包测试也不能代。 |
| **31 P1 干净机与独立研究者**（29） | 另一台不带 Python/Qt/Homebrew 的 Mac，正式候选安装入口和真客户端，3–5 独立非开发用户首试，至少一个真实歧义 T3。现有正式规程不重写。 | 记录无帮助尝试、错误与后续帮助。开发机新账号不充洁净。需联系新人/用新渠道时依授权；条件缺则只是受控候选。 |
| **32 P1 冻结并发行**（27/30/31） | exact SHA 官方 Linux complete 一次，真实 Mac 包及科研各自检查；现有 verification.py/release.py 做 Developer ID、公证、Gatekeeper 与 ZIP SHA256。正常晋级并核实主干。 | 缺相应证据就只声明测试范围。单文件若未过 21，保持旧可用入口发布其余项。不得另触发同 SHA 重复证明。 |
| **33 P2 真使用驱动后续**（29/31） | 对实际记录的卡点分别建任务。只在真实用例需要时选 PDF 批注、样式复用、另一个科学族或平台。可参考竞品真实流程和可用许可代码，不为了相似而复制。 | 大需求同样变可执行一张卡、一条测试、一次真实结果。没有用户、数据和受益，不铺功能。 |

## 容易做成大 PR 的卡，按小交付再切开

- **11a 编辑入口**：打开现有图和原生窗口，核对选中图及基线，打开本身不改磁盘。**11b 同版本保存**：只接一项已支持的展示编辑并让 AI 读新版本；旧窗口不能覆盖 AI 新版本。完成 11b 才叫可编辑，不把 11a 说成已交付。
- **14a 打开失败**：先收口缺源/权限，CLI 与 MCP 给同一可执行动作，不创建假项目。**14b 续编失败**：接现有过期/未导出回执，验证不会重复提交。**14c 用户显式导出的诊断摘要**：从上述真实结果抽取状态，检查不含样品、原始值、绝对路径和凭据。不要为了摘要先造通用日志系统。
- **20a 文件闭包**：限定一个已支持的 Managed 图，封装/导入沿现有 portable owner。**20b 安全保存**：先验证版本、临时空间和实际读回，再跨进程测试写中断与过期拒绝，成功才替换。**20c 离线移址**：关应用，移走原路径、清工作区，单独拿文件开，核对原数据、两版历史并再导出；测一次代表性项目的实际保存成本。不要用通用目录打包器当文档导入。
- **21a Finder 打开**：真实安装入口接受文件、空启动仍到 Welcome；未知格式给出错误，不执行文件内命令。**21b 双向同档**：先人改→AI 核对，再 AI 改→人重开；未知原生修改不写入。**21c 可见文件**：仅选 PDF 时目录只有项目文件和 PDF；CSV/VSZ 是主动导出。项目文件可能含原数据，分享图片和分享项目始终是两件事。
- **32a 源码晋级**：核定一个候选 SHA 和一次完整官方验收，记录结果再晋级。**32b macOS 分发**：完成同源包验证、开发者签名、公证和 Gatekeeper，保留校验值。真实用户及科研证据不由上述两项代替。

## 统一验收和不做

- **正常反馈**：每张卡只跑对口已有/新增节点、Ruff 与必要类型，一个真实正例一个真实反例。真实科研或原生原件的改动必须选真实路径，不能用全 mock 冒充。集成时用 exact SHA 复核组合、收集与证据绑定。冻结候选只完整跑一次该跑的官方检查；原两次运行归原版本，不能证明新代码。
- **独立出口**：正式签名/公证、外部真实 AI 客户端、另一台干净 Mac、真实独立用户与科研证据仍按原门；区分暂存、已保存、已交付和已发布。目录清理、外部使用和科学数据都有明确各自授权；不利用用户同意压过实际验收。
- **唯一活路线**：本文件拥有任务和完成条件；独立验收与复杂度记录保留规程和证据，不再列平行任务队列。
- **明确不做**：自带 AI 后端、通用新编辑器/渲染器、OPJU 格式复刻、旧格式完全兼容、云同步多主、SQLite 重写、无用户的跨平台移植、推测性状态机/缓存/CI 调度器。也不靠修几个表面小问题冒充产品闭环。

下一轮验收先展示一次从真实源到隔日继续、正确交图的工作，再考虑增加功能。

## 独立验收细则

### Independent beginner and installation acceptance

See cards 29–31. Follow the [existing procedure](docs/INDEPENDENT_ACCEPTANCE.md)
with an exact supported Mac build, a genuinely clean Apple-silicon Mac and
3–5 non-developers in an actual external client. Verify their own data, a real
ambiguity, review, export and next-day recovery. Inspect original values, units,
sample/physical row identities, and the same figure ID. Record first attempts,
interventions, friction, and positive/negative outcomes; keep unknown usage unknown.
Local relocation, synthetic fixtures and SDK discovery are not this human usability evidence.

Complete independent original-source coverage for advertised table choices,
including untouched workbook/FTIR metadata, selected pair/worksheet/region,
changed-value cross-sheet revisions, explicit units, original Test/block
selection, missing values, binary64 round trips, source append (including an unused pair or independent Test in the same file),
categorical and replicate statistics, and frequency/viscosity metadata. Retain
raw-only point behavior, valid-n and missing-policy disclosure, compatible
true grids, and complete original row/missing domains through native export.
A rule-selection answer must not encode arbitrary scientific facts; extend
reusable profiles only when current headers, units and mappings can be validated.
Generated tests or shift/fitting assumptions do not substitute for original-source
evidence.
Use the existing [metadata](docs/SCIENTIFIC_METADATA_ACCEPTANCE.md),
[table range](docs/TABLE_RANGE_ACCEPTANCE.md) and
[source update](docs/TABLE_SOURCE_UPDATE_ACCEPTANCE.md) protocols and preserve
known visual gaps: e.g. independent legend collision, mechanical individual
points, previously delivered dual-Y and multipanel checks, and cross-host font
evidence are not inferred from native or geometry success. Do not silently move
a fixed legend or claim unavailable font-face evidence.

For **Reviewed annotation rebinding**, independently test untouched source
revisions with moved, missing and multiple observed peaks. Check exact
metadata/values/samples, preview/approval, native/spec/CSV export and actual
interrupted-update recovery. A generated edit or fault injection cannot
replace a real revision, and an unchanged XRD pair does not cover these cases.

### Freeze and qualify one candidate for release

See card 32. Bind exact Linux whole public CI, native Mac build/relocation
and independent real-science results to the same candidate. Keep separately
required local private full and complete access capture: exact collected
nodes/parameters, authorized original raw/golden inputs and bytes, child
startup/exits and socket/access epoch evidence, original waits, declared and
undeclared file/metadata controls. Keep private inputs and streams local.
Incomplete observation, capture or runtime authority remains blocked; do not
promote the preliminary inventory from static review or a passing subset.
Retain cold replay for original sealed DataMapping executions and strict
version-3 preparation; old-reader unit controls do not certify native recreation.

Use the [existing beta/release process](docs/PUBLIC_BETA.md). Public delivery
requires Developer ID signing, stapled notarization, Gatekeeper and exact ZIP
identity/checksum as well as the independent Mac/client outcomes. Do not claim
other platforms/font configurations or physical print/journal acceptance.
Keep the same proven artifact, check actual branch rules before a normal
fast-forward, and separate already-pushed source from default upgrades or
publication. No backup or cleanup of private inputs/evidence is implied.
