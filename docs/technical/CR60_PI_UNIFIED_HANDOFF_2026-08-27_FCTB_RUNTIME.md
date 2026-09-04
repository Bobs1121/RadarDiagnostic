# CR60 统一平台 Handoff：CRGVI-1829 runtime 验收

日期：2026-08-27  
状态：`partially-verified`  
主线：Document-driven development / Pi-first / runtime evidence overlay

## 1. 本次目标

使用已经准备好的 `arbe`/`algo_source` 环境和真实 bag，验证统一工具能否：

- 先做 Sprint1 确定性预检查；
- 识别同一数据中的多功能、多雷达事件；
- 在隔离 ROS 环境中启动当前算法 ELF；
- 通过 headless GDB 按 `frame_counter` 捕获真实调用链、目标循环 `i`、目标属性、ROI 和
  FCTB 状态；
- 检验 SGU/LGU 短预热和点云长预热不能混用；
- 把发现沉淀为跨功能的工具契约，而不是 case 特例。

## 2. 输入与 source context

```text
server: 10.190.171.44
workspace: /home/hoz2wx/CR60LIGHT/cr60_light_arbe
bag: /home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
COEM: BYD_UKE
HILMODEL: 2
BUILDModel: 2
outer: develop_LGU_Simulation / dirty
algo_source: a81b08a38f316a3d25bfcbcad6dcfc822d24b990 / detached / dirty
source_snapshot_hash: d75fd296200dd1ab1e3713509f6f4506ff742bfc232b2cb327e10289eee37c8e
source_context_id: 0762176290744b4bf189d50238b0962bc093ca6c58f70fbaf5f1ce5b38f22660
```

本次没有 checkout、更新 CUDA、`catkin_make`、`bash start` 或连接正式 GUI 的既有 PID；
只读 preflight、隔离 ROS master、隔离 launch-under-GDB 均保留正式 workspace 不变。

## 3. Sprint1 结果

统一 `radarAnalyze` adapter 调用 `cr60-debug-harness` 完成：

```text
status: ready
case_count: 1
event_count: 28
failed/unsupported/blocked: 0/0/0
```

事件包含：`BSD_L=7`、`LCA_L=7`、`BSD_R=6`、`LCA_R=6`、`FCTB_L/radar1=1`、
`FCTA_R/radar2=1`。raw warning 无显式 frame，因此 `47840/47877` 仍是 nearest-LGU
时间对齐帧，不是已证明的 CAN Tx 上升沿。

报告：

```text
D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260827/data/CRGVI-1829/report.html
```

## 4. runtime 真实证据

### 4.1 radar1 raw FCTB_L

`frame_counter=47840` 的 `FrontCrossTrafficAlertAndBrake` 命中，且在
`HandleFctbLeftWarningFlag` 中逐目标得到：

```text
i=0 -> objID=39 -> objFctbWarningFlag=0
i=1 -> objID=30 -> objFctbWarningFlag=0
i=2 -> objID=16 -> objFctbWarningFlag=0
```

该隔离回放窗口没有 `warning_status_with_frame` 非零输出；因此当前证据不能把
radar1 raw `FCTB_L` 绑定到任一上述目标，也不能判定录制事件的最终原因。

### 4.2 radar2 replay FCTB/FCTA

`frameID=47875` 的运行时命中：

```text
function: HandleFctbRightWarningFlag
i: 0
objID: 44
objFctbWarningFlag: sObj snapshot 4 -> objInfo->trcOutData[i] 5
fTTC: 1.02
fDDCI: 8.38
target yawAng: 54.4000015 deg
fInterX: 8.44471264
fInterY: 0
warning_status_with_frame first non-zero: frame 47875
```

同一时刻的 `rightFctaRoi` 是 `num=10`、`x=3.86919975..8.64912415`、
`y=-1.0855..0`；目标当前四角在 `y=-2.6133..-7.5467`。这不是简单的即时矩形重叠，
而是代码根据目标运动方向计算预测交点；viewer 必须把即时包含与预测交点分别呈现。

### 4.3 warm-up 敏感性

长窗口和目标前约 5 帧的短窗口都重现 `objID=44`、flag 4→5 和 15 个 with-frame
非零样本，但派生 `radius` 分别约为 `884.086304` 和 `1149.37061`。结论是：

- SGU/LGU 默认 3–5 帧可以用于目标注入；
- 3–5 帧不是所有派生状态的等价证明；
- 工具要记录短/标准窗口的状态漂移并标记 `warmup_sensitive`；
- 不能因为短窗口输出相同，就隐藏参数或状态差异。

## 5. 已完成的代码/文档

- `cr60-debug-harness/tools/run_gdb_isolated_smoke.py` 支持 `--radar-id`，从 profile 读取
  当前 radar 安装参数，并通过逐断点 command list 扫描同帧所有目标；
- GDB 记录同时输出 `sObj` 快照与 `objInfo->trcOutData[i]` 更新值；
- GDB 入口输出当前 `leftFctaRoi/rightFctaRoi`；
- `radarAnalyze` 生成 `runtime-case-evidence.v1` 机器证据；
- `runtime-evidence-normalize` 已能从 canonical runtime artifact、GDB session 或 transcript
  生成/兼容 `runtime-case-evidence.v1`，并把旧 replay detail 提升为同帧 GDB fields、
  `objPoly`、ROI、动态自车参数和 before/after 状态；
- `runtime-evidence-validate` / `runtime-evidence-merge` 已实现 source/data/binary/event
  identity gate；merged bundle 只增加 `runtime_evidence`、`runtime_merge` 和事件 overlay，
  不覆盖静态事实；
- 静态 `viewer-model.v1` 已支持每个事件窗口逐 `frameID` 切换，真实本次数据共 2634 帧；
  frame-local ego/目标值采用轻量数组，代码 token 和 source metadata 在事件级复用；
- runtime viewer 已支持在当前 frame 查看 GDB fields、before/after、调用栈、真实 runtime
  target polygon/ROI 和动态参数；runtime 信息独立为 `Runtime` 面板，没有同帧证据时不沿用前一帧；
- `pi-context` 已接收相同 runtime artifact，可输出绑定状态和 deterministic runtime summary；
- `runtime-debug-plan` 已将当前事件的真实 breakpoint pack、45 条 GDB command、58 个
  capture fields、radar2 PID、HILMODEL=2 和 readiness gates 形成独立 artifact；HTML Code
  面板可直接展示并复制该计划，不在前端重新生成条件；
- Pi extension 已由 catalog 重新生成，包含三个 runtime evidence 原子工具；
- PRD、系统设计、Sprint 规划、实现状态和研究报告补充了证据分层、几何不变量、warm-up
  sensitivity 和用户级提问边界；
- sibling harness 全量测试通过，`compileall` 通过。

机器证据：

```text
D:/RamboStar/idea/radarAnalyze/outputs/runtime_fctb_case_evidence_20260827.json
D:/RamboStar/idea/radarAnalyze/outputs/runtime_fctb_case_evidence_normalized_20260827.json
D:/RamboStar/idea/radarAnalyze/outputs/runtime_debug_plan_CRGVI1829_FCTA_R.json
D:/RamboStar/idea/radarAnalyze/outputs/gdb_fctb_radar1_20260827_v2.log
D:/RamboStar/idea/radarAnalyze/outputs/gdb_fctb_radar2_frame47875_final_20260827.log
D:/RamboStar/idea/radarAnalyze/outputs/gdb_fctb_radar2_frame47875_warmup5_20260827.log
```

## 6. 尚未完成 / 不应过度宣称

- 当前已生成独立 runtime overlay HTML：
  `D:/RamboStar/idea/radarAnalyze/outputs/radar_project_fctb_CRGVI1829_20260827_runtime/data/CRGVI-1829/report.html`；
  原始静态报告仍保留，runtime merge 不覆盖它；
- 当前 smoke 仍用当前源版本的 FCTA/FCTB 函数作为 runtime 验证目标，产品化必须由
  source/runtime schema 动态生成 function/field/expression；
- 尚未验证正式 `bash start` GUI player parity，也未验证最终 CAN Tx `Com_SendSignal`；
- radar1 raw FCTB_L 仍缺同源 runtime target，不能给出正报/误报或根因结论；
- existing PID attach 受当前 `ptrace_scope`/权限影响，隔离 launch-under-GDB 是已验证 fallback；
- 不应把当前源版本的 ROI 语义写成所有车型/功能的固定规则。
- 当前 debug plan 在该真实事件上为 `partial/approval_required`：target `i/k` 未由静态窗口唯一证明，
  nearest-LGU 不是 CAN Tx 上升沿，source dirty 且 binary fingerprint 尚未纳入 bundle；这些是
  readiness gate，不是被工具隐藏的风险。

## 7. 下一步建议

1. 把当前 transcript/experiment adapter 接到通用 `RuntimeProvider`，输入为
   `PiRunContext + RuntimeRequest`，由 source/runtime schema 生成 capture fields；
2. 增加 binary fingerprint 生产和正式 `bash start` GUI player parity 校验；
3. 将最终 CAN Tx `Com_SendSignal` 上升沿接入同一 evidence layer，严格区分
   `warning_status_with_frame` 与 CAN Tx；
4. 在隔离 session 验证多个功能、多次报警和四个 radar，再评估正式 GUI/attach；
5. 所有需要用户确认的问题只问业务目标、报告口径、是否允许隔离运行/正式运行等，不问
   用户不熟悉的 `frameID`、ROI、PID 或 GDB 细节。

## 8. 用户交互原则

当缺少技术事实时，Pi 先自动探测；只有以下问题才请求用户确认：

- 报告是以“录制报警”还是“当前代码回放输出”为主口径；
- 是否允许启动隔离 runtime 或触碰正式工作区；
- 结果主要用于代码定位、工程修复还是客户解释；
- 用户是否接受当前证据不足时先交付阶段性报告。
