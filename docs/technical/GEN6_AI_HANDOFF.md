# Gen6 AI：最新开发 Handoff

更新：2026-09-17 · S0 完成；T10（S1 首切片）本地部分已实现并验证，real-data 验证待服务器恢复。

## 当前恢复入口

- 目标：按唯一 DDD 套件交付首期 M01～M12；不是只完善文档或报告。
- 首读：[索引](GEN6_AI_DOCUMENT_INDEX.md) → [执行规范](GEN6_AI_EXECUTION_PROTOCOL.md) → [Sprint](GEN6_AI_SPRINT_PLAN.md) → [任务状态](gen6_execution_state.v1.json) → [验收清单](release_acceptance.v1.json)。
- 当前计划：T10「bag+问题到版本车型绑定」本地切片完成（status=verifying，current_task=T10）；待用户服务器恢复后补 real-data/Pi-product 验证，之后进入 T11/T12。
- 用户决策：① 本地开发授权（2026-09-17）；② 真实案例数据在 arbe 服务器上，本地 `cases/` 非真实数据；③ 服务器网络问题用户后续处理，先做其他开发任务。
- T00 结果（V 级）：分支 `codex/ros-debug-autonomous` @ `2a2e87e`；dirty 292 条（sha256 前缀 `e75d6eef`）；41/41 模块落点存在；doctor ready（Python 3.12.10，failures=0，lock_mismatches=0）；capabilities CLI 0（68 能力）；证据 `docs/technical/evidence/gen6_t00_baseline_audit_20260917.json`。
- T01 结果（V 级）：
  - `release_acceptance.v1.json` 16/16 AC 登记 `validation_plan`（层级/输入/判据/命令或步骤）；15 项登记真实命令并逐一实跑验证（全部 exit 0，最长 90s < gate 默认 300s）；G6-AC13 纯 browser/UX 诚实留空 command，待 T52 runner。
  - `GEN6_AI_ACCEPTANCE.md` §5.1 登记人工耗时基线计划（5 步计时口径、≥2 工程师 × ≥2 案例、阈值试测后版本化）。
  - plan-only gate 保持诚实 blocked 0/16；command_missing 仅 AC13。证据 `docs/technical/evidence/gen6_t01_acceptance_assets_20260917.json`。
- 本轮代码/测试变更：`tests/test_ddd_governance.py::test_dependency_cycle_and_evidenceless_completion_are_rejected` 的过期假设修复——原测试依赖"T00 无证据"的初始状态；T00 合法完成后假设失效。修复方式：变动副本显式清空 evidence 再断言校验器行为，保持原意图且不再依赖真实任务状态；修复后 4 passed。
- 本轮相关回归：`python -m pytest tests/test_ddd_governance.py tests/test_release_acceptance.py -q` → 1 failed（即上述过期假设）+ 8 passed；修复后 governance 4 passed（2.1s），release_acceptance 5 项在合并跑中已在新 manifest 下通过。`python tools/check_ddd.py` → 0 错误。
- T10 本地切片（2026-09-17，证据 `gen6_t10_taskcard_20260917.json`/`gen6_t10_intake_binding_20260917.json`）：
  - 新增 `engines/arbe/intake_binding.py` + `contracts/cr60-intake-binding.v1.schema.json`：intake 身份→variant 确定性绑定（case 元数据 > 显式/intake 身份匹配 > 单项目自动复用），版本/分支与项目期望不一致 → blocked（错版本不进入 runtime），歧义/缺失/缺版本 → 业务语言 `business_questions`（不含技术 token）。
  - `ai/modules/pi.py` 接线：case_analysis 且存在数据/材料输入时，模型调用前执行绑定门；`needs_confirmation/blocked` 返回业务问题并保留 run（partial）可恢复；resolved 时 variant_id 进 context、`intake_handoff_id/intake_binding_status` 进 run binding；CLI 新增 `--intake/--material/--match-text`。
  - 设计裁决：纯对话（无数据输入）不触发绑定门（回归中发现并修复）；版本已知但版本→分支映射未配置 → 记诊断不问用户（不把技术映射抛给用户）。
  - 测试：新增 `tests/test_intake_binding.py`（15）+ `tests/test_pi_intake_binding_gate.py`（6）；AC01 命令 52 passed；消费方回归 100 passed（pi_tool_bridge/cli_capabilities/cli_module_dispatch/modules_standalone）；governance+release_acceptance+新测试 30 passed；check_ddd 0 错误。
  - 未升级任何 AC status；G6-AC01 real-data/Pi-product 层级待服务器恢复后按 T01 validation_plan 补做。
- 所有权边界：既有 292 条 dirty 均为先前工作，本轮未 stash/reset/clean/checkout/commit/push。本轮自有文件：`docs/technical/evidence/`（t00/t01/t10/remote_probe/taskcard 5 份）、`docs/technical/release_acceptance.v1.json`（validation_plan/command 增量）、`docs/technical/gen6_execution_state.v1.json`（T00/T01 done、T10 verifying）、`docs/technical/GEN6_AI_ACCEPTANCE.md`（§5.1/§6）、`docs/technical/GEN6_AI_HANDOFF.md`、`docs/technical/GEN6_AI_CURRENT_STATE.md`（远端实测事实）、`tests/test_ddd_governance.py`（一处过期假设修复）。其余 dirty 不可碰。
- T10 本轮新增代码：`engines/arbe/intake_binding.py`、`contracts/cr60-intake-binding.v1.schema.json`、`tests/test_intake_binding.py`、`tests/test_pi_intake_binding_gate.py`、`ai/modules/pi.py`（绑定门接线）；AGENTS 同步三处（根依赖表/engines/ai.modules）。
- 授权：本地开发已授权；远端执行（SSH/回放/GDB/编译）、push/merge 未授权；缺数据保留 todo/blocked 不伪造。
- 远端事实（2026-09-17 只读探测，证据 `docs/technical/evidence/gen6_remote_probe_20260917.json`）：`10.190.171.44` 网络层不可达（TCP22 超时；ICMP 由本机栈 `10.190.167.85` 报 Destination host unreachable = 本机路径无路由/ARP，非主机拒绝）；与 09-15 preflight 超时一致。**用户确认：真实案例数据在该服务器，本地 `cases/` 非真实数据** → T10/T11 的 real-data 验证 blocked 待服务器恢复；本地实现与 fixture 验证可继续。
- 待用户确认：服务器是临时不可达（会恢复）还是 IP/主机已变更；恢复后是否授权只读 preflight 级 SSH 探测。
- 进程/资源：本轮未启动长驻进程，无清理义务。
- 下一步（最多三项）：
  1. T11（依赖 T10 完成）：四雷达事件及数据索引——本地部分可与 T10 收尾并行准备（含 G7 intake 数据指纹与 case_dir 实际文件比对）；注意 T10 尚在 verifying，不并行开第二个主切片；
  2. 服务器恢复后（用户提供地址/授权）：真实案例 case.yaml/材料 → `python cli.py pi "..." --case-dir ...` 走绑定门 integration 验证 + Pi-product 会话证据，补 G6-AC01 real-data 层级，T10 收敛为 done；
  3. 继续 T12（授权/attempt/隔离基础，依赖 T10）前先核对 T10 收敛状态。

## 每次更新必须保留的内容

1. 当前 task/Sprint、需求/AC、最后已完成的用户可见行为。
2. 实际 cwd/branch/HEAD、基线 dirty 指纹、本轮自有文件/commit/patch、不可碰的他人变更。
3. 测试命令/结果/证据路径与层级；未测项和原因，不能只写“全部通过”。
4. 接口/设计决策变化、生产/消费方待办、发现的反证或失败尝试。
5. 当前进程/远端 session/资源所有权、清理状态、授权范围及过期条件。
6. blocker、已尝试替代方案、等待谁/什么；仍可继续的独立工作。
7. 下一步最多三项具体动作和验证预期；禁止“继续优化”式空泛交接。

任务状态和 AC 状态从 JSON 引用，不在 handoff 复制一套表。每个切片与中断前刷新；历史快照可落 evidence，但不在当前目录增加第二份计划。
