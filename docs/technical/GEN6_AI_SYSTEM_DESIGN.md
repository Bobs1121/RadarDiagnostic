# Gen6 AI：系统顶层设计

版本：1.0 · 2026-09-16 · 目标设计，当前状态见 [现状与环境](GEN6_AI_CURRENT_STATE.md)。

## 1. 决策与目标

用户已确认：Pi AI 基座、预注册原子工具、按需选择路径；独立分析会话默认；Pi 对话＋实时工作页；三层阶段成果；就绪环境下十分钟分析目标。首期为个人/小范围本地与内网使用，不引入多租户平台或新的总 Agent。

设计以用户旅程为约束：技术事实自动发现，证据自动对应，状态一次持久化，故障从检查点恢复。扩展点服务实际环境/车型变化，避免为泛化而要求用户填写内部 schema。

## 2. 运行拓扑与责任

```text
用户 ←→ Pi 对话 ←→ 案件上下文/意图
                    ↓                      浏览器实时工作页
               Pi RPC 与能力发现              ↕ 查询/用户动作
                    ↓                 本地工作页服务（目标新增）
        generated registerTool → Python bridge → 执行监督边界
                    ↓                            ↓
        当前 BaseTool / BaseModule           授权/幂等/预算/会话
         ↓            ↓            ↓              ↓
   数据/代码引擎    sibling harness    arbe adapter/provider
         ↓            ↓                        SSH/ROS/GDB
         └──────── AnalysisRun + evidence artifacts ───┘
                              ↓
                    同一读模型 → 实时页 / 离线报告
```

本地服务是呈现和用户动作适配器，不进行根因推理，不另存一份业务账本；Pi 仍为唯一总体编排。可以由本地 launcher 管理 CLI/RPC 与页面生命周期，具体组件技术选型服从现有实现、包体和维护成本，不预设重型前端框架。

Linux 承载 arbe 的算法执行和 GDB；Windows/本地承载 Pi、索引/报告等能力；大型 bag 尽量在可用位置处理，只传窗口和结果。实际能力由 provider probe 决定，不要求所有解析必须在同一机器。

## 3. 单一上下文与证据数据流

一次案件保留用户问题、项目/车型/COEM/录制版本、data ref、目标 source snapshot 和环境 profile。AnalysisRun 表示一次可恢复调查；实验 attempt 表示一次具体执行；revision 表示新的事实/结论集合。用户改问题可在同一 run 中新增步骤，改变输入/版本时显式产生新的绑定，旧实验不改写。

数据链：材料→身份核对→数据索引/事件→有界切片→代码/变量映射→实验观察→推理 claim→统一视图。Pi 可跳过、回到或组合任意能力，但证据生产者和消费者必须满足各自身份条件。

文件命名不是身份。至少验证 data bytes、recording layout/version、源码含 dirty 内容、COEM/vehicle、参数配置、binary、host/workspace/session、雷达/目标与时间映射。所需字段取决于结论用途：静态数据查看不要求 binary，runtime 条件必须具有对应执行绑定；不能用全局硬门阻止无关可用能力。

## 4. 执行与调查状态分离

调查状态呈现已知事实、候选、缺口、用户裁决、L1/L2/L3 完成度；它不是强制阶段机。执行状态管理有副作用的 attempt：

```text
planned → authorized → preparing → running → collecting → terminal
terminal = succeeded | partial | failed | cancelled
外加 waiting_user / blocked / connection_unknown 等可解释状态
```

每次转换先落盘 intent，再执行，再确认结果；远端完成不等于产物收集成功，两者分别记录。重连发现执行未知时先 reconcile，不直接重启。取消以可验证清理为完成条件；不会为了“干净”停止非本工具拥有的进程。

现有 AnalysisLedger 提供调查记录基础，不能代替 durable 执行监督。本轮方案是在 bridge/provider 的现有边界补齐执行监督职责；不要求另造名为 RunSupervisor 的大型框架。

## 5. 独立 arbe 会话

首次准备生成来源可证明的隔离工作区/构建 profile；可采用受控 worktree 或复制所需文件，具体由当前仓布局与构建路径约束决定。数据只读共享，禁止默认复制 10 GB 文件多份。构建输出和可变参数独立，避免两个工作区共享实际产物造成版本串扰。

从 source→车型 CUDA/config→编译→binary→ROS 启动→雷达选择→reset/warmup→play/ACK→capture→cleanup 记录链路。模式与实际执行阶段分别证明；启动 API 不存在时不能把 ACK 当控制 API。需要工具组接口变更时交付最小协议与补丁提案，当前授权不足则停在计划。

独立 ROS master、namespace、端口、output root 和进程组需防冲突；能力不支持时禁止假装隔离成功。默认同一可变 workspace/build profile 互斥运行；分析与读取可并行，执行并发必须有资源与状态隔离证明。

正式 GUI 会话为显式模式，核验其 PID/executable/代码/数据；禁止自动打断人工 GDB。隔离与 GUI 输入调度、初始化、预热及输出关系需要 parity 证据，不以相同 binary 自动认定等价。

## 6. 权限与预算

授权对象绑定案件/计划修订、环境、允许动作/文件范围和预算，记录用户来源。UI/模型不能自行声明权威批准；bridge 在调用前验证，provider 在执行边界复核输入状态。批准后路径或身份变化使相关执行失效，不让旧批准覆盖新目标。

分类：只读/本地产物；数据准备与环境操作；仿真调试；算法修改验证。任务可一次覆盖多个动作，范围内自主继续。push/merge、权限/凭据、工具组生产仓发布等始终是独立范围。

预算包含总耗时、模型成本、回放/重试次数、输出大小和资源占用；初值为可配置策略，后续实测调整，不让用户每次填写。确定性错误停止同参数重试，临时故障有界退避；预算将超限时提供已有结果和继续价值。

## 7. 性能与上下文

一次数据索引，多次窗口读取；代码按 hash 增量索引；视频按时间段解码；Pi 读取摘要和 artifact refs；工具 schema 通过渐进发现暴露。短名单应可扩展，不能因关键词遗漏永久屏蔽必要工具。

证据 hash 成本纳入性能，临时 size/mtime 可帮助发现变化但不能冒充关键身份验证。缓存包括 parser/schema/source/DBC/profile 版本；有效签名才复用。大图、trace、点云按帧/块和 byte-range 查询，响应截断必须显式。

分析 wall clock 含其正常索引/模型/额外构建/报告时间，不通过更名 preparation 转移超时。交互更新独立于模型长调用，不阻塞停止、状态查询和已完成成果查看。

## 8. 部署、稳定性与维护

先提供一个受控本地启动入口：体检→恢复运行状态→启动 Pi 与本地工作页→打开案件。配置/provider/SSH 引用一次设置；不在报告中保存 secrets。服务默认仅 loopback，使用会话授权、origin/CSRF 防护和路径白名单，外部网页不可触发执行或读任意文件。未来远程访问需另行设计身份认证。

提供依赖锁和兼容版本矩阵、schema version、adapter health、workspace 磁盘检查。升级前检查活跃执行与契约兼容，保留配置/账本和旧版本恢复路径；不得自动重写用户算法仓。

保留证据与可重建缓存分开。自动清理仅限过期且无活动引用的缓存；案件、原始数据、修改和关键证据不默认删除。磁盘不足先给有用结果与清理建议，不生成半文件后宣称成功。

原始/派生 artifacts 原子写入，运行/产物 ID 防重名，日志带 run/attempt，敏感路径可在分享导出时裁剪。共享报告默认为明确选定的证据摘录，不隐含传送全部源码/视频到模型或外网。

## 9. 历史知识

复用 memory/freshness/knowledge_manifest，variant/customer/branch 隔离。默认不在每案开始全量 Dream；需要刷新时按 scope 执行并记录耗时。成功 scope 单独发布，失败 scope 保持 stale。用户反馈、运行事实、可复用知识三者权限和来源独立。

## 10. 设计决定记录

| ADR | 决定 | 来源/代价 |
|---|---|---|
| G6-D01 | Pi 为唯一总体编排 | U；需限制 bridge 越权并避免工具目录膨胀 |
| G6-D02 | 默认独立分析会话 | 本轮 U；需付出隔离构建/资源管理成本，并验证正式运行差异 |
| G6-D03 | 首期实时页＋对话＋离线导出 | 本轮 U；增加本地服务和动作/状态同步工作，复用 ledger |
| G6-D04 | 证据不覆盖、上下文统一 | 继承旧 ADR 并细化；需要可控 artifact 生命周期 |
| G6-D05 | 按范围授权与自主恢复 | U；需要 durable execution，不只 prompt 约束 |
| G6-D06 | 首期单案例验证、插件扩展 | U；不宣称跨数据集性能改善 |
| G6-D07 | 工作区互斥与局部降级 | D；选择稳定性优先，不把未知执行状态当成功或重新执行 |
