# CR60 统一平台 Handoff：source-driven runtime debug plan 与 GDB marker 验证

日期：2026-08-28  
状态：`partially-verified`  
主线：Document-driven development / Pi-first / artifact-in-artifact-out

## 1. 本轮目标

在上一轮 runtime evidence overlay 的基础上，补齐：

```text
当前 diagnosis bundle + 当前 arbe preflight
    → runtime-debug-plan.v1
    → plan-bound GDB runner
    → gdb-session.v1
    → runtime-case-evidence.v1
    → HTML / Pi deterministic input
```

计划工具只负责生成和校验，不启动 ROS、回放或 GDB；执行仍由批准后的 provider/runner
完成。

同一 bundle 允许多个 runtime producer 叠加：merge 会保留历史 `runs/layers/observations`
并追加新 session；不会因为新一次 GDB 采集而删除上一轮 public with-frame、warm-up 或
其他 GDB 证据。

## 2. 研究发现

### 2.1 GDB `$N` 不能直接和表达式绑定

多断点、自继续 command list 的 GDB 输出中，`$1/$2/...` 没有表达式名称。旧的全局
顺序匹配会把一个 stop 的值错配到另一个函数的 watch。真实 `CRGVI-1829` 计划回放中
曾出现：

```text
g_egoCarAddInfo.carSpd = 2.171
```

实际 `2.171` 是 `g_egoCarFixPara.vehicle_width`，说明顺序错配会产生看似合理但错误的
诊断事实。

### 2.2 解决策略

`gdb-service` 在每条 `p expression` 前生成字面量 marker；plan-bound runner 生成同一
marker 后，通过 GDB embedded Python 对每个 expression 单独调用 `gdb.execute("p ...")`
并捕获异常：

```text
CR60_GDB_EXPR token="g_egoCarAddInfo.carSpd" phase="unknown"
$13 = 4.42844534
```

解析器按 marker 绑定值；plan runner 中某个表达式 `No symbol`/作用域不可见时，只把该
字段标为 `not_found`，并继续执行后续 breakpoint/handler。没有 marker 且检测到多次
stop 时，所有表达式都标记为 `not_observed`/`unmarked_expression_mapping_ambiguous`，
不再按位置猜值。`CR60_GDB_ERROR` 不会成为独立 observation，也不会产生
`observed=null`。

### 2.3 作用域错误必须局部降级

真实计划回放命中 `PostProcessMainTI`、`ResetFctaRoi`、`FrontCrossTrafficAlertAndBrake`，
但 `fFctaTTMXThresh` 在当前 stop 作用域中不存在，GDB 报：

```text
No symbol "fFctaTTMXThresh" in current context.
```

session 仍保留已经采集的变量、栈和 stop，并把该表达式标记为 `not_found`；整个 session
为 `partial`，不能冒充完整采集。每次回放的 `RESULT_PREFIX` 会进入
`gdb-session.target.run_id`，相同 plan 的重复执行可以独立比较。

## 3. 输入

### 3.1 runtime debug plan

```text
diagnosis_bundle.v1
可选 arbe-preflight.v1
可选显式 source_context/binary_context
权限/approval 状态
```

### 3.2 GDB runner

```text
runtime-debug-plan.v1
确认后的 harness TOML profile
bag 路径
target radar/frame
```

runner 支持 `--debug-plan` 和 `--session-output`。`--debug-plan` 使用 plan 中的真实
source location/condition/watch；`--session-output` 生成通用 `gdb-session.v1`，不绑定
FCTA/FCTB 消费逻辑。

## 4. 输出

| 产物 | 用途 |
|---|---|
| `runtime-debug-plan.v1` | readiness gates、radar 安装参数、target/index、断点、GDB commands、capture fields、VS Code handoff |
| `runtime-debug-run` | 按 plan 执行隔离 ROS/GDB，产出 `gdb-session.v1`；需要 approval |
| `gdb-session.v1` | GDB stdout/stderr、实际 commands、target、原始 stop/backtrace/locals/expressions |
| `runtime-case-evidence.v1` | 带 source/data/binary binding 的运行时证据层 |
| merged diagnosis bundle | 静态事实 + additive runtime overlay，不覆盖静态值 |
| viewer-model/HTML | 当前 frame 的 runtime fields、geometry、ROI、调用栈和 debug plan |
| `pi-orchestration-context.v1` | Pi 可消费的 deterministic runtime evidence/debug plan summary |

## 5. 真实 CRGVI-1829 验证

输入：

```text
server: 10.190.171.44
workspace: /home/hoz2wx/CR60LIGHT/cr60_light_arbe
bag: /home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
radar: 2
target frame: 47877
HILMODEL: 2
```

计划结果：

```text
status: partial
execution_status: approval_required
breakpoints: 8
gdb_commands: 45
capture_fields: 58
radar_pos: 2
orientation: 1
yaw: -52
```

readiness warnings：

```text
source_cleanliness
event_frame                  # nearest-LGU，不是 CAN Tx 上升沿
target_identity              # objID=44，但静态候选窗口为 6，i/k 未唯一证明
gdb_attach_permission        # ptrace_scope=1，正式 existing-PID attach 需额外权限/关系
approval

当前 v4 preflight 已计算 ELF SHA-256，`binary` gate 为 `pass`：

```text
93a8f2b2c11a6d8ba1abadbc7eb480e8867352f261a71c4bb5023f4c4ef80890
```
```

计划实际驱动隔离 GDB 后（2026-08-28 v4 session）：

```text
PLAY_RC=0
GDB_HIT_COUNT=7
frameID=47877
objInfo->trcNum=16
g_egoCarAddInfo.carSpd=4.42844534
g_egoCarAddInfo.actual_gear=4 '\\004'
g_egoCarAddInfo.yawRate=0.361754119
fFctaObjWarningBaseTTMX=2.26308894
fFctbObjWarningBaseTTMX=1.24952006
```

其中 `fFctaTTMXThresh` 等当前函数作用域不可见的表达式明确为 `not_found`，并未污染
前面已正确绑定的表达式。后续 handler 已实际执行，并捕获：

```text
i=0
objInfo->trcOutData[i].objID=44
objInfo->trcOutData[i].objFctaWarningFlag=5
objInfo->trcOutData[i].rightFctaFlag=true
```

本次 runner 通过 `--debug-plan` 使用 plan 的断点和 watch，通过 `--session-output` 自动
落盘 session；没有调用固定 FCTA/FCTB consumer 解析。旧的 `--flow` 仍仅作为兼容实验
适配器保留。

本次实际 plan-bound session 的 disturbance 为 `suspected`：`PLAY_RC=0`、
`GDB_HIT_COUNT=7`、`WARNING_ROWS=45`、`WARNING_NONZERO_COUNT=15`，且存在 9 个
表达式作用域错误。之前相同 bag/窗口的另一轮记录过不同的 warning 行数和 flag 状态，
说明 GDB 停顿、运行窗口和状态预热会影响输出；session 只能作为“部分 GDB 变量已捕获、
回放可能受扰动”的证据，不能替代无 GDB 的输出基线。

本次 v4 session 的唯一运行身份为：

```text
gdb-plan:4fd81d056d8da411:cr60_harness_gdb_smoke_1787911466
```

### 5.1 正式 arbe existing-PID attach 现场验证

在同一服务器上先执行只读 node/PID/executable 校验：

```text
ROS_MASTER_URI=http://localhost:11311
radar1/2/3/4 visualization nodes: present
radar2 PID: 3662064
expected exe == /proc/3662064/exe: true
ptrace_scope: 1
```

`arbe-formal-start` 随后执行了已有节点保护逻辑，返回：

```text
status=already_running
ownership=external
nodes=9
```

没有重复执行 `bash start`。对当前正式 radar2 PID 做 plan-bound attach 的最终结果为：

```text
gdb-session.status=blocked
evidence_status=not_available
ATTACH_EXECUTABLE_MATCH=1
ATTACH_BLOCKED_REASON=gdb_attach_failed
PLAY_RC=125
WARNING_ROWS=0
WARNING_NONZERO_COUNT=0
```

远端 GDB 原始日志明确为：

```text
Could not attach to process
ptrace: 对设备不适当的 ioctl 操作.
```

因此已证明“正式 node/PID 和 binary 定位链路可用”，也已证明当前用户态
`ptrace_scope=1` 不允许该 SSH GDB 进程附加这个既有 PID。工具没有修改 sysctl、没有提权、
没有回放 bag，也没有把断点设置结果冒充 runtime 命中。该 blocked attempt 已作为
`runtime_debug_attempt` 保留在最终 bundle，但不污染隔离 GDB 的有效 observation。
blocked 结果同时提供了需审批的 `runtime-debug-run` fallback；fallback 的 session 路径与
formal attach 路径隔离，避免覆盖本次权限失败的审计 artifact。

机器产物：

```text
D:/RamboStar/idea/radarAnalyze/outputs/runtime_debug_plan_CRGVI1829_FCTA_R_current_v2.json
D:/RamboStar/idea/radarAnalyze/outputs/runtime_debug_plan_CRGVI1829_FCTA_R_current_v3.json
D:/RamboStar/idea/radarAnalyze/outputs/runtime_debug_plan_CRGVI1829_FCTA_R_current_v4.json
D:/RamboStar/idea/radarAnalyze/outputs/gdb_session_provider_CRGVI1829_FCTA_R_20260828_v4.json
D:/RamboStar/idea/radarAnalyze/outputs/runtime_fctb_gdb_provider_normalized_20260828_v5.json
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260828_provider_runtime_final_bundle.json
D:/RamboStar/idea/radarAnalyze/outputs/gdb_session_formal_attach_CRGVI1829_FCTA_R_20260828_v7.json
D:/RamboStar/idea/radarAnalyze/outputs/runtime_fctb_formal_attach_blocked_normalized_20260828.json
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260828_runtime_final_with_attach_attempt_bundle.json
D:/RamboStar/idea/radarAnalyze/outputs/arbe_start_session_formal_existing_20260828.json
D:/RamboStar/idea/radarAnalyze/outputs/arbe_preflight_current_20260828_v3.json
D:/RamboStar/idea/radarAnalyze/outputs/arbe_preflight_current_20260828_v4.json
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260828_runtime_final_v2/data/CRGVI-1829/report.html
D:/RamboStar/idea/radarAnalyze/outputs/pi_context_CRGVI1829_runtime_final_v3.json
```

## 6. 测试

- runtime/GDB/parser/debug-plan/Pi context/formal lifecycle 专项：通过（本轮 65 项相关
  radarAnalyze 测试通过）；
- sibling harness GDB/lifecycle 全量：通过（50 个测试点，退出码 0）；
- Vite production build：通过；
- runtime evidence JSON Schema：通过；
- plan JSON Schema：通过；
- 真实隔离 GDB：`PLAY_RC=0`，59 个表达式 marker 中可观测值按 token 绑定，作用域缺失
  降级为 `not_found`/session `partial`，后续 `i`/handler 仍命中；
- plan-bound runner：模块/直接脚本入口均有明确错误处理，session artifact 可被 normalize
  继续消费；
- Pi bridge plan-only：`runtime-debug-run` 已通过生成的 `registerTool` 调用；
- Pi context artifact-only：仅提供 merged diagnosis bundle + runtime debug plan 时已能
  派生显式 case/data/source/strategy/radar，输出 `pi-context:ready`，不再要求调用方
  人工重建 intake；
- radarAnalyze 全量回归：`610 passed, 1 skipped, 2 xfailed, 10 warnings`；
- Pi catalog generator：`36 Pi 能力（30 模块 + 6 工具）`，包含 formal start/stop/attach；
- 直接执行和模块执行入口均可显示帮助，错误路径不触碰服务器。

## 7. 当前边界

本轮不宣称：

- 正式 `bash start` GUI player 与隔离 direct rosbag play 完全等价；
- 当前服务器 `ptrace_scope=1` 下的正式 existing-PID attach 已能准确报告阻断，但尚未形成
  可消费的正式 runtime 变量证据；
- 已观测最终 CAN Tx `Com_SendSignal` 上升沿；
- 所有功能/所有代码版本的 source adapter 已自动生成；
- static bundle 当前具备 binary fingerprint；
- point-cloud 150–200 帧 runtime 已完成。

下一步应在现有 artifact 契约上继续实现正式 `RuntimeProvider`/session supervisor，优先
复用当前 arbe 公共输出和 GDB provider，不把本轮 experiment adapter 的 FCTA/FCTB 断点
集合上升为全平台固定规则。
