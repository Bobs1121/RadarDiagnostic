
# CR60 Pi Unified Platform：真实用户流程确认表

版本：user-workflow-questionnaire.v1

日期：2026-08-26

状态：P0 已完成第一轮确认，剩余实现细节待探测/补充

## 1. 目的和回答规则

这份表用于确认真实工程师从数据到诊断、从静态预检查到 GDB 调试的实际操作链路。它不要求用户重复描述仓库中可以自动探测的函数、字段、topic 或参数，而是锁定只能由真实使用者确认的流程语义、权限边界、判断标准和验收标准。

第一轮 P0 已由用户确认主要流程；现在只需补充表中列出的实现细节。P1 结合当前仓库和首个 runtime case 继续确认。

无需提供密码、token 或私钥；只需要说明连接方式、权限类型、实际命令或配置位置。

工具的准确性规则：

- 仓库可以读取的字段、函数、topic、构建脚本和配置由工具自行探测并附 provenance。
- 用户需要确认的是工程上实际怎么操作，以及什么结果算正确。
- 未确认的信息进入 blocked_missing_input 或 runtime_probe_required，不允许用默认值伪装成准确结论。
- 报告区分 observed、derived、not_available、conflict；静态推导不等于运行时验证。

## 2.1 用户已确认的流程事实（2026-08-26）

| 事项 | 已确认内容 | 仍需探测的细节 |
|---|---|---|
| 数据和构建顺序 | 先传数据到 Linux；按数据软件版本切 src/algo_source；数据唯一对应 COEM 和具体车型；更新 CUDA/配置；编译外层主仓；bash start；导入和播放；debug | 软件版本和车型身份在数据中的实际载体，及版本到 tag 的映射 |
| 自动化 | 原则上所有操作自动，关键步骤让用户确认 | 审批合并为阶段性 plan approval |
| 材料获取 | 有材料先读；没有材料就通过对话补齐，最终归一为同一个 intake | 具体字段载体和缺口问题由工具动态生成 |
| SGU | HILMODEL=2；按代码运行周期的 frameID 预热 3–5 帧 | 具体版本例外及最小状态要求 |
| point-cloud | 仍按代码运行周期和 frameID 设计 150–200 帧预热 | 各项目/功能/雷达是否需要 profile 差异 |
| 报警首帧 | 算法向 CAN 信号输出报警位的 0→非零上升沿 | CAN 字段和算法 warning 位的精确映射 |
| VSCode/GDB | 默认 ROS: Attach；启动后选择 arbe_visualization_engine 和 radar1/2/3/4 | namespace、PID、binary、source mapping 自动校验 |
| runtime | 优先 headless GDB，将中间变量直接写入 HTML | 符号、优化、权限、扰动和采样策略 |
| workspace | 允许工具操作原仓；运行前会重新编译，运行中默认不会发生更新；不同版本之间内部接口可能变化 | 每次运行前重新 source learn、检查 adapter compatibility 和生成 GDB plan |

报警首帧的业务口径已经确定：选择算法内部向 CAN 输出报警信号的那一帧。当前代码探测到的 `warning_status_with_frame` 只作为算法输出代理；工具还要探测实际 `RteComMapping_TxRunnable_FuncSignal`、宏展开后的 `RteLite_Write_<signal_token>`、`Com_SendSignal` 是否在当前 host 执行。`warning_status_raw` 仍单独作为真实 CAN/ECU 侧证据，不再反复询问这个业务定义。

## 2. 不需要用户重复提供的信息

原则上由工具从当前 arbe、src/algo_source、构建产物、ROS topic、rosbag 和 runtime probe 探索：

1. 功能、函数、宏、结构体字段、参数常量、调用链和源码位置。
2. outer arbe、algo_source、COEM 的 branch、commit、dirty 状态和 source hash。
3. rosbag 的 topic、消息类型、frame counter、object ID、报警输出和输入对象。
4. HILMODEL、SGU 注入、point-cloud 路径和现有播放器服务。
5. GDB 目标进程、调试符号、源文件映射和表达式可见性。
6. ROI、目标 polygon、动态参数依赖和当前帧输入。
7. 某个字段来自 bag、runtime、源码推导还是不可用。

用户不需要维护固定的 FCTA/FCTB 参数表。代码版本变化后，工具应重新生成 schema 和证据链。

## 3. P0：必须先确认的真实流程

### A. 从数据到工具

| ID | 问题 | 为什么重要 | 期望证据 |
|---|---|---|---|
| Q-P0-01 | 请从一条全新数据开始，按真实顺序写出：数据放置、版本确认、切子仓、COEM/车型配置、编译、bash start、导入、播放、进入 debug。 | 这是工作流主状态机，不能推测。 | 实际命令、路径、GUI 操作或录屏；可脱敏。 |
| Q-P0-02 | Q-P0-01 的每一步，哪些希望自动，哪些要人工确认，哪些禁止自动？ | 决定自动化和审批边界。 | 给每一步标注自动/确认/禁止。 |
| Q-P0-03 | 通常一次处理一条 bag、一个问题单目录还是整个数据文件夹？是否有视频、CSV、xlsx、日志、截图和多个版本材料？ | 决定 case manifest 和批量边界。 | 一个真实目录树和命名规则。 |
| Q-P0-04 | 未来用户最少要提供哪些输入？候选包括服务器、arbe 路径、子仓 branch/commit、bag、车型、COEM、雷达位置、功能、问题单、视频、DBC、需求材料。哪些必须填，哪些能探测，缺失时哪些必须阻断？ | 决定 intake schema，避免猜车型、版本或雷达映射。 | 字段、是否必填、来源、缺失处理。 |
| Q-P0-05 | 数据和代码版本绑定的权威来源是什么：问题单/Excel G 列、用户 branch、tag、commit、metadata 还是人工判断？多个来源冲突时谁优先？ | 版本错配会使代码和 runtime 结论失效。 | 优先级和冲突规则。 |
| Q-P0-06 | 切 branch、应用 COEM、编译和启动时，工具是否可以操作原 arbe 工作区？还是必须复制隔离工作区？ | 决定写权限、并发隔离、回滚。 | 原工作区/隔离副本/两者均可及副作用。 |

### B. 回放和报警定义

| ID | 问题 | 为什么重要 | 期望证据 |
|---|---|---|---|
| Q-P0-07 | SGU 目标注入的真实操作是什么？HILMODEL 改为 2 是所有版本的前置条件，还是仅部分版本/车型成立？修改位置、编译和验证方式是什么？ | SGU 是优先 runtime 路径，不能把单版本事实固化。 | 一条真实 SGU case 的操作记录和例外。 |
| Q-P0-08 | point-cloud 的“提前 150–200 帧”准确指什么：报警首帧前的 frameID、LGU 消息帧、雷达帧还是固定时间？不同 radar 是否不同？ | 决定 warm-up 起点、帧对齐和状态建立。 | 一个 bag 的报警首帧、回放起点、提前帧数、播放速率、丢帧情况。 |
| Q-P0-09 | SGU 已有目标注入时是否可以从关注帧开始？是否仍需建立功能状态、车辆状态或其他模块的前置帧？ | 决定两条 replay strategy 的真实差异。 | SGU 最小前置帧数或验证依据。 |
| Q-P0-10 | 报警第一帧的业务定义是什么：输出位 0→1 上升沿、UI 第一次显示、声音/制动第一次产生、warning counter 第一次变化，还是指定信号？ | 决定首帧是否可重复。 | 一条样例中各定义对应的帧，及最终口径。 |
| Q-P0-11 | 一条数据中多功能报警、同功能多次报警是否全部拆成 event？持续区间怎样定义，间隔多少帧算新 event？ | 决定事件模型和断点集合。 | 多报警样例和拆分规则。 |
| Q-P0-12 | 功能和左右侧的权威输出是什么：算法内部 flag、LGU、HMI、CSV、视频标注还是人工结论？左右侧如何映射 radar1/2/3/4？ | 不能根据雷达物理位置猜报警侧。 | 权威 signal/field 和映射来源。 |

### C. GDB 控制

| ID | 问题 | 为什么重要 | 期望证据 |
|---|---|---|---|
| Q-P0-13 | VSCode 的 ROS: attach 实际 attach 哪个进程、节点和可执行文件？launch.json 如何区分 radar1/2/3/4？ | 决定 GDB 目标和 source/binary 映射。 | 脱敏后的 launch.json、进程名、节点名、PID 获取方式。 |
| Q-P0-14 | VSCode 和 Linux 的真实关系是 Remote-SSH、本地 VSCode 远程 attach，还是其他通道？GUI、ROS master、算法进程是否同一服务器？ | 决定控制链路和端口转发。 | 一次成功 attach 的实际步骤。 |
| Q-P0-15 | 是否允许后台 GDB attach、条件断点、continue、读取变量、导出日志和 detach？是否允许自动重启仿真？最大可接受暂停多久？ | 决定自动 debug 安全边界和时序影响。 | 每个操作标注允许/需确认/禁止，最大暂停时间。 |
| Q-P0-16 | 首版优先生成可复制的 VSCode 条件断点，还是 headless GDB 全自动采集？两种模式都保留吗？ | 决定 Sprint 顺序。 | 优先级排序。 |
| Q-P0-17 | 断点至少要包含哪些真实表达式？类似 frame_counter >= 47872 && frame_counter <= 47877 && sObj->objID == 44 的条件是否还要加入 i、radar、功能 flag、对象类型？ | 决定 breakpoint pack 的生成规则。 | 一条真实可复制样例和必须字段。 |
| Q-P0-18 | 编译产物是否带 -g，是否允许 -O0/-Og，是否存在 stripped binary、容器或交叉编译限制？ | 无符号时局部变量不可保证准确。 | 当前编译命令和 source/binary 映射。 |

## 4. P1：准确性和长期扩展问题

### D. frame、对象、索引

| ID | 问题 | 设计影响 |
|---|---|---|
| Q-P1-01 | frame_counter、ROS frameID、rosbag 播放序号、算法输出 frame 和 UI frame 是否同一计数域？ | 报告必须保留各原始域及映射。 |
| Q-P1-02 | objInfo->trcOutData[i] 中的 i 是本 radar 数组索引、全局目标索引、排序索引还是复制后的索引？objID 是否跨帧稳定？ | i 必须能直接命中代码作用域。 |
| Q-P1-03 | SGU objTrans[i]、trcOutData[k]、objectlist/CSV 中的目标如何对应？是否有 source ID？ | 防止把时间接近目标错当成报警目标。 |
| Q-P1-04 | 目标重排、ID 复用、丢失或多 radar 共享 objID 时如何呈现？ | 需要 object identity confidence 和冲突报告。 |

### E. 坐标系、矩形、ROI

| ID | 问题 | 设计影响 |
|---|---|---|
| Q-P1-05 | ego 原点是否后轴中心？bumper2RearAxle_dist、radar_x_offset、radar_y_offset 的正方向和单位是什么？ | 决定自车和 ROI 的绝对位置。 |
| Q-P1-06 | distX/distY 是 ego 坐标还是 radar 坐标？需要何种安装位姿变换？yaw 属于哪个坐标系？ | 决定目标四角和 collision 是否有效。 |
| Q-P1-07 | 目标四角能否直接从 runtime objPoly 获取？字段缺失时是否允许默认尺寸？ | 默认尺寸必须标记 derived，不能冒充 runtime。 |
| Q-P1-08 | ROI 来自宏、COEM、NvM、车型文件、ROS topic 还是动态车速/横摆角计算？哪些会逐帧变化？ | 决定参数 schema 和每帧重算。 |
| Q-P1-09 | ROI 与报警侧/雷达物理侧/目标位置冲突时，是否报告 coordinate conflict 而不是强行修正？ | 保证工具暴露错误。 |

### F. 功能、代码和参数

| ID | 问题 | 设计影响 |
|---|---|---|
| Q-P1-10 | 未来功能是否固定为 BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB，还是允许新增功能插件？ | 决定 FeaturePlugin。 |
| Q-P1-11 | 参数真实来源有哪些，播放期间哪些会变？ | 决定静态和 runtime 参数采集。 |
| Q-P1-12 | 代码链路优先显示完整链路，还是围绕事件的最小链路？是否需要需求/标准条款？ | 决定检索上下文。 |
| Q-P1-13 | 哪些表达式可以暂时显示 runtime_probe_required，哪些必须第一版支持？ | 避免错误简化 C/C++ 表达式。 |

### G. 输出和人工判定

| ID | 问题 | 设计影响 |
|---|---|---|
| Q-P1-14 | HTML 必须固定显示哪些区块，哪些点击展开？ | 决定 report schema 和 UI 信息密度。 |
| Q-P1-15 | 是否需要 JSON/JSONL、source snapshot、GDB transcript、截图/视频索引、SQLite/Parquet？ | 决定 Pi 和 radarAnalyze 的接口。 |
| Q-P1-16 | 工具是否可以直接给正报/误报，还是只给证据和候选原因由工程师确认？ | 决定结论责任边界。 |
| Q-P1-17 | 版本错配、变量不可得、frame 未对齐、目标不确定时如何阻断和提示？ | 决定 fail-closed 状态。 |

### H. 多用户、服务器、规模

| ID | 问题 | 设计影响 |
|---|---|---|
| Q-P1-18 | 用户各自有服务器/工作区，还是共享服务器和同一工作区？ | 决定锁、隔离、并发。 |
| Q-P1-19 | Linux、ROS、CUDA、编译器、Python、目录布局是否变化？允许安装 runner 和依赖吗？ | 决定环境 adapter。 |
| Q-P1-20 | 单次 bag 数量、大小、并发和可接受等待时间？ | 决定队列、缓存和限流。 |
| Q-P1-21 | 客户数据和源码的权限、日志脱敏、结果保留和访问范围？ | 决定安全和审计。 |

## 5. 验收样例

至少准备四类样例，避免只用单一 FCTA/FCTB 数据：

| 样例 | 最低要求 | 验证能力 |
|---|---|---|
| A：SGU 单功能单次报警 | 已知功能、侧别、首帧、目标 ID，允许 HILMODEL=2 | SGU runtime attach、变量、断点 |
| B：SGU 多功能/多次报警 | 一个 bag 中多个功能或多个报警区间 | event 拆分和目标选择 |
| C：point-cloud 报警 | 明确需要 150–200 帧前置计算 | warm-up、回放起点、状态链 |
| D：无报警或冲突 | 无报警、版本错配、目标不确定或 ROI 冲突至少一种 | fail-closed |

每个样例尽量提供：bag/case 路径、arbe 路径、source branch/commit、车型/COEM、已知预期、已存在的 VSCode 断点，以及哪些结果必须完全一致。

## 6. 第一轮回复模板

    [流程]
    Q-P0-01: 从一条新数据开始，我实际操作是：
    1.
    2.
    3.
    Q-P0-02: 自动 / 人工确认 / 禁止自动：

    [输入与版本]
    Q-P0-03: 典型目录树：
    Q-P0-04: 必填输入：
    Q-P0-05: 版本绑定权威来源及冲突优先级：
    Q-P0-06: 是否允许操作原 arbe 工作区：

    [回放]
    Q-P0-07: SGU/HILMODEL=2 实际步骤：
    Q-P0-08: point-cloud 报警帧、起始帧、提前帧数、播放速率：
    Q-P0-09: SGU 最小前置帧数：
    Q-P0-10: 报警第一帧定义：
    Q-P0-11: 多功能/多次报警拆分规则：
    Q-P0-12: 功能与侧别权威输出：

    [GDB]
    Q-P0-13: ROS attach 的进程/节点/target：
    Q-P0-14: VSCode 与 Linux 的连接方式：
    Q-P0-15: 允许的后台 GDB 操作及最大暂停时间：
    Q-P0-16: 首选人工辅助、半自动还是全自动：
    Q-P0-17: 真实条件断点样例：
    Q-P0-18: 编译符号/优化情况：

    [验收]
    样例 A 路径与预期：
    样例 B 路径与预期：
    样例 C 路径与预期：
    样例 D 路径与预期：

## 7. 回填动作

收到第一轮回答后：

1. 将事实和来源写入调研报告。
2. 将产品行为写入 PRD 和 intake/output schema。
3. 将权限、版本冲突、报警首帧、warm-up、GDB 策略写入 ADR。
4. 将样例转成 Sprint 验收 manifest。
5. P0 闭环且 SGU case 可复现后，才进入 runtime probe；point-cloud GDB 放在 SGU 证据链通过后。

## 8. 当前不能承诺的事项

在事实确认和实际 runtime 验收前，不能承诺：

- 仅靠静态 bag 能得到所有报警首帧和所有 runtime 临时变量；
- 任意版本、车型、COEM 都能用同一套固定参数规则解析；
- objID 或索引 i 在所有数据和模块中天然稳定；
- 只凭雷达物理位置就能判断功能报警侧；
- 后台 GDB 不会改变实时回放时序；
- point-cloud 的 150–200 帧对所有项目和功能都相同。

## 9. Analysis Workbench 第二轮产品问题（2026-08-30）

以下问题只涉及用户工作方式，不要求用户理解 frame/ROI/GDB 内部实现：

| 编号 | 问题 | 当前建议 |
|---|---|---|
| Q-P1-01 | 默认让工具自动分析到什么程度后停下来？ | 自动到 Debug-ready；关键冲突、副作用或用户选择事件时停 |
| Q-P1-02 | 用户手工 VSCode debug 的结果如何回到工具最方便？ | 首版页面粘贴/表单；后续可选轻量 VSCode bridge |
| Q-P1-03 | 不同 Gen6 项目的页面要完全统一，还是允许功能专属面板？ | 统一三栏骨架 + 项目/功能插件 panel |
| Q-P1-04 | 是否需要多人查看、批注和接力同一个 AnalysisRun？ | 首版本地单用户，schema 保留 actor/timestamp |
| Q-P1-05 | 最终“根因确认”由谁签字？ | 必须由算法工程师/问题负责人确认，工具只给 supported hypothesis |
| Q-P1-06 | 哪类中间线索最值得优先放在首屏？ | Event Map、目标身份、关键条件、代码层级、关键缺口、下一实验 |

这些答案会影响 Workbench 默认节奏和 Sprint 验收，不影响现有只读预检查、代码查询或
runtime artifact 的正确性。
