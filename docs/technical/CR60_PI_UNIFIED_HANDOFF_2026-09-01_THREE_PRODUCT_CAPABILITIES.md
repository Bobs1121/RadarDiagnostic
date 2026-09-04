# CR60 Pi Unified Handoff：三个用户出口纵向切片

版本：`handoff.2026-09-01.three-outputs.v2`  
状态：`implemented-partial-field-acceptance`  
关联需求：DDD `US-003/US-004/US-011/US-014/US-015/US-021/US-022/US-023`  
关联 Sprint：`S1C`  

## 1. 本次交付结论

已把平台收敛为三个可组合的产品出口：

1. 批量预检查：继续使用 sibling `cr60-debug-harness` 的 `cr60-precheck` adapter；
2. 单事件详细报告：新增 `evidence-query` 和 `diagnosis-report` 两个非重复原子能力；
3. 对话式分析：Pi 使用生成的 `registerTool` 调度已有工具，并自动把对话轮次落到 Analysis Ledger。

三者不是三套数据解析逻辑。批量产出的 bundle/viewer/runtime/code artifact 是后续详细报告和对话的
唯一输入；报告只做投影；AI 只在显式的 inference 区域工作。

## 2. 输入和输出

### 2.1 批量预检查

| 输入 | 必需性 | 说明 |
|---|---|---|
| 数据文件夹 / intake / manifest | 必需 | 由 `cr60-precheck` 选择对应 mode |
| sibling harness root + profile | 必需 | 当前仓/数据版本对应的 harness 配置 |
| analysis context | 必需或 `prepare_context=true` | source/code index/runtime schema 来源 |
| output_dir | 必需 | 每条数据独立目录 |

输出：batch index、每条数据的 `diagnosis_bundle.json`、`viewer-model.json`、`report.html` 和已有
CSV/media/运行时 artifact；失败 case 只标记自身状态。

### 2.2 详细诊断报告

最小输入是 `bundle_path` 或 `viewer_model_path`。可选输入包括 `runtime_evidence_path`、
`runtime_debug_plan_path`、`code_context_path`、`event_code_path_path`、`analysis`（来自
`diagnosis-panel`）和 `analysis_run_path`。

过滤条件：`event_id`、`event_index`、`function`、`side`、`radar_id`、`frame_id`。输出：

- `evidence-query.v1`：事件/帧/字段有界切片；
- `diagnostic-report.v1`：事件索引、选中事件、ego/target/index/code/runtime、证据层、缺口和 next actions；
- `diagnostic-report.json/.md/.html`：机器、文本和快速分享投影。

### 2.3 对话式分析

入口：`python cli.py pi --question ...`、`python cli.py pi --interactive`，或 Pi 原生对话入口。

Pi 自动携带：

- `pi-orchestration-context.v1`；
- 当前项目/variant/source/data/runtime artifact refs；
- `AnalysisRun` 路径和同名 Pi `session_id`；
- 生成的 `.pi/extensions/radar-capabilities.ts`。

每个回合追加一个 `dialogue` AnalysisStep；工具的内部大 payload 不写进隐藏模型思维链，只有工具摘要、
状态、artifact ref、用户可见总结和缺口进入账本。用户可以继续追问属性、代码、信号或下一步实验。

## 3. 实现映射

| 组件 | 位置 | 职责 |
|---|---|---|
| evidence query engine | `engines/evidence_query.py` | 只读 artifact 查询、过滤、字段路径和有界切片 |
| evidence query module | `ai/modules/evidence_query.py` | BaseModule/CLI/JSON schema |
| diagnostic report engine | `engines/diagnostic_report.py` | 确定性事件索引和报告投影 |
| diagnostic report module | `ai/modules/diagnostic_report.py` | BaseModule/CLI/JSON schema/文件输出 |
| Pi session ledger | `ai/modules/pi.py` | 创建/恢复 AnalysisRun、落 dialogue step |
| persistent Pi session | `ai/pi_bridge.py` | 有 session ID 时使用 `--session-id`，不使用 `--no-session` |
| Pi catalog | `.pi/extensions/radar-capabilities.ts` | 自动暴露新增 leaf capabilities |

## 4. 真实验证

使用现有 CRGVI-1829 产物验证：

- bundle：`D:/RamboStar/idea/cr60-debug-harness/outputs/actual_folder_CRGVI1829_20260827/cases/corner_radar_net_2026-07-19-11-56-15_11.bag/diagnosis_bundle.json`；
- viewer：同一输出的 `data/corner_radar_net_2026-07-19-11-56-15_11.bag/viewer-model.json`；
- 查询结果：`outputs/final_real_evidence_query_CRGVI1829_20260901.json`；
- 详细报告：历史报告目录已在 2026-09-03 清理，当前统一入口为
  `outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`；
- runtime overlay 的结论已并入当前报告对应 JSON，保留 runtime association 和 first-frame gap；
- 定向测试：历史 slice 为 `29 passed`、扩展后为 `61 passed`；本轮加入 case companion discovery、
  bounded tool allowlist、nested tool event、output guard、condition trace 和 memory recall 后，组合定向测试为 `77 passed`。

三出口纵向验收摘要：`outputs/three_output_acceptance_CRGVI1829_20260901/acceptance-summary.json`。
该摘要记录真实 batch index 的 `5` 条数据、`149` 个事件，真实 `FCTA_R/radar2/frame=47877`
查询命中 `objID=44`、`raw_sgu_index=0`、`algorithm_object_index=0`、`objectlist_index=1`，
并生成详细报告三件套；同一 AnalysisRun 已有 `3` 个阶段 step。详细报告诊断状态为 `partial`，
保留 `alarm_first_frame_not_exact`，没有把 selected analysis frame 宣称为最终 CAN Tx 首帧。

真实查询得到的 FCTA_R/radar2 事件保留：`objID=44`、`raw_sgu_index=0`、
`algorithm_object_index=0`、`objectlist_index=1` 以及 ego/target 真实字段。该事件仍标注
`first_observed_warning_nearest_lgu` / `selected_frame_not_alarm_edge`，没有把它升级为最终 CAN Tx 首帧。

### 4.1 本轮最终单数据验收（2026-09-01）

本轮使用用户指定的真实 bag 重新执行了 sibling harness 的 manifest 预检查，结果为：

| 项目 | 结果 |
|---|---|
| 输入 | `/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag` |
| case | `CRGVI-1829-single-2026-07-19-11-56-15-11` |
| precheck | `ready`，1 case，28 events，failed/blocked/unsupported 均为 0 |
| 已发现功能 | `BSD_L/radar3=7`、`LCA_L/radar3=7`、`BSD_R/radar4=6`、`LCA_R/radar4=6`、`FCTB_L/radar1=1`、`FCTA_R/radar2=1` |
| 选中事件 | `recorded_raw:FCTA_R:radar2:519.376635` |
| 选中分析帧 | `frameID=47877`，同雷达 LGU `/wf/corner_radar/lgu_data_2`，时间差约 `1.17 ms` |
| 目标映射 | `objID=44`，raw SGU/算法对象 `i=0`，`objectlist_index=1` |
| 代码链路 | `FrontCrossTrafficAlertAndBrake`，8 组断点，主条件为 `(frame_counter >= 47877 && frame_counter <= 47877) && (sObj->objID == 44)` |
| 详细报告 | JSON/Markdown/HTML 均生成，`diagnosis.status=partial` |
| 条件证据 | `condition-trace.v1` 已生成，22 条当前 FCTA 条件全部保留为 `not_evaluable`，没有把缺失运行时量当成 false |
| 记忆召回 | `memory-recall.v1` 已实际执行；未绑定 variant 时 3 层项目/功能/会话笔记可读，4 层代码型记忆标记 `blocked_stale` |
| Pi 入口 | `cli.py pi` 实际触发 `evidence-query` 和 `diagnosis-report` 的 `tool_execution_start/end`；字段查询 run 为 `run-20260901T060752-8a061b93da`，最终报告 run 为 `run-20260901T074010-db991ea470` |

本轮还修正了两个通用入口问题：

1. `PiModule` 通过 `batch-index.json` 绑定 sibling harness 分离的 `cases/<id>` 和 `data/<id>`，
   因此 Pi 能拿到真实 `viewer-model.json`，而不是退化到只有轻量 bundle；
2. Pi 按问题从 live catalog 生成有限 allowlist，避免部分 provider 面对全量 53 个工具时只复述工具
   说明；`evidence-query` 收到 `output=json/text` 这类格式名时不再写出伪 artifact。

3. `condition-trace` 从当前代码链路读取 22 条 FCTA 条件，在报告中展示源码行、代入表达式和
   缺失的 runtime token；详细 HTML 新增 ego/target 字段摘要、目标 yaw 朝向和 ROI/场景 SVG。

4. `memory-recall` 复用现有 variant-scoped `MemorySystem`，没有 variant 或显式 memory_dir 时
   不选择配置中的默认车型代码记忆，避免 standalone Pi 串用其他项目知识。

完整本轮验收材料：`outputs/single_case_actual_CRGVI1829_20260901/acceptance-summary.json`。

## 5. 已知边界

- 现有 sibling viewer 是正式场景图形界面；本次新增 HTML companion 是证据/诊断投影，不替换 viewer；
- `diagnosis-report` 不自行运行 AI，需由 Pi 先调用 `diagnosis-panel` 后以结构化 `analysis` 传入；
  没有 AI 时仍会生成包含 `condition-trace.v1` 的证据版报告；
- 没有 runtime 的报告仍可交付静态事实，但会显示 `runtime_probe_required`；
- objectlist 没有算法 frameID 时仍遵守 strict/publication-correlated/unbound 证据分层；
- 已在当前本地 Pi provider `bosch-qwen3_6/Qwen3.5-27B-FP16` 实测真实 case 的
  “manifest companion discovery→evidence-query→结果解释”，本轮 Analysis Run
  `run-20260901T060752-8a061b93da` 已记录 `tool_execution_start/end`；批量执行审批链和
  `diagnosis-panel→diagnosis-report` 的 AI 长链仍需现场验收；
- 正式 workspace 的 checkout、CUDA 写入、catkin_make、bash start、attach 和 GDB 仍由既有 approval gate 控制。

## 6. 下一步

1. 现场用 Pi 批量请求跑一遍真实数据目录，确认模型能够选 `cr60-precheck` 并返回 batch index；
2. 选一条含 runtime overlay 的事件，Pi 组合 `evidence-query → event-code-path → diagnosis-panel → diagnosis-report`；
3. 连续发送两个业务追问，确认同一 `analysis_run_id` 的 ledger step 增长且不重新扫 bag/source；
4. 再进入 S2B Workbench，把 ledger 的 steps/claims 投影进 sibling viewer 的 Analysis Trail；
5. 最后才推进 point-cloud 150–200 帧 runtime 和正式 CAN Tx 首帧闭环。
