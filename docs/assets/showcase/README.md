# SciPlot 展示图与可复现来源

本目录的四张图全部使用**明确标注的合成演示数据**，通过 SciPlot 的原生 Veusz 渲染生成 PDF，再以 Poppler 转为 300 dpi PNG。它们展示图形表达与数据合同，不代表真实材料性能、实验发现或期刊合规认证。图例中的 `This work`、`Reference materials` 是模板的角色标题；`Demo`、`Ref` 都是演示样本，没有真实论文引用。

运行版本：`2da1aa905f6459b2d86fcb1453bd676536c882f1`，生成日期：2026-09-07。命令在仓库根目录执行。原生 PDF、VSZ、QA 和运行回执保存在忽略目录 `.tmp_verify/github_showcase/`，不作为网页资源提交。

| 图片 | 合成数据来源 | 展示范围 | PNG 尺寸 |
| --- | --- | --- | --- |
| [UV-vis 多曲线](uvvis-curves.png) | [uvvis-demo.csv](data/curves/uvvis-demo.csv) | 四条曲线，各 501 个点，250–750 nm | 709 × 650 |
| [重复分布](replicate-distribution.png) | [replicate-demo.csv](data/replicate-demo.csv) | 两组各三次观测，保留六个原始点、median/IQR 与须线 | 709 × 650 |
| [性能散点](performance-scatter.png) | [material-performance-demo.csv](data/material-performance-demo.csv) | 六个演示样本，密度与比冲击强度 | 1417 × 650 |
| [性能雷达](performance-radar.png) | [material-performance-radar-demo.csv](data/material-performance-radar-demo.csv) | 同六个样本的三个指标：密度、比冲击强度、断裂伸长率 | 1417 × 650 |

## 数据怎样得到

UV-vis 曲线是确定性的数学演示。波长 `λ = 250, 251, …, 750 nm`，每条曲线计算

```text
y = 0.04 + A × exp(-0.5 × ((λ - c) / s)²)
         + 0.20 × exp(-0.5 × ((λ - 305) / 22)²)
```

四组 `(c, A, s)` 分别为 `(430, 0.95, 38)`、`(465, 1.18, 43)`、`(505, 1.38, 47)`、`(550, 1.13, 51)`，CSV 数值保留六位小数。图中峰形仅用于展示多曲线绘制，不对应任何化合物或吸收机理。

重复分布的数值来自受版本控制的 [synthetic semantic smoke 生成器](../../../src/sciplot_core/smoke/semantic_parser.py) 中 `impact_metric` 的 `2 mm` 条件：第一组为 `1.0, 1.2, 1.4`，第二组为 `2.0, 2.2, 2.4 kJ m⁻²`。演示 CSV 将组名改为 `Demo A/B`，保留数值与单位，以三行表头记录指标、单位和组名。此图只展示这个条件，不包含 smoke 的 `4 mm` 条件；三次重复不足以支持材料优劣推断。

性能数据来自受版本控制的 [material_performance_long.csv](../../../tests/fixtures/performance_comparison/material_performance_long.csv)。`Own A/B/C` 改为 `Demo A/B/C`，`PA6/ABS/CFRP` 改为 `Ref A/B/C`，清空了原 fixture 的占位 `Journal/Year/DOI`，并更改演示分组文字。保留原始 `Value`、`Unit`、`Role`、`Direction`、`ScaleMin`、`ScaleMax`、`ScatterAxis`、`RadarOrder` 与 `MaterialOrder`。

散点源保留全部 24 条记录，图形使用源中明确指定的两个 `ScatterAxis` 指标。雷达源明确选取其中 18 条记录，只含 `density`、`specific_impact_strength`、`elongation_at_break`，未包含拉伸强度。雷达标签 `Impact` 指比冲击强度，`Elongation` 指断裂伸长率；每个轴标明源单位。雷达半径按源中给定的方向和范围映射：密度 `0.8–1.6 g cm⁻³` 越低越向外，其余两个指标均为 `0–120`、越高越向外。不同单位不能直接相加，围成面积不作为综合性能指标。

## 生成命令

先确认运行环境，再在新的输出目录复现。下面的 JSON 请求只保存创建任务所需的公开字段，不配置内部模型。

```bash
skill/scripts/sciplot doctor --json
mkdir -p .tmp_verify/github_showcase/reproduce/.sciplot/tasks \
  .tmp_verify/github_showcase/reproduce/tasks

skill/scripts/sciplot task start --request docs/assets/showcase/requests/uvvis.json \
  --task-dir .tmp_verify/github_showcase/reproduce/tasks/uvvis --json

skill/scripts/sciplot task start --request docs/assets/showcase/requests/scatter.json \
  --task-dir .tmp_verify/github_showcase/reproduce/tasks/scatter --json

skill/scripts/sciplot task start --request docs/assets/showcase/requests/radar.json \
  --task-dir .tmp_verify/github_showcase/reproduce/tasks/radar --json

skill/scripts/sciplot render docs/assets/showcase/data/replicate-demo.csv \
  --auto --template box_strip \
  --options '{"size":"60x55","y_label_override":"Impact strength (kJ m⁻²)","summary_statistic":"median_iqr"}' \
  --out .tmp_verify/github_showcase/reproduce/replicates
```

前三项请求分别选择 `uvvis_spectrum`、`performance_comparison/scatter`、`performance_comparison/polar_curve`；重复分布使用公开开发渲染命令。当前版本在首次创建任务前需要先建立上述父目录。任务返回的 `project` 可用 `project inspect PROJECT --json` 检查当前 source、QA 与 delivery。每次完整重建需要新的任务和输出目录；已创建的项目按返回路径继续查看。

将各任务回执中对应的 PDF 转为 PNG，保持完整页面，不裁切或重绘图形：

```bash
pdftoppm -png -r 300 -singlefile INPUT_PDF OUTPUT_PREFIX
```

发布的 PNG 对应本次实际原生 PDF 栅格化结果。重建的 PDF 元数据与 PNG 字节可能随依赖版本变化；源 CSV 是这里的数值基准。原始执行回执位于 `.tmp_verify/github_showcase/root_uvvis/`、`scatter_task_result.json`、`radar_units_task_result.json` 与 `replicate_demo_wide_render.json`。

## 校验

[SHA256SUMS](SHA256SUMS) 记录四张 PNG、四份 CSV 和三份请求 JSON 的 SHA-256。可在本目录执行 `shasum -a 256 -c SHA256SUMS`。这些 hash 识别本次发布文件，不承诺不同平台导出时字节相同。

本次验证包括：四幅最终 PNG 逐图目视；性能 demo 与原 fixture 的值、单位、角色、方向和边界逐项一致；重复分布的六个原始点完整保留；UV-vis、散点、雷达项目的 source、QA、delivery 均为 current；重复分布渲染 QA 无 issues。为获得受控 smoke 数据执行的 runtime smoke 为 36/36 通过。以上证据不扩大为真实数据验证或期刊合规声明。
