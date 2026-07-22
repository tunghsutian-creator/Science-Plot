# SciPlot Development Roadmap

Status: sole active product and maintenance roadmap.

`README.md` defines current product behavior, `skill/SKILL.md` defines agent
execution, and `docs/ARCHITECTURE.md` defines module ownership. This file lists
unfinished priorities only. Completed work and superseded designs belong in
`DEVELOPMENT_LOG.md` and Git history, not in active instructions.

## Product truth

SciPlot 已确定采用 Veusz-first 路线：

- 原生 Veusz `MainWindow` 是唯一日用绘图前端；
- `studio/document.vsz` 是唯一视觉权威；
- `studio` 是交互和 exact-current 项目的主命令族，交互和 headless 是同一生命周期的
  两种调用方式；
- SciPlot 只增加项目状态、exact-current 导出/QA/delivery 和可选 selected-object AI；
- 浏览器只做首次数据/分组/命名/顺序/尺寸/导出确认和只读结果审查；
- Canvas、Composition、session evidence、promotion 和第二编辑器不再属于产品路线；
- 生命周期、artifact QA、provenance、人工验证和期刊合规保持为不同声明。
- 数据源旁的 `SOURCE_SciPlot/`（或显式 `--out`）只显示 `figures/`、
  `data/`、`project/` 和 `Open_in_Veusz.command`；内部运行历史与证据进入同级
  隐藏 `.sciplot/`。

`autoplot` 是唯一公开的程序化全自动项目、QA 和 delivery 入口，内部复用
one-step/`run_request`；它不是第三个 renderer。`one-step` 只保留为内部
readiness/manifest 合同。

## P0 — 日用可靠性与入口收敛

- 保证 provider 缺失、无网络和未打开 AI dock 时主流程完整可用；
- 保证手工 VSZ 是权威，打开或导出不重新生成或覆盖人工修改；
- 保证 `editing -> exporting -> ready` 与 `needs_fix` 状态可信；
- 把项目结果、准备/自动化和来源审计三类状态分开；
- 只公开并推荐以下 Studio 语义：

  ```text
  studio PATH                         interactive native Veusz
  studio PATH --export ... --json     headless same lifecycle
  studio FIGURE.vsz                   open existing visual authority
  studio PROJECT --export ... --json  exact-current project export
  ```

- 从正常帮助、文档和生成提示中移除 `one-step`、`quick`、`prepare`、`intake`、
  `workbench`；只保留对旧生成 launcher 的显式迁移检测，禁止静默改变科学含义；
- 保持 `autoplot` 为单一全自动编排入口，但不得复制 renderer、Studio 编辑器或另一套
  视觉权威；
- 把 Web `app` 收缩到首次确认和只读结果审查，删除 post-render style/axis/legend/series
  编辑能力；
- 用真实项目记录操作摩擦，只修复实际出现的完整性问题和高频阻塞。

## P1 — 契约单一来源

- 生产语义模板固定为 `curve`、`point_line`、`stacked_curve`、`box`、
  `bar`、`box_strip` 和 `heatmap`；未实现模板在请求验证阶段失败；
- `policy.py` 是全局硬样式权威；模板不能私有覆盖字体、线宽、刻度、标记或普通图框；
- 热图颜色是显式例外，只管理标量色带、等高线和色条配色；
- vendored `plot_contract.json`、ready 规则和文档构建器持续通过
  `style_contract.py` 同源审计；
- README、project skill、CLI help、Doctor 输出和 launcher 文案不得各自复制不同入口；
- 为 public/hidden command 集合、Studio interactive/headless 语义和兼容 alias 增加
  source-controlled 回归测试；
- 所有共享契约变化都增加测试并重跑完整 ready-rule 生命周期。

## P2 — 结构维护与遗留拆分

- 按单一职责继续拆分 `studio.py` 和 `semantic.py`，每次只迁移一个明确 owner；
- 将 `intake.py` 的 headless 项目准备与 browser server/static UI 分离，Studio 不依赖
  第二前端实现；
- 保持 renderer-independent `request_contract.py` 为请求验证的单一 owner，不再引入
  Web/workbench 命名依赖；
- 将 Studio/open/export 共用结果结构抽到单一 owner，再决定 autoplot adapter 的退役窗口；
- 缩小 `_vendor` 桥接面，禁止新增直接依赖；
- 删除未被正常 Studio、兼容合同或测试引用的模块、命令、probe 和文档；
- 优先删除重复和死代码，不用新抽象层掩盖相同逻辑；
- 每次提取保持公开 CLI、项目、VSZ、manifest 和 delivery 合同不变。

## P3 — 人工日用证据

至少覆盖：

- 多样品流变；
- 光谱或衍射；
- 热分析；
- 力学或分类指标；
- 标量场或另一种高级图。

每个项目检查：

```text
raw input
  -> inspect / ready rule
  -> 仅确认未解决的科学含义
  -> Veusz 人工微调
  -> 保存、关闭、重开
  -> exact-current PDF/TIFF
  -> QA 和 delivery
```

记录是否需要改代码、确认次数、是否丢失编辑、制品是否一次生成成功，以及 optional AI
是否真的比手工更快。AI 没有收益也是有效结论。机器门支持当前使用，但不能关闭人工连续
日用证据项。

## 非目标

- 恢复独立 Canvas、Composition Board 或浏览器绘图 workbench；
- 自制 Veusz 对象树、属性编辑器、Datasets 或任意拼图器；
- 广泛自主的整文档 AI；
- AI 修改原始科学数值；
- 用自动图像审查替代已经验证的确定性路径；
- 用 synthetic smoke 冒充真实数据或人工日用证据；
- 在证据不足时宣称通用期刊合规；
- 在个人日用稳定前扩展云协作或更广平台产品化。

## 工程门

每个非平凡开发回合：

1. 保留无关用户修改；
2. 更新本地 `DEVELOPMENT_LOG.md`；
3. 为改变的公共行为增加或更新测试；
4. 保持一个 Veusz `Document`、一个 VSZ 权威和原生 Undo；
5. 运行：

   ```bash
   python -m pytest -q
   skill/scripts/sciplot doctor --json
   skill/scripts/sciplot smoke --out .tmp_verify/runtime_smoke --json
   git diff --check
   ```

6. GUI/文档改动验证保存、Undo/Redo、关闭重开和 exact-current 导出；
7. AI 改动验证 disabled、invalid、stale、interrupted 和 rollback 路径；
8. 共享 style、renderer、rule、QA 或 delivery 改动运行完整 `acceptance rules`；
9. 交付前清理 `build/` 与 `*.egg-info/`，构建 wheel，并禁用源码 `PYTHONPATH`
   验证安装态 Doctor/Smoke；
10. 最后核对工作树、分支和提交状态。

runtime smoke 是变化门，不是真实数据证据。规则矩阵通过是范围证据，不是人工连续使用或
期刊合规证据。

## Deferred

- packaging、签名、公证和干净机器分发；
- broader platform support；
- additional AI operation types；
- cloud collaboration。

这些工作等待个人日用稳定，不能抢占日用可靠性和可维护性。
