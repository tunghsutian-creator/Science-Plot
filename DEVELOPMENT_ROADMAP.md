# SciPlot Development Roadmap

Status: active maintenance roadmap.

## Product truth

SciPlot 已确定采用 Veusz-first 路线：

- 原生 Veusz `MainWindow` 是唯一日用绘图前端；
- `studio/document.vsz` 是唯一视觉权威；
- SciPlot 只增加项目状态、exact-current 导出/QA/delivery 和可选 AI；
- AI 只修改当前选中对象的安全属性，并共享 Veusz 原生 Undo；
- Canvas、Composition、session evidence 和 promotion 流程不再属于代码库或产品路线；
- 不再开发第二个编辑器、第二个渲染器或第二套文档模型。

## 现在的目标

目标不是扩张功能数量，而是把已有能力做成可以长期维护的日用工具：

1. 无 AI 完成受支持原始数据到可编辑 VSZ、PDF/TIFF、QA 和 delivery；
2. 人工调整始终使用 Veusz 原生交互，保存和重开不丢失；
3. 六类已实现生产模板 fail closed，不允许未知模板静默退化；
4. 字体、字号、线宽、刻度、标记和普通图框由全局硬契约控制；热图的标量色带、
   等高线和色条配色由显式热图颜色契约控制；
5. 真实使用中重复出现的问题进入共享规则、policy、fixture 和测试；
6. 生命周期、artifact QA、provenance、人工验证和期刊合规保持为不同声明。

当前机器门可以证明工程路线成立，但不能代替连续人工日用。只有真实项目使用过、关闭重开、
手工调整和交付均无阻塞，才能称为完成日用验证。

## 维护优先级

### P0 — 日用可靠性

- 保证 provider 缺失、无网络和未打开 AI dock 时主流程完整可用；
- 保证手工 VSZ 是权威，导出不重新生成或覆盖人工修改；
- 保证 `editing -> exporting -> ready` 与 `needs_fix` 状态可信；
- 把来源审计状态与当前制品状态分开；
- 对保存、导出、哈希、QA 和 delivery 使用失败可见、可恢复的边界；
- 用真实项目记录操作摩擦，只修复实际出现的 P0/P1 问题。

### P1 — 契约收敛

- 生产语义模板固定为 `curve`、`point_line`、`stacked_curve`、`box`、
  `box_strip` 和 `heatmap`；
- 未实现模板在请求验证阶段失败；
- `policy.py` 是 SciPlot 全局硬样式权威；
- vendored `plot_contract.json`、ready 规则、figure profiles 和文档构建器必须通过
  `style_contract.py` 的同源审计；
- 模板只拥有语义选项，不能私有覆盖字体、线宽、刻度、标记或普通图框边距；
- 热图颜色是显式例外：可以独立管理标量色带、等高线和色条配色，但不能借此私有覆盖
  全局字号、线宽或物理图框；
- 所有共享契约变化都增加 source-controlled 测试并重跑完整 ready-rule 生命周期。

### P2 — 结构维护

- 按单一职责继续拆分 `studio.py` 和 `semantic.py`，每次只迁移一个明确 owner；
- 缩小 `_vendor` 桥接面，禁止新增直接依赖；
- 删除未被正常 CLI、Studio 或测试引用的遗留模块和文档；
- 保持 README、架构、路线图和 CLI help 只描述当前产品；
- 优先删除重复和死代码，不用抽象层掩盖相同逻辑；
- 每次提取保持公开 CLI 和制品合同不变。

### P3 — 人工日用证据

至少覆盖这些真实任务族：

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

记录是否需要改代码、确认次数、是否丢失编辑、制品是否一次生成成功，以及 AI 是否真的比
手工更快。AI 没有收益也是有效结论。

## 非目标

- 恢复独立 Canvas 或 Composition Board；
- 自制 Veusz 对象树、属性编辑器、Datasets 或任意拼图器；
- 广泛自主的整文档 AI；
- AI 修改原始科学数值；
- 用自动图像审查替代已经验证的确定性路径；
- 用 synthetic smoke 冒充真实数据或人工日用证据；
- 在证据不足时宣称通用期刊合规；
- 在个人日用稳定前扩展云协作或跨平台产品化。

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
8. 共享 style、renderer、rule、QA 或 delivery 改动运行完整
   `acceptance rules`，并检查授权证据层级；
9. 交付前从清理过的 `build/` 与 `*.egg-info/` 状态构建 wheel，禁用源码
   `PYTHONPATH` 验证安装态 Doctor/Smoke，并检查 wheel 不含退役模块；
10. 最后核对工作树、分支和提交状态。

runtime smoke 是变化门，不是真实数据证据。规则矩阵通过是范围证据，不是人工连续使用或
期刊合规证据。

## 以后再做

只有个人日用稳定后才考虑打包、签名、公证、干净机器安装、更新/回滚和更广平台支持。
分发工作不得抢占日用可靠性和可维护性。
