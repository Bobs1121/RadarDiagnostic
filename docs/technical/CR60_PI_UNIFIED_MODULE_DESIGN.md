# CR60 统一平台模块设计

版本：`module-design.v2.3`  
日期：`2026-09-01`  
前置：[调研报告](../CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md)  
关联：[PRD](../CR60_PI_UNIFIED_PRD.md)

## 1. 设计目标

所有面向用户的业务能力都通过 Pi 的 `registerTool` 目录暴露，但工具背后的实现分为三类：

```text
Core capability
    不依赖 ROS/SSH/GDB，负责数据、代码、证据和报告

Provider capability
    连接外部数据源、harness、arbe、ROS、GDB

Orchestration capability
    管理顺序、依赖、状态、确认、重试和恢复
```

Pi 只看到稳定的工具契约，不依赖某个工具内部的 Python 类或具体仓库路径。生成的
TypeScript extension 只负责 schema 注册和 JSON 转发，所有调用统一经过
`ai/capability/pi_tool_bridge`；`python cli.py <module>` 只保留给开发、测试和
bridge 进程边界。

### 1.1 Pi 编排上下文

每次 Pi run 必须绑定 `pi-orchestration-context.v1`。`pi-context` 是一个原子、
确定性 context binder，合并 `cr60-analysis-intake.v1`、`arbe-preflight.v1`、
explicit case/project/variant、replay/radar、policy 和 artifact refs。若没有 intake，
也可从已校验的 `diagnosis_bundle.v1` 读取其明确的 case/data/source 字段，并从显式
`runtime-debug-plan.v1` 读取 strategy/radar。它不调用 LLM、不从路径名称推断身份、不覆盖 upstream 的 fingerprint；缺失/冲突输出
`partial`/`blocked`，由 Pi 决定是否向用户询问或停止；输出同时包含
`context_fingerprint`，用于后续 artifact/runtime 合并时拒绝错误上下文。

## 2. 模块分层

### L0：外部资源适配层

| 模块 | 资源 | 职责 | 不负责 |
|---|---|---|---|
| `DataTransferProvider` | Excel/UNC/SMB/本地文件 | 调用 `bosch-data-transfert` 能力、获得数据落盘结果 | 不解析算法报警 |
| `ArbeEnvironmentProvider` | Linux/arbe workspace | 只读探测、版本、车型、CUDA、构建、启动 | 不解释报警根因 |
| `RosReplayProvider` | ROS master/播放器/rosbag | 回放、暂停、继续、状态和 ACK | 不选择功能结论 |
| `GdbProvider` | GDB/GDBserver/MI2 | attach、断点、变量、栈、trace | 不猜变量值 |
| `MediaProvider` | camera/image/video | 按证据关联媒体 | 不推断 camera-object identity |

### L1：确定性领域能力层

| 工具 | 输入 | 输出 | 主要来源 |
|---|---|---|---|
| `cr60_sprint1_precheck` | bag/BLF + source context | bundle/model/HTML/index | `cr60-debug-harness` |
| `source_context_refresh` | outer arbe + algo_source | source snapshot/code index/schema | 当前代码 |
| `code_schema_query` | runtime schema + query | 结构、类型、字段、行号 | CodeGraph/AST |
| `code_call_chain_query` | function/feature | 调用链、读取/写入变量 | CodeGraph |
| `code_condition_query` | feature/event | 条件、参数、状态、源码位置 | 当前 source |
| `geometry_contract_resolve` | source + profile | 坐标契约、公式、来源 | 当前 source |
| `geometry_runtime_capture` | runtime session | runtime ego/target/ROI geometry | GDB/probe |
| `geometry_collision_evaluate` | 同帧 geometry | collision/containment evidence | 确定性几何引擎 |
| `evidence_merge` | bag/source/runtime artifacts | merged bundle | schema contract |
| `report_generate` | merged bundle | HTML/CSV/JSON | viewer/report builder |

### L2：编排和解释层

| 模块 | 职责 | 是否直接执行远程副作用 |
|---|---|---|
| `PiCoordinator` | 解析用户目标、规划工具、汇总结果 | 否 |
| `RunSupervisor` | 持久化任务、执行阶段、轮询、恢复 | 通过 Provider |
| `ApprovalGate` | 在危险动作前要求确认 | 否 |
| `DiagnosisExplain` | 基于 evidence 做解释和假设排序 | 否 |
| `MemoryPublisher` | 按 variant/source hash 沉淀知识 | 可写本地知识，不写 arbe |

## 3. Pi 工具目录

### 3.1 数据和上下文工具

#### `pi-context`

职责：生成一个本次 Pi 任务可追踪、不可由模型覆盖的 `PiRunContext`。

输入：`intake`/`preflight` artifact（或路径）、可选 `project-capability-manifest`、
`diagnosis_bundle`/`runtime-debug-plan` artifact、case/project/variant、可选 replay
strategy/radar、freshness、policy。输出：
`pi-orchestration-context.v1`，包含
identity/data/source/build/runtime/capabilities/policy/artifacts/freshness/missing/conflicts。

它是编排前置工具，不承担数据解析、代码分析或远程执行；capability manifest 只提供
当前可用能力摘要，source/data identity 冲突时 fail-closed。

#### `pi_tool_bridge`

职责：Pi Extension 的唯一 Python 调用边界。按 capability name 分派到现有
`BaseTool.safe_execute()` 或 `BaseModule` adapter，统一返回
`{status,message,data,artifacts}`，并默认阻断副作用。

#### `bosch_data_prepare`

职责：复用上游数据准备 skill。

输入：

- 数据源类型；
- Excel/清单/UNC/本地路径；
- TR 列映射；
- 服务器；
- 目标落盘目录；
- 允许的扩展名。

输出：`cr60-analysis-intake.v1`。

风险：远程写入，首次执行或目标不明确时需要用户确认。

#### `cr60-data-prep-verify`

职责：在调用上游传输执行器前，验证 intake 中每个数据 entry 在 Linux 命名空间中的
可达性和内容身份。Linux absolute 路径原样检查；UNC 路径只有在显式给出
`source_prefix` 时才映射；Windows 盘符、relative path 和未配置 mount 返回
`needs_confirmation`，不从路径名猜服务器或车型。

输出 `cr60-data-prep-verification.v1`，每个 entry 保留原始路径、映射状态、case/entry
索引、文件名、扩展名、size、mtime、SHA-256；如果显式开启 destination 检查，则按文件名
比较源和目标的 size/hash。该模块只读，不创建目录、不 `cp`/`rsync`，因此可以由 Pi 在
数据传输之前自动调用；真正传输仍由上游 `bosch-data-transfert` adapter 在审批后执行。

#### `cr60-data-transfer`

职责：在用户批准后调用已经部署/配置好的上游 `bosch-data-transfert` 脚本。输入是
远端脚本路径、远端清单/XLSX 路径、目标 Linux 根目录、source type 和可选 mount 前缀；
平台只生成安全的参数化命令和统一 session，不把上游 `cp/rsync` 实现复制进来。

默认只规划。`execute=true` 且没有 `approved=true` 时返回 `approval_required`，不执行
SSH；批准后保留上游 stdout/stderr/return code/timeout，产出
`cr60-data-transfer-session.v1`。完成后必须再次调用 `cr60-data-prep-verify` 核对目标
文件，不能仅凭传输脚本返回 0 宣称数据内容一致。

#### `project_context_resolve`

职责：生成本次 run 的项目、variant、source、data、workspace 和 session namespace。

输入：项目、车型、COEM、代码仓、数据路径。

输出：`ProjectContext` 和 `analysis-context.v1` 引用。

门禁：source/variant 不确定时返回 `blocked_missing_input`，不得使用其他项目缓存。

### 3.2 Sprint1 工具

#### `cr60_sprint1_precheck`

职责：调用独立 `cr60-debug-harness` 的确定性入口，完成静态预检查。

输入：

```text
intake_manifest 或 input_dir
harness_root
harness_profile
analysis_context
output_dir
html/web_dist
```

输出：

```text
diagnosis_bundle.v1
viewer-model.v1
runtime-schema.v1
breakpoint-pack.v1
batch-index.v1
```

边界：不启动 ROS、不 attach GDB、不改 arbe；只为后续 runtime 生成目标事件和断点输入。

#### `cr60_report_refresh`

职责：当 bundle 已存在、viewer 代码更新时只重新生成 HTML，不重新解析 bag、不刷新远程 source。

### 3.3 源码和几何工具

#### `source_context_refresh`

职责：读取当前 source snapshot，构建 code index 和 runtime schema。

输出必须包含：

- source root；
- outer repository HEAD/branch/dirty；
- algo_source HEAD/branch/dirty；
- source snapshot hash；
- functions；
- structures/message contract；
- parameters；
- feature implementation status；
- parser confidence。

#### `geometry_contract_resolve`

职责：根据当前代码而不是固定模板解析：

- ego axis 和原点；
- x/y 正方向和单位；
- 车辆长宽；
- `bumper2RearAxle_dist`；
- radar mount offsets/yaw/orientation；
- target polygon function；
- feature ROI function；
- runtime collision variables。

#### `geometry_runtime_capture`

职责：通过 GDB/探针捕获：

- `g_egoCarFixPara`；
- `g_radarPos`；
- `objInfo->trcOutData[i]`；
- `sObj`；
- `objPoly.points[0..3]`；
- `adasRoi`；
- `fIntAng`、`fInterX`、`fInterY`、`fTTMX`、`fTTMXObj`、`fTTMY`、`fDDCI`。

#### `runtime_evidence_normalize`

职责：把不同 runtime 来源归一成 `runtime-case-evidence.v1`，不做功能专属判断。输入
可以是 public with-frame topic、算法输出 trace、GDB transcript、probe snapshot 或
objectlist candidate；输出必须保留：

- `recorded_raw`、`replay_algorithm`、`runtime_with_frame`、`gdb_observation` 等证据层；
- data/source/binary/radar/frame/object/function provenance；
- 同一 `frameID + algorithm index + object identity` 的 before/after 字段；
- 当前 polygon、ROI、即时包含、预测交点及 source/formula 引用；
- replay strategy、实际预热帧数、reset/gap 和 `warmup_sensitive`；
- optimized-out/not-found/conflict/not-available 状态。

该模块不认识 FCTA/FCTB，也不把一个层的值覆盖另一个层；功能差异由上游
`source_context_refresh`/runtime schema 和 FeaturePlugin 提供。

### 3.4 arbe 前置工具

#### `arbe_context_probe`

只读检查：

- 主机、用户、OS；
- ROS distro/master；
- workspace 是否存在；
- outer/algo git 状态；
- `catkin` 和 `bash start` 可用性；
- 目标节点和进程；
- GDB/GDBserver；
- ptrace policy。

#### `arbe_version_resolve`

职责：根据用户确认或上游 handoff 检查 tag/branch，不自动 checkout。

#### `arbe_cuda_resolve`

职责：在 checkout 之后读取实际 `08_CustData`，根据当前车型给出真实 CUDA 文件和 sheet 候选。

当前首版原子能力分别是 `arbe-source-resolve` 与 `arbe-cuda-resolve`：

- `arbe-source-resolve` 只读当前 `algo_source` 的 HEAD、branch/detached、exact tag、dirty
  状态，并检查显式目标 ref 是否存在于本地或可选的 `git ls-remote` 结果。软件版本只有在
  Pi/调用方明确提供 `ref_prefix` 与 `version_suffix_strip` 时才派生 ref；工具不内置
  `BYD_UKE` 或其他车型映射。显式 ref 与派生 ref 冲突直接 `blocked`。
- `arbe-cuda-resolve` 只读当前 source 的
  `coem/<vehicle>/tools/container_input/08_CustData/CUDA_*.xlsx`，记录每个候选的远程
  mtime、size、sha256，并按“最新 mtime、路径稳定排序”选出 candidate；同时读取当前
  `launch_config_4radars.yaml` 的 `xlsx_path/xlsx_sheet/type`，返回 `aligned`、
  `needs_update` 或 `not_available`。它不复制 workbook、不编辑 YAML。
- 两个能力都支持 `execute=false` 的 command plan 与注入 runner；`execute=true` 仍然只做
  读操作。输出分别是 `arbe-source-resolution.v1`、`arbe-cuda-resolution.v1`，后续
  `apply` 能力必须重新校验 source fingerprint、dirty 状态和 approval，不能把 read-only
  `selected` 直接当作写入授权。

#### `arbe_patch_plan`

职责：在 source/CUDA 解析之后，读取当前 outer/algo 工作区，检查仿真适配是否存在、文件
是否有 dirty diff、检查项是否因版本变化失效。输入为显式 `arbe_root`、可选
`algo_source_root` 和可配置 `checks`；缺省检查只代表当前上游 skill 的已知适配契约，
不是 FCTA/FCTB 逻辑。

输出 `arbe-patch-plan.v1`：每项保留 scope、相对路径、原始 pattern、匹配行、文件 sha256、
diff 和 required/status；整体状态为 `ready`、`partial` 或 `needs_action`。当前实现只读，
`needs_action` 不会自动修改代码。它把 GUI 调用中的 `taskTime, taskTime` 作为一项独立
检查，因此只有看到真实调用参数才算存在；仅看到 `PostProcessMainTI` 或局部变量
`taskTime` 不足以通过该检查。

#### `arbe_apply_patch`

职责：在用户批准后应用最小、可回退的仿真改动，并返回 before/after hash 和 diff。

#### `arbe_build`

当前实现对应原子模块 `arbe-build`；确定性实现：`engines/arbe/build.py`。
它只在显式 `arbe_root` 上运行 `catkin_make`，保存命令、参数、日志、耗时和 return code；
分支/CUDA/仿真补丁和 `bash start` 都是独立能力，不能由此模块隐式触发。默认 plan-only，
执行需审批，产物为 `arbe-build-session.v1`。

#### `arbe_start`

当前实现对应原子模块 `arbe-formal-start`；它先探测已有正式节点，避免重复启动，再检查
`start` 脚本和非交互 sudo，受批准后以 owned process group 执行 `bash start`，产出
`arbe-start-session.v1`。已有外部进程只标记 `already_running/ownership=external`，不接管。

`arbe-formal-stop` 是配套清理模块，只接受 `ownership=tool_started` 的 session，并在
远端重新校验 PID/PGID、workspace 和命令行，不能以 PID 猜测或停止其他用户进程。

### 3.5 三个用户出口的原子能力组合

三个出口不是三个重复的诊断器，而是对已有原子能力的固定产品配方。Pi 可以按用户意图跳过不需要的步骤，
但每个实际调用仍以独立 artifact 进入 Analysis Ledger。

#### 批量预检查配方

```
cr60-intake / pi-context / project-capability-manifest
    → cr60-precheck(folder|handoff|manifest)
    → batch index + per-data diagnosis_bundle/viewer-model/report
```

`cr60-precheck` 继续是 sibling `cr60-debug-harness` 的窄 adapter；radarAnalyze 不复制 bag parser、
几何渲染或 HTML。Pi 只消费其结构化返回和 artifact refs。

#### 详细诊断报告配方

```
evidence-query(bundle/viewer/runtime, event/frame/filter)
    → code-context-read / code-analyze / event-code-path
    → public-topic-plan / public-evidence-audit（可用时）
    → runtime-evidence-merge（已有 runtime 时）
    → diagnosis-panel（可选 AI 解释）
    → diagnosis-report（确定性报告投影）
```

`evidence-query` 只做通用 artifact 切片；`diagnosis-report` 只聚合事实、来源、缺口、代码链、断点和
可选的 AI 面板结果，不自行判断某个功能的固定条件。没有 AI 或 runtime 时仍生成证据版报告，并把
`diagnosis.status` 设为 `pending`/`partial`。

#### 对话式分析配方

```
Pi session/run context
    → evidence-query（字段/事件/帧）
    → code-context-read / code-analyze（代码/变量/调用链）
    → signal-extract / data-explore（曲线/统计）
    → public-runtime / runtime-debug-plan / GDB（只在证据缺口且获批时）
    → analysis-step-record + evidence/diagnosis-report（需要交付时）
```

对话层不新增“万能查询器”别名，也不直接读任意远程 shell。`evidence-query` 与 `data-explore` 的边界
是：前者读已生成的 diagnosis/viewer/runtime artifact，后者读 FrameStore 中的数据表。

Pi provider 的 tool schema 采用运行时 allowlist：入口根据用户意图和当前 case artifact 从 live
catalog 选择有限的原子工具，再由 Pi 自己决定调用顺序。这样保留“Pi 组合工具”的产品语义，
同时避免一次暴露全部能力导致部分 provider 只复述工具说明而不发起 tool call。allowlist 不是
功能规则，也不会改变工具 registry；未知意图使用小的通用 starter set，显式 `tools` 可覆盖。
case 目录与 sibling harness 的 `data/<id>` 分离时，`batch-index.json` 是 viewer/bundle
companion 的唯一绑定依据。

#### 条件证据与场景投影

`condition-trace` 是确定性的通用原子能力：输入当前 `event-code-path` 的真实条件/参数和选中
事件的同帧 field facts，输出每条 C 表达式的 source ref、bindings、substituted expression、
`satisfied`/`not_satisfied`/`not_evaluable`/`unsupported` 状态和 gap。它不包含 BSD/FCTA 等功能
专用规则，不跨 radar/跨帧找值，也不把 `not_evaluable` 转成失败。

`diagnosis-report` 复用该引擎输出 `condition_trace`，HTML 以条件状态表、来源展开和场景 SVG
展示 ego/target/ROI/heading；完整 JSON 仍是机器真值，HTML 不重新求值。AI 只能解释 trace，
不能写入 observed/derived 值。

报告默认调用 `diagnostic_narrative` 生成 `executive_summary`、关键 `operating_condition`/
`runtime_facts`、`condition_digest` 和有限 `condition_items`，先用文字说明“当时是什么工况、
哪一层输出报警、哪些代码条件已满足、哪些仍缺失”。完整数据仍通过折叠证据区和 JSON 输出；
该选择器只改变展示密度，不改变 condition trace 的求值结果，也不把候选条件拼成固定功能规则。

`geometry_projection` 是同一报告 read model 的确定性场景层：它按当前事件功能/侧别选择 ROI，
使用目标 polygon 与 ROI 的边交叉/包含关系输出 `collision_status` 和逐 ROI
`collision_evidence`。runtime 同帧时标记 `observed_*`，只有 source-derived 点时标记
`source_derived_*`；不得把 `intersects/disjoint` 直接解释为完整功能报警 verdict。

`memory-recall` 复用现有 `MemorySystem`/`SemanticMemory`，按当前 project/variant 返回 L1-L6
和相似案例的结构化 hint。它不新建第二套记忆库，不写入记忆；`code_knowledge`、`constants`、
`patterns` 和 semantic recall 在 freshness 缺失/签名不匹配时返回 `blocked_stale`，Pi 只能把
它们作为缺口或待刷新动作。输入还可以是显式 `pi-orchestration-context.v1`/`context_path`，
由当前 run 注入 variant/memory scope；没有绑定 scope 时不读配置默认车型的代码记忆。

#### 跨证据报警时间线配方

`alert-timeline` 是一个独立的证据投影原子能力。它把已有 bundle/viewer/runtime 里的报警行
统一成 `recorded_raw`、`replay_algorithm`、`runtime_with_frame`、`gdb_observation`、
`can_tx_observation` 五类 layer，并生成 `playback_frame_map`、layer comparison 和 identity
conflict。它不解析 bag、不运行 ROS/GDB，也不拥有 FCTA/FCTB 规则；`diagnosis-report` 直接
复用同一 engine，避免 Pi 查询与 HTML 报告出现两种 frame 语义。

```text
bundle/viewer/runtime artifact
    → alert-timeline
        → layer rows + playback_frame_map + comparisons
            → diagnosis-report / Pi / Workbench
```

只有两侧均带 observed exact frame 时 compare 才能是 `same/different`；缺层是
`not_evaluated`，只有 derived/time-aligned frame 时是 `not_comparable`。data/source/binary
identity 冲突直接 blocked，不得继续作为 selected event 的 runtime 证据。

Pi provider 的 tool schema 采用运行时 allowlist：入口根据用户意图和当前 case artifact 从 live
catalog 选择有限的原子工具，再由 Pi 自己决定调用顺序。这样保留“Pi 组合工具”的产品语义，
同时避免一次暴露全部能力导致部分 provider 只复述工具说明而不发起 tool call。allowlist 不是
功能规则，也不会改变工具 registry；未知意图使用小的通用 starter set，显式 `tools` 可覆盖。
case 目录与 sibling harness 的 `data/<id>` 分离时，`batch-index.json` 是 viewer/bundle
companion 的唯一绑定依据。

### 3.5 Runtime/GDB 工具

#### `runtime_debug_prepare`

职责：根据 Sprint1 bundle 生成 `runtime-debug-plan.v1`，不 attach。

包含：

- runtime mode；
- HILMODEL；
- radar ID/position；
- warm-up policy；
- target events；
- breakpoint locations/conditions；
- capture variables；
- expected process/binary；
- permission requirements。

`runtime_debug_prepare` 只消费当前匹配的 source/runtime schema；如果函数、字段、消息
布局或 binary fingerprint 不匹配，返回 `source_mismatch`/`binary_source_mismatch`，不
复用旧的 GDB 表达式。用户侧只需要确认分析目的和运行权限，技术表达式由工具生成。

当前实现对应原子模块 `runtime-debug-plan`（Engine：`engines/runtime_debug_plan.py`）。
它消费 bundle 内已由当前 source/harness 生成的 `breakpoint_pack`，输出
`runtime-debug-plan.v1`，包含 `readiness.gates`、`gdb_commands`、`vscode_handoff`、
`capture_fields`、radar 安装参数、选定进程和 replay/warm-up 信息。它只规划，不启动 ROS、回放或 GDB；
Pi 可将 `gdb_commands` 通过 typed artifact reference 交给 `gdb-service`，并在执行前
单独处理 approval。

#### `runtime-debug-run`

当前实现对应 `ai/modules/runtime_debug_run.py` + `Cr60HarnessProvider.run_gdb_plan`。
它只把已校验的 `runtime-debug-plan.v1` 转为 sibling harness 的 argv；默认返回
`planned`，`execute=true` 但未批准返回 `approval_required`，批准后才启动隔离 ROS/GDB，
并把原始结果落盘为 `gdb-session.v1`。它不从用户自然语言拼接 GDB 命令，也不替代正式
`bash start`/existing PID attach。

#### `gdb_attach`

职责：按已批准的 plan attach formal `arbe_visualization_engine` existing PID；当前
实现为 `runtime-debug-attach` + `tools/run_gdb_attach_plan.py`。runner 在正式 ROS master
中重新解析 radar node/PID，并要求 `/proc/<pid>/exe` 与 profile program 完全一致。
它不隐式启动/停止 arbe；`replay=true` 也必须显式授权。

运行策略：

1. 已确认的 existing PID attach（正式 `bash start` 路径）；
2. `runtime-debug-run` 的隔离 launch-under-GDB fallback；
3. 用户手工 VS Code handoff。

不允许自动提权或修改 `ptrace_scope`。

#### `gdb_probe_install`

职责：安装当前源码和作用域可证明的断点/tracepoint。

每个断点记录：

- source file/line；
- function；
- condition；
- visible variables；
- expected hit；
- capture command；
- source/binary hash。

#### `runtime_trace_capture`

职责：在回放期间持续或按条件捕获 runtime snapshots、call stack 和 GDB 状态。

高频回放默认使用轻量采样；关键目标帧才进行完整 locals/backtrace。

#### `runtime_debug_teardown`

职责：停止回放、detach/终止由本次 session 创建的进程、收集日志、标记清理结果。

不得误杀用户已有进程。

### 3.6 解释和交付工具

| 工具 | 职责 |
|---|---|
| `evidence_merge` | 合并 bag/source/runtime，保留冲突和 provenance |
| `runtime_compare` | 比较 bag 值、source-derived 值和 runtime 值 |
| `diagnosis_explain` | AI 基于证据解释，不生成事实 |
| `hypothesis_rank` | 排序 perception/situation/FCT 假设 |
| `next_debug_action` | 生成下一步工具调用或人工断点建议 |
| `report_generate` | 输出 HTML、CSV、JSON、handoff |
| `memory_publish` | 按 variant/source fingerprint 沉淀可复用知识 |

## 4. Provider 接口约束

所有 Provider 通过统一 envelope 返回，不向 Pi 抛出未处理异常：

```text
status: pending | ready | running | succeeded | partial | blocked | failed
data: structured JSON
artifacts: file references
provenance: source/data/runtime references
diagnostics: machine-readable gaps
next_actions: allowed follow-up tools
```

每个 Provider 还要声明：

```text
capability
risk
requires_approval
side_effects
idempotency
timeout
retry_policy
```

## 5. FeaturePlugin 接口

为了不把 FCTA/FCTB 固化到核心，功能插件只提供 adapter hint，当前真实信息由 source schema 填充：

```python
class FeaturePlugin:
    feature_id: str
    match_event(event, runtime_schema) -> bool
    resolve_code_focus(runtime_schema) -> dict
    resolve_parameters(runtime_schema, frame) -> dict
    resolve_geometry(runtime_schema, frame, runtime_trace) -> dict
    breakpoint_targets(runtime_schema, event) -> list[dict]
    triage_projection(bundle) -> dict
```

插件不拥有固定参数真值，不能在代码版本变化后继续使用过期字段。

## 6. 能力注册规则

新增能力必须：

1. 实现 `BaseModule` 或 `BaseTool`；
2. 声明 input/output schema；
3. 声明 tags、risk、approval 和 provenance 需求；
4. 注册到 `MODULE_REGISTRY`/`TOOL_REGISTRY`；
5. 自动进入 `CapabilityRegistry`；
6. 增加离线契约测试；
7. 更新本文件和 `AGENTS.md`。

Pi 不直接 import `cr60-debug-harness` 内部模块。短期使用 CLI/JSON adapter；长期如 schema 稳定，再提取很小的 contracts package。

`ai/capability/module_bridge.py` 是当前 Pi/ReAct 与模块注册表之间的窄桥：它把
`cr60-intake`、`arbe-preflight`、`cr60-precheck` 的 `input_schema` 和 `ModuleResult`
转换为 `BaseTool` 的 JSON envelope。默认 registry 只暴露这三个统一平台入口，并排除
递归的 `pi`/`agent-repl`；`cr60-precheck` 的 `execute=true` 在未获得 supervisor 审批时
会被桥拒绝。这样 LLM 可以规划数据绑定、环境探测和 Sprint1 预检查，但不能自行绕过
确认门执行远程/重任务。

## 7. 已落地的首批模块（2026-08-26）

### `cr60-intake`

`engines/arbe/intake.py` 提供确定性 `build_intake(...)`，由
`ai/modules/cr60_intake.py` 暴露为 Pi/CLI 能力。它读取显式输入、JSON/YAML/CSV/文本和
XLSX 材料，保留材料 SHA-256、字段候选和 locator；当前 XLSX 兼容问题清单的
B/C/E/G/J（Ticket/触发功能/车型/触发版本/数据路径）。输出同时包含：

- 内部审计状态 `intake_status=ready|needs_confirmation|blocked_missing_input`；
- 下游 handoff 状态 `status=ready|partial|blocked`；
- `handoff_id`、`environment`、`data.cases[]`、`identity/source_context` 和
  `cr60-analysis-intake.v1` 详细 candidates/conflicts/confirmation_required。

`status=blocked` 不能进入 Sprint1；`status=partial` 需要显式批准后才可消费。路径名不
参与身份推断，Linux/UNC 数据路径在本地只标记 `remote_unverified`。

### `arbe-preflight`

`engines/arbe/preflight.py` + `ai/modules/arbe_preflight.py` 是只读 SSH 预检。它已在
`10.190.171.44` 的现有运行 workspace 验证了 outer/algo HEAD、COEM/CUDA/config、
`BUILDMODEL/HILMODEL`、binary、GDB/ptrace、四个 visualization PID/namespace/radar ID
和 CAN Tx 源码候选；可通过显式 `ros_master_uri` 选择 ROS master。产物为
`arbe-preflight.v1`。它不执行任何 build/start/attach。

### `cr60-precheck` 与 `Cr60HarnessProvider`

`ai/modules/cr60_precheck.py` 通过 `ai/providers/cr60_harness.py` 调用 sibling
`cr60-debug-harness`，不复制其 parser/viewer。`folder` 模式消费远程/本地数据目录，
`handoff` 模式消费 `cr60-analysis-intake.v1` 并转换为 `intake-manifest.v1`，`manifest`
模式直接消费已有 harness manifest。默认只生成
`shell=False` argv 计划；设置 `execute=true` 才运行 harness。必须提供已有
`analysis-context.v1` 或 `prepare_context=true`，以保证源码/参数解释绑定当前代码。

当前实现的边界是 Sprint1 静态预检查：会回传 `diagnosis_bundle`、`viewer-model`、HTML
及 `batch_summary` 产物引用，但不执行数据传输、切分支、CUDA 写入、编译、`bash start`
或 GDB。后续 S3 runtime 工具只消费这里的 event/frame/target/breakpoint pack。

## 8. 原子工具编排契约（新增）

统一平台不把“分析一个报警”实现成一个大工具，而是把可复用能力拆成可组合的
artifact-in/artifact-out 原子工具：

| 原子工具 | 输入 | 输出 | 是否认识功能名 | 默认副作用 |
|---|---|---|---|---|
| `public-topic-plan` | 当前 harness TOML、可选 preflight/runtime schema | `public-topic-plan.v1` | 否 | 无 |
| `ros-topic-inventory` | ROS setup/workspace + allowlisted topic names | `ros-topic-inventory.v1` | 否 | 无 |
| `public-evidence-audit` | `diagnosis_bundle.v1` | `public-evidence-audit.v1` | 否 | 无 |
| `code-analyze` | 当前 CodeGraph 查询 | 函数/调用/变量/条件证据 | 不要求 | 无 |
| `code-gdb-plan` | 当前 source code-index + 函数/变量/观测条件 | `code-gdb-plan.v1`、GDB 指令 | 否；只使用调用者提供的真实 token | 无 |
| `gdb-service` | target + 上游生成的 GDB commands | `gdb-session.v1` | 否 | `execute=true` 时可能停进程，需审批 |
| `runtime-evidence-normalize` | GDB session/transcript 或 public `runtime-snapshot-with-frame.v1` + 显式 run/binding | `runtime-case-evidence.v1` | 否 | 无 |
| `runtime-evidence-validate` | runtime artifact，可选 diagnosis bundle | validation/binding report | 否 | 无 |
| `runtime-evidence-compose` | 两个已规范化 `runtime-case-evidence.v1` producer | composite runtime evidence，保留 runs/layers/observations | 否 | 只写用户指定本地产物 |
| `runtime-evidence-merge` | `diagnosis_bundle.v1` + `runtime-case-evidence.v1` | additive merged bundle + merge report | 否 | 只写用户指定本地产物 |

标准编排链为：

```text
Sprint1/harness bundle
  → public-evidence-audit
  → code-analyze / code-gdb-plan
  → gdb-service(plan)
  → 用户/RunSupervisor approval
  → gdb-service(execute)
  → runtime-evidence-normalize
  → runtime-evidence-validate
  → runtime-evidence-compose（公共/GDB 多 producer 时）
  → runtime-evidence-merge
  → viewer-model / HTML + pi-context
```

`gdb-service` 不绑定 `cr60-precheck`、`code-analyze`、FCTA/FCTB 或任何固定断点；它只
验证通用 GDB 命令的安全语法并执行。`code-gdb-plan` 也不硬编码功能，它必须从当前
code-index 解析真实函数位置；frame/object 条件由上游证据传入，且函数入口局部变量
的 scope 风险会被记录。Pi 可以自由组合这些工具，但只能沿 schema 和 provenance
传递数据，不能把自然语言答案直接当作 GDB 命令。

工具间传值使用 AgentLoop 的 typed artifact reference，而不是文本拼接：

```json
{
  "tool": "gdb-service",
  "params": {
    "target": {"$ref": "steps[0].result.data.target"},
    "commands": {"$ref": "steps[1].result.data.gdb_commands"}
  }
}
```

执行轨迹同时保存原始 `$ref` 和 `resolved_params`，所以可以审计 Pi 实际把哪一份
代码分析结果交给 GDB。

### 8.1 Runtime evidence 的消费规则

`runtime-evidence-normalize` 是 GDB/public runtime 生产端与下游消费端之间的唯一规范化
边界。它将 `gdb-session.v1` 的 stop/backtrace/args/locals/expressions、producer 的
`CR60_RUNTIME` marker 或 `runtime-snapshot-with-frame.v1` 变成 `runtime-case-evidence.v1`，并保持每个字段的真实
`token/value/status/phase/source`。marker 只有在带 `field_token` 或显式
`marker_field_map` 时才可被当作代码变量；否则保留为未知 marker 字段。

`runtime-evidence-merge` 先比较 source context、source snapshot、data/bag 和 binary
identity，再按 `event_id → radar_id + frame_id + object_id` 匹配。时间邻近只能作为
诊断信息，不能建立 runtime 与事件的绑定。匹配成功但 binary 指纹缺失是 `partial`；
identity 冲突是 `blocked`，事件不挂可消费引用。merged bundle 的 `runtime_evidence`
和 `runtime_merge` 为新增字段，静态 `alarm_events/frame_evidence` 保持不变。

merge 支持可选的 event/frame/object scope。Pi 传入当前事件后，工具只把对应
radar_id + frame_id + object_id observation slice 物化到 merged bundle，并在
runtime_merge.scope 记录源/选中数量；完整 runtime artifact 仍由调用方单独保存并通过
runtime_evidence.artifacts 引用。未提供 scope 时保持兼容的 full merge 行为。

`viewer_model` 只读取合法 overlay，在当前 frame 显示 GDB fields、before/after、调用栈、
runtime `objPoly/ROI` 和动态变量；没有同帧 observation 时显示缺失，不沿用前一帧。`pi-context`
只嵌入同一 artifact 的 deterministic summary，AI 可以解释和提出假设，但不能改写值。

## 9. 分析过程与协同模块（v2）

### 9.1 `AnalysisLedger`

职责：持久化 `AnalysisRun`、`AnalysisStep`、`Claim`、`Hypothesis`、`DebugExperiment` 和
用户 decision。它不调用 LLM、不解码 bag，是所有阶段状态和中间结论的单一来源。

公开能力建议：

```text
analysis-run-create / analysis-run-read / analysis-run-resume
analysis-step-begin / analysis-step-complete / analysis-step-fail
claim-append / claim-link-evidence / claim-contradict
hypothesis-upsert / hypothesis-update-status
debug-experiment-plan / debug-experiment-record-result
user-observation-append
```

底层可以先实现为 append-only JSONL + manifest，稳定后再评估 SQLite。Pi 只通过 typed
tool 写入，不直接编辑 ledger 文件。

### 9.2 `EventCodePathBuilder`

输入：event、current source/index、ProjectCapabilityManifest。输出 `event-code-path.v1`：

- output/CAN chain；
- feature/handler/state chain；
- situation/ROI/TTC/suppression chain；
- target selection/tracking chain；
- input/replay/perception chain；
- 真实 token、source ref、参数依赖、静态条件、runtime gap、breakpoint group。

它组合现有 `code-analyze`、`code-gdb-plan` 和 source schema，不新建另一套代码解析器。

当前确定性实现为 `engines/event_code_path.py` + `ai/modules/event_code_path.py`，Pi 名称为
`event-code-path`。输入是一个上游已选择的 event 和 `code-index.v1`（可直接传
`code_index_path`，也可传 `code-context.v1` 的 `context_path`）；event 可以携带真实函数名、
输出信号、frame/object scope、条件和 watch token。实现按唯一函数解析输出五层导航，调用
已有 `build_code_gdb_plan()` 生成 root breakpoint，不执行 GDB。解析不到函数或同一输出信号
对应多个函数时返回 `blocked`，不把功能名反推成函数名。

同一切片新增 `code-context-refresh` / `code-context-read`：前者一次性生成 source-bound
CodeGraph/index，后者按 section 有界读取，供 Pi 在多条数据间复用。两者与 EventCodePath
通过 `code-index.v1` 连接，避免每次数据分析重新扫仓。

### 9.3 `HypothesisManager`

不负责判断数据真值，只管理候选根因：

```text
generate candidates from claims/gaps
rank by evidence coverage and contradiction
select minimum-cost discriminating experiment
update supported/weakened/rejected state
require user confirmation for final root cause
```

类别由项目 manifest 扩展，公共基类为 data/replay/perception/tracking/situation/function/
config/output/integration。

S2B MVP 先由 `engines.analysis_ledger.AnalysisLedger.upsert_hypothesis()` 提供确定性状态
和历史持久化，再由 `analysis-hypothesis-record` 暴露给 Pi；它不自动生成候选、不替用户
确认根因。`debug-experiment-record` 负责计划/结果的同一实体生命周期，要求先 `planned`
再记录结果；`analysis-user-observation` 负责人工 VSCode/GDB/截图/备注回填，产物固定为
独立 `user-observation.v1`，不直接进入 runtime condition binding。详细输入/状态门禁见
`CR60_PI_UNIFIED_S2B_MVP_DESIGN_2026-09-01.md`。

### 9.4 `PublicRuntimeCollector`

优先消费当前 arbe 已有：

- `warning_status_with_frame`；
- `radar_info`；
- `objectlist_<radar>`；
- BagReader event/scene selection 和完成 ACK。

Collector 必须输出关联质量。由于当前 objectlist 无算法 frameID、stamp 为发布时刻，严格模式只能
保留 frame_verified、callback_correlated 或 unbound；当当前 source 分析证明同一处理周期
内 objectlist 先于 warning_status_with_frame 发布，并且 capture 保存消息序号时，可显式选择
publication_order，输出 publication_correlated 及其 derived 证据。它不按 timestamp
猜同帧，也不把 publication_correlated 冒充消息自带 frame。

当前实施不新增 Pi capability，而是扩展已有 `sim-verify`：

```text
sim-verify(mode=remote_public)
  → RemoteArbeReplayProvider.capture_public()
  → SSH rosbag record + rosbag play + remote generic JSON extractor
  → optional scp fetch
  → public-runtime-normalize
  → runtime-snapshot-with-frame.v1
```

`sim-verify` 负责远程回放、录制和 capture artifact；`public-runtime-normalize` 负责 warning
上升沿、frame/callback/publication-order/unbound 归一化。二者不互相复制职责，也不把当前项目的 15 路名字
固化在远程回放引擎中；名字由当前 source/manifest 传入。

### 9.5 `ArbeStampedSnapshotBridge`（可选）

如果 public collector 无法满足精确同帧，才在 arbe feature branch 增加默认关闭的 snapshot
topic/service。bridge 在同一算法 callback 内输出 frame/radar/ego/objects/warning/ROI 和
fingerprint；不修改算法决策，不导出任意内存。局部变量和调用栈仍由 GDB 获取。

### 9.6 `ProjectCapabilityManifestBuilder`

从 intake/source/config/data/preflight 生成项目能力清单，供 Pi tool shortlist、FeaturePlugin
和 Workbench panel 选择。manifest 变化使旧 event-code-path、runtime schema 和 hypothesis
上下文 stale；不能跨项目回退。

当前实现对应唯一 Pi 能力 `project-capability-manifest`，确定性代码位于
`engines/project_capability.py`，输入可以是 inline artifact 或 JSON path：

- intake / preflight；
- code-context（含 source snapshot/hash）；
- runtime-snapshot；
- diagnosis bundle；
- 显式 project/variant identity 和可选 additive capability declaration。

输出 `project-capability-manifest.v1`，按 data/feature/code/replay/runtime/presentation
分类，保存 artifact schema/hash/path、identity provenance、unsupported、freshness 和
manifest fingerprint。它不复制 `pi-context` 的 run binding，不从路径名猜测车型或功能；
没有证明的能力只进入 unsupported。该模块已注册到 Pi catalog，新增的是 manifest
投影能力，不是第二套编排入口。

### 9.7 `CapabilityPackRouter`

完整 registry 继续保留。Router 根据 stage、manifest、policy 和 freshness 返回 5–12 个候选
工具及其输入缺口，不执行工具。Pi 使用短名单规划，避免随着原子工具增长而降低选择准确率。

### 9.8 `WorkbenchProjection`

将 ledger + evidence bundle 投影为：

- Analysis Trail；
- Scene/Timeline/Code/Debug/Media 主面板；
- Claim cards 和 gap/conflict；
- Hypothesis Board；
- Next Experiments；
- Snapshot HTML。

WorkbenchProjection 不计算根因、不重新解析 HTML；任何 UI 值都必须回到 ledger/evidence ref。
