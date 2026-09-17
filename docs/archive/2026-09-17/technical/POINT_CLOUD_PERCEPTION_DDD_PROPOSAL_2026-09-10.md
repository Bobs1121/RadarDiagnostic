# 点云驱动的感知与 ADAS 联合仿真分析：DDD 需求与设计方案

> **归档：2026-09-17。本文仅保留历史设计/证据，不再是当前开发指令。当前唯一套件见 [DDD 入口](../../../technical/GEN6_AI_DOCUMENT_INDEX.md)。**


<!-- GEN6-DDD-CANONICAL-20260916 -->
> **当前设计已统一至 [Gen6 AI DDD 文档入口](../../../technical/GEN6_AI_DOCUMENT_INDEX.md)（2026-09-16）。** 本文保留历史设计、操作和证据上下文；产品/架构/实施冲突按新套件裁决。特定版本宏、预热帧数、服务器状态及历史测试结论不作为当前通用事实。


日期：2026-09-10。版本：`perception-proposal.v1`。状态：`implementation-slice-4-verified / field-replay-pending`。
DDD 在本项目指 Document-driven development。本文件交付需求、事实、设计、实施与验收方案；不代表新增能力已经实现或点云仿真已经验收。

> 2026-09-11 复核补充：后续开发与状态解释遵循 [自主仿真分析设计复核及收口基线](SIMULATION_ANALYSIS_DDD_REVIEW_2026-09-11.md)。下文历史 `verified/ready` 仅表示对应局部检查；真实感知闭环仍有 Pi 选择、阶段采集、执行完成、输入解码与身份复核缺口，不能概括为仅等待现场执行批准。RUN-02 的“没有 point topic → 缺少点云输入”推断已被后续 LGU 解码探索修正；RUN-04 等解码数量仍需录制版本与二进制布局独立校验，不能作为感知重算输出证明。

## 1. 产品目标与适用边界

用户希望在已有 `adasFunc.c` 功能分析之上，使用点云重新运行前级感知，解释“为什么这个目标没有生成、生成迟了、属性不准、ID 跳变，或最终造成 ADAS 漏报/误报”。

交付主线：问题/目录 → 输入审计 → 当前源码与构建路径确认 → 连续点迹回放 → 分阶段证据 → 代码与数据联合解释 → Top-3 假设与区分实验 → 单数据报告与批次索引。

本期“点云仿真”明确为从已录制、已解码的点迹/检测列表进入后处理感知。ADC、FFT、波束形成、CFAR 等更前端阶段，只有材料确实含所需原始输入且存在可执行入口时才另列支持范围。不能将已有 `dotTrans` 称为未处理的原始雷达信号。

保留两条可比较路径：

| 路径 | 注入内容 | 可以回答 | 必须说明的限制 |
|---|---|---|---|
| `sgu_injection` | 录制目标及配套自车/配置 | 给定目标下 ADAS 决策、保持和抑制原因 | 无法证明该目标如何由点迹生成 |
| `point_cloud` | 输入点迹及其质量、帧、自车、标定/配置 | 点迹处理、过滤、聚类、跟踪、输出属性到 ADAS 的传播 | 受输入截断、压缩、量化、缺失字段影响；不是传感器端全链路等价证明 |

支持“只分析感知”及“感知→ADAS 联合分析”。无报警也是合法输入，不能依赖已经存在的 AlarmEvent 才创建调查。

## 2. 当前状态：已检查事实与未证明事项

2026-09-10 对当前工作树及远端 `10.190.171.44:/home/hoz2wx/CR60LIGHT/cr60_light_arbe` 做只读检索。
远端 outer HEAD 为 `4c171298b2c3583509ea9e3da222b90ba0a9e513`，algo HEAD 为 `a81b08a38f316a3d25bfcbcad6dcfc822d24b990`。已有 9/10 preflight 记录 dirty 状态；HEAD 不是未提交内容的完整指纹。以下源码事实不能替代本轮重新编译/运行证据。

| 证据 ID | 当前来源和发现 | 对方案的约束 |
|---|---|---|
| SRC-01 | 远端 `src/arbe_phoenix_radar_driver-master/arbe_gui/CMakeLists.txt:18-19` 指向 `adas/symmetry/perception/src` 和 include | 当前分析优先检查 symmetry；仓库另有 beamform 同名入口，不能只按函数名命中即认为是编译目标 |
| SRC-02 | 远端 `src/algo_source/adas/symmetry/perception/src/postProcess.c:170,187,193`：`PostProcessMainTI` 调用 `DataProcInit`、`CalEgoCarAddInfo_CR` | 初始化、自车模型同样影响感知结果，不能只记录目标输出 |
| SRC-03 | 同文件 `:195-236`：`#if 0 == HILMODEL` 包围 `DotPrePosTI`、`EnvModelDetect`、`DotFilter`、`ObjCluster`、`ObjTrack`、`OutputTrkObj`、`CalibMainProcess`、`OtherAttributeCal`；`OutputCluObj` 另受 `BUILDMODEL >= 2` 控制 | 需要独立构建配置及阶段运行命中证明；不能复用 HILMODEL=2 的成功报告作为点云通过证据 |
| SRC-04 | 同文件 `:238-244`：`PF_BUILD_FUNTEST_SGU_INJECTION` 可调用 `replace_objInfo_with_injection`，随后 `AdasFunc` | 即使感知被执行，目标仍可能在 ADAS 前被替换；必须证明实际消费的是本次跟踪输出 |
| SRC-05 | 远端 `paraDefine.h:10-17` 当前 `BUILDMODEL=2`，`HILMODEL` 两条预处理分支均为 2 | 修改启动参数不足以启用感知分支；需构建产物、预处理结果和 runtime 共同证明 |
| SRC-06 | 远端 `visualization_node.cpp:3719,3794` 可见目标注入 gate 和 `BagTransTIMerge` | `/wf/corner_radar/lgu_data_<radar>` 名字本身不能判定只含目标；需检查载荷与消费分支 |
| SRC-07 | 本地参考副本 `tools/arbe/.../visualization_node.cpp:3560,3645,3689,3764,3793`：读取 dotTrans、按 range 排序、填 algo_bagData、非零 HILMODEL 注入 trcOutData、调用主函数 | 本地副本与远端行号不同；报告必须标明 source root/hash，不能混用源码定位 |
| SRC-08 | 同一本地回调副本：角度/距离/速度 `/100.0f`、`noise=power-snr`；多项方差为 0；主函数 `frmPeriod=0.066f` | 启用点云前须逐字段证明转换正确；零方差是适配器赋值，不应冒充原始观测；固定周期要与录制周期核对 |
| CODE-01 | `engines/arbe/remote_replay.py` capture extractor 当前归一化 warning/radar_info/objectlist/ROI | 可录制额外 topic 不等于已有点迹/簇/关联矩阵/航迹状态采集；这些需要新增 producer/adapter |
| CODE-02 | `engines/runtime_debug_plan.py:663` 现有 SGU 宏检查；既有 DDD US-008 定义点云 150–200 帧但说明现场样例待补 | 点云 readiness、reset、输入覆盖与阶段采集仍需单独验收 |
| CODE-03 | `engines/diagnostic_report.py` 已有条件、几何、运行上下文和事实投影 | 扩展现有报告，增加感知阶段和跨帧对象关系，不复制另一套报告引擎 |
| RUN-01 | `outputs/remote_public_execute_20260910.json` 历史成功采集，`61` snapshots，带帧和无帧报警共 `4` 上升沿行，`8` unbound object rows | 这是公共输出回放证据；不是四个独立故障，也不是完整感知重新执行证明 |
| RUN-02 | 2026-09-11 只读 preflight：当前远端 source 为 `BYD_SC6H`、`HILMODEL=0`、binary sha256=`b4d895f702fc920508be7a79c98e47592caaab1601d7e9c7f78182bf0a8744fe`；同一 bag topic metadata 的 `point_cloud_topics=[]`，只有 LGU/objectlist | 编译分支门已通过，但当前 bag 缺少可审计点云输入，`point-cloud-plan` 必须 blocked；运行中的 PID 属于 `/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int`，不能借用作目标 workspace runtime 证明 |
| RUN-03 | 2026-09-11 只读扫描远端 data 目录现有 `26` 个 `.bag` 候选；topic 名过滤 `dot/point/cluster/detection/raw_radar/radar_data` 命中 `0` 个 | 这是 bounded topic-name evidence，不能证明 LGU payload 内部没有点；当前仍需一条已解码点迹 artifact 或批准的 payload decode，不能把扫描结果当成全量输入否定 |
| RUN-04 | 2026-09-11 只读解码 `/wf/corner_radar/lgu_data_2`：`PERInfoOutStruct.dotTrans` 200 消息、36591 点迹，同时解码 `objTrans` 3200 条输出对象；保留 `frame_id/point_key/byte_offset`，报告采用 2000 点 inline + JSONL 全量 artifact；HILMODEL=0、输入/identity gates 通过，但 runtime PID 属于 `_0909int` workspace，`runtime_workspace_alignment=conflict`，point-cloud plan 被安全阻断 | 已证明 post-detection 点迹/对象输出和 source/build identity 可用；仍未证明目标 workspace runtime、ADC/FFT/CFAR、cluster/track producer 或真实 point-cloud replay |
| RUN-05 | 针对实际 `_0909int` workspace 的只读 preflight：HILMODEL=0、runtime workspace alignment=`aligned`、binary sha256=`547444aa56f1bf19280f6938d3f5b6074a9a2820ccd27831fa0fd0060e6b2829`；基于同一 decoded point artifact 生成 plan=`ready`，binding=`approval_required` | 控制面已具备一份可审阅的正确 workspace plan；批准前不执行 replay，且仍不证明 stage producer/cluster/track/parity |
| RUN-06 | 当前 runtime topic inventory：`/wf/corner_radar/lgu_data_2` publisher=`/rviz`、subscriber=`radar2_visualization_engine`/`arbe_gui`；`/wf/corner_radar/rviz/pointcloud_2`、`/wf/rviz/clusters_2`、`/wf/objectlist_2` 均有 runtime publisher；有类型/连接，但 bounded sample 当前无消息 | 输入和阶段输出通道拓扑已对齐，静态 inventory 不等同于 replay 期间有帧流动；ready plan 已绑定三类 output topic，需批准 replay 后再验证 completed frames/outputs |

因此应修正此前“M0–M4 全部完成”的解释范围：已有测试和 release smoke 支持的是部分工具契约及目标注入公共回放；并未证明第二异构真实项目、全感知阶段 lineage、完整恢复或点云因果报告。不能将这些缺项通过更名为增强项隐式移出本次新需求。

## 3. DDD 用户故事与验收编号

沿用主基线 US-001～US-026；本轮需求基线为 US-027～US-032。PC-AC 是本轮唯一场景前缀，
不重用历史文档中含义不同的 AC-001。各 AC 的当前实现/验收状态以 §11–12 和
`release_acceptance.v1.json` 为准，不由本节 Given/When/Then 定义推定为完成。

| 用户故事 | 验收场景 | Given / When / Then |
|---|---|---|
| US-027：判断数据可否重新运行感知 | PC-AC-01 | 给定混合点迹/目标文件，审计消息 schema、样本载荷和当前入口后，输出每雷达支持路径、缺字段、是否使用了录制目标；不从 topic 名猜路径 |
| US-027 | PC-AC-02 | 只有目标或 GUI 降采样点云时，给出静态/ADAS 分析和不支持原因；不宣称全感知复现 |
| US-028：可靠运行完整感知链 | PC-AC-03 | 给定版本绑定输入和已批准计划，从干净状态连续回放；提供构建宏、binary hash、入口/阶段命中、实际完成帧及目标来源，证明没有注入覆盖 |
| US-028 | PC-AC-04 | 遇到倒放、跳帧、重播、超时或输入 EOF，reset/预热状态可见；只有完成处理的帧进入对比，失败 attempt 也持久化 |
| US-029：查看目标生成/消失过程 | PC-AC-05 | 点击对象或未检出区域，追溯同帧点→过滤→簇→关联→航迹→输出；没有真实映射时显示 unavailable，不以距离近邻冒充 observed |
| US-029 | PC-AC-06 | ID 复用、簇分裂/合并、目标漏检、空帧出现时，跨帧对象身份与匹配等级明确；不沿用上一帧数据 |
| US-030：源码与实际数据联合解释 | PC-AC-07 | 针对所选异常，展示当前编译分支、真实调用路径、输入/中间/输出字段、实际分支观察或静态代入及缺口；AI 给出可反驳 Top-3，不能由条件数量确认根因 |
| US-030 | PC-AC-08 | 出现宏不明、unsupported 表达式、优化掉变量、source/binary 冲突，保留部分解释并限制相关结论；未知不是 false |
| US-031：可交付的感知报告 | PC-AC-09 | 相同选中帧驱动点云场景、阶段计数、航迹时间线和源码卡；分层展示录制/回放/派生/inference；导出的 HTML 可按交付说明离线打开 |
| US-031 | PC-AC-10 | 批量含好文件、坏文件、无报警文件，全部出索引条目；每条有独立结果/失败原因和可恢复位置，单条失败不丢其他结果 |
| US-032：比较与复验 | PC-AC-11 | 同一输入在不同版本或两种策略中运行，独立 reset/预热；自动匹配记录目标与回放目标并显示匹配依据，先报告最早可观察分歧再解释传播 |
| US-032 | PC-AC-12 | 无标注时只输出一致性、稳定性、差异；有可信 GT 才报告 precision/recall 等精度；模型候选必须经专家复核/区分实验才能提升结论 |

## 4. 仿真执行流程

```text
目录 + 用户问题
 → intake：project/variant/data/source/config 绑定
 → capability audit：点迹输入边界、缺字段、运行阶段、可用采集方式
 → plan：策略、起止帧、reset/预热、采样与副作用范围
 → 独立 workspace/build/profile：当前编译分支与 binary 验证
 → 批准与执行：独立 ROS 会话、唯一 run/attempt、完成帧账本
 → stage evidence：点迹、簇、跟踪与 ADAS 的阶段输入/输出
 → 同身份/同帧关联和录制-回放比较
 → 当前源码路径与条件代入
 → AI Top-3 + 区分实验 → 报告/索引/可恢复调查
```

### 4.1 编译与运行配置

建议为两条路径保留独立 build/profile，不来回覆盖正式工作区。对当前已检查版本，点云分支候选为 `HILMODEL=0`；它不是跨版本通用规则，必须由实际 active source/preprocessed TU、编译参数及调用观察证明。`PF_BUILD_FUNTEST_SGU_INJECTION` 不得覆盖本次感知目标；仅有宏文本或符号存在均不足以证明阶段执行。

Manifest 记录 source snapshot（包含 dirty diff 内容及未跟踪编译输入）、配置/CUDA/标定文件内容 hash、消息布局、编译参数、binary、输入文件内容 hash。不能用 HEAD、git status 文件名清单或旧 Pi context hash 代替完整输入绑定。
执行前重新读取实际目标身份；比较两个传入旧 JSON 相同不算实时复核。计划还应绑定 host/user/port/master、输入和采集白名单、资源归属及输出目录。

### 4.2 时序与预热

150–200 帧是既有点云 profile 的初始候选窗口，不是任意数据都足够的证明。窗口须覆盖出生/确认/删除、遮挡和 ADAS 保持历史；必要时从录制起点执行。保留 requested/warmup_completed/analyzed_frames 与不足原因。
至少比较两个预热长度及一次全前缀参考运行的关键轨迹/输出差异；没有收敛则声明 warmup-sensitive，扩大窗口或保留结论缺口。
区别 bag timestamp、源帧、算法帧、ROS 接收时间、实际运行耗时。`frameID` 回绕用 epoch 区分。
现有回调 ACK 位置在后处理主调用之前，接收 ACK 不能代替阶段完成 ACK；必须验证 player 等待策略及完成计数。
固定 `0.066f`、丢帧、乱序、并发 callback、CPU 过载必须纳入运行证据；改变周期会影响算法，不能在 adapter 中静默“修正”。

### 4.3 状态和失败恢复

计划、准备、执行、采集、归一化、推理和交付分别保存 AnalysisStep。重试创建新 attempt，恢复下载复用原 capture；禁止按相同 base 删除已有证据。
中断需区分连接断开、播放器停止、录制停止、算法仍存活和产物可恢复。观察“没有进程”不能独自证明由 trap 清理；记录 tool-owned PID/group、退出原因与清理时间。公共回放当前共用正式 master 的历史记录不能称为独立会话隔离验收。

## 5. 数据获取与证据契约

### 5.1 最少需要什么

| 层 | 获取字段（存在才读取） | 主要问题 | 采集来源 |
|---|---|---|---|
| 录制载荷 | 消息类型/定义、frame、radar、dot count、量化系数、缺包/截断 | 输入是否够、输入位于哪一处理阶段 | 原 bag/BLF/MF4 及 parser provenance |
| 算法输入点迹 | 原始索引/排序后索引、距离/角度/径向速度、SNR/power/noise/RCS、质量、方差、歧义状态 | 转换、量纲、排序是否改变结果 | serializer→adapter 的真实转换映射 |
| 配套输入 | 自车速度/转弯/挡位、安装位姿、动态标定、BLD、车型参数、dt、有效位 | 点迹解释是否使用正确环境 | 源载荷+当前配置，冲突显式保留 |
| 预处理/过滤 | 输入输出计数、字段变化、拒绝原因、对应源码分支 | 点在哪一步被丢弃或改写 | 优先公共 trace；缺失则批准后的探针 |
| 聚类 | cluster id、成员点 key、中心/速度/尺度/协方差（实际有才给） | 未成簇、错聚、分裂/合并 | 当前 cluster 容器和成员映射 |
| 跟踪 | 候选/成熟状态、预测/更新、关联候选/选中关系、门限或代价、出生/删除原因 | 未建轨、确认迟、关联错、ID 跳变 | 当前跟踪状态/关联结构的有界 trace |
| 输出及 ADAS | OutputTrkObj 输出、后续属性修改、trcOutData、真实报警输出/保持状态 | 哪个阶段的变化传播到报警 | 输出采集+阶段边界 token |

不存在的质量/关联字段不能补零；图上“0 个点”和“没采集到点云”必须是不同状态。
记录 `dotTrans → 按 range 排序 → algo_bagData → BagTransTIMerge → dotStruct` 映射。排序并列值、丢弃和数组压缩导致索引变化必须保留；point index 不能当跨帧物理点 ID。

### 5.2 拟议 schema（确定性切片已实现，现场 producer 仍待）

| 契约 | 内容 | 消费者 |
|---|---|---|
| `perception-input-contract.v1` | injection boundary、必需字段、转换/损失、数据完整度、支持阶段 | replay plan、报告 |
| `perception-stage-map.v1` | stage→真实函数/条件/编译分支/输入输出 token/source ref、运行证明要求 | planner、source query、采集器 |
| `perception-stage-evidence.v1` | run/attempt/frame/stage、before/after、采样范围、记录数/截断、artifact refs | evidence query、报告、AI |
| `perception-lineage.v1` | point↔cluster↔track↔output 的有向关联、recorded/replay 匹配、证据等级 | 场景与时间线、比较 |
| `perception-lineage-index.v1` | callback→JSONL byte range、row/type counts、block SHA-256；不替代 lineage 节点或边 | 精确 callback 查询与有界 Pi context |
| `perception-run.v1` | run/attempt、warm-up、reset、observed/completed/analyzed frames、失败 attempt | replay runner、恢复和报告 |
| `perception-comparison.v1` | 比较身份、显式对齐方法、最早可见分歧、影响与未观测阶段 | AI、复验报告 |
| `perception-batch-index.v1` | 每条数据的报告入口、状态和失败原因 | batch viewer、交付 |

上述契约的静态 producer/consumer 已在本地实现；真实阶段 trace、连续回放和 runtime
producer 仍属于现场验收，不由合成 artifact 代替。

复用 `runtime-case-evidence.v1` 作为现有 runtime 兼容入口，通过 additive refs 引入感知 artifact；大数组不直接塞进旧单帧 JSON。schema 版本迁移须兼容旧报告并在 consumer 未支持时明确降级。

推荐 FrameKey：`(data_hash, run_id, attempt_id, radar_id, frame_domain, epoch, frame_id)`。
PointKey 加 `stage_id/source_message_id/index`；TrackKey 加 `tracker_instance/birth_frame/local_id`。
每个字段至少有 `raw_token/value/unit/coordinate_frame/status/source_ref/phase`；source_ref 含 path/line/hash，运行值含 callback/step。
每条 edge 有 `relation_kind`、`observed|derived|not_available` 和 `basis_ref`；跨策略 ID 不相等不自动判错，同 ID 不自动认为同一目标。

### 5.3 有界采集与 JSON 合法性

全程低成本阶段摘要+目标窗口详细 trace；全量点迹保存在独立分块 artifact，只给 AI 当前问题的切片及统计。保留未采集/截断计数，不能因 UI 抽稀丢失机器证据。
采集预算按输入规模测量后确定，避免现在许诺固定时延。记录读盘次数、CPU/RSS、trace 字节、每阶段耗时、LLM token 与首次有效线索时间。
NaN/Infinity 不得直接进入需标准 JSON 的 Pi 协议；编码为 value=null + raw_literal + non_finite reason，保留原值含义，不能转为 0。

## 6. 当前源码链与联合分析方法

当前已查到的逻辑顺序（按 SRC-02～04，未来版本必须重新解析）：

```text
corner_radar_post_process_data_callback
 → 点迹解码/排序/输入组装 → BagTransTIMerge
 → PostProcessMainTI
   → DataProcInit → CalEgoCarAddInfo_CR
   → [HILMODEL==0]
       DotPrePosTI → EnvModelDetect → DotFilter
       → ObjCluster → ObjTrack → OutputTrkObj
       → CalibMainProcess → OtherAttributeCal
       → [BUILDMODEL>=2] OutputCluObj
   → [如启用注入宏] replace_objInfo_with_injection
   → AdasFunc → 当前功能分支/最终算法报警
```

这张图是静态调用骨架；报告中的“实际执行路径”必须由 runtime hit/trace 标注。
尤其不能把 `OutputTrkObj` 的快照当成 `OtherAttributeCal` 后或 ADAS 入口时的同一份属性值。

联合分析步骤：

1. 用户问题决定锚点：报警事件、航迹出生/消失、ID 跳变、属性突变，或指定时间/空间区域。
2. 从输出异常反向选择相关 stage，再按前向依赖补齐必要点迹、自车和状态窗口。
3. 读取当前 source index、active branch 和 stage map；宏/指针/循环状态无法静态证明时只列候选。
4. 用 stage+frame+phase 严格匹配值，代入真实表达式并显示 observed/derived/not_evaluable/unsupported。
5. 比较同输入不同运行或录制参考，指出“最早可观察分歧”；中间缺层时禁止称为首个根因。
6. AI 生成最多三项候选：现象、机制、支持/反证、假设、缺口、置信区间/等级及最小区分实验。
7. 单变量或有明确控制条件的复验验证传播：如仅改变输入转换、版本、参数或预热；记录副作用与混杂因素。

同一历史数据的录制目标是参考输出，不是真实世界 GT。SGU 正常、点云异常可缩小到注入上游差异，但仍可能是 adapter/配置/reset/预热造成，不能直接断言 `ObjTrack` 有 bug。

## 7. 报告呈现与最终交付物

### 7.1 单条数据详细报告

首屏依次呈现：用户问题与当前结论 → 仿真覆盖阶段/运行可信度 → 关键证据表 → 场景+时间轴 → Top-3 和下一步。
代码、完整 JSON、运行命令放入折叠详情；用户无需输入 frame/PID/token，但点击证据能回到真实 token 和源位置。

```text
问题：为什么目标出现较晚？   模式：点迹重跑感知 → ADAS
状态：执行完成 / 证据部分可用 / 候选待复验（分别显示）
覆盖：输入 ✓ 过滤 ✓ 聚类 ✓ 跟踪 ? 输出 ✓ ADAS ✓
----------------------------------------------------------------
场景区：点迹 + 簇 + 航迹 + 目标 + 可选 ADAS ROI   | 所选对象/阶段属性
时间轴：预热 / 出生 / 确认 / 丢失 / 报警           | 录制↔回放差异
----------------------------------------------------------------
阶段追踪表：输入 → 变化/拒绝原因 → 输出 → 源码 → 证据等级
候选原因卡：支持、反证、缺口、如何验证
```

图层切换“录制点迹/实际注入点迹/过滤后点/簇/候选轨迹/成熟轨迹/ADAS 输出”。默认突出与问题相关区域；提供全部视野复查。时间轴可以查看无报警帧、空帧、预热帧。
点选点迹高亮所属簇及轨迹；点选航迹反查真实支持点。没有 lineage 时不画实线关联，派生匹配用虚线并标方法。
图例写明单位、坐标系和旋转/位姿来源；默认统一鸟瞰坐标，提供雷达/车体切换；不同雷达不混用 frame 或原点。色彩之外同时用文字/图形区分丢弃、候选、确认和未知。

### 7.2 报告结果形态（示例均非本次诊断结论）

| 证据情况 | 应呈现的结果 | 不应呈现 |
|---|---|---|
| 原始窗口无相关有效点迹 | “输入窗口未发现支持点；需检查上游检测/录制完整性”，附覆盖范围 | “感知算法漏检已确认” |
| 过滤前存在点、过滤后消失且有分支 trace | 真实拒绝条件、输入值与阈值；解释该事实是否与需求冲突 | 只凭点数变少断言过滤错误 |
| 有簇无成熟轨迹，缺关联内部量 | 出生/确认过程表、最早可见差异，候选及所需探针 | 编造关联门限或删除原因 |
| 轨迹存在但进入 ADAS 前被替换 | 明确“感知运行存在，但 ADAS 消费了注入目标”，区分两条结果 | 把报警归因于这次点云输出 |
| 同身份实验支持候选机制 | 提升候选支持等级，并列未排除解释和验证范围 | 单凭 replay completed 标根因 confirmed |
| 证据相互冲突/阶段未采集 | 图中灰色缺口、可查看局部事实，给下一步采集建议 | 把 unknown 画为条件失败或空场景 |

### 7.3 交付清单

每数据 `diagnostic-report.html/.md/.json`、已有 bundle 的 additive refs、stage/lineage/comparison artifact、指标 CSV、执行/恢复日志；批次 `index.html` 按模式/项目/功能/阶段/结论等级筛选。
默认采用自包含或随包附带资源的 HTML。大点云需分块加载时随包提供 launcher 和离线使用说明，并单独验证 file/local HTTP 场景；不承诺任意浏览器 file:// 能跨文件读取。
确定性事实报告可先交付；LLM 不可用时保留事实和缺口并明确“AI 分析未完成”，不能生成替代的伪根因。

## 8. 代码映射和实施切片

| 切片 | 复用位置 | 新增或扩展责任 | 退出条件 |
|---|---|---|---|
| PC-S0 输入/路径审计 | intake、preflight、source resolve、code-context | 输入 contract、active compile/stage map、字段损失清单 | PC-AC-01/02；一条真实输入能说明可运行/绕过阶段 |
| PC-S1 点迹真实回放 | arbe adapter、build、sim-verify、execution binding | 独立 profile、reset/完成帧/warmup sensitivity、注入覆盖探测 | PC-AC-03/04；真实 runtime 证明整个路径；不能用 mock 替代 |
| PC-S2 感知证据链 | 外部 harness/parser、public_runtime、runtime_evidence | dot/cluster/track trace producer、source-bound 字段解码及 lineage | PC-AC-05/06；可反查点-簇-轨迹，歧义显式 |
| PC-S3 源码联合推理 | codegraph/event_code_path、condition_trace、diagnosis-panel、ledger | 非报警锚点、stage+phase binding、Top-3/实验 | PC-AC-07/08/11/12；事实与假设分层，缺值不会切断 AI 推理 |
| PC-S4 报告与批次交付 | diagnostic_report/narrative、viewer、index | 图层、时间轴、阶段卡、相同帧联动、离线包 | PC-AC-09/10；工程师从自然语言独立生成并核验证据 |
| PC-S5 异构适配与发布 | capability manifest、doctor、release gate | 第二项目/格式 adapter 与当前版本证据索引 | 相同场景矩阵通过；不改核心编排、不串缓存 |

Pi 仍是唯一编排入口。优先扩展既有 `sim-verify/public-runtime-normalize/evidence-query/diagnosis-report` 契约；只有独立责任才新增原子能力，不能另起固定“点云诊断总管线”。
外部 harness/arbe 改动分别在其仓库维护，当前仓库用 adapter/version/schema 接入，不复制算法实现。本文不授权新的正式 workspace 构建或运行。

## 9. 验收证据、效率与发布标准

每个 AC 关联 requirement version、当前源码/工具/binary/config/data hash、run/attempt、命令、环境、artifact hash、结论与缺口。新增的感知必须项不能在 manifest 中设成 optional 后宣称全通过。
至少覆盖：正常目标、无目标、过滤拒绝、错聚/簇分裂、航迹确认迟/ID 跳变、遮挡、倒放/reset、缺配套输入、错误宏、注入覆盖、跨版本比较和批量坏文件。
单元测试证明 mapping/状态契约；合成 fixtures 证明可控逻辑；真实回放证明编译分支/时序；专家案例与盲测证明解释有用；浏览器检查证明报告可读。证据层不可互相替代。
发布门需读取运行结果和覆盖信息；文件存在、命令 rc=0、smoke passed 均不能单独证明感知 stage 被执行或 root cause 正确。
性能先对真实小/中/大样本建立 P50/P95 与内存/输出体积基线；再冻结预算与回归阈值。记录首次索引和复用索引两种成本；不在设计时捏造“秒级分析”。

## 10. 实施前仍需确认或探测的事项

- 自动探测：真实候选 bag 是否含足够完整 dotTrans、量化/方差/质量字段；当前源码实际参数与阶段容器；编译目标与符号；ROS 回放/ACK/reset 行为。
- 自动验证：目标注入宏与点云分支组合、录制点迹是否已过滤、点云输出截断/压缩、固定周期与实际 dt 差异。
- 业务选择（进入实施时确认）：首个典型问题优先“未建轨/生成迟”还是“错误轨迹导致误报”；是否需要 ADAS 联合结论；可用参考标注及允许的受控实验范围。
- 外部条件：需要一条包含相关点迹历史的真实样例和匹配代码/配置；尽量从现有资料发现，不让用户手填技术字段。另一个项目与独立用户验收保持真实未完成状态。

推荐首先实施 PC-S0 和 PC-S1：证明输入确实进入当前感知阶段，再建设细粒度 trace 与报告。没有这项证据时，复杂场景图和 Top-3 文本都不足以交付可信的感知分析工具。

## 11. 当前代码实施检查点（2026-09-10）

已实施并通过测试的第一条纵向切片：

| 代码/契约 | 当前状态 | 证据 |
|---|---|---|
| `engines/point_cloud_replay.py` | implemented | 点云 replay plan、输入契约、stage coverage、lineage、analysis read model |
| `ai/modules/point_cloud_plan.py` | implemented | Pi/CLI `point-cloud-plan`；当前 preflight `HILMODEL=2` 会明确 `blocked` |
| point-cloud execution profile | implemented | plan 携带与 `sim-verify` 一致的 `execution_plan`；identity-bound binding 和批准执行链已有 fake-provider 集成测试，但未启动真实 HILMODEL=0 runtime |
| `ai/modules/point_cloud.py` | implemented | Pi/CLI `point-cloud-analyze`；JSON/HTML `perception-report.v1`，缺阶段证据为 `partial` |
| `engines/diagnostic_report.py` + `ai/modules/diagnostic_report.py` | implemented | `perception_analysis` 作为 additive evidence layer 进入现有 diagnosis-report JSON/Markdown/HTML，不替代 ADAS 结论 |
| `contracts/perception-*.v1.schema.json` | implemented | 输入、阶段、lineage、analysis、report schema |
| Pi catalog / extension | implemented | `point-cloud-plan`、`point-cloud-analyze`、`point-cloud-batch` 已注册并生成 `registerTool` |
| `tests/test_point_cloud_perception.py` | implemented | 输入 alias/缺字段、HILMODEL gate、lineage 不猜、partial report、schema validation |

第二条确定性切片已实施：

| 代码/契约 | 当前状态 | 证据 |
|---|---|---|
| 输入审计扩展 | implemented | 按 payload shape 审计 point/cluster/track/target，逐雷达字段计数、message schema、转换/target usage、字段损失和 NaN/Infinity 保真；不按 topic 名分类 |
| `perception-run.v1` | implemented | run/attempt、warm-up、reset、observed/completed/analyzed frames、失败 attempt 保留 |
| `perception-comparison.v1` | implemented | 仅显式 match 或声明的 exact frame/identity key；输出最早可观察分歧，不按时间近邻猜测 |
| stage evidence normalization | implemented | 多帧 `frame_domain/epoch/frame_id`、逐条 evidence、计数、截断和 runtime proof 保留；不把静态 source candidate 当运行命中 |
| `point-cloud-batch` / `perception-batch-index.v1` | implemented | 好/坏/无报警输入逐条隔离，JSON/HTML/metrics CSV 和失败原因保留；HTML 可按 project/function/stage/conclusion 离线筛选 |
| `perception-scene.v1` / `perception-timeline.v1` | implemented | 明确 selected frame 才生成同帧场景、阶段时间线和 SVG；缺选中帧保持 `not_available` |
| `perception-warmup-analysis.v1` | implemented | 对独立 150/175/200 帧 attempts 做一致性/敏感性投影；没有 output signature 时不宣称收敛 |
| `perception-injection-audit.v1` | implemented | 分离显式 injection macro、target usage 和 stage runtime proof；启用注入时 point-cloud plan blocked |
| source condition bindings | implemented | `point-cloud-analyze` 保留 condition-trace 的 source ref、求值状态和缺失 token，不把 `not_evaluable` 当失败 |
| `perception-hypothesis-set.v1` | implemented | 接收最多 3 个 candidate 和区分实验，保持 `candidate_only`，不伪造 observed/confirmed 根因 |
| `perception-capability-manifest.v1` | implemented | 把当前输入/阶段/runtime 能证明的点云路径、unsupported 和 freshness 结构化输出；缺 runtime 不宣称完整感知 |
| `perception-artifact-audit.v1` | implemented | JSON/JSONL/CSV 按内容结构分类；MF4/BLF/BAG 无附加 parser 时显式 unsupported，保留 size/SHA-256/provenance |
| artifact adapter SPI | implemented | `register_perception_artifact_adapter()` 支持外部格式 parser 接入，不修改点云核心编排 |
| PointCloud2 output decoder | implemented | 按 declared field offset/datatype 解码 stage output，保留 topic/point_step/row_step provenance；无 runtime sample 时不虚构数据 |
| `perception-validation.v1` | implemented | 报告生成后检查 schema、计数、ready/runtime/lineage 不变量和 Top-3 限制；只报告 validation，不升级根因结论 |
| Pi catalog / extension | implemented | 重新生成后包含 `point-cloud-batch`、`point-cloud-validate`；当前 catalog 为 63 capabilities |

尚未宣称完成：`HILMODEL=0` 的独立 point-cloud build/replay、真实 stage trace、簇/航迹生产者、跨阶段完整 lineage，以及报告与实际感知 run 的 parity。当前模块对缺少这些输入返回 `blocked/partial`，这是交付安全边界。

## 12. 2026-09-13 implementation continuation

后续获批的隔离公共回放已取得 PointCloud2 与 objectlist 公共输出，但没有 producer-owned reset/warm-up ACK。
最新 source-bound report `outputs/point_cloud_remote_report_source_bound_20260912_inline200_indexed/`
保留 180 个 callback pair、31,440 个 PointCloud2 输出点、10,576 个 `cluster_id` 节点、3,260 个
公开 ObjectList 输出行（lineage 的 track nodes 为这些行的投影）。原始支持行共 40,257 条，去重后
canonical lineage 为 32,443 条边；选中 callback 的 scene 为 174/58/2/2，lineage 查询有 157 条 canonical
边和 161 条 raw 行。`input_decode`、reset/warm-up、私有阶段内部 trace 和 ADAS warning 仍缺失，报告
继续保持 `partial`；不能把公开输出关联升级成 PC-AC-03/04/06 完成或根因确认。

报告投影与 Pi 消费路径已加固：全量计数与内嵌样本分离，大型 lineage 写入 callback-contiguous 的
JSONL 附件，并用 `perception-lineage-index.v1.json` 固定 byte range、行数、类型计数和 block SHA-256；
默认内嵌上限 200。大型输入未给 `output_dir` 时自动生成唯一本地 run 目录。
`point-cloud-read` 可依 `scene.selected_frame` 默认读取同帧，并返回有界字段投影和分页信息；Pi 的
显式 `context_path` 现在会先载入再注入确定性 anchor，工具说明要求总量只取全量计数字段。此进展
改善的是事实读取与上下文边界，真实私有 stage producer、稳定预热、第二异构项目和现场独立 build
仍未完成。报告 HTML 的 selected-frame 场景可切换 points/clusters；点击精确点行、簇行和轨迹/输出行会
展开同帧属性；簇质心只按 exact `cluster_id` 派生，track/output 不在缺少验证变换时叠加。报告目录附带
localhost-only HTML 使用说明，2026-09-13 Playwright 检查 0 console errors/warnings、exact point/cluster/track
交互与层缺口。按此本地报告交付约定，PC-AC-09 已验收；file:// 未列为支持要求。PC-AC-05 仍为
partially-verified，内部过滤/关联 trace 与跨帧身份证据仍缺。Pi-product read-only 复验得到与 anchor
一致的全量/selected-frame 计数；同一
129,050-row 工件的本机三次读取初步比较，全扫描/hash P50/P95 `0.9779/1.0254 s`，索引 callback
切片 `0.0489/0.1405 s`。这些结果不把 PC-AC-03/04/06/07/11/12 升级为通过，也不构成 P4
性能验收（冷/热缓存尚未隔离，且尚无第二项目/格式样本）。2026-09-13 最终全量本地回归为
`860 passed, 1 skipped, 2 xfailed, 10 warnings`；release gate accepted `10/10` required entries；doctor `ready` / 64 capabilities。
远端 reset/warm-up ACK、私有阶段 trace、异构项目和独立构建仍待验收。

### 12.1 2026-09-13 lineage 关系语义与 Pi P2 复核

本次 P2 复核发现报告的 `tracks` 节点由公开 `/wf/objectlist_2` 输出行投影生成，不能代表内部 candidate/mature tracker 快照；因此 lineage 现在显式携带 `track_population.scope=public_objectlist_output_rows`，并将内部两类 population 固定标为 `not_available`。`cluster_supports_track` 仅覆盖点迹 `track_id` 命中已捕获 ObjectList ID 的关系；`point_supports_cluster` 的公开关系条件严格是 `cluster_id > 0`。`cluster_id=0/-1` 不生成该边，但报告不推断由哪个算法阶段设置这些值。

另一个计数缺陷是 `cluster_supports_track` 原先按每个支撑点重复写边：selected callback 原始 7 行仅对应 3 个唯一 `(cluster, track)` pair，全局原始 11,265 行对应 3,451 个唯一 pair。canonical lineage 现在按 `(from,to)` 去重，`raw_edges` 和 `raw_relation_counts` 保留输入行数；`relation_summaries` 显示关系两端的 node kind、唯一 pair 和 distinct endpoint 数。报告验证同步检查这些计数与 `relation_scopes`。

当前 source-bound report：`outputs/point_cloud_remote_report_source_bound_20260912_inline200_indexed/perception-report.json`，sha256=`620a4e5abde9d7591b32e542c1fad13613f4b3abb288d7d34566629ec81e821a`，状态 `partial / valid_with_warnings`。全局节点数为 points 31,440、clusters 10,576、tracks/outputs 各 3,260；canonical relation 数分别为 point→cluster 25,732、cluster→track 3,451、track→output 3,260；原始总边行为 40,257，canonical 总边为 32,443，`invalid_edge_count=0`。选中的 `callback:13-14` 含 174/58/2/2 个点/簇/公开 track 行/output 行；canonical 边为 152/3/2，原始 cluster→track 行为 7。时间线对相邻 callback `13-14 → 15-16` 记录 UID `43`、`47` 的两条 `derived` recurrence；timeline 汇总状态也标为 `derived`。

Pi P2 cross-frame read-only 复核产物 `outputs/pi_point_cloud_hypothesis_review_runtime_20260913_v15.json` 与该报告 hash 一致。模型准确将 UID `43`、`47` 标为 `same_public_uid_adjacent_callback` 的 derived 关系，并明确不代表物理目标身份或内部 track 生命周期；没有提出因果假设，也没有把 UID recurrence 解释为 ID reuse、删除或出生。PC-AC-06 因此获得公开 UID recurrence 证据，但仍为 `partially-verified`，内部生命周期、ID reuse、split/merge 和目标漏检行为需要 per-frame runtime/GDB trace。

2026-09-13 新鲜只读 preflight 保存为 `outputs/arbe_preflight_p2_refresh_20260913.json`：target workspace 为
`/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int`，`HILMODEL=0`、`BUILDMODEL=2`、
`PF_BUILD_FUNTEST_SGU_INJECTION=absent`；binary SHA256 为
`547444aa56f1bf19280f6938d3f5b6074a9a2820ccd27831fa0fd0060e6b2829`，GDB 12.1 available，debug symbols
present，`ptrace_scope=1`。探测时 radar2 visualization process 为 PID `3830187`，其 `/proc` executable
位于上述 workspace。outer/algo source 与配置仍 dirty，因此执行前必须重新验证 source/binary identity；GDB attach
可能短暂停顿运行中的 ROS process。本次只读 preflight 未 attach、未 build、未改源码。

最终报告页面的本地浏览器复验记录在 `outputs/offline_browser_verification_20260913_v6.json`，绑定 report sha256=`620a4e5abde9d7591b32e542c1fad13613f4b3abb288d7d34566629ec81e821a` 和 HTML sha256=`78f2495bc0d208066046620adfee9fa3012091b06acdbb45db1ba99157534f7b`。浏览器确认 0 console errors/warnings；相邻 UID 表显示 43/47 为 derived recurrence 并带 identity limitation。PC-AC-09 保持 accepted；PC-AC-05 和 PC-AC-06 仍 partially-verified，因为内部 filter/match trace、candidate/mature lifecycle、ID reuse/split/merge 和物理目标跨帧 identity 证据尚缺。

release acceptance manifest 现完整列出 PC-AC-01～PC-AC-12：PC-AC-01/09/10 为 `accepted`；PC-AC-02～08（含 PC-AC-05）、11、12 均保持 `partially-verified`，且未设为本地首版必需门。M0–M4 加 PC-AC-01/10 共 10 个必需项的 gate 可通过；这不把任何现场 AC 自动升级为通过。

### 12.2 Target-only 静态退化路径

当 capture 只有 `object_rows` 而没有任何 point rows 时，`perception-input-contract.v1.input_boundary` 现在标为
`target_only`（injection-only 显式标 `target_injection_only`；只有 source-proven 空 PointCloud2 message 才标
`empty_public_pointcloud_observation`），不再将占位空数组误算为已观测点迹，也不再落入默认 `post_detection_point_cloud`。
`perception-input-audit.v1` 的 `target_or_object_rows_only_not_point_cloud_input` diagnostics 会投影进 HTML Input contract；
如果提供当前 stage map/code context，静态 `ObjTrack`/ADAS source candidates 和 `not_evaluable` 条件仍可见，
而 full perception 状态保持 `blocked`。`test_target_only_capture_blocks_full_replay_but_keeps_static_source_analysis`
回归覆盖这一分层。真实 GUI-downsampled 点云的外部样本和完整 ADAS 退化分析仍待 field acceptance，PC-AC-02 保持 `partially-verified`。
同一静态回退的真实公开 ObjectList-only 报告保存在 `outputs/point_cloud_target_only_static_report_20260913/`，
report SHA256=`8ce4df5f1b78b26f6cb5c0e20e43c23d964c366b857c2bcd1fa97ee0109c2829`。它显示 0 点、
`target_only`、`target_or_object_rows_only_not_point_cloud_input`，source contract `source_verified`，并保留
`DotPrePosTI` / `EnvModelDetect` / `DotFilter` / `ObjCluster` / `ObjTrack` / `OutputTrkObj` / `AdasFunc`
的静态候选，但不把它们写成 runtime hits。HTML 检查记录 `outputs/target_only_static_browser_verification_20260913.json`
绑定该 report 和 HTML hash，console errors/warnings=0。

### 12.3 最终本地回归与远端刷新状态

target-only 输入边界变更后重新执行全量本地回归：`860 passed, 1 skipped, 2 xfailed, 10 warnings`，耗时 `698.98s`。这只证明本地回归覆盖，不满足现场构建、私有阶段 trace、reset/warm-up ACK 或跨项目验收门。

更新验收证据后，`tests/test_release_acceptance.py` 为 `4/4 passed`；`python tools/release_gate.py` 接受全部 `10/10` 必需项。`python scripts/gen_pi_extension.py` 重新生成 64 项能力，`python cli.py capabilities --json` 成功退出，`python tools/doctor.py --json` 返回 `ready`、64 项能力、无 lock mismatch、0 failures。release manifest 列出全部 12 个点云 AC，所有引用的 evidence 路径均存在。

后续只读刷新尝试记录于 `outputs/arbe_preflight_p3_refresh_20260913.json`（SHA256 `64610f450146ff269b0e383f285b2cd6eb744f56f4f9d502da147750724c1180`）。产物状态为 `blocked`：访问 `10.190.171.44` 的 22 个 SSH 探测均在 20 秒限时内超时，返回码为 `124`；另有两个本地 source-output 扫描完成。该产物没有新的 source、configuration、binary、PID 或 GDB identity。它表示当前无法观察远端，并不证明远端 runtime 已停止。最近一次完整 preflight 仍为 `outputs/arbe_preflight_p2_refresh_20260913.json`，在新的探测成功前只作为历史记录。

本轮未执行远端 build、replay、GDB attach，也未写入远端 source/configuration。已有公共 replay 证据仍限于此前获批的单次运行；后续 attach/replay 需要新的身份刷新和明确授权。

### 12.4 远端预检查的失败短路与未知状态

P3 的 22 次串行 SSH 超时暴露出 preflight 的失败路径既耗时，也会把没有输出误解成“runtime 未运行”“没有 GDB/binary”或“源码无映射”。`SshCommandRunner` 现在先做 5 秒有界的 `ssh_connectivity` 检查；连接失败或任一 SSH command 超时/返回 `255` 后，停止后续远端请求，并在 `probe_execution` 与各 probe 的 `skipped` / `blocked_by_probe` 字段记录原因。成功的 workspace、config、binary、runtime 和 source 探测仍按原顺序保留。

新的只读产物 `outputs/arbe_preflight_p4_refresh_20260913.json`（SHA256 `053fbdb55f50b8293a02879f5e3868d888e82bc306465e2c3127e2b42025ed16`）仍为 `blocked`，但只运行了一个连接探测，`ssh_connectivity` 在 `5.031s` 超时，跳过 22 个后续 probe。JSON schema 校验通过；`runtime.status=unknown`、进程/ROS 节点为 `null`、`bash_start_required=null`，GDB 为 `available=null`，宏/binary/CAN source 均标 `not_available/unknown`，没有报告 runtime 停止或工具缺失。

当进程枚举命令成功但没有匹配行时，`grep` 的空结果也会规范化为成功探测，因此 `runtime.status=not_running` 只表示已完成的进程扫描确实没有找到目标进程。当前相关测试 `tests/test_arbe_preflight.py` 为 `10 passed`；包含 preflight 消费方的 7 个测试文件共 `98 passed`。这项控制面修复不补足现场的 HILMODEL build、reset/warm-up ACK、内部阶段 trace 或 lineage 要求。

包含 fail-fast、未知运行态语义和新增清单 evidence 的全量回归为 `862 passed, 1 skipped, 2 xfailed, 10 warnings`，耗时 `567.05s`；10 条警告仍是语义记忆表 API 的弃用提示。

最终 `python tools/release_gate.py` 接受 `10/10` 个必需项；`python tools/doctor.py --json` 返回 `ready`、64 项能力、无 lock mismatch、0 failures。release manifest 的所有 evidence 路径均存在，PC-AC-01/09/10 维持 `accepted`，其余现场 AC 仍为 `partially-verified`。

### 12.5 2026-09-14 P0/P1 remediation follow-up

Pi provider allowlist 现在为普通交互会话保留有界的 point-cloud starter 和 `sim-verify`；单次问题若使用业务表述“目标没被检出/突然消失/跟踪丢失”，也会把点云调查能力加入 allowlist，不要求用户说 `point-cloud` 或 `ObjCluster`。`tests/test_pi_tool_bridge.py` 同时覆盖关键词选择与 `PiModule.run`→`_build_bridge`→`PiBridge` 的 allowlist 转交；最新定向运行 `28 passed`。这证明本地桥接边界，不证明真实 Pi 模型已在一次自然语言会话中完成 replay→analyze。

`sim-verify` 的 `analysis_handoff.analysis_inputs` 现在传递 capture path、source context、plan、revalidated execution binding 和 `perception-run.v1` sidecar；`point-cloud-analyze` 可直接消费 inline handoff 或 persisted handoff path，而不用 Pi/用户手工拼接 artifact。fake-provider 集成测试证明 handoff 贯通后仍将缺 reset/warm-up ACK 的 run 保持 `partial`。这只是控制面 integration，不代替 P1 真实 replay 或 Pi-product 验收。

P0 输入身份复核发现历史 `lgu_point_capture_current_20260911.json` 与显式 source context 不一致：原始 BAG SHA256=`241e732ada70dd809894d3bed5f3f6603358c0ea5cd45f6204ab11628d11e18c`，其 `source_context.data_fingerprint`=`764f9fcfddaa4cca1023781b9c4fbd63224e9bdfa20c95d92eede191e6b23e19`；capture 内 `source_context_id`=`f1482689ec5ab9a757c3bde7ecd80b8e3efb17b582cc863e15643de1a2d3c221`，显式上下文为 `7e70b553e9a7aec4d983b8380d629a0253b25c8a864936e2602328affcc05f1f`。这些值不得通过“显式输入优先”静默合并。

`PointCloudAnalyzeModule` 现在对 capture 与显式 source context 做逐字段比较并保留冲突；输入契约同时核对原始 artifact SHA、data fingerprint、active source layout hash 和录制兼容性证据。raw `PERInfoOutStruct.dotTrans` 仅有 source header/profile `verified=true` 时会保留解码行供静态分析，但 `layout_status` 为 `recording_version_unbound`；hash/版本不匹配时为 `conflict`，point-cloud execution plan 必须 blocked。`decode_lgu_output.py` 通过 `--recording-compatibility-path` 读取并 hash 绑定经审阅的兼容性证据，随后再核对该证据所指的 recording SHA 与实际 BAG SHA。

`perception-capability-manifest.v1` 不再仅凭非空 hash 字符串标记 freshness：它要求 ready plan、completed run、plan/run hash 相同、data/source/binary/config/session 五项 identity 跨上下文/plan/run 相同，并确认 server host/workspace runtime binding aligned。completed `perception-run.v1` 还要求非空 `run_id`、`attempt_id`、`plan_hash`、observed/completed frame、reset 与完成预热证据；`analysis.status=ready` 需 capability manifest、freshness 和 identity binding 同时 ready/aligned。未知仍允许部分静态分析，但不再升级执行/结论状态。

以冲突历史输入重新生成的本地报告 `outputs/point_cloud_lgu_report_identity_audit_20260914/perception-report.json` SHA256=`a399007ff98ecae39cc112ab42f081a5b61f96711f8b803edb404e443de010f4`，状态 `partial / valid_with_warnings`，input layout 与 source-context binding 均为 `conflict`，capability 为 `blocked`；报告 HTML 的 Input contract 区也显示数据 hash、layout 和 source identity 冲突。它是冲突处理证据，不是新的感知 replay。相关定向回归 `tests/test_lgu_output_decoder.py`、`tests/test_point_cloud_perception.py`、`tests/test_replay_provider_mapping.py`、`tests/test_execution_binding.py`、`tests/test_pi_tool_bridge.py` 为 `104 passed`。

随后按更新后的 HTML 投影重新生成 `outputs/point_cloud_lgu_report_identity_audit_20260914_v2/perception-report.json`，SHA256=`604f91950c9d37c96dd9f7e3dcec28b378572a0d437e253d171e509c7cccdf33`，HTML SHA256=`48f892f44b40b3e076c0b49c55041c881ef453990a877dab1d0d4044f837a76b`。Playwright 离线浏览器复验 `outputs/offline_browser_verification_identity_audit_20260914.json` 记录了 `partial`、`layout conflict`、`source_context_id` 冲突可见，`0 errors/0 warnings`；截图在 `output/playwright/point_cloud_identity_audit_20260914.png`。这是报告渲染验收，不是输入解码正确性或现场 replay 证明。

加入 plan/run hash 和 revalidated execution binding 后，最终冲突报告 v3 位于 `outputs/point_cloud_lgu_report_identity_audit_20260914_v3/perception-report.json`，SHA256=`20fc4d2364d995ec7a81fd5ce206d421092fd5fe4695248be299cd0afa9326ab`，HTML SHA256=`dd1a45b17bf4962d67996edcba8302ff54982d94155a37332d31bd6c43614cfa`。Playwright 记录 `outputs/offline_browser_verification_identity_audit_20260914_v3.json` 与 report/HTML hash 匹配，页面可见 `partial` 与 layout/source-context conflict，`0 errors/0 warnings`；截图为 `output/playwright/point_cloud_identity_audit_20260914_v3.png`。

以上修复收口了 F01 的本地选择器、F04/F05/F06 的 fail-closed 证据边界，并加强了 F03 完成态合同。最新只读 preflight `outputs/arbe_preflight_p6_refresh_20260914.json`（SHA256=`44733e05a134d4be38b89891edd532887d67b22d4fd553dedbe666c3eaf5b4d5`）5 秒 SSH 探测 `timed_out/124`，22 项后续探测跳过；远端 source/binary/runtime PID 均未知。§12.6 增加的本地 source snapshot 是静态且 dirty 的源码证据，不与远端运行时绑定。F02 私有阶段 producer、P1 真实完成 ACK/独立 reset/warm-up、P2 真实模型联合推理及 P4 第二异构项目/clean-machine/冷热门槛仍未证明；本轮没有远端 build、replay 或 GDB attach。

最后一次全量回归（本次局部 source-context mapping 改动之前）为 `873 passed, 1 skipped, 2 xfailed, 10 warnings`（`617.83s`）；本次改动后 `tests/test_code_context.py`、`tests/test_event_code_path.py`、`tests/test_code_gdb_plan.py`、`tests/test_project_capability.py`、`tests/test_product_capabilities.py`、`tests/test_release_acceptance.py` 为 `41 passed`，`tests/test_pi_tool_bridge.py` 为 `28 passed`。release acceptance 测试实际运行 `evaluate_manifest(run_checks=True)` 并验证 `10/10` required entries accepted；doctor M3 校验通过。manifest 21 条验收项引用的 175 个 evidence path 均存在；PC-AC-01/09/10 为 `accepted`，其余现场 AC 仍为 `partially-verified`。`git diff --check` 无 whitespace error，仅有 CRLF conversion 提示。

### 12.6 2026-09-14 BYD_SC6H 本地跨仓源码快照与 RTE mapping 隔离

从 `config.local.yaml` 指向的本地代码根 `D:\BYD-SC6H-cr60light\cr60_light` 建立了只读静态快照，artifact 位于
`outputs/code_context_byd_sc6h_crossrepo_static_20260914/`。snapshot SHA256 为
`772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336`，context ID 为
`73312fc491aa87186e10527a30d12b944d1992b95ce19992d2a423425ed9df2b`，覆盖 43 个明确 allow-list 的 C/H 文件、807 个函数和 1,299 条调用边。`code-context.json`、`code-index.json`、`output_mapping.json` 的 SHA256 分别为
`fbce8f7bc3117c4e55173a04cf4ca266400379a55610344ce03ee0b2f0187d7f`、
`a11b714cde11862eda95a645bf02c2f1bb9f5a4907363d33d5ec3ceed0081a49`、
`72c6f6f754decac75b0ee51a5fe4123493a3ba01e8c39672ca0b384750a78d0e`。外层仓库 HEAD `ab3eeb3a4ee1ca72adccdd16625ee375b73e73c4` 在 dirty `master`；`adas` 子仓 HEAD `2ff7784e053c87a6915d938dd154b02e526624db` detached 且 dirty。快照明确标记 `source_role=local_static_source_not_remote_runtime_bound`、`runtime_binding=not_available`、`binary_fingerprint=not_available`、`compile_macro_observation=not_observed`，不能代替远端 source/binary identity。

当前源码静态调用顺序从 `adas/symmetry/perception/src/postProcess.c::PostProcessMainTI`（170–271）进入 `DotPrePosTI`、`EnvModelDetect`、`DotFilter`、`ObjCluster`、`ObjTrack`、`OutputTrkObj`，随后调用 `coem/BYD_SC6H/components/AswPerception/func/adasFunc.c::AdasFunc`（11148–11214）。`AdasFunc` 的源码按 `g_radarPos.m_mountingPosition.radar_pos` 在 `FrontRadarAdas`/`RearRadarAdas` 间分支；当前运行的 radar/branch 未观察。

源码 `adas/symmetry/perception/include/paraDefine.h`（14–18）写明：定义 `PF_BUILD_FUNTEST_SGU_INJECTION` 时 `HILMODEL=2`，否则 `HILMODEL=0`。`postProcess.c` 的 `#if 0 == HILMODEL`（195–236）包住上述点迹、过滤、聚类、跟踪和输出链；之后 injection 宏块（238–241）可调用 `replace_objInfo_with_injection`，而 `AdasFunc` 调用位于该块之后（243–245）。这是当前本地源码的静态条件；没有当前 compile command、目标 binary 或 runtime probe，不能据此声明该条件在远端 build 生效或本次运行命中。

同时修正了 `code-context-refresh` 的 variant output mapping 选择：可显式传入 `output_mapping_rte_file`，否则使用 `source_identity.coem` 解析当前 COEM；没有显式 path 或 COEM identity 时也返回 `unavailable`，不默认套用 legacy GWM。被选中目录下所有 `RteComMapping_Tx*.c` 都进入 source manifest。已知 COEM 找不到 mapping 时返回 `unavailable`，不回退到另一 COEM；mapping 源码变化会改变 snapshot hash 并触发重建。当前 index 中 40 条 output mapping 均来自 `coem/BYD_SC6H/components/AswIf/ASW_ComMapping/RteComMapping_Tx.c`。`tests/test_code_context.py` 的 10 项用例验证 variant 选择、Tx/SGU companion hash 失效、缺失/未知 COEM 不回退及旧 mapping 文件清空；code-context/event-code-path 定向套件 `17 passed`。

这份本地源码证据加强了 PC-AC-07/08 的静态调用链、条件和 mapping provenance，但 selected-frame/runtime 分支观察、GDB trace、实际 binary、实时 CAN/ADAS 输出及真实 Pi 联合推理仍缺，因此这些 AC 继续为 `partially-verified`。

### 12.7 2026-09-14 Gen6 代码检索边界与 debug 计划

`code-analyze` 的列表查询现在默认最多返回 200 项，可显式设置 `max_results=1..5000`；`result_bounds` 返回精确的 `limit/total_count/returned_count/truncated`，截断时 message 也显示返回数/总数。CodeGraph 的 `callers/callees` 名称去重后统一受同一上限控制，不再在结果计数之前静默裁成 50 项。Pi capability schema 与 CLI 同步支持 `max_results`。

在 §12.6 的 BYD_SC6H 当前本地静态快照（source snapshot `772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336`）上，`PostProcessMainTI` 的 `max_depth=1` 查询返回 13 个直接调用，其中包括 `DotPrePosTI`、`EnvModelDetect`、`DotFilter`、`ObjCluster`、`ObjTrack`、`OutputTrkObj` 和 `AdasFunc`。`FrontCrossTrafficAlertAndBrake` 的 `max_depth=2` 查询返回 28 条静态路径，包括 `FctaDirectRunning`、`FctaTurning` 及左右侧 FCTA/FCTB warning handlers。边界证据分别保存在 `outputs/code_chain_gen6_pipeline_entry_20260914.json` 和 `outputs/code_chain_gen6_fcta_path_20260914.json`。

对 `PostProcessMainTI` 做 `max_depth=5` 查询时，code index 实际含 754 条路径；Pi 默认只接收前 200 条并附带 `truncated=true`，完整计数不丢失。实际结果保存在 `outputs/code_chain_gen6_postprocess_bounded_20260914.json`。同一 source hash 下的静态 GDB 计划 `outputs/code_gdb_plan_gen6_static_20260914.json` 定位到 `adas/symmetry/perception/src/postProcess.c:170`，生成 `break ...:170`、`bt 5`、`info args`、`info locals`。该计划未运行 GDB，也没有当前 binary/PID identity，不能作为 runtime breakpoint hit。

本轮最新只读 preflight `outputs/arbe_preflight_p8_refresh_20260914.json` SHA256=`ef6551e3db994649a598bde54cd6af5632cb0d12f5b5db7c475c3b7e02740265`；连接探测 `5.047s` 超时（`124/timed_out`），22 个远端探测被跳过；P8 与 P7 的内容 SHA256 相同，远端状态没有新增可观测字段，source/binary/runtime PID/GDB 均为未知。没有执行远端 build、replay 或 GDB attach。该静态查询改善 PC-AC-07/08 的本地代码检索与 debug 准备，现场结论仍保持 `partially-verified`。

本轮定向回归 `tests/test_code_analyze.py`、`tests/test_product_capabilities.py`、`tests/test_pi_tool_bridge.py` 为 `48 passed`；新增 `test_pi_bridge_preserves_bounded_code_analyze_results` 验证 bridge 保留截断计数，`test_pi_plain_symptom_flow_can_execute_bounded_code_analyze_through_bridge` 用 fake provider 验证普通目标症状 allowlist 经 `invoke_capability` 返回 4/12，`test_pi_bridge_cli_executes_bounded_code_analyze_json` 验证 Pi CLI JSON 边界返回 3/12；这些测试不代替真实 Pi model/product 验收；`doctor` 为 `ready`/64 项能力/0 lock mismatch；更新后的 release gate 接受 `10/10` 必需项。本轮全量 `python -m pytest -q` 为 `887 passed, 1 skipped, 2 xfailed, 10 warnings`（`204.63s`），覆盖当前 Code Context、bounded code query 与 Pi bridge 改动；这项本地回归不提升现场 PC-AC 状态。PC-AC-01/09/10 仍为 `accepted`，其他现场 AC 仍为 `partially-verified`。

### 12.8 2026-09-14 Gen6 source-only stage visualization

从 §12.6 的 43-file BYD_SC6H source context 重建并 schema-validate `perception-stage-map.v1`。source context SHA256=`772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336`；stage-map SHA256=`f6d950c82b5e2800dc25ce739a99cdbb0c1c6afd1396ff4fc6ec5372fb7639bc`，包含 8 个 stage groups 和真实路径/行号。所有 stage-map 行仍为 `source_candidate`，`runtime_proof=not_available`。

`_bounded_code_context()` 现在只读一次 CodeIndex，按确切 stage function name 与一跳 caller/callee 选取函数，避免 `DotFilter` 被 `ResetDotFilter` 之类的子串先占满结果。对 CodeIndex function definitions，`build_perception_code_flow()` 只有在 stage map 与 CodeIndex 的 source root、file set 和每文件 SHA-256 都一致时才列出定义；本次绑定状态 `same_file_snapshot`、匹配 43/43 文件、无 hash/path mismatch。HTML 把 stage-map occurrence candidates（可能为声明、定义、调用点）与 CodeIndex 函数定义候选分栏，定义候选包括 `DotFilter` (`dotFilter.c:2226`)、`ObjCluster` (`cluster.c:818`)、`ObjTrack` (`track.c:16119`)、`OutputTrkObj` (`track.c:15853`) 和 `AdasFunc` (`adasFunc.c:11148`)；这些仍是静态候选，不证明编译或运行命中。

source-only bundle 位于 `outputs/gen6_static_code_flow_20260914/`。没有录制输入，因此 JSON `status=blocked`、`input_boundary=not_available`、capability `blocked`，但结构校验为 `valid`。最终 report JSON SHA256=`fe44dbe1d4e428be08bc686a7a91f9fdb0528be2ccc0efa02a20ac8576dfd97e`，HTML SHA256=`10ebe317ea1cb3731b2a5f5c1ea2d5b8fd3791682f47f20b7047a840f86598dd`。离线浏览器验收 `outputs/offline_browser_verification_gen6_static_code_flow_20260914.json` 绑定两者 hash 和截图 `output/playwright/gen6_static_code_flow_20260914.png`，页面标题、输入详情折叠、8 行 stage 表、CodeIndex 定义列均可见，HTTP 200，console errors/warnings 为 0。该工件验证静态源码地图的呈现，不包含点迹、选中场景、运行证据或 replay，现场 AC 不升格。

### 12.9 2026-09-14 本机 Pi Gen6 代码检索运行续验

在 `ollama` provider 配置的 loopback endpoint `http://localhost:11434/v1` 上，Pi `0.84.4` 使用已安装但尚未列入 Pi 模型目录的自定义 ID `qwen3.5:9b` 成功完成本地请求。调用使用 `--offline`、`--no-session`、仓库内明确指定的 `.pi/extensions/radar-capabilities.ts`，并将 extension tool 白名单限制为 `code-analyze`。Pi JSON 事件流实际包含 `toolCall` 和对应 `toolResult`；未调用 Bosch/远端模型，也未改写用户级 Pi 配置。

真实参数为 `kind=call_chain`、`name=PostProcessMainTI`、`max_depth=1`、`max_results=3`，输入是 §12.6 当前 BYD_SC6H 静态 `code-index.json`。工具结果 `backend=source_code_index`，`result_bounds={limit:3,total_count:13,returned_count:3,truncated:true}`，snapshot hash 为 `772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336`；三条返回边是 `PostProcessMainTI -> DataProcInit`、`PostProcessMainTI -> CalEgoCarAddInfo_CR`、`PostProcessMainTI -> DotPrePosTI`。结果 artifact 为 `outputs/pi_local_code_analyze_gen6_20260914.json`（SHA256 `F30B36264FCA6762533350135CB4463159AFCC681977F4D1171587A03E412281`）；脱敏 Pi session/tool-call/result 摘要为 `outputs/pi_local_tool_trace_gen6_20260914.json`（SHA256 `00f1606c231cec64105e2d000b9c71c3cb0386b4075b35262f4813df3cdfd4d3`，不含模型思考流）。这证明本地 Ollama → Pi tool loop → Python capability bridge → 当前 Gen6 code index 的一次有界链路；不证明远端 source/binary identity、运行命中、selected-frame 或完整 perception 诊断。

同日刷新 `outputs/arbe_preflight_p9_refresh_20260914.json`（SHA256 `053fbdb55f50b8293a02879f5e3868d888e82bc306465e2c3127e2b42025ed16`）仍因 SSH connectivity 返回 `124/timed_out`、约 `5.031s` 短路，22 个远端探测被跳过。preflight 的 connection probe 按实现限制在 5 秒；额外只读 `ssh -o ConnectTimeout=15` 也在 15 秒后连接超时。当前 source、binary、runtime PID 和 GDB 仍未知；没有执行远端 build、replay 或 GDB attach。

### 12.10 2026-09-14 Pi source-only context and RPC verification

pi-orchestration-context.v1 now distinguishes case_analysis and source_code. The default case-analysis scope still blocks without intake/case data. A source-only request can bind code-context.v1 project/variant/source root/snapshot hash with provenance while marking data.status=not_required; missing code-context artifacts, invalid context, missing snapshot hash or source identity conflict block before model invocation; Pi never falls back to an unbound CodeGraph. PiModule selects this scope only for code intent without case/runtime inputs, uses a compact source-specific prompt and bounded read-only tool set, disables AGENTS/CLAUDE/skills/global-extension discovery for that turn, and explicitly loads only the generated project extension. The user Pi thinking setting is preserved unless an explicit level is supplied; built-in shell tools remain disabled.

真实 PiModule -> PiBridge (--mode rpc) -> local Pi -> code-analyze -> Python capability bridge 运行记录在 outputs/pi_module_bridge_code_analyze_gen6_live_profile_20260914.json（SHA256 F30B36264FCA6762533350135CB4463159AFCC681977F4D1171587A03E412281）和脱敏事件摘要 outputs/pi_module_bridge_tool_trace_gen6_live_profile_20260914.json（SHA256 100813FBEA9081F64F15CE397E60714C46D18FD13DC8FEA912A13DBE0C98504B）。请求由 ollama/qwen3.5:9b 处理，调用 ID call_x1yipnit，实际 toolCall/tool_execution_end 成功；source-only context ready、missing 为空、source snapshot hash 772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336。结果为 PostProcessMainTI depth-1 的 3/13 条静态路径：DataProcInit、CalEgoCarAddInfo_CR、DotPrePosTI。trace 只存 provider/model、上下文、stop reason、工具参数和结果摘要，不保存 assistant 文本或思考流。

本机 Pi 模型目录未登记 qwen3.5:9b，因此 Pi 将其当作 custom model ID；一次较长 prompt 达到 4096 token 的实际用量并以 stop_reason=length 结束，证据为 outputs/pi_module_bridge_observation_gen6_20260914_no_context_files.json。源码 scope 改用短提示后，实际 RPC 调用在同一用户配置下成功，模型响应停在 2841 token。本轮另运行 python cli.py pi：一条样例完成 code-analyze 并写出 outputs/pi_cli_code_analyze_gen6_20260914.json，但模型没有最终文本；PiModule 现暴露脱敏 pi_event_summary，并只在 source_code 的成功 call_chain 工具结果可结构化提取时返回 answer_mode=tool_result_projection，标记 ai_final_synthesis_status=not_available；没有可用工具结果时返回 empty_final_answer，不误报成功。最新一条 CLI 样例的 RPC telemetry 显示 enabled_tools 仅为 code-analyze、context_prompt 514 字符、source system prompt 172 字符且不加载 context files/skills/extensions；输入 4051、输出 45、总计 4096 token 后 stop_reason=length，没有工具调用。因此该本机 9B 模型的完整 CLI 交互仍受 4096 token 上限影响。未改用户级 Pi 配置；没有调用 Bosch/远端模型。

本轮 tests/test_pi_context.py 与 tests/test_pi_tool_bridge.py 定向回归为 53 passed；全量 python -m pytest -q 为 898 passed, 1 skipped, 2 xfailed, 10 warnings（224.35s），10 条 warning 均为 semantic_memory.table_names() deprecation。这仅提升 Gen6 静态代码检索的 Pi 运行证据；现场 selected-frame、binary/runtime、perception Pi 诊断、P1/P2/P4 仍未验收。
