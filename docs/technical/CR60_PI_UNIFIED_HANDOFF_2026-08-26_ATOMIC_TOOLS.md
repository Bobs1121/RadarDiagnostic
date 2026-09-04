# CR60 统一平台 Handoff：公共证据与原子工具首版

版本：`handoff.v1`  
日期：`2026-08-26`  
状态：`S1 基础能力完成，隔离 launch-under-GDB 已验证，正式 workspace attach/build 待审批`

## 1. 本次目标

把“逐帧公共信号采集、代码分析、GDB 调试”拆成独立原子能力，让 Pi 通过 artifact
自由编排：

```text
ros-topic-inventory
    → public-topic-plan / public-evidence-audit
    → code-analyze / code-gdb-plan
    → gdb-service
```

每一步都可以独立运行、独立失败和独立留痕；GDB 不绑定报警功能，也没有默认断点。

## 2. 已交付代码

| 能力 | 代码 | 契约 |
|---|---|---|
| 输入绑定 | `engines/arbe/intake.py`、`ai/modules/cr60_intake.py` | `cr60-analysis-intake.v1` |
| arbe 预检 | `engines/arbe/preflight.py`、`ai/modules/arbe_preflight.py` | `arbe-preflight.v1` |
| Sprint1 adapter | `ai/providers/cr60_harness.py`、`ai/modules/cr60_precheck.py` | `cr60-harness-provider.v1` |
| ROS 公共盘点 | `engines/arbe/ros_inventory.py`、`ai/modules/ros_topic_inventory.py` | `ros-topic-inventory.v1` |
| 公共证据计划/审计 | `engines/arbe/public_evidence.py`、`ai/modules/public_topic_plan.py`、`ai/modules/public_evidence_audit.py` | `public-topic-plan.v1` / `public-evidence-audit.v1` |
| 代码→GDB | `engines/code_gdb_plan.py`、`ai/modules/code_gdb_plan.py` | `code-gdb-plan.v1` |
| 通用 GDB | `engines/gdb_service.py`、`ai/modules/gdb_service.py` | `gdb-session.v1` |
| Pi 桥 | `ai/capability/module_bridge.py` | 受控 `BaseModule`→`BaseTool` |

模块已进入 `MODULE_REGISTRY` 和 `CapabilityRegistry`，`input_schema/output_schema` 会
进入能力 catalog。Pi/ReAct 的 module bridge 默认自动发现所有已注册的叶子模块，因此
`code-analyze`、`code-learn`、`signal-extract`、`signal-bridge`、`sim-verify` 等已有能力
也可和 intake、preflight、Sprint1、ROS 公共盘点、公共证据、code→GDB、GDB service
自由组合；仅排除 `pi`、`agent-repl`、`agent-loop` 防止递归。`cr60-precheck/gdb-service`
的执行开关以及 `project-init` 的写操作默认被审批桥拦截。

## 3. 真实环境/数据验证

目标环境：`hoz2wx@10.190.171.44`
arbe：`/home/hoz2wx/CR60LIGHT/cr60_light_arbe`  
数据样例：`/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/`

### 3.1 `arbe-preflight.v1`

- outer HEAD：`4c171298b2c3583509ea9e3da222b90ba0a9e513`；
- `src/algo_source` HEAD：`a81b08a38f316a3d25bfcbcad6dcfc822d24b990`；
- COEM：`BYD_UKE`；CUDA：`CUDA_BYD_UKE_Bundle_V2.0.xlsx`；sheet：`03_QZH`；
- `BUILDMODEL=2`、`HILMODEL=2`；
- visualization 进程已发现 `radar1..radar4`，PID 当次为 `3662013/3662064/3662071/3662012`；
- `/usr/bin/gdb` 可用，`ptrace_scope=1`；
- 解析到 110 个 CAN Tx 源码候选；
- 服务器当时已有运行进程，preflight 是只读观察，不代表本次工具启动了它们。

Artifact：[arbe_preflight_20260826.json](../../outputs/arbe_preflight_20260826.json)

### 3.2 独立 harness 单数据验收

通过 `cr60-precheck` 的 `manifest` 模式处理了
`CRGVI-1829_ALT_2026-07-18`：返回 `ready`、1 case、34 个报警事件，生成
`batch_summary.json`、`batch-index.json`、`index.html`、bundle、viewer/report、
`vscode_handoff.json` 和 34 个断点文件。此过程没有 GDB。

Artifact 根目录：
`D:/RamboStar/idea/cr60-debug-harness/outputs/pi_adapter_acceptance_CRGVI1829_ALT_20260826/`

之后发现并修复了 decoder 对 `objFctaWarningFlag/objFctbWarningFlag` 的错误命名，
使用新目录 `pi_adapter_acceptance_CRGVI1829_ALT_20260826_v2` 重跑：34 个事件保持不变，
但 `frame_precheck.debug_frame_range` 正确降级为
`internal_warning_counter_not_present_in_public_object`，不再生成伪 counter 范围。
之后又按当前 `perception_public_api.h` 恢复 `historyMovDist` 并修正 velocity/TTC/DDCI
字段索引，decoder 升级为 v3；后续新产物以 v3 为准，旧目录仅作为修复前/中间证据保留。

v3 真实验收目录：
`D:/RamboStar/idea/cr60-debug-harness/outputs/pi_adapter_acceptance_CRGVI1829_ALT_20260826_v3/`

随后将 `decoder_contract` 接入 `BatchAnalyzer`，由当前 source index 校验后传入远端
decoder；v4 真实验收确认 `decoder_status=source_resolved`、25 个 compressed object
字段、29 个 ego 字段、`LGU_OUT_NUM_SGU=16` 和 source snapshot hash 一致。以 v4 目录
作为当前有效验收结果：
`D:/RamboStar/idea/cr60-debug-harness/outputs/pi_adapter_acceptance_CRGVI1829_ALT_20260826_v4/`

### 3.3 公共证据

真实 bundle 审计得到：

- 9173 条 `alarm_events[].frame_evidence[]` 逐帧行；
- 9173 个显式 `wfAutosarData.frameID`；
- 23 个回灌 ego 字段（速度、横摆、加速度、挡位、方向盘、转向灯、四门、validity、轮速有效性、方向符号、雨刷和 mileage）；
- 目标候选保留 `raw_sgu_index`、`algorithm_object_index`、`objectlist_message_index`、
  `trc_index_i` 等层级；
- 当前 bag 的 `warning_status_with_frame` 不存在，CAN Tx 未观测。

当前对象 decoder 为 `arbe_PERInfoOutStruct_debug_tail_v3`，`objOutStrunct` 按
`perception_public_api.h` 的 36 字节顺序解析；公共对象没有算法内部 warning counter。

### 3.4 当前 ROS master 盘点

真实只读 inventory 显示：

- `/wf/objectlist_2`：`arbe_msgs/wfObjectMsg`，radar2 visualization publisher 存在；
- `/wf/corner_radar/lgu_data_1..4`：`arbe_msgs/wfAutosarData`，当时均无 publisher（播放器未在盘点瞬间发布）；
- `/corner_radar/radar_info`：`std_msgs/Float32MultiArray`，4 个 visualization publisher；
- `/corner_radar/warning_status_with_frame`：`std_msgs/UInt32MultiArray`，4 个 visualization publisher；
- `/wf/xcp_signals/front_left/parsed`：`common_xcp_info_publisher_rvizbag/XcpEgoInfo`，
  当时 publisher 为 0、subscriber 为 2，故 `data_observable=false`。

Artifact：[ros_topic_inventory_full_20260826.json](../../outputs/ros_topic_inventory_full_20260826.json)

## 4. 关键能力边界

### 不需要 GDB

优先使用 bag 的 `wfAutosarData.frameID/outputData` 和公共 ROS 输出；可以获得回灌
`egoCarInfoTrans`、raw `objTrans[i]`、ADAS enable、calibration/BLD、算法显示对象子集、
ROI marker 和带 frame 的算法 warning。

当前 `public-topic-plan`/`ros-topic-inventory`/`public-evidence-audit` 已覆盖公共通道的
规划、运行时注册状态和已有 bundle 审计；尚未实现持续的 live `rosbag record` 或 ROS
subscriber collector。因此 inventory 中的 `data_observable=true` 只表示当前存在 publisher，
不是已经把一段回放输出保存成逐帧证据。

### 仍需要 GDB 或显式 runtime probe

`g_egoCarAddInfo` 派生值、`sObj/objPoly`、`fInterX/Y`、`fTTMX`、局部计数器、作用域内
真实 `i`，以及 `RteComMapping_TxRunnable → RteLite_Write_* → Com_SendSignal` 的真实命中。

live XCP 可以读更多内存字段，但当前 `canfd_sgu_pub.py` 是独立 50 Hz Kvaser/A2L
路径，无算法 `frameID`；没有明确 correlation 时只能作为 `live_xcp` 证据，不能冒充
bag 帧真值。

## 5. 下一步进入 S3 前必须确认

1. 是否允许在当前已运行的 `arbe_visualization_engine` 上做一次 headless GDB attach；
2. 目标选择使用哪一个当前 PID/radar（PID 必须重新 preflight，不能复用本 handoff 的旧 PID）；
3. 是否只做一次 `gdb-service` plan/attach/一帧命中试验，还是需要启动独立 debug session；
4. 运行中若命中 `<optimized out>`、source/binary hash 不一致或进程不是目标 radar，立即
   detach 并只保留公共证据，不输出 runtime 结论。

## 6. 验证命令

```powershell
python -m pytest -q
# 当前结果：560 passed, 1 skipped, 2 xfailed, 10 warnings

python cli.py ros-topic-inventory --host 10.190.171.44 --user hoz2wx `
  --ros-setup /opt/ros/noetic/setup.bash `
  --workspace-setup /home/hoz2wx/CR60LIGHT/cr60_light_arbe/devel/setup.bash `
  --topic /wf/objectlist_2 --topic /corner_radar/warning_status_with_frame --execute
```

正式 workspace 的 existing-PID GDB attach 尚未执行，因为它会暂停/扰动正式进程，必须在
用户确认后运行；隔离 launch-under-GDB smoke 已执行并通过，完整证据见本 handoff 的
2026-08-27 补充记录。

当前默认 module bridge 已验证自动暴露 21 个叶子能力（包括 `code-analyze`、
`code-learn`、`signal-extract`、`signal-bridge`、`sim-verify` 等）；递归编排根
`pi`、`agent-repl`、`agent-loop` 不作为子工具暴露。工具可通过
`{"$ref":"steps[0].result.data.<field>"}` 传递上一步的结构化 artifact，不能用
自然语言拼接命令。

`gdb-service` 执行后会额外写入 `observations`：包括 stop 行、backtrace、`info args`、
`info locals`、`print` 表达式和 diagnostics；`<optimized out>`、`No symbol`、
`Cannot access memory` 等状态不被替换成猜测值。Windows 本地旧版 MinGW GDB 使用
临时 command file，Linux 远程 arbe 继续使用 `-ex` 参数。

## 7. 2026-08-27 实际运行补充

- 新鲜 preflight：[arbe_preflight_20260827.json](../../outputs/arbe_preflight_20260827.json)；
  binary identity：[arbe_runtime_identity_20260827.json](../../outputs/arbe_runtime_identity_20260827.json)；
- 单数据 Sprint1：[actual_acceptance_CRGVI1829_strategy_20260827](D:/RamboStar/idea/cr60-debug-harness/outputs/actual_acceptance_CRGVI1829_strategy_20260827/)，
  `ready`、34 events、source-resolved decoder、所有事件 `sgu_injection 5/5`；
- 公共 topic 采样：[ros_topic_inventory_20260827_sampled.json](../../outputs/ros_topic_inventory_20260827_sampled.json)，
  有 publisher 的 topic 在采样窗口仍无消息；隔离 direct replay 的
  `WARNING_NONZERO_COUNT=15` 记录在
  [public_isolated_smoke_20260827_v3.log](../../outputs/public_isolated_smoke_20260827_v3.log)；
- 隔离 GDB：[gdb_isolated_smoke_20260827_v2.log](../../outputs/gdb_isolated_smoke_20260827_v2.log)，
  `PLAY_RC=0`、`GDB_HIT_COUNT=1`、`frame=47877/radar=2`、`objID=44`、`i=0`、目标
  `objPoly`/FCTA/FCTB 状态已采集；
- 合并摘要：[runtime_smoke_evidence_20260827.json](../../outputs/runtime_smoke_evidence_20260827.json)；
- teardown：隔离 master `11321/11322` 无法通信，正式 `11311` 的 4 个 visualization
  节点保持，两个测试前缀无残留。

本次 radarAnalyze 全量回归为 `560 passed, 1 skipped, 2 xfailed, 10 warnings`；Pi
context/bridge 专项为 `13 passed`，sibling harness 当前全量收集并通过 `38` 项。

本次 runtime smoke 使用仓库内的隔离实验 adapter，不能替代正式 GUI player parity；正式
workspace 的 checkout/CUDA/build/start/existing-PID attach 仍按审批门保留。

文件夹批量实际验收：对远程 `CRGVI-1829` 目录自动发现 5 条 bag，生成 5 个独立 data
report，合计 149 个 event，结果 `5 ready / 0 failed / 0 unsupported / 0 blocked`；
输出目录为
`D:/RamboStar/idea/cr60-debug-harness/outputs/actual_folder_CRGVI1829_20260827/`。

## 8. 2026-08-27 DDD / Pi-first 补充

需求基线已收敛到
[CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md](CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md)，
包含 `US-001..US-014`、Given/When/Then、DoR/DoD 和实现/测试/证据追踪。当前 handoff
不能把隔离 runtime smoke 或 Pi tool smoke 等同于正式 arbe workspace 生产验收。

Pi 调度链已纠偏为：

```text
Pi registerTool → pi_tool_bridge → BaseTool.safe_execute / BaseModule adapter
                 → deterministic engine/provider → external artifact
```

本轮新增 `pi-context` 生成 `pi-orchestration-context.v1`；扩展 generator 现在真实
透传 `params`，PiBridge 显式加载当前项目 extension，默认关闭内置工具。真实 Pi RPC
和 `pi-context` tool invocation 已通过；本机当前 provider 是
`bosch-qwen3_6 / Qwen3.5-27B-FP16`，旧 `bosch-qwen35` 只保留为历史记录，其他用户需
通过 `CR60_PI_PROVIDER`/`CR60_PI_MODEL` 或调用参数绑定。

另外补齐了历史模块的 Pi 参数契约：没有显式 `input_schema` 的模块由真实
`run()` 签名和 `register_cli()` 保守推导 schema，bridge 复用 `from_cli_args`，不会把
构造期的 MF4/BLF/source 路径丢掉。

新增/更新验证：`tests/test_pi_context.py`、`tests/test_pi_tool_bridge.py`、
`scripts/pi_rpc_smoke.py`、`ai/pi_bridge.py`。Pi 的 side effect 仍必须走批准后的
supervisor，生成 extension 不传 `--allow-execution`。

直接 `cli.py pi` 入口也已实测：`PiModule` 自动建立当前 case 的 partial context，
实际调用 `pi-context`，最新一次返回 `FINAL_SCHEMA_PI_TOOL_CALLED`；PiBridge 的无输出 timeout 和
Windows Node 进程树清理均有专项测试/现场检查。
