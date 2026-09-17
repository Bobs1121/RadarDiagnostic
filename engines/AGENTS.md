# engines 维护说明

`engines/` 只放可确定性复现的领域逻辑。引擎不依赖 Pi，不调用 LLM，不执行
远程副作用；Pi 通过 `ai/modules`/`BaseTool` 调度它们。

新增引擎必须提供：

- 明确输入、输出、证据等级和缺口状态；
- source/data/runtime provenance（适用时）；
- 正常、缺输入、冲突和不支持路径的单元测试；
- 对应 DDD 用户故事和 contract 引用。

`analysis_ledger.py` 是阶段性调查过程的确定性持久化边界。它使用 run 目录、原子 JSON
替换、append-only `events.jsonl` 和跨进程 lock，保存 `AnalysisRun`、`AnalysisStep`、
`Claim`、`Hypothesis`、`DebugExperiment` 和 `user-observation`。它不运行 LLM、不计算根因、
不读取 HTML。关键门禁：

- AI 创建的 claim 不能标记为 `observed`；
- observed claim 必须有 evidence ref；
- step 只能从 `running` 完成一次，重复完成是 conflict；
- run/step/claim ID 必须是安全组件，不能目录穿越；
- 每个 mutation 更新 event sequence，可从中断后恢复；
- `update_run()` 可增量绑定 source/data/binary identity 和 artifact refs；已绑定字段发生漂移时抛出 `LedgerConflict`，避免恢复时串用另一项目。
- step metrics 聚合到 run，旧 step ref 缺少关键 gap 计数时只读回查 entity；
- `confirmed_by_user` 只能由 user actor 写入；非用户只能更新候选状态；
- DebugExperiment 必须先以 `planned` 建立计划，才允许记录 `completed/partial/failed` 结果；
- `user-observation` 固定为独立层且 `runtime_eligible=false`，必须经过 runtime normalizer 和身份门禁后才能成为运行时证据。
- `user-observation.v1.kind` 支持 `feedback_confirmed`、`feedback_rejected`、`feedback_irrelevant`；这些是用户对候选/报警的反馈，不是 observed runtime，也不会被 ledger 自动发布到 knowledge manifest。

`feedback_review.py` 只读聚合当前 `analysis-run.v1` 的三类 feedback，逐条核对 binding、created_by 和
runtime_eligible，返回 `feedback-review.v1` 的 `knowledge_publish_gate=approval_required/blocked`；它不调用
KnowledgeStore、不会写 memory 或 manifest。真正发布必须是另一个显式且 freshness-gated 的动作。

`feedback_knowledge_plan.py` 只接受已审查 feedback、候选 RootCausePattern 摘要和 freshness 输入；要求
candidate `variant_scope` 命中当前 run、至少一个 `feedback_confirmed`、actor=user 和 `approved=true` 才返回
`status=ready`。它只生成 `feedback-knowledge-plan.v1`，固定 `writes_knowledge=false`，不执行 KnowledgeStore mutation。

`feedback_knowledge_publish.py` 是单独的 `requires_approval=True` leaf：只接受 ready plan、`approved=true`、
`actor=user`、显式 `knowledge_dir`，并再次校验 variant scope；只写当前 scope 的 `RootCausePattern`，不写
其他 variant、feedback 原始 observation 或 knowledge manifest。其结果是 `feedback-knowledge-publication.v1`。

`analysis_workbench.py` 只读取 `analysis-run.v1` 及其实体 refs，输出 `analysis-workbench.v1` 与可选 HTML；
Workbench 是 AnalysisRun/ledger 的 projection，不拥有独立状态树，不执行工具，不更新 ledger，也不发布 knowledge。
- Windows 下 lock creation 和 atomic replace 的短暂 `PermissionError` 会在有界窗口内重试，
  超时仍返回可审计的 `LedgerConflict`/原始写入错误；不得无限等待或静默丢失事件。

`analysis_collaboration.py` 是 ledger 的 Pi 适配层，不执行 GDB/ROS/远程命令。三个原子模块
分别负责 hypothesis upsert、debug experiment plan/result 和用户 VSCode/GDB/截图/备注回填；
它们不互相复制职责，也不把人工观察覆盖自动 runtime evidence。`diagnostic_report.py` 只
读取其结构化摘要，投影有限的 Hypothesis/Experiment/Observation 过程卡片。

`code_context.py` 是一次性 source snapshot 边界：`discover_source_files()` 只读取显式
allow-list 或排除生成目录后的 C/C++ 文件，`build_source_manifest()` 用内容 SHA-256 形成
聚合 snapshot，`build_code_context()` 复用 `CodeGraphBuilder` 并导出 `code-index.v1`。
`build_code_context()` 可通过 `output_mapping_rte_file` 显式指定 Tx mapping；否则按
`source_identity.coem` 解析 BYD/variant mapping。没有显式 mapping path 或 COEM identity 时，
mapping 返回 `unavailable`，不默认套用 legacy GWM。被选中的 `RteComMapping_Tx*.c` 全部进入
source manifest 和增量图；已知 COEM 但 mapping 缺失时也返回 `unavailable`，不回退到其他
COEM。`discover_output_signal_mapping_files(source_root, rte_file)` 与 extractor 共用文件选择。
输出目录绑定到 source root 和项目/variant identity，源码在构建期间变化或 identity 冲突时不发布
可消费的新 context。`code-context.v1.artifacts.code_index_sha256` 固化伴随 index 的文件 hash；
index 丢失或 hash 漂移时 refresh 不能复用旧产物，`query_code_context()` 在读取前也会核验该 hash，
随后只返回限定 section。

`signal_mapper.py` 的 RTE 选择由 `resolve_rte_mapping_file(source_root, rte_file=None, side=...)`
决定：显式路径必须在 source root 内且存在；省略路径时只有唯一候选可自动使用，多 COEM 歧义或无候选返回
`unavailable/ambiguous`，不套用 GWM。`trace_variable_chains()` 读取选定 RTE 的 Tx companions，按 COEM
过滤 customer-specific `globalVariDef`，并把 `rte_file/rte_source_files/rte_hash/coem` 与扫描文件 hash
写入 `variable_chains.meta.json` version 4；旧版缓存强制重建。`extract_output_signal_mapping()` 不会在显式 RTE 缺失时
全仓搜第一个 `RteComMapping_Tx*.c`，避免把其他 COEM 的输出映射带入当前 variant。

`event_code_path.py` 只把上游事件投影到当前 `code-index.v1`：唯一函数解析、调用者/被调用者、
变量/信号/条件/参数和通用 GDB root plan。它同时生成 `resolution.condition_chain`，按当前
caller→helper→event root→callee 候选调用关系收集真实源码条件，并给每行附上
`chain_relation/chain_function_order/chain_source_order`；这是可验证的 source 候选路径，不是
把不同分支合成无条件 AND。它不执行远程操作、不把层名当作代码事实；解析不唯一时必须返回
`blocked`，runtime 值缺失时保留 `not_evaluated`/required tokens。
它也接受 sibling `cr60-debug-harness` 当前使用的同结构 legacy index，在内存中适配为
`code-index.v1`；不会改写上游文件，并在 `source_context.adapter` / `source_schema_version`
中保留适配 provenance。通过 `code-context.v1` 读取 index 时，还要继承 enclosing context 的
`source_context_id`、`source_snapshot_hash`、project/variant/COEM 等身份；否则同一 context
派生的 event path 会因 compact index 只保留 `snapshot_hash` 而被报告身份门误拦。

`condition_trace.py` 只对当前代码 index/动态 condition chain 的条件/参数和选中事件的同帧
field facts 做安全标量求值。
支持的表达式子集显式限定为比较、逻辑、四则运算、`abs/min/max/round` 和 C 基础类型转换；
缺 token 输出 `not_evaluable`，语法/函数超出子集输出 `unsupported`，两者都不能转成条件失败。
输出保留原始表达式、source ref、bindings、substituted expression 和 gap，供 report/AI 消费。
当当前 source 在条件之前明确声明局部 copy（例如
`objOutDataStruct sObj = objInfo->trcOutData[i]`）时，只对声明后未再次赋值的字段生成
`source_alias_bindings`；没有源码证明或字段可能被修改时不做 token 猜测。

`memory_recall.py` 是现有 `MemorySystem` 的只读 Pi 边界，按显式 project/variant/memory_dir
读取 L1-L6 和 semantic recall；code-derived layers 遵守 `KnowledgeFreshnessGuard`，状态为
`blocked_stale` 时只能作为缺口返回，不能进入当前诊断事实。

`project_capability.py` 只把显式 artifact 的身份、能力类别、unsupported 和 freshness
投影为 `project-capability-manifest.v1`；不从路径名猜车型/功能/仓库能力，不调用 LLM，
也不替代 `pi_context.py`。输入 artifact 的 schema/hash/path 会保留在 `input_refs`；
显式项目 capability declaration 只能 additive。

`arbe/public_runtime.py` 只处理公共 runtime 行的确定性归一化。warning/radar_info 的
frame 来自消息字段；objectlist 没有 frame 时默认落到 `unbound_objects`，显式 frame 或
callback 才能建立对象关联。collector 若已由当前 source 证明同周期发布顺序，可显式选择
`publication_order`：它依赖 capture message sequence，将对象标记为
`publication_correlated`，并保留 derived 关联证据；不按 timestamp 猜同帧。
它不连接 ROS、不执行回放，输出 `runtime-snapshot-with-frame.v1` 供 collector/bridge 消费。

`arbe/ros_inventory.py` 的 `RosTopicInventory` 默认只盘点 topic/type/publisher/subscriber；
可选 `inspect_message_schemas=True` 针对本次 inventory 返回的真实 ROS type 调用只读
`rosmsg show`，通过 `parse_message_definition()` 生成带 message type 的字段路径目录，并保留
定义 SHA-256、字段数和有界截断状态。`--sample-once` 每个 topic 记录客户端 UTC 观察时刻、
完整 stdout SHA-256/字符数和截断标志。类型参数先经 ROS type token allowlist 校验；完整定义不会
自动注入 Pi prompt，也不从字段或 topic 时间推断对象与报警帧的关联。
可选 `preflight_path` 解析 `arbe-preflight.v1`，校验/解析 server 与 user/port，将 preflight 文件 SHA-256、
workspace、binary/config fingerprint 放入 `runtime_binding`；缺失或部分 preflight 不标成 bound。
公开 helper 签名是 `build_message_definition_command(*, message_type: str, ros_setup: str = "", workspace_setup: str = "") -> str`
和 `parse_message_definition(text: str, *, root_type: str) -> list[dict[str, str]]`。

`runtime_capture_from_topic_inventory(inventory, *, inventory_path="", inventory_sha256="", topic_plan=None, topic_plan_path="", topic_plan_sha256="", preflight=None) -> dict[str, Any]`
只接受 `ros-topic-inventory.v1`。当前消息字段目录必须完整且只找到一个嵌套 message array 字段才可展开；
样本 hash/长度失配、采样截断、字段歧义和未知 topic role 都保留 diagnostics。若传入 topic plan，必须与
当前 preflight server/workspace identity 匹配才能用于 role mapping。它不生成 `message_seq`，独立采集的
topic 样本不能提升成 publication-order 关联，运行态快照仍要求后续按 `AnalysisRun` 显式绑定身份。

`build_public_topic_plan(...)` 的 `source_schema` 同时保留 `preflight_server`、`preflight_workspace`
和该 preflight artifact 的 SHA-256；topic sample adapter 要求 inventory/preflight/plan 三方 hash 和
server/workspace identity 一致，缺失或漂移时不使用该 plan 做角色映射。旧 topic-plan artifact 即使结构兼容，
也不能绕过这一 fresh binding 门。
该计划 builder 签名是 `build_public_topic_plan(*, profile=None, preflight=None, preflight_sha256: str = "", runtime_schema=None, topic_inventory=None) -> dict[str, Any]`；
`RosTopicInventory.run(..., inspect_message_schemas=False, runtime_binding=None)` 的 `runtime_binding` 由模块从
preflight artifact 构建，直接调用时默认输出 `not_bound`。

`arbe/remote_replay.py` 的 `capture_public` 已通过注入的 SSH/scp 底座接通真实
短窗口回放。远端只运行既有 ROS/arbe；capture 为 warning/radar_info/objectlist/ROI 保存
消息序号，具体关联仍由 `public_runtime` 按显式模式执行。旧 submit/poll/fetch trace API
保留兼容语义，尚未宣称为通用后台 job 调度。
当前 arbe 的 `wfSObj` 适配可选择 `object_validity_policy=arbe_wf_sobj`，把 source 中
GUI 明确跳过的 `ID<0` sentinel 放入 `ignored_objects`；默认 preserve，保留所有原始行。

`arbe/execution_binding.py` 是远程副作用的执行前身份门：`data_fingerprint`、
`source_context_id`、`binary_fingerprint`、`config_fingerprint` 和 `session_id` 必须与已批准
plan 一致，任一缺失或漂移都返回 `blocked`。`capture_public` 执行时生成或消费唯一
`attempt_id`，输出不会复用其他 attempt；远端 recorder 命令带 `trap`，SSH 中断会清理
tool-owned recorder/child process。`derive_execution_identity()` 可从 preflight 的
workspace/build/config/runtime 嵌套结构派生 source/binary/config/session 字段，并返回
字段级 provenance；data fingerprint 仍必须来自 intake/bundle，不从路径猜测。该模块不建立
SSH 连接，也不替代 preflight。

`point_cloud_replay.py` 是点云前级感知的纯确定性边界：它只生成 point-cloud replay
plan、审计输入字段、投影阶段覆盖和显式 point→cluster→track→output lineage；没有显式
edge 不推断关联，也不把 SGU target rows 当作点云输入。输入审计按 payload shape 区分
point/cluster/track/target，topic 名只作为未分类元数据保留。`HILMODEL!=0` 时 point-cloud
plan 必须 blocked；该引擎不播放 ROS、不编译、不修改 arbe。输入 contract 还输出逐雷达
字段损失、message schema/转换和 target usage；非有限值写成 `null` 并保留
`raw_literal`，避免非法 JSON。没有 point rows 时，输入 boundary 区分 `target_only`、
`target_injection_only`、`empty_public_pointcloud_observation` 和 `not_available`，不把占位空数组当作已观测输入，也不把默认 post-detection 路径误写成已存在。若同时提供当前
stage map/code context，报告仍保留静态源码候选和 `not_evaluable` 条件，完整感知状态继续 `blocked` 并显示 payload audit 缺口。`build_perception_code_flow()` 仅在 stage map 与 CodeIndex 的源根一致、文件集合相同且逐文件 SHA-256 相同时补充函数定义候选；identity/root/file hash 失配时不混合定义，调用/声明出现位置与 CodeIndex 函数定义在 HTML 分栏显示，二者均保持 `source_candidate`，runtime proof 独立。
`perception-run.v1` 只记录 producer 提供的
run/attempt/reset/完成帧，`perception-comparison.v1` 只接受显式 match 或声明的精确
frame/identity key，绝不按时间近邻、数组下标或跨策略相同 ID 猜测对象。
`perception-scene.v1` / `perception-timeline.v1` 只有在显式 `selected_frame` 存在时才投影
同帧场景和时间线；缺少选中帧返回 `not_available`。scene point 保留 observed coordinates 和
精确 `cluster_id/track_id`；cluster centroid 只从同 callback、相同 cluster id 的点派生；
track/output rows 若无 verified coordinate transform，不与 point layer 共用几何平面。
public timeline 的 `public_uid_recurrences` 仅在 callback binding summary 完整、`track_population.scope` 为
`public_objectlist_output_rows` 且显式 `selected_frame` 存在时，比较同一 capture/radar 的相邻
source-proven ObjectList callbacks；match grade 为 `derived/same_public_uid_adjacent_callback`，不等同
物理目标 identity，也不跨 gap 建连。`algorithm_track_id` 来自 ObjectList 的整数字段，不套用
PointCloud2 float32 UID 的 2^24 精度上限；物理身份和内部 lifecycle 仍为 `not_available`。
`perception-warmup-analysis.v1` 只比较独立 attempts 的显式 output signature 和完成状态，
用于标记 warm-up stable/sensitive，不把稳定性当成算法正确性。
`perception-injection-audit.v1` 分离显式 injection macro、target usage 和 stage runtime proof；
发现注入启用时 point-cloud plan 必须 blocked。
`perception-hypothesis-set.v1` 只保存最多三个候选及区分实验，状态为 `candidate_only`，
不提升任何 evidence claim 的 observed/confirmed 等级。
`perception-capability-manifest.v1` 将当前点云输入/静态 stage/runtime stage 证明、unsupported
和 freshness 聚合为路由声明；它不等同于完整项目 capability manifest 或 runtime 验收。
`freshness.status=verified` 必须有 ready plan、completed run、上下文/plan/run 的 data/source/binary/config/session
指纹逐字段一致，以及 aligned runtime workspace；非空字符串不能单独证明 freshness。identity 冲突为
`blocked/conflict`，字段缺失或 run 未完成保持 `partial`。报告只有在该 manifest 也 ready 时才能输出
`analysis.status=ready`。
`perception-run.v1.status=completed` 要求非空 `run_id/attempt_id/plan_hash`、plan/run hash 对齐、
至少一条 observed frame 和 completed frame，以及 reset、warm-up 完成；缺任一字段时仍保留 attempt，
但只能是 partial。
`perception-artifact-audit.v1` 对 JSON/JSONL/CSV 以及带 `rosbags` 依赖的 ROS1 `.bag`
做结构化读取；MF4/BLF/DB3 等未接入 parser 的格式必须显式 `unsupported`，保留文件 hash
和缺口。ROS bag adapter 只产出 `wfAutosarData.dotTrans/objTrans` 的 post-detection
边界，并保留 layout binding required，不把 bag 的存在当成完整感知重算。raw `dotTrans` 的
`layout_status=verified` 还要求 source header 与 active source snapshot 一致、原始 recording SHA-256
与 input data fingerprint 对齐，并带录制版本及 hash-bound compatibility evidence；只有 source header
profile 的 `verified=true` 不足以解锁 replay。冲突时 input contract 为 partial/conflict，plan blocked，
行值仍保留 `observed_with_layout_warning` 供静态检查。
`register_perception_artifact_adapter()` 提供外部格式 adapter SPI；外部 loader 必须返回结构化
mapping，且仍由 artifact audit 保留原文件 hash/provenance。
`perception-validation.v1` 在报告投影后检查 schema、计数、ready/runtime/lineage 和候选上限；
lineage 的 `node_counts`、canonical `edge_count`、`raw_edge_count`、`invalid_edge_count`、`relation_counts`、`raw_relation_counts` 与 `relation_summaries` 保持全量计数，
内嵌前缀由 inline counts 标记。大型 lineage 写入 callback-contiguous `perception-lineage.jsonl`，
并输出 `perception-lineage-index.v1.json` 的 byte range 与 callback block hash；读取器按 callback seek
后校验 index/block hash、大小、行数和 record-type 计数，缺失/失配时返回 `partial`。
它是完整性检查，不是 root-cause 结论。
`build_perception_lineage()` 可选接收 `track_population` 和 `relation_scopes`。规范
`cluster_supports_track` 是唯一 `(from,to)` pair 边；重复输入行保留在 `raw_edges` / `raw_relation_counts`，
不重复计作关系。`relation_summaries` 显示每类边的端点 node kind、edge row 数和 distinct 端点数。
当前 public PointCloud2 producer 的 `point_supports_cluster` 仅纳入 `cluster_id > 0`；公开 ObjectList
track nodes 只代表已捕获输出行，内部 candidate/mature population 必须保持 `not_available`。
point-cloud execution plan 和 `sim-verify` provider 都会执行 runtime/workspace alignment
双重检查，避免计划生成后的 process 漂移被批准 binding 掩盖。计划现在还要求显式输入
contract、输出 topic、server target、完整身份（含 config/session）和足够覆盖 warm-up 的
回放窗口；缺失输入、未确认注入状态、4 秒窗口不足以覆盖 175 帧等情况保持 `blocked`。
`audit_runtime_workspace_alignment()` 优先使用 preflight 的 `/proc/<pid>/exe`，不再用命令行
中任意出现 workspace 字符串作为 aligned 证明。preflight 额外记录 outer/algo dirty 内容
和 launch config 的 sha256，binding 在冲突时 fail-closed。

`arbe/remote_replay.py` 的公共 capture extractor 按 payload 解码 `wfAutosarData.dotTrans`、
PointCloud2、MarkerArray 和 objectlist，并输出 point/cluster/track/output rows 与 stage
计数；它仍不能伪造私有阶段、reset 或 warm-up ACK。point-cloud capture 没有 producer-owned
完成确认时，`sim-verify` 返回 `partial`，而不是把 rosbag play 返回码当成感知完成。
`bind_public_perception_capture()` 生成的 callback key 只属于本次 recorder capture；bag `message_seq`
是录制顺序，不是 algorithm frameID/frame counter，也不能与 warmup_requested 帧数相比较。
由于当前 producer 没有导出算法 frame counter，`algorithm_frame_counter_status=not_available`、
`warmup_frame_relation=not_evaluable`；consumer 不得用 callback suffix 推断该回调在 warm-up 前后。

`pi_context.py` 是控制面上下文 builder：优先合并显式 intake/preflight 和用户输入，
也允许从已校验的 diagnosis bundle 读取其明确声明的 case/data/source 字段，生成
`pi-orchestration-context.v1`；不得从路径名猜测车型、COEM、分支、雷达或 runtime
状态。bundle 派生字段必须带 `diagnosis_bundle...` provenance。

`build_pi_orchestration_context(task_scope="case_analysis")` 默认继续要求 case/intake；
缺数据保持 blocked。`task_scope="source_code"` 专用于没有录制数据的静态源码查询，
此时 `data.status=not_required`，可消费 `code-context.v1` 并将项目、variant、source
root/snapshot hash 与 runtime_binding 保留 provenance。若 context 声明 companion
`code-index.v1`，builder 还核验 context/index schema、source root、snapshot hash 和 index
文件 SHA-256；source context 与 artifact refs 中绑定两份 artifact 的路径/hash。source_code
scope 缺少 index/hash、文件不可读或与 context 不匹配时 blocked。source snapshot 只能提供静态候选，不宣称 runtime。
PiModule 在没有显式 code context path 时，从有效 variant 配置读取 source root/key files，
经 `CodeContextRefreshModule` 在 variant snapshots 下的 `code_context_current` 生成或复用
source snapshot；不会复用共享/旧 CodeGraph。PiBridge 将经验证的 index binding 限定传给
本次 Pi 子进程，`pi_tool_bridge` 在执行 `code-analyze` / `code-gdb-plan` / `code-context-read` /
`event-code-path` 前重算/核验文件哈希、source root/snapshot 和 context 对 index 的引用，拒绝
inline index 或冲突路径/db 覆盖。

`runtime_evidence.py` 是 runtime producer 与 HTML/Pi consumer 之间的确定性边界：

| 公开接口 | 职责 |
|---|---|
| `parse_runtime_markers(text)` | 解析 `CR60_RUNTIME`/uppercase `KEY=value` marker，保留未知字段 |
| `normalize_runtime_evidence(...)` | GDB session/transcript 或 `runtime-snapshot-with-frame.v1` → `runtime-case-evidence.v1` |
| `validate_runtime_evidence(payload)` | 无第三方依赖的稳定 schema 子集校验 |
| `validate_runtime_binding(bundle, evidence)` | 比较 data/source/binary identity，输出 verified/partial/conflict |
| `match_runtime_observations(bundle, evidence)` | 仅按 event/radar/frame/object identity 匹配，禁止按邻近时间猜目标 |
| `merge_runtime_evidence(bundle, evidence)` | 生成 additive runtime overlay，不覆盖静态 bundle |
| `compose_runtime_evidence(existing, incoming)` | 组合多个 runtime producer 的 runs/layers/observations，不丢历史证据 |
merge_runtime_evidence 支持可选 event/frame/object scope；Pi 应按当前事件物化小片段，完整
runtime evidence 由 artifact ref 保留。runtime_summary 默认只返回有界 observation 样本，
避免把逐帧公共数据完整复制到 Pi context。
| `runtime_summary(evidence, merge)` | 给 Pi context 使用的确定性小投影 |

runtime 的 `partial` 不是“条件通过”：例如 binary fingerprint 缺失可以展示已捕获
GDB 值，但不能声称 ELF 与静态源码完全同源；source/data identity 冲突则 overlay
必须 blocked。`observed`、`derived`、`optimized_out`、`not_found`、`conflict` 和
`not_available` 保持原状态，禁止用空值或 AI 推断填补。

读取旧版 canonical `runtime-case-evidence.v1` 时，`runtime_evidence.py` 会重新运行 GDB
结构体标量/点解析，把 `objInfo->trcOutData[i]` 中的真实字段（如 warning flag、side flag、
`fInterX/fInterY`）保留为独立 token；不会覆盖 evidence layer。`evidence_query.py` 对超长
tokenized field list 采用头部、尾部和高价值字段的有界选择，保持 `frame/ego` 输入与结构体
尾部输出同时可见，并标记 `truncated`。

`arbe/build.py` 只提供 feature-neutral `catkin_make` primitive：
`build_catkin_make_command(...)` 生成显式 workspace/ROS setup command，
`run_catkin_make(...)` 返回 `arbe-build-session.v1`。它不 checkout、改配置、启动 ROS
或清理工作区；远程执行由上层审批和 `SshCommandRunner` 负责。

`arbe/source.py` 和 `arbe/cuda.py` 是上游 `cr60light-arbe-build` 工作流的只读边界：

- `build_source_resolve_command` / `resolve_source` 只读取当前 `algo_source` 的 HEAD、branch/
  detached、exact tag、dirty 状态以及显式目标 ref 的 local/remote 存在性；不会 `fetch`、
  `checkout` 或根据版本字符串内置 Bosch/车型映射；版本→ref 必须由调用方传入
  `ref_prefix`/`version_suffix_strip`，并保留 `ref_source`。
- `build_cuda_resolve_command` / `resolve_cuda` 只扫描当前 source 的
  `coem/<vehicle>/tools/container_input/08_CustData/CUDA_*.xlsx`，按远程 mtime 再按路径
  选择候选，记录大小和 sha256，并读取当前 YAML 的 `xlsx_path/xlsx_sheet/type`。它不会
  `cp`、修改 YAML、编译或启动。
- 两个引擎均支持 plan-only、注入 runner 和结构化 blocked/partial/needs_confirmation；
  未确认车型、source root、版本映射或 dirty 工作区不得被猜测。后续写入能力只能消费
  当前同一 source fingerprint 的 artifact，并单独经过 approval。

`arbe/patch_plan.py` 将上游仿真适配检查表示为可配置的 `checks`：每项指定 `scope`
（`arbe` 或 `algo`）、相对路径、正则 pattern 和 required 级别。默认检查来自当前
`cr60light-arbe-build` skill 的已知适配契约（GUI `taskTime` 调用、`BUILDMODEL=2`、
`HILMODEL=2`，以及可选 SGU define），但 pattern/路径可以被 Pi 按新 source 版本替换。
它读取文件、sha256、匹配行和 `git diff`，返回 `arbe-patch-plan.v1`；即使所有 pattern
存在，只要 outer/algo dirty 也会是 `partial`，缺少 required pattern 则是 `needs_action`。
它不将 `#ifdef PF_BUILD_FUNTEST_SGU_INJECTION` 误当成宏已启用，也不修改远程文件。

`arbe/data_prep.py` 是 `bosch-data-transfert` 的只读前置边界。`map_source_path` 只将
明确声明的 Linux absolute 或显式 `source_prefix` 映射后的 UNC 路径交给远端；Windows
盘符、相对路径和未提供 UNC mount 都保留为 `needs_confirmation`，不猜测服务器路径。
`verify_data` 对每个 entry 扫描支持的扩展名并记录文件名、size、mtime、sha256；可选
按同名文件比较 destination。它不创建目录、不 cp、不 rsync，输出
`cr60-data-prep-verification.v1`，供后续 transfer executor 做 approval-bound 输入。

`arbe/transfer.py` 只生成并执行已配置的上游脚本命令，输出
`cr60-data-transfer-session.v1`。它不接受自然语言 shell、不内置源路径/目标目录、不
创建自己的复制实现；`approved` 是执行门，执行结果必须保留返回码、stderr 和超时状态。

`ArbePreflight` 支持显式 `ros_setup` 和 `ros_master_uri`；未传 master 时保留远端环境，
传入后才用该 URI 做 `rosnode` 发现。`runtime-debug-plan` 的
`gdb_attach_permission` 会把 `ptrace_scope=1/2` 标为 warning；这不阻断隔离
launch-under-GDB，但 formal existing-PID runner 必须在执行时重新验证 attach 权限，
失败只能生成 blocked attempt。

远端 preflight 会先通过短时限 SSH command 检查连通性；发生 SSH session error 或任一探测
超时后停止后续远端 fan-out，并在 `probe_execution`、各 probe 的 `skipped/blocked_by_probe`
字段保留失败链。运行态进程探测失败时 `runtime.status=unknown`、进程/ROS 节点输出为
`null`，`bash_start_required` 也保持未知；GDB、宏、binary 和 CAN source 未观测时不会分别
降级为 `gdb_not_found`、`HILMODEL not found`、binary not found 或 source mapping not found。
`tests/test_arbe_preflight.py` 验证此 fail-closed 和短路行为。

GDB runner 的 `PLAY_RC/GDB_HIT_COUNT/WARNING_ROWS/WARNING_NONZERO_COUNT` 和 command
error 会进入 `disturbance`。只有 ptrace/attach、内存、runner/rosbag 或 GDB script 等
强运行时错误才把状态标为 `suspected/confirmed`；单纯 `No symbol`（宏、枚举或不在当前
栈帧的局部量）只作为字段缺口和 parser diagnostic，不证明回放被扰动。plan-bound runner 对 watch expression 使用可恢复 probe：每个表达式单独
捕获 `No symbol`/优化等异常，后续 breakpoint 仍继续执行；解析器把错误绑定回该
token，禁止生成 `observed=null`。每次隔离回放还把唯一 `RESULT_PREFIX` 纳入
`gdb-session.target.run_id`，同一 plan 的重复运行可被区分。多次 runtime merge 会
组合 `runs/layers/observations`，并对相同 radar/frame/object/token/phase 的重复值生成
`same/different` comparison。

`runtime_debug_plan.py` 是执行前的计划边界：`build_runtime_debug_plan(bundle, ...)` 只
消费当前 bundle 的 breakpoint pack 和当前 preflight，输出 `runtime-debug-plan.v1`。
如果 event code path 提供 `resolution.condition_chain`，它会按当前 source chain 为 caller/helper、
event root 和 callee 生成 source-condition probe 候选，保留函数和 chain relation；没有该链时
才回退 event-root conditions，不为具体功能补固定断点。
它按 event/radar/frame/object 组织 target，校验 source HEAD、code/schema hash、HILMODEL、
binary/GDB、process、approval 和 GDB command allowlist；只产生 readiness warning/block，
不启动回放或 GDB。`gdb_commands` 可由 Pi 以 typed artifact reference 交给
`gdb-service`，不能由自然语言拼接。

`evidence_query.py` 是 `evidence-query.v1` 的确定性 artifact 查询引擎。它只读取显式
diagnosis bundle/viewer/runtime JSON，按 event/function/side/radar/frame 过滤，并按点号
路径返回真实字段；默认限制事件、帧和目标数量，缺失字段保持 `not_available`。它不做
bag/source 解析、时间近邻关联或功能规则判断。runtime join 可使用事件 projection 中
明确提供的 `details.feature.entry_function` 连接外部功能名与实际源码入口；有界截断时
优先保留同帧 GDB observation、selected object 和公共 frame，避免长 objectlist 将关键
GDB 证据挤出报告。
另可直接查询 `runtime-snapshot-with-frame.v1`：只读取 capture metadata 声明且来自当前
message schema 的动态 ObjectList token；unbound 行没有 event/frame association，frame filter
不匹配时返回缺口而不近邻关联，且 `identity_binding=not_bound` 保持 `partial`。

`diagnostic_report.py` 是 `diagnostic-report.v1` 的确定性投影引擎。它从事件/代码/runtime/账本
artifact 生成事件索引、选中事件、证据层、缺口和 next actions，并可把外部
`diagnosis-panel` 结果作为 inference 携带。它不把 AI 结论写成 observed，也不覆盖原 bundle。
它还输出 `gdb_confirmation` 和 `execution_context`：前者分别核对 GDB runner 状态、规范化
GDB observation、frame/radar/object identity 和实际字段，后者说明录制 bag、arbe 仿真、
`HILMODEL`/回放模式、预热范围以及算法报警 topic。可选 `gdb_session_path` 用于把
`gdb-session.v1.status` 与 transcript 绑定，避免仅凭日志存在就宣称 GDB 执行成功。
source snapshot 比较优先使用真正的 `source_snapshot_hash/snapshot_hash`，只有 legacy artifact
没有 source snapshot 时才回退 `source_index_hash/code_index_hash`。从跨多个 GDB stop 合并的
`info args/locals` 没有 source-line binding 时，局部快照只进入 runtime/display evidence，
不参与条件真值，防止把 handler 更新前的计数器误用于更新后的条件。

`diagnostic_report.py` 可额外接收 `runtime_snapshot_path`，复用 `evidence_query` 的 bounded
snapshot projection，把 unbound ObjectList rows 作为独立 partial layer 输出；不把 snapshot rows
自动并入 selected event、alert timeline 或 condition trace，且保留 `identity_binding=not_bound`。

`alert_timeline.py` 是 `alert-timeline.v1` 的功能无关投影引擎。它把 bundle/viewer 的 raw
报警、arbe replay、public runtime、GDB 和 CAN Tx 行转换为统一的 layer/frame/transition
记录，另外生成播放帧 map 和跨层 compare。它不解析 bag、不执行回放、不做 FCTA/FCTB 或
其他功能规则判断；缺少 exact frame 时只能返回 `not_evaluated`/`not_comparable`，身份冲突
时返回 `blocked`。

`diagnostic_narrative.py` 是报告内部的只读文字投影服务：按已生成的 condition trace 和
alert timeline 形成 `executive_summary`、紧凑的 `operating_condition`/`runtime_facts`、关键
条件命中描述及 `should_alert` 状态。默认只把最多 10 条最相关条件放进 `condition_items`，完整
条件仍由 `condition_trace` 保留；选择可按当前事件的功能提示优先相关 token，但不把候选行当作
完整 AND 链。它不解释未观测变量，不把条件层支持升级为 CAN Tx 事实，也不实现功能规则。
同时输出 `analysis_flow`（`diagnostic-analysis-flow.v1`）读模型，按输入工况、源码条件逐级
代入、几何/预测和输出端点组织同一批已存在的证据，给 HTML/Pi 一个稳定的中间分析视图；
它不引入新的求值器，条件的真实绑定、缺口和 source ref 仍以 `condition_trace` 为准。

`diagnostic_report.py` 的 `geometry_projection` 只做场景读模型：按当前功能/侧别选 ROI，计算
同一 polygon/ROI 的 `intersects` 或 `disjoint`，并带 `observed_*`/`source_derived_*` 来源前缀。
它必须同时保留 `collision_evidence`、坐标语义和缺口；几何关系不能替代功能 branch、runtime
局部变量或 CAN Tx 判定。

当前实现还会把三种语义分开输出：`instantaneous_relation/collision_status` 表示同帧
`objPoly` 与 ROI 的实际几何关系；`algorithm_branch` 表示从当前 source 条件确认的 ROI
可用性分支（例如 `<side>FctaRoi->num > 0U` 设置 `<side>Flag`），不把它解释为目标已经
进入 ROI；`predicted_intersection` 只消费 runtime 已观察到的交点/穿越点坐标与时间 token
（当前案例是 `fInterX/fInterY/fTTMY`，其他项目可使用 `intersection_x/time_to_cross`），
表示算法预测的穿越点/时间。HTML 对预测点使用独立虚线和标记，禁止为了迎合
报警结果修改当前多边形。超长 runtime field list 的有界投影优先保留
`observed/derived` 数值 token，不让 `not_found`/`optimized_out` 同字段族占用预测字段槽位。

`diagnostic_narrative.py` 与 `diagnostic_report.py` 共同使用 `output_policy`：默认以 arbe
可视化工具报警灯对应的算法最终输出作为 `effective_endpoint=algorithm`；只有用户明确要求
CAN 侧核验时才切换到 `can_tx`。CAN 是可选的下游辅助证据，不得因为输入中没有 CAN 而在
主结论重复提示或改变算法报警结论。该策略与功能名无关。

`arbe/replay_provider.py` 的 trace parser 不再把 `WARNING_BITS` 当跨项目默认映射；
`parse_warning_trace_csv(..., warning_names=...)` 或当前 case 的 runtime schema 提供语义时
才展开功能名，否则保留 `wN`。`WARNING_BITS` 仅是旧调用方兼容导出。

`arbe/preflight.py` 的 `can_output` 只扫描当前 YAML `coem_name` 对应的
`RteComMapping*.c`/`components/com/AutoGen/*.c`，不跨 COEM 读取，也不使用固定行数截断。
除 `write_mappings` 外，还输出 `transport_mappings`（`RteLite_Write_*` 与附近的
`Com_SendSignal`）和 `public_evidence.objectlist_frame_contract`。这些都是 source candidate；
只有 runtime/CAN/GDB artifact 才能升级为 observed。
同时，preflight 会对当前 COEM 的 C/C++ 源码做一次窄的 member-assignment scan，生成
`can_output.source_output_chain`（`arbe-source-output-chain.v1`）：它把 WriteSignal 表达式中的
内部 member path、有效/注释赋值、生产函数引用和 transport 引用连起来。该扫描用于代码导航和
证据 provenance，不等同于赋值已执行；超出当前源快照的链路必须保持 `not_scanned` 或
`not_found`，不得由功能名猜测。

`diagnostic_narrative.py` 在算法报警输出之后生成 `output_chain`（`diagnostic-output-chain.v1`）。
它优先消费同帧 runtime/GDB 的真实 `adasWarning` 字段，再接上当前 source 的内部信号、对外
WriteSignal 表达式以及 RteLite/Com 调用点。算法输出可以按 `output_policy` 作为本报告终点，
但没有同帧 runtime observation 的内部/对外环节只能标为 `source_candidate`；自然语言结论必须
同时写清已观察值和未证实的跳跃。

`arbe/public_runtime.py` 支持 `object_association_mode=auto`：只有 preflight 的
`objectlist_frame_contract.status=source_verified` 才有效地采用 publication-order 关联，
否则使用 strict。capture message sequence 仍是必要输入，timestamp 不用于猜同帧。

`arbe/intake_binding.py`（`cr60-intake-binding.v1`，T10/G6-AC01）是"bag+问题→版本/车型/
COEM 绑定"的确定性门。`bind_intake_identity(intake, config, *, case_variant,
case_variant_error, explicit_variant_id, intake_path, intake_sha256)` 只消费
`cr60-analysis-intake.v1` 中 `status=resolved` 的身份字段与 `config.variants`，解析
优先级为 case 元数据 > 显式 variant > intake 身份匹配（customer+vehicle 成对和/或
coem 末级目录）> 单配置项目自动复用；歧义、零匹配、缺版本产生**业务语言**
`business_questions`（`blocking` 标记，措辞不含 frameID/PID/GDB 表达式等技术
token），版本/分支与项目 `source_context.code_branch`（或可选
`expected_software_version`）不一致时 `status=blocked` 且
`binding_status_note=runtime_binding_blocked`——错误版本不得进入当前 runtime 绑定。
版本已知但版本→分支映射未配置时保持可分析并记
`version_to_branch_mapping_unavailable` 诊断，不把技术映射问题抛给用户；路径名/
bag 文件名永不作为身份证据。它不调用 LLM、不做 IO（除可选 intake 文件 hash）、
不访问网络。消费方：`ai/modules/pi.py` 的 pre-model gate 与 AnalysisRun 绑定
（`intake_handoff_id`/`intake_binding_status`）。
