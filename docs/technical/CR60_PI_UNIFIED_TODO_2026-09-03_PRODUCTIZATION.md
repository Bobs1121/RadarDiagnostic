# CR60 Pi Unified Platform 产品化 TODO

版本："todo.2026-09-03.productization.v1"
对应 handoff："CR60_PI_UNIFIED_HANDOFF_2026-09-03_PRODUCTIZATION.md"
原则：文档先行 → 单条验证 → 小步修复 → 记录证据 → 再扩大范围

> 本 TODO 是后续执行清单，不要求一次性全部并行完成。P0 按顺序推进；每一项必须有输入、产物、验收和证据。没有证据只能标记 partial/open。

## 0. 目标定义

最终产品要支持三类出口：

| 出口 | 目标 |
|---|---|
| A：批量预检查 | folder → 每条数据 diagnosis bundle → 每条数据 HTML → batch index |
| B：详细诊断报告 | selected event → 静态/公共/GDB/source chain → 自然语言+表格+图+诊断线索 |
| C：Pi 对话式调查 | 用户问题 → Pi 选择原子 tool → 阶段性观察/缺口 → 继续追问/运行 GDB → 最终报告 |

最终诊断不是单一黑盒答案，必须保留：

- 选择了哪个功能/侧别/radar/frame/object；
- 用了哪些 source/data/binary/runtime artifact；
- 哪些条件通过、未通过、无法求值；
- 哪些数值来自 recorded、derived、runtime、GDB；
- 哪些结论是事实、推导、AI inference；
- 下一步验证如何反证当前假设。

## 1. 状态和优先级

| 状态 | 含义 |
|---|---|
| todo | 尚未开始 |
| in_progress | 正在执行，有执行者和产物 |
| blocked | 外部输入、权限或环境阻塞，原因已记录 |
| partial | 有部分证据，不能作为完成 |
| done | 验收标准和证据均完成 |
| deferred | 有意后置，不阻塞当前目标 |

| 优先级 | 说明 |
|---|---|
| P0 | 影响产品独立使用、结论可信度、安全交接 |
| P1 | 影响效率、可复现性、多项目适配和 runtime 深度 |
| P2 | 高级诊断、AI 协同、工程闭环 |
| P3 | 体验和非核心扩展 |

## 2. P0 产品收口

### P0-01 工作区归属和提交边界

状态：todo  
依赖：无  
执行者：接手开发者

输入：

- git status、git diff、git diff --cached；
- 本 handoff；
- 用户已有修改。

执行：

1. 分类 tracked、untracked、staged 文件；
2. 标记产品代码、文档、测试、fixture、运行产物、scratch；
3. 不重置、不强制覆盖用户修改；
4. 形成 PRODUCT_COMMIT_SCOPE_2026-09-03.md；
5. 逐项 stage 产品文件。

验收：

- [ ] commit scope 文档存在；
- [ ] 没有 .env、API key、bag、MF4、SQLite WAL 被 stage；
- [ ] git diff --cached --check 无错误；
- [ ] stage 清单可由另一人复核。

### P0-02 删除临时/冗余文件但保留证据

状态：done（本轮冗余文档与输出清理已完成；保留项均有证据或回溯价值）  
依赖：P0-01  
执行者：接手开发者

本轮已删除：

- 26 个无引用或已被当前报告替代的顶层重复输出目录；
- 同一案例下 11 个重复 HTML/JSON/Markdown 报告子目录；
- 87 个重复版本/临时顶层输出文件；
- _capabilities_check.json 和 .playwright-cli/；
- 旧 V2/V3 规划、重复 CodeGraph 阶段 handoff、旧 phase/taskboard 和旧审查文档。

按证据链保留：

- 最新最终报告及其 bundle、viewer、runtime evidence、GDB plan、代码上下文和 preflight；
- `analysis_runs` 及研究文档仍引用的历史 runtime evidence；
- 仍未删除的较大历史 evidence（如远端公共采集、FCTB runtime 证据），因为它们不是报告副本，
  后续若要归档应先迁移 provenance 再处理。

后续清理（不阻塞本轮完成）：

- `memory` 中的 `*.db-shm`、`*.db-wal`；
- `scripts/_*.py` 和早期一次性探索脚本；
- 需要逐项确认的历史输出引用。

执行要求：

1. 先生成删除清单；
2. 用 rg 检查是否仍被 README、CLI、测试引用；
3. 必要研究结论先写入 research/handoff；
4. 只逐项删除，不使用 git clean -fd；
5. 在 cleanup report 中记录删除/保留/原因。

验收：

- [x] 项目根目录不再出现临时 capability 检查文件；
- [ ] 产品目录中没有未被入口/文档引用的一次性扫描脚本（后续清理项，不属于本轮 output 清理）；
- [x] 最终报告链接仍可打开；
- [ ] git status 剩余未跟踪项都有明确归属。

### P0-03 能力目录和 Pi 入口一致性

状态：done（交接前已验证，提交前复核）  
依赖：无

命令：

python cli.py capabilities --json
python -m ai.capability.pi_tool_bridge --list
python scripts/gen_pi_extension.py --out .pi/extensions/radar-capabilities.ts

当前基线：

- catalog=65；
- Pi-visible=58；
- duplicate=0；
- registerTool=58；
- bridge=58。

验收：

- [x] diagnosis-report、event-code-path、code-context-refresh、runtime-debug-plan、gdb-service、sim-verify 存在；
- [x] 生成 TS 不包含固定 D:\... Python 路径；
- [ ] 提交前生成器输出与 stage 文件一致。

### P0-04 单条真实数据报告重建

状态：done（当前报告已生成，提交前复核）  
依赖：无

真实输入：

- bag=/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag；
- function=FCTA_R；
- radar=2；
- frame=47877；
- objID=44。

报告：

outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html

验收：

- [x] report status=ready；
- [x] GDB confirmation=confirmed；
- [x] algorithm output adasWarning->bRightFctaWarning=2；
- [x] source output chain status=source_scanned；
- [x] primary internal=AdasStM.Frontright_FCTA；
- [x] primary external=RRadar_FCTA_Warning_Right_S；
- [x] 结论采用自然语言编号步骤；
- [x] 数据使用表格；
- [x] 当前几何和未来预测分开；
- [x] HTML 有 FCT/对外映射段落；
- [ ] 内部信号 runtime 值仍待 P0-07。

### P0-05 报警输出口径统一

状态：done  
依赖：无

默认策略：

- output_policy.effective_endpoint=algorithm；
- output_authority=algorithm；
- algorithm_output_is_terminal=true。

要求：

- 默认以 arbe GUI 报警灯对应 algo_adasWarning 输出为报警终点；
- 外部 signal/RTE 作为下游映射证据，不改变默认算法报警结论；
- 只有用户明确要求时才切换 can_tx 口径；
- 主结论不反复强调输入中没有外部信号；
- object warning flag 不能替代最终算法输出。

验收：

- [x] 当前报告主结论没有把外部信号缺失写成报警失败；
- [x] output chain 仍展示真实对外映射；
- [ ] 所有历史报告模板和 Pi prompt 统一到该口径。

### P0-06 报警条件链自然语言化

状态：done（本轮已实现，需复核不同功能）  
依赖：无

用户可见顺序：

1. 状态机/系统门；
2. 自车速度、挡位、enable；
3. 目标 dynFlg、objID 和目标过滤；
4. 当前 source 的 ROI 可用性 gate；
5. 预测/时空条件和目标 warning flag；
6. 算法报警输出；
7. FCT/ASW 内部信号；
8. 对外 signal 映射。

注意：编号只是呈现层排序，不能把不同 if/else 分支拼成虚假的 AND 链。

验收：

- [x] 每个步骤显示 source function/location；
- [x] 显示关键同帧值；
- [x] satisfied/not_satisfied/not_evaluable/unsupported 分开；
- [x] 完整表达式在折叠详情中保留；
- [x] not_evaluable 不被当作 false；
- [ ] 至少用一个非 FCTA 功能真实数据复核描述是否合理。

### P0-07 补齐 FCT/ASW 内部映射 GDB 证据

状态：todo  
依赖：P0-01、当前 source/binary 对齐、用户允许 GDB  
执行者：runtime/GDB 执行者

目标：

AdasStM.Frontright_FCTA
ADAS_Warn_Process_FrontRight_FCTA(inputLevel)
RRadar_FCTA_Warning_Right_S
RteLite_Write_RRadar_FCTA_Warning_Right_S(data)

执行顺序：

1. 根据 output_chain source refs 生成映射探针计划；
2. 确认 arbe_visualization_engine binary 与 source hash/dirty 状态；
3. 先尝试 launch-under-GDB 隔离 session；
4. 若使用正式 bash start，重新发现 radar2 PID 和 /proc/<pid>/exe；
5. 在 ADAS_HMI.c:3623 或真正映射调用点抓取内部值；
6. 抓取 RteComMapping_Tx.c:147 附近的 expression 输入；
7. 写成 gdb-session.v1，再 normalize/validate/merge；
8. 重生成报告，确认 internal 状态从 source_candidate 升级为 runtime_observed。

不允许：

- 把旧 GDB session 当成新 binary 证据；
- 把 source assignment 当成执行事实；
- 只看到 Com_SendSignal 符号就说 signal 已发送；
- 跨 radar 借用另一个进程的内部变量。

验收：

- [ ] runner status succeeded；
- [ ] frame/radar/object/function identity 命中；
- [ ] AdasStM.Frontright_FCTA 有同帧 observation；
- [ ] 对外 signal 输入/返回路径有同帧 observation，或明确 blocked；
- [ ] 报告显示算法事实和下游执行事实的状态差异。

### P0-08 正式/隔离 GDB 失败路径可解释

状态：todo  
依赖：P0-07

已知问题：

- 历史动态 source-chain runner 曾出现远端 ROS node communication failure；
- formal existing-PID attach 在 ptrace_scope=1 下可能被权限阻断；
- runner 启动成功不能写成 GDB 已命中。

需要：

- 区分 runner_started、process_found、attach_succeeded、breakpoint_hit、identity_matched、field_observed；
- 每个失败阶段给出用户能理解的下一步；
- 失败 artifact 也能被 report/Pi 消费；
- 不自动修改 ptrace_scope，不自动杀非 tool-owned 进程。

验收：

- [ ] 对一个失败 runner 生成 partial report；
- [ ] report 不出现伪造 runtime 值；
- [ ] next action 指向正确原子 tool；
- [ ] 用户不需要理解 errno/ptrace technical detail 才能继续。

### P0-09 单条数据端到端 AnalysisRun

状态：todo  
依赖：P0-01～P0-08

目标链：

cr60-intake
  → arbe-preflight
  → code-context-read/refresh
  → cr60-precheck
  → event-code-path
  → public-topic-plan / public-evidence-audit
  → runtime-debug-plan
  → runtime-debug-run（approved）
  → runtime-evidence-normalize/validate/merge
  → diagnosis-report

验收：

- [ ] 每个 AnalysisStep 有输入 artifact ref、tool call、观察、gap、摘要、下一步；
- [ ] 任一步失败可恢复，不需要从头猜身份；
- [ ] 最终 HTML 与单独调用 report engine 一致；
- [ ] Pi summary 返回 artifact ref，不返回大段 transcript；
- [ ] 运行结束可由 handoff 复现。

## 3. P1 多数据、多功能和可复现性

### P1-01 多功能、多次报警事件验证

状态：todo  
依赖：P0-09

输入：一条真实包含以下至少两种情况的 bag：

- 两个不同功能同时/先后报警；
- 同一功能两次不连续报警；
- 四个 radar 均有事件。

验证：

- alarm_events 是否完整；
- event_id 是否唯一；
- 每个 event 的 function/side/radar/frame/target/index 是否独立；
- HTML 是否能切换事件；
- runtime evidence 是否串线；
- 同一 objID 在不同 radar 是否被错误合并。

DoD：

- [ ] 每个事件都有独立 selected_event/报告视图；
- [ ] batch index 展示事件数量和功能摘要；
- [ ] 加入跨 radar identity collision fixture；
- [ ] 记录至少一条真实多事件报告。

### P1-02 Folder batch 输入和输出

状态：todo  
依赖：P1-01

目标输出：

batch-output/
  batch_summary.json
  batch-index.json
  index.html
  data/<data-id>/report.html
  data/<data-id>/viewer-model.json
  cases/<data-id>/diagnosis_bundle.json

验收：

- [ ] 文件名完整显示；
- [ ] 每条报告不复用上一条 selected event；
- [ ] 单条失败不影响其它 ready 数据；
- [ ] unsupported/blocked/ready 在 index 清楚显示；
- [ ] data id 不冲突；
- [ ] 不把文件夹名当车型/功能推断。

### P1-03 输入身份和 source context 分离

状态：todo  
依赖：P0-01

每次运行必须明确绑定：

data_fingerprint
source_context_id
source_snapshot_hash
outer_head
algo_head
COEM
vehicle/project
binary_fingerprint
HILMODEL/BUILDMODEL

实现：

- 统一 cr60-analysis-intake.v1；
- pi-orchestration-context.v1 只消费已验证字段；
- report 统一 input_refs/artifact_refs/conflicts；
- source hash 变化让旧 condition/code/GDB artifact stale；
- 不因路径相似复用其它车型/项目知识。

验收：

- [ ] 构造 data/source mismatch fixture；
- [ ] report status=blocked/partial；
- [ ] Pi 不继续给出具体报警根因；
- [ ] mismatch 原因显示在 evidence gap。

### P1-04 当前 source 的 CodeGraph 完整覆盖

状态：todo  
依赖：P1-03

已发现缺口：部分 source context 只选取有限文件，可能缺少
coem/BYD_UKE/components/AswIf/ASW_ADAS/ADAS_HMI.c，但 preflight 远端扫描能读到它。

目标：

- code context 能从当前 source root 或远端 provider 动态覆盖 output chain 相关文件；
- 内部映射文件被 CodeGraph/CodeIndex 或按需 source query 获取；
- 不需要每个功能手工补 key file；
- 代码索引更新有 file hash、增量统计和 freshness。

DoD：

- [ ] output mapping 与内部赋值分属不同文件的 fixture；
- [ ] code learn 能找到内部赋值；
- [ ] 代码变化后旧 index 不复用；
- [ ] 不把 ADAS_HMI.c 固化成所有项目必选文件。

### P1-05 所有功能的真实输出链适配

状态：todo  
依赖：P1-04

目标：验证 BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB 不受 FCTA 假设限制。

执行：

- 从当前 source output expression 动态识别内部路径；
- 按功能/侧别筛选当前 scope；
- 无映射时显示 source_mapping_not_found_for_scope；
- 不把 legacy output list 当当前版本事实；
- legacy fallback 在 report 中标明 fallback。

DoD：

- [ ] 每个功能有 source fixture 或真实样例；
- [ ] signal selection 不串左右侧；
- [ ] FCTB 不错误复用 FCTA internal token；
- [ ] external signal 与 algorithm output 状态独立。

### P1-06 报警帧和上升沿语义统一

状态：todo  
依赖：P0-05、P1-01

必须同时保留：

recorded_raw frame
algorithm rising frame
selected analysis frame
runtime_with_frame frame
gdb stop frame
external signal rising frame（可选）

验收：

- [ ] 报告明确写当前分析帧还是算法上升沿；
- [ ] nearest LGU frame 不伪装 exact edge；
- [ ] 用户选首帧时按算法报警灯/with-frame 上升沿选择；
- [ ] GDB 接收上升沿 frame，而不是默认滞后一帧；
- [ ] 关联包含 topic、message index、timestamp delta 和 frame source。

### P1-07 public runtime 同帧 collector

状态：todo  
依赖：P1-06

目标在 arbe callback 中产生 stamped snapshot：

frameID
radar_id
objectlist_index
algorithm_index
ego fields
target fields
ROI
warning output
source/binary fingerprint

DoD：

- [ ] callback 内采集不依赖时间近似；
- [ ] 目标属性来源为同帧 target-frame snapshot；
- [ ] objectlist 与 algorithm object 映射有 source proof；
- [ ] public evidence 能优先替代重复 GDB。

## 4. P1 仿真和 GDB

### P1-08 SGU 目标级注入稳定运行

状态：partial  
依赖：P0-09

当前真实配置：HILMODEL=2，策略为 sgu_injection；目标级分析通常可用 3–5 帧预热。
不要和点云 150–200 帧混淆。

验证：

- bash start 前后 process/node；
- radar2 对应 /radar2_visualization_engine/arbe_visualization_engine；
- playback frame 和 wfAutosarData.frameID；
- 预热帧、目标帧、报警窗口、post window；
- derived-state fingerprint/output-transition fingerprint。

DoD：

- [ ] 同一 bag 连续两次运行输出 transition 可比较；
- [ ] 失败 session 不污染成功 session；
- [ ] artifact 带 workspace/binary/source/data identity；
- [ ] report 显示 runtime status。

### P1-09 点云级仿真 150–200 帧策略

状态：deferred  
依赖：P1-08

目标：实现 HILMODEL=1 或实际点云回灌链，提前 150–200 帧建立 perception/tracking 状态。

要求：

- 与 SGU 目标级注入使用不同 ReplayStrategy；
- report 显示 warmup policy 和实际 frame 数；
- 输出边沿比较考虑状态建立差异；
- 点云回灌失败不直接归因功能条件；
- 支持短 warmup 到完整 warmup 的敏感性对比。

### P1-10 GDB plan 输出链探针

状态：todo  
依赖：P0-07

扩展 runtime-debug-plan.v1：

- 读取 preflight.can_output.source_output_chain；
- 生成 internal/producer/source line capture candidate；
- 条件使用真实 frame/function/object token；
- 映射函数无 frameID/objID 时标记 unconditional/source-scope-risk；
- 不虚构函数签名；
- capture_fields 包括 AdasStM.*、producer input、external expression operand。

验收：

- [ ] 计划显示 algorithm output token；
- [ ] 计划显示 internal token；
- [ ] 计划显示 external signal token；
- [ ] 每个 breakpoint 有 source ref 和 scope note；
- [ ] runner 可消费，旧 plan 不被破坏。

### P1-11 Formal lifecycle 和 PID attach

状态：partial  
依赖：P1-08、用户权限确认

目标：

formal start → discover PID → executable check → attach → capture → detach/stop owned session

当前 blocker：ptrace_scope=1。

约束：

- 只能 attach tool-owned 或用户明确授权进程；
- 不杀非 owned 进程；
- bash start 不重复启动；
- process group/session ownership 落盘；
- attach blocked 给出可读原因和人工建议。

## 5. P1 HTML 和 Workbench

### P1-12 HTML 场景图准确性

状态：partial  
依赖：P0-04、P1-06

必须保证：

- +X forward、+Y left 与算法坐标一致；
- radar2/4 右侧目标不镜像到左侧；
- 四角来自真实 length/width/yaw；
- heading arrow 与 yaw 一致；
- ego rectangle、ROI、target polygon 不被裁切；
- 当前相交、ROI gate、未来预测点分别画；
- 点击 ego/target 显示/隐藏真实属性。

验收：

- [ ] 正/负 distY fixture；
- [ ] yaw=0/90/180/负角 fixture；
- [ ] ROI 与 polygon 相交/不相交 fixture；
- [ ] 视图缩放后能看完整 ROI；
- [ ] 图中显示 i 和 objID provenance。

### P1-13 数据列表和报警列表层级

状态：todo  
依赖：P1-02

目标 UI：

数据列表
  ├─ 数据 A
  │   ├─ FCTA_R × 2
  │   ├─ FCTB_L × 1
  │   └─ ...
  └─ 数据 B
      └─ ...

要求：

- 数据列表和该数据报警列表不是同层级；
- 中间图区滚动位置不受左右栏滚动影响；
- 右侧属性栏独立滚动；
- 当前 data/event/frame 在顶部有摘要；
- 切换数据不会保留上一条 target/runtime fields。

### P1-14 报告自然语言和表格一致性

状态：todo  
依赖：P0-06、P1-12

检查：

- 文字 token/value 必须来自表格/证据对象；
- 文字说满足时对应 condition status 必须是 satisfied 或 runtime output confirmed；
- 未来预测不能写成当前相交；
- 内部信号已观察必须有同帧 GDB/public field；
- source candidate 不能写成已发送。

DoD：

- [ ] deterministic narrative consistency checker；
- [ ] mismatch 时 report=partial/block；
- [ ] FCTA/FCTB/其它功能 fixture。

## 6. P1 Pi 独立运行

### P1-15 Pi 独立入口现场验收

状态：partial  
依赖：P0-09

运行环境：

- Python；
- Node/npm；
- Pi executable 或 PATH 中的 pi；
- CR60_RADAR_ANALYZE_PYTHON，可选；
- CR60_PI_PROVIDER / CR60_PI_MODEL，可选；
- REMOTE_BASE_URL/API key 只存在 .env。

验收对话：

1. 分析这条 bag，先给我有哪些报警；
2. 展开 FCTA_R 的报警帧、目标属性、自车属性；
3. 告诉我报警条件按代码怎么一步步命中；
4. 继续查下游 FCT 内部 signal；
5. 给我可复制的 GDB 条件；
6. 执行已批准的 runtime debug；
7. 把结果写成 HTML。

每一步都要看到：

- Pi 选用了哪些 tool；
- tool 输入/output artifact；
- 当前结论和未确认项；
- 是否需要用户批准。

### P1-16 Pi prompt 约束复核

状态：todo  
依赖：P1-15

复核 ai/pi_bridge.py 和项目 prompt：

- 不猜车型/COEM/分支/radar/i/frame；
- 不把 feature name 当 source function；
- 不把未求值条件判 false；
- 不把 AI inference 写成 observed；
- 先输出中间观察，再输出结论；
- 只使用 catalog 已注册工具；
- side-effect tool 需要 approval；
- 优先返回 artifact ref，避免长文本占上下文；
- freshness 不满足时停止使用旧 knowledge。

### P1-17 AnalysisRun 自动恢复

状态：todo  
依赖：P1-15

场景：

- 用户重启电脑；
- GDB runner 中断；
- 网络/ROS 节点失败；
- 报告成功但 Pi 中断；
- source/binary 变化。

要求：

- run/step 状态可读；
- 只从成功 checkpoint 继续；
- artifact identity 不匹配时停止；
- 不重复执行有副作用的 start/build/GDB；
- 用户可用自然语言继续调查。

## 7. P2 高级诊断

### P2-01 根因分类

状态：todo

候选类别：

data
replay/warmup
perception
tracking
situation
function logic
parameter/config
output mapping/integration
build/binary/source mismatch

分类是 AI 推理层，不能覆盖确定性事实；至少给 Top-3 线索、支持证据、反证和下一步实验。

### P2-02 What-if/参数敏感性

状态：todo

要求：

- 当前 source/config 读取参数；
- 明确参数是静态、随自车状态变化还是随车型/COEM变化；
- 有公式和依赖时才做 what-if；
- 不直接修改源仓；
- 输出候选 diff/实验计划，不未经批准自动 patch。

### P2-03 需求到代码追踪

状态：todo

要求：

- 需求材料优先；
- 真实需求与代码条件关联；
- 标记 gap/冲突/未覆盖；
- 历史 memory 不能替代当前 source。

### P2-04 协同 Debug Workbench

状态：todo

实体：

AnalysisRun
AnalysisStep
Claim
Hypothesis
DebugExperiment
UserObservation

用户可以确认/否定线索，工具持续记录反证，最终报告区分 AI 推理和用户确认。

## 8. 测试矩阵

### 8.1 每次相关改动的窄测试

python -m py_compile engines/arbe/preflight.py engines/diagnostic_report.py engines/diagnostic_narrative.py
python -m pytest tests/test_arbe_preflight.py tests/test_diagnostic_narrative.py tests/test_condition_trace.py -q

### 8.2 产品 gate 测试

覆盖：

- cli/capabilities/module dispatch；
- code context/event path；
- runtime debug plan/run/evidence；
- GDB service；
- arbe replay/public runtime；
- cr60 precheck；
- project capability/Pi context；
- diagnostic report/narrative/geometry/GDB confirmation；
- evidence query/Pi bridge。

当前基线：127 passed in 17.42s。

### 8.3 契约检查

至少检查：

- contracts/arbe-preflight.v1.schema.json；
- contracts/diagnostic-report.v1.schema.json；
- contracts/diagnostic-narrative.v1.schema.json；
- contracts/diagnostic-output-chain.v1.schema.json；
- contracts/runtime-evidence.v1.schema.json；
- contracts/runtime-debug-plan.v1.schema.json。

### 8.4 不要默认做的测试

- 不因 CSS/narrative 小改动跑全量回归；
- 不为验证静态报告去远端 build/start；
- 不为验证 parser 去跑 formal GDB；
- 不把旧输出目录全部重生成当测试；
- 未批准不启动/停止正式 arbe 或修改远端 workspace。

## 9. DDD 交付模板

每项完成后记录：

任务 ID：
用户价值：
输入：
代码修改：
新增/修改 schema：
工具入口：
确定性证据：
AI/推理边界：
测试命令和结果：
实际 artifact：
未完成/blocked：
下一步：

每个阶段结束时更新：

- PRD（需求变化时）；
- research report（新事实时）；
- architecture/design（接口/边界变化时）；
- AGENTS.md（公开 API、schema、prompt、缓存、流程变化时）；
- handoff（阶段完成/暂停/交接时）；
- TODO（状态、依赖、验收变化时）。

## 10. 后续 Agent 最短启动指令

请先阅读：

1. docs/technical/CR60_PI_UNIFIED_HANDOFF_2026-09-03_PRODUCTIZATION.md
2. docs/technical/CR60_PI_UNIFIED_TODO_2026-09-03_PRODUCTIZATION.md
3. docs/CR60_PI_UNIFIED_PRD.md
4. docs/technical/CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md
5. docs/technical/CR60_PI_UNIFIED_SOFTWARE_DESIGN.md
6. docs/CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md

从 P0-01 开始，先分类 dirty worktree；不要 reset/clean。
完成 P0-07 前不要宣称 FCT 对外映射 runtime 已闭环。
先用 CRGVI-1829 单条数据验收，再扩展多事件/批量。
每完成一项更新 TODO 和 handoff，并记录 artifact/test evidence。
