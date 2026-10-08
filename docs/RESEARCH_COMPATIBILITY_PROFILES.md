# 真实科研图 compatibility profiles：mechanical + rheology

本阶段日期：2026-10-08。已完成两个 family、三个历史图的固定 golden-master 回归：机械拉伸强度分类柱形图，以及 PP 频率扫描 G′、G″。历史交付、legacy production 重放和 ManagedPlot 分别接受同一固定基准检查。本轮没有改变核心架构、house contract 或科学算法；只修复重现这些历史图所必需的有限表达与绑定问题。

本报告证明所列真实图在锁定的本地渲染环境下的兼容性。它不是全部机械/流变图、跨平台字体或任意 native 功能的兼容保证。“历史交付”有原文件和交付记录支持；机械图未找到独立的用户审美认可或发表记录，不把交付事实升级为这类结论。

完整文件入口：[本轮证据索引](../.tmp_verify/family_compatibility_20261008/delivery-index.md)、[机械索引](../.tmp_verify/family_compatibility_20261008/mechanical/delivery-index.md)、[流变索引](../.tmp_verify/family_compatibility_20261008/rheology/delivery-index.md)。证据及新导出均在 ignored `.tmp_verify/`；原始 OneDrive 研究文件没有改写。固定 fixtures 是本地回归材料，本轮未提交或发布研究数据。

## 结果与验收边界

| 固定 profile | 数据 | 有效结构叶节点 / 每条路径 | Managed 原始像素差 | 结果 |
| --- | --- | ---: | ---: | --- |
| mechanical-v1 | E0/E2/E3/E4，每组 n=5 | 766 | 439；最大通道差 6/255 | 结构一致，差异符合原有抗锯齿容差；不是逐像素完全相同 |
| rheology-gp-historical-20260918 | PP 3155、PP-5UDC，各 16 点 | 501 | 0 | 有效结构与像素一致 |
| rheology-gpp-historical-20260918 | PP 3155、PP-5UDC，各 16 点 | 482 | 0 | 有效结构与像素一致 |

三幅图均为 60 × 55 mm，均检查真实 PDF 页尺寸和 300 dpi TIFF 的尺寸/DPI，并通过删除 backend artifacts 后的全量重建。三幅历史 TIFF 与当前直接打开各自历史 VSZ 的 TIFF **逐像素一致**，因此固定 golden 的首次本机捕获有历史栅格锚点。

原有 FTIR 与已认可 NMR 又使用当前编译器重新创建：分别检查 340、250 个结构叶节点，结构差和原始像素差均为 0。见 [既有谱图结果](../.tmp_verify/family_compatibility_20261008/existing-spectroscopy-results.json)。其历史源和 golden 未改写。

## 固定基准如何防止共同漂移

1. 保存真实历史 VSZ/PDF/TIFF、原始数据、科学 owner 输出、原始配置和历史修改证据；逐文件 SHA-256 固定在 profile manifest。
2. Golden PNG、结构和环境从历史 VSZ 捕获一次；不从当前 legacy 或 Managed 生成结果建立基准。
3. 每次原生回归首先重新打开固定历史 VSZ，检查 golden、渲染环境和像素。此检查通过后，才运行两个新生成路径。
4. legacy production 使用原有生产编译器和历史配置；Managed 使用明确绑定同一数据的 FigureTemplate request。三条路径均对比固定 golden，避免“两条新路径一起变样，彼此仍相等”。
5. 输出完整 native inventory、datasets、绘制几何、实际文本边界、有效结构差和 old/new/diff PNG。关闭的 native 通道保留完整记录，但不冒充当前可见图形。
6. 删除 Managed backend/IR 缓存后，由保存的 document、source 和状态重新生成，核对完整 PlotIR、科学 identity、native state、PNG 与 export。

比较器不平移、缩放、裁切、重采样或配准输入。`diff.png` 只是差异可视化，不作为验收输入。结构浮点绝对容差沿用 `1e-9`；栅格沿用既有 channel noise 8、前景差异比例及 ink-mass 门槛，没有为本轮放宽。空白图、尺寸变化、字段缺失、环境变化均不能自动通过。

## Mechanical profile

历史来源是 OneDrive `1 PhD/2 PA ADR Recycle/新料 1.14/plot/Tensile_2mm` 中的 `tensile_strength_by_sample.vsz` 及配套 PDF/TIFF。三件文件的 SHA 与 2026-07-24 历史 delivery receipt 完全相符。完整原路径、快照身份和记录保留在 [manifest](../tests/fixtures/rendering_profiles/mechanical-v1/manifest.json) 与 source audit。

| 核对项 | 固定历史行为 |
| --- | --- |
| 分组与统计 | E0/E2/E3/E4，各 5 个原始重复值；mean ± sample SD |
| 数据 | E0 34.078 ± 1.2417205804849973；E2 35.538 ± 0.6279888534042614；E3 35.484 ± 0.8302891062756409；E4 38.616 ± 0.7982042345164566 MPa |
| 柱形 | 原 category colors；宽度 0.32 data unit；左、右、上边框，无独立基线边框 |
| 误差线 | 原位置/线宽；cap 0.16 data unit，按固定物理轴宽换算为 4.705511811023623 pt |
| 坐标与标签 | 原类别顺序、轴域、ticks、字体、文本边界、页尺寸与 margins |
| individual points | 原图没有可见散点；n=5 原数据保留并审核，不能添加新的点层来伪造历史覆盖 |
| legend | 原图无图例；回归明确检查其缺席，未声称覆盖 mechanical visible-legend 样式 |
| export | 原生 PDF 和 300 dpi TIFF；真实页尺寸及栅格尺寸均检查 |

既有科学 owner 已完成原始 workbook → replicate/summary。此次只逐值投影既有结果，没有另写统计实现，也未把配置中另一种 box 摘要字段误当作柱形 errorbar 的统计含义。部分当前 workbook 字节已不同于历史快照；profile 固定历史原始快照，不拿新的同名文件替换历史科学 identity。每个 Managed summary source 同时保留原始重复值及明确缺失的 summary 行，缺失值不是新增观测。

独立 [抗锯齿分析](../.tmp_verify/family_compatibility_20261008/mechanical/aa-explanation.json) 使用实际 native painted primitives：旧 stacked bar 对四个填充矩形分别叠绘 4/3/2/1 次，新路径各绘制一次。766 个有效结构叶节点一致，最大浮点差 `7.105427357601002e-15`。439 个差异像素全部距填充边界不超过 0.457 px，分布为 E0=131、E2=156、E3=152、E4=0；最后一组没有重复叠绘，也没有像素差。差异的最大通道幅度是 6，未达原有噪声门槛 8。

这保留了真实差异，不把结果描述为精确像素复制，也不增加旧渲染器的重复绘制来迎合 golden。原始 primitive 与完整设置均可追查；semantic projection 将重叠后的最终四个柱面与 24 个独立边线/误差线比较，不要求两个后端采用同一种 widget 分解。

Managed 科学 hash：`2acc531136a209c094c7ae8121cf387beb80fe2ff1cf31992a57467b375b4712`。PlotIR hash：`e47eda852a22ab6f0f6a011f8eb5839d575d53febc12ab68e3c28f9312afdaae`。

公有 `plot.create` 和删除后 `plot.export` 均已运行，详见 [公有重建证据](../.tmp_verify/family_compatibility_20261008/mechanical/public-rebuild.json)。该次 canonical state 已原字节归档至证据目录，不把归档路径宣称为已迁移的活跃项目。

[独立 resolved-style-provenance](../.tmp_verify/family_compatibility_20261008/mechanical/resolved-style-provenance.json) 核对 88 项实际 resolved 值全部通过，另检查 1 项高度约束与 3 项算法 binding。不可见 panel-label 的保存状态单列，不计作可见图形覆盖。

## Rheology profile

历史来源是 OneDrive `1 PhD/4 UDC/pp3155 udc/FS_SciPlot_修正_20260918`，分别固定 `project/studio_004.vsz`（G′）和 `project/loss_modulus_vs_frequency.vsz`（G″）。[fixture 说明](../tests/fixtures/rendering_profiles/rheology-v1/README.md) 包含完整来源链、原数据和运行方法。

两个 profile 都使用实际 PP 3155 与 PP-5UDC 频率扫描，直接核对原始 UTF-16 CSV 的 16 个 ω/G′ 或 ω/G″ 数据点；顺序、数值、单位不变。覆盖 log axis、主/次 log ticks、G 的斜体与 prime、marker identity、palette、线宽、图例成员及几何、物理 layout 和 PDF/TIFF export。

实际交付采用 **PP 3155 黑色、PP-5UDC 蓝色**。历史 companion spec 没同步后来的 native 配色修改。本轮找到对应 preview/outcome 记录，恰好包含两个样本各三项颜色修改，且 outcome VSZ SHA 等于交付件。legacy 重放因此采用原 spec 加这六项已证明的历史 delta；并非看到新结果后改写旧标准。配色保留为 profile explicit override，不进入全局 house default。

每张图有两处原始文本编码差：历史 `\omega (rad s⁻¹)` 与 Managed `ω (rad s⁻¹)`。测试只对 manifest 点名的轴标签/painted-text 路径进行内存中的精确 token 等价比较，并固定 Veusz symbol table 的源文件 hash。该规则要求实际像素差为 **0**，即使仅 1/255 的差异也不能借一般抗锯齿容差通过；其他字符串、单位、路径或 renderer 版本不适用。原始结构和 raw diff 完整保留，golden 文件不改写。

此外，每张图的完整通道记录有六项隐藏 grid/border 宽度差（历史 inherited 1.2 pt，当前 0.5 pt）。这与前阶段已披露的隐藏 native 通道边界一致。当前可见图形一致，不保证人工开启这些隐藏设置后的效果相同。不能宣称 full native state 与历史文件逐字段或逐字节相等。

| Profile | scientific hash | PlotIR hash |
| --- | --- | --- |
| G′ | `4ebb610534060b826423374334250b780a1e404791773feb85d5db8a9a64be70` | `1c65caa5ccaf54c57e146e937dfd246d217f0f4890bc112ab1a0f453e0d7802f` |
| G″ | `625d9ab32558a7484bc40e6d31fc061ccecf1970ee1376f792d4049fa26e919c` | `8a01f32cbd20331642064058b8a30ca8ed951f90a3eb21f5780076796fef33cb` |

两张图共核对 138 个 resolved style provenance 值，均与实际 resolved 字段一致。历史包中 G′/G″/tanδ 是独立图；没有找到可作为此轮基准的已交付双轴图，因此没有制造新的双轴 golden，也没有把前阶段 synthetic/grammar dual-Y 能力当成历史兼容验收。

## 有限修复与模块边界

| 模块 | 本轮变化及原因 |
| --- | --- |
| `plot_grammar/schema.py`, `validation.py`, `styles.py`, `house.py`, `compiler.py`, `ir.py` | 允许并严格验证显式 category tick labels、语义 italic label runs、无基线的三边 bar override；保留每项来源。未设新的 house 默认或添加 mark family |
| `plot_backends/house_guides.py`, `figure_plan.py`, `figure_marks.py` | 将上述已解析语义映射到原生轴标签/文本/三条独立边线；backend 不重新解释科学统计 |
| `plot_engine/managed_sources.py`, `data_mapping/table_choice.py` | 已显式绑定的机械表通过现有 `source_table_snapshot` 读取，保留真实 `tensile_curve` rule；不再被 ordinary discovery 的曲线资格筛选错误拦截；source/hash/metadata/单位/行选择 guard 保留 |
| `tests/rendering_profiles_helpers.py`, `rendering_profiles_native.py` | 固定 manifest、独立历史门槛、三路结构/像素/环境比较；无 update-golden 模式 |
| `tests/rendering_profile_mechanical*.py`, `rheology_profile_helpers.py` | 各 family 自己的科学映射、历史 override、native 角色和重建验收 |
| `verification/plot_owners.py` | 登记新增测试、helper 和 fixture 所属 owner，避免 changed-owner 门槛遗漏 |

显式 override 有作用域；未定义的旧 house 规则仍保留 unspecified/adapter baseline 来源。本轮没有改变 RenderingStyleContract 资源、`OLD_RENDERING_CONTRACT.md`、架构文档、既有科学 owner 或添加另一套 CLI 实现。开始/结束文件 identity 审计见证据索引。

## 渲染环境、回归与验证

每个 snapshot 记录 Python 版本/二进制 SHA、平台、相关 package 版本、Qt 编译/运行版本与模块 hash、Veusz Python 源 hash、Arial 字体文件 hash、实际 resolved font family、150 dpi preview / 300 dpi TIFF / PDF 配置。producer identity 单列，便于追查捕获工具变化。环境变化会失败，需要审查原因，不能通过重画 golden 自动消除失败。

固定 fixtures 下包含运行所需原始文件，不依赖 OneDrive 在线同步。原生回归测试是 comprehensive 层；默认 `verify --changed` 的纯测试结果不能代替它。

```bash
.venv/bin/python -m pytest tests/test_mechanical_rendering_profile_native.py tests/test_rheology_family_profiles_native.py -m comprehensive -q
```

本轮最后一次统一 native 检查额外包括现有 house、Figure backend 与 Managed CLI/MCP：**12 passed，2 deselected**。FTIR/NMR 的真实历史回放另有独立证据。精确命令、changed-owner / 静态类型 / Doctor / smoke 结果汇总于 [验证索引](../.tmp_verify/family_compatibility_20261008/delivery-index.md)，原始日志保留。

最终 changed-owner 检查为 **1,896 passed / 128 deselected**，Ruff、配置范围内严格 mypy（306 个文件）及 whitespace 均通过。Doctor 为 ready；本阶段最终一次 runtime smoke 为 **36/36 passed**。Smoke 使用合成 fixture，只证明运行链路；真实科研兼容性由上述独立历史 profiles 证明。

## 尚未覆盖

- 机械可见 individual-point overlay、可见 legend、grouped bar；所选历史图没有这些可见状态。没有为了覆盖列表而改造历史图。
- 历史 G′/G″/tanδ 双轴 golden；本阶段没有可核验的交付实例。
- 隐藏 native 通道开启后的行为、任意字体/平台版本、所有旧 native 特性或所有科研 family。
- TTS/master curve、relaxation spectrum、DSC 等后续 profile 未在本轮扩展。

当前可执行保证是：这些固定历史科研图有独立的旧图基准、科学数据 identity、native 结构、真实栅格和环境门槛；以后功能增加或重构可以重跑它们，发现未经授权的变化，而不是靠肉眼判断“差不多”。本阶段到 mechanical + rheology 为止。
