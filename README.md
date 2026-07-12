# SciPlot

SciPlot 是面向材料科研日常出图的本地、可复现工作流。它把原始仪器数据变成可继续编辑的
`studio/document.vsz`，由 Veusz 完成生产渲染，并交付 PDF、300 dpi TIFF、数据工作簿、
分析记录和机器可读 QA。Luna/Codex 只在确定性程序无法识别数据或表达规则时介入。

正式渲染器只有 Veusz。Matplotlib 公共回退和自研高级图形编辑器均不属于产品路线。

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

- 识别命中 fixture-backed `ready` 规则；
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

## 高级修图

需要高级修正时，打开项目内的 `Open_in_Veusz.command`，或运行：

```bash
skill/scripts/sciplot studio PROJECT/studio/document.vsz --advanced-editor
```

在完整 Veusz 中修改对象树、轴、图例、字体、标注和排版并保存。然后精确导出当前文档：

```bash
skill/scripts/sciplot studio PROJECT --export pdf,tiff_300 --json
```

这一步不会重新生成 VSZ。手工保存的 `.vsz` 是视觉权威；显式再生成前会先归档旧文档。

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
- 拉伸、流变/DMA、DSC/TGA/DTG、FTIR/UV-Vis、XRD/SAXS、GPC/SEC、
  扭矩和溶胀等 fixture-backed 生产规则；
- 同指标多样品比较、谱图堆叠、replicate 处理和事件段选择；
- Veusz `.vsz` 生成、完整 Veusz 高级编辑和 exact-current export；
- 60/120/180 mm 单图尺寸以及 183 mm 组合图布局；
- publication intent、transform ledger、研究模型和证据绑定；
- PDF 页面/字体/尺寸/可见墨迹、TIFF 分辨率、PDF-TIFF 配对和哈希 QA；
- 可携带 `delivery/`，包含图、数据工作簿、项目文件与内部审计材料；
- `intervention_request.json`、`assisted_cleanup_request.json`、
  `cleanup_result.json` 和 `revision_brief.md` 组成的可审计辅助修复链；
- 文件夹 batch、3D PA 真实数据 acceptance 和扭矩专项 curation。

未验收的 pending 规则不会自动进入绘图。新增规则默认是 pending，只有加入真实 fixture 与回归测试后
才能成为 `ready`。

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

助手必须先保存原始输入，写出可验证的 `cleanup_result.json` 或 recipe/rule 补丁，增加 fixture 和测试，
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

# 稳定脚本包与批量验收
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

## 安装与开发

```bash
make setup       # 安装开发与 Veusz Studio 所需依赖
make test
make lint
make clean       # 只清缓存，保留 outputs/ 科研交付
```

`make clean-all` 会删除 `outputs/`，只在明确不需要其中成果时使用。

代码职责：

- `src/sciplot_core/materials_rules.py`：实验族、轴/单位语义与 fixture readiness；
- `src/sciplot_core/semantic.py`：识别和预处理；
- `src/sciplot_core/studio.py`：VSZ 生命周期、Veusz 打开/导出与 Studio 交付；
- `src/sciplot_core/workflow.py`：request 编排和辅助修复闭环；
- `src/sciplot_core/qa.py`、`delivery.py`：制品 QA 与交付门禁；
- `src/sciplot_core/publication.py`、`study_model.py`：出版与证据合同；
- `src/sciplot_recipes/`：经过测试的实验族 recipe；
- `third_party/veusz/`：迁移的生产渲染器黑盒。

## 当前文档

- [Alpha 使用指南](docs/ALPHA_USER_GUIDE.md)
- [Luna / SciPlot 操作流](docs/SCIPLOT_OPERATION_FLOW_PLAN.md)
- [VSZ-first Veusz 集成路线](docs/VSZ_FIRST_VEUSZ_INTEGRATION_PLAN.md)
- [出版级科研绘图路线](docs/SCIPLOT_PUBLICATION_FIGURE_ULTIMATE_ROADMAP.md)
- [稳定 autoplot 合同](docs/STABLE_AUTOPLOT_CONTRACT.md)
- [第三方许可](docs/THIRD_PARTY_NOTICES.md)

历史 UI、Swift sidecar、WebAgg 和旧版路线文档已移除；Git 历史保留其开发记录。
