# ai/modules/ — V3 standalone capability modules

> 用于「需求 ↔ 实现」review。AI 编辑 `ai/modules/` 目录文件时参考本文档。

---

## 模块概览

| 文件 | 编号 | 定位 | CLI 子命令 | AI 调用 |
|------|------|------|-----------|---------|
| `agent_loop.py` | PR5 | 离线 Agent/ReAct 执行核心包装 | `agent-loop` | 无 |
| `project_init.py` | PR6-F | 最小输入项目接入 | `project-init` | 无 |
| `signal_bridge.py` | M2 | CAN ↔ 内部变量/输出信号映射 | `signal-bridge` | 无 |
| `diagnosis_panel.py` | M6 | 独立诊断面板（分类+专家） | `diagnosis-panel` | simple × 1 + 可选 complex × 多次 |
| `code_review.py` | M7 | 离线 code review 骨架 | `code-review` | 无 |
| `data_diagnostics.py` | M4 | 车辆数据探针（无代码假设） | `data-explore` | 无 |
| `bsd_data_bridge.py` | M9 | BSD 信号匹配 + 条件交叉验证 | `bsd-data-bridge` | 无 |
| `signal_audit.py` | M10 | BLF 关键链路信号抽取 + 契约审计（枚举合法性 + UI 模式回传契约） | `signal-audit` | 无 |
| `arbe_preflight.py` | CR60 | 只读探测 arbe/source/config/binary/GDB/进程/CAN Tx 候选，可显式绑定 ROS master | `arbe-preflight` | 无 |
| `cr60_intake.py` | CR60 | 材料优先的数据/软件/车型/COEM/分支绑定，冲突和缺口 fail-closed | `cr60-intake` | 无 |
| `cr60_precheck.py` | CR60 | 将已确认 intake/数据目录交给独立 harness 做 Sprint1 预检查和 HTML 产出 | `cr60-precheck` | 无 |
| `public_topic_plan.py` | CR60 | 规划不依赖 GDB 的 ROS/bag 公共逐帧证据通道 | `public-topic-plan` | 无 |
| `public_evidence_audit.py` | CR60 | 审计 bundle 已有的逐帧自车/目标/warning 证据和 GDB 缺口 | `public-evidence-audit` | 无 |
| `code_gdb_plan.py` | CR60 | 基于当前 code-index 解析真实函数位置并生成通用 GDB 指令 | `code-gdb-plan` | 无 |
| `gdb_service.py` | CR60 | 通用 headless GDB batch 服务，独立于功能和断点；执行后归一化 observations | `gdb-service` | 需审批 |
| `runtime_evidence.py` | CR60 | runtime session/transcript 归一化、producer compose、身份校验、静态 bundle additive merge | `runtime-evidence-normalize` / `runtime-evidence-validate` / `runtime-evidence-compose` / `runtime-evidence-merge` | normalize/compose/merge 无远程副作用 |
| `runtime_debug_plan.py` | CR60 | 按当前事件/source/preflight 生成 runtime debug readiness、断点、采集字段和 handoff | `runtime-debug-plan` | 无 |
| `runtime_debug_run.py` | CR60 | 将已确认的 `runtime-debug-plan.v1` 交给 sibling harness 做隔离 ROS/GDB 执行并产出 session | `runtime-debug-run` | 需审批 |
| `runtime_debug_attach.py` | CR60 | 对正式 `bash start` 后已发现且 executable 校验通过的 PID 做 plan-bound GDB attach | `runtime-debug-attach` | 需审批 |
| `arbe_formal_start.py` | CR60 | 启动正式 arbe `bash start`，记录 owned process group/session，避免重复启动 | `arbe-formal-start` | 需审批 |
| `arbe_formal_stop.py` | CR60 | 只停止 `arbe-formal-start` 创建且 ownership/process-group 可证明的正式 session | `arbe-formal-stop` | 需审批 |
| `arbe_build.py` | CR60 | 对显式 arbe workspace 执行 `catkin_make`，不切分支/CUDA/start | `arbe-build` | 需审批 |
| `arbe_source_resolve.py` | CR60 | 只读解析当前 algo_source 与目标 branch/tag；显式版本映射，不 checkout/fetch | `arbe-source-resolve` | 无 |
| `arbe_cuda_resolve.py` | CR60 | 只读解析当前车型 CUDA 候选和 YAML 对齐，不复制/写配置 | `arbe-cuda-resolve` | 无 |
| `arbe_patch_plan.py` | CR60 | 只读执行可配置仿真适配检查、hash/diff 和 action gate，不应用补丁 | `arbe-patch-plan` | 无 |
| `cr60_data_prep_verify.py` | CR60 | 只读验证 Linux 数据源/目标文件、大小和 SHA-256，不执行传输 | `cr60-data-prep-verify` | 无 |
| `cr60_data_transfer.py` | CR60 | 审批后通过 SSH 调用已配置上游传输脚本，不复制脚本逻辑 | `cr60-data-transfer` | 需审批 |
| `ros_topic_inventory.py` | CR60 | 只读获取 ROS topic/type/publisher/subscriber，验证公共逐帧证据链 | `ros-topic-inventory` | 无 |
| `pi_context.py` | CR60 | 将 intake/preflight/project/data/runtime/policy 绑定为 PiRunContext | `pi-context` | 无 |
| `project_capability.py` | CR60 | 将当前显式 artifact 投影为 Gen6 能力/缺口/freshness 清单，供 Pi shortlist | `project-capability-manifest` | 无 |
| `analysis_ledger.py` | V4 S1A | AnalysisRun create/read/update、Step begin/complete、Claim append | `analysis-run-*` / `analysis-step-record` / `analysis-claim-append` | 本地 artifact 写入 |
| `analysis_collaboration.py` | V4 S2B | Hypothesis 状态历史、DebugExperiment 计划/结果、用户手工观察回填 | `analysis-hypothesis-record` / `debug-experiment-record` / `analysis-user-observation` | 本地 artifact 写入 |
| `code_context.py` | V4 S1B-prep | 一次性当前源码快照、CodeGraph 导出和有界查询 | `code-context-refresh` / `code-context-read` | 本地 source/index/db 产物 |
| `event_code_path.py` | V4 S1B | 事件到当前源码的五层导航、runtime gap 和通用 GDB 计划 | `event-code-path` | `event-code-path.v1`（可选 JSON） |
| `public_runtime.py` | V4 S2A-prep | arbe 公共 warning/radar_info/objectlist 行归一化和帧关联质量 | `public-runtime-normalize` | `runtime-snapshot-with-frame.v1` |
| `evidence_query.py` | V4 S1C | 从已有 bundle/viewer/runtime artifact 按事件/帧/真实字段做有界查询 | `evidence-query` | 无 |
| `diagnostic_report.py` | V4 S1C | 将静态/runtime/code/AI artifact 投影为详细诊断报告 | `diagnosis-report` | 无（AI 结果由输入传入） |
| `condition_trace.py` | V4 S1D | 基于当前 source 条件和同帧 field facts 生成可审计求值 trace | `condition-trace` | 无 |
| `memory_recall.py` | V4 S1D | 读取当前项目/variant 的历史记忆和相似案例，不写入、不替代当前证据 | `memory-recall` | 无 |
| `alert_timeline.py` | V4 S1E | 将 raw/replay/public/GDB/CAN 报警按证据层和播放帧投影比较 | `alert-timeline` | 无 |

`memory-recall` 除显式 `variant_id`/`memory_dir` 外支持 `context`/`context_path`，从当前
`pi-orchestration-context.v1` 读取 scope；缺少可证明 scope 时，代码型记忆仍为
`blocked_stale`，不得使用 `config.default_variant`。

### V4 能力模块（Pi 驱动架构，Engine/BaseTool/BaseModule + Pi registerTool）

> V4 不新增平行的 `CapabilityModule` 协议。确定性逻辑放在 Engine，Pi/Agent 契约使用
> `BaseTool`，需要独立 CLI/API 时使用 `BaseModule`；catalog 自动生成 Pi
> `registerTool`。用户编排统一由 Pi 完成，完整设计见 `docs/technical/V4_PI_DRIVEN_ARCHITECTURE.md`。

| 能力 | name | 独立 CLI | 职责边界 | 复用资产 |
|------|------|----------|----------|----------|
| 数据抽取 | `signal-extract` | `cli.py signal-extract "车速" <case> --plot` | 信号查找/抽取/绘图 | `PlotSignalTool` + `tools/plot_signals.py` + `generated_signal_map.py` |
| 数据分析 | `data-analyze` | `cli.py data-analyze ...` | 统计/分布/窗口/TPE | `engines/data_probe.py` + TPE |
| 代码学习 | `code-learn` | `cli.py code-learn ...` | 代码索引/条件/映射（AST→索引→按需检索） | `ai/codegraph/`（激活 tree-sitter AST）+ `engines/signal_mapper.py` |
| 代码分析 | `code-analyze` | `cli.py code-analyze ...` | 调用链/依赖/语义 | `ai/codegraph/` |
| 问题诊断 | `diag` | `cli.py diag ...` | 完整 8 步管线（保留，V3 兼容） | `ai/orchestrator.py`（run_diagnosis） |
| 代码修复 | `code-fix` | `cli.py code-fix ...` | 代码修改建议（diff） | `ai/code_fix_engine.py` |
| 仿真验证 | `sim-verify` | `cli.py sim-verify ...` | arbe 回放 + KPI/结果验证 | `tools/arbe/` + `engines/arbe/replay_provider.py` |
| 需求分析 | `req-analyze` | `cli.py req-analyze ...` | 需求→代码 gap（violations + requirement_trace） | `core/materials.py` + `ai/requirements/loader`+`tracer` + code-analyze |
| 记忆 | `memory` | `cli.py ...` | 记忆读写/召回/沉淀 | `memory/memory_system.py` |
| 对话中枢 | `pi` | `cli.py pi "..."` / `cli.py pi` | 意图理解/规划/调度/综合（唯一产品入口） | `ai/pi_bridge.py` + generated `registerTool` + `pi_tool_bridge` |

**新增能力三步**：① 新建 Engine（如需要）和 `BaseTool`/`BaseModule` 契约
（name/description/input_schema/output_schema/tags/run）→ ② 注册到对应 registry
（module 使用 `ai/modules/__init__.py` 的 try/except）→ ③ catalog/generator 自动发现并
生成 Pi `registerTool`。`capability.module_bridge.build_module_tool_registry()` 仅为
AgentLoop/ReAct fallback 适配模块，排除 `pi`、`agent-repl`、`agent-loop` 三个编排根；
Pi 正式入口使用 `ai/capability/pi_tool_bridge`。

**质量契约**：`run()` 必须返回 `ModuleResult`（不得抛未捕获异常）；能力只依赖 L1 数据统一层 + 其他能力的公开结果；新增模块不得修改既有模块。`CapabilityRegistry` 会把模块的 `input_schema`/`output_schema` 暴露到 catalog 的 `parameters`/`output_schema` 字段，供 Pi/外部调度器生成工具调用参数和校验结果；没有声明 schema 的历史模块仍返回空对象。

### V4 S1A `analysis-ledger`（阶段性调查账本）

同一文件注册 5 个原子模块：

| 模块 | 作用 |
|---|---|
| `analysis-run-create` | 创建 goal/binding/policy/artifact-bound run |
| `analysis-run-read` | 读取摘要或完整 step/claim entity |
| `analysis-run-update` | 更新 run 状态、阶段和显式 metrics |
| `analysis-step-record` | `begin/complete` 一个可见阶段；保存观察、gap/conflict、摘要和下一步 |
| `analysis-claim-append` | 追加 evidence-bound claim，并可链接到 step |

所有模块调用 `engines.analysis_ledger.AnalysisLedger`，不做业务推理。Pi/AI 若创建 claim，
只能使用 `inferred/derived/not_available/contradicted`，不能创建 `observed`；observed 必须由
工具或用户提供 evidence ref。Hypothesis/DebugExperiment 通过 `analysis_collaboration.py`
持久化；用户观察固定为独立 `user-observation.v1`，不能直接覆盖 runtime evidence。
`ledger_root` 默认是项目内 `outputs/analysis_runs`，可按项目/用户显式覆盖。

### V4 S1B `event-code-path`（事件→源码路径）

`EventCodePathModule` 只消费上游选择的单个事件和当前 `code-index.v1`/`code-context.v1`，
通过真实函数名或输出信号反查唯一源码函数，然后输出 output、handler、situation、target、
input 五层导航、真实 source ref、静态条件、相关参数、runtime-required tokens 和
`code-gdb-plan.v1` root breakpoint。功能名、报警位、ROI 和数组下标不在模块中写死；事件无法
唯一解析时返回 `blocked` 与诊断，供 Pi 请求上游补充或转入公共/runtime 探测。模块不会执行
GDB，也不会把静态条件判定为最终根因。

### V4 S1B-prep `code-context`（一次性源码上下文）

同一文件注册两个原子模块：

| 模块 | 作用 |
|---|---|
| `code-context-refresh` | 对显式 `source_root` 计算 C/C++ 文件内容指纹，复用 `CodeGraphBuilder`，导出当前 source-bound `code-context.v1` 和 `code-index.v1` |
| `code-context-read` | 从已生成 context 读取限定 section（functions/calls/variables/signals/conditions/parameters 等），不重新扫描源码 |

`code-context-refresh` 的 generic index 不内置 FCTA/FCTB、ROI 或固定文件路径；可选的
`function_keywords` 只用于当前项目的模块绑定。源码在构建期间变化会阻止发布，已有 context
绑定到不同 `source_root` 时不覆盖。`code-analyze` 与 `code-gdb-plan` 可以直接消费其
`code-index.json`，因此一次代码处理后，Pi 后续分析只需按 section/函数查询。默认不调用
LLM；未来语义 enrichment 必须另存并绑定相同 `snapshot_hash`。

### CR60 `arbe-source-resolve` / `arbe-cuda-resolve`（上游只读绑定）

这两个模块把 `bosch-data-transfert` 与 `cr60light-arbe-build` 的关键前置事实拆成
Pi 可组合的原子能力。它们都只读当前远程工作区，不能替代后续 checkout、配置写入或
编译审批。

`arbe-source-resolve` 的输入可以是 `cr60-analysis-intake.v1` 或显式
`algo_source_root`。当给出 `software_version + ref_prefix + version_suffix_strip` 时，
才按调用方的映射规则生成候选 ref；显式 `requested_ref` 与派生 ref 冲突则
`blocked`。执行后返回当前 HEAD、branch/detached、exact tag、dirty、local branch/tag
和可选 `git ls-remote` 结果，产物为 `arbe-source-resolution.v1`。它不调用 `git fetch`
或 `git checkout`。

`arbe-cuda-resolve` 的输入可以是 intake/preflight 或显式 workspace、车型和 sheet。它
从当前 `algo_source/coem/<vehicle>/tools/container_input/08_CustData` 读取所有
`CUDA_*.xlsx` 的 mtime、size、sha256，按当前扫描结果选择最新候选，并读取
`launch_config_4radars.yaml` 的 `xlsx_path/xlsx_sheet/type`。返回
`configuration.alignment`（`aligned`/`needs_update`/`not_available`）和实际源码路径，
不复制文件、不修改 YAML。未知车型或路径不进入远程命令。

两者的 `execute=false` 仍然生成完整 command plan；`execute=true` 只允许这类只读扫描，
并把 `command_result`、输入来源和 preflight 引用写入 artifact。后续
`arbe-source-apply` / `arbe-config-apply` 必须重新校验同一 source fingerprint、dirty
状态和用户审批，不能直接把本模块的 `selected` 当成写入授权。

`arbe-patch-plan` 使用 `checks` 描述仿真适配检查：每项包含 `scope`（`arbe`/`algo`）、
相对路径、正则 pattern 和 required 级别。缺省检查来自当前
`cr60light-arbe-build` skill 的已知适配契约，但可以由 Pi 按新 source 版本替换。它
保留匹配行、文件 sha256 和 `git diff`，以 `arbe-patch-plan.v1` 返回
`ready`/`partial`/`needs_action`。GUI 检查要求真实调用参数出现
`taskTime, taskTime`；只出现函数名或局部变量不通过。即使检查项全部命中，outer/algo
dirty 仍为 `partial`，不代表可以直接编译。

`cr60-data-prep-verify` 只消费 intake 或显式数据路径。它将 UNC 路径交给显式
`source_prefix` 映射，Linux absolute 路径原样验证，Windows/relative/无 mount 的路径
返回缺口；每个 entry 保留原始路径、映射规则、文件 size/mtime/SHA-256，并可比较指定
destination。它只读当前远端文件，输出 `cr60-data-prep-verification.v1`，不调用上游
复制脚本的写操作。

`cr60-data-transfer` 是实际写入边界：它只接受显式远端 `script_path`、`input_path`、
`destination_root` 和 `source_type`，把命令交给 `bosch-data-transfert`，不在本项目中
重写 `rsync/cp` 重试逻辑。`execute=false` 生成 plan；`execute=true` 且
`approved=false` 返回 `approval_required` 且不调用 runner；只有显式批准才执行，并保留
上游 stdout/stderr/return code。完成后仍应调用 `cr60-data-prep-verify` 检查目标 hash。

### CR60 `cr60-intake`（材料优先输入绑定）

| 公开接口 | 位置 | 职责 |
|---|---|---|
| `build_intake(...) -> dict` | `engines/arbe/intake.py` | 读取显式输入和材料，返回 `cr60-analysis-intake.v1`；无远程副作用 |
| `CR60IntakeModule.run(...) -> ModuleResult` | `ai/modules/cr60_intake.py` | 暴露 Pi/CLI 契约，可选写本地 JSON artifact |

输入优先级为 `explicit_input` > 结构化材料/XLSX > key-value 文本；每个候选保留 `source`、`locator`、`method`、`priority` 和 `authoritative`，材料级保留 `sha256`。XLSX 默认识别当前 CR60 问题清单的 B/C/E/G/J 列（Ticket/触发功能/车型/触发版本/数据路径），但若存在可识别表头则优先按表头映射。批量问题单必须通过 `--match`、ticket 或数据文件名选择行，未匹配时不得把整张清单当成当前数据。

关键约束：

- 路径名只能作为低优先级提示，不能推断车型、COEM、软件版本或分支；
- 软件版本、车型、COEM、代码分支/版本到分支映射缺失，返回 `intake_status=needs_confirmation` 且 handoff `status=blocked`；
- 多个权威材料给出不同值，返回 `conflicts` 并 fail-closed；
- `/home/...`、UNC 等远程数据路径在本地只记录 `remote_unverified`，由数据准备 adapter 做远程存在性和 checksum 验证；
- `cr60-intake` 不执行 checkout、数据拷贝、CUDA 修改、编译、`bash start` 或 GDB。后续能力只消费已确认的 intake artifact。

### CR60 `cr60-precheck`（Sprint1 harness adapter）

`CR60PrecheckModule` 只负责输入校验、审批门和 provider 调度；实际 bag 解码、报警
事件、`frameID`、目标关联、ROI/source evidence、条件断点、`diagnosis_bundle.v1`、
`viewer-model.v1` 和 HTML 均由 sibling `cr60-debug-harness` 持有。输入模式为：

- `folder`：`harness_root`、下游 TOML `profile`、Linux/本地 `input_dir`、匹配的
  `analysis-context.v1` 或显式 `prepare_context=true`；
- `handoff`：上述 profile/context，加 `cr60-analysis-intake.v1`；`status=partial` 必须
  显式 `allow_partial=true`，`status=blocked` 永不执行；
- `manifest`：直接消费已准备好的 harness `intake-manifest.v1`（JSON/TOML），用于
  上游尚未生成统一 handoff 或回归已有 manifest 的场景；
- `execute=false` 是默认安全模式，只返回 shell-free argv 计划；只有用户确认后才设置
  `execute=true`。provider 使用 `subprocess.run(..., shell=False)`，对话文本不会成为命令；
- harness 返回非零但仍有 `batch_summary.json` 时，模块保留 `completed_with_case_failures`
  和全部 artifact，不把有效 case 丢掉。

provider 不解析 HTML，也不复制 harness 的 bag/parser/viewer；它只把 intake 转为
`intake-manifest.v1`，调用 `folder-analyze`/`batch-analyze`，并回传 argv、stdout、stderr、
返回码、harness JSON 和标准产物路径。

### CR60 `ros-topic-inventory`

该原子工具只读取已配置 ROS master 的 topic inventory，使用 allowlisted topic 名和
`SshCommandRunner` 的只读命令；不发布、不暂停、不调用 `rosbag play`。输出
`ros-topic-inventory.v1`，每个 topic 记录类型、publisher、subscriber、数量和
`data_observable`。topic 有 subscriber 但没有 publisher 时仍可记录其注册类型，但
`data_observable=false`，不能当作存在数据。
它特别用于识别 `wfObjectMsg`、`warning_status_with_frame`、`wfAutosarData`、live
XCP topic 之间的消息类型/发布者差异，不能把“有 subscriber”误判为“有数据发布”。

### M9 与 M1..M8 的关系

```
M1 (code-structure):  源码静态分析，无数据
M2 (signal-bridge):   CAN ↔ 内部变量映射（纯正则），无MF4数据
M3 (req-review):      需求审查 + 追溯，无代码
M4 (data-explore):    FrameStore 数据探针，无代码假设
M6 (diagnosis-panel): AI 诊断面板（分类+专家面板）
M7 (code-review):     代码 review 骨架
M9 (bsd-data-bridge): MF4 数据 + BSD 条件交叉验证，特定领域（BSD/LCW）
M10 (signal-audit):   BLF 数据 + 关键链路信号契约审计，确定性无 LLM
```

**M9 的独特性**：唯一需要读取 MF4 记录文件 + 加载 BSD 特定条件文件的模块。不依赖于 M1-M8 的任何输出产物。

**M10 的独特性**：BLF 数据 + DBC 值表 + 内置"开关链路契约"（旧 UI 雷达不回传 FCTA_FCTB_Status_S 等），输出确定性审计结果；诊断管线 Step 5 也复用 `engines.signal_audit.SignalAuditEngine` 做同样的审计（`orchestrator._run_signal_audit`），审计 markdown 注入专家面板上下文并作为报告固定章节。

---

## signal_audit.py — M10 Signal Audit

### 公开接口

| 签名 | 行号 | 职责 |
|------|------|------|
| `__init__(self, *, mf4_path=None, cases_dir=None, source_root=None, output_dir=None, pad_values=None)` | 108-120 | 构造函数，注入 MF4 路径和输出目录 |
| `run(self, *, mode: str, **kwargs) -> ModuleResult` | 190-207 | 主入口：`summary` / `index` / `validate` |
| `safe_run(**kwargs)` | inherited | BaseModule 安全包装，不抛异常 |
| `get_bsd_knowledge(self) -> dict` | 180-196 | 导出 BSD 知识（信号清单 + 条件 + PAD 值） |
| `register_cli(subparsers)` | classmethod, 209-225 | CLI 注册 |
| `from_cli_args(args)` | classmethod, 227-233 | CLI 参数 → 模块实例 |

### 运行模式

| 模式 | 描述 | 输入 | 输出产物 |
|------|------|------|---------|
| `summary` | 快速概览 BSD 信号在 MF4 中的覆盖率 | `--mf4-path` | 内存中返回，可选存 `bsd_signal_index.json` |
| `index` | 完整 BSD→MF4 通道映射（32 信号） | `--mf4-path` | 同上 |
| `validate` | PAD 条件 + MF4 数据交叉验证 | `--mf4-path` + `source_docs/*.json` | `bsd_dynamic_signals_full.json` + `bsd_cross_validation_report.json` |

### 关键数据结构

**BSD_SIGNAL_LIST**（第 29-62 行，32 个信号）：
```python
[
    {"signal": "egoSpeed_vxvRef", "keyword": ["EgoSpeed", "vxvRef", ...], "category": "GLOBAL"},
    {"signal": "obj_dx", "keyword": ["_dx", "AbsDx", "LongitudinalDx"], "category": "OBJECT"},
    ...
]
```
每个信号：`signal`（标准化名称）、`keyword`（MF4 关键词组）、`category`（GLOBAL/OBJECT/CONFIG/OUTPUT/...）

**DEFAULT_PAD_VALUES**（第 65-78 行，13 个 PAD 配置值）：
```python
{
    'BSDLCAIsoLineCOffset_F': 4.0,
    'BSDLCAExistProbThreshold_f': 0.6,
    ...
}
```

**validate 返回结构**：
```python
{
    "mode": "validate",
    "conditions": [  # 逐条件验证结果
        {
            "step": "1",
            "step_description": "...",
            "conditions": [
                {
                    "id": "bsd-trig-1",
                    "description": "...",
                    "type": "warning",
                    "signal_short": "existProb",
                    "pad_value": "0.6",
                    "sample_count": 13687,
                    "non_zero_count": 12,
                    "triggered": "YES" / "NO (all zero)" / "N/A",
                    "verification": "VERIFIED" / "NO DATA" / "SKIP (X)",
                }
            ]
        }
    ],
    "summary": {
        "total_conditions": 34,
        "verified": 34,  # 有 MF4 数据的条件数
        "verified_pct": 100.0,
        "activated": 28,  # MF4 实际触发过的条件数
        "constant_zero": 6,  # 有数据但未触发的条件
        "no_data": 0,
    },
    "pad_values_used": { ... },
    "dynamic_signals": { ... },
}
```

### 算法说明

#### `_index_signals()` — 信号索引

1. 加载 asammdf.MDF，获取 `channels_db.keys()`
2. 对 BSD_SIGNAL_LIST 每个信号，用 `keyword` 列表对 MF4 通道名做子串匹配（大小写不敏感）
3. 去重后返回 `found` 布尔 + `mf4_matches` 列表

#### `_read_dynamic_signals()` — 动态信号读取

1. 遍历 MF4 `channels_db`，匹配 BSD 输出信号关键词（8 组）
2. 对每个匹配通道，用 `mdf.get(name, group=G, index=I)` 处理重复通道
3. 返回样本统计：采样数、非零数、非零占比、数值范围

#### `_validate_conditions()` — 条件验证

1. 加载 `source_docs/BSD_conditions.json` → 条件步骤列表
2. 加载 `source_docs/gen5_bsd_signal_mapping.json` → 变量到信号映射
3. 对每个条件：
   - 匹配 PAD 值（变量名子串匹配 `DEFAULT_PAD_VALUES`）
   - 匹配 MF4 信号分析（非零计数、采样数）
   - 判定验证状态：`VERIFIED`（有数据）/ `NO DATA`（无数据）/ `SKIP (X)`（数据问题）
   - 判定是否触发：`YES`（非零 > 0）/ `NO (all zero)` / `N/A`

#### `_analyze_samples()` — 样本分析

对信号样本做统计分析：
- `status`: OK / ALL_ZERO / NO_DATA / ERROR_READING / TUPLE_DATA
- `sample_count`: 总样本数
- `unique_first20`: 前 20 个唯一值
- `non_zero_count`: 非零样本数
- `non_zero_pct`: 非零占比（%）
- `non_zero_min/max`: 非零最小/最大值
- `time_range_s`: 时间范围（秒）

### 依赖关系

```
bsd_data_bridge.py
  ├── .base.BaseModule             # BaseModule, ModuleResult
  ├── asammdf                      # MF4 读取（可选依赖，通过 _is_mdf_available() 检查）
  └── source_docs/                 # JSON 输入
        ├── BSD_conditions.json    # BSD 条件树（ConditionExtractor 产出）
        └── gen5_bsd_signal_mapping.json  # PAD/变量映射（signal_mapper 产出）
```

### 与其他模块的协作

| 消费方 | 协作方式 | 说明 |
|--------|---------|------|
| orchestrator | 无直接集成 | M9 为独立模块，目前不被诊断管线调用 |
| auto_dream | 可集成 | 在 Phase 0 后增加 `_run_bsd_validation` 步骤，定期验证 BSD 条件一致性 |
| data_diagnostics (M4) | 互补而非嵌套 | M4 是无假设探针，M9 是 BSD 特定验证；二者输入可共用 MF4 文件 |
| signal_bridge (M2) | 互补而非嵌套 | M2 做 CAN/internal 映射，M9 做 BSD 信号关键词匹配；映射结果可辅助 M9 |
| code_learner | 互补 | CodeLearner 学习 BSD 源码知识到 `memory/code_knowledge/BSD.json`，M9 做 MF4 验证 |

### 已知约束与注意事项

1. **asammdf 是可选依赖**：模块在构造时不要求安装，`run()` 时通过 `_is_mdf_available()` 检查；缺失时返回 `ModuleResult.fail()` 而非抛异常
2. **`BSD_conditions.json` 是硬性依赖**（validate 模式）：文件不存在时返回 `ModuleResult.fail()`，不自行生成
3. **`gen5_bsd_signal_mapping.json` 是软依赖**：不存在时仅记录 warning，PAD 查找会降级为仅用 `DEFAULT_PAD_VALUES`
4. **MF4 重复通道**：同一通道名出现在多个 group 时，通过 `mdf.get(name, group=G, index=I)` 精确定位
5. **信号关键词匹配是启发式的**：可能有误匹配或漏匹配，validate 结果需人工复核关键条件
6. **PAD 值默认值源自历史经验**：可能不准确，建议从 `source_docs/gen5_bsd_signal_mapping.json` 覆盖
7. **不缓存 MF4 解析结果**：每次 validate 重新读取 MF4 文件，避免 stale data
8. **输出文件使用原子写**（如需要）：当前使用直接 `open().write()`，可改为 `atomic_write_json`（与 condition_extractor 一致）

---

## code_learn.py — V4 P5 代码学习（AST 建图）

### 概述

`CodeLearnModule`（name=`code-learn`）是 P5 的 `code_learn` 入口：激活 `ai/codegraph/CodeGraphBuilder` 对源码建 AST 图（`use_ast=True`，tree-sitter 不可用时自动回退 regex），并把索引增量刷新到 variant 的 codegraph DB。确定性、无 LLM，供 pi 在分析前主动建图/增量更新。

### 公开接口

| 项 | 值 |
|----|----|
| class | `CodeLearnModule(BaseModule)`（`ai/modules/code_learn.py`） |
| CLI | `python cli.py code-learn [--rebuild] [--aggressive] [--no-ast] [--source-root ...] [--db-path ...]` |
| run kwargs | `rebuild`（删旧 DB 强制全量）、`aggressive`（AST 全量 = rebuild+ast）、`no_ast`（强制 regex）、`use_ast`（默认 True） |
| 产物 | `ModuleResult`：`build_type`（full/incremental/skip）、`nodes_added`、`edges_added`、`files_scanned`、`files_changed`、`duration_sec` |

### 行为

- **建库/刷新**：复用 `CodeGraphBuilder(db_path, source_root, key_files, func_keywords, calib_files, use_ast, source_docs_dir, variable_filter)`。calib_files 从 key_files 里按 `paraDefine`/`structDefine`/`globalVarDefine` 过滤得出。
- **无 key_files 兜底**：未配置 `key_source_files` 时扫描源码根 `.c/.cpp/.h/.hpp` 相对路径（上限 800），避免空建。
- **db 路径**：默认经 `resolve_codegraph_db(config, Path.cwd())` 解析；`--db-path` 可覆盖。
- **幂等**：文件无变化时返回 `build_type="skip"`，不重写图。

### 与其他模块协作

| 消费方 | 说明 |
|--------|------|
| pi (P1) | 分析前主动调 `code-learn` 确保 codegraph 新鲜；`code-analyze` 查询同一 DB |
| code-analyze | `code-learn` 建的图即 `code-analyze` 的查询源 |

### 已知约束

1. `use_ast=True` 依赖 tree-sitter；不可用时 builder 自动 `warning` 回退 regex，`use_ast=False`
2. Gen5 平台 builder 内部强制 regex（tree-sitter-cpp 兼容问题）
3. 全量重建（`--rebuild`/`--aggressive`）会先删除旧 DB，属破坏性操作，仅在明确要求时使用

---

## code_analyze.py — V4 P5 代码分析（调用链/依赖/语义）

### 概述

`CodeAnalyzeModule`（name=`code-analyze`）是 P5 的 `code_analyze`：封装 `ai.query.CodeGraph` 的查询接口，回答函数定义、调用链、信号/变量访问、标定、统计等问题。确定性、无 LLM，供 pi 在"代码调用逻辑"分析时复用。

### 公开接口

| 项 | 值 |
|----|----|
| class | `CodeAnalyzeModule(BaseModule)`（`ai/modules/code_analyze.py`） |
| CLI | `code-analyze --kind {function\|callers\|callees\|call_chain\|signals_of\|vars_read\|vars_written\|conditions\|calib\|stats} --name F --max-depth N` |
| KINDS | `function`（节点）、`callers`/`callees`（调用者/被调用者名）、`call_chain`（递归调用链）、`signals_of`、`vars_read`/`vars_written`、`calib`（category 过滤）、`stats`（图统计） |
| 依赖 | codegraph.db（`resolve_db` 解析或 `--db-path`） |

### 行为

- 每个 kind 直接映射到 `CodeGraph` 查询；结果经 `_to_jsonable`（dataclass→dict）序列化。
- `callers`/`callees` 取 `caller_name`/`callee_name` 去重、最多 50 条。
- `calib` 的 `--name` 作为 category 过滤（可空）。
- Graph 不可用（无 db）时返回 `ModuleResult.fail`，不抛异常。

### 与其他模块协作

| 消费方 | 说明 |
|--------|------|
| pi (req-analyze 未来) | 需求-代码 gap 分析依赖 `code-analyze` 的调用链 |
| code-learn | 消费其构建的图；二者共用同一 codegraph.db |

### 已知约束

1. `call_chain` 结果按 `depth` 递增、包含 `path`（`A -> B -> C`）与 `func_id`
2. 查询是只读的，不触发建图；图不存在时请先运行 `code-learn`
3. Gen5/gen6 路径差异由 codegraph.db 构建期决定，查询侧无需感知 platform

---

## req_analyze.py — V4 P7 需求→代码 gap 分析

### 概述

`ReqAnalyzeModule`（name=`req-analyze`）做"需求→代码 gap"：加载需求 YAML → 需求→信号
trace（复用 `RequirementTracer`）→ **逐条核对需求声明的 `linked_functions` 是否在
CodeGraph 中真实索引**，缺失项输出 `violations`，全部输出 `requirement_trace`。
确定性、默认无 LLM；P7 同时验证"新增模块后 pi 工具目录自动出现，无需改核心（Q5）"。

### 公开接口

| 项 | 值 |
|----|----|
| class | `ReqAnalyzeModule(BaseModule)`（`ai/modules/req_analyze.py`） |
| CLI | `python cli.py req-analyze --req-dir <dir> [--variant <id>] [--max-trace N]` |
| run kwargs | `req_dir`、`variant_id`、`max_trace`（violation 上限）、`db_path` |
| 产物 | `requirement_trace`（list）、`violations`（list）、`checked`（统计）、`n_reqs` |
| 依赖 | `ai/requirements/loader`+`tracer`、codegraph.db（`resolve_codegraph_db`） |

### 行为

- 需求加载：`RequirementLoader.load_yaml_dir`（V3 与 RequirementSpec 两种 schema）。
- trace：复用 `RequirementTracer`（需求→信号→源码，coverage full/partial/none）。
- code-gap：对每个 `linked_functions` 调 `CodeGraph.get_function_by_name`；缺失 →
  violation（含 `requirement_id` / `priority` / `function` / `reason`）。
- **鲁棒**（Q4）：无 CodeGraph 时降级为"无法核对"，不硬判 violation；
  violation 去重 + 上限 `max_trace`（默认 5）。

### 与 pi 的关系

- 属于 P7 "扩展示例"：新增即自动进 `MODULE_REGISTRY` / `capability_catalog()`，pi
  工具目录无需改核可直接发现（验证可插拔）。

---

## sim_verify.py / engines.arbe — V4 P4 仿真验证

### 概述

`SimVerifyModule`（name=`sim-verify`）解析本地 trace/KPI 或远程公共 ROS 回放产出，
供 Pi 调度验证。本地和远程 provider 都在 `engines/arbe/`；远程公共 capture 已接通。

### engines/arbe 分层

| 提供者 | 文件 | 说明 |
|--------|------|------|
| `ArbeReplayProvider`（抽象） | `engines/arbe/replay_provider.py` | submit / poll / fetch_trace / fetch_kpi |
| `LocalArbeReplayProvider` | `engines/arbe/replay_provider.py` | 解析本地 trace csv；优先使用 case/runtime schema 的 warning mapping，无映射时保留 `wN` |
| `RemoteArbeReplayProvider` | `engines/arbe/remote_replay.py` | SSH 公共输出 capture 已接通；legacy trace job API 保留兼容语义 |

> P4 计划把 local/remote 放在单独 `local_replay.py`/`remote_replay.py`；实际 local 实现
> 内联在 `replay_provider.py`（同一 provider 文件），remote 独立 `remote_replay.py`。

### 已知约束

1. local 模式为同步读取（`submit` 直接返回 case_dir；`poll` 依据文件存在）。
2. `remote_public` 通过注入的 SSH/scp runner，在已有 ROS/arbe 会话中执行短窗口
回放、录制公共 topic、拉回 capture JSON；执行需要 `approved=true`，不安装或修改远端代码。
3. `sim-verify` 支持 `--mode local` 和 `--mode remote_public`；远程模式必须提供
server_host、remote_bag_path、remote_capture_base，并把结果交给 `public-runtime-normalize`。
4. `object_association_mode=publication_order` 只有在当前 source 分析证明
objectlist→warning_status_with_frame 是同周期发布顺序时才能选用；默认 `strict`。
5. local replay 的结构化结果为 `arbe-replay-result.v1`；trace warning 位只有在当前
runtime schema/显式输入提供映射时才显示功能名，否则保持 `wN`。

---

## capability/project_context.py — V4 P6 多项目隔离

### 概述

`project_context` 把 variant/project_key/case_dir 解析为隔离的项目上下文
（workspace/memory/codegraph/source_docs/snapshots），并提供 **fail-closed** 跨项目
门禁（P6 验收红线）。复用 `config.resolve_*` 单一来源。

### 公开接口

| 项 | 值 |
|----|----|
| `resolve_project_context(config, root, variant_id=, project_key=)` | → `ProjectContext` |
| `resolve_project_context_from_case(config, root, case_dir)` | case.yaml/metadata 匹配 variant，回退 default |
| `guard_project(ctx, path, what=, on_mismatch=)` | `raise`（默认，抛 `ProjectIsolationError`）/ `ignore`（返回 False） |
| `ProjectContext.contains(path)` / `.namespace()` | 路径归属判断 / 记忆命名空间 key |

### 行为

- 每个 variant 的 workspace/memory/索引隔离到 `.workspaces/<variant>/`（或 variant
  命名空间全局目录），两个 variant 的 `namespace()` 不同。
- `guard_project` 拒绝其他项目的 memory/workspace 路径（fail-closed）；空路径放行。
- 会话绑定：`PiModule._derive_session_dir` 从项目上下文派生根目录。
- 测试：`tests/test_project_isolation.py`（6 条离线用例）。

---

## 模块开发规范（适用于所有 ai/modules/*）

### 文件结构标准

```python
# -*- coding: utf-8 -*-
"""
ModuleName (M#) — 一句话定位描述。

使用示例：
    python cli.py module-name --mode X
    from ai.modules.module_name import ModuleName
    res = ModuleName().safe_run(mode="X")
"""
from __future__ import annotations

# stdlib — 按字母序
import json
import logging
from pathlib import Path
from typing import Any

# 项目内部 — 相对导入
from .base import BaseModule, ModuleResult

log = logging.getLogger(__name__)

# ── 常量定义 ──────────────────────────────────────────────────────────
CONSTANTS: list = [...]

# ── 模块类 ───────────────────────────────────────────────────────────
class ModuleName(BaseModule):
    name = "module-name"
    description = "一句话描述"

    def __init__(self, *, ...):
        ...

    # ── 私有方法（按运行时序分组） ──────────────────────────────────
    def _helper1(self) -> ...:
        ...

    def _helper2(self) -> ...:
        ...

    # ── 主入口 ──────────────────────────────────────────────────────
    def run(self, **kwargs: Any) -> ModuleResult:
        ...

    # ── CLI ─────────────────────────────────────────────────────────
    @classmethod
    def register_cli(cls, subparsers: Any) -> Any:
        ...

    @classmethod
    def from_cli_args(cls, args: Any) -> "ModuleName":
        ...
```

### 编码规则

1. **`__future__` 注解**：文件首行之后必须立即 `from __future__ import annotations`
2. **模块级别日志器**：`log = logging.getLogger(__name__)`，用 `log.exception/debug/info()` 而非 print
3. **`Any` 类型提示**：所有 `**kwargs`、`Any`、`Optional` 必须标注类型
4. **`try/except` 保护**：
   - 每个模块的导入在 `__init__.py` 中使用 `try/except` 保护
   - 模块内可选依赖在运行时通过 `_is_*_available()` 检查
   - 不允许模块中 `raise` 异常跨越模块边界（用 `ModuleResult.fail()` 代替）
5. **`ModuleResult` 必须作为 run() 的唯一返回值**：
   - 成功：`ModuleResult.success(message="...", module=self.name, key=value, ...)`
   - 失败：`ModuleResult.fail("error message", module=self.name, context=...)`
6. **CLI 注册必须实现** `register_cli()` 和 `from_cli_args()` — 即使只读入 base
7. **模块名命名**：短横线分隔（`bsd-data-bridge`），类名 PascalCase + `Module` 后缀
8. **模块编号**：M1-M8 已分配，M9 留给 BSD，M10+ 留给新能力
9. **`__all__` 导出**：在 `__init__.py` 的 `__all__` 中追加模块类名
10. **模块必须 self-contained**：不依赖其他模块的输出产物，可通过构造函数注入协作数据

### 测试规范

1. **冒烟测试**：每个新模块必须有对应的 `tests/test_<module_name>_smoke.py`
2. **冒烟测试内容**：
   - 模块可实例化
   - `register_cli()` 不抛异常
   - `safe_run()` 返回 `ModuleResult`（无论 ok 或 fail）
3. **数据注入测试**：通过构造函数注入模拟数据，测试 `run()` 的核心逻辑分支
4. **集成测试不要求**：模块设计为独立可运行，集成测试由 orchestrator 覆盖

### 文档维护

1. **本文件 AGENTS.md 必须与代码同步更新**：
   - 新增/删除/重命名模块 → 更新模块概览表 + 本行引用
   - 修改公开 API → 更新 "公开接口" 表格
   - 修改数据结构 → 更新 "数据结构" 段落
   - 修改常量/阈值 → 更新对应的值
2. **根目录 AGENTS.md "跨模块依赖速查表"**：如果新模块产生/消费其他模块的输出，必须在此表添加对应行
3. **代码评审 Checklist**（针对 modules/ 目录）：
   - [ ] 公开接口签名与代码一致
   - [ ] ModuleResult 返回格式正确（ok/data/message/artifacts）
   - [ ] 可选依赖有防护（try/except 或 _is_*_available）
   - [ ] CLI 注册有 `--help`
   - [ ] 无 print/debug 残留
   - [ ] 模块不修改其他文件（除非是明确的 output）

## Runtime evidence modules（DDD / Pi 原子链）

文件：`ai/modules/runtime_evidence.py`；确定性实现：`engines/runtime_evidence.py`。

| 模块 | 输入 | 输出 | 允许副作用 |
|---|---|---|---|
| `runtime-evidence-normalize` | `gdb-session.v1` / transcript 或 `runtime-snapshot-with-frame.v1` + 显式 run/binding | `runtime-case-evidence.v1` | 无 |
| `runtime-evidence-validate` | runtime artifact，可选静态 bundle | validation + source/data/binary/event binding | 无 |
| `runtime-evidence-compose` | 两个已规范化 runtime evidence producer | composite `runtime-case-evidence.v1`，保留 runs/layers/observations | 只写用户指定本地产物 |
| `runtime-evidence-merge` | 静态 `diagnosis_bundle.v1` + runtime artifact | additive merged bundle + `runtime-evidence-merge.v1` | 只写用户指定本地产物 |

`gdb-service` 不被这三个模块反向依赖；它仍然只生产通用 GDB session。规范化器现在同时
接受 `public-runtime-normalize` 的 `runtime-snapshot-with-frame.v1`，将 warning/radar_info
和 objectlist 投影为 `runtime_with_frame`/`objectlist_candidate` observations，再复用同一
validate/merge 链；这不是新增 public runtime 工具。规范化器支持
显式 `CR60_RUNTIME` marker、实验 adapter 的 uppercase marker 和旧版 replay detail
兼容提升。marker 没有 `field_token` 时只能使用调用方提供的 `marker_field_map`，不把
 marker key 猜成代码变量。merge 会保留 `alarm_events/frame_evidence` 原值，并且只在
source context、source snapshot、数据路径等身份没有冲突时挂可消费的 event overlay；
binary fingerprint 缺失显示 `partial`，冲突显示 `blocked`。

runtime-evidence-merge 支持可选 scope（event_id/frame_ids/object_ids），按当前事件物化小窗口；
完整 runtime artifact 保持独立并通过 artifacts 引用。未提供 scope 时保持 full merge 兼容行为，
但大规模逐帧公共数据应由 Pi 默认使用事件 scope，避免把无关帧带入 HTML/merge。

GDB 执行态会在 `p/print` 前加入字面量 `CR60_GDB_EXPR` marker，避免多 stop 场景中的
`$N` 顺序错配；plan-bound runner 进一步通过可恢复 probe 对每个 expression 单独捕获
作用域错误，后续断点不会因一个 `No symbol` 中止。原始 `commands` 与实际
`execution_commands` 都进入 session；规范化会把 `CR60_GDB_ERROR` 归回对应字段并标为
`not_found`，不会创建 `observed=null` 的伪 observation。无 marker 且多次 stop 的旧
transcript 会 fail-closed 为 `unmarked_expression_mapping_ambiguous`。重复执行同一
plan 时，runner 用 `RESULT_PREFIX` 区分 `target.run_id`，便于跨 session comparison。
`No symbol`/`optimized_out` 仍是字段级缺口；只有 ptrace/attach、内存、runner/rosbag 或
GDB script 失败才会把 runtime `disturbance` 升级为 `suspected/confirmed`，避免把正常的
宏/枚举不可见误解为回放被扰动。

`PiContextModule` 可通过 `runtime_evidence`/`runtime_evidence_path` 接收同一 artifact，
并可选传入 `diagnosis_bundle`/`diagnosis_bundle_path` 做绑定校验。Pi context 只嵌入
deterministic runtime summary（token、值、phase、调用栈、geometry、diagnostics），
AI 不得改写事实。

### `RuntimeDebugPlanModule`

文件：`ai/modules/runtime_debug_plan.py`；确定性实现：`engines/runtime_debug_plan.py`。

输入为 `diagnosis_bundle.v1`、可选 `arbe-preflight.v1`、source/binary context 和权限状态；
输出为 `runtime-debug-plan.v1`。该模块只读取当前事件已有的 `breakpoint_pack`，不在
HTML/Pi 层重新推断函数或变量，因此代码变化后可由上游 code/harness 重新生产。输出同时
提供 `gdb_commands`、`vscode_handoff`、`capture_fields` 和 readiness gates，可通过 typed
artifact reference 传给 `gdb-service`。缺少 binary identity、HILMODEL、唯一目标、精确
frame 或 source cleanliness 时分别标记 warning/blocked，不自动执行远程回放或 GDB。

### `RuntimeDebugRunModule`

文件：`ai/modules/runtime_debug_run.py`；实现：`ai/providers/cr60_harness.py` + sibling
`tools/run_gdb_isolated_smoke.py`。

它是执行侧 provider adapter，不重新解释 plan、不生成 feature-specific 断点。默认只返回
`shell=False` 的 harness argv；`execute=true` 且 supervisor/用户显式批准后，才允许启动
隔离 ROS master、回放指定 radar LGU 和 GDB，并通过 `--session-output` 生成
`gdb-session.v1`。正式 workspace 的 `bash start`/existing PID attach 不由此模块隐式替代。

### `RuntimeDebugAttachModule`

文件：`ai/modules/runtime_debug_attach.py`；provider：`Cr60HarnessProvider.run_gdb_attach_plan`；
sibling runner：`tools/run_gdb_attach_plan.py`。

该模块只消费已校验的 `runtime-debug-plan.v1`，在正式 ROS master 中重新发现
`/radar{radar_id}_visualization_engine/arbe_visualization_engine`，读取 node PID，并要求
`readlink -f /proc/<pid>/exe` 与 profile 的 program 完全一致后才允许 attach。它不启动或
停止正式进程；`replay=true` 也必须由审批显式打开。node/PID/executable 不可证明时产出
`gdb-session.v1(status=blocked)`，不会按相同可执行文件名猜测 radar。
`blocked` 结果还携带需审批的 `runtime-debug-run` fallback 引用；如果调用方提供了
session 输出路径，fallback 会生成不同的 isolated 输出路径，不能覆盖 formal attach 的
审计 artifact。

### `ArbeFormalStartModule` / `ArbeFormalStopModule`

`arbe-formal-start` 的 provider runner 先检测已有正式节点，再检查 start 脚本和
`sudo -n`，之后以 `setsid bash <workspace>/start` 创建可追踪的 process group，产出
`arbe-start-session.v1`。`ownership=tool_started` 是停止的必要条件；发现已有用户进程时
只返回 `already_running/ownership=external`，不接管也不清理。

`arbe-formal-stop` 只接受 owned session，远端再次核对 PID、PGID、workspace 和命令行，
仅在 process group 与 start PID 一致且 owner 证据成立时发送 TERM/KILL；任何校验失败都
返回 blocked，并保留原因。

### `ArbeBuildModule`

文件：`ai/modules/arbe_build.py`；确定性实现：`engines/arbe/build.py`。

该模块只构造并执行显式 `source ROS setup && cd <arbe_root> && catkin_make [args]`，参数
通过 token 校验，不接受换行、分号、反引号或 `$` 等 shell 片段。source/branch/CUDA
准备和 `bash start` 是独立阶段；执行结果保存为 `arbe-build-session.v1`，包含命令、返回码、
耗时、stdout/stderr 和失败状态。默认 plan-only，`execute=true + approved=true` 才触发
远程 build。

## `PiContextModule`（DDD / Pi 编排上下文）

文件：`ai/modules/pi_context.py`；确定性实现：`engines/pi_context.py`。

`PiContextModule(name="pi-context")` 把显式的 `intake`、`preflight`、数据目录、
variant/project、replay/radar、freshness 和 policy 组装为
`pi-orchestration-context.v1`。它不是 LLM 摘要器，也不从路径名称猜测身份。

公开输入：

| 输入 | 说明 |
|---|---|
| `intake` / `intake_path` | `cr60-analysis-intake.v1` 内联对象或 JSON artifact |
| `preflight` / `preflight_path` | `arbe-preflight.v1` 内联对象或 JSON artifact |
| `case_dir` | 没有 intake 时的数据目录指针 |
| `project_id` / `variant_id` | 只有显式提供才写入身份 |
| `replay_strategy` / `radar_id` | 运行策略/雷达选择，来源标记为 explicit |
| `runtime_evidence` / `runtime_evidence_path` | GDB/public runtime 证据；经 schema 和 binding 校验后进入 `runtime.evidence` |
| `diagnosis_bundle` / `diagnosis_bundle_path` | 可选静态 bundle，用于验证 runtime 是否属于同一数据/源码上下文 |
| `policy` / `artifact_refs` | 审批策略与上游 artifact 引用 |
| `capability_manifest` / `capability_manifest_path` | 当前 Gen6 capability categories、unsupported、freshness 和 fingerprint；只嵌入有界摘要 |
| `output` | 可选的 context JSON 输出路径 |

输出至少包含 `schema_version/status/run_id/context_fingerprint/project/data/source/build/runtime/policy/`
`artifacts/freshness/missing/conflicts/diagnostics`。source 或身份不完整时输出
`partial`，缺少 case、artifact 无法读取或 intake 已 blocked 时输出 `blocked`；
不以默认值替代缺口。

当没有 `intake`/`case_dir` 时，若调用方提供了 `diagnosis_bundle.v1`，模块可以从
bundle 的 `case.bag`、`provenance` 和 `source_context.identity` 绑定 data/source，并
从 `runtime-debug-plan.v1` 读取显式 strategy/radar；这些字段均标注
`diagnosis_bundle...` 或 `runtime_debug_plan` provenance。若 bundle 也没有明确数据路径，
仍必须返回 `blocked`，不能从文件夹名或 bag 文件名猜测身份。

### Pi 入口规则

`PiContextModule` 由 registry 自动进入 Pi Extension catalog；Pi Extension 的实际
调用只经过 `ai.capability.pi_tool_bridge`。`python cli.py pi-context` 仅为开发/测试
入口，不能被写成第二套用户编排流程。

可选接收 `capability_manifest`/`capability_manifest_path`。模块只嵌入 manifest 的有界摘要和
artifact ref；会比对 schema、project/variant identity 与 source_snapshot_hash，发生不一致直接
blocked，manifest status=partial 则 context 为 partial。

## `ProjectCapabilityManifestModule`

文件：`ai/modules/project_capability.py`；确定性实现：`engines/project_capability.py`。

`project-capability-manifest` 不是诊断器，也不替代 `pi-context`。它读取显式的 intake、
preflight、code-context、runtime snapshot、diagnosis bundle 和可选项目声明，生成
`project-capability-manifest.v1`，让 Pi 先知道当前项目能可靠使用哪些能力以及缺哪些输入。

它只把 source/data/runtime/presentation 的已证明状态放入 capability category，并保留每个
artifact 的 schema/hash/path provenance；缺失能力进入 `unsupported`，不会从车型、功能名、
仓库目录名或 bag 文件名推断。source snapshot 存在且 code-context ready 时才标记 freshness
为 fresh，否则为 unknown/partial。显式项目声明只能 additive，不能覆盖 artifact 事实。多个
输入 artifact 的 source_snapshot_hash 不一致时返回 blocked、freshness=conflict，并将
source-consistency 放入 unsupported；这比把冲突留给下游更安全。

## `CodeContextRefreshModule` / `CodeContextReadModule`

文件：`ai/modules/code_context.py`；确定性实现：`engines/code_context.py`。

`code-context-refresh` 接受显式 `source_root`，用内容 SHA-256 形成当前源码快照，复用
`CodeGraphBuilder`，产出 `code-context.v1`、`code-index.v1` 和隔离的 CodeGraph DB。
同一 source/identity 且 hash 未变化时直接复用；不允许把已绑定另一 source root 或项目身份
的输出目录覆盖。`--no-git-probe` 适用于由远程 source mirror 提供 git identity 的场景。
`code-context-read` 只从 index 读取有界 section，不重新扫源代码。

## `EventCodePathModule`

文件：`ai/modules/event_code_path.py`；确定性实现：`engines/event_code_path.py`。

输入为上游事件和 `code-index.v1`/`code-context.v1`，输出 `event-code-path.v1`。它按真实
函数或输出信号解析唯一函数，输出五层导航和 `code-gdb-plan.v1` root plan；函数缺失/歧义
返回 `blocked`。它不执行 GDB、不固定 FCTA/FCTB、不评价最终根因。

## `PublicRuntimeNormalizeModule`

文件：`ai/modules/public_runtime.py`；确定性实现：`engines/arbe/public_runtime.py`。

输入是 collector 采集的 warning/radar_info/objectlist 行或 capture JSON，输出
`runtime-snapshot-with-frame.v1`，并可按外部 source-derived warning mapping 计算 0→非零
上升沿。默认 strict：只有消息自带 frame 或明确 callback 才关联对象；当前 arbe `wfObjectMsg` 只有
publish timestamp 时，行进入 `unbound_objects`。若当前 source 已证明同周期发布顺序且 capture
保存消息序号，调用方可显式选择 `publication_order`，对象标记为 derived `publication_correlated`。
Pi/SimVerify 的 `auto` 模式会读取 `arbe-preflight.v1.public_evidence.objectlist_frame_contract`，
只有 `status=source_verified` 才自动选择该模式，否则退回 strict；不按时间戳猜同帧。
当前远程公共 capture 由既有 `sim-verify` 调度；该模块本身不订阅 ROS、不播放 bag。
对当前 arbe 的 `wfSObj`，调用方可按 source 证据选择 `object_validity_policy=arbe_wf_sobj`，
将 GUI 明确跳过的 `ID<0` 占位行放入 `ignored_objects`；默认 preserve，不静默删除原始行。

## V4 S1C：三个用户出口

`evidence-query` 是已有证据 artifact 的通用切片模块，不读任意远程 shell、不重新解析 bag，
也不把字段名映射成平台自定义别名；`diagnosis-report` 是确定性报告投影，负责把事件索引、
选中帧、ego/target/index、代码链、runtime association、缺口、next actions 和可选的
`diagnosis-panel` inference 组合成 `diagnostic-report.v1`。Pi 通过 catalog 自动发现这两个
模块，并可用它们完成“批量预检查 → 选事件详细报告 → 按意图追问”的三出口流程。

`evidence-query` 的普通 Pi 响应默认不展开完整详情，并用 `max_field_rows` 限制 list-heavy
字段；需要完整冻结事件时才传 `include_details=true`。`diagnosis-report` 默认写出完整 JSON/
Markdown/HTML，但通过 `response_mode=summary` 给 Pi 返回小摘要和 `details_ref`，避免报告正文
再次进入模型上下文。

`diagnosis-report` 的 `output_endpoint`/`can_data_status` 是跨功能的业务口径输入：默认
`auto`/`algorithm` 以 arbe 可视化工具报警灯对应的算法输出作为端点；只有用户明确要求
`can_tx` 时才将 CAN Tx 作为下游辅助端点。报告的 `output_policy`、`alarm_assessment` 和
`conclusion` 必须保持一致，算法输出层的观察结果不能伪装成 CAN 上升沿，CAN 缺失也不应
在主结论中反复强调。
`gdb_session_path` 可选绑定 `gdb-session.v1`，报告会把“runner 成功”和“同帧/同目标命中”
分开显示；运行时 probe 缺失只进入缺口，不覆盖已确认的报警状态。

报告还输出 `diagnostic_narrative.output_chain` / `diagnostic-story.output_chain`（契约
`diagnostic-output-chain.v1`）：自然语言和 HTML 会继续说明算法输出之后的真实内部 token、
对外 signal expression、生产函数和 transport 调用点。`arbe-preflight` 提供的
`can_output.source_output_chain` 只证明当前 source 中存在或缺少词法赋值路径；只有 GDB/public
runtime observation 才能把内部字段标为 `runtime_observed`。因此报告可以明确回答“代码链路到哪里”，
但不会把静态映射候选写成该 frame 已发送。

报告同时发布 `diagnostic-analysis-flow.v1` 读模型，供 HTML 按当前 source 的实际
caller/helper→event root→callee 条件链呈现中间过程，再连接几何/预测和输出结论。它消费
condition trace 的真实绑定，不新增功能规则；条件的 `not_evaluable`/`unsupported` 必须在
流程卡片中保留。Pi/工具结果的 `response_mode=summary` 只返回这份有界摘要和 artifact ref，
完整条件/连续帧/GDB transcript 留在本地报告中，不重复进入模型上下文。

报告场景图必须保留当前几何和算法预测两个层次。当前 polygon 与 ROI 的关系由确定性几何
投影计算；源码中 ROI `num` 分支只作为 source-derived gate，runtime 中当前代码实际命名的
交点/穿越点坐标与时间 token（例如 `fInterX/fInterY/fTTMY`）作为独立预测证据。新增功能
不得在 HTML 层写死“报警即相交”，应由当前
source/code-context 和 runtime token 提供对应分支。

`alert-timeline` 是独立的跨证据层投影能力：它只消费已有 bundle/viewer/runtime artifact，输出
`alert-timeline.v1` 的报警行、播放帧 map、层间 compare 和 identity conflict；它不重新解析 bag，
也不固化任何功能规则。`diagnosis-report` 内部复用同一 engine，保证 Pi 单独查询和详细报告
使用同一语义；报告还通过 `diagnostic_narrative` 生成条件命中文字和保守的 `should_alert`，
不能替代 exact runtime/CAN 证据。

`PiModule.discover_case_artifacts()` 会优先读取 case 目录内的 artifact；当 sibling harness 按
`batch-index.json` 将 `cases/<case_id>` 与 `data/<case_id>` 分开输出时，按 manifest 的显式
`case_id`/`data_id` 解析 viewer-model、viewer report、runtime schema 和 bundle companion，
并把它们作为 artifact refs 提供给 Pi，不从文件名猜车型或功能。`_select_pi_tools()` 只按
用户意图选择当前 live catalog 中的有限工具 allowlist，解决某些 provider 面对全量 catalog
不稳定选工具的问题；它不改变 Pi 的规划权，也不绑定 FCTA/FCTB。用户可通过 `tools` 显式
覆盖 allowlist。

`analysis-run-update` 还可在恢复时增量写入 `binding` 和 `artifact_refs`；已存在的 source/data/
binary 字段发生冲突会返回 `conflict`，Pi 不应忽略该结果继续生成代码或 runtime 结论。
