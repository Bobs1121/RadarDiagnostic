# radarAnalyze 本地/内网交付调研与建议

> **归档：2026-09-17。本文仅保留历史设计/证据，不再是当前开发指令。当前唯一套件见 [DDD 入口](../../../technical/GEN6_AI_DOCUMENT_INDEX.md)。**


日期：2026-09-09。状态：建议稿，未将建议升级为已批准需求或已验收能力。

## 1. 本轮明确的目标与审查范围

用户明确首版面向算法工程师本地/内网使用，覆盖数据分析、仿真验证、证据报告。
用户明确 DDD 指 Document-driven development：需求、设计、实现、验收保持一致。
本轮由三个子 agent 分别检查文档契约、实际交付链路和工程质量，主 agent 汇总并抽样验证。
不执行远端回放、构建、GDB 或生产写入，不修改实现与现有基线。

审查基于工作树 HEAD `2a2e87efa87223625bb4e556f8d788f1c6181b4f`。
开始时工作树已有案例报告、记忆数据库修改和大量未跟踪分析脚本；这些内容没有被清理或覆盖。
因此本轮结果是当前工作树的抽样审查，不是干净 release commit 的全面认证。

## 2. 核心判断

当前项目已有可用的证据与报告底座，但本轮证据不足以支持“可由另一位工程师独立安装、完整运行并可靠恢复的数据仿真分析产品已经交付”。
首版应收敛一条真实用户旅程，并完成可信度、执行恢复和安装验收，而不是继续增加能力数量。

应保留：Pi 唯一产品入口、原子能力注册、外部 harness/arbe 窄 adapter、variant 隔离、
静态与 runtime 证据分层、AlertTimeline、ConditionTrace、Hypothesis/Experiment ledger、报告投影。
其中多项已在代码及 2026-09-01 handoff 中存在，不能再当作“待新增功能”列计划。
AI 继续负责跨代码、数据、需求和案例的假设推理；确定性条件检查只提供证据标注。

## 3. 当前发现及证据边界

| ID / 优先级 | 已观察事实与来源 | 对交付的影响 | 建议验收 |
|---|---|---|---|
| REV-01 / P0 | `core/knowledge_guard.py:63-76` 在 manifest 未放行后继续根据 stale flags 判断。variant + `freshness={available: True}`，缺 manifest 和签名时，接口实际返回 `allowed=True` | 不满足无法自证新鲜即拒绝的知识消费约束；尚未证明日常 CLI 必然触发或已经污染实际诊断 | 缺失/损坏 manifest、缺 scope、签名不符、刷新失败均不能进入真实 AI prompt；成功发布 scope 可用 |
| REV-02 / P0 | `core/diagnosis_bundle.py:246` 仅凭 evidence 与 code localization 升级 confirmed；`ai/orchestrator.py:2718-2730` 从模型 summary 正则提路径后调用升级。`engines/diagnostic_report.py:1029` 使用更保守的结论 envelope | 同一产品不同可达路径的“根因已确认”语义不一致。静态调用链已确认，未重跑完整旧 diag | 所有入口共用一份发布契约；路径、证据条数不能单独确认根因；保留充分推理空间及候选，不将未知判失败 |
| REV-03 / P0（发布门） | `harness/harness_runner.py:203-217` 读取现成 report.md；`tools/run_harness_gate.py:47-53` 汇总这些评估。零案例没有明确失败条件 | 旧报告通过不等于当前版本主链路通过 | 保留报告质量门，另加从输入重新生成本次产物的 journey gate；零样本、缺必测场景、旧输出都失败 |
| REV-04 / P1 | `harness/harness_runner.py:79-86` 缺 L2 按零计分，L0/L1 满分仍可达到 0.6 并通过；子 agent 纯内存复现 | 不适合独立证明 AI 根因判断质量 | 区分证据交付、运行完成、AI 效果三个结果；声称 Top-3 能力时必须有专家标注及盲测 |
| REV-05 / P1 | DDD 基线 US-024 明确全流程仍待现场验收（`:530-549`）。Pi bridge 默认关闭副作用是已存在的保护；持久化 run 已实现 | 缺的是确认、执行、恢复、报告的真实闭环证明 | 仅从 Pi 完成计划确认与运行；拒绝零副作用；重开继续原 run；不重复已完成动作 |
| REV-06 / P1 | `ai/modules/sim_verify.py:249-309` 在该入口 capture 前检查路径/批准，preflight/source context 在 capture 后参与归一化 | 执行前计划与当前 source/binary/session 的匹配约束不充分；不能据此断言所有上层入口均无保护 | 执行前重核 data/source/binary/config/session 与计划绑定；变化即阻止该次执行 |
| REV-07 / P1 | `engines/arbe/remote_replay.py:262-273` 使用传入 capture base 清理旧文件并启动 recorder，生成命令没有 trap；真实中断清理未实测 | 重试可能覆盖已有证据，中断后资源归属和恢复未证明 | run/attempt 独立输出；保留已有产物；仅清理 tool-owned 进程；fetch 失败支持复取而非重播 |
| REV-08 / P1 | `engines/analysis_ledger.py:524,579` 顺序保存 step/event/run；`:604,641` 校验 run 状态枚举但未形成完整完成门 | 单文件原子写不等于多文件调查状态原子提交；属于静态风险，未做崩溃复现 | 各提交边界故障注入；重启对账；完成时无悬挂执行且交付 artifact 已登记；诊断仍可带 gaps |
| REV-09 / P1 | README `:142-146` 说明尚非零配置安装；requirements 使用 `>=`；`ai/providers/cr60_harness.py:313-323` 检查 sibling 路径而非完整兼容版本 | 新机器安装与外部系统兼容性未证明 | 发布受测依赖组合、自动体检、版本与 schema 检查；另一工程师在干净机器完成样例 |
| REV-10 / P1 | DDD 基线 `:684` 将 US-001 定义为 intake，9/1 gap review `:168` 却把文件夹批量写成 US-001/AC-001 | 同 ID 不同含义，测试覆盖容易被错误回链 | 现有 DDD baseline 作为唯一编号来源；局部审查编号加前缀或映射，不复制出竞争需求 |

次级维护项：根 AGENTS 中 V4 决策文档链接应指向 `docs/technical/`；
`engines/AGENTS.md` 的纯确定性边界与部分 router/执行 adapter 的实际职责需对齐。
首版不建议为了目录形式进行大规模架构搬迁。

## 4. 建议的首版交付合同

以下为建议，需在实施前合入现有需求基线，不能视为已经批准的新范围。

用户给出数据目录和一个业务问题；系统自动解析可获取的身份、源码与数据上下文，
生成初步证据；如问题需要仿真，给出可审阅的执行计划，经业务授权后在已配置环境运行；
最后交付可离线打开的逐数据报告、批次索引和机器可读证据。
再次打开产品可以继续同一调查，失败或资料不足也有明确的阶段结果。

交付包至少包括：

- 批次索引：完整数据名称、状态、事件数、失败分类和报告入口。
- 单数据报告：问题、数据/代码/二进制绑定、关键曲线和场景、事实与推断、候选根因、反证、缺口及下一步。
- 证据包：输入 hash、真实 token/source locator、单位/坐标/帧域、runtime 层别和 artifact hash。
- 仿真记录：明确策略、预热窗口、计划/批准、执行身份、耗时、输出与清理结果。
- 调查记录：run/attempt/step、可恢复点、错误原因和可操作的续作方式。
- 安装与支持材料：受测版本矩阵、体检结果、样例、故障排查和已知限制。

首版建议只承诺一个已准备好的项目/车型/数据格式/回放策略组合。
未进入受测矩阵的能力可以保留，但显示 experimental/unsupported，不能隐式宣称全部 Gen6、
全部格式、全部功能或 point-cloud/SGU 策略均完成验收。
正式 PID attach、自动修源码、自动调参、多用户调度是否进入首版，需要单独业务需求支撑。

建议将“准备好的 arbe 环境中完成回放”作为首版闭环；全自动 checkout/CUDA/patch/build 的 US-024
更大范围可保留后续阶段。此项属于范围收敛建议，不能无文档决策自行删除已有需求。

## 5. 按文档驱动开发组织落地

继续使用 `CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md` 作为唯一 US/FR 编号基线。
本文件是审查输入，不替代 PRD、设计、开发计划或验收记录。

每个切片先完成以下链路，再实现：

`US/FR → 可执行 AC → 设计与契约 → 实现位置 → 测试/真实运行 → artifact+hash → 验收状态`

AC 需要写明 Given/When/Then、失败与降级、证据成熟度、允许的副作用、性能测量方法。
沿用现有 specified/implemented/partially-verified/accepted/blocked，不用测试数量代替 accepted。
建议在现有文档旁增加一个小型机器可读验收索引，字段至少包含：

```text
release_id, baseline_version, workspace_commit, working_tree_state
requirement_id, acceptance_id, required_for_release
test_or_run_id, reproducible_command, environment_fingerprint
input_fingerprints, artifact_path, artifact_sha256
result, evidence_level, known_gaps, reviewer
```

自动校验编号引用唯一、必测场景齐全、artifact 存在/hash 匹配、来源属于本次 release。
无需引入复杂需求管理平台；先让一份索引驱动发布检查。

## 6. 建议实施顺序与退出条件

| 阶段 | 工作 | 退出条件 |
|---|---|---|
| M0：冻结首版合同 | 对齐需求编号，选定一个受测组合，明确报告承诺和成功/失败判据 | 每项必交结果有唯一 AC、预期证据与负责人；后续范围显式列出 |
| M1：可信证据 | 修复 freshness 放行与跨入口根因升级差异，补消费端与跨入口测试 | stale、缺值、身份冲突、模型伪造路径等反例不能造成虚假确认；候选推理仍可正常输出 |
| M2：交付一条闭环 | 串接现有 Pi、静态证据、计划确认、公共回放、报告；补 attempt/恢复 | 工程师不手拼内部命令即可完成真实数据旅程；中断与重试不破坏已有证据 |
| M3：发布验收 | 锁版本、体检、干净机安装、真实 journey gate、专家验收 | 另一工程师按材料独立完成；必需 AC 全部有本次版本证据 |
| M4：有证据地扩展 | 增加第二个异构项目/格式/策略，随后评估高级 debug 或环境准备自动化 | 新适配不修改核心编排、无跨项目污染，原验收集继续通过 |

不在缺少团队容量和真实数据规模时承诺工期。先测量一个完整闭环，再以工作量排期。

## 7. 发布场景与效果评估

建议首个发布验收集至少覆盖下列场景类型；具体数量和门槛须在 M0 冻结：

1. 正常数据和已知正常报警：避免把正确功能行为说成异常。
2. 专家已确认问题：检验事实提取、候选排序与复验是否支持正确解释。
3. 无报警或无目标：仍有可用报告，不伪造目标或报警事件。
4. 缺代码/DBC/内部量：给出可用子集、缺口和能力边界。
5. 数据/source/binary 或知识签名冲突：受污染信息不可用于结论。
6. 文件夹中单条损坏：其他数据仍完成，索引有失败分类。
7. 仿真被拒绝、超时、SSH 中断、录制挂起、结果获取失败：授权和恢复行为分别验收。
8. Pi/LLM 不可用或用户重开任务：已有证据可读，运行状态可恢复。

AI 效果用独立专家标注集和留出数据评估，避免只记住 CRGVI-1829 等演示案例。
指标建议分开统计：事件/目标/帧关联正确性、溯源完整性、无依据确认数、
Top-3 命中率、应拒答场景的缺口表达、人工纠正次数及完成时间。
无依据确认和身份错配属于硬失败；对确实证据不足的正确拒答不能按“没有猜出根因”处罚。
耗时统计区分首次学习、缓存命中、解析、回放、LLM、报告；记录峰值内存和数据规模。
性能目标应由真实样本测量后冻结，不在本次审查凭空承诺秒数。

## 8. 本轮验证结果

主 agent 执行：

```powershell
python -m pytest tests/test_harness_gate.py tests/test_diagnostic_report_identity.py tests/test_analysis_ledger.py tests/test_freshness.py tests/test_pi_tool_bridge.py -q
```

结果：`46 passed, 1 failed in 52.97s`。
失败：`test_hypothesis_state_history_and_user_confirmation_gate`，
`engines/analysis_ledger.py:153` 的 `os.replace` 返回 `PermissionError: [WinError 5] Access is denied`。

单独复跑该用例：`1 passed in 4.81s`。未定位首轮文件访问失败的根因；
不能改写为首次全通过，也不能断言是稳定业务缺陷或杀毒软件造成。
本轮仅做调研，因此记录问题而未直接修改实现。

主 agent 另以纯内存配置调用 `runtime_knowledge_decision`，复现 REV-01：

```python
runtime_knowledge_decision(
    {"identity": {"variant_id": "review_variant", "freshness": {"available": True}}},
    "conditions:RCTA",
)
# KnowledgeDecision(category='conditions:RCTA', allowed=True, reasons=())
```

上述测试不是完整回归，不证明真实远端回放、安装或所有 Pi 调用均已完成验收。
9/1 文档中的历史真实运行记录只作为历史证据，没有被标为本轮复测结果。

## 9. 主要依据

- `docs/archive/2026-09-17/technical/CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md`：唯一需求编号与验收基线，特别是 US-024 和 DoD。
- `docs/archive/2026-09-17/technical/V4_DESIGN_CONTEXT_AND_DECISIONS.md`：既有用户故事、Pi 入口与数据准确性决策。
- `docs/archive/2026-09-17/technical/CR60_PI_UNIFIED_DDD_GAP_REVIEW_2026-09-01.md`：已有缺口分析；其中局部编号需与基线对齐。
- `docs/archive/2026-09-17/technical/CR60_PI_UNIFIED_HANDOFF_2026-09-01_DDD_GAP_REVIEW.md`：已有实现与历史验证范围。
- 各发现行所列当前工作树源码，以及本轮抽样测试输出。

最优先的建设方向：用现有底座交付一条别人能独立完成、出错能恢复、结论能核验的真实工作流程。
