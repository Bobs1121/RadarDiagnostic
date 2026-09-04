# CR60 Pi Unified Handoff：DDD 缺口审查与跨证据报告补足

版本：`handoff.2026-09-01.ddd-gap-review.v1`  
状态：`implemented-partial-field-acceptance`  
日期：2026-09-01  
分支：`codex/ros-debug-autonomous`

## 1. 目标

按 Document-driven development 复审统一诊断平台的需求、领域边界、实现和证据，补足
“原始报警/仿真报警/运行态/GDB/CAN 报警帧”没有统一呈现的问题；保持 Pi 为唯一产品入口，
不复制 sibling harness 的 bag parser，不绑定 FCTA/FCTB 规则。

## 2. 已完成

### 文档

- 新增 [DDD 缺口审查与补足设计](CR60_PI_UNIFIED_DDD_GAP_REVIEW_2026-09-01.md)；
- DDD 需求基线升级到 `v2.3`，加入 `AlertTimeline`、`DiagnosticConclusion`、US-026；
- PRD 升级到 `v2.5`，加入五类证据层、报警时间线和结论等级；
- 模块设计/软件设计/实施方案/Sprint/文档索引同步 `alert-timeline.v1`、runtime condition
  overlay 和 memory context scope；
- 调研报告新增 23.31/23.32，记录实际结果和边界。

### 代码和契约

- `engines/alert_timeline.py`：跨证据层报警行、播放帧 map、比较和 identity gate；
- `ai/modules/alert_timeline.py`：Pi/CLI 原子模块；
- `contracts/alert-timeline.v1.schema.json`；
- `engines/diagnostic_report.py`：接入 timeline 和 `conclusion`，HTML/Markdown/JSON 同源；
- `engines/diagnostic_narrative.py`：按真实条件、代入值和证据层生成文字命中过程及 `should_alert`；
- `engines/diagnostic_narrative.py`：默认输出 `executive_summary`、关键 operating/runtime facts、
  最多 10 条关键条件和 `condition_digest`；完整条件只在折叠证据/JSON 中展开，减少无意义堆叠；
- `engines/diagnostic_report.py`：对同帧目标 polygon/功能 ROI 计算几何关系，输出
  `observed_*` 或 `source_derived_*` containment 状态，并在 SVG 标出目标四角和几何关系；
- `ai/modules/pi.py` / `ai/pi_bridge.py`：Pi 输入支持显式 runtime/viewer/code/report 路径，按
  artifact 解析 function/side scope，生成确定性 `evidence_anchor`，报告请求自动落盘并记录
  `evidence-anchor` AnalysisStep；超时返回失败而不吞掉已生成的报告；
- `engines/diagnostic_report.py`：exact runtime observation 回填条件 trace；
- `engines/analysis_ledger.py` + `ai/modules/analysis_collaboration.py`：S2B Hypothesis、
  DebugExperiment、user-observation 原子持久化；计划先于实验结果，用户观察不升级 runtime；
- `engines/diagnostic_report.py`：从 AnalysisRun step/entity ref 投影 Analysis Trail、
  Hypothesis Board、Next Experiments 和 User Observations；
- `engines/memory_recall.py` / `ai/modules/memory_recall.py`：支持显式
  `pi-orchestration-context.v1`/`context_path` 的 variant/memory scope；
- `.pi/extensions/radar-capabilities.ts` 已按 catalog 重生成：当前 57 个能力（53 modules + 4 tools）。

## 3. 输入/输出契约

### 输入

详细报告和 timeline 可以使用：

```text
diagnosis_bundle.v1       # 录制/raw 事件和静态字段
viewer-model.v1           # 场景、连续帧、ego/target/ROI 展示投影
runtime-snapshot-with-frame.v1
runtime-case-evidence.v1
replay/GDB/CAN rows       # 必须带明确 layer 和 provenance
event-code-path.v1        # 当前源码条件/调用链/断点
pi-orchestration-context.v1
```

技术字段由 artifact 和当前 source 探测；用户只需提供数据/材料/业务问题以及必要的副作用确认。

### 输出

```text
alert-timeline.v1
  sources / rows / context_alarm_rows / playback_frame_map / comparisons / conflicts

diagnostic-report.v1
  identity / event_index / selected_event / alert_timeline / condition_trace /
  conclusion / diagnosis / next_actions / evidence_layers / refs
```

结论等级：`facts_only`、`supported_hypothesis`、`confirmed`、`blocked`。当前无 runtime/CAN
时只能是 `facts_only`，即使 `diagnostic-report.html` 成功生成也不能称根因已确认。

## 4. 实际验证

真实输入：

`/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag`

现有静态产物：

`outputs/single_case_actual_CRGVI1829_20260901/batch/data/CRGVI-1829-single-2026-07-19-11-56-15-11/`

重新生成报告：

`outputs/single_case_actual_CRGVI1829_20260901/ddd-audit-report-FCTA_R/diagnostic-report.html`

运行态增强报告（复用已保存的 arbe public runtime run5 artifact）：

`outputs/single_case_actual_CRGVI1829_20260901/ddd-audit-report-FCTA_R-runtime-run5/diagnostic-report.html`

GDB/几何增强报告（复用已保存的 isolated GDB artifact）：

`outputs/single_case_actual_CRGVI1829_20260901/ddd-audit-report-FCTA_R-runtime-gdb/diagnostic-report.html`

观察：

- raw `FCTA_R/radar2` 有事件，selected analysis frame `47877`；
- `47872..47876` 是 SGU 目标级回放的 5 帧 warm-up，`47877` 是 selected analysis frame；
- 当前帧来源为 nearest-LGU/time-aligned，故 frame status 为 `derived`；
- 当前 sibling bundle 没有独立 `data_fingerprint`，timeline identity status 为 `partial`；没有
  用报告 JSON 的 hash 冒充 bag hash；
- replay/public/GDB/CAN 层当前未传入，报告逐层显示 `not_available`，compare 为 `not_evaluated`；
- 结论为 `facts_only/partial`，没有给正报/误报或根因已确认结论；
- 当前报告仍保留真实 ego/target code token、`objID=44`、`i=0`、algorithm index、objectlist index、
  源码条件和缺失 runtime token。
- 运行态增强报告显示 `runtime_with_frame=observed`、60 条 FCTA_R 运行态报警字段，
  `frame=47876` 为运行态上升线索、`frame=47877` 仍为非零；raw/runtime compare 仍为
  `not_comparable`，因为 raw 首帧是 derived time-aligned candidate；`should_alert=supported_yes`
  仅表示算法输出层支持，`conclusion.level=facts_only` 仍保留，CAN Tx 未被冒充。
- 同一 public runtime 报告还保留选定帧的 `objectlist_candidate` 目标属性（含 objID=44），
  关联等级为 `publication_order_derived`；该层不会被当作 runtime exact polygon 或同帧算法真值。

GDB/几何增强报告读取到 `frame=47877/objID=44` 的 GDB observation、4 个 runtime target polygon
角点和 1 个 runtime ROI；完整条件 trace 为 `satisfied=5/not_evaluable=17`，其中 FCTA/R scope
为 `satisfied=3/not_evaluable=11`。由于 GDB transcript
有命令错误且 `disturbance=suspected`，报告明确降级，不能作为无扰动实车真值。

报告默认呈现已调整为“文字结论优先”：页面先给出功能/侧别/radar/frame/objID、自车和目标关键 token、
报警输出层和 `should_alert`，再显示关键条件和选中帧附近的 timeline；完整 `condition-trace`、
runtime observation 和事件投影保留在折叠区/JSON，不再默认展开大段原始数据。

另外，三份真实报告均显式暴露了事件内部的映射质量问题：选定事件为 `radar=2`，而
`frame.gui_main_mapping.radar_id=3`。该冲突被记录为 `frame_radar_mapping_conflict`，不会改变
事件 scope，也不会让 radar3 的数据混入 radar2 的诊断。

定向验证：

```text
97 passed（扩展定向组合，含 Pi capability catalog CLI、S2B 协同 Debug）
py_compile: passed
Pi extension generation: 57 capabilities (53 modules + 4 tools)
```

另经 `python -m ai.capability.pi_tool_bridge --name alert-timeline --params ...` 对同一真实
bundle/viewer 做了原子调用，bridge 返回 `alert-timeline.v1`，raw row 为
`FCTA_R/radar2/frame=47877/objID=44`，其余 replay/runtime/GDB/CAN 层保持
`not_available`；说明新能力已通过 Pi 的正式 Python bridge，而不只是直接 import engine。

Pi 真实入口验收：使用 `python cli.py pi --question ... --case-dir ... --runtime-evidence ...`
调用本机 `bosch-qwen3_6 / Qwen3.5-27B-FP16`，验证了 Pi 可以读取确定性 `evidence_anchor`，
锁定 `FCTA_R/R`，并输出 `frame=47876` 算法上升沿、`frame=47877` active、
`source_derived_disjoint` 和 `indeterminate`。报告请求版本已生成：
历史验收目录已在 2026-09-03 清理，当前复核入口为
`outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`；对应 AnalysisRun
记录了 `evidence-anchor` 和 dialogue step。一次故意等待超时的回合返回 `ok=false`，同时保留
已生成 report artifacts，证明不会把超时伪装成成功。

详细报告现已从 `analysis-run.json` 的 step ref 读取结构化阶段摘要，Pi 入口生成的报告中
可见 `evidence-anchor` / `dialogue` 的状态、observations、gaps 和 next actions；没有
AnalysisRun 时仍显示 `not_provided`，不伪造过程。基础 `analysis_run_id` / Pi session
恢复已覆盖测试；用户 accept/question/irrelevant decision 和 Live Workbench 仍是后续切片。

本轮还修复并实测 `python cli.py capabilities --json` 的实际入口；基础切片时 Python
registry、Pi bridge `--list` 和 `.pi/extensions/radar-capabilities.ts` 为 54 个可暴露叶子
能力，加入 S2B 协同 Debug 能力后当前为 57 个；不包含 `pi/agent-loop` 编排根，
`runtime-debug-run` 的审批要求仍为 true。

旧 GDB artifact 的标量字段也已在 canonical read 阶段规范化：报告当前显示
`g_egoCarAddInfo.actual_gear=4`，并保留原始 GDB 文本字段，避免条件求值把可解析的数值
误当作字符串。

2026-09-01 重新执行只读 `arbe-preflight` 的结果已保存为
`outputs/arbe_preflight_refresh_20260901.json`：当前 outer/algo HEAD 分别为
`4c171298b2c3583509ea9e3da222b90ba0a9e513` / `a81b08a38f316a3d25bfcbcad6dcfc822d24b990`，
COEM/CUDA/sheet 为 `BYD_UKE` / `CUDA_BYD_UKE_Bundle_V2.0.xlsx` / `03_QZH`，
`BUILDMODEL=2/HILMODEL=2`，binary fingerprint 为
`93a8f2b2c11a6d8ba1abadbc7eb480e8867352f261a71c4bb5023f4c4ef80890`，四个 radar visualization
engine 均已存在；workspace dirty、`ptrace_scope=1` 和 CAN 仅有源码候选仍未跨过正式副作用门。

## 4.1 本轮继续实施与真实验收（2026-09-02）

> 注：本节记录本轮中间阶段快照；后续完成了真实 GDB 日志规范化、source identity 修正、
> runtime 有界查询修正和局部变量真值门禁，最终状态以 4.2 为准。

- `arbe-preflight` 已改为按当前 YAML 的 `coem_name` 限定 source 扫描，不再对所有 COEM
  做固定 `head -n 320` 截断；当前远端 `BYD_UKE` 实测有效 `RteComMapping_WriteSignal=191`、
  transport `RteLite_Write_* → Com_SendSignal=762`，并排除注释映射。
- preflight 新增 `public_evidence.objectlist_frame_contract`，当前 source 已证明
  `corner_radar_post_process_data_callback` 先调用 `wf_object_display_handler()`，后发布
  `warning_status_with_frame`。公共 runtime `auto` 只有在该证明存在时才采用
  `publication_order`，否则保持 strict/unbound。
- 详细报告新增 `Source output chain`、`Public runtime binding` 两个 compact 区块，并将
  source `RteComMapping → RteLite_Write_* → Com_SendSignal` 作为 `source_candidate` 展示，
  不将其冒充 CAN Tx observed。
- `condition_trace` 新增当前源码证明的局部 copy alias：
  `objInfo->trcOutData[i] → sObj`，只回填未再次赋值字段；真实 FCTA_R 报告现在能把
  `sObj.objFctaWarningFlag` 与同帧 GDB `objInfo->trcOutData[i].objFctaWarningFlag=4`
  绑定，并单独标出 `object_warning_observed`。
- 真实报告重建：
  `outputs/single_case_actual_CRGVI1829_20260902/diagnostic-report-final/diagnostic-report.html`；
  status=`ready`，condition=`22 total / 6 satisfied / 0 not_satisfied / 16 not_evaluable`，
  source output=`5` 条 event-scoped 候选，object warning=`observed`，最终 alarm/CAN 仍为
  `indeterminate`。
- 本轮定向验证：`36 passed`（public/runtime/preflight/condition/narrative），此前核心
  组合 `68 passed`，Pi extension 重新生成 `57 capabilities (53 modules + 4 tools)`；未做
  全量回归，未对远端执行 checkout/build/start/attach。

## 4.2 本轮最终收口与当前可用边界（2026-09-02）

本轮按“先修身份/证据绑定，再出报告”的 DDD 验收顺序完成了一次真实单数据闭环：

1. 从远端 `10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 的工具自建隔离 GDB 日志
   规范化 `runtime-case-evidence.v1`，保留 `gdb_observation`、断点栈、局部变量、C 结构体
   字段和 `objPoly/rightRoi`；工具自建的 11324 进程已清理，正式四 radar 进程未被停止。
2. 按真实 `source_snapshot_hash`、bag path、source context 和 binary fingerprint 绑定公共
   runtime 与 GDB；发现并修正了一个 source context 字符串错误，以及 legacy
   `source_index_hash` 优先级导致的假冲突。
3. `event-code-path` 继承 enclosing code context 的 source identity；runtime query 通过
   事件中明确的 `details.feature.entry_function` 将外部 `FCTA_R` 和实际
   `FrontCrossTrafficAlertAndBrake` 连接，并在有界切片中优先保留同帧 GDB/selected object/
   public frame。
4. 当前报告已能文字说明：`frameID=47877`、`i=0`、`objID=44`，自车/目标属性，实际
   `fTTMX/fTTMY` 与当前源码阈值的代入，`rightFctaRoi->num=10`，目标 warning flag，
   `adasWarning->bRightFctaWarning=2`，以及源码 `RteComMapping → RteLite_Write_* →
   Com_SendSignal` 候选链。
5. 当前真实报告明确标注 `objPoly` 与 `rightRoi` 为 `observed_disjoint`，同时明确它不替代
   FCTA 使用的预测交点/TTM/状态机逻辑；公共输出 `FCTA_R=2` 在 `47876` 有上升线索、
   `47877` active，但 CAN Tx 上升沿尚未观测。
6. `info args/locals` 跨 stop 且无 source-line binding 时只做展示，不参与条件真值；因此不会
   把较早的 `rightFctaWarningNum=0` 错用于后续 `adasFunc.c:10255`。单纯 `No symbol` 只
   记录为字段缺口，不再自动标记 replay disturbance；真正 ptrace/内存/runner 故障才进入
   `suspected/confirmed`。

最终产物：

- HTML：`outputs/single_case_actual_CRGVI1829_20260902/diagnostic-report-final/diagnostic-report.html`
- JSON：同目录 `diagnostic-report.json`
- Markdown：同目录 `diagnostic-report.md`
- runtime composite：`outputs/single_case_actual_CRGVI1829_20260902/runtime-evidence-final.json`
- current code context：`outputs/single_case_actual_CRGVI1829_20260902/code-context-current/code-context.json`
- current event code path：`outputs/single_case_actual_CRGVI1829_20260902/event-code-path-current.json`
- GDB source-condition plan：`outputs/single_case_actual_CRGVI1829_20260902/runtime-debug-plan-source-condition.json`

验收结果：radarAnalyze 相关定向测试 `120 passed`；sibling SSH/GDB runner 测试 `8 passed`；
diagnostic report/narrative/runtime evidence/preflight/event-code-path/code-context/runtime-debug-plan
schema validation 全部通过；Pi catalog 为 `58` 个可暴露能力（`54 modules + 4 tools`）。本轮
没有做全量回归，也没有对远端执行 checkout/build/start/formal PID attach。

Pi RPC 冒烟在显式 `bosch-qwen3_6 / Qwen3.5-27B-FP16` 下返回 `PONG/agent_settled`；默认
provider 探测的 30 秒冒烟曾超时，已将 provider/model 做成脚本可选参数。带完整证据的长问题
回合在模型响应阶段达到 timeout，但 deterministic anchor 和 HTML 已落盘，Pi 返回
`ok=false`，没有将超时伪装为成功；这仍是长链路响应效率缺口，不是静态报告/证据链失败。
随后执行短交互问题（要求只基于 evidence anchor、不继续扩散工具调用）成功返回
`ok=true / agent_settled`，创建并完成 `AnalysisRun=run-20260902T055424-ce7520198c`，
该次短验收报告目录已在 2026-09-03 清理；当前报告入口为
`outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`。回答已
列出真实源码条件、runtime 结果和 CAN/后处理缺口。

这意味着当前产品已经具备“真实数据→公共/GDB runtime evidence→源码条件代入→文字优先 HTML
报告→Pi 原子能力继续追问”的可用闭环；仍不等于自动拿到 CAN Tx 首帧、所有后处理状态机变量，
或自动签署正报/误报根因。

## 4.3 本轮几何判定语义修正与无 CAN 端点（2026-09-02）

本轮针对实际报告截图完成一次“图形事实”和“代码语义”的对照审查。当前
`CRGVI-1829 / FCTA_R / radar2 / frameID=47877 / objID=44 / i=0` 的 GDB 多边形计算为
`objPoly/rightRoi=observed_disjoint`：目标四角约为
`(6.683,-2.259),(3.827,-6.055),(5.297,-7.161),(8.153,-3.365)`，右 ROI 的横向范围为
`0 ... -1.0855`。这个结果不能被报警事实反向改写，目标 `yawAng=53.0400009` 必须继续
参与旋转四角计算。

审查当前 `adasFunc.c` 约 `9988-10005` 行后确认：FCTA 在这里执行
`adasObjPloyCal(sObj, &objPoly)`，但 `rightFlag` 的设置来自
`rightFctaRoi->num > 0U`，不是当前目标多边形与 ROI 的相交判断；“Determine whether two
polygons intersect”只是过时注释。后续判定使用 `FctaDirectRunning` 计算出的预测状态和
TTM。当前 runtime 观测到 `fInterX≈8.38272381`、`fInterY=0`、`fTTMY≈0.564559579s`
（另有结构体 token `sObj->fInterX≈8.34897423`），所以报告必须分层显示：

- 当前几何：`observed_disjoint`；
- 源码 gate：`rightFctaRoi->num > 0U` → `rightFlag=true`，含义是 ROI 可用，不是目标已侵入；
- 预测关系：`fInterX/fInterY/fTTMY`，用虚线和预测点表示，不能替换当前目标多边形。

`diagnostic_report` 已加入通用 `geometry_projection.predicted_intersection`、
`algorithm_branch` 和 `instantaneous_relation`，HTML 将预测点纳入视图边界并画出目标中心到
预测点的方向线。runtime 有界字段投影也优先保留同一字段族中 status 为 `observed/derived`
的数字值，避免 `not_found` token 抢占 `fInterX/fInterY/fTTMY` 的展示槽位。

同时落实用户确认的输出口径：CAN 缺失或未探测到时，报告的有效终点为算法最终输出，
`output_policy.effective_endpoint=algorithm`、`can_required=false`；公共运行态的
`FCTA_R=2` 可以作为算法输出层观察结果，但不冒充 CAN Tx。存在 CAN 数据时才切换到
`can_tx` 终点。该策略由通用 output policy 控制，不绑定 FCTA/FCTB。

本次更新保持 DDD 边界：确定性 engine 负责坐标/字段/源码证据投影，HTML 只呈现这些证据，
Pi 负责后续组合和自然语言解释；没有将当前案例的数值或 FCTA 规则写入通用渲染器。

## 4.4 结构化诊断流程 HTML 验收（2026-09-02）

根据用户提供的“结构化对象数据→逐级代入代码→报警结论”示例，详细报告新增
`diagnostic-analysis-flow.v1`。这不是针对 BSD 的特判，而是对已有 artifact 的顺序化读模型：

1. `input_context`：展示当前事件 scope、真实自车/目标 token 和值；
2. `source_condition_walk`：按源码行展示关键条件、`bindings`、代入后的表达式和求值状态；
3. `geometry_and_prediction`：并列展示当前 polygon/ROI 关系、source ROI gate 和 runtime
   预测点；
4. `output_decision`：依据 `output_policy` 选择算法输出或 CAN Tx，并列出支持结论的源码行、
   未满足分支和缺口。

HTML 首屏只显示关键条件卡，完整条件仍在 `condition-trace.v1`；条件卡不把不同 `if/else`
分支自动拼成 AND 链。参数值来自当前 source/index 或同帧 runtime binding，无法获取时保持
`not_evaluable`。用户给出的 BSD 示例中的速度阈值只有在当前代码和数据都绑定成功后才会进入
结论，不能用示例文本反向生成事实。

本次实际报告已重建：

`outputs/single_case_actual_CRGVI1829_20260902/diagnostic-report-final/diagnostic-report.html`

报告结构检查通过：4 个 flow steps、10 个关键 condition cards；`diagnostic-report.v1` 和
`diagnostic-narrative.v1` schema validation 通过，相关定向测试 `22 passed`。没有做全量回归。

## 4.5 详细报告 UI 结构优化（2026-09-02）

用户要求“参数用表格、然后绘图、然后文字描述”，并明确准确性和代码逻辑优先于视觉效果。
报告页面现按以下顺序组织：

1. 结论摘要：只放当前输出端点和最短结论；
2. 报警参数表：滚动表格，按自车、目标、源码参数/条件、runtime 中间量、几何预测分组，
   列出真实 token、值、单位、数据状态和来源；
3. 场景图：同帧目标/自车/ROI 当前几何与预测关系；
4. `diagnostic-story.v1`：以自然语言描述代码入口、逐步条件代入、几何/预测和最终输出；
5. 时间线、代码链、GDB 和完整 JSON：作为后续查证的折叠/细节区。

`_parameter_table_html`、`_diagnostic_story_html` 都是确定性投影，不创建或修改事实。页面布局
变化不改变 `diagnosis_bundle`、`condition_trace`、`runtime evidence` 和 geometry projection。
当前真实报告的参数表与流程卡均已重新生成，HTML 标签结构解析和两个 report schema 校验通过。

## 4.6 GDB 与 arbe 报警灯链路验收（2026-09-02）

当前实际数据的 GDB 证据已经闭环：隔离 runner 的 `gdb-session.v1.status=succeeded`，
`runtime-case-evidence.v1` 中 GDB observation 为 `observed`，并且
`frameID=47877/radar_id=2/object_id=44/algorithm_index=0` 与选定事件一致，命中
`adasFunc.c:10093`。报告将此表示为“GDB 已确认命中”，但仍显示 10 个不可用 probe，
不把 GDB 成功夸大为所有局部变量都可用。

报警状态的实际证据包括：

```text
adasWarning->bRightFctaWarning=2
bFctaRightWarningFlg=true
objInfo->trcOutData[i].objFctaWarningFlag=5
objInfo->trcOutData[i].rightFctaFlag=true
i=0, frameID=47877
```

当前 `HILMODEL=2`、回放策略为 `sgu_injection`，所以这次是录制 bag 输入经过 arbe
工作区的 SGU 目标级仿真；不是点云级 150-200 帧感知回放。报告同时保留预热范围
`47872 → 47877`。

通过 SSH 对当前 arbe GUI source 的只读核验确认：`visualization_node.cpp:4063-4078`
把 `algo_adasWarning` 写入 `/corner_radar/warning_status`；
`visualization_node.cpp:4080-4087` 将同一数组加上 `frame_counter` 发布到
`/corner_radar/warning_status_with_frame`；GUI `viewpanel.cpp:2276-2291` 订阅
`/corner_radar/warning_status` 并更新报警灯。因此在没有 CAN 的 rosbag 中，最终诊断
端点是算法输出 `algo_adasWarning`，而不是 CAN。`warning_status_with_frame` 是同一输出
的逐帧定位版本。

本例的算法报警上升沿为 `frame=47876`，而本次 GDB 成功命中的目标帧为 `frame=47877`，
报告已标注“上升沿后 1 帧”。这证明 GDB 在选定活动帧生效并补充了内部数据，但不冒充
精确上升沿现场；后续 exact-edge 调试应由 Pi 重新生成 target frame=47876 的同一计划。

## 5. 当前未完成，不得误报完成

1. `runtime_with_frame` 的 stamped object snapshot/callback collector；
2. 正式 `bash start` 后的完整 GUI player parity；
3. existing PID attach 在当前 `ptrace_scope=1` 下的权限解法；
4. 精确 CAN Tx 0→非零上升沿和 frame 绑定；
5. point-cloud 150–200 帧 perception/tracking runtime trace；
6. Hypothesis/DebugExperiment 的用户确认、反证和 Live Workbench；
7. 两个异构 Gen6 项目 capability SPI 验收；
8. Pi 自动执行批量→详细报告→AI panel→runtime 的长链路现场验收。

## 6. 下一步建议

按成本和价值排序：

1. 在同一 Pi run 中接入一次 `sim-verify --mode remote_public`，生成
   `runtime-snapshot-with-frame.v1`，让 `auto` 消费当前 preflight 的 source contract，并用
   `alert-timeline` 投影，确认公共 warning/radar_info/objectlist 与静态事件的 compare；
2. 优先增加最小 stamped snapshot bridge，保证 object/ego/warning/ROI 在算法 callback 内共享
   frame identity，减少 GDB 次数；
3. 若公共 snapshot 仍不能给出局部状态，再执行已批准的 SGU headless GDB，结果以
   `gdb_observation` overlay 合并并回填 condition trace；
4. 采集 CAN Tx 后，才允许把“selected analysis frame”升级为用户定义的报警首帧；
5. 再建设 Hypothesis/Experiment 和 Workbench，不先继续堆叠功能规则。

## 7. 交接检查

- [x] 文档先行，缺口记录在审查文档和调研报告；
- [x] 新能力为原子 engine/module/schema，并进入 Pi catalog；
- [x] report 与 timeline 共享确定性 engine；
- [x] 缺层、跨帧、身份冲突均有显式状态；
- [x] 没有执行远程 arbe 写入、checkout、build、start 或 formal GDB attach；
- [x] 没有做无价值的全量回归；
- [x] 当前 COEM 的源码输出扫描不再跨车型混扫或按固定 320 行截断；
- [x] 报告展示 source output chain，并保留“静态候选≠CAN Tx observed”边界；
- [x] `objInfo->trcOutData[i]` 到 `sObj` 的源码证明 alias 已纳入 condition trace；
- [ ] 联合 runtime/GDB/CAN 现场验收；
- [ ] 用户确认默认自动推进节奏、人工 GDB 回填方式和根因签字人。
## 4.7 首屏结论和数据表验收口径（2026-09-02）

详细报告首屏必须直接回答“发生了什么、为什么报警”：先呈现总结性分析结论，再呈现报警帧
关键数据表，后续才展开图形和源码命中流程。表格使用当前 source/runtime 的真实 token 和
数值，不让用户从内部状态层或 JSON 自行推导结论。

默认报警终点是 arbe 可视化工具报警灯对应的算法最终输出。CAN 不属于用户主流程的必读项，
只作为显式需要时的下游辅助证据保留在机器产物或展开详情中。

FCTA 的几何解释必须区分“当前目标矩形与 ROI 的瞬时关系”和“代码计算的未来交叉预测”。
当前 source 中 `rightFctaRoi->num > 0U` 是 ROI 可用性/路径 gate，并不是目标 polygon 相交
判断；`FctaDirectRunning`/`FctaTurning` 计算的 `fInterX/fInterY` 与 `fTTMX/fTTMXObj/fTTMY`
才是后续功能条件使用的运行态量。因此图上 `observed_disjoint` 与算法报警可以同时成立，
报告必须把这条原因写进总结结论，而不是把图形误判为绘图错误或直接判定误报。

## 4.8 独立 Pi 入口与动态代码链验证（2026-09-03）

- `python cli.py pi` 已作为脱离 ChatGPT 的独立产品入口保留；Pi 使用生成的
  `registerTool` 和 `pi_tool_bridge`，代码分析 allowlist 已包含
  `code-context-refresh`、`code-learn`、`code-analyze`、`event-code-path`；
- `event-code-path.v1` 新增动态 `condition_chain`，从当前 source 的 caller/helper/event root/
  callee 候选关系和源码位置生成，不绑定具体功能、变量名或固定条件顺序；
- 详细报告首屏顺序已收敛为总结结论、报警条件链表、报警帧数据表、工况图和自然语言命中流程；
- 直接 CLI `diagnosis-report` 已完成带 `--gdb-session` 的真实 artifact 冒烟，返回
  `ok=true/status=ready`；Pi/报告工具的 summary response 只回传有界摘要和 artifact ref；
- 动态 source-chain GDB 计划已生成并执行一次隔离 runner。runner 返回成功但远端 ROS 节点
  通信失败，session 未形成有效 observation，故没有覆盖既有已确认的 GDB 证据；当前结论是
  “动态计划能力已具备，任意远端环境的稳定 runtime 取证尚未验收”。

当前独立运行仍需 Python/Node/Pi、provider/model、项目配置、source context 和远端 arbe
profile；尚未宣称零配置发行包或所有 Gen6 项目的一键运行。

## 4.9 HTML 结论可读性修正（2026-09-03）

用户验收反馈“代码罗列不能作为分析陈述”。当前首屏已把条件链表改为自然语言判断和关键值，
源码表达式、代入表达式和完整 trace 只在行内详情/完整 artifact 中展开；报警帧的自车、目标、
runtime 变量仍以真实 token 数据表保留。最新报告已用当前 FCTA source chain 重新生成，
并通过 HTML 结构检查和定向测试。

## 4.10 报警输出到 FCT/ASW 对外信号的自然语言闭环（2026-09-03）

本轮把用户要求的“报警行为要讲到最后”落实为新的通用读模型：
`diagnostic-output-chain.v1`。它不是另一套功能规则，而是把三类证据按实际源码顺序串起来：

1. 同帧 `adasWarning`/arbe 报警灯算法输出；
2. 当前 source 中承接该输出的内部 member path、赋值语句和生产函数；
3. 对外 `WriteSignal` expression 以及当前 source 找到的 RteLite/`Com_SendSignal` 调用点。

`arbe-preflight.v1.can_output.source_output_chain` 由当前 COEM 的只读 member-assignment scan
产生，保留 `source_active`、`source_commented`、`not_found` 等状态；报告侧再将同帧 GDB/public
runtime 观察叠加为 `runtime_observed`。因此可以回答“代码上下一跳是什么”，但不会把静态
候选误写成已执行。

当前真实刷新结果（`BYD_UKE`）确认：

```text
adasWarning->bRightFctaWarning=2 (GDB, frame=47877)
 -> AdasStM.Frontright_FCTA = ADAS_Warn_Process_FrontRight_FCTA(...)
    (ADAS_HMI.c:3623, source_active)
 -> RRadar_FCTA_Warning_Right_S = (AdasStM.Frontright_FCTA == 2) ? 1u:0u
    (RteComMapping_Tx.c:147, source_candidate)
 -> RteLite_Write_RRadar_FCTA_Warning_Right_S -> Com_SendSignal
    (rteLite_PubCan_FCRonly.c:177, source_candidate)
```

本次报告明确指出 `AdasStM.Frontright_FCTA` 尚未被当前 GDB 停点直接观察，因此算法输出
结论是 confirmed，而下游映射结论是 source candidate。后续 GDB 只需补充映射调用点的
同帧断点/字段采集，报告即可增量提升证据等级；无需重新设计 HTML，也不需要为 FCTA 写死
一套流程。

本轮实际报告：`outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html`。
