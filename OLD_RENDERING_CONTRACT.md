# 旧绘图实现的 Rendering Contract 审计

审计日期：2026-10-08。审计对象是现存 legacy 普通绘图链路、共享 Veusz primitives、版本化 policy，以及真实历史 VSZ；不是从 Figure Grammar v2 的默认值倒推旧规范。本文描述旧行为，不代表新 ManagedPlot 已经通过视觉等价验收。

## 1. 权威、范围与提取证据

普通新建旧链路是 `studio_core/veusz_document.py:_write_veusz_document` → `studio_render/style_contract.py:_veusz_style_contract` / `veusz_spec_builder.py:_build_veusz_plot_spec` → `veusz_apply.py:_apply_veusz_spec` → `veusz_save.py:_save_veusz_document_from_spec`。以后手工编辑过的 LegacyPlot 则以当前保存 VSZ 为完整视觉权威，不能用创建时 spec 抹掉用户修改。

必须区分以下来源：

| 类别 | 本文含义 |
| --- | --- |
| project hard contract | `policy/frame_export.py` 的统一字体、笔画和固定物理边距，以及 `visual_identity.py` 的普通单图尺寸 |
| style preset | `policy/plot_contract.json` 的 nature spacing、alpha、legend frame 等；不是允许字体任意漂移的另一套硬规范 |
| family / template | FTIR 倒轴、光谱长画布、分类图误差帽、TTS 标题等；只适用于对应路线 |
| explicit override | 确认的系列编码、模板选择、尺寸选择和后续保存的人工/native 编辑 |
| unspecified | 被审计的旧普通创建实现没有显式规定；不能包装成旧项目要求。运行时继承的 Veusz/Qt 默认值须另记 renderer evidence |

本次程序化提取证据位于 [old_source_audit.json](.tmp_verify/visual_contract_20261008/old_source_audit.json)：155 个 policy 常量、原始 plot-contract JSON、旧 executable style 的实际返回值，以及 14 个旧 lowering/annotation/export 源文件中的 448 条 `Set` 调用（源文件、符号、行号、setting/value expression、文件 SHA256）。这份证据是 source audit，不把没有显式赋值的 native 属性冒充规范。

`_veusz_style_contract({})` 本次实际运行结果：Arial 7 pt，legend 6 pt；line 1.2 pt / alpha 0.92，marker 2 pt / alpha 0.95 / outline 0.8 pt；axis/major/minor width 0.8 pt；major 2.8 pt，minor 1.5 pt；label offset 2 pt，tick offset 1.4 pt；边距 L14/R4.5/B11/T5.5 mm。

## 2. 画布与 plot rectangle

| 属性 | 旧值与含义 | 精确来源 |
| --- | --- | --- |
| 默认普通单图宽×高 | **60 × 55 mm**，整个 page，不是绘图区 | `policy/visual_identity.py:6 DEFAULT_FIGURE_SIZE`；`policy/plot_contract.json:24 global_frame` |
| 支持的显式尺寸预设 | 60×55、120×55、180×55、60×110、120×110、180×110 mm | `policy/frame_export.py:111 FIGURE_SIZE_PRESETS` |
| 固定边距 | left 14、right 4.5、bottom 11、top 5.5 mm | `policy/frame_export.py:66–75 UNIFIED_*_MARGIN_MM`；`style_contract.py:94–97` 从 global_frame 取值 |
| 默认绘图区 | 左上原点 `(14, 5.5)` mm，宽 41.5 mm，高 38.5 mm | 由 page 尺寸减上述固定边距；`studio_core/veusz_graph_setup.py:49–54` 写 native margins |
| 固定框策略 | `margin_mode=fixed_mm`；outside legend 禁止；辅助 frame/text 不越过固定 envelope | `policy/layout_policy.py:34–40 FrameAlignmentPolicy`；`veusz_spec_builder.py:175–186 _frame_alignment` |
| 宽图 plot rectangle | 120×55 时 `(14,5.5,101.5,38.5)` mm；边距不按比例缩放 | 同上；`veusz_document.py:152 _size_mm` |
| 图外 border | 不画 graph 的矩形 Border；主要 x/y 轴单独画 | `veusz_graph_setup.py:48 Border/hide=True` |
| 通用 panel gap / shared legend 外占位 | **unspecified**；没有一个适用于任意 Figure composition 的旧通用规则 | 普通链路只创建 `page1/graph1`；TTS 和 performance 另有专用 composition |

旧尺寸和边距是数值约束，不能因新 solver 的估算字体宽度而偷偷扩页、缩字体或移动 plot rectangle。实际渲染超出固定安全区域应产生明确 QA 失败；不能把适配后的新几何称为旧样式。

## 3. 字体与文本

| 属性 | 旧值 / 状态 | 精确来源与限定 |
| --- | --- | --- |
| 默认 family | Arial | `frame_export.py:24 UNIFIED_FONT_FAMILY`；`veusz_graph_setup.py:34 StyleSheet/Font/font` |
| axis label / tick label | 7 pt；foreground `#111111` | `frame_export.py:27,63`；`studio_render/axes_spec.py:172–179,210–217` |
| legend text | 6 pt；font 继承 Arial | `frame_export.py:30`；`veusz_graph_setup.py:95` |
| legend text color | **unspecified**（旧 key 没有显式设置 `Text/color`） | `veusz_graph_setup.py:91–115 _add_native_veusz_key`；不可直接把 axis foreground 当成其旧值 |
| 普通 axis / tick / legend bold、italic | **unspecified**（这些对象未显式赋值；由 native 样式继承） | 同上述 axis/key lowering |
| 普通新图 title | 默认没有独立 title 对象；title 内容、字号和位置 **unspecified** | `veusz_apply.py:_apply_veusz_spec` 普通路径没有通用 title 创建 |
| typed annotation / title 编辑 | Arial 7 pt、`#111111`、非粗体、非斜体；left/bottom；angle 0；margin 0 pt；不裁剪 | `studio_core/annotation_geometry.py:24–35 annotation_widgets`；这是 annotation API 默认，不是自动标题布局 |
| 旧 inline/direct series label | 7 pt、系列颜色；left/right 取 label side；默认 centre 垂直对齐；angle 0；bottom 时 margin 1 pt 否则 0；clip=true | `studio_render/axes_spec.py:222–303 _direct_label_contracts` |
| panel label | 普通单图不创建；已有 TTS 专用标题 7 pt bold 黑色 | `frame_export.py:36`；`rheology_tts_native.py:33–54,191–199`；不能据此推导任意 grid 的 panel-label 位置 |
| 单位排版 | 空格分隔、除法变负指数乘积、Unicode superscript、不用 solidus | `frame_export.py:9–21 SCIENTIFIC_UNIT_*`；axis/legend 文本分别经 `_veusz_axis_label` / `_veusz_literal_text` |

旧硬规范在 `studio_render/style_contract.py:71–98,119–122` 明确不从请求的字体/笔画值重设创建标准；`policy/render_options.py:145–205` 从可验证 override 键里剔除硬属性。后续合法 native 编辑仍可保存不同值。故新层级可以提供显式 override，但不能声称“旧 Theme 本来就允许任意覆盖所有硬标准”。

## 4. Axis、ticks 与 padding

| 属性 | 旧普通行为 | 精确来源 |
| --- | --- | --- |
| Axis line | 0.8 pt、`#111111`、visible、transparency 0 | `frame_export.py:42,63`；`veusz_axis_apply.py:67–71` |
| 主刻度 | width 0.8 pt、length 2.8 pt、transparency 0 | `frame_export.py:45–48`；`veusz_axis_apply.py:72–80` |
| 次刻度 | width 0.8 pt、length 1.5 pt、transparency 0 | `frame_export.py:51–54`；`veusz_axis_apply.py:81–90` |
| 刻度方向 | `outerticks=True`，向外 | `veusz_axis_apply.py:66` |
| 镜像轴 | `autoMirror=False`；普通创建仅 x/y，没有自动 top/right | `veusz_axis_apply.py:65`；`veusz_graph_setup.py:55–56` |
| Axis-label padding | nature 2 pt | `plot_contract.json styles.nature.spacing.axes_labelpad`；`style_contract.py:89`；`veusz_axis_apply.py:102` |
| Tick-label padding | nature x/y 均 1.4 pt | 同 JSON 的 xtick_major_pad / ytick_major_pad；`veusz_axis_apply.py:115–118` |
| Linear numeric format | `Auto`，具体生成字符串由旧 Veusz format 行为决定 | `axes_spec.py:149–152,187–190`；`veusz_axis_apply.py:108` |
| Log numeric format | `%Ve`、major decade labels；minor multiplier `(2,4,6,8)` | `frame_export.py:181–187`；`axes_spec.py:158–166,196–204`；`studio_render/value_parsing.py:_log_minor_ticks` |
| Minor count | linear 20；log 默认 5；显式 minor list 时 `MinorTicks/hide=False` | `axes_spec.py:153–166,191–204`；`veusz_axis_apply.py:90–98` |
| 没有显式 minor list 时的显示状态 | **unspecified**：旧 lowering 不写 hide，继承 native 默认 | `veusz_axis_apply.py:91–98`；不可把新 `hide=True` 当旧规则 |
| Major tick locations | 从 scientific axis contract 取值；只有 2–12 个时写 `manualTicks`，其余使用 native tick generation | `veusz_axis_apply.py:127–129` |
| Tick-label rotation | categorical x 且类别数>4 时 45°；普通 numeric 的 rotation **unspecified** | `veusz_axis_apply.py:109–114` |
| 隐藏 y ticks | 请求 `show_ticks=False` 时 major/minor/tick labels 全隐藏 | `veusz_axis_apply.py:119–122` |
| Label position / auto spacing / collision policy | 没有显式 physical text anchor，旧 native axis 决定；**unspecified** 为通用定量规则 | 旧路径真正启用原生 `Label` / `TickLabels`，不是 page-level 手工 label |
| Major / minor grid | 普通旧创建均 **unspecified**（没有 `GridLines` / `MinorGridLines` 赋值） | 完整 `_add_veusz_axis` 与本次 source inventory |

轴域不能混同于样式常量。旧 `policy/plot_contract.json:32 axis_policy` 有 linear nice steps `[1,2,5]`、outer padding 0.05、端点标签；`frame_export.py` 也保留另一轴辅助算法的 0.02 padding 常量。实际测试必须取旧 `_veusz_axis_contract` / `_expand_axis_for_visual_extents` 的解析结果，不能任选一个 padding 数字当所有 family 的真实输出。显式科学 Scale domain 和原始数据仍须保持。

## 5. 系列线、marker、颜色和误差棒

| 属性 | 旧普通值 / family 例外 | 精确来源 |
| --- | --- | --- |
| 默认 palette | `control_first_bright`，按解析后的样品顺序 | `policy/visual_identity.py:DEFAULT_PALETTE_PRESET`；`policy/palette_authority.py:resolve_palette_authority` |
| Palette 颜色序列 | `#222222`, `#3568C0`, `#C83E4D`, `#2A9D8F`, `#D99A24`, `#7C9ED9`, `#7B61A8` | `visual_identity.py:CONTROL_FIRST_BRIGHT_COLORS`，JSON 同名 categorical palette |
| Line width | 默认 1.2 pt；系列明确绑定值 / 保存后人工编辑可不同 | `frame_export.py:39`；`series_encoding_contract.py:80–84` |
| Line style | 普通 curve 默认 solid；可用序列 solid/dashed/dotted/dash-dot/dash-dot-dot/dashed-fine/dotted-fine | `frame_export.py:97–108`；`veusz_primitives.py:48–49` |
| Line alpha | 默认 nature 实际 **0.92**，写 native transparency=8 | `style_contract.py:85`；`series_encoding_contract.py:85`；`veusz_primitives.py:74` |
| Join style | 未显式编辑时保留 **bevel**；round 是明确 native 修改 | `studio_core/veusz_line_joins.py:8–35` runtime extension；不要把新 grammar 的 round 冒充旧默认 |
| Line cap / interpolation | **unspecified**（旧注释明确保持 upstream 所有权） | `veusz_line_joins.py:9–13`；`veusz_primitives.py:_add_veusz_xy_series` |
| Marker size / outline | 2 pt / 0.8 pt；系列显式编码可不同 | `frame_export.py:57–60`；`series_encoding_contract.py:87–105` |
| Marker color | fill/line 默认都跟随系列 color，显式系列填充/描边可覆盖 | `series_encoding_contract.py:95–105` |
| Marker alpha | nature 默认 0.95 → transparency=5；原始点 family / item 可覆盖 | `style_contract.py:86`；`series_encoding_contract.py:282–294` |
| Marker sequence | 普通 point_line 为 circle/square/diamond/triangle；curve 通道通常 marker=none | `policy/template_defaults.py:53–58 POINT_LINE_RENDER_OPTIONS`；最终取系列 encoding |
| Marker fill | point_line 默认 filled；未显示的通道显式 hide | `template_defaults.py:56`；`veusz_primitives.py:65–73` |
| Marker thinning | 最终 `encoding.marker.thin_factor`；大于1才写 thinfactor | `series_encoding_contract.py:94`；`veusz_primitives.py:85–87`；不得误认为删 raw data |
| XY unused error channel | `ErrorBarLine/hide=True`，避免图例中心伪误差点 | `veusz_primitives.py:57–64` |
| 普通 categorical bar/error | error width 1.2 pt、solid、opaque、`#111111`；真实 native line segments；low/high 按明确统计结果 | `studio_core/veusz_bar_error.py:82–151` |
| Error cap | 分类 bar 宽度×0.50；默认 bar width 0.32 个类别间隔，因此 cap 总宽0.16数据单位；不是统一8 pt | `policy/categorical.py:72,214`；`veusz_bar_error.py:89–98` |
| Point-line error color | 与对应 error record 的 color 相同；width默认1.2 pt，cap 同参考bar宽×ratio | `veusz_legends.py:200–279` |
| Categorical bar outline/fill | outline 0.70 pt；bar fill transparency 0；fill/keyline 另有 palette 映射 | `policy/categorical.py:50–70,116–125`；`veusz_bar_error.py:154–279` |

一个实际不一致必须保留在证据中：`template_defaults.py` 的 `CURVE_RENDER_OPTIONS` / `POINT_LINE_RENDER_OPTIONS` 声明 alpha=1，但 `_veusz_style_contract` 不读取这些请求 alpha；普通 XY native lowering 最终使用 style 的 0.92/0.95。因此本次兼容目标以旧 executable spec/native 为准；不以配置字段名字推断旧图确实不透明。

## 6. Legend、annotation、背景及 native settings

| 属性 | 旧行为 | 精确来源 |
| --- | --- | --- |
| Legend visible | 普通series>1且未显式隐藏；单曲线无key；stacked inline/edge用direct labels；分类图有自己的legend条件 | `studio_render/legend_visibility.py:97–125` |
| Legend position | inside；auto→已解析inside_best/clearance结果；四角和manual有明确映射；无匹配最终fallback right/bottom | `legend_visibility.py:19–34`；`veusz_axis_apply.py:15–52` |
| Legend size/spacing | 6 pt；native `keyLength=0.40cm`；`marginSize=0.15`（native单位，不能擅自标成mm）；title为空 | `veusz_graph_setup.py:91–103`；`frame_export.py:33` |
| Legend columns | series≤4为1；窄图长label也1；其他2 | `legend_visibility.py:37–52` |
| Legend frame | nature false→Background/Border都hide | `style_contract.py:93`；`veusz_graph_setup.py:113–114` |
| Legend native row gap、symbol/text gap、text bounds、对齐细节 | **unspecified**；由native key真正排版，而不是新手工绘制的legend几何 | `_add_native_veusz_key`完整实现 |
| Reference line | 旧guide API默认1.2 pt dashed `#6B7280`，transparency35；typed annotation reference line另用`#111111` opaque | `studio_render/axes_spec.py:71–126`；`annotation_geometry.py:44–57`；两个API不能混成单一默认 |
| Reference band | 默认`#6B7280`，transparency86 | `axes_spec.py:71–98`；`studio_core/veusz_guides.py` |
| Annotation arrows | typed annotation arrow5 pt、`#111111`、line1.2 pt；实体填充；anchor来自document | `annotation_geometry.py:44–57` |
| Page background | white且visible；另加整页relative白色rect，opacity1、border hidden、clip=true | `veusz_graph_setup.py:44–45`；`veusz_canvas_finish.py:34–51` |
| Paint order | Veusz sibling反序；label/key/error先添加使其在数据上方，reference guides在数据后添加作为底层 | `veusz_apply.py:53–81`；`veusz_graph_setup.py:68–80` |
| Clip | 旧原生XY使用原生绘图区；reference/error line显式clip=true；direct labels clip=true；typed text annotation clip=false | `veusz_primitives.py:91–122`；`veusz_legends.py:161–197`；`annotation_geometry.py:30` |

完整的“旧代码写过哪些 Veusz setting”按源文件/函数/表达式见 `old_source_audit.json.native_setting_assignments`，覆盖 axis/page/key/XY/line/contour/image/colorbar/bar/box/direct label/reference/error/背景与导出路径。`Add` 的顺序、未写出的 renderer defaults 和 annotation dict settings 仍须用实际 native reopen inventory 验证；仅文本搜索/生成 VSZ 中显式 `Set` 行不能证明完整 native state 等价。

## 7. Export

| 属性 | 旧值 / 状态 | 精确来源 |
| --- | --- | --- |
| 默认交付 | PDF + 300-dpi TIFF | `policy/frame_export.py:114 DEFAULT_EXPORT_FORMATS_POLICY` |
| 可选格式 | PDF、SVG、PNG300、PNG600、TIFF300；别名规范化 | `frame_export.py:117–129`；`render/formats.py:19–25 _EXPORT_FORMATS` |
| Raster DPI | TIFF300 / PNG300 / PNG600分别明确传dpi | `studio_core/export_execution.py:140–151` |
| PDF DPI选项 | `pdfdpi=72`，page=[0]；vector图元不等于72dpi位图 | `export_execution.py:146–151` |
| PDF/PS font type42、RGB、figure150dpi、save300dpi | JSON preset声明存在；**普通Veusz导出未把pdf_fonttype/ps_fonttype/color_space作为Export参数传入** | `plot_contract.json styles.nature.export` vs `export_execution.py:146–151`；不能声称Matplotlib选项已强制Veusz嵌字格式 |
| TIFF compression / bitdepth、PDF version、font embedding细节、anti-alias、ICC profile | **unspecified**，继承当前Veusz/Qt exporter；必须在同native/font环境比较 | `export_execution.py:146–151`实际kwargs只有page/dpi或pdfdpi |
| 背景透明度 | 由显式整页opaque白rect保证白底 | `veusz_canvas_finish.py:34–51` |
| 时间戳等metadata | native/export运行产物，不应进入scientific identity；byte equality不是视觉等价定义 | 普通spec `created_at`见`veusz_spec_builder.py:138`；新Managed hash分离仍保持 |

## 8. Family 与历史用户例外

FTIR/spectrum 的默认 stacked尺寸是120×110 mm，FTIR reversed x、inline series labels、baseline none；这来自 `policy/visual_identity.py:12 STACKED_SPECTRUM_FIGURE_SIZE`、`template_defaults.py:101–113` 和 `layout_policy.py:69–93`。`plot_contract.json.special_layouts.wide_nmr` 另有60×110/18mm结构保留/92mm光谱高度的声明，不能覆盖真实NMR用户选定的120×55。

Log rheology point_line 的 x/y log、major/minor格式来自 `template_defaults.py:61–70 RHEOLOGY_FREQUENCY_RENDER_OPTIONS`；Scientific units/metric的限定不是通用视觉契约。TTS单独有panel title和composition，performance radar单独有8/10.5/9.5/7mm边距、6pt轴标等（`visual_identity.py:15–45`）；这些不能当成普通 Cartesian 60×55 单图的新默认。

已核实的历史代表图位于：

`/Users/dongxutian/Library/CloudStorage/OneDrive-HKUST(Guangzhou)/1 PhD/4 UDC/NMR/NMR_12345_CSV_sample5/`

该目录当前具有原始 `sample5_1H.csv` / `sample5_13C.csv`、各 `sample5_*_120x55_SciPlot/project/studio_009.vsz`、PDF和300-dpi TIFF。只读采集其当前SHA/大小的证据见 [approved_legacy_sources.json](.tmp_verify/visual_contract_20261008/approved_legacy_sources.json)。本轮没有改写这些历史交付。

¹H VSZ实际值确认：120×55mm，标题`¹H NMR` Arial7pt regular、relative anchor，x域5→−0.5但major ticks只有0..5，y轴整体hidden；曲线0.7pt、round、opaque、颜色保存为16-bit hex `#338933893389`。这些是用户保存的explicit override，**不是统一house默认**；需要完全等价时必须表达并保留其真实色值/几何/文本/native效果，不能拿默认黑色1.2pt曲线冒称重现。原CA认可案例的旧Downloads路径当前不存在，因此没有把记忆中的图当作本轮已复核native基线。

## 9. 新契约提取与验收边界

`sciplot-house-style-v1` 应从上述硬常量和实际 `_veusz_style_contract({})` 提取，可为每个属性记录 `value`、`source_file`、`source_symbol`、`source_line`、`notes`。可直接复用现有 policy loader，避免第二份数字维护。固定尺寸/边距/字体/线宽和实际alpha都有来源；只有native继承的属性必须显式标为 `unspecified`，或在另一层记录“Veusz版本固定后的resolved renderer default”，不能悄悄晋升为旧科学/视觉规范。

任何新通用 composition 的gap、shared decoration reserve、panel-label box、outer size计算应归入独立 `sciplot-figure-composition-v1`。旧TTS的局部实例不足以证明存在任意grid通用兼容规则。

新旧回归需要至少普通多曲线、log曲线、spectrum、marker/errorbar以及上述真实历史案例，逐个绑定相同source/data/domain/文本。结构检查必须比较真正native和physical geometry，像素检查保留old/new/diff且能识别字体/位置/笔画漂移；不能仅比较新编译器与自己，也不能由“新旧都读同一份新IR”制造循环证明。旧结构审计、视觉回归、scientific/native audit、clipping QA和Managed rebuild各自独立。

本文只完成旧实现审计。Managed默认是否恢复旧风格、哪些属性仍不等价，应由本轮实际回归报告给出结果；不能由此审计文档本身宣布通过。
