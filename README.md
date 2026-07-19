# SciPlot

SciPlot 是面向材料科研日常出图的本地工作流：读取原始数据，按确定性规则生成可编辑的
`studio/document.vsz`，在 Veusz 中完成调整，并交付 PDF、300 dpi TIFF、绘图数据、QA
和可追溯运行记录。

## 产品边界

原生 Veusz `MainWindow` 是唯一日用绘图前端，也是唯一高级编辑器。SciPlot 在同一个
Veusz `Document` 上增加两个默认隐藏、可关闭的入口：

- `SciPlot Project`：来源、映射、当前制品、QA 和交付状态；
- `SciPlot AI`：可选的当前选中对象助手。

对象树、属性编辑器、Datasets、画布、菜单、快捷键、Save 和 Undo/Redo 都沿用 Veusz。
SciPlot 不维护第二套前端、第二个文档模型、独立 Canvas、Composition Board 或 Veusz
属性编辑器的复制品。手工和 AI 修改共享同一个文档和同一个原生 Undo 历史；保存后的
`.vsz` 是视觉权威。

AI 不是日用必需依赖。没有 provider 或 API key 时，受支持输入的识别、绘图、人工编辑、
保存、QA、导出和交付仍应完整工作。

## 当前可用性

仓库的自动门可以证明无 AI 的确定性路线、Veusz 运行、制品一致性和规则生命周期是否通过。
这些机器证据支持把 SciPlot 用作日常工具，但不等于已经完成连续数周的人工日用验证。
真实使用中的操作摩擦、长任务响应和边缘数据仍需由实际项目暴露；发现问题后应修复共享
规则、样式契约或工作流，而不是增加一个替代编辑器。

## 最短路线

首次使用或交付前：

```bash
skill/scripts/sciplot doctor --json
```

要求 `status=ready`。从原始文件、文件夹或已有项目进入 Veusz：

```bash
skill/scripts/sciplot studio PATH \
  --out outputs/projects \
  --export pdf,tiff_300 \
  --json
```

已知实验规则或展示类型时，直接表达意图：

```bash
skill/scripts/sciplot studio PATH \
  --rule RULE_ID \
  --template TEMPLATE_ID \
  --out outputs/projects \
  --export pdf,tiff_300 \
  --json
```

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

高频和低频视觉调整都可以直接在 Veusz 中完成。SciPlot 不应阻止用户使用 Veusz 的完整
对象属性、Datasets、对齐和 Undo/Redo。

## 模板与全局绘图契约

生产 Veusz 文档构建器只接受六种已经完成语义验证的模板：

- `curve`
- `point_line`
- `stacked_curve`
- `box`
- `box_strip`
- `heatmap`

其它模板必须在请求边界明确失败，不能悄悄退化成曲线图。模板只描述图形语义和允许编辑的
选项，不拥有私有字体、字号、线宽、刻度、标记或普通图框边距。颜色可以承担图形语义：
特别是 `heatmap` 的标量色带、等高线和色条配色由热图模板契约独立管理，不强行套用普通
曲线配色。

全局硬样式由 `src/sciplot_core/policy.py` 统一定义，并与
`src/sciplot_core/_vendor/src/plot_contract.json` 的渲染合同保持一致。
`src/sciplot_core/style_contract.py` 对生产模板、ready 规则、figure profile、全局硬样式和
显式模板配色进行 fail-closed 审计。修改字体、线宽、刻度、标记或普通图框时，必须改全局
权威；修改热图配色时，必须改热图颜色契约。两者都要扩展契约测试，不能在 recipe 或一次性
脚本中复制常量。

## 编辑和精确导出

项目中的 `Open_in_Veusz.command` 或下面的命令会打开当前 VSZ：

```bash
skill/scripts/sciplot studio PROJECT/studio/document.vsz --advanced-editor
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
transform lineage 或完整 SciPlot 项目交付。

显式重新生成文档前必须归档人工保存的 VSZ。打开和导出项目不得静默覆盖人工修改。

## 可选 AI

AI dock 只处理当前选中的受支持对象。请求可以包含当前页的有界渲染、文档 revision、
对象类型和安全属性目录；模型只能提出受验证的 `set_setting` 操作。过期 revision、
越权目标、未知 setting、错误类型或超范围值必须整体拒绝。

AI 提案默认由用户确认，接受后形成一个 Veusz 原生 Undo 步骤。它不能修改原始科学数据、
执行任意 Python/VSZ 代码或替代全局属性编辑器。

没有 AI 配置时无需切换模式；独立工作流保持可用。

## 状态与交付

日用结果状态：

- `editing`：文档尚未产生匹配当前 revision 的交付；
- `exporting`：保存、导出、QA 或 delivery 正在执行；
- `ready`：当前 VSZ、PDF/TIFF 和交付制品一致；
- `needs_fix`：导出、QA、哈希或 delivery 失败。

来源审计状态与结果状态分开；`pending` 不能被误写成当前制品已经失效。

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
交付前应检查 `manifest.json`、`review.html`、QA、最终制品和 `delivery/`，不能只看命令
退出码。

## 确定性规则和兼容确认面

查看程序如何理解输入：

```bash
skill/scripts/sciplot inspect PATH --json
skill/scripts/sciplot rules list --json
skill/scripts/sciplot rules show RULE_ID --json
```

稳定结果是 `ready`、`needs_human_confirmation` 或 `needs_rule_repair`。后两者应修复科学
确认或共享规则，不应生成占位数据。

只有明确需要浏览器确认样品分组、图例名称、顺序、尺寸或导出格式时才使用：

```bash
skill/scripts/sciplot app --out outputs/intake_projects
```

浏览器是数据确认兼容面，不是绘图前端；高级编辑仍在 Veusz 中完成。

## 工程验证

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

完整规则矩阵应为所有 ready 规则通过，并逐项检查证据层级。runtime smoke 使用明确标记的
synthetic contract fixture，不是真实数据证据；生命周期通过也不等于通用期刊合规或人工
连续日用验证。

发布 wheel 前先删除本地 `build/` 和 `*.egg-info/` 缓存再构建，并检查 wheel 中没有已经
退役的前端或证据模块。安装态验证必须禁用源码 `PYTHONPATH`；“源码可导入”不能替代
“安装包可运行”。

## 安装与代码入口

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[studio,dev]'
skill/scripts/sciplot doctor --json
```

主要职责：

- `materials_rules.py`、`semantic.py`：实验族、轴、单位和确定性准备；
- `policy.py`、`style_contract.py`：全局绘图样式与模板一致性；
- `studio.py`：项目、VSZ 生命周期和 exact-current 导出；
- `studio_project.py`、`studio_project_status.py`：Veusz Project dock 与状态；
- `studio_assistant.py`、`assistant_*`：可选的 selected-object AI；
- `qa.py`、`delivery.py`：制品 QA 与最小交付；
- `third_party/veusz/`：固定版本的上游渲染器和日用编辑器；
- `_vendor/`：迁移兼容黑盒，默认最后才修改。

产品方向、模块边界和当前维护队列见
[DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)，第三方许可见
[THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)。
