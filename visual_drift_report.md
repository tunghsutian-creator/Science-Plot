# SciPlot Figure Grammar v2 视觉漂移审计

本报告区分三件事：旧程序规定的视觉值、旧 native runtime 的继承行为，以及 Figure Grammar v2 引入的布局/绘制行为。它们不能互相替代。科学映射正确、VSZ native audit 通过或删除产物后自重建一致，都不足以证明新旧视觉相同。

**验收结论：已恢复本轮覆盖的单 panel 旧视觉规范。** 新建 FigureTemplate v2 ManagedPlot 默认绑定旧 house contract；五组真实数据的新旧渲染比较通过，1,889 个有效结构属性零差异，五张原生 PNG 均逐像素一致。此结论限定于下述单图线/点/光谱 profile，不代表任意旧 native 功能或所有科学 family 已完成迁移。完整 native inventory 还存在明确列出的隐藏属性差异。证据位于 [完整交付索引](.tmp_verify/visual_contract_20261008/delivery-index.md)，可直接打开五组最终 VSZ/PDF/TIFF、旧图/新图/差分图和逐属性来源。

## 比较依据与版本界线

旧标准来自 `policy/plot_contract.json`、`policy/frame_export.py`、`policy/visual_identity.py`、旧 Studio renderer 的显式设置和随项目固定的 Veusz 源码。详细枚举见 [OLD_RENDERING_CONTRACT.md](OLD_RENDERING_CONTRACT.md)。机器提取资源为 [sciplot-house-style-v1.json](src/sciplot_core/rendering_contract/styles/sciplot-house-style-v1.json)。每项记录 `value/status/source_file/source_symbol/notes`。

旧程序没有明确规定的值仍为 `unspecified`。若为保留现有 mark 能力而固定旧 renderer 的继承行为，单独标记 `adapter_baseline`，不将其写成旧 house 规则。例如 native 字体默认字重、legend 黑色、polygon 填充、普通 label 对齐，以及非 categorical errorbar 的物理端帽基线。

新创建的 FigureTemplate v2 ManagedPlot 在 document 的 presentation 域绑定 contract ID 与内容哈希。已有未绑定 contract 的历史 FigureSpec v2 保留原来的解释，不在读取、重建或 theme 修改时偷偷改样式。LegacyPlot 的现存 VSZ 继续为权威。已有 v1 ManagedPlot 与任意历史用户手工改图不是本报告默认迁移或普遍等价的对象。

## 已定位漂移与修复位置

表中“此前 Grammar”指本阶段开始时的 `plot_grammar/styles.py` 及物理布局/guide 实现。它不是旧程序标准。

| 属性 | 旧程序 / 旧 native | 此前 Grammar v2 | 来源 | 本轮修复与边界 |
| --- | --- | --- | --- | --- |
| 单图画布 | 60 × 55 mm；另有命名尺寸 | 必须显式给 layout；样例 90 mm / auto，真实多面板另定尺寸 | `plot_contract.json:global_frame/size_presets` | 新 bound 单图省略尺寸时取封存 contract；显式用户尺寸保留并记来源 |
| 左/右/上/下边距 | 14 / 4.5 / 5.5 / 11 mm | 从文本估算动态累加，基础 2 mm | `frame_export.py:UNIFIED_*_MARGIN_MM` | 新 bound 视图使用固定内边距；空间不足应失败，不暗中改变字体或边距 |
| 默认单图 plot rect | x=14、y=5.5、w=41.5、h=38.5 mm | 受字体、标签长度、估算策略影响 | 上述尺寸与边距的差值 | 结构比较已逐项检查；A–D 为相同固定矩形，E 为显式 120 mm 宽的对应矩形 |
| 常规字体 | Arial 7 pt | Arial 8 pt | `UNIFIED_FONT_FAMILY/UNIFIED_FONT_SIZE_PT` | contract → Theme → figure/view/layer/mark override，并附逐字段来源 |
| legend 字号 | 6 pt | 8 pt | `UNIFIED_LEGEND_FONT_SIZE_PT` | contract 默认 6 pt；显式 override 单独记录 |
| panel label | 7 pt、bold | 普通 annotation 的 8 pt、普通字重 | `UNIFIED_PANEL_LABEL_SIZE_PT`；`styles.nature.typography.panel_label_weight` | 独立使用 panel-label 规定及完整 property 来源；Theme 明确覆盖仍优先 |
| 普通曲线宽度 | 1.2 pt | 0.7 pt | `UNIFIED_LINE_WIDTH_PT` | 从封存 contract 解析 |
| 曲线透明度 | alpha 0.92，native transparency=8 | 未表示，native 默认不透明 | `styles.nature.stroke.line_alpha`；`veusz_primitives._add_veusz_xy_series` | IR 表示 `line_opacity`，backend 显式映射 |
| 曲线连接 | 旧 native bevel | round | `veusz_line_joins.ensure_veusz_line_joins` | 单独 adapter baseline 固定 bevel；显式 round override 保留 |
| marker 尺寸 / 描边 | 2 pt / 0.8 pt | 3 pt / 0.5 pt | `UNIFIED_MARKER_SIZE_PT/UNIFIED_MARKER_LINE_WIDTH_PT` | contract 解析 |
| marker 透明度 / 采样 | alpha 0.95；每个测量点 | 无 alpha；未显式规范 thinfactor | `styles.nature.stroke.marker_alpha`；`series_request._marker_thin_factor` | IR 表示 0.95 与 thinfactor=1，保留全部数据 |
| point-line marker 顺序 | circle / square / diamond / triangle | 所有 series 默认 circle | `studio_render.models.POINT_LINE_MARKERS` | 按语义 layer 顺序分配；绘制 z_order 不应改变颜色和 marker 身份 |
| 类别颜色顺序 | #222222、#3568C0、#C83E4D、#2A9D8F、#D99A24、#7C9ED9、#7B61A8 | 线/点均默认 #000000 | `control_first_bright.categorical` | 按封存 palette 与 layer 顺序解析；显式颜色优先 |
| 轴线 / major tick | 宽 0.8 pt；major 长 2.8 pt | 宽 0.7 pt；major 长 3 pt | `UNIFIED_AXIS_LINEWIDTH_PT/UNIFIED_TICK_*` | 各物理通道在 IR 中明确表示 |
| minor tick | 宽 0.8 pt、长 1.5 pt；旧 native 可见 | backend 固定隐藏 | `UNIFIED_MINOR_TICK_*`；Veusz `MinorTick` | IR 表示可见性、尺寸、manual ticks 和数量；log 与 linear 分开解析 |
| linear / log minor 数量 | linear 20；log 5及 [2,4,6,8] 倍数 | 未完整表示 | `veusz_axis_apply`；`DEFAULT_LOG_MINOR_*` | 需要保留 scale 语义与显式 style override，来源与最终值一致 |
| 轴/label 颜色 | #111111 | #000000 | `UNIFIED_FOREGROUND_COLOR` | contract 显式颜色 |
| major/minor tick 颜色 | 继承 native foreground #000000 | 绑定轴 style.color | 旧 native `Line → StyleSheet/Line/color → Colors.foreground` | adapter baseline 单独表示 tick_color，不能合并成轴颜色 |
| axis label padding | 2 pt | 根据估算位置放独立 page text | `styles.nature.spacing.axes_labelpad` | 使用明确物理 padding 与旧 native metric flow；后置 native text bounds QA |
| tick-label padding | x/y 均 1.4 pt | 独立 page text 的估算锚点 | `styles.nature.spacing.xtick_major_pad/ytick_major_pad` | 同上；不是调几毫米去近似旧外观 |
| grid | major/minor 均隐藏 | 只部分显式设置 | Veusz `GridLine/MinorGridLine` | inherited baseline 明确进入 resolved style |
| legend key 长度 | 4 mm | symbol slot 约 6 mm，额外文本间隙 | `UNIFIED_LEGEND_KEY_LENGTH_MM`；旧 key setup | 对 line/point view guide 使用相同 native key metric flow，membership 与顺序由 IR 指定 |
| legend margin / frame | marginSize=0.15；无背景框/边框 | 自定义空间预算；未完整表示 frame | `veusz_graph_setup._add_native_veusz_key` | IR 显式表示；复杂/共享 guide 应保持独立 composition 策略，不能谎称旧 key 等价 |
| legend 字色 | inherited #000000 | #000000 | native `Colors.foreground` | 数值原本相同，现增加准确 adapter provenance，不归入轴 foreground |
| categorical bar | opaque 浅色填充；0.7 pt 浅色 keyline | 固定 #4477aa 填充、黑边 | `policy/categorical.py:CATEGORICAL_*` | 按旧 categorical palette 映射；不把全局 `fill_alpha=0.34`误当成旧 native bar 的实际值 |
| band | 没有统一旧科学 band 规则 | opacity 0.25、固定蓝填充 | 旧 house 为 unspecified；Veusz polygon 有默认 | 新默认只能称已绑定 adapter baseline；显式 band 风格优先，不能声称旧 band 全等 |
| errorbar 端帽 | categorical 按 bar/data width 比例；无通用 pt 值 | 通用 4 pt | `CATEGORICAL_ERROR_CAP_TO_BAR_RATIO` | categorical 回归要显式换算真实 cap；4 pt 仅独立 native XY baseline，不冒充旧 categorical 规范 |
| 页面背景 | white | #ffffff | `create_veusz_page_and_graph` | 数值等价；改为从 contract 源读取并规范颜色表达 |
| PDF / TIFF | PDF；TIFF 300 dpi；native PDF pdfdpi=72 | 自有 export 路径 | `DEFAULT_EXPORT_FORMATS_POLICY`；`export_execution` | 必须比较实际 native 导出参数；policy 的 Matplotlib fonttype=42 不能证明 Veusz PDF 嵌字 |
| TIFF compression / 通用 title / 通用 annotation anchor | unspecified 或每图显式定义 | 部分 grammar 默认 | 旧源未规定通用值 | 不建立不存在的旧保证；保留具体图的显式语义与 native 比较 |

## 来源追踪的要求

对当前验收图，最终 PlotIR 的 `style_provenance` 应覆盖实际使用的视觉属性，而不只是保存输入 Theme。每个 mark、axis、legend、annotation、panel label 的最终值应能区分：RenderingStyleContract、明确标记的 adapter baseline、project Theme、figure override、view override、layer override、对象 override；布局和背景也应记录其 contract 或显式来源。

后续依据 scale 将 linear minor count 改为 log count、根据 palette 序号选择颜色、将背景 `white` 规范为 `#ffffff` 等解析步骤，也必须让来源与最终值一致。不能只更新 `value` 却留下另一个属性的 `source_symbol`。编译器生成的 panel-label 对齐不能假称用户显式 override。

历史请求中的显式字体、尺寸、marker 等值仍是用户/模板覆盖，修改 house 默认不会覆盖它们。本轮没有找到前阶段 `.tmp_verify/figure_grammar_20261008/` 的原始验收文件，因此没有声称重画或复核那一张旧 2×2 图。当前五组真实数据均保留科学映射，在新 revision 中使用 house 默认或有历史 native 依据的显式覆盖；历史 revision 不原地重写。

## 实际旧/新对照

| 组别 | 同源数据与范围 | 物理尺寸 | 有效结构叶子 | 原生 PNG 变化像素 | 结果 |
| --- | --- | --- | ---: | ---: | --- |
| A 普通多曲线 XY | PP-5UDC / PP3155，2×16 点，linear | 60×55 mm | 373 | 0 | 通过 |
| B log 科学曲线 | 同一对真实频率数据，2×16 点，双 log | 60×55 mm | 441 | 0 | 通过 |
| C FTIR | 原始 7,469 点，顺序不变 | 60×55 mm | 340 | 0 | 通过 |
| D marker | 同源 2×16 点，circle/square，逐点绘制 | 60×55 mm | 485 | 0 | 通过 |
| E 已认可 NMR | Sample 5，65,536 点；与保存的实际用户 VSZ 比较 | 120×55 mm（显式） | 250 | 0 | 通过 |

A–D 的旧图来自现有 production `render_to_dir`，新图通过公开 `plot.create`、FigureTemplate v2、Binding 与 Managed compiler 创建；新图不读取旧 VSZ 或其 widget spec。E 的旧基准是用户以前实际交付的 VSZ 的同字节副本；新图只从其科学数据及明确记录的语义覆盖重建。原始用户数据未改写；source 快照、SHA、表格选择和派生准备脚本哈希见 [source-fixtures.json](.tmp_verify/visual_contract_20261008/source-fixtures.json)。

A 保留旧 rheology family 在 linear 轴也使用 `%Ve` 的明确 notation override；这不是通用 house 默认。C 原始 CSV 未给吸光度/透过率身份，保留中性 `Signal (reported)`，没有推测科学量。E 保留原处理数据中的归一化百分比列、0.7 pt round line、原 16-bit RGB `#338933893389`、反向 5→−0.5 ppm、隐藏 y 轴与 `¹H NMR` 标题。历史标题在 plot 外、page 内，新 document 用 figure-space 的等价物理位置表示；没有放宽 clipping QA。

同一 Veusz/Qt、字体文件 SHA 与渲染进程中重新打开两个 native 文档，比较 canvas、plot rect、margins、轴/刻度、字形与实际文字 paint bounds、线/marker、palette、legend、annotation、PDF 页尺寸/字体和 TIFF 导出设置。坐标数组哈希及点数也进入独立比较。Preview 为 150 dpi、PDF 为 native 72 pdfdpi、TIFF 为 300 dpi；不对 PDF 非确定 metadata 作逐字节科学身份比较。

[完整机器回归结果](.tmp_verify/visual_contract_20261008/rendering-regression-results.json) 保存结构 JSON pointers、环境匹配与 raster metrics。每个 `cases/<case>/comparison/` 都有 `old.png`、`new.png`、`diff.png`、结构差分；`old-snapshot/` 与 `new-snapshot/` 保留 PDF/TIFF、完整 native settings 和实际文字测量。未经阈值过滤的 `raw_changed_pixels` 均为 0，MAE/RMSE 为 0，exact pixel fraction=1，changed bbox=null。没有配准、平移、裁切或缩放来制造匹配。

Raster gate 允许 8/255 的通道噪声，按非白前景归一化，超过阈值的墨迹变化上限 0.5%，墨迹总量变化上限 1%。这些阈值没有用于掩盖本轮漂移：最终原始像素已完全一致。独立负对照证明一像素移动、改变字体和线宽会失败；空结构、环境不匹配不能通过。

## 尚未等价及尚未覆盖的属性

| 属性/范围 | 当前差异或边界 | 是否影响当前五张图 |
| --- | --- | --- |
| 隐藏 major/minor grid 和边框的 inherited width | old 1.2 pt，new 0.5 pt；A/B/D 各6项，C5项，E3项 | 均 hidden，不绘制；像素无差异 |
| 完整 native settings identity | 因上列隐藏值，all-channel diff 有差异；不宣称整个 native inventory 相同 | 有效结构另独立通过 |
| Categorical errorbar caps / box / heatmap 等旧 family | 本轮 D 选择用户允许的 marker 分支，未验证 categorical errorbar cap 的全等 | 不属于此次覆盖 |
| 通用 band / title / annotation 默认 | 旧未规定者为 unspecified；保留有来源的 adapter baseline 或显式覆盖 | 不冒充旧 house 规则 |
| 多 panel 外部组合 | panel 内继承 house；gap/shared arrangement/总尺寸由独立 composition policy 负责 | 不宣称旧 2×2 等价 |
| 旧 v1 template、历史 unbound FigureSpec、任意手工 native 图 | 保留既有解释；不会自动重新套用 house | 不做隐式迁移 |
| 跨系统字体/Veusz 版本 | 本轮环境固定并有匹配证据；未证明跨系统逐像素相同 | 需各目标环境单独验收 |

隐藏属性未从证据删除：每组 `comparison/all-channel-diff.json` 与 `all-channel-structure.json` 完整保留。有效结构只排除明确 `hide=true` 的非绘制子通道，保留 hide 本身；任何可见性改变仍会失败。将来若支持显示这些通道，应先将会影响结果的值显式纳入 resolved IR 并补回归，不能沿用 backend 的隐藏缺省。

## Canonical schema、编译边界和模块

- `rendering_contract/`：从旧 AST/constants/JSON 及固定 Veusz baseline 提取87项，封存 immutable resource、闭合 binding schema、来源漂移审计与样式投影。House 内容哈希为 `cb9d4af22f1905ede7acc956ccbc9d664f4d9171a4dad9afb2ca878cf96cd821`；即使重新计算资源哈希，也不允许同 ID/version 静默替换内容。
- FigureSpec 的 `rendering_contract={contract_id,content_hash}` 属于 presentation；多 panel 另带 `composition_policy`。角色 ID 分开校验，不能把 composition 资源充当 house。历史未绑定 document 读取时不自动加入新 binding。
- `plot_grammar/`：按 Contract → project Theme → figure → view → layer → object 解析；颜色/marker 身份按语义层顺序，z-order 不改变身份。PlotIR v2 完整保存最终 styles、geometry、axis/legend metric flow、policy binding 与 `style_provenance`。Backend 无需解释 Theme 或模板默认。
- `plot_layout/`：固定 panel 内边距；约束不足明确失败。Native 文字检测只负责验证，不偷偷改变画布、margin、字号或线宽。
- `plot_backends/house_guides.py` 及现有 marks/plan/QA：将已解析 IR 映射为 native axis/key/mark；不将 Veusz object path 引入 canonical schema。简单 line/point legend 采用旧 metric flow；多个 mark 组成一个语义 entry，不重复标签。
- `qa/rendering_regression.py`：可复用结构/像素/环境 gate；`tests/test_house_style_native.py` 将独立旧新生产渲染对照纳入 native regression，随后另测自重建。新 owner 已接入 changed verification。
- 旧纯 tick/legend 算法通过共享 owner 复用，不复制第二套近似算法。另以 `sciplot-legacy-layout-algorithms-v1` 固定24个实现/政策资源字节，hash `2e9d099a3643b86cdb86239b52395356e1b8660d1ecc7dc719e3e889ad0ff279`。变动会返回 `rendering_contract_algorithm_drift`，要求审查版本；这是保守内容固定，可能阻止无视觉影响的源码变化，后续升级需显式维护。

每组 `style-provenance.json` 汇集最终值与 source 层级、contract/source symbol、canonical/IR identity、最终 geometry 和 export evidence；共281个 resolved style 属性与原始 IR trace.value 逐项核对一致，见 [来源检查汇总](.tmp_verify/visual_contract_20261008/style-provenance-summary.json)。科学数据/transform provenance 仍归既有 scientific owner，本轮没有改写科学算法或引入动态 AI 代码。原有 document authority、transaction/revision、persistent service、typed transforms 和 dependency DAG 没有被另一套渲染入口替代。

## 自重建与回归验证

五组真实 ManagedPlot 保存 document/revision 后，删除 VSZ、render/export 以及持久化 IR cache，仅保留 source 与 SciPlot state，再调用公开 `plot.export` 从零生成。完整 IR 内容、IR hash、scientific hash、native state hash 和 PNG 字节均与删除前相同，PDF/TIFF 正常；native scientific audit、publication QA 通过，source SHA 不变。见 [rebuild-acceptance.json](.tmp_verify/visual_contract_20261008/rebuild-acceptance.json)。该检查与上面的旧/新比较是两套独立门禁。

当前测试证据：

- Contract extraction/binding/drift、grammar style/provenance、结构/raster 负对照均有可重复的 unit tests。
- 可移植 native regression 使用合成 CSV（明确不是实测数据），通过 production legacy 与 Managed 两条路径比较 linear、log、log+marker 三组，再全部删除 Managed 产物并重建。
- 五组真实数据验收另保留完整科学映射、实际 native snapshot、PDF/TIFF 和删除重建证据。
- 最终 `verify --changed --json`：**1,869 passed / 125 deselected**；严格 mypy **306 source files**；Ruff 与 diff whitespace 通过，架构文件大小与无环边界门禁通过。[JSON](.tmp_verify/visual_contract_20261008/verify-changed.json)。
- 最终额外 native：**12 passed**，覆盖既有 Figure 全七类 mark、多面板共享/组合、Managed v1、CLI/MCP v1/v2、未知 native mutation、三组独立旧新比较及全重建。[log](.tmp_verify/visual_contract_20261008/final-native-tests-repaired.log)。全七 mark 可运行不等于全七 mark 已证明与旧 family 视觉等价。
- 原生回归曾抓住 generic legend 直线被错误传入 `Line/joinStyle` 的回退。现仅向支持多段连接的 XY `PlotLine` 发送此属性，自由单线段没有连接顶点；线型与透明度仍按 IR 映射。四个既有 Figure native 失败已全部复跑通过，初始失败 log 保留。
- Doctor：**ready**；runtime smoke：**passed**。Smoke 在最后 provenance 修正与上述局部 generic-line 修复前运行；修复后完整 changed gate 和12项相关 native gate 已重新通过。本报告不会把 changed suite 称为完整 release suite，也不把 Doctor 当作交付质量证明。

**对核心问题的回答：是，在上述已实现并验证的单 panel line/point/光谱 compatibility profile 内，新 FigureTemplate v2 ManagedPlot 的默认 house 视觉已恢复。** 旧源码规定的尺寸、字体、轴/刻度、线/marker、颜色、legend 和有效图形 geometry 均有独立旧/新证据；历史显式覆盖仍以覆盖身份保留。完整 native 隐藏值及未覆盖 family 的等价性不在这个结论内。
