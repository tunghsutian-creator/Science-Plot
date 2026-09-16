# 科学元数据确认：实现与验收

日期：2026-09-10。范围限于原始区域查询、逐列诊断、带证据的元数据确认，
以及一份真实原件的确认—建图—导出。异长范围、自然源修订、AI 调用效率和
独立安装/用户验收不计入本项完成结论。

## 已实现的公开入口

- `task table-region TASK --query QUERY_JSON --json` 与 MCP
  `sciplot_task_table_region`：读取当前问题所绑定原件的指定矩形，最多
  128 行 × 64 列；保持零基索引、空单元格和读取值，查询不改写任务。
- `table_selection` 返回逐列 `raw_metadata`、数值点数/无效原始行位置、
  X/Y 拒绝原因、样品缺失提示及元数据冲突。
- `metadata_confirmations`：每项绑定原件 SHA-256、工作表、列和
  `quantity` / `unit` / `sample`。原始单元格、外部 URI/位置/摘录、
  署名用户声明分别存储；不把声明改写成原始事实。
- 更正时提交完整替换列表，`[]` 撤回全部声明；改变区域也清除声明。
  当前问题版本参与答案绑定，已接受答案及旧问题保留在任务历史中。
  形状/原件/单元格错误不消耗当前问题；科学冲突保留在诊断中并阻止相关列对。
- 继续使用 DataMapping 的确认与执行。新提案携带 `table_confirmation`；
  预览、执行、项目源核验和导出恢复时重新由原件、选择及冻结声明重建映射。
  历史提案未设置此字段时保留原确认哈希契约。

完整字段见 [外部控制说明](../skill/references/external-control.md)。
外部材料的相关性和真实性由读取材料的调用方判断；SciPlot 核验记录与源绑定，
不会自动访问引用或证明用户声明真实。确认不执行单位换算，也不允许声明新的
科学量来替换当前规则。需要数值转换的单位差异继续阻断。

## 成功的独立原始工作簿

来源：[Bath-01345 数据集](https://researchdata.bath.ac.uk/1345/)，
Zoumpouli 等，2024，*Reimagining the shape of porous tubular ceramics using
3D printing*。下载其 [XRD/MIP/Compression 原始工作簿](https://researchdata.bath.ac.uk/1345/10/Sintered%20titania%20XRD_MIP_Compression.xlsx)，
未重排、修改或补写任何单元格。

| 核对项 | 实际证据 |
| --- | --- |
| 文件 SHA-256 | `ece4b70a827b3b1e36716b449caf0c89d50716cba9992488556de08e94cf00cd`，前后相同 |
| 区域 | `XRD`，表头行 6，数据 `[7, 4899)`，列对 `(0,1)` 与 `(2,3)` |
| 样品 | 原始行 5 的 `Ti acrylate 25%`、`Ti acrylate 50%`，通过源单元格确认分别绑定 X 列 |
| X 单位 | 原始 `2θ (degrees)` 单元格支持显式确认 `degree`；是单位写法确认，没有数值换算 |
| Y 量和单位 | 原始表头明确为 `Intensity (a.u.)` |
| 点数与测量值 | 每样品 4,892 点，数值及顺序逐项等于原件、spec、真实 Veusz 数据集和交付 CSV |
| 纠错 | 注入标明为验收故障的 `nm` 声明，与原始 Y 单位冲突；选列被拒绝。撤回后继续，旧问题答案被拒绝 |
| 结果 | 公开 CLI 完成建图和 PDF/TIFF 导出；新进程查询 source、QA、delivery 均 current |
| 当前文档 | 当前与交付 VSZ SHA-256 均为 `3c50f759c62c54086c8d85d24efb807a48abe4b59cf30ee313d50c5b72e2f97c` |
| 交付 CSV | SHA-256 `7377b526085bfd431ec8ea3348f631f6b7f2d15fbad33c9bd675bfe588ec93d4` |

原件在现有原始文件归档中有字节相同的副本。保存文档通过 Veusz 原生接口
只读加载并读取实际数据集，未以 VSZ 文本推断测量值。检查了原生预览与 PDF
重新栅格化图像，两个样品标签、坐标及曲线显示完整，未发现裁切或图例遮挡。
这是代理完成的真实数据验收，不是独立初学者或最终印刷尺寸的人工验收。

## 真实外部证据与继续阻断

对上一轮 [eLife 51737 数据](https://elifesciences.org/articles/51737/figures)，
直接读取了出版方 [Figure 1 supplement 2 原图](https://cdn.elifesciences.org/articles/51737/elife-51737-fig1-figsupp2-v3.jpg)。
原始 Y 表头为样品 `Z`；源单元格确认其身份，再以原图 panel a 的纵轴文字
“Absorbance”作为 `external_reference` 确认量名。

公开任务正确保留 `raw_metadata.header = Z`，有效量名变为 Absorbance，
但图中未声明现有规则要求的 `a.u.`。因此诊断仍为 `missing_unit`，选列被拒绝，
任务保持 `needs_input`，没有创建或导出项目。未把未标单位的吸光度自动改标
为任意单位。真实外部摘录可进入确认流程，不代表引用不足也会获准成图。

Bath-00675 的出版方 XRD 原图也未给出明确 Y 单位，仍不作为成功案例。
先前五个案例的历史结果保留在 [原验收记录](TABLE_SOURCE_UPDATE_ACCEPTANCE.md)。

## 自动化与证据文件

最终 `verify --changed`：Ruff、985 个 focused 测试（66 个 comprehensive 未选入）、
172 个配置范围内源文件的严格 mypy 与 diff whitespace 均通过。另跑新元数据
确认的原生建图/冷导出测试，1 项通过；Doctor 为 ready，运行 smoke 为 36/36。
未运行完整 pytest 或规则发布验收，不作发布/合并验收声明。

开发证据全部在忽略目录 `.tmp_verify/scientific_metadata/`：

- `run_real_case.py`、`commands.json`、`00`–`10` 请求/响应及 `real-task/`：
  只编排公开 CLI，没有绘图实现；成功交付位于其原件旁的
  `raw/Sintered_titania_XRD_MIP_Compression_SciPlot/`。
- `verify_real_integrity.py`、`integrity.json`：原件、原生 VSZ、spec、CSV、
  字节归档与交付文件哈希核对。
- `run_external_evidence_case.py`、`external-real-case.json`、`elife-external-task/`：
  真实外部原图量名确认和缺失单位拒绝。
- `native-preview/`、`export-review.png`、`visual-review.json`：实际检查的图像及记录。
- `changed-verification-final.json`、`metadata-tests-final.txt`、`native-test.txt`、
  `doctor.json`、`smoke.json`：验证输出。新增原生测试覆盖外部摘录进入 DataMapping、
  真实 Veusz 建图及另一任务中的冷导出；该测试的输入和外部摘录是明确的合成夹具。

本地网页下载曾分别受到网络沙箱及公开站点 HTTP 403 限制；改用可读取的
公开出版方图片核对，保留图像及 SHA，不猜测缺失标注。上述限制没有通过
改写源文件或放宽科学校验来解决。

每对独立范围、跨工作表组合、单位数值转换、新科学量、自然源修订全流程、
真实 AI 客户端效率、干净机器和独立用户验收仍分别待完成。
