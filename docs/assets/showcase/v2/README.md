# 八种图形，一套可复现的合成数据展示

本版用于 SciPlot 的 GitHub 首页。八张图全部由 **SciPlot / Veusz 原生渲染**生成 PDF，
再以 Poppler 将完整页面转为 300 dpi PNG。每张图保留对应 CSV、公开选项或任务请求及生成记录。
所有数据均为合成演示，不代表真实实验、材料性能或拟合结论。

普通分组图统一为 **五组样品，60 × 55 mm**，保留曲线的完整数据点。
连续响应场保留完整网格；两张性能比较采用 **120 × 55 mm**。
图幅指完整导出页面，PNG 分别为 709 × 650 与 1417 × 650 px。

| 图形 | 数据规模 | 源 CSV | 选项与复现记录 |
| --- | --- | --- | --- |
| [多样品光谱](spectra/spectra-rich.png) | 5 × 601 点 | [CSV](spectra/spectra-rich.csv) | [选项](spectra/options.json) · [manifest](spectra/manifest.json) |
| [堆叠光谱](curves/stacked-spectra.png) | 5 × 600 点 | [CSV](curves/stacked-spectra.csv) | [选项](curves/stacked-spectra.options.json) · [manifest](curves/manifest.json) |
| [流变点线](curves/rheology-point-lines.png) | 5 × 30 点 | [CSV](curves/rheology-point-lines.csv) | [选项](curves/rheology-point-lines.options.json) · [manifest](curves/manifest.json) |
| [重复分布](distributions/replicate-distributions.png) | 5 × 25 个观测值 | [CSV](distributions/data/synthetic-replicate-distributions.csv) | [选项](distributions/requests/replicate-distributions.json) · [manifest](distributions/manifest.json) |
| [组成柱图](distributions/composition-bars.png) | 5 配方 × 4 组分 | [CSV](distributions/data/synthetic-composition-bars.csv) | [选项](distributions/requests/composition-bars.json) · [manifest](distributions/manifest.json) |
| [连续响应场](distributions/response-heatmap.png) | 61 × 41 网格 | [CSV](distributions/data/synthetic-response-heatmap.csv) | [选项](distributions/requests/response-heatmap.json) · [manifest](distributions/manifest.json) |
| [性能散点](performance/performance-scatter-rich.png) | 4 组、16 样品、16 点形 | [CSV](performance/performance-scatter-rich.csv) | [任务请求](performance/scatter.request.json) · [manifest](performance/manifest.json) |
| [多指标雷达](performance/performance-radar-rich.png) | 6 样品 × 5 指标 | [CSV](performance/performance-radar-rich.csv) | [任务请求](performance/radar.request.json) · [manifest](performance/manifest.json) |

## 数据与表达

光谱使用确定性多峰函数；公式与参数记录在对应 manifest。堆叠光谱有明确的纵向显示偏移，
CSV 保留未偏移数值；其峰形没有化学指认。流变点线为合成频率响应，使用双对数坐标。
CSV 中的样品元数据、单位及完整坐标参与原生渲染，未通过稀疏采样减少曲线点数。

分布、组成与响应场的公式、随机种子、数据生成脚本和组分缩写见[专门说明](distributions/README.md)。
箱线图展示中位数与 IQR，并叠加全部观测点。组成图每个配方合计 100%，四个组分不是统计重复。
热图颜色表示合成响应值；61 × 41 指连续场网格，不是样品组数。

性能散点保留四个彩色分组和每个样品的独立身份，包络表示组内点范围，不是置信区间。
源表有 48 条指标记录：每个样品的密度与冲击强度用于绘图，伸长率作为辅助元数据保留。
雷达源表有 30 条记录，五个指标为密度、冲击强度、拉伸强度、断裂伸长率和恢复率。
各轴按源表中的单位、方向和边界归一化；多边形面积不解释为综合分数。

## 复现与校验

运行日期为 2026-09-07，使用的实现版本为 `d6791809a06141188d3797b561f05e31b2126711`。
从仓库根目录先执行：

```bash
skill/scripts/sciplot doctor --json
```

确认 `status=ready` 后，按各 manifest 的命令运行。普通示例走公开 `render` 开发渲染入口，
性能图走公开 `task start` 和 `performance_comparison` 规则；它们不意味着任意输入都能由任务层自动识别。
全新复现应使用新的输出及任务目录，性能任务的父目录准备命令见其 manifest。
运行回执、原生 PDF / VSZ 与 QA 保留在忽略目录 `.tmp_verify/github_showcase_v2/`，不作为网页资源提交。

从原生 PDF 导出网页图，保持整页：

```bash
pdftoppm -png -r 300 -singlefile INPUT_PDF OUTPUT_PREFIX
```

已核验全部源数据与原生图规格、样品数、图幅、单位及 PNG 标签布局。
八图最终原生 QA 无 issues，性能受管项目的 source、QA、delivery 均为 current。
这些检查用于本组合成示例，不替代真实实验验证。

[SHA256SUMS](SHA256SUMS) 记录本版文件摘要。在本目录执行：

```bash
shasum -a 256 -c SHA256SUMS
```

摘要标识本次发布文件；不同平台或依赖版本重新导出时，PDF 元数据及 PNG 字节可能不同。

## 首页封面

[封面 PNG](../../sciplot-banner.png) 由[可编辑 SVG](../../sciplot-banner.svg)导出。
封面嵌入本版光谱、分布和散点图的完整 PNG 页面，仅作整体排版与旋转，不重画数据。
复现构图使用 [build_banner.py](../../build_banner.py)：

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python docs/assets/build_banner.py
```

[第一版四图](../README.md)仍保留，便于追溯此前展示。
