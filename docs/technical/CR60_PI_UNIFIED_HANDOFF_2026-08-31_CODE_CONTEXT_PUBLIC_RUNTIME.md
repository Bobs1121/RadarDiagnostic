# CR60 Pi Unified：Code Context / Event Path / Public Runtime normalizer handoff

版本：`handoff.v1`  
日期：2026-08-31  
阶段：S1B-prep / S2A-prep  
状态：`partially-verified`

## 1. 本切片目标

把“代码一次性处理”和“arbe 公共运行时字段”做成 Pi 可组合的原子能力：

```text
current source snapshot
        ↓
code-context.v1 + code-index.v1
        ↓
event-code-path.v1
        ↓
public runtime rows → runtime-snapshot-with-frame.v1
        ↓
后续 HTML / AnalysisRun / GDB overlay
```

本切片不启动正式 arbe、不播放 bag、不执行 GDB，也不宣称已经获得最终 CAN Tx 或完整
算法局部变量。

## 2. 已交付

| 原子能力 | 产物 | 当前职责 |
|---|---|---|
| `code-context-refresh` | `code-context.v1` + `code-index.v1` + CodeGraph DB | 当前源码内容指纹、函数/调用/变量/信号/条件/状态/参数索引 |
| `code-context-read` | section 查询结果 | 不重扫源码读取限定代码关系 |
| `event-code-path` | `event-code-path.v1` | 事件→真实函数→五层代码视图→root GDB plan |
| `public-runtime-normalize` | `runtime-snapshot-with-frame.v1` | warning/radar_info/objectlist 行的明确 frame/callback 关联 |

新增公共契约：

- `contracts/code-context.v1.schema.json`
- `contracts/code-index.v1.schema.json`
- `contracts/event-code-path.v1.schema.json`
- `contracts/runtime-snapshot-with-frame.v1.schema.json`

Pi extension 已重新生成，当前为 49 个正式能力（45 modules + 4 tools）。历史代码查询
入口仍保留在 CLI/AgentLoop，但不再暴露给 Pi，避免重复能力。

## 3. 真实源码镜像验证

服务器：`10.190.171.44`；远程 source：
`/home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/algo_source`；当前 algo HEAD：
`a81b08a38f316a3d25bfcbcad6dcfc822d24b990`；代码处于 detached/dirty 状态。

远程只读核验发现：整个 algo_source 约 3642 个 C 文件，BYD_UKE 目录约 780 个 C/C++
文件。因此测试只按显式关键文件建立本地只读镜像，没有复制整仓，也没有修改远端。

镜像包含当前 BYD_UKE 的 `adasFunc.c/h`、`dotCalibDefine.h`、ASW ADAS、ASW IN/OUT、
AswIfSchedule、RteComMapping 以及 symmetry perception 定义文件，共 16 个文件。运行：

```text
functions: 205
calls: 220
variables_read: 3073
variables_written: 988
signals: 309
conditions: 1268
parameters: 109
```

这次验证还发现并修复了现有 regex analyzer 的两个通用问题：同一行函数体不识别、相邻
函数被跳过；同时新增括号深度条件提取，避免 `((...))` 条件被截断。当前镜像产物：

[code-context.json](../../outputs/remote_code_context_test_20260831/context/code-context.json)  
[code-index.json](../../outputs/remote_code_context_test_20260831/context/code-index.json)  
[FCTB event path](../../outputs/remote_code_context_test_20260831/fctb-event-code-path.json)

## 4. 真实事件代码路径 smoke

使用当前索引中的真实函数 `FctaFctbUpdateStatus`，事件输入绑定：

```text
frame_id=47877
radar_id=2
object_id=44
frame_scope: frame_counter 47872..47877
object_scope: sObj->objID == 44
```

结果：`status=ready`，解析到当前 `adasFunc.c:2521`，抽取 17 条条件、17 条变量读取、
22 条变量写入；root GDB plan 的条件为：

```text
(sObj->objID == 44) && (frame_counter >= 47872 && frame_counter <= 47877)
```

其中 `sObj->objID == 44` 由事件条件和 object scope 同时提供时已去重。该字符串仍然只是
用户提供事件范围与当前函数位置组成的 GDB 计划，不代表该函数就是最终 CAN Tx 输出点。

## 5. Public Runtime 归一化边界

当前 arbe 事实：

- `/corner_radar/warning_status_with_frame` 的 `data[0]` 是 radar，`data[1]` 是
  `frame_counter`；
- `/corner_radar/radar_info` 的 `data[0]` 是 radar，`data[4]` 是 frame，并包含 ego
  speed/yaw rate/detections/cycle time；
- `/wf/objectlist_<radar>` 目标字段丰富，但当前消息没有算法 `frameID`，header stamp
  是发布时刻。

因此 normalizer 的规则是：

```text
显式 object frame       → frame_verified
明确 callback 可匹配      → callback_correlated
只有 timestamp/无关联    → unbound_objects
```

若当前 source 分析确认同一处理周期内 objectlist 先于 warning_status_with_frame 发布，
且 capture 保留消息序号，调用方可显式选择 publication_order；对象将标记为
publication_correlated，并保存 derived 关联依据。没有该 source proof 时仍使用 strict，
不按 timestamp 近邻绑定。

它不会按时间近邻把目标挂到报警帧。实际 ROS subscriber、BagReader event/scene 播放和
arbe stamped snapshot bridge 仍是后续能力。

## 6. 验证结果

本切片只执行定向验证，没有再次执行全量回归：

```text
tests/test_code_context.py       \
tests/test_event_code_path.py    \
tests/test_public_runtime.py     \
tests/test_code_gdb_plan.py

16 passed
```

此前在 Ledger/CodeContext/EventCodePath 基础切片上的全量回归为
`666 passed, 1 skipped, 2 xfailed, 10 warnings`；它不作为本次 public runtime 变更的全量
回归证据。

## 7. SSH 真实回放补充验证

在当前远程 ROS master 使用 SSH 做了 4 秒实际回放并记录公共输出：

```text
PLAY_RC=0
captured messages=1205
warning_status_with_frame=241
radar_info=241
objectlist_1..4=61/60/60/60
FCTA_R/FCTB_R first algorithm rise: frame_id=47876, radar2
```

`radar2/frame=47876` 的 `radar_info` 为 `ego_speed=4.4284453392`、
`yaw_rate=0.2395757139`、`detections=274`、`cycle_ms=67.9702759`。同一发布时序附近的
`/wf/objectlist_2` 有 `objID=44`，位置 `(5.9200000763,-4.9099998474)`、`Ang=54.0099983215`、
`fTTC=1.0115679502`、`fDDCI=8.3489742279`、FCTA/FCTB object flag=5；但它没有 frame
字段，因此规范化结果仍是 `unbound`，没有伪造 exact same-frame。

规范化后的实际结果见：

[normalized runtime snapshot](../../outputs/remote_public_capture_20260831/runtime-snapshot-with-frame.json)

这次实验说明公共输出采集路径可行，也验证了“全局 warning 值”和“object flag 值”不是
同一数值域；仍不能替代最终 CAN Tx 或 stamped object snapshot。

## 8. 未完成与下一步

远程 source mirror/fetch adapter 仍未产品化；当前 code-context 真实测试使用显式关键文件的
手工只读镜像，不能宣称可自动处理任意远程仓。
PublicRuntimeCollector 仍需接 ROS/BagReader，按 jumpToFrame/scene/ACK 做正式场景采集；
sim-verify remote_public、public-runtime-normalize、runtime-evidence-normalize 和
runtime-evidence-merge 的短窗口/事件 scope 已接通，但 publication_correlated 仍不是 exact frame。
HTML 目前可消费 canonical runtime evidence overlay，尚未把 public snapshot 的完整帧序列
直接纳入 Sprint1 viewer；AnalysisLedger 尚未由各 provider 自动写 step。
Hypothesis/DebugExperiment 和人工 VSCode observation 尚未落地。

下一步按小切片推进：产品化远程 source mirror、BagReader event/scene/ACK collector、
stamped snapshot bridge，并将 public snapshot/canonical evidence 接入 HTML/AnalysisRun；
只有 Sprint 收口或公共契约变化时才做全量回归。

## 9. 真实远端 sim-verify 目标绑定增量验收

在补齐 capture message sequence 后，使用既有 sim-verify remote_public 入口，针对同一
服务器/arbe/bag 的 radar2 单雷达窗口执行 approved replay。结果 artifact：

- outputs/remote_public_capture_20260831/sim-verify-session-run5.json
- outputs/remote_public_capture_20260831/sim_verify_capture_run5.json

验收结果：play/record/extract 均为 0；带帧报警 FCTA_R、FCTB_R 的上升沿均为
frameID=47876；120 个 frame snapshot 中有 60 个包含目标记录，716 条目标记录全部
通过 publication_correlated 绑定，unbound_objects=0。

当前源码证明 objectlist→warning_status_with_frame 是同一处理周期的发布顺序，因此这次
显式启用 object_association_mode=publication_order。该模式保存 object_message_seq、
warning message sequence、关联方法和 derived confidence；它不是 wfObjectMsg 自带的
frameID，也不允许在没有当前 source proof 时默认启用。默认仍是 strict。

对 objID=44 的报警窗口，frameID=47872..47877 均可展示 object_index=0、ID=0、
distX/distY/Ang、Vx/Vy、fTTC/fDDCI 及 FCTA/FCTB object flag。object_index 是发布
ObjectsBuffer 下标；源码循环变量 objInfo->trcOutData[i] 仍属于代码/GDB证据，不能
从 object_index 反推或改名为 i。

## 10. run6 复验与能力边界修正

对同一输入再次执行 sim-verify remote_public（artifact：
outputs/remote_public_capture_20260831/sim-verify-session-run6.json）。远端回放、录制、
提取均成功，但 recorder 的跨 topic 写入顺序发生变化：warning_status_with_frame(frame=47874)
先于同周期 objectlist 被写入。严格关联拒绝 32 条对象行，objID=44 在 47874/47875 没有
被错误挂接；结果为 object_snapshots=57、object_records=683、ignored_objects=1、
unbound_objects=32，算法 FCTA_R/FCTB_R 上升沿仍为 frameID=47876。

因此 publication_order 只能提供“可证明时的 derived 关联”，不能替代消息级 stamped frame。
后续 HTML 必须分别标示 frame_verified、publication_correlated 和 unbound；如果用户要求
报警首帧的绝对目标属性，优先使用同一算法 callback 内的 stamped snapshot/collector，
或在 frame_counter 停止点用 headless GDB 读取 objInfo->trcOutData[i]/sObj。

## 11. wfSObj 占位行处理

当前 viewpanel.cpp 的 ObjectListDispByRadar() 跳过 obj.ID < 0；因此 public-runtime-normalize
新增 source-aware object_validity_policy。默认 preserve；在确认当前消息契约后使用
arbe_wf_sobj，把 ID=-1 放入 ignored_objects，不把它呈现为目标。run5 的消费快照为
真实 object records=715、ignored_objects=1；这不影响 objID=44 的逐帧 derived 关联。
该策略由当前 source/消息定义驱动，不能作为跨项目全局硬编码。

## 12. ProjectCapabilityManifest 真实一致性门禁

使用当前 CRGVI-1829 的 preflight、16 文件 code-context mirror、run5 public snapshot 和
静态 diagnosis bundle 生成 manifest；检测到 code-context source snapshot=52a… 与 bundle
source snapshot=d75… 不一致，结果为 status=blocked、freshness=conflict，
unsupported 包含 source-consistency。随后用同一 manifest 调用 pi-context，也返回
blocked，并保留 capability_manifest_identity/source_snapshot conflict diagnostics。
这证明能力发现不会绕过 source/data identity gate；下一步必须从同一当前 source 快照
重建 code-context 后再让 Pi 消费。

## 13. sibling viewer 集成 smoke

现有 cr60-debug-harness 的 build_html_reports.py 可直接消费 merged diagnosis bundle 和
runtime_evidence；radarAnalyze 不重复实现 HTML。用 run5 的真实 FCTA event slice 生成：
outputs/remote_public_capture_20260831/viewer_batch_run5/index.html
outputs/remote_public_capture_20260831/viewer_batch_run5/data/CRGVI-1829/report.html
以及 viewer-model.json。

模型中 FCTA event 的 runtime_status=matched、observation_count=70、fields=183，其中
159 个 token 来自 wfObjectMsg.ObjectsBuffer[0].*。页面链路已通；后续只需在 sibling
viewer 中增加 publication_correlated/unbound 的明确标签和公共快照帧选择，不在本仓复制 UI。
