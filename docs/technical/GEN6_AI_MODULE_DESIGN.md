# Gen6 AI：模块与软件设计

状态：目标契约/改造指引；先复用现有模块，本文逻辑接口不是已存在的 API 声明。

## 1. 模块责任与已有代码落点

| M | 责任与既有落点 | 输入→输出 | 本轮需核查/补齐 |
|---|---|---|---|
| M01 案件与身份 | `config.py`、core/workspace、project_init、cr60_intake、pi_context | 用户材料/profile→唯一案件绑定和缺口 | bag+问题直接路径、版本材料解析和冲突业务提示 |
| M02 数据与事件 | parsers、case_loader、cr60_harness provider、point_cloud_replay | 原始数据→索引/事件/窗口/媒体 refs | 四雷达/多事件/无报警；读一次复用，视频索引 |
| M03 代码与映射 | code_context、codegraph、signal_mapper、event_code_path、condition_trace | snapshot+事件→真实符号/条件/数据绑定 | 上游赋值、阶段与时间语义，不把静态推导当 observed |
| M04 Pi 调度 | modules/pi、pi_bridge、capability/registry、pi_tool_bridge、生成扩展 | 问题+上下文+能力→调用/推理/下一步 | 非固定关键词工具发现、上下文预算、追问继承与缺口补证 |
| M05 调查记录 | engines/analysis_ledger、analysis_collaboration、feedback_review | 工具/用户/模型事件→run/steps/claims | 统一动作入口、当前选择/修订、恢复和错误权威 |
| M06 执行监督 | bridge+module_bridge+arbe/execution_binding，provider | 授权 plan→attempt 状态/审计 | durable 授权、幂等、poll/cancel/reconcile、互斥与预算 |
| M07 环境与仿真 | arbe source/cuda/patch_plan/build/preflight/remote_replay，sim_verify | 环境计划→source/config/binary/session/capture | 隔离工作区与正式会话分离，模式/预热/ACK 实证 |
| M08 取证与关联 | gdb_service/runtime_debug、public_runtime、runtime_evidence | 当前实验→分层 observations/relations/gaps | 同帧/作用域绑定、多阶段值、采集扰动与失败恢复 |
| M09 修复验证 | code_fix_engine＋M06/M07/ledger | 可行动发现+标准→diff/构建/回灌/比较 | 建议与真实 apply 分开；原版保留、验证标准修订和回退 |
| M10 页面与报告 | analysis_workbench、diagnostic_report、viewer；目标新增本地服务 | 同一 run 读模型→实时页面/离线包 | 动作回流、增量更新、联合选择、媒体/源码/曲线联动 |
| M11 知识 | memory、auto_dream、knowledge_guard、feedback publication | 新鲜度/反馈→可用知识 refs | 只按 scope 发布，不将用户反馈直接变事实 |
| M12 交付运维 | doctor、release_smoke/gate、依赖锁和配置 | 环境/版本→健康、安装/升级与证据 | 干净机器上手、生命周期、故障支持包与缓存维护 |

## 2. 契约沿用与演进

沿用 `analysis-run.v1`、`analysis-step.v1`、`claim.v1`、`hypothesis.v1`、`debug-experiment.v1`、`user-observation.v1`、`code-context.v1`、`code-index.v1`、`event-code-path.v1`、`gdb-session.v1`、runtime/point-cloud/perception、diagnostic-report、analysis-workbench 等现有契约。

仅在现有模型无法表达独立责任时新增契约；先字段兼容扩展，再评估版本升级。新增枚举需旧 reader 明确 unknown，不静默认作 ready。迁移提供 old fixture、schema validator 和生产消费方测试。

模块 run 返回 ModuleResult，区分 ok（调用是否有效）与业务状态（ready/partial/blocked/failed）。调用成功但没有证据不能升级 ready。缺字段返回明确原因和可能补救，不抛未捕获异常或默默吞错。

## 3. 执行请求逻辑字段（拟议）

`request_id / run_id / expected_revision / action / target_scope / plan_ref+hash / approval_ref / input_bindings / budget / output_root`。

- request_id 由可信调用边界生成并贯穿，重复提交返回已有 attempt。
- plan 与输入在授权时冻结，执行前采样复核；授权源必须是用户动作，不能由模型自行生成 authority。
- 同一个 attempt 持久化 intent、启动凭据、PID/process group、远端结果、采集结果、清理结果和错误分类。
- 数据采集重试与算法重跑区分；已完成回放但 fetch 失败只重取产物，不能重复 replay。
- 当账本无法写入时，只读查看可降级；影响授权/执行幂等的关键状态不可丢失，禁止继续新副作用。这比现有部分 observability-only 异常处理更严格，需审计落点。

## 4. 工作页读写边界（拟议）

只读操作：读取 run 摘要/修订、步骤增量、事件分页、有界证据、代码片段、媒体窗口、对比报告。

用户动作：改变关注点、发送追问、反馈/工程裁决、批准/撤销未开始动作、取消、恢复、导出。动作统一映射到当前 run 的既有 Pi/ledger/执行入口，不在 Web 层直接运行算法或 shell。

更新采用 revision/cursor；SSE 或短轮询是实现选项。客户端断线从 cursor 恢复，重复事件不重复显示，状态竞争用 expected_revision 检查。选择态是 UI 上下文，不改变证据身份；用户选中失效证据时显示历史而非覆盖当前事实。

媒体只允许访问已登记 artifact 的范围，路径 canonicalize 并限制 roots；源码片段按 snapshot+symbol/ref 提供，不暴露任意文件读取接口。页面文本、代码和用户内容必须转义，外部文档内容不执行为控制指令。

## 5. 变量和因果证据绑定

逻辑链：raw field→decode/scale→坐标/单位变换→算法输入→copy/write→局部/跨帧状态→condition→output。每条边有 source ref 与证据等级；未知边保留 gap。符号名相同、时间相近、值碰巧相等都不是绑定证明。

Observation 需要保持作用域/采集阶段，数组位置和稳定 ID 不混淆；同帧不同断点值可不同。Condition evaluator 只处理支持表达式且具有有效依赖的情况；其他转 runtime probe 或 unknown。AI 可以提出映射假设，但验证前不进入 observed 绑定。

Claim 引用关键链路与反证。代码符合预期但需求不明确可交付技术解释并等待用户裁决，不要求生成补丁。没有足够变量/实验支撑的定位不能作为自动 apply 的依据。

## 6. 修改和比较协议

验证计划先于修改：绑定 baseline 输入、source/config/binary、问题窗口、同 bag 对照窗口、指标和标准来源。建议包含 diff、目的、影响和风险；实际应用先核对 baseline hash 和干净隔离区域，不覆盖用户未提交改动。

编译产物和试验 run 独立身份；更改模式/初始化/输入时不能仅比较报警数量宣称改善。比较保留 exact/derived/unbound 关系、不可比原因、输出时序及目标质量。失败 patch/构建/回放留在 attempt 历史，用户恢复使用记录的原始快照/逆向差异，先检查外部修改冲突。

## 7. 跨模块失败传播

| 错误类 | 消费行为 | 重试 |
|---|---|---|
| identity_conflict / stale | 阻断相关 join/执行，保留无关证据 | 重新解析/刷新后新计划 |
| unsupported / missing_evidence | 查询替代来源或返回 gap | 同参数盲重试无益 |
| transient_transport / model_unavailable | 保存阶段产物，恢复会话/取回结果 | 预算内有界重试 |
| execution_unknown | 先查 PID/session/result | 禁止直接重复动作 |
| budget_exceeded / cancelled | 收集已有成果并清理 own resources | 新授权/用户继续后再执行 |
| artifact_corrupt / disk_full | 不发布半产物；保留索引和错误 | 排除资源问题后原子重写 |

## 8. 扩展接口

新车型配置通过 profile/adapter 引入，数据格式通过 parser plugin，运行环境通过 provider，面板通过同一读模型扩展。其他数据集回归未来复用验证计划和批次结果，不复制 Pi 或建立第二份报告真值。模型 provider 可替换，但更换模型不能丢失 run、授权和证据等级。
