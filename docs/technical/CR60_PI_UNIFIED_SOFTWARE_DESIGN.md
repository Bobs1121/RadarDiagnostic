# CR60 统一平台软件设计

版本：`software-design.v2.3`  
日期：`2026-09-01`  
前置：[调研报告](../CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md)  
关联：[系统设计](CR60_PI_UNIFIED_SYSTEM_DESIGN.md) · [模块设计](CR60_PI_UNIFIED_MODULE_DESIGN.md)

## 1. 软件设计原则

### 1.1 三件套能力模型

每一项对 Pi 暴露的业务能力由三部分组成，Pi Extension 是产品侧唯一入口：

```text
Engine
    确定性实现，负责事实和算法

BaseTool
    Pi/Agent 可调用的 JSON-in/JSON-out 接口

BaseModule
    CLI/API 独立入口、参数解析、ModuleResult 包装

Pi Extension / registerTool
    由 catalog 自动生成的 Pi 原生工具声明；execute 只转发 JSON 到
    ai/capability/pi_tool_bridge
```

Provider 是 Engine 与外部系统之间的实现适配层，不能把 SSH、ROS、GDB 细节泄漏到业务模块。

### 1.2 依赖方向

```text
Pi (registerTool)
    → pi_tool_bridge
        → BaseTool.safe_execute / BaseModule adapter
            → Engine / Provider interface
                → external system
```

禁止：

- harness import radarAnalyze 内部 orchestrator；
- arbe 源码 import radarAnalyze；
- Pi prompt 直接拼接任意远程 shell；
- HTML 反向作为事实输入；
- 模块共享可变全局状态。

### 1.3 原子工具边界

当前已落地的原子能力不形成隐式业务调用链；组合关系只由 Pi/typed composition
表达：

```text
public-topic-plan / public-evidence-audit
        └─ 只读公共证据描述和审计
code-analyze / code-gdb-plan
        └─ 只读当前源码，生成函数/变量/条件和 GDB 指令
gdb-service
        └─ 只接收 target + commands；不认识报警功能，不内置断点
```

`gdb-service` 的 `execute=false` 是规划态；执行态必须同时具备显式 `approved=true`，
并记录 target、source/binary provenance、argv、stdout/stderr、结构化 `observations`
和 teardown 状态。`observations` 只归一化 GDB 实际打印的 stop/backtrace/args/locals/
expressions，并把 `<optimized out>`、`No symbol` 等不可用状态保留为 diagnostics；代码
分析输出的 GDB 指令只是当前 source-index 下的候选，不能越过 source/binary identity
gate 直接执行；函数入口局部变量的作用域风险必须保留。

`pi-context` 生成 `pi-orchestration-context.v1`，是 Pi 工具组合的显式上下文输入。
它保留 upstream provenance、fingerprint、freshness、missing/conflicts 和 policy；
工具可以追加 artifact ref，但不能覆盖身份和 source/binary 绑定。

## 2. 推荐目录结构

### 2.1 radarAnalyze

```text
radarAnalyze/
  ai/
    modules/
      pi.py
      pi_context.py
      cr60_precheck.py
      cr60_runtime_debug.py
      arbe_control.py
      geometry_evidence.py
      evidence_merge.py
    tools/
      cr60_tools.py
      arbe_tools.py
      runtime_debug_tools.py
      evidence_tools.py
    orchestration/
      run.py
      state_machine.py
      checkpoints.py
      approval.py
      recovery.py
    providers/
      cr60_harness_adapter.py
      remote_arbe.py
      ros_replay.py
      gdb_mi.py
    capability/
      registry.py
      tool_bridge.py
      pi_tool_bridge.py
      project_context.py
  contracts/
    cr60-analysis-intake.v1.schema.json
    analysis-context.v1.schema.json
    runtime-debug-plan.v1.schema.json
    arbe-source-resolution.v1.schema.json
    arbe-cuda-resolution.v1.schema.json
    arbe-patch-plan.v1.schema.json
    cr60-data-prep-verification.v1.schema.json
    cr60-data-transfer-session.v1.schema.json
    analysis-run.v1.schema.json
    analysis-step.v1.schema.json
    claim.v1.schema.json
    hypothesis.v1.schema.json
    debug-experiment.v1.schema.json
    user-observation.v1.schema.json
    event-code-path.v1.schema.json
    project-capability-manifest.v1.schema.json
    runtime-trace.v1.schema.json
    orchestration-run.v1.schema.json
    pi-orchestration-context.v1.schema.json
```

### 2.2 cr60-debug-harness

```text
cr60-debug-harness/
  cr60_debug_harness/
    parsers/
    source_analysis/
    geometry/
    bundle/
    viewer_model.py
  tools/
    build_html_reports.py
  web/
  docs/
  skill-dist/
```

它继续独立发布和运行；radarAnalyze 只调用公开 CLI/contract。

## 3. 核心数据模型

### 3.1 `RunContext`

```python
RunContext(
    run_id: str,
    owner: str,
    project_id: str,
    variant_id: str,
    profile_id: str,
    input_fingerprint: str,
    source_context_id: str,
    data_paths: list[str],
    harness_root: str,
    remote: dict,
    arbe: dict,
    vehicle: dict,
    permissions: dict,
    output_root: str,
)
```

`RunContext` 不保存密码和私钥内容，只保存 key reference/credential profile 名称。

### 3.2 `ToolResult`

```json
{
  "schema_version": "tool-result.v1",
  "status": "succeeded",
  "message": "...",
  "data": {},
  "artifacts": [],
  "provenance": [],
  "diagnostics": [],
  "next_actions": [],
  "requires_approval": false
}
```

状态至少包括：`pending`、`ready`、`running`、`succeeded`、`partial`、`blocked`、`failed`。

### 3.3 `ArtifactRef`

```json
{
  "artifact_id": "artifact-...",
  "kind": "diagnosis_bundle",
  "path": "...",
  "sha256": "...",
  "producer": "cr60_sprint1_precheck",
  "schema_version": "diagnosis-bundle.v1",
  "run_id": "...",
  "source_context_id": "..."
}
```

下游工具只通过 artifact reference 读取产物，不依赖上游模块的内存对象。

## 4. 版本化契约

### 4.1 `cr60-analysis-intake.v1`

包含：

- `handoff_id`；
- source data entries；
- TR/问题单；
- original path/remote path；
- file size/hash/format；
- user-confirmed server/workspace；
- vehicle/COEM/tag/CUDA decision；
- `downstream.harness_profile`；
- `status` 和 `diagnostics`。

### 4.2 `analysis-context.v1`

包含：

- outer arbe identity；
- algo_source identity；
- branch/commit/dirty；
- source snapshot root/hash；
- code index path/hash；
- runtime schema path/hash；
- message contract；
- vehicle/profile identity；
- freshness status。

### 4.3 `runtime-debug-plan.v1`

```json
{
  "schema_version": "runtime-debug-plan.v1",
  "run_id": "...",
  "mode": "sgu_injection",
  "hilmodel": 2,
  "replay": {
    "point_cloud_warmup_frames": 0,
    "feature_state_warmup_frames": 0,
    "target_frame": 47877,
    "post_window_frames": 30
  },
  "target": {
    "event_id": "...",
    "radar_id": 2,
    "radar_pos": 1,
    "obj_id": 44,
    "raw_sgu_index": 0,
    "algorithm_object_index": 0
  },
  "breakpoints": [],
  "capture_fields": [],
  "binary_identity": {},
  "source_identity": {},
  "permissions": {}
}
```

### 4.4 `runtime-trace.v1`

每一条 snapshot 包含：

- `run_id`、`session_id`、`event_id`；
- `frame_counter`、`wfAutosarData.frameID`、ROS timestamp；
- `radar_id`、`radar_pos`；
- raw SGU/algorithm/objectlist index；
- `objID`；
- function/file/line/PC；
- args/locals/globals；
- call stack；
- `objPoly`/ROI；
- GDB stop reason；
- value status、unit、source ref；
- timeout/dropped/perturbation。

## 5. Provider 接口

### 5.1 `Cr60HarnessProvider`

```python
class Cr60HarnessProvider(Protocol):
    def precheck(self, request: PrecheckRequest) -> ToolResult: ...
    def refresh_report(self, request: ReportRequest) -> ToolResult: ...
```

实现方式优先为：

```text
subprocess → python -m cr60_debug_harness.cli → JSON/artifacts
```

不直接 import harness 内部包，避免依赖树和 Python 环境冲突。

### 5.2 `ArbeProvider`

```python
class ArbeProvider(Protocol):
    def preflight(self, context: RunContext) -> ToolResult: ...
    def resolve_version(self, context: RunContext) -> ToolResult: ...
    def resolve_cuda(self, context: RunContext) -> ToolResult: ...
    def build_plan(self, context: RunContext) -> ToolResult: ...
    def apply_plan(self, context: RunContext, approval: Approval) -> ToolResult: ...
    def build(self, context: RunContext, approval: Approval) -> ToolResult: ...
    def start(self, context: RunContext, approval: Approval) -> ToolResult: ...
    def stop(self, context: RunContext, session_id: str, approval: Approval) -> ToolResult: ...
```

当前只读版本/车型绑定接口：

```python
def resolve_source(..., requested_ref, software_version, ref_prefix,
                   version_suffix_strip, remote_query, execute) -> dict: ...

def resolve_cuda(..., algo_source_root, vehicle, expected_sheet,
                  preflight, execute) -> dict: ...
```

`resolve_source` 的 `execute` 只执行 git identity/ref 观察和可选
`ls-remote`，不 fetch/checkout；`resolve_cuda` 的 `execute` 只扫描当前 source 的
`08_CustData` 并读取 launch YAML，不 cp/写配置。它们的具体机器契约是
`arbe-source-resolution.v1` 和 `arbe-cuda-resolution.v1`。二者提供的是“当前事实”和
“写入前输入”，不是 branch/CUDA 变更本身；写入能力必须在同一 PiRunContext 中重新做
source dirty/fingerprint 和 approval gate。

Provider 可以调用现有 skill 脚本，但返回统一结果。

### 5.3 `ReplayProvider`

```python
class ReplayProvider(Protocol):
    def prepare(self, plan: RuntimeDebugPlan) -> ToolResult: ...
    def start(self, plan: RuntimeDebugPlan) -> ToolResult: ...
    def pause(self, session_id: str) -> ToolResult: ...
    def resume(self, session_id: str) -> ToolResult: ...
    def status(self, session_id: str) -> ToolResult: ...
    def stop(self, session_id: str) -> ToolResult: ...
```

实现：`SguInjectionReplayStrategy`、`PointCloudReplayStrategy`、后续 `FormalPlayerReplayStrategy`。

### 5.4 `GdbProvider`

```python
class GdbProvider(Protocol):
    def preflight(self, target: DebugTarget) -> ToolResult: ...
    def launch_under_gdb(self, plan: RuntimeDebugPlan) -> ToolResult: ...
    def attach(self, plan: RuntimeDebugPlan) -> ToolResult: ...
    def install_probes(self, plan: RuntimeDebugPlan) -> ToolResult: ...
    def capture(self, plan: RuntimeDebugPlan) -> ToolResult: ...
    def detach(self, session_id: str) -> ToolResult: ...
```

GDB 输出先落盘 JSONL/日志，再由 `RuntimeTraceNormalizer` 归一化。

## 6. GDB 采集实现约束

### 6.1 断点来源

断点必须来自：

```text
当前 source schema
    + 当前 event
    + 当前 function signature
    + 当前 variable scope
```

不使用固定 `FCTA/FCTB` 字符串替代解析。

### 6.2 采集层级

```text
Level 0  symbol/process preflight
Level 1  function entry + frame/object identity
Level 2  local args/locals + call stack
Level 3  objPoly/adasRoi/temporary calculations
Level 4  continuous trace/ring buffer/debug probe
```

先完成 Level 1/2，再增加 Level 3；Level 4 可能需要 arbe feature branch 的默认关闭 probe。

### 6.3 编译要求

GDB runtime 能力必须记录：

- DWARF/debug symbol 状态；
- `file`/ELF 是否 stripped；
- 编译优化级别；
- source/binary hash；
- `<optimized out>` 字段；
- GDB 版本和命令。

没有 debug symbols 时只允许生成手工断点计划，不允许输出 runtime 变量已读取。

## 7. Runtime evidence producer/consumer 实现

### 7.1 原子接口

```python
normalize_runtime_evidence(
    payload=None, *, transcript="", stderr="", commands=None,
    run=None, binding=None, marker_field_map=None, artifacts=None
) -> dict

validate_runtime_binding(bundle, evidence) -> dict
match_runtime_observations(bundle, evidence) -> list[dict]
merge_runtime_evidence(bundle, evidence) -> dict
runtime_summary(evidence, merge=None) -> dict
```

`normalize_runtime_evidence` 可以接收现有 `gdb-session.v1`、原始 transcript 或已生成的
`runtime-case-evidence.v1`。标准化后的 observation 统一携带 identity、真实字段 token、
value/status/phase/source、call chain、geometry 和 diagnostics。未知字段不会被删除，
缺失值不会被填为零。

### 7.2 绑定和合并不变量

1. `source_context_id`、`source_snapshot_hash`、数据路径和 binary identity 分开比较；
2. `event_id` 优先，其次必须同 radar + `frame_id`，有 object identity 时再核对 object；
3. 时间邻近只产生 diagnostics，不建立事件绑定；
4. identity conflict 时 `runtime_merge.status=blocked` 且事件 overlay 引用为空；
5. binary 指纹缺失为 `partial`，允许可见地展示已采集值，但不能声明完全 parity；
6. static bundle 的 alarm/frame/target 值不可被 runtime 覆盖，runtime 只在新 namespace
   `runtime_evidence`/`runtime_merge`/`runtime_overlay` 中出现。
7. 多个 runtime producer 通过 `compose_runtime_evidence` 叠加，保留每个 run/layer/observation；
   同一 identity/token/phase 的重复值才进入 comparison，差异不得自动选边。
8. GDB/回放 command error、非零 play code 和 warning 输出变化进入 `disturbance`/diagnostics；
   其中 `No symbol`/`optimized_out` 只代表字段不可见，只有 ptrace/attach、内存、runner/
   rosbag 或 GDB script 等强错误才升级为 replay disturbance，避免把缺字段误判成回放被扰动。

### 7.3 Pi 和 HTML 消费

`runtime-evidence-validate` 只读返回 gate；`runtime-evidence-merge` 产生新 bundle；
`cr60-debug-harness.viewer_model` 在同一 `frame_id` 上投影 runtime fields、before/after、
call chain、`objPoly`/ROI 和动态量，没有同帧 runtime 观察时显示缺口且不沿帧复用。
`pi-context` 使用 `runtime_summary` 作为确定性输入，保存 runtime artifact ref、binding
状态和 diagnostics；若没有 intake/case_dir，可从已校验 diagnosis bundle 的显式
`case.bag`、`provenance`、`source_context.identity` 继续构建 context，并从显式 debug
plan 读取 strategy/radar。解释层只引用事实，不改写事实；所有 bundle 派生字段保留
provenance。

`runtime-debug-plan.v1` 是执行前的独立契约：输入当前 diagnosis bundle 和可选
`arbe-preflight.v1`，输出选定事件、replay/warm-up、target/index、readiness gates、
`gdb_commands`、`capture_fields`、`vscode_handoff`。它不执行副作用；Pi 只有在 gate 和
approval 满足后，才能把其中的 commands typed-ref 给 `gdb-service`。HTML 只展示这个
artifact，不重新计算断点。

`runtime-debug-run` 是执行侧 adapter：它只接受已校验的 plan artifact、profile、bag 和
目标 frame/radar，默认返回 sibling harness 的 `shell=False` argv；只有
`execute=true + approved=true` 才启动隔离 ROS/GDB，并将原始结果写成 `gdb-session.v1`。
它不负责切分支、改 CUDA、编译或替代正式 `bash start`；这些动作由独立 provider 和审批
阶段负责。

`runtime-debug-attach` 是正式工作区 existing-PID 路径：它不启动或停止 arbe，只重新发现
`/radar{radar_id}_visualization_engine/arbe_visualization_engine`，校验 node PID 与
`/proc/<pid>/exe`，然后将同一 source-bound plan 交给 GDB。`arbe-formal-start` 和
`arbe-formal-stop` 是独立 lifecycle 原子模块；start 记录 `arbe-start-session.v1` 的
ownership/process group，stop 只处理该 ownership 且远端再次验证 PGID/命令行的 session。

### 7.4 当前真实样例的已知状态

`CRGVI-1829` runtime merge 现在为 `partial`，原因是静态 bundle 尚无 binary fingerprint
且 data fingerprint 采用不同表示；source context、source snapshot、bag 路径已经一致。
这是一种明确的证据状态，不是失败，也不是 production parity 声明。正式 `bash start`
已有节点保护、ROS node/PID/executable 定位和 attach blocked 语义已经在现场验证；当前
`ptrace_scope=1` 仍阻止该 SSH 用户态 GDB 取得正式 PID runtime 变量，正式 GUI player
parity 和最终 CAN Tx 仍属于后续验收。

## 8. 几何软件实现

### 7.1 自车

自车矩形不是算法内部一定存在的 `polygonStruct`，应根据当前 runtime/profile 参数构造，并标记 `derived_from_runtime_params`：

```text
origin = source-defined ego reference
front_x = bumper2RearAxle_dist
rear_x = bumper2RearAxle_dist - vehicle_length
left_y = +vehicle_width / 2
right_y = -vehicle_width / 2
```

如果当前车型/坐标原点没有证据，返回 `coordinate_contract_missing`。

### 7.2 目标

优先直接采集运行时 `objPoly.points[]`。如果没有运行时变量，才使用当前 source snapshot 重建 `adasObjPloyCal`，并标记 `derived_from_active_source`。

### 7.3 ROI

优先采集运行时：

```text
adasRoi->leftFctaRoi
adasRoi->rightFctaRoi
```

静态 source evaluator 只处理当前源码中可证明的简单表达式；弯道 helper、状态依赖和宏链不强行求值。

### 7.4 碰撞判断

`geometry_collision_evaluate` 对同一坐标契约下的 polygon/ROI 输出带证据前缀：runtime 同帧为
`observed_*`，源码公式重建为 `source_derived_*`；只有缺少可比 polygon/ROI、坐标语义或身份时
才保留 `not_evaluated` 和原因。任一几何关系都不能替代功能分支和 CAN Tx 结论。

## 9. 状态机和恢复

每个 stage 写入：

```text
run.json
checkpoint/<stage>.json
events.jsonl
artifacts.json
```

恢复规则：

- 只从成功 checkpoint 继续；
- 外部资源状态变化时重新 preflight；
- source/data/binary fingerprint 变化时废弃 runtime plan；
- 正在运行的 GDB/ROS session 先查询并清理，再重试；
- 已生成 Sprint1 结果时不重复解析，除非输入 fingerprint 变化。

## 10. 权限和安全

### 自动允许

- 读取本地代码/数据；
- 构建 source schema；
- 调用 Sprint1 只读预检查；
- 生成报告和静态断点计划；
- 读取已有 trace。

### 必须确认

- 远程写入数据；
- checkout/tag/branch；
- 修改 CUDA/yaml/source；
- `catkin_make`；
- `bash start`；
- launch-under-GDB；
- existing PID attach；
- pause/continue/stop/kill；
- sudo 或修改系统 ptrace policy。

禁止将密码、私钥和完整 credential 写入 artifact。

## 11. 测试设计

### 单元测试

- schema validation；
- tool parameter validation；
- path/command quoting；
- source/binary mismatch gate；
- frame/index mapping；
- geometry coordinate conversion；
- failure status and retry policy。

### 合同测试

- harness CLI 输出可被 radarAnalyze adapter 消费；
- `diagnosis-bundle.v1` 到 `viewer-model.v1` 不丢字段；
- `runtime-trace.v1` 可以叠加到现有 bundle；
- tool catalog 自动发现新工具。

### 集成测试

- fake SSH runner；
- fake GDB/MI transcript；
- fake ROS replay provider；
- single SGU golden case；
- point-cloud warm-up simulation；
- blocked permissions；
- source/binary mismatch。

### 现场测试

- 先只读 preflight；
- 再 launch-under-GDB 单数据；
- 再 SGU/HILMODEL=2；
- 再 point-cloud 150–200 帧；
- 最后批量。

## 12. Analysis Ledger 软件契约

### 12.1 `analysis-run.v1`

```json
{
  "schema_version": "analysis-run.v1",
  "run_id": "...",
  "goal": {"question": "...", "customer_claim": "...", "expected": "..."},
  "binding": {
    "project_id": "...",
    "variant_id": "...",
    "data_fingerprint": "...",
    "source_fingerprint": "...",
    "binary_fingerprint": "..."
  },
  "status": "running|partial|blocked|completed",
  "current_stage": "event_map",
  "steps": [],
  "claims": [],
  "hypotheses": [],
  "experiments": [],
  "artifacts": [],
  "metrics": {}
}
```

run 文件只保存索引和小摘要；大 payload 通过 ArtifactRef 引用。

### 12.2 `analysis-step.v1`

```text
step_id / run_id / stage / status
started_at / finished_at / duration
tool_calls: requested + resolved params + result refs
input_artifacts / output_artifacts
observations / claim_refs / gaps / conflicts
user_visible_summary / next_action_candidates
metrics: bag_reads/model_calls/replay_count/gdb_stops
```

step 完成后 append-only；更正通过新 step/claim contradiction，不静默覆盖历史。

### 12.3 `claim.v1`

```text
claim_id / scope / statement
status: observed|derived|inferred|contradicted|not_available
evidence_refs / assumptions / conflicts
binding: data/source/binary/radar/frame/object/function
created_by: tool|ai|user
```

`created_by=ai` 只能使用 inferred，并必须引用已有 evidence/claim；AI 不能创建 observed。

### 12.4 `hypothesis.v1`

```text
hypothesis_id / category / statement
rank / confidence_band
supporting_claim_refs / contradicting_claim_refs
required_evidence / experiment_refs
status: open|testing|supported|weakened|rejected|confirmed_by_user
history[]
```

history 保存每次状态变化、依据和 actor。

### 12.5 `debug-experiment.v1`

```text
experiment_id / question / method
target event/radar/frame/object/source/binary
plan_ref / approval / session_ref
watch_groups / expected_discrimination
observations / disturbance / conclusion_delta
status
```

人工 VSCode 结果以 `user-observation.v1` 进入 experiment，不作为未经校验的 GDB runtime
字段覆盖自动采集结果。

### 12.6 `user-observation.v1`

```text
observation_id / run_id / kind / summary / content
artifact_refs / target / experiment_id / hypothesis_refs
created_by=user / binding / evidence_layer=user_observation / runtime_eligible=false
```

该实体用于记录用户在 VSCode、GDB、截图或对话中的人工观察。它可进入 Analysis Trail 和
Experiment 的结果上下文，但只有在另行通过 `runtime-evidence-normalize`、source/data/frame
identity gate 和对应 schema 校验后，才允许产生独立的 `gdb_observation` 或公共 runtime 证据。

## 13. EventCodePath 软件接口

```python
build_event_code_path(
    *,
    event: Mapping[str, Any],
    code_index: Mapping[str, Any],
    source_root: str = "",
    max_call_depth: int = 2,
    max_breakpoints: int = 8,
) -> dict[str, Any]

load_code_index(
    *, code_index_path: str = "", context_path: str = ""
) -> dict[str, Any]

evaluate_static_conditions(
    event_code_path,
    frame_window,
) -> list[ConditionEvidence]

build_debug_experiment(
    event_code_path,
    missing_variables,
    hypothesis_refs,
    runtime_capabilities,
) -> DebugExperiment
```

调用链节点必须携带 source file/line/symbol/signature/fingerprint；参数节点携带 definition、
formula、runtime dependencies 和 evaluator status。

`event-code-path` 的当前输出是 `event-code-path.v1`：`status`、事件原样引用、source
snapshot、唯一函数 resolution、五层 `layers`、`breakpoint_groups`、
`required_runtime_tokens`、`static_evaluation` 和 diagnostics。它只构建计划，不执行 GDB。
`code-context-refresh` 产生的 `code-index.v1` 至少包含 files/functions/calls、变量读写、
signals、conditions、states、parameters 和 summary，字段来源为当前 CodeGraph SQLite；
两种契约均允许后续项目扩展字段，但不能删除 source/snapshot provenance。

## 14. Public Runtime 关联契约

```text
warning_status_with_frame → frame source: observed
radar_info                → frame source: observed positional schema
objectlist                → frame source: absent in current msg; optional publication-order derived
```

Collector 输出：

```text
association_status:
  frame_verified
  callback_correlated
  publication_correlated
  unbound
```

只有 `frame_verified` 可以作为消息自带 frame 直接挂到 event frame。`callback_correlated` 必须记录 collector
如何保证同一 callback；`publication_correlated` 是基于已验证源码发布顺序的 derived 关联，必须保留
message sequence、关联依据和 source proof，不能升级为 message-level observed；`unbound` 仍单独保留。
`runtime_snapshot_with_frame.v1` 直接携带 frame/radar/object/index/ego/warning/ROI 和
source/binary/config fingerprint。

### 14.1 Source Tx output mapping

`arbe-preflight` 的只读 source scan 同时提取当前 `RteComMapping_WriteSignal(signal)(expr)`
调用，输出 `can_output.write_mappings[]`，每行保留 signal、expression、source file/line 和
原始 snippet。详细报告可按当前事件的 feature/side 对该列表做有界投影，形成
`can_output`/`output_signal_mapping` 区块；它的状态只能是 source candidate，不能当作
`can_tx_observation`。报告只有在同一 frame 的 runtime/CAN artifact 明确命中对应 token 后，
才把该 signal 作为实际输出层事实。

为支持“算法输出之后继续讲到 FCT/ASW 内部最终信号”，preflight 还对当前 COEM 的源文件做
member-assignment scan，产出 `can_output.source_output_chain`（`arbe-source-output-chain.v1`）。
该链从 WriteSignal 表达式抽取真实 member path，关联有效/注释赋值和生产函数，再关联
RteLite/`Com_SendSignal`。报告将它与同帧 runtime/GDB 事实合成为
`diagnostic-output-chain.v1`，按“algorithm output → internal assignment → external mapping →
transport”生成自然语言步骤。源码存在赋值不代表本帧执行；没有运行时值的 internal/external
步骤必须保持 `source_candidate`，不能提升成已发送。

## 15. ProjectCapabilityManifest 契约

```json
{
  "schema_version": "project-capability-manifest.v1",
  "identity": {},
  "data_capabilities": [],
  "feature_capabilities": [],
  "code_capabilities": [],
  "replay_capabilities": [],
  "runtime_capabilities": [],
  "presentation_capabilities": [],
  "freshness": {},
  "unsupported": []
}
```

Pi pack router 只从 manifest 中生成 shortlist。manifest/source fingerprint 不匹配时，
event-code-path、runtime schema、GDB plan 和 project knowledge 均不可消费。

当前唯一 manifest 入口为 `project-capability-manifest`；其 Engine 只读取显式 artifact，
按 schema/status/source snapshot 形成 capability categories 和 unsupported，不做 LLM 推断。
Pi 先调用它获得当前项目短名单，再组合 `code-context-read`、`sim-verify`、
`public-runtime-normalize`、`runtime-debug-plan` 等已有原子能力；不会为每个功能复制
一套工具。

## 16. Workbench 投影和性能

Workbench 读取 ledger 的增量事件，不轮询/反序列化完整 50 MB viewer model。建议：

- run/step/hypothesis 用小 JSON/JSONL；
- frame/object series 用 Parquet/SQLite/按事件分片 JSON；
- 场景按当前事件和 frame 查询；
- source/code 通过 ref 延迟加载；
- Snapshot HTML 构建时冻结所需 slice；
- report refresh 不触发 bag parse/source learn。
- Pi/runtime summary 只返回有界 observation 样本；大快照通过 event/frame/object scope 物化，
  完整 evidence 保留为独立 artifact，避免上下文和 merge 内存随全量帧线性膨胀。

新增性能测试：同一 fingerprint 重跑命中率、Time to First Useful Clue、Debug-ready、bag
full-read count、Workbench 首屏时间、事件切换时间、GDB stop 数和 Pi tool shortlist 大小。

## 17. 三出口的软件落点

### 17.1 evidence-query.v1

`engines.evidence_query.build_evidence_query()` 只接受显式 bundle/viewer/runtime artifact，
按 `event_id/event_index/function/side/radar_id/frame_id` 过滤，并以点号路径读取任意真实字段。
默认返回有界摘要；`include_details=true` 才展开当前事件的场景详情。字段不存在时返回
`status=not_available`，不从上一帧继承，也不把近时间 objectlist 当同帧 runtime。

### 17.2 diagnostic-report.v1

`engines.diagnostic_report.build_diagnostic_report()` 是确定性投影：事件索引、选中事件、ego/target、
source refs、代码/断点、runtime association、缺口和 next actions 均从输入 artifact 获取。
`write_diagnostic_report()` 生成 JSON、Markdown 和 HTML companion；HTML companion 用于快速分享，
正式场景仍由 sibling harness viewer 提供交互式 frame/geometry 视图。可选 `analysis` 字段只进入
`diagnosis.panel_result`，并且 `interpretation_policy` 明确其为 inference。
报告生成前会比较 bundle/code-context 的 source snapshot hash；冲突时报告为 `blocked` 并写入
`conflicts`，不会用当前或历史代码替代事件绑定的 source。

### 17.3 Pi session 与 ledger

`PiModule` 在有 case/context 时自动创建或恢复 `AnalysisRun`，将每个用户回合记录为 dialogue step；
`PiBridge(session_id=...)` 使用 Pi 的 `--session-id`，有稳定 run ID 时不附加 `--no-session`。
Pi tool 事件仅保存工具摘要、结果状态和 artifact refs，不保存隐藏思维链。已有原子
`analysis-run-*`/`analysis-step-record` 仍是正式账本入口，Pi 自动落盘只是对话入口的便利绑定。

`PiModule` 还会从 batch manifest 显式解析 split `cases/<id>` / `data/<id>` 输出，把 viewer-model
作为详细查询的输入；PiBridge 按当次问题生成 bounded tool allowlist，并将 provider 的
`tool_execution_start/end` 归一为 dialogue step 的工具摘要。可选输出字段收到 `json`/`text` 等
格式名时不创建工作区伪文件，只有用户明确给出路径才落盘。

### 17.4 condition-trace.v1

`engines.condition_trace.build_condition_trace()` 只接收当前 source index 的条件/参数行和选中
事件的同帧 field facts。它先保留原始 C 表达式和 source ref，再对可识别的安全表达式子集做求值；
所有操作数必须有明确绑定，参数表达式也必须能由当前 index 递归解析。结果状态为
`satisfied`、`not_satisfied`、`not_evaluable` 或 `unsupported`，并保留 `missing_tokens`、
`bindings`、`substituted_expression` 和原因。它不使用 Python `eval`、不跨帧/跨雷达合并，不把
缺值转换为 false。

`diagnosis-report` 从 event-code-path 自动生成该 artifact projection，并在 HTML 中提供条件表和
ego/target/ROI/heading 的坐标示意；后续 runtime/GDB overlay 只增加事实，不覆盖静态 trace。

### 17.5 memory-recall.v1

`engines.memory_recall.recall_memory()` 是对已有 `MemorySystem` 的只读适配。输入明确的
`project_root`、可选 `variant_id`/`memory_dir`、`pi-orchestration-context.v1`/`context_path`、function/query/case_dir 和 layer；输出每个
记忆层的 status、值和文件 provenance。代码派生层使用现有 `runtime_knowledge_decision`，
freshness 不可证明时 fail closed；该产物只能作为 Pi/AI 的辅助上下文，不得覆盖当前 bundle、
runtime 或 GDB 观察。

`PiModule` 还会从 batch manifest 显式解析 split `cases/<id>` / `data/<id>` 输出，把 viewer-model
作为详细查询的输入；PiBridge 按当次问题生成 bounded tool allowlist，并将 provider 的
`tool_execution_start/end` 归一为 dialogue step 的工具摘要。可选输出字段收到 `json`/`text` 等
格式名时不创建工作区伪文件，只有用户明确给出路径才落盘。

### 17.6 alert-timeline.v1

`engines.alert_timeline.build_alert_timeline()` 是跨证据层的只读 projection。输入可以是
bundle/viewer、`runtime-snapshot-with-frame.v1`、`runtime-case-evidence.v1` 或带明确 layer
的 replay/GDB/CAN rows；输出 `sources`、`rows`、`context_alarm_rows`、`playback_frame_map`、
`comparisons` 和 `conflicts`。它只按 `function/side/radar/frame` 整理已有事实，不执行
功能规则或时间近邻对象关联。

关键约束：

```text
no layer             → source.status=not_available, comparison=not_evaluated
derived/time-aligned → frame_status=derived, comparison=not_comparable
both observed exact  → comparison=same/different
identity conflict    → timeline.status=blocked
```

`diagnostic_report.build_diagnostic_report()` 将 timeline 和 `conclusion` 一起写入
`diagnostic-report.v1`。`report.status=ready` 只说明投影成功；`conclusion.level` 默认是
`facts_only`，只有后续证据、实验和人工确认满足发布门时才允许升级。

报告同时生成 `diagnostic_narrative` 读模型：它按真实源码行、原始条件、代入表达式和当前
求值状态形成中文工程描述，并给出 `should_alert` 的保守状态。`yes_observed` 只来自精确
CAN Tx 上升沿，`supported_yes` 只能表示算法输出或条件层支持，缺少同帧 runtime/CAN 时为
`indeterminate`；该字段不是新的功能规则引擎。

读模型的默认呈现不是完整数据 dump：`executive_summary` 和 narrative 先描述工况、报警输出层、
条件统计和结论，`condition_items` 默认只保留最多 10 条当前功能相关/最影响判断的条件，
`operating_condition` 与 `runtime_facts` 只取关键真实 token。完整 trace、对象列表、连续帧和
GDB transcript 仍作为折叠/机器 artifact 保留。该“摘要 + 完整证据”双层结构保证用户先得到
可读的诊断线索，同时不会牺牲可追溯性。

场景 projection 同时输出 target polygon 与功能 ROI 的几何关系：同帧 runtime 证据使用
`observed_intersects/observed_disjoint`，源码推导几何使用 `source_derived_intersects/`
`source_derived_disjoint`；SVG 标出 polygon 四角、来源和 containment 状态。该几何判断不替代
功能分支的 runtime 状态、`fInterX/fInterY` 或 CAN Tx。
