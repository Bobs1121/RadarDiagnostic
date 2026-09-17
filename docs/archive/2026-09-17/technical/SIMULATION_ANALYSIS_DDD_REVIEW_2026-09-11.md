# 自主仿真与分析：设计复核及开发收口基线

> **归档：2026-09-17。本文仅保留历史设计/证据，不再是当前开发指令。当前唯一套件见 [DDD 入口](../../../technical/GEN6_AI_DOCUMENT_INDEX.md)。**


日期：2026-09-11。最后状态更新：2026-09-14。状态：`reviewed / remediation-in-progress / perception-e2e-unverified`。

本项目 DDD 指 Document-driven development（文档驱动开发）。本文件补充并约束既有 [需求与验收基线](CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md)、[点云方案](POINT_CLOUD_PERCEPTION_DDD_PROPOSAL_2026-09-10.md) 与 [设计决策](V4_DESIGN_CONTEXT_AND_DECISIONS.md)，不重编号 US-027～US-032、PC-AC-01～12。审查对象为当前未提交工作树；本次没有执行远端回放，历史现场记录不视为本轮验证。

## 1. 结论与产品目标

目标保持为：用户给出问题、rosbag 和代码/项目材料，Pi 自动选择原子工具，完成可恢复的仿真与调查，输出结合实际值、源码和需求的证据报告；准确性先于推理速度优化，同时持续测量耗时与上下文成本。

方向合理，落实不完整。Engine / BaseTool / BaseModule / Pi 分层、variant freshness、evidence provenance 和 ledger 值得保留。当前开发偏重 artifact/schema/validator 的数量和本地合成测试，真实执行、采集、AI 消费和报告交付之间仍有断点。不能把当前状态描述为“仅待一次批准便完整闭环”。

已有目标注入/公共 ROS 输出路径和静态报告能力，但尚未证明从一次自然语言请求到真实点迹感知重算、逐阶段证据、源码推理、离线报告的完整产品流程。历史源码显示 HILMODEL=0 存在前级感知调用路径；编译宏或计划 ready 不能证明对应二进制实际执行了这些阶段，也不能证明 ADAS 未消费被替换的录制目标。

这里的感知仿真范围是录制点迹进入后处理、过滤、聚类、跟踪与输出。ADC/FFT/CFAR 等前端能力须另有原始输入及可执行入口，不能由 dotTrans 推导支持。

## 2. 当前工作树证据与影响

以下是代码检查发现；没有将静态检查标成现场复现。修复时须针对具体行为建立回归证据。

| 编号 | 当前代码入口 | 发现与影响 | 优先级 |
|---|---|---|---|
| F01 | `ai/modules/pi.py::_select_pi_tools` | 当前选择逻辑没有把 point-cloud 能力纳入正常意图分派；注册成功不能代表普通 Pi 会话能够调用并串联这些能力 | P1 |
| F02 | `engines/arbe/remote_replay.py::_PUBLIC_CAPTURE_EXTRACTOR`、`ai/modules/sim_verify.py` | 采集解析覆盖 warning/radar_info/objectlist/ROI，未覆盖 PointCloud2/cluster MarkerArray 与阶段 trace；录制额外 topic 不等于 JSON 证据和感知报告已有这些数据 | P1 |
| F03 | `engines/arbe/remote_replay.py` | 基于已有 session 和时长播放，不等价于独立 reset、连续 warmup 和算法实际处理完成确认；计划字段尚不能证明执行。按 0.066 s/帧估算，175 帧约 11.55 s，4 s 播放不足以满足该预热声明 | P0/P1 |
| F04 | `ai/modules/sim_verify.py`、`engines/arbe/execution_binding.py` | 复核仍可读取原 preflight JSON；显式 source_context_id 与当前 binary 信息可能来自不同采样；源码 dirty 内容、配置实际字节和目标 host/workspace 等需要统一绑定并在执行边界实时复核 | P0 |
| F05 | `tools/decode_lgu_output.py` | DOT_STRUCT 尾部全按 signed byte 解码，与当前参考头文件中的部分 uint8 字段不符；按载荷长度倒推点迹起始位置及固定对象布局缺少录制版本证明。已有点数属于该解码实现的结果，不能自行证明字段准确 | P0 |
| F06 | `engines/point_cloud_replay.py` | input contract 缺失、部分 runtime/injection unknown 的情况下仍可能获得 ready；阶段计数/status 不能替代 producer 命中；没有假设时不应自动生成 supported_hypothesis；两个 identity 字符串不能自行证明 freshness | P0 |
| F07 | `engines/point_cloud_replay.py` | PointCloud2 解码须完善字段边界、point_step/row_step、截断、非有限值及部分失败语义；捕获 struct.error 并返回空值不能同时声称该字段 observed | P0 |
| F08 | `ai/modules/point_cloud_batch.py::_html_index` | 链接字符串再次 HTML escape 导致无法点击；百分号格式化模板仍保留双花括号 CSS；清洗后重名目录可能覆盖。字符串包含测试不能代表离线报告可用 | P2 |

既有报告中的 `36591` 点迹和 `3200` objTrans 对象，是历史解码/录制层结果，不能改称本次感知回放输出。没有独立校验的录制版本、布局、单位和枚举，数量正常不足以证明值正确。历史 topic-name 扫描未发现 point topic，也不能证明 LGU 载荷没有点迹。

## 3. 收口后的架构职责

```text
用户问题 + bag + 项目材料
  → Pi：理解目标、检索能力、选择调查锚点和下一步
  → intake/source/input audit：生成可验证的输入和身份
  → execution plan/binding：冻结执行范围与来源
  → replay adapter：reset → warmup → replay → completion → cleanup
  → producer/parser：输入、阶段、输出及 lineage 证据
  → evidence query + code context：围绕问题提供小窗口事实
  → Pi：假设排序、冲突解释、区分实验、结论综合
  → diagnosis-report：统一报告及离线附件
```

这是职责关系，不是强制固定诊断流水线。Pi 可选择静态分析、信号查询、目标注入、感知重算或增量实验。确定性状态机仅管理一次执行的生命周期、超时和资源清理，不负责根因判断。

| 模块责任 | 复用与改造范围 | 禁止扩张 |
|---|---|---|
| Pi 编排 | `ai/modules/pi.py`、catalog、既有 bridge；按问题渐进加载能力并保留 run 上下文 | 为点云再建一个独立总调度器，或仅靠几个关键词永久屏蔽能力 |
| 身份与新鲜度 | execution binding、source context、knowledge guard；source dirty bytes/config bytes/binary/data/host/workspace/profile 共同绑定 | 用 manifest 存在、相同名称或自报 ready 代替当前输入校验 |
| 执行 | `engines/arbe` 与既有外部 harness adapter；管理 reset/帧完成/退出/attempt | 在分析模块复制 SSH、ROS 或生命周期脚本 |
| 数据与证据 | 版本化 parser profile、现有 runtime evidence 与有界查询 | 近邻匹配标为 observed；将录制目标作为重算目标 |
| 推理 | Pi + 当前代码检索、条件证据和需求；提出最多三个有区分价值的候选 | 用条件通过数量直接确认根因，或强行补满三个假设 |
| 展示 | 扩展 `diagnosis-report` 与现有 viewer，共享选中帧和附件引用 | 每个 artifact 再生成一套报告系统 |
| 知识 | variant/customer/branch 隔离；freshness 验证后召回；Dream 按成功 scope 发布 | 把历史案例写成当前 observed，或退回其他 variant 的 L6 |

原子工具应有明确输入、单一有界责任、ModuleResult、错误与部分成功语义、provenance 和成本记录。长任务以 run/attempt 为恢复单元；优先扩展既有契约，只有出现独立生产/消费责任才新增 schema。审批沿用已授权的执行范围，artifact 缺少 approved 字段本身不构成重复询问理由；真正扩大副作用范围时再以业务语言确认。

## 4. 开发顺序与完成定义

| 阶段 | 工作包与责任模块 | 交付验收 | 依赖 |
|---|---|---|---|
| P0 准确性收口 | LGU/PointCloud2 parser、execution binding、plan/status；修 F04～F07 | 独立来源的二进制 fixture/人工核验；signed/unsigned、版本冲突、截断均有正确语义；修改 dirty 内容、配置或目标 workspace 后失效；analysis-ready 与 execution-ready 可区分；未知不阻止静态分析但不允许无依据的执行/结论升级。对应 PC-AC-01/02/08 | 先完成 |
| P1 单案例真实闭环 | Pi 选择、sim-verify、远端 adapter、stage producer；修 F01～F03 | 一次 Pi 请求完成真实输入→独立 reset→连续处理→完成确认→阶段采集→证据查询→报告；证明感知阶段执行及目标未被注入覆盖；实际帧数和丢帧可核查。对应 PC-AC-03/04，并覆盖 05/07 的最小路径 | P0 |
| P2 联合推理 | Pi、code context、evidence query、ledger | 真实模型消费 P1 证据；每项假设引用 artifact/代码和反证、缺口、最小区分实验；无报警/未检出也能调查；lineage 缺失不伪造。对应 PC-AC-05/06/07/08/11/12 | P1 |
| P3 报告与批次 | diagnostic-report、viewer、batch；修 F08 | 相同选中帧驱动点/簇/航迹/代码；离线打开能点进每项报告；好/坏/空/无报警混批独立出结果，重名不覆盖、失败可恢复。对应 PC-AC-09/10 | P1；完整推理交付依赖 P2 |
| P4 泛化与速度 | parser profiles、variant freshness、索引/查询缓存、成本观测；本地 prewarm 计时应支持隔离 `source_docs` 冷/热目录 | 第二套不同输入/代码配置验证隔离；对比冷/热启动、回放、解析、检索、LLM、报告的 p50/p95、峰值内存、读取字节和 tokens；所有缓存命中都满足当前签名 | P0～P3 |

P0 中互不依赖的本地缺陷可分别修复；P1 最小闭环以前，不以增加新 manifest/validator 数量作为里程碑进展。阶段交付必须更新同一张验收表，禁止仅新增 handoff 宣称完成。

### 开发开始条件（DoR）

- 绑定一个既有 US/PC-AC，写明用户可观察的前后行为、模块责任与非目标。
- 明确输入来源、版本/单位/枚举、身份与副作用；不能自行获得的业务口径才向用户提问。
- 提供失败和部分成功预期；定义用哪条真实数据或独立 fixture 检验，避免测试只复制实现公式。

### 开发完成条件（DoD）

- 代码、相应 AGENTS/API/schema、需求验收状态一致；保留并检查其他工作树修改。
- 相关回归通过，失败路径可解释；接口测试、真实执行验收、浏览器验收分开记录。
- 保存命令/输入 hash/source/config/binary/producer/输出路径和结论限制；缺少证据的 AC 继续 pending。
- 准确性测试包括：多 radar、frame wrap、ID 复用、空帧、截断、版本错配、配置变化、倒放/跳帧、超时/中断/重试、预热收敛和目标来源。
- 性能优化须有前后测量和相同正确性基线；不得通过丢失必要帧/字段来换取更快的表面耗时。

## 5. 验收记录与当前发布口径

沿用原 PC-AC 编号，后续每项记录：`AC ID | 当前实现 | 测试级别 | 输入/身份 | 证据路径 | 结果 | 缺口 | 下一工作包`。测试级别区分 `unit/contract`、`integration`、`real-replay`、`Pi-product`、`offline-browser`，不可相互替代。

当前可以描述为“已有本地感知分析契约与报告原型，目标注入/公共输出回放有历史证据；完整自主感知仿真待修复并验收”。此前 `implementation-slice-4-verified` 只表示当时局部检查，不是 PC-AC 全量通过；`ready` 不等于执行成功，`observed` 不等于根因确认。

初始审查时没有重新运行测试、远端构建或仿真；后续实现已按第 6 节修复一批控制面问题。真实远端构建和回放仍未执行，下一可交付产品里程碑仍为 P1 的真实单案例闭环。

## 6. 本轮实现进度（2026-09-11 continuation）

本轮已经落地的 P0/P1 控制面改造如下：

- Pi 感知意图会把 `point-cloud-plan/analyze/validate/batch`、`sim-verify` 和 execution binding 纳入 live allowlist。
- `point-cloud-plan` 缺少输入 contract、server target、输出 topic、注入状态或完整身份时保持 `blocked`；175 帧按 `0.066 s` 估算时，4 秒窗口会被识别为不足。
- preflight 记录 outer/algo dirty 内容及 launch config sha256；binding 检测显式 source/config 与当前 preflight 冲突，执行计划包含 server/user/port。
- LGU decoder 改为 `<hhhhbbbBBBBB` 混合布局，使用固定 `dotTrans` 前缀，不再按载荷尾部倒推；PointCloud2 对 row/field 边界和截断返回显式错误或 partial。
- 远程公共采集器可按内容输出 LGU point、PointCloud2、MarkerArray、objectlist 的结构化行和阶段计数；缺少 producer-owned reset/warm-up/completion ACK 时 `sim-verify` 保持 `partial`。
- 批次索引链接、CSS、清洗重名目录已修正，避免生成不可点击或互相覆盖的离线报告。

这些改造强化了准确性和 fail-closed 语义，但没有把公共 topic 采集升级成私有阶段 trace，也没有执行远端 replay。当前验收仍为：本地 P0/P1 控制面可测；真实 HILMODEL=0 构建、阶段 producer、reset/warm-up ACK、完整 lineage、第二异构项目和真实 Pi 端到端仍 pending。

截至本轮现场只读刷新，已生成一份可审查的执行前材料：`outputs/arbe_preflight_p0_runtime_20260911.json`、
`outputs/source_context_p0_runtime_20260911.json`、`outputs/point_cloud_plan_source_bound_20260911.json`、
`outputs/point_cloud_execution_binding_pending_20260911.json`。该计划针对 `_0909int` workspace，
输入 `/wf/corner_radar/lgu_data_2`，输出 PointCloud2/MarkerArray/objectlist 五个公共 topic，
预热 175 帧、窗口 12 秒；所有输入、HILMODEL、注入、topic、runtime workspace 和五项 identity gate
均已通过，binding 明确为 `approval_required`。只有用户批准后才允许调用 `sim-verify --execute --approved`；
该调用会启动远端公共录制/回放并改变 ROS 运行态，因此本轮没有代为执行。即使执行成功，公共 topic
输出仍需 producer-owned reset/warm-up/completion ACK 才能升级为完整感知结论。

## 7. 2026-09-13 continuation：公开回放结果与 report/Pi 查询收口

前述 §6 是 2026-09-11 执行前状态。其后用户批准了一次隔离的公共回放；当前权威工件为
`outputs/sim_verify_point_cloud_remote_20260911.json`（provider `completed`）和归一化派生件
`outputs/sim_verify_point_cloud_remote_normalized_20260911.json`（`partial`）。运行仍缺少
producer-owned reset/warm-up ACK，因此不能把 ROS bag 录完或公共输出存在说成完整感知 run。

基于当前源码快照 `outputs/source_snapshot_runtime_20260912/` 重新绑定后，最新报告位于
`outputs/point_cloud_remote_report_source_bound_20260912_inline200_indexed/perception-report.json`，完整 lineage
在同目录 `perception-lineage.jsonl`，callback 索引为 `perception-lineage-index.v1.json`。报告状态
`partial`、validation `valid_with_warnings`；source
contract 为 `source_verified`，180 组公开 PointCloud2/objectlist callback pair 按源码 publication order
关联，未借用原始 LGU frameID。捕获 31,440 个 PointCloud2 公共输出点；按公开 `cluster_id` 形成
10,576 个簇节点，3,260 个有效轨迹/输出对象，40,257 条 `derived` lineage edges。选中 callback
`0ce8db9037eb0f4d79550e4e9bfc10ebbdf59e3aecb07e860bb3b640ddbcc8ce:radar2:callback:13-14` 的同帧投影为
174 点、58 簇、2 轨迹和 2 输出，切片含 161 条边。

当前仍只有 2/8 runtime-observed stages；4 个阶段来自源码绑定的 derived evidence，`input_decode`
不可用，run/reset/warm-up 不完整，私有中间 trace 与 ADAS warning 输出没有采集。以上边和阶段计数
不能证明过滤拒绝原因、关联矩阵、历史 ID 延续或根因；PC-AC-03/04/06/07/11/12 仍不能标 accepted。

为修复 Pi 将内嵌前缀当成全量的风险，`perception-report.v1` 默认只内嵌 200 行，超出后附带 hash-bound
JSONL 与 `perception-lineage-index.v1.json`。`point-cloud-read` 按 callback byte range 读取，核对
index/block SHA-256、文件大小、行数和 record-type counts；summary 与 Pi anchor 使用全量
`node_counts/edge_count`。该真实样例的报告 JSON 为 6,345,358 bytes，完整 lineage JSONL 为
100,072,691 bytes，索引为 76,241 bytes，完整点迹仍保存在 `perception-points.jsonl`。若大型分析没有
给 `output_dir`，会自动生成唯一的 `outputs/point_cloud_analysis/run-*` 目录。

对同一 129,050-row/100 MB lineage 工件，本机 3 次本地读取的初步对比为：全文件扫描/hash
P50/P95 `0.9779/1.0254 s`，索引切片 P50/P95 `0.0489/0.1405 s`；两种路径返回的节点数和 161-edge
callback 结果一致，Pi tool result 约 `97 KB`。这是一个样例的本地初步测量，冷/热缓存未隔离，未形成
性能发布阈值或多格式 P50/P95 验收。

Pi 显式 `context_path` 下先载入上下文再注入 deterministic evidence anchor；system prompt 禁止从截断
数组推总量。最新 Pi 复验 `outputs/pi_point_cloud_analysis_runtime_20260913_final_report_v6.json` 的
`context_status=ready`，总量和 callback 计数分别与 anchor/read slice 一致，reset/warm-up/input_decode
缺口仍正确呈现。这验证了 report-read 路径，不代表 Pi 从自然语言发起并完成了点迹回放、私有阶段追踪
或根因复验。

同一报告的 HTML 现在有可切换点迹/簇层、精确 point/cluster 列表和 track/output 属性面板；点击 PointCloud2
row 与 cluster centroids 可展开完整 source/data 字段，track `ID=43` 按精确 `track_id` 高亮 1 个点迹，
不做坐标系未经验证的空间叠加。每个 selected-frame stage 行显示 exact callback 计数；layer availability
表将缺少的输入/过滤/候选轨迹/ADAS/comparison/inference 明确标为 `not_available`。报告目录附带
`perception-report-README.md`，用仅绑定 localhost 的
Python 静态服务器离线打开。`outputs/offline_browser_verification_20260913.json` 记录了本地 HTTP
验收、point/cluster/track 点击与 `0 errors/0 warnings`；整份 bundle 复制到临时目录后，relative JSONL/index
引用仍能查询 selected callback。file:// 协议不在交付约定中；经 README 指定的 localhost-only workflow
验收后，release manifest 将 PC-AC-09 记为 `accepted`。

截至 2026-09-13，最新全量本地回归 `python -m pytest -q` 为 `853 passed, 1 skipped, 2 xfailed, 10 warnings`
（204.78s）；`python tools/release_gate.py` accepted（10/10 required entries），`doctor` 为 `ready`、
catalog 64、lock mismatches 0，`git diff --check` 无 whitespace error（仅 CRLF conversion warnings）。
真实回放仍处 `partial`，其他尚未验收项不因本地 release gate 通过而升级。

## 8. 2026-09-14 remediation follow-up

以下状态是对 F01～F08 的当前代码/测试复核。它不把本地 fixture、旧 replay 或公开 topic 派生计数改称新的现场 runtime 证据。

| Finding | 当前本地处理 | 仍缺的验收证据 |
|---|---|---|
| F01 Pi allowlist | `ai/modules/pi.py::_select_pi_tools` 在普通交互会话保留 bounded perception starter；`PiModule.run` 把普通中文目标未检出/消失问题路由为 Pi 工具 allowlist 并经 `_build_bridge` 传给 `PiBridge`（`tests/test_pi_tool_bridge.py` 定向 `28 passed`），`sim-verify.analysis_handoff.analysis_inputs` 可直接交给 `point-cloud-analyze` | fake-provider handoff 集成只证明控制面串接且缺 ACK 仍 partial；`Pi-product` 真正的一次自然语言请求、工具调用轨迹及报告仍未复验 |
| F02 capture/parser | 公共 PointCloud2/MarkerArray/objectlist 按消息结构解析；运行输出和私有阶段 trace 仍分层标记 | 过滤/关联内部 producer 及阶段命中需真实运行时采集 |
| F03 lifecycle | `perception-run.v1` completed 必须有 `run_id`、`attempt_id`、`plan_hash`、observed/completed frames、reset 和完整 warm-up；SimVerify 写出可传给分析器的 run sidecar | fake-provider handoff 测试保持无 ACK run 为 partial；当前远端 producer 仍没有 reset/warm-up ACK，独立连续回放未复验 |
| F04 identity binding | analyzer 比对 capture 与显式 source context；capability freshness 要求 ready plan 与 completed run 的五项 identity 一致并 runtime workspace aligned；矛盾会 blocked。BYD_SC6H 本地静态 code context 绑定了外层/adas dirty identity 和 COEM Tx mapping，但显式标为非 runtime-bound | 远端当前 preflight 无法刷新；新的 target identity/实际执行仍需现场证据 |
| F05 LGU layout | decoder 将 source-header verified 与 recording compatibility 分开；精确 recording SHA、录制版本和 hash-bound compatibility 文件缺任一项时不标 `layout_verified` | 现有历史输入缺录制版本兼容证明，仍需独立 recorder/source fixture 或人工核验 |
| F06 readiness | `input_contract` 原始 `dotTrans` 记录要求 source+recording binding；capability、analysis 与 report validator 不再凭非空 identity 字符串升级 ready | 真实 plan/run/stage producer 尚未共同提供一致、可审计的完成证据 |
| F07 PointCloud2 parser | 保留 field/row/step 边界、截断、非有限值和 partial 状态测试；读到不完整字段不会标为 observed | 第二种消息定义/recording version 的真实样本待 P4 |
| F08 batch/report | 批次链接、碰撞隔离与离线 viewer 已有浏览器验收；新增的 identity/layout warning 面板通过 `outputs/offline_browser_verification_identity_audit_20260914_v3.json` 离线复验，0 console errors/warnings | 这是离线渲染验收；完整自然语言→真实 replay→report 仍 pending |

2026-09-14 的历史 LGU 解码输入产生本地审计报告 `outputs/point_cloud_lgu_report_identity_audit_20260914/perception-report.json`，SHA256=`a399007ff98ecae39cc112ab42f081a5b61f96711f8b803edb404e443de010f4`。它记录原始 artifact SHA 与 source-context `data_fingerprint` 不同、capture/显式 `source_context_id` 冲突，`layout_status=conflict`、capability=`blocked`，而且仍保留 partial 静态投影。后续 v3 报告 `outputs/point_cloud_lgu_report_identity_audit_20260914_v3/perception-report.json` SHA256=`20fc4d2364d995ec7a81fd5ce206d421092fd5fe4695248be299cd0afa9326ab` 保留相同 fail-closed 结论；`outputs/offline_browser_verification_identity_audit_20260914_v3.json` 绑定 report/HTML hash，确认 Input contract 面板能读到冲突，console errors/warnings 为 0。这个冲突意味着输入不能作为版本绑定的重放数据。

当前可完成的本地回归和 P0 控制面 fail-closed 修复继续推进；P1 真实单案例闭环、P2 真实模型联合推理、P4 第二项目/冷热门槛仍未完成。当时最新只读 preflight `outputs/arbe_preflight_p6_refresh_20260914.json`（SHA256 `44733e05a134d4be38b89891edd532887d67b22d4fd553dedbe666c3eaf5b4d5`）对 SSH port 22 的 5 秒探测返回 `124/timed_out`，其余 22 项跳过；当前远端 source/binary/runtime PID 未知。`outputs/code_context_byd_sc6h_crossrepo_static_20260914/` 是本地 BYD_SC6H 跨仓静态源码快照，明确 `runtime_binding=not_available`，不补远端 identity。本轮未执行远端 build、replay 或 GDB attach。

2026-09-14 最后一次全量回归（本次 source-context mapping 代码改动前）为 `873 passed, 1 skipped, 2 xfailed, 10 warnings`（`617.83s`）；本次改动后 code-context/event-code-path/code-gdb-plan/project-capability/product-capability/release-acceptance 定向套件 `41 passed`，Pi 桥接套件 `28 passed`。release acceptance 测试内实际运行 manifest evaluator，验证 `10/10` required entries accepted；doctor M3 校验通过。manifest 21 条验收项引用的 175 个 evidence path 均存在；只读远端状态当前因 SSH timeout 不可用。该结果只证明本地回归与发布门，不提升仍缺真实 replay/Pi-product 证据的 AC。

## 9. 2026-09-14 Gen6 代码检索与 debug 准备续验

在当前 BYD_SC6H 静态 index 上，`code-analyze` 列表查询默认返回上限 200，允许显式设为 1～5000；`result_bounds` 精确标注总数与截断状态。`PostProcessMainTI` 的 `max_depth=5` 查询有 754 条路径，Pi 结果限定为 200 条且标记 `truncated=true`；入口 `max_depth=1` 的 13 项与 `FrontCrossTrafficAlertAndBrake` `max_depth=2` 的 28 项查询完整返回。证据为 `outputs/code_chain_gen6_postprocess_bounded_20260914.json`、`outputs/code_chain_gen6_pipeline_entry_20260914.json` 和 `outputs/code_chain_gen6_fcta_path_20260914.json`，均绑定 source snapshot `772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336`。静态 GDB plan `outputs/code_gdb_plan_gen6_static_20260914.json` 给出 `postProcess.c:170` 函数入口断点和 `bt 5`/`info args`/`info locals` 命令；它没有执行 attach 或证明断点命中。

最新只读刷新 `outputs/arbe_preflight_p8_refresh_20260914.json` SHA256=`ef6551e3db994649a598bde54cd6af5632cb0d12f5b5db7c475c3b7e02740265` 在 `5.047s` 后返回 `124/timed_out`，22 个远端探测短路，source/binary/runtime PID/GDB 仍未知。本轮未执行远端 build、replay 或 GDB attach。

本轮定向回归 `tests/test_code_analyze.py`、`tests/test_product_capabilities.py`、`tests/test_pi_tool_bridge.py` 为 `48 passed`；新增 `test_pi_bridge_preserves_bounded_code_analyze_results` 验证 bridge 保留截断计数，`test_pi_plain_symptom_flow_can_execute_bounded_code_analyze_through_bridge` 用 fake provider 验证普通目标症状 allowlist 经 `invoke_capability` 返回 4/12，`test_pi_bridge_cli_executes_bounded_code_analyze_json` 验证 Pi CLI JSON 边界返回 3/12；这些测试不代替真实 Pi model/product 验收；`python tools/doctor.py --json` 为 `ready`、64 项能力、无 lock mismatch/doctor failure；更新后的 `python tools/release_gate.py` 接受 `10/10` 必需项。本轮全量 `python -m pytest -q` 为 `887 passed, 1 skipped, 2 xfailed, 10 warnings`（`204.63s`）；10 条 warnings 是 `semantic_memory.py::table_names()` deprecation。本地全量通过仍不提升 P1/P2/PC-AC 现场状态。新的 query bounds 改善本地 Gen6 source lookup 上下文规模，不改变 P1/P2/PC-AC 现场验收状态：PC-AC-01/09/10 accepted，其余仍 partially-verified。

## 10. 2026-09-14 Gen6 source-definition binding and report UI

`_bounded_code_context()` now reads the 29.6 MB CodeIndex once, selects exact stage names and direct caller/callee neighbors, and returns explicit matched/missing function names. One local query projection measured `5.219s` before and `0.176s` after this change; this is a single-run indication, not a P4 p50/p95 performance acceptance. For the current 43-file BYD_SC6H snapshot, per-file SHA-256 comparison confirms the CodeIndex and stage map use the same file set/content (`same_file_snapshot`, 43 matched, no mismatch). Source-map token occurrences/declarations/call sites are shown separately from CodeIndex function definitions at `DotFilter` `dotFilter.c:2226`, `ObjCluster` `cluster.c:818`, `ObjTrack` `track.c:16119`, `OutputTrkObj` `track.c:15853` and `AdasFunc` `adasFunc.c:11148`. Each stays a static `source_candidate`; the report does not state runtime execution.

The Gen6 static report is `outputs/gen6_static_code_flow_20260914/`, report SHA256=`fe44dbe1d4e428be08bc686a7a91f9fdb0528be2ccc0efa02a20ac8576dfd97e`, HTML SHA256=`10ebe317ea1cb3731b2a5f5c1ea2d5b8fd3791682f47f20b7047a840f86598dd`. With no recording input, report status remains `blocked`, input boundary `not_available`, validation `valid`, and all runtime proofs are `not_available`. The HTML uses Chinese primary labels, collapses full JSON details, and keeps source candidates and function definitions in separate columns. Offline browser record `outputs/offline_browser_verification_gen6_static_code_flow_20260914.json` confirms HTTP 200, title, 8 stage rows, definition column, collapsed input details and 0 console errors/warnings; screenshot is `output/playwright/gen6_static_code_flow_20260914.png`. This establishes local source-map rendering only; a separate bounded code lookup through the actual local Pi tool loop is recorded in §11. PC-AC-03/04/07/08/11/12 remain `partially-verified` until selected-frame recording, runtime trace, binary/config identity and perception-level Pi-product evidence are available.


## 11. 2026-09-14 本机 Pi 调用与现场连通性续验

以本机 Ollama endpoint `http://localhost:11434/v1`、Pi `0.84.4` 和自定义模型 ID `qwen3.5:9b` 运行仓库扩展。Pi JSON event stream 记录了真实 `code-analyze` `toolCall`/`toolResult`；`--offline`、`--no-session`，仅显式加载 `.pi/extensions/radar-capabilities.ts` 且只开放 `code-analyze`。有界结果 `outputs/pi_local_code_analyze_gen6_20260914.json` 的 SHA256 为 `F30B36264FCA6762533350135CB4463159AFCC681977F4D1171587A03E412281`；脱敏运行摘要 `outputs/pi_local_tool_trace_gen6_20260914.json` SHA256 为 `00f1606c231cec64105e2d000b9c71c3cb0386b4075b35262f4813df3cdfd4d3`。结果是 `PostProcessMainTI` depth-1 的 3/13 条路径，source snapshot hash 为 `772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336`。这验证本机模型实际驱动一个 read-only Gen6 capability，不等同 perception 联合推理或现场 runtime。

只读刷新 `outputs/arbe_preflight_p9_refresh_20260914.json`（SHA256 `053fbdb55f50b8293a02879f5e3868d888e82bc306465e2c3127e2b42025ed16`）的 SSH 探测在 `5.031s` 返回 `124/timed_out`，22 个后续 probe skipped；preflight connectivity probe 的设计上限为 5 秒，单独将 OpenSSH `ConnectTimeout` 设为 15 秒也连接超时。远端 source/binary/runtime/GDB 状态未知。没有执行远端 build、replay 或 attach；现场 P1/P2/P4 和相关 PC-AC 保持未验收。PC-AC-07/08 继续为 `partially-verified`，不会因一次静态代码查询而升格。

## 12. 2026-09-14 Pi source-only RPC and CLI result status

PiContext and PiModule now support source-only lookup without fake case data: task_scope=source_code binds an explicit code-context snapshot and marks data not_required; case-diagnosis scope remains blocked without case/intake, and source-only scope blocks before model use when the current code-context snapshot is missing. The local source prompt is compact, uses a bounded read-only source capability set, and disables automatic project/global context, skill, and extension discovery while explicitly loading the generated project extension. A real PiModule -> PiBridge (--mode rpc) call through local Ollama qwen3.5:9b succeeded for PostProcessMainTI, returning 3/13 depth-1 paths under snapshot 772e24a23d07fee749d0ad50f23d76d066326748b6d5defc90c91f78bbb9b336. Result and sanitized tool trace are outputs/pi_module_bridge_code_analyze_gen6_live_profile_20260914.json and outputs/pi_module_bridge_tool_trace_gen6_live_profile_20260914.json; no assistant reasoning is stored.

The current Pi user model catalog does not list qwen3.5:9b; a longer prompt hit an observed 4096-token stop limit. The source-specific prompt allowed one real RPC tool result within that limit without changing user configuration. A separate python cli.py pi run wrote outputs/pi_cli_code_analyze_gen6_20260914.json but returned an empty answer. PiModule now exposes sanitized pi_event_summary and, only for a completed source-code call_chain result, projects exact tool rows/bounds with answer_mode=tool_result_projection and ai_final_synthesis_status=not_available; without a completed result it returns empty_final_answer. The latest local CLI telemetry showed enabled_tools=[code-analyze], a 172-character source system prompt, a 514-character context prompt, and context/skill/extension discovery disabled; it still reached 4051 input + 45 output = 4096 tokens and stop_reason=length before a tool call. This local 9B CLI path remains variable due to its current context budget. No remote model, build, replay or GDB attach was used; field P1/P2/P4 and perception-level Pi acceptance remain open.


Pi source-only RPC 与 empty-final-answer 回归：tests/test_pi_context.py、tests/test_pi_tool_bridge.py 为 53 passed；当前全量 python -m pytest -q 为 898 passed, 1 skipped, 2 xfailed, 10 warnings（224.35s）。全量测试通过不提升 selected-frame/runtime/perception Pi-product 或现场 P1/P2/P4 状态。

## 13. 2026-09-14 当前配置 variant 自动 source-context 绑定

无 case 的 source-only Pi 查询现在从 `config.load_config()` 解析有效 variant，并用其 source root/key files 在 variant 的
`.workspaces/<variant>/memory/snapshots/code_context_current` 建立或复用 `code-context.v1`、`code-index.v1` 和 CodeGraph；
不读写共享默认 CodeGraph。`code-context.v1.artifacts.code_index_sha256` 固化 index 内容 hash；refresh 检查 snapshot 时若 index
缺失/哈希漂移则重建。PiContext 对 context 与 index 核验 schema、source root、snapshot、context→index 引用和 SHA-256，
记录两个 artifact ref；source-only PiModule 若缺少绑定 index 字段则在 provider 调用前停止。PiBridge 只向本次子进程传递
经验证的 context/index path/hash 和项目身份；`pi_tool_bridge` 分别为 `code-context-read`、`code-analyze` 注入路径，执行前复核
artifact/hash/snapshot，并拒绝 inline index、冲突路径和 `db_path` 覆盖。

当前默认 `gen6/byd_sc6h` 配置真实刷新后，PiContext 为 `ready`；source snapshot `0cf8c9c1a59030b36604c76cd2d7a7757a9989e87212841d1e245c7e8848c023`，
code-index SHA-256 `ff54d28cbf309aa81a7b48a0c9b243f56379c99617a463c96306a2c5aa80dee2`。绑定的
`code-context-read(section=summary)` 返回 18 个文件/415 个函数/3145 个源码条件；`code-analyze(call_chain, PostProcessMainTI, depth=1, limit=3)`
通过 `source_code_index` backend 返回 3/5 行并标记截断。可追溯 artifact 为
[`evidence/pi_source_context_autobind_gen6_20260914.json`](../../../technical/evidence/pi_source_context_autobind_gen6_20260914.json)，其 SHA-256
`48a7a6a3b05e285b881827f37ef585f4c2bbdf5987983b8dd01248723305d83d`。定向 Pi/CodeContext 回归为 `72 passed`。

此 smoke 验证的是配置 variant 到静态 source-index 工具边界；它没有调用 Pi 模型，也没有 selected-frame、runtime、build、GDB、CAN
或感知阶段证据。PC-AC-07/08、US-024 和现场 P1/P2/P4 仍为 `partially-verified`，不能因本次静态索引绑定升格。

## 14. 2026-09-14 source-only Pi 未经工具答复门

一次本机 Ollama `qwen3.5:9b` PiModule 调用在 `context_status=ready` 时 `agent_settled`，但 `event_summary.tool_calls=[]`、
`tool_events=[]`；模型文本给出了一组与当前索引相符的路径，但这不能证明它调用了已绑定工具。该未验收观察保存在
[`evidence/pi_source_context_unverified_text_probe_gen6_20260914.json`](../../../technical/evidence/pi_source_context_unverified_text_probe_gen6_20260914.json)，
文件把文本标为 `unverified_model_text`，不作为 source fact 或成功验收。

针对该缺口，`PiModule._prompt_with_ledger()` 在 `task_scope=source_code` 中要求 `code-analyze`、`code-context-read`、
`event-code-path` 或 `code-gdb-plan` 至少一个返回明确 `status=ok` 的 tool execution；否则清空模型最终文本，写入
`source_code_tool_evidence_missing` 并将 AnalysisRun 设为 partial。新增回归验证无工具文本会被抑制、成功绑定工具结果仍可正常返回；
Pi/CodeContext 定向测试当前为 `74 passed`。修复后的真实 Pi model/tool 轮次仍需一次现场运行确认。

在 no-tool gate 引入前，另一次本机 PiModule RPC 确实执行了 `code-analyze`，tool event `call_p38gs3ve` 返回 `status=ok`；
它使用当前自动绑定 snapshot `0cf8c9c1a59030b36604c76cd2d7a7757a9989e87212841d1e245c7e8848c023`，结果为 `PostProcessMainTI` depth-1 的 3/5 项。
脱敏记录 [`evidence/pi_source_context_tool_backed_rpc_gen6_20260914.json`](../../../technical/evidence/pi_source_context_tool_backed_rpc_gen6_20260914.json)
SHA-256=`14958e49d9a9cd4764060423e53381b95ea8c91b52f532bb3b6cc86afcbf0bb5`；context/index hash 与上一节静态边界 smoke 一致。
加入 no-tool gate 后的真实 RPC 重放返回 `ok=false`、`source_code_tool_evidence_missing`，事件摘要仍为 0 tool calls；记录见
[`evidence/pi_source_context_post_guard_rpc_gen6_20260914.json`](../../../technical/evidence/pi_source_context_post_guard_rpc_gen6_20260914.json)。
这证明本机模型未调用工具时会被正确阻断。随后用新的源码条件问题再次运行同一 PiModule 入口，模型发起 `code-analyze`
`kind=conditions`，tool event `call_d7fsfd9k` 返回 `status=ok`；本机绑定工具的二次确定性查询与回答的条件表达式、文件、行号一致。
证据 [`evidence/pi_source_context_post_guard_conditions_rpc_gen6_20260914.json`](../../../technical/evidence/pi_source_context_post_guard_conditions_rpc_gen6_20260914.json)
SHA-256=`f770bbc0c36de66e828ba12160e6fe5c56fd59ab2af8b47b3955053d404fcfe6`。这验证本机真实 source-only Pi 的成功工具路径和无工具失败路径；
仍然没有 selected-frame/runtime/build/GDB/CAN 或感知阶段证据，PC-AC-07/08、US-024 和现场 P1/P2/P4 保持 `partially-verified`。

## 15. 2026-09-15 远端 preflight 连通性复验

按当前 runtime workspace `/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int` 重新执行只读 `arbe-preflight`。SSH connectivity 在 `5.015s`
返回 `124/timed_out`，`probe_execution.status=short_circuited`，其余 22 项跳过；source/config/binary/runtime PID/GDB 仍为 `not_available`，
没有执行远端 build、replay 或 attach。原始 preflight 为
[`evidence/arbe_preflight_remote_refresh_20260915.json`](../../../technical/evidence/arbe_preflight_remote_refresh_20260915.json)，SHA-256=`dcf1c1b057ca373345218d6ff4e9cc7fa4f2b97a7bdd666ef39eedb8f2a983a4`。
这次确认当前 P1/P2/P4 现场输入仍不可观测；本地 Pi source-index 能力可以继续验证，但不能替代远端证据。

## 16. 2026-09-15 默认 variant 路径与 prewarm cold/hot 计时

P4 预热计时首次揭示当前 `default_variant=gen6/byd_sc6h`、历史 `default_project=gwm_b26` 时，`config.load_config()` 仍回填 GWM 的
`paths.source_code/key_source_files`；首次隔离计时的 variable-chain cache metadata 因而记录了 GWM RTE、空 RTE hash 和 0 alias。
该报告已重命名并标为无效调查样本 `evidence/prewarm_timing_gen6_byd_sc6h_invalid_gwm_rte_20260915.json`，不用于 BYD 性能结论。

修复后，`config.load_config()` 在有效 variant 存在时用该 variant backfill source/DBC/key/source_docs paths，`default_project` 仅作无 variant
时 fallback。`trace_variable_chains()` 现在只在显式路径有效或候选唯一时解析 RTE；它组合当前目录的 `RteComMapping.c`、`RteComMapping_Tx.c`、
`RteComMapping_TxSGU.c`，按所选 COEM 限定 customer-specific `globalVariDef`，并把 mapping path/file hash/COEM 写进 meta version 4。显式
RTE 缺失、多 COEM 歧义或 output mapping path 不存在都不再全仓捡第一个 Tx 文件或回退 GWM。

当前 `gen6/byd_sc6h` variant-scoped 隔离目录得到 1 cold + 9 warm prewarm runs；首次运行 `4.715849s`，warm p50=`0.576731s`、
nearest-rank p95=`0.666486s`（9 个 warm samples）。样本绑定 BYD_SC6H RTE + 两个 Tx companion 及扫描源码 SHA-256，alias_count=0。
工具使用 offline CodeLearner/Router stubs，因此测量覆盖 `_run_prewarm` 结构扫描与缓存路径，不含真实 LLM；没有 flush OS file cache，也不测
回放、数据解析、Pi、报告或第二项目。复验 JSON 为
[`evidence/prewarm_timing_gen6_byd_sc6h_variant_bound_20260915.json`](../../../technical/evidence/prewarm_timing_gen6_byd_sc6h_variant_bound_20260915.json)，
SHA-256=`b5cde89b78eb0601127dcf97c63d5dc2ba4a59c7a648cdc88b460b814a3a9449`。这只把 US-020 从 specified 推进到局部 partially-verified；完整 P4 仍待全链路样本与异构项目。

## 17. 2026-09-15 全量回归与变体映射收口

`config.load_config()` 当前按有效 `default_variant` 回填 legacy `paths.source_code/key_source_files/dbc_files/source_docs` 与 active `source_domains`；旧 `default_project`/top-level legacy domains
只有没有可解析 variant 时才用。RTE resolver 对显式路径验证 source-root containment，对无显式路径的 auto-discovery 仅接受唯一 COEM；
cache meta version 4 纳入所选 RTE 和 Tx companions、COEM 与扫描文件 hash。`ConditionExtractor` 与 `ExpertPanel` 也消费 active variant 的
`source_domains`，不再从 legacy global GWM domain 读源码。BYD_SC6H 当前 `variable_chains` metadata 指向
`coem/BYD_SC6H/components/AswIf/ASW_ComMapping/RteComMapping.c` 与两个 Tx companions，`coem=BYD_SC6H`，scan list 无 GWM；alias_count=0
如实保留，不将“成功加载 mapping”误标成已命中 alias。配置、prewarm、signal-mapper、signal-bridge、investigator 和 CodeContext 定向套件
`73 passed`，ExpertPanel/condition/config 定向切片 `38 passed`；全量 `python -m pytest -q` 为 `917 passed, 1 skipped, 2 xfailed, 10 warnings`（`215.07s`）。Release gate 接受 `10/10` required entries，
doctor `ready` / 64 capabilities / zero lock mismatches or failures；diff check exit 0，仅有 LF/CRLF 提示。

当前 P4 局部 prewarm sample 是 variant-bound 且离线 LLM stub；它不代表回放/解析/LLM/报告的完整性能门。当前 SSH P10 仍 `124/timed_out`，
远端 source/binary/runtime PID 不可观测，因此 P1/P2 perception-level/P4 full remain partially-verified。

## 18. 2026-09-15 source-only Pi CLI 正式入口续验

通过正式 python cli.py pi 入口，以 task_scope=source_code 和仅 code-analyze allowlist 查询
PostProcessMainTI depth-1 调用目标。使用本机 ollama/qwen3.5:9b 的单次参数
--provider ollama --thinking off，真实 Pi event stream 记录一次 code-analyze tool call
call_wk8q30ew，结果 status=ok，无 extension error。PiContext 为 ready，绑定
gen6/byd_sc6h source snapshot 0cf8c9c1a59030b36604c76cd2d7a7757a9989e87212841d1e245c7e8848c023；
模型列出的 5 个目标与同一 bound code-index 的直接 code-analyze 结果完全一致，且未截断。
证据为
[evidence/pi_cli_source_lookup_gen6_20260915.json](../../../technical/evidence/pi_cli_source_lookup_gen6_20260915.json)。

`qwen3.5:9b` 不在 Pi 的当前 `--list-models` 输出中；只指定 model 的对照运行没有 tool event 并超时，
显式指定 provider 后成功。该观察不改动 Pi 全局配置，也不把静态源码查询提升为 selected-frame、runtime、build、
GDB、CAN 或感知阶段证据。PC-AC-07/08 与现场 P1/P2/P4 仍保持 partially-verified。

`python tools/run_harness_gate.py --allow-known-edge` 的 6 个本地案例全部通过（报告
`reports/harness_gate_20260915_022426.json`）；doctor 为 ready、64 capabilities、无 lock mismatch。

本轮再以 --timeout-sec 15 做只读 P11 preflight；连接握手仍受 engines/arbe/preflight.py 的
min(timeout_sec, 5.0) 短上限约束，实际 5.015s 后返回 124/timed_out，22 项后续探测跳过。
artifact 为 outputs/arbe_preflight_p11_refresh_20260915.json；未执行 build、replay 或 GDB。

随后以 --timeout-sec 10 再做只读 P12 refresh，ssh_connectivity 仍在 5.015s 返回 124/timed_out，
probe_execution 短路并跳过 22 项；远端 source/config/binary/runtime/GDB 均 not_available。
artifact 为 outputs/arbe_preflight_p12_refresh_20260915.json；没有远端写入或 replay。

## 19. 2026-09-15 source-only Pi AnalysisRun 与只读 schema 收口

PiModule 现在在 source-only bridge/context 创建前解析 task scope；无 case/batch 的显式或自然语言源码查询
自动创建本地 AnalysisRun，并把 task_scope 写入 goal。当前 code-context/index 通过身份校验后绑定 project、
variant、source snapshot 与 index hash；默认 Pi session ID 稳定派生为 pi-<AnalysisRun ID>，与 ledger run ID
分开，显式 session_id 优先。tool step 从 Pi event 的 result.details.status 读取状态，返回的
analysis_run_status 取 ledger finalize 后值。

P11 之前的 Pi session 复验揭示源码 tool error：Pi schema 把 code-analyze.output（文件路径）暴露给模型，
模型误传 output=text/json；source-only bridge 在调用模块前拒绝，session 记录 8 个 isError tool result。
修复后，code-analyze/event-code-path/code-gdb-plan 的 Pi input_schema 不声明文件型 output 字段，通用
extension generator 按能力 schema 生成工具；source prompt 明确源码工具 inline 返回，bridge 继续 fail-closed
拒绝手工 output 路径，原有独立 CLI 参数未改。

修复后的无 session-id 覆盖真实运行完成：Pi 只调用一次 code-analyze，参数 kind=callees、
name=PostProcessMainTI、max_depth=1、max_results=5，tool status=ok；最终回复与绑定 index 的直接查询一致，
返回 DataProcInit、ObjTrack、OutputTrkObj、OtherAttributeCal、AdasFunc（5/5，未截断）。本地 AnalysisRun 与
tool-code-analyze/dialogue 两个 step 均为 completed，binding 保留当前 BYD_SC6H source/index hash。证据为
[evidence/pi_cli_analysis_run_source_lookup_gen6_20260915.json](../../../technical/evidence/pi_cli_analysis_run_source_lookup_gen6_20260915.json)。

随后以纯自然语言问题“PostProcessMainTI 的直接下游函数有哪些？”复验，不传 task_scope 或 tools。
Pi 自动判定 source_code，shortlist 为 4 个只读源码工具，并只调用一次 kind=callees；未传 function_name、
output 路径或 session_id。AnalysisRun run-20260914T200129-ee848e5e8e 与 code-index hash 绑定、status=completed，
直接 index 复核返回同一 5 个目标。证据为
[evidence/pi_cli_natural_source_lookup_gen6_20260915.json](../../../technical/evidence/pi_cli_natural_source_lookup_gen6_20260915.json)。

定向 Pi/AnalysisRun/schema 回归 tests/test_pi_tool_bridge.py、tests/test_analysis_ledger.py、
tests/test_pi_context.py、tests/test_code_analyze.py 为 92 passed；Pi extension 已重生成，64 项能力未改变。该验证只证明静态源码工具链和
可恢复 ledger，不提升 selected-frame/perception-level Pi reasoning 或现场 P1/P2/P4 状态；PC-AC-07/08、
US-015/US-024 仍为 partially-verified。

## 20. 2026-09-15 AnalysisRun-bound ledger tools

PiBridge 现在将当前 AnalysisRun ID 与 ledger root 作为本次子进程绑定传给 pi_tool_bridge。
analysis-run-read/update、analysis-step-record、analysis-claim-append、analysis-hypothesis-record、
debug-experiment-record 和 analysis-user-observation 会自动注入当前 run/root；显式指定不同 run 或 root 时
fail-closed，无绑定时拒绝 ledger 操作，active run 中也阻止重复创建。Pi input_schema 将 run_id/ledger_root
标为可省略并说明它们由 bridge 注入；独立 CLI 仍要求显式 run_id。

离线桥接回归在临时 ledger 中省略 run_id/ledger_root 调用 analysis-hypothesis-record 与
debug-experiment-record，随后从同一 run 读取到 1 条 hypothesis 和 1 条 planned experiment；跨 run_id
和跨 ledger_root 覆盖均被拒绝，run 状态未被冲突调用改变。相关测试为
tests/test_pi_tool_bridge.py::test_pi_ledger_tools_bind_active_run_and_reject_conflicts、
tests/test_pi_bridge_child_process_receives_exact_code_index_binding 和
tests/test_analysis_ledger.py::test_pi_ledger_tool_schemas_leave_bound_run_fields_optional。
包含上述绑定与 schema 用例的定向 Pi/AnalysisLedger/PiContext/CodeAnalyze 套件为 92 passed。

这补齐了 Pi 保存 hypothesis/experiment 时的运行身份与路径传递。诊断 prompt 现在要求最多 3 个有证据支持的候选、
不为数量填补假设、证据不足时返回 0 个因果假设，并计划一个成本低且区分度高的实验；确认仍只允许用户执行。
但尚无新鲜 P1 现场证据验证真实模型的候选排序/实验选择，root_cause 发布门也未完成。US-015/US-018 仍为
partially-verified，不能据此宣称 P2 现场推理闭环完成。

## 21. 2026-09-15 gen6/reco_fw variant-isolation probe

根据 config.load_config() 中显式登记的 gen6/reco_fw，read-only refresh 读取 source root D:\pl-xpeng 的
13 个已配置 key files；Code Context/index 与 capability manifest 全部落在 radarAnalyze 的
.workspaces/gen6_reco_fw 路径，不复用 BYD_SC6H cache，也未执行修改外部 source 的命令。复验后外部 Git 状态有 6 条 dirty entry，
本轮未保存调用前基线，因此不将其归因于本次；产物与计时缓存只写在 radarAnalyze workspace。Context/index 共同绑定
source snapshot 8e1ddec8177485974fde5c648f80582b99d3003032d6855f3a5fbd17884050a2，13 files / 59 functions；
direct code-analyze 返回 checkDistortiveBlindness 于
reco_fw/component/per/runnables/spp_bdm/src/per_sppBdmRunnable.cpp:218-245，source root/hash 与该 variant 一致。

project-capability-manifest.v1 标记 partial / freshness=fresh、无 conflicts，并显式列出 recorded-data、
Arbe workspace、public runtime snapshot、GDB 和 Sprint1 report 缺口；当前 RTE resolver 为 not_found。
这只推进 US-019 的静态 variant/source isolation，未通过无报警/已知报警/runtime/缺输入/版本变化五类测试，
也未满足 P4 第二项目 replay/performance 门。证据为
[evidence/reco_fw_variant_context_isolation_20260915.json](../../../technical/evidence/reco_fw_variant_context_isolation_20260915.json)。

## 22. 2026-09-15 gen6/reco_fw variant-bound prewarm slice

在上述独立 gen6/reco_fw workspace 内，使用 isolated source_docs override 运行 10 次离线 prewarm harness：
1 次 cold 为 7.396263s，9 次 warm 的 nearest-rank p50 为 2.438595s，p95 为 2.536051s；CodeLearner/Router
使用 offline stubs，因此只测 _run_prewarm 结构扫描和 cache path，不含真实 LLM、bag 解析、回放或报告。

variable_chains cache metadata version=4，rte_mapping_status=not_requested、rte_file/rte_hash/coem 为空、
alias_count=0、file_hashes 为空，没有 GWM path；该结果表示此 Reco firmware variant 未声明 RTE mapping，
不是 alias 查找成功。manifest 为 partial/fresh，recorded-data/Arbe/runtime/GDB/report 均明确 unsupported。
证据为 [evidence/prewarm_timing_gen6_reco_fw_variant_bound_20260915.json](../../../technical/evidence/prewarm_timing_gen6_reco_fw_variant_bound_20260915.json)。

这把 US-020 从仅有 BYD 的隔离预热推进到两个配置 variant 的静态 prewarm 子路径对照，但不是异构项目数据/replay/LLM/report 的 P4 全链路验收。

## 23. 2026-09-15 自然语言 Pi 源码检索指标

在正式 `python cli.py pi` 入口再次以纯自然语言查询
“PostProcessMainTI 的直接下游函数有哪些？”，未显式传入 `task_scope` 或工具 allowlist。
Pi 推断 `source_code`，只调用一次 `code-analyze`（`call_dx0w77qn`），状态为 `ok`，
backend 为 `source_code_index`。AnalysisRun `run-20260914T215459-af69d53325` 与当前
BYD_SC6H source snapshot `0cf8c9c1a59030b36604c76cd2d7a7757a9989e87212841d1e245c7e8848c023`
及 code-index SHA-256 `ff54d28cbf309aa81a7b48a0c9b243f56379c99617a463c96306a2c5aa80dee2` 绑定；
工具和对话步骤均完成。Pi 返回 5 个直接下游目标，当前 index 的独立查询得到相同结果且未截断。

该 AnalysisRun 记录 `code_index_refresh_attempt_count=1`、`code_index_cache_hit_count=1`、
`code_index_refresh_duration_sec_total=3.978219`、`code_index_query_success_count=1`，
返回/总行数为 5/5。`time_to_first_useful_clue_sec=84.364` 是单次本地 Ollama 样本，含模型等待；
它不是性能基准，也没有可比的前后基线。运行的 `data_status=not_required`，没有读取 bag、回放、
build、GDB 或 CAN，因此这只验证 source-only Pi 查询和可持久化索引指标，不代表完整 P4 或
PC-AC-07/08 的 selected-frame/runtime 验收。证据为
[`evidence/pi_source_index_run_metrics_gen6_20260915.json`](../../../technical/evidence/pi_source_index_run_metrics_gen6_20260915.json)
及对应的 [AnalysisRun](../../../../outputs/analysis_runs/run-20260914T215459-af69d53325/analysis-run.json)。

## 24. 2026-09-15 P13 只读远端 preflight 重试

针对 P12 的 `ssh_connectivity` 超时，以 `--timeout-sec 15` 对同一台
`10.190.171.44` 的只读 preflight 重试，目标仍为
`/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int`。SSH 探针仍在 5.015s 返回 `124/timed_out`，
preflight 短路并跳过 22 个后续探测；source/config/binary/runtime/GDB 均因此不可观测。
产物为 `outputs/arbe_preflight_p13_refresh_20260915.json`。没有执行远端 build、replay 或 GDB；
远端集成门仍等待 SSH 连通后再按显式授权继续。

## 25. 2026-09-15 source-index metrics 回归结果

加入 AnalysisRun 源码索引 refresh/reuse 和 `code-analyze` 结果计数后，全量
`python -m pytest -q` 为 `929 passed, 1 skipped, 2 xfailed, 10 warnings`（223.89s）；
10 条 warning 是现存 `semantic_memory.table_names()` deprecation。`python tools/release_gate.py`
接受 10/10 required entries；`python tools/doctor.py --json` 为 `ready`、64 capabilities、
无 lock mismatch/failure；`python tools/run_harness_gate.py --allow-known-edge` 为 6/6 passed、
blocking=0（`reports/harness_gate_20260915_060913.json`）。release manifest 有 21 entries、
238 evidence refs、161 unique refs、missing=0。P13 远端 preflight 仍因 SSH 探针超时未能提供
source/runtime 证据；上述本地门禁结果不提升 P1/P2/P4、US-019/US-020 或 PC-AC-03/07/08 的现场验收状态。

## 26. 2026-09-15 ObjectList message schema introspection

`ros-topic-inventory` 新增默认关闭的 `inspect_message_schemas` / CLI
`--inspect-message-schemas` 选项：对当前 inventory 解析到的有效 `package/Type` 调用远端只读
`rosmsg show`，从返回定义中生成带嵌套 message type 的字段路径目录，并保留完整定义 SHA-256、
字符数和 command result。返回给 Pi 的字段目录最多 512 项，定义解析输入最多 250,000 字符；
超限状态为 `partial` 且带 diagnostic；完整定义本身不进入 Pi payload。message type 经严格 token
校验，错误类型不会执行 shell 命令。模块不据此给 `wfObjectMsg` 补算法 frame，现有 normalizer 继续
将无 frame/callback 对象保留为 `unbound`。

`tests/test_ros_inventory.py` 覆盖类型安全、当前定义字段解析、SHA、字段目录上限和无硬编码字段；
与 `tests/test_public_runtime.py` 一起定向回归为 `18 passed`。M4-AC-002 记录为
`partially-verified`：这是字段目录的本地实现与 fake-runner 验证，远端 `rosmsg show` 尚未能通过
当前 P13 SSH preflight 连通性复核；统一 live collector、时间戳快照、报告 drilldown 和事件跳转仍待实现。

## 27. 2026-09-15 ObjectList slice 全量验证

合并本轮 source-index metrics 与 ObjectList schema-introspection slice 后，最新全量
`python -m pytest -q` 为 `933 passed, 1 skipped, 2 xfailed, 10 warnings`（224.30s）；
`tests/test_ros_inventory.py tests/test_public_runtime.py` 为 `18 passed`。`python tools/release_gate.py`
接受 10/10 required entries；`python tools/doctor.py --json` 为 `ready`、64 capabilities、无 lock mismatch/failure；
Harness Gate 为 6/6 passed、blocking=0（`reports/harness_gate_20260915_063345.json`）。当前 release manifest
为 22 entries、246 evidence refs、169 unique refs、missing=0；M4-AC-002 明确保持
`partially-verified`。`git diff --check` 退出码为 0，只有 Git 的 LF/CRLF notices。

仍需现场环境完成 P13 preflight 和 `rosmsg show` 复核；当前 SSH 探针 5.015s/`124/timed_out`，
没有远端采集、build、replay 或 GDB。本地 schema 输出与 gate 通过不代表真实 collector/snapshot 或
ObjectList 用户链路已经完成。

## 28. 2026-09-15 ROS sample 到 PublicRuntime snapshot

`ros-topic-inventory.v1` 的 `--sample-once` 现记录客户端 UTC 观察时刻、sample stdout 完整 SHA-256、
字符数和 `stdout_truncated`；传入 `--preflight-path` 时自动解析 server 并保留该 preflight artifact hash、
workspace/binary/config fingerprint。`public-topic-plan.v1` 同样保存 preflight artifact hash。
`public-runtime-normalize --capture-path <inventory.json>` 可直接消费该 artifact：它核验 inventory 文件 hash、
样本 hash/字符数/截断标志，要求 inventory、topic plan 和当前 preflight 的 artifact hash 一致；只有当前 message schema `ready`、
定义 SHA 存在且只找到一个 nested message array 字段时才展开 ObjectList。输出的
`runtime-snapshot-with-frame.v1.capture_metadata` 绑定 inventory/topic-plan hash、采样时刻、server，
并明确标记 `topics_sampled_independently=true` 与 `cross_topic_frame_association=not_asserted`。

若附带 `public-topic-plan.v1`，角色映射要求 inventory `runtime_binding=preflight_bound`，计划记录的
preflight SHA/server/workspace 与本次 preflight artifact 和 inventory server 匹配；不一致时禁用映射并输出 gap。
Plan 中的 `algorithm_warning` 与 `raw_can_warning`
保持不同 evidence layer。独立 topic sample 没有共享 `message_seq`，所以即使 source contract 有
publication-order，ObjectList 仍为 `unbound`。快照还标记 `identity_binding=not_bound`，在进入 runtime
evidence/诊断结论前仍需要 AnalysisRun、data、source、binary、config 和 session identity。

Pi 的 ObjectList/目标属性请求 shortlist 现在包括 `ros-topic-inventory` 与
`public-runtime-normalize`；default prompt 要求先复用 current preflight 生成 `public-topic-plan`，再采样
计划中的公开 topic、为 inventory 写新本地 artifact，并把返回的 `artifact_path` 传给 normalizer；不覆盖
preflight/topic plan/input capture，允许按 plan、inventory sample、runtime snapshot 逐步执行；
没有 GDB/SSH 写入，也不把该离线 adapter 宣称为真实当前状态验证。定向
`tests/test_ros_inventory.py tests/test_public_runtime.py tests/test_public_evidence.py tests/test_pi_tool_bridge.py`
覆盖采样 hash/截断、message-array schema 路径、inventory→snapshot、过期 plan 身份拒绝、跨 topic 不配对及
raw CAN warning 分层，定向结果为 `86 passed`。

## 29. 2026-09-15 P14 只读远端 preflight 重试

针对 P13 的 SSH timeout 再做只读 preflight，目标仍是 `10.190.171.44` 的
`/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int`；5.032s 后以 `124/timed_out` 短路，22 项后续探测未执行。
artifact 为 `outputs/arbe_preflight_p14_refresh_20260915.json`。因此本地 adapter 尚无本轮实时 ROS 样本或
远端 `rosmsg show` 定义验证；没有执行 build、replay 或 GDB。

## 30. 2026-09-15 PublicRuntime snapshot slice 回归

加入 inventory-to-snapshot adapter、current-preflight plan identity gate 和 ObjectList Pi routing 后，
全量 `python -m pytest -q` 为 `940 passed, 1 skipped, 2 xfailed, 10 warnings`（233.36s）；
10 条 warning 仍是 `semantic_memory.table_names()` deprecation。定向
`tests/test_ros_inventory.py tests/test_public_runtime.py tests/test_public_evidence.py tests/test_pi_tool_bridge.py`
为 `86 passed`。Release gate 接受 10/10 required entries；doctor `ready` / 64 capabilities / 无 lock mismatch
或 failure；Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_072654.json`）。
manifest 为 22 entries、258 evidence refs、177 unique refs、missing=0；`git diff --check` exit 0，只有
LF/CRLF notices。

M4-AC-002 仍是 `partially-verified`。adapter 和 UI shortlist 经本地 fixture/fake runner 验证；P14 的 SSH
`124/timed_out` 阻止了实际 ROS sample、当前消息定义确认和 ObjectList drilldown 验证，所以 US-021 尚未闭环。

## 30. 2026-09-15 preflight-hash binding 回归

inventory、topic plan 与 normalizer 现在只有在相同的 `arbe-preflight.v1` 文件 SHA、server/user/port 和
workspace 摘要一致时才采用 plan role mapping；inventory 没带 `preflight_path` 或 status 不是
`preflight_bound` 时不使用计划映射，仍把可动态解析的 ObjectList 字段作为 unbound snapshot 返回。
`tests/test_ros_inventory.py` 覆盖 preflight 自动解析和显式 server conflict，
`tests/test_public_evidence.py` 覆盖 topic-plan preflight SHA，runtime/Pi 集成切片共 `89 passed`。

这一轮完整 `python -m pytest -q` 为 `943 passed, 1 skipped, 2 xfailed, 10 warnings`（237.07s）；
Release gate 接受 10/10 required entries；doctor `ready` / 64 capabilities / 无 lock mismatch/failure；
Harness Gate 为 6/6 passed、blocking=0（`reports/harness_gate_20260915_075842.json`）。release manifest 为
22 entries、259 evidence refs、178 unique refs、missing=0；`git diff --check` 退出码 0，仅有 LF/CRLF notices。
P14 SSH 探针仍 `124/timed_out`，实际 remote inventory 与 `rosmsg show` 验收仍未完成，M4-AC-002 保持
`partially-verified`。

## 31. 2026-09-15 inventory-to-snapshot 回归

将 ObjectList sample adapter、preflight identity gate 和 Pi intent routing 合并后，最新全量
`python -m pytest -q` 为 `940 passed, 1 skipped, 2 xfailed, 10 warnings`（233.36s）；
上述四个 ROS/runtime/public-evidence/Pi 定向套件为 `86 passed`。之后更新 Pi prompt 以要求新建
inventory artifact 并沿用返回的 `artifact_path`；对应 prompt regression 为 `1 passed`。Release gate 接受 10/10 required
entries；doctor `ready` / 64 capabilities / 无 lock mismatch 或 failure；Harness Gate 6/6 passed、
blocking=0（`reports/harness_gate_20260915_072654.json`）。release manifest 为 22 entries、
258 evidence refs、177 unique refs、missing=0；M4-AC-002 继续标记 `partially-verified`。
`git diff --check` 退出码为 0，仅有 LF/CRLF notices。

P14 仍因远端 SSH 5.032s/`124/timed_out` 跳过 22 项探测，所以尚无实际 `ros-topic-inventory`
采样、当前 ROS message definition 或 report drilldown 的现场证据；ObjectList 工具流本轮只完成本地实现与
fake-runner/fixture 验证。

## 32. 2026-09-15 unbound runtime snapshot bounded query

`evidence-query` 可将 `runtime-snapshot-with-frame.v1` 作为独立只读来源，不再强制 bundle/viewer；按
radar 和当前 `object_field_catalog` token 返回至多 `max_targets × max_field_rows` 的属性切片，并保留
inventory/topic/schema hash、`association_status` 和 `identity_binding`。未知 field token 为
`not_available`。如果用户指定 `frame_id` 而 ObjectList 仍 unbound，查询排除该行并返回
`unbound_runtime_snapshot_rows_excluded_by_frame_filter`/`runtime_snapshot_has_no_exact_frame_match`；有样本时
结果状态为 `partial`，并标记 `event_association_status=not_available`，不会从 sample_time 关联到事件。

`tests/test_evidence_query_runtime_join.py` 新增 direct snapshot path、schema-backed fields、frame filter
拒绝 unbound row 和缺失 token 测试，单文件 `6 passed`。该接口补齐 Pi bounded field lookup，不等同
diagnosis-report HTML drilldown、事件关联或已绑定 runtime evidence；这些仍待后续闭环验证。
Pi 的 objectlist field intent 也会将 `evidence-query` 放入 bounded shortlist；当前系统提示要求只用 schema
中的 exact token，且 frame filter 不能命中 unbound rows。

## 33. 2026-09-15 runtime-snapshot query 全量验证

加入 `evidence-query --runtime-snapshot` 与 direct snapshot path 后，全量
`python -m pytest -q` 为 `948 passed, 1 skipped, 2 xfailed, 10 warnings`（240.28s）；
`tests/test_evidence_query_runtime_join.py` 单独 `6 passed`，ROS/runtime/public-evidence/Pi 定向切片
`96 passed`。Release gate 接受 10/10 required entries；doctor `ready` / 64 capabilities / 无 lock mismatch；
Harness Gate 为 6/6 passed、blocking=0（`reports/harness_gate_20260915_083043.json`）。release manifest 为
22 entries、263 evidence refs、182 unique refs、missing=0；`git diff --check` 退出码 0，仅有 LF/CRLF notices。

直接 runtime-snapshot query 仍为 bounded evidence read：unbound 对象可按 radar/schema token 显示，指定报警帧
时被排除；它不补 diagnosis-report HTML event drilldown，也不绕过 `identity_binding=not_bound`。P14 SSH timeout
及真实远端 inventory/schema 验证仍未解决，US-021 和整体目标继续保持 partially verified。

## 34. 2026-09-15 snapshot report projection

`diagnosis-report` 现在可额外接收 `runtime_snapshot_path`，复用同一 `evidence-query` projection，把
unbound ObjectList rows 放入独立 `runtime_snapshot_rows` 和 evidence layer，并在 overview 记录
`runtime_snapshot_status`/object count。它不把 snapshot rows 自动并入 selected event、alert timeline 或
condition trace；`identity_binding=not_bound`、sample provenance 和 event association gap 保留为 partial。
报告仍要求 bundle/viewer 作为事件上下文，所以这条能力不把无事件快照伪装成已绑定诊断。

新增 `tests/test_diagnostic_report_identity.py` 用例验证这条边界。最后全量
`python -m pytest -q` 为 `949 passed, 1 skipped, 2 xfailed, 10 warnings`（230.87s）；报告/evidence/Pi
受影响定向套件 `96 passed`。Release gate 接受 10/10 required entries；doctor `ready` / 64 capabilities；
Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_084626.json`）；manifest 为 22 entries、
266 evidence refs、185 unique refs、missing=0；`git diff --check` 退出码 0，仅有 LF/CRLF notices。
P14 现场 SSH timeout 和真实 ObjectList/rendered drilldown 缺口保持不变。

## 35. 2026-09-15 snapshot HTML/Markdown projection

`diagnosis-report` 的 HTML 和 Markdown 现在都展示独立 ObjectList snapshot 表：Radar、Frame、association
状态、topic、动态字段 token/value 和 sample time；缺 frame 显示 `not_available`，identity status 与 partial
语义保留。页面文案明确这些行来自独立 ROS sample，不是同帧 warning，也没有被自动绑定到报警事件。

新增 report HTML fixture 测试；最终全量 `python -m pytest -q` 为 `950 passed, 1 skipped, 2 xfailed, 10 warnings`
（222.37s）。受影响 report/evidence/Pi 定向套件为 `74 passed`。Release gate 接受 10/10 required entries；
doctor `ready` / 64 capabilities / 无 lock mismatch；Harness Gate 6/6 passed、blocking=0
（`reports/harness_gate_20260915_090044.json`）；manifest 为 22 entries、266 evidence refs、185 unique refs、
missing=0；JSON contracts valid；`git diff --check` exit 0，仅有 LF/CRLF notices。P14 远端 SSH timeout、
现场 ROS sample 和真正的跨层 drilldown 仍未验证。

## 36. 2026-09-15 snapshot navigation handoff

当详细报告包含独立 ObjectList snapshot rows 时，`next_actions` 现在增加两个保守 handoff：
`event-code-path` 用已有事件/代码上下文继续查字段来源，`debug-experiment-record` 计划低成本区分实验。
两者都不从 `objID` 猜函数、不把 snapshot 行升级为 observed runtime，也要求后续绑定 event/frame/source/runtime
identity；这补齐了 US-021 “跳转代码链/下一次 DebugExperiment”的本地产品路径，但不等同现场执行。

本轮新增 handoff 断言后全量 `python -m pytest -q` 为 `950 passed, 1 skipped, 2 xfailed, 10 warnings`
（220.38s）。Release gate 接受 10/10 required entries；doctor `ready` / 64 capabilities；P14 SSH timeout
和远端 ObjectList/rosmsg/show 缺口保持不变。

本轮 handoff 的 `target` 还保留 bounded radar/frame/object/topic/source refs 和
`handoff_status=requires_event_and_source_binding` / `plan_only_requires_approval_and_identity`，便于
Workbench 或 Pi 后续消费而不把字段值升级为事实。最终全量回归为 `950 passed, 1 skipped, 2 xfailed,
10 warnings`（219.24s），报告身份用例 `9 passed`。

## 37. 2026-09-15 P15 只读 preflight refresh

再次以 `--timeout-sec 15` 对 `10.190.171.44` /
`/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int` 做只读 preflight。SSH probe 在 5.031s 返回
`124/timed_out`，后续 22 项探测跳过；artifact 为 `outputs/arbe_preflight_p15_refresh_20260915.json`。
远端 source/config/binary/runtime/GDB/ROS inventory 仍不可观测，没有执行 build、replay 或 GDB；P15 结果
已追加到 PC-AC-08 证据，不能升级 US-021/P1/P2/P4 的现场状态。

## 38. 2026-09-15 evidence-first user feedback kinds

US-014 的 `analysis-user-observation` ledger 新增三个明确用户反馈 kind：
`feedback_confirmed`、`feedback_rejected`、`feedback_irrelevant`。它们复用现有
`user-observation.v1`，必须由 `created_by=user` 写入，保留当前 run 的 variant/source/data binding，
并固定为 `evidence_layer=user_observation`、`runtime_eligible=false`。反馈不会自动写入 memory、
knowledge manifest 或其他 variant；后续知识发布仍需独立 freshness、证据和用户流程。

新增 `M4-AC-003` 以 ledger fixture 验证三类 feedback 的 provenance 和 authority gate。最后全量
`python -m pytest -q` 为 `951 passed, 1 skipped, 2 xfailed, 10 warnings`（232.65s）；
定向 ledger/Pi/runtime 套件 `86 passed`。Release gate 接受 10/10 required entries；doctor `ready` / 64
capabilities；Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_093928.json`）；
manifest 为 23 entries、271 evidence refs、189 unique refs、missing=0。US-014 仍为
`partially-verified`，AI 根因反馈驱动的 knowledge publish 和 Workbench 闭环未完成。

## 39. 2026-09-15 feedback-review gate

新增只读 `feedback-review` capability：它读取当前 `analysis-run.v1` 的用户反馈，核对
`feedback_confirmed`/`feedback_rejected`/`feedback_irrelevant` 的 variant/source/data binding、
`created_by=user` 和 `runtime_eligible=false`，输出 `feedback-review.v1` 的 counts、conflicts 和
`knowledge_publish_gate`。默认结果是 `approval_required`，`writes_knowledge=false`；identity/authority
冲突时为 `blocked`。它不调用 KnowledgeStore、不写 memory/manifest，也不跨 variant 聚合。

本轮生成的 Pi capability catalog 为 65 项。全量 `python -m pytest -q` 为
`951 passed, 1 skipped, 2 xfailed, 10 warnings`（232.65s）；feedback/ledger/Pi 定向切片 `76 passed`。
Release gate 接受 10/10 required entries；doctor `ready` / 65 capabilities / 无 lock mismatch；Harness Gate
6/6 passed、blocking=0（`reports/harness_gate_20260915_093928.json`）。manifest 为 24 entries、277 evidence
refs、193 unique refs、missing=0；US-014 仍 partially-verified，真正 knowledge publish/Workbench 仍待完成。

Pi feedback intent 现在会将 `feedback-review` 与 `analysis-user-observation` 选入 bounded shortlist；
自然语言“确认/否定/无关/反馈”可以先审查 gate，再由用户决定是否继续写入 feedback observation。
对应 prompt/allowlist regression 通过，capability catalog 当前为 65 项。

feedback-review 后续修正为优先 materialize AnalysisRun 中的 user-observation refs，再做 binding/authority
检查；这避免只读 run summary 时把缺少 binding 的 ref summary 误判为冲突。对应 ref materialization fixture
通过，反馈审查仍然只读、不写 knowledge。

## 40. 2026-09-15 feedback-review ref materialization 回归

这一修正后全量 `python -m pytest -q` 为 `956 passed, 1 skipped, 2 xfailed, 10 warnings`（763.80s）；
定向 feedback/ledger/Pi 套件为 `76 passed`。Release gate 接受 10/10 required entries；doctor `ready` /
65 capabilities；Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_105054.json`）；
manifest 为 24 entries、277 evidence refs、193 unique refs、missing=0。P15 SSH/remote evidence 与 knowledge
publish/Workbench 仍未完成。

## 41. 2026-09-15 P16 只读 preflight refresh

重新核验 `10.190.171.44` / `/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int`，SSH probe 在 5.062s
返回 `124/timed_out`，22 项后续探测跳过；artifact 为 `outputs/arbe_preflight_p16_refresh_20260915.json`。
远端 source/config/binary/runtime/GDB/ROS inventory 仍不可观测，没有执行 build/replay/GDB；P16 结果已追加
到 PC-AC-08，US-021/P1/P2/P4 现场状态不升级。

## 42. 2026-09-15 explicit feedback knowledge plan

新增 `feedback-knowledge-plan` capability：它接受已审查的 `feedback-review.v1`、候选 pattern、freshness
inputs 和显式 user approval，校验 variant scope 与 confirmed feedback；默认返回
`status=approval_required`，即使 approved 也只返回 `status=ready` 的 write-free plan，固定
`writes_knowledge=false`，实际 KnowledgeStore mutation 仍需另一个明确且 freshness-gated 的动作。
它不写 memory/manifest，不把 feedback summary 当作 root cause observed。

Pi catalog 目前 66 项。全量 `python -m pytest -q` 为 `958 passed, 1 skipped, 2 xfailed, 10 warnings`
（946.30s）；feedback-review/knowledge-plan 定向 `6 passed`。Release gate 接受 10/10 required entries；
doctor `ready` / 66 capabilities；Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_113120.json`）；
manifest 为 25 entries、282 evidence refs、196 unique refs、missing=0。P15/P16 远端 SSH 与 Workbench/实际
knowledge publish 仍未完成。

## 44. 2026-09-15 explicit knowledge publish leaf 回归

新增 `feedback-knowledge-publish` 是真正的受 approval 写入 leaf：只接受 ready publish plan、用户批准、
`actor=user`、显式 knowledge dir 和匹配 variant scope，写入当前 scope 的 RootCausePattern，并保留
feedback review/run provenance。普通 feedback、未批准 plan、跨 variant 或非用户 actor 全部拒绝。

本轮 catalog 为 67 项。全量 `python -m pytest -q` 为 `959 passed, 1 skipped, 2 xfailed, 10 warnings`
（840.74s）；feedback/knowledge-plan/publish 定向 `7 passed`。Release gate 接受 10/10 required entries；
doctor `ready` / 67 capabilities；Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_120134.json`）；
manifest 为 26 entries、287 evidence refs、198 unique refs、missing=0。实际 Workbench、P15/P16 remote evidence 和
真实 AI feedback loop 仍待完成。

## 43. 2026-09-15 approved feedback knowledge publish leaf

新增 `feedback-knowledge-publish`，声明 `requires_approval=true`。它只接受 `feedback-knowledge-plan.v1`
的 `status=ready`、`approved=true`、`actor=user`、显式 `knowledge_dir` 和匹配当前 variant scope，才写入
当前 scope 的 `RootCausePattern`；普通 feedback、未批准 plan、其他 variant 或 actor 都被拒绝。写入结果为
`feedback-knowledge-publication.v1`，不写其他 variant、不把 observation 当 runtime，且保留 feedback review/run ref。

本轮 catalog 为 67 项。全量 `python -m pytest -q` 为 `959 passed, 1 skipped, 2 xfailed, 10 warnings`
（840.74s）；feedback/knowledge-plan/publish 定向 `7 passed`。Release gate 接受 10/10 required entries；
doctor `ready` / 67 capabilities；Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_120134.json`）；
manifest 为 26 entries、287 evidence refs、198 unique refs、missing=0。P15/P16 远端 SSH、Workbench 和真实
AI feedback knowledge loop 仍待完成。

## 44. 2026-09-15 feedback gate in report projection

`diagnosis-report` 现在可接收 `feedback-review.v1`，并在 JSON/HTML/Markdown 中显示独立 Feedback layer：
confirmed/rejected/irrelevant counts、knowledge publish gate、conflicts 和 diagnostics。它不覆盖 observed/runtime
事实；报告页面把 feedback kind 显示为用户可读标签并保留原始 token，避免把用户反馈误读成根因或运行态。

最终全量 `python -m pytest -q` 为 `960 passed, 1 skipped, 2 xfailed, 10 warnings`（763.05s）；
report/Pi 受影响定向套件 `81 passed`。Release gate 接受 10/10 required entries；doctor `ready` / 67 capabilities；
Harness Gate 6/6 passed、blocking=0（`reports/harness_gate_20260915_131704.json`）；manifest 为 26 entries、
287 evidence refs、198 unique refs、missing=0。Workbench 和远端现场证据仍未完成。
