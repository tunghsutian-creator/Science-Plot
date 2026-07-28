# SciPlot 架构审计与重构记录

日期：2026-07-28  
范围：`src/sciplot_core`、`src/sciplot_gui`、`src/sciplot_recipes`、相关测试和打包配置  
约束：不改变公开 CLI、Python 导入路径、请求/manifest/VSZ/交付格式或用户可见行为

## 结论

审计前的主要问题不是单个文件偶然偏大，而是多个业务域长期堆叠在平面模块中：
入口解析、科学语义、数据转换、Veusz 文档构建、GUI 装配、项目状态、QA 与交付经常
共享同一文件；依赖只能通过大量私有函数互相穿透。重构后，公开模块名保留为兼容门面，
实现按业务职责进入有名称的包，CLI 作为组合入口，GUI 只依赖 Core 的业务/服务契约，
Core 业务与数据层不反向依赖 GUI。

当前一方 Python 模块图无循环依赖；普通实现文件均不超过 400 行。仍超过 400 行的
11 个文件全部是精确列名的线性集成验证脚本，已由架构测试锁定，不允许白名单扩张。
原先 39,372 行的 `_vendor` 兼容树也已完成活跃能力迁移并整体删除；项目不再通过
`src.*` 导入或运行时 `sys.path` 注入访问另一套隐藏架构。

## 一、审计基线

基线取自本次修改前的 Git `HEAD`。下表当时排除了另行审计的 39,372 行迁移兼容树
`src/sciplot_core/_vendor/`；该树已在最终阶段删除：

| 指标 | 审计前 |
| --- | ---: |
| 一方 Python 文件 | 75 |
| Python 行数 | 82,195 |
| 超过 400 行 | 45 |
| 超过 1,000 行 | 29 |
| 静态导入强连通分量 | 7 |
| 跨模块私有实现导入 | 81 |
| `_utils.py` 直接依赖者 | 43 |

最大的文件及其混杂职责：

| 原文件 | 行数 | 混杂职责 |
| --- | ---: | --- |
| `studio.py` | 14,741 | 请求解释、数据系列、布局、Veusz 命令、Qt 窗口、保存、导出、项目发布 |
| `semantic.py` | 5,814 | 识别、分类、单位、样品命名、各实验预处理、输出表 |
| `smoke.py` | 3,218 | 环境、映射、语义、标签、标量场、交付、总门禁 |
| `materials_rules.py` | 2,635 | 规则模型、词汇、单位、实验特定规则、注册表 |
| `veusz_worker.py` | 2,441 | worker I/O、文档操作、spec 审计、数值证据、CLI |
| `workflow.py` | 2,134 | 请求执行、自动拆图、repair、bundle、状态写入 |
| `performance_comparison.py` | 2,106 | 表验证、指标、归一化、legend、几何和请求 |
| `intake.py` | 2,000 | 会话、路径安全、分组、项目生成、打包 |
| `readiness.py` | 1,940 | 注册表、证据、规则判定、报告 |
| `qa.py` | 1,939 | 文件检查、PDF/TIFF、样式、可访问性、发布 QA |
| `data_mapping.py` | 1,830 | 映射模型、验证、转换、执行、状态 |
| `studio_project_status.py` | 1,673 | 项目证据聚合、状态机、用户消息 |

## 二、原模块职责与主要依赖

审计前的平面职责可归为：

- 入口层：`cli.py`、`intake_server.py`、`studio.py` 的命令分支；
- 科学规则层：`materials_rules.py`、`semantic.py`、`mapping_contract.py`；
- 数据处理层：`data_mapping.py`、`study_model.py`、`plot_data.py`；
- 渲染与编辑层：`render.py`、`studio.py`、`veusz_worker.py`、
  `performance_veusz.py`；
- 编排层：`workflow.py`、`one_step.py`、`autoplot.py`；
- 证据层：`qa.py`、`readiness.py`、`delivery.py`、`evidence.py`、
  `source_coverage.py`、`visual_review.py`、`acceptance.py`、`smoke.py`；
- 展示层：`sciplot_gui` 下四个大型平面模块；
- 配方层：`sciplot_recipes/common.py` 和薄配方模块。

主要运行依赖为：

```text
CLI / browser adapter
  -> workflow / autoplot / studio lifecycle
  -> semantic rules + mapping + study model
  -> render specification + Veusz document operations
  -> exact-current export
  -> QA + readiness + delivery + evidence
  -> source tables + source inspection + policy contract
  -> pinned Veusz boundary

Veusz MainWindow
  -> SciPlot GUI docks
  -> Core project/export/assistant service contracts
```

问题在于这些方向没有在目录和公开接口中表达清楚。典型表现包括：

- `studio.py` 同时是业务门面、渲染实现和 GUI 组合根；
- Core 的 Qt 菜单代码直接导入 `sciplot_gui`，形成底层反向依赖；
- `intake.py` 同时持有纯领域逻辑和 browser 项目组装；
- `_utils.py` 集中哈希、JSON、文本、路径、命名等无关能力；
- `common.py` 以泛化名称承载材料配方实现；
- 文件拆分前存在 7 个静态导入环；
- 多个 GUI bridge 重复解析当前窗口文档路径；
- 大量内部函数只能通过跨文件私有导入复用，公开边界不明确。

## 三、重复逻辑与复杂度审计

发现并处理的真实重复包括：

- 文件哈希、JSON 安全值、文本解码、路径命名从 `_utils.py` 分离到具名
  `foundation` 模块；
- Project 与 Assistant bridge 的当前窗口文档解析合并到
  `sciplot_gui/window_context.py`；
- Studio 项目服务依赖集中到 `StudioProjectServices`，不再由 GUI 到处导入
  Core 私有实现；
- 多个旧平面模块的常量、模型、I/O、纯转换和 orchestration 分开归属。
- canonical JSON 哈希集中到 `foundation/json_hashing.py`，数据映射、readiness、
  source coverage 和 assistant history/provider 不再各自复制序列化与哈希实现；
- Project 状态 facade 只保留有意义的 patch seam，实际装配由单一 status adapter 完成。

重构后的精确 AST 函数体扫描只剩 5 组重复：

- 两个 9 行时间戳规范化函数，分别属于 assistant 文本验证和 mapping 值模型；
- 两个 9 行可选文本函数，分别服从不同的错误文案和长度默认值；
- 三组 `_check` 函数，全部位于彼此独立的黑盒 probe/smoke 场景。

这些实现短小且业务语义/证据格式不同；强行抽取会制造共享测试工具或跨域耦合，因此保留。

## 四、目标目录和职责

```text
src/
  sciplot_core/
    cli/                    参数注册、命令分派、组合入口
    foundation/             哈希、JSON、文本、路径命名等具名基础能力
    materials_rules/        科学规则、指标、单位、别名和规则注册
    semantic.py             旧公开 API 的兼容门面
    semantic_sources/       各实验族识别和纯数据准备
    mapping_contract/       映射模型、提案和验证
    data_mapping/           映射计划执行与状态
    study_model/            研究/实验模型与计划
    plot_data/              源表读取、spec 转表、用户 CSV 导出
    source_tables/          原始表解码及曲线、重复值、热图数据解析
    source_inspection/      输入形态识别及生产模板建议
    policy/                 全局视觉、轴、布局、导出和绘图契约
    render/                 renderer-independent 请求到渲染结果
    studio.py               旧公开 API 的兼容门面
    studio_render/          纯系列、轴、布局和 plot-spec 转换
    studio_core/            VSZ 生命周期、保存、导出、发布和 Qt 端口
    workflow/               confirmed request 编排和 bundle
    one_step/               内部 readiness/manifest 生命周期
    autoplot/               自动化公开适配器
    qa/ readiness/          制品检查和规则证据判定
    delivery/ evidence/     交付构建和证据模型
    source_coverage/        来源覆盖证明
    visual_review/          显式人工视觉决定记录
    acceptance/             ready-rule 生命周期矩阵
    smoke/                  按验证场景组织的 runtime 门禁
    veusz_worker/           worker 协议、文档操作和 spec 审计
    veusz_audit/            exact-current VSZ 只读审计
    *_probe.py              线性黑盒集成证据脚本
  sciplot_gui/
    main_window_menu.py     MainWindow 菜单和 Dock 组合
    window_context.py       当前窗口文档上下文
    studio_project/         Project Dock 展示与交互
    studio_project_status/  纯项目状态聚合
    studio_assistant/       selected-object AI Dock
    studio_assistant_history/ Assistant 历史模型和存储
  sciplot_recipes/
    material_recipe.py      材料配方执行
    registry.py             配方发现
```

目录最多使用“包 / 明确子域 / 模块”三层；没有继续创建
`utils.py`、`helpers.py`、`common.py` 或 `*_common.py`。

## 五、依赖方向

允许的方向：

```text
CLI composition root
  -> GUI presentation installer
  -> Core public facades

GUI presentation
  -> Core service contracts and immutable/pure status data

autoplot / workflow / one_step
  -> semantic + mapping + render + studio

semantic + mapping
  -> materials rules + study model + foundation

studio_core
  -> studio_render + policy + Veusz boundary

QA / readiness / delivery
  -> saved artifacts + public evidence contracts
```

禁止并由测试检查的方向：

- Core 业务/数据层不得导入 `sciplot_gui`；
- 一方模块不得形成导入强连通分量；
- 不得新增泛化万能模块；
- 不得新增未列入精确白名单的超 400 行普通源文件。

CLI 是组合入口，因此可以装配 GUI；GUI 再向下调用 Core 服务。窗口菜单已从
`studio_core` 移入 `sciplot_gui/main_window_menu.py`，Core 仅保留可注入的
窗口 presentation 端口。

## 六、分阶段重构

| 阶段 | 单一目标 | 状态 |
| --- | --- | --- |
| 0 | 固化基线、写入架构规则、建立审计指标 | 完成 |
| 1 | 拆除 `_utils.py`，建立具名基础模块，消除首批导入环 | 完成 |
| 2 | 拆分 CLI、intake domain、browser server/static adapter | 完成 |
| 3 | 拆分 rules、semantic、mapping、study/data transformation | 完成 |
| 4 | 拆分 Studio 纯渲染、VSZ 生命周期、Veusz worker/audit | 完成 |
| 5 | 拆分 workflow、autoplot、QA、readiness、delivery/evidence | 完成 |
| 6 | 拆分 GUI bridge/status、assistant/openai provider，倒置 GUI 依赖 | 完成 |
| 7 | 拆分 smoke 场景、增加架构门禁、更新文档并执行全局验证 | 完成 |
| 8 | 迁移 `_vendor` 活跃能力，删除第二渲染器/Data Studio/兼容注入和整棵旧树 | 完成 |

每个阶段保留原模块导入路径作为门面，并在进入下一阶段前运行相关 Ruff、
`compileall` 和聚焦测试；关键阶段运行全量 pytest。

## 七、文件变化计划与落实

新增：

- `agent.md`：用户指定的长期架构规则；
- `tests/test_architecture_boundaries.py`：规模、循环、层级和命名门禁；
- 本审计记录；
- 上述按业务域命名的实现包和模块。

移动/拆分：

- 30 余个大型平面模块变为同名包，原 Python import 名保持不变；
- `intake_static/` 移入 `intake/intake_static/`，同步更新 package data；
- `sciplot_core/studio_core/qt_menu.py` 移至
  `sciplot_gui/main_window_menu.py`；
- `sciplot_recipes/common.py` 移至 `material_recipe.py`；
- `batch.py` 和 `plot_data.py` 分别按 source discovery、spec/table、
  export/report 职责分包。

删除：

- 泛化 `_utils.py`；
- 被同名业务包替代的旧大型平面实现文件；
- 泛化的 `sciplot_recipes/common.py` 实体文件。
- `_bootstrap.py`、vendor boundary 门面和整个 `src/sciplot_core/_vendor/`；
- 无生产调用方的 Matplotlib renderer、旧 Data Studio、reference-only
  template 生命周期和相关持久化实现。
- 不再被一方源码使用的 `matplotlib`、`seaborn`、`scienceplots` 和
  `charset-normalizer` 安装依赖。

修改：

- 所有调用方 import/export；
- `pyproject.toml` package-data 路径；
- GUI topology、autoplot、visual-review 和架构测试；
- probe 的明确 presentation 安装；
- `docs/ARCHITECTURE.md`、`DEVELOPMENT_ROADMAP.md` 和
  `DEVELOPMENT_LOG.md`。

兼容措施：

- `studio.py`、`semantic.py` 和同名包 `__init__.py` 继续导出旧 API；
- CLI 的 `run_autoplot`、`serve_intake` 等 monkeypatch seam 保留；
- `sciplot_recipes.common` 通过延迟包属性解析到 `material_recipe`，保留旧导入和
  monkeypatch 行为，但不恢复 `common.py`；
- worker 和 CLI 包提供 `__main__.py`，保留 `python -m ...`；
- 静态资源、launcher source root 和 registry 默认路径按新包位置修正。
- 旧检查结果中的字段名和请求/manifest 数据格式保持不变；输入建议只返回当前 Veusz
  文档构建器真正实现的模板，不把 reference-only 模板伪装成已支持功能。

## 八、完成态规模与例外

删除 `_vendor` 后当前有 598 个一方 Python 文件，其中 545 个为非
`__init__`/`__main__` 实现文件：

- 308 个实现文件位于建议的 100–300 行；
- 361 个实现文件位于 100–400 行；
- 其余较小文件主要是公开门面、模型、常量、协议适配器或单一
  I/O 责任；
- 普通实现文件没有超过 400 行。

超过 400 行的精确例外：

- `analysis_contract_probe.py`
- `data_mapping_probe.py`
- `openai_provider_probe.py`
- `readiness_probe.py`
- `semantic_contract_probe.py`
- `smoke/runtime.py`
- `smoke/scalar_field.py`
- `smoke/semantic_parser.py`
- `studio_assistant_probe.py`
- `studio_figure_set_probe.py`
- `studio_project_probe.py`

这些文件是顺序敏感的黑盒证据 harness：初始化、故障注入、攻击样本、恢复和证据汇总
共同构成一个场景。继续按行数拆分会把同一证据轨迹分散为无独立复用价值的小文件。
架构测试要求当前超限集合必须与该列表完全相等；新增例外会直接失败。

## 九、全局检查结果

- 普通源文件无无理由的 400 行以上文件；
- 一方静态导入图无循环；
- Core 业务和数据层无 GUI 反向依赖；
- 无 `utils.py`、`helpers.py`、`common.py` 或 `*_common.py`；
- 精确 AST 扫描只剩 5 组有意保留的短小/验证器重复；
- 未创建只有无意义一层转发的业务 wrapper；短门面只用于保留有调用方的公开兼容；
- 最大目录深度限制在明确子域，不使用任意多层 `internal/shared/common`；
- `_vendor`、`_bootstrap.py`、一方 `src.*` 导入和旧兼容路径均不存在；
- 原始曲线/重复值/热图解析、单位规范化、系列顺序、轴范围、绘图契约和输入识别均有
  迁移回归测试；
- 原 CLI、Python 导入、数据格式和 artifact 合同由回归测试与 runtime gate 验证。

最终命令证据见同日 `DEVELOPMENT_LOG.md` 条目。synthetic smoke、
ready-rule acceptance 和静态架构检查仍不能替代授权真实数据、校准尺寸人工审阅或
连续日用证据。

项目没有配置 mypy、Pyright、Pyre 或其他独立 type-check 命令，当前环境也未安装
这些工具；因此本次没有把 `compileall` 或 Ruff 冒充为类型检查。引入并收敛新的
类型检查基线应作为独立工作，不在结构重构中临时增加大型工具或通过宽松配置制造
虚假通过。
