# CR60 Pi Unified Platform 产品化交接文档

版本："handoff.2026-09-03.productization.v1"
日期："2026-09-03"
状态："phase-1-audit-complete / implementation-deferred"

> 本文是后续执行者的第一阅读入口。它记录当前工作区的真实状态、已验证事实、证据边界、未完成事项和执行顺序。不要把“设计存在”“代码能生成 artifact”“历史运行日志成功”直接当成“整条现场链路已经验收”。

## 1. 交接结论

当前项目已经具备 Pi 驱动的 CR60/arbe 诊断骨架：

用户问题/材料
  → Pi 统一入口
  → intake / source / preflight / code context
  → 静态数据预检查
  → public runtime / arbe 回放
  → source-bound GDB plan / GDB session
  → runtime evidence merge
  → condition trace / output chain
  → 逐事件 HTML / 批量 index / Pi 对话解释

本轮完成的是第一阶段产品盘点和核心 gate 验证，不是宣称所有现场能力都已闭环。

已确认：

- Pi 能力目录、Python bridge、生成的 registerTool 对应同一套原子能力；
- diagnosis-report 可以合并真实 bag、当前源码条件、GDB 运行时值和 arbe 报警灯输出；
- 输出链可以从算法 adasWarning 追到当前 source 的内部 member path、赋值函数、对外 signal expression 和 RteLite/Com_SendSignal；
- 真实 CRGVI-1829 示例的算法报警和 GDB 目标命中有可追溯证据；
- ASW/FCT 内部信号同帧 GDB、正式 PID attach、公共 snapshot 精确关联和完整 Pi 现场长链仍有缺口。

后续应做产品化收口和现场闭环，不要重新设计固定 FCTA/FCTB 规则，也不要复制当前 case 的专用流程。

## 2. 用户目标和呈现要求

用户最终脱离 ChatGPT，通过 Pi 对话入口使用工具。输入可能是一条数据、一个文件夹或上游 cr60-analysis-intake.v1，并可包含 arbe 仓、src/algo_source、车型、COEM、分支/tag、DBC、需求材料和运行权限。

工具自动获取技术字段，不要求用户手工推导：

- frameID
- radar_id
- objInfo->trcOutData[i]
- algorithm_index
- objectlist_index
- ROI points
- GDB expression
- source line

用户要看到的叙事顺序是：

当前工况
→ 功能/侧别/雷达/目标
→ 自车和目标真实值
→ 状态机、自车条件、目标过滤、ROI/预测条件
→ 算法报警输出
→ FCT/ASW 内部信号
→ 对外 signal 映射
→ 已证实项、未证实项、是否应该报警、下一步验证

HTML 首屏顺序：总结结论 → 报警条件表 → 报警帧数据表 → 工况图 → 自然语言命中流程；源码表达式、完整 JSON、GDB 命令放在折叠详情中。

## 3. Git 和工作区状态

当前本地分支：codex/ros-debug-autonomous

当前 HEAD：138901fab0bfef0fa1ff73ebf87f8798de8b00ae

远程：origin https://github.com/Bobs1121/RadarDiagnostic.git

本次 git ls-remote 只确认了 origin/main，没有确认目标分支已经存在；本轮没有 commit 和 push。

工作区混合了多轮开发遗留的产品代码、文档、测试、case 报告、SQLite/WAL、outputs、实验脚本和用户修改。接手者禁止直接执行：

- git reset --hard
- git checkout -- .
- git clean -fd

必须按类别盘点后再处理：

| 类别 | 原则 |
|---|---|
| 产品代码、schema、测试、DDD 文档 | 评审后提交 |
| outputs、报告、远程日志 | 本地保留，默认不提交 |
| bag/MF4/BLF、SQLite/WAL/LanceDB | 默认不提交 |
| .env、API key、服务器凭据 | 永不提交 |
| 一次性探索脚本 | 结论迁移到文档后删除/移出 |
| 用户已有修改 | 不覆盖，无法判断归属时先确认 |

## 4. 产品架构和职责

Pi interaction / orchestration
  ai/pi_bridge.py + .pi/extensions + pi_tool_bridge
        ↓ registerTool / JSON
Atomic modules
  ai/modules/*.py
        ↓ deterministic engine
Deterministic engines
  engines/
        ↓ provider / adapter
ROS bag / arbe / SSH / GDB / DBC / media

核心边界：

- engines/ 只负责确定性数据、计算、source path、证据投影、schema 和 provenance；
- ai/modules/ 负责 Pi/CLI/approval/artifact 契约，不重复实现 engine；
- Pi 负责组合和解释，不能覆盖 observed 事实；
- diagnosis_bundle 是证据真值，viewer/HTML/narrative 是投影；
- runtime/GDB 以 additive overlay 合并，不覆盖原始录制；
- source/data/binary 变化后，旧 index、memory、plan 不得静默复用；
- 功能、变量、数组下标、ROI 形式和输出链由当前 source/data/runtime 动态确定。

三条业务链：

| 链 | 顺序 | 责任 |
|---|---|---|
| 数据准备 | intake → data-prep → transfer → source/CUDA/patch plan → build/start | 绑定真实远端环境 |
| 静态预检 | bag/folder → cr60-precheck → bundle/viewer → event/timeline → HTML/index | 发现事件、属性、源码条件和缺口 |
| 深度诊断 | public evidence → code path → GDB plan/run/attach → runtime merge → report/Pi | 补充中间变量和根因证据 |

## 5. 原子能力现状

单一注册源：ai/capability/registry.py。
Pi JSON 边界：ai/capability/pi_tool_bridge.py。
生成扩展：.pi/extensions/radar-capabilities.ts。

本次盘点：

- Capability catalog：65
- Pi-visible：58
- duplicate names：0
- registerTool blocks：58
- bridge calls：58

| 能力 | 责任 | 当前状态 |
|---|---|---|
| pi | 唯一对话/编排入口 | 入口和帮助已验证，现场长链待验收 |
| cr60-intake | 材料/数据/版本/车型/COEM 绑定 | 已实现 |
| cr60-precheck | 调用独立 harness 产出 Sprint1 bundle/HTML | 已实现 |
| code-context-refresh / code-learn | 当前 source snapshot、CodeGraph、增量学习 | 已实现，需补 output 相关文件覆盖 |
| event-code-path / condition-trace | 当前事件的源码路径和同帧条件代入 | 已实现 |
| alert-timeline / diagnosis-report | 跨层报警时间线和 JSON/MD/HTML | 已实现，本轮加入 output chain |
| public-topic-plan / public-evidence-audit | arbe 公共逐帧证据 | 已实现 |
| runtime-debug-plan / gdb-service | GDB 计划和通用执行边界 | 已实现，需补下游映射探针 |
| runtime-debug-run / runtime-debug-attach | 隔离/正式 runtime | 已实现，现场权限/通信待补 |
| runtime-evidence-* | 归一化、验证、合并 | 已实现 |
| arbe-preflight / arbe-build/start/stop | 环境、源码、配置、二进制和生命周期 | 已实现，完整审批现场待验收 |
| analysis-run/step/claim | 可恢复调查账本 | 已实现 |

新增能力前先判断能否扩展已有 engine/module/schema；不要因为新增一个功能就创建重复 tool。

## 6. 真实环境和数据证据

### 6.1 远程环境

本轮通过 SSH 只读刷新确认：

- host：10.190.171.44
- user：hoz2wx
- arbe_root：/home/hoz2wx/CR60LIGHT/cr60_light_arbe
- algo_source：/home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/algo_source
- COEM：BYD_UKE
- outer HEAD：4c171298b2c3583509ea9e3da222b90ba0a9e513
- algo HEAD：a81b08a38f316a3d25bfcbcad6dcfc822d24b990
- HILMODEL=2 / BUILDMODEL=2
- binary sha256：93a8f2b2c11a6d8ba1abadbc7eb480e8867352f261a71c4bb5023f4c4ef80890
- GDB：/usr/bin/gdb, GNU gdb 12.1
- ptrace_scope：1

远程 outer/algo 工作区是 dirty 的，后续 runtime 结果必须保留 non-reproducible 说明。

### 6.2 真实 bag/event

- bag：/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
- event：FCTA_R / R
- radar：2 / Front_Right
- selected frame：47877
- objID：44
- algorithm index：0
- warmup：47872 → 47877, 5 frames
- algorithm output rising frame：47876

47877 是分析/GDB 活动帧，报告同时保留算法输出上升沿 47876，不得把二者混写。

### 6.3 GDB 已观察字段

当前报告引用的 gdb-session.v1 / runtime-case-evidence.v1 已确认：

- frameID=47877
- radar_id=2
- object_id=44
- i=0
- adasWarning->bRightFctaWarning=2
- bFctaRightWarningFlg=true
- objInfo->trcOutData[i].rightFctaFlag=true
- objInfo->trcOutData[i].objFctaWarningFlag=5
- g_egoCarAddInfo.carSpd=4.42844534
- rightFctaRoi->num=10
- fTTMX=1.01918888 / fTTMY=0.564559579
- fInterX=8.38272381 / fInterY=0
- observed fields=173 / missing probes=10

这证明 GDB 在目标算法路径生效并获取了大量实时字段，但不能证明 ASW 对外映射函数在同一停点已经执行。

## 7. 报警终点和 output chain

arbe GUI 报警灯链路已核对为：

algo_adasWarning
  → visualization_node.cpp
  → /corner_radar/warning_status
  → viewpanel.cpp adas_warning_status[radar_id][index]
  → 对应报警灯

逐帧定位通道是 /corner_radar/warning_status_with_frame。默认 output_policy 以 arbe 报警灯对应的算法最终输出为报告终点；对外 signal 是后续映射证据。

本轮新增 diagnostic-output-chain.v1，顺序为：

algorithm_output
  → fct_internal_assignment
  → external_mapping
  → transport_mapping

当前真实 FCTA_R 链：

adasWarning->bRightFctaWarning=2
  [GDB frame=47877, observed]
  → AdasStM.Frontright_FCTA =
    ADAS_Warn_Process_FrontRight_FCTA(PEROutput.adasWarning.bRightFctaWarning)
    [ADAS_HMI.c:3623, source_active]
    [ADAS_Warn_Process_FrontRight_FCTA definition: ADAS_HMI.c:3091]
  → RRadar_FCTA_Warning_Right_S =
    (AdasStM.Frontright_FCTA == 2) ? 1u:0u
    [RteComMapping_Tx.c:147, source_candidate]
  → RteLite_Write_RRadar_FCTA_Warning_Right_S
  → Com_SendSignal [rteLite_PubCan_FCRonly.c:177, source_candidate]

当前 AdasStM.Frontright_FCTA 尚未被该 GDB 停点直接观察，所以不能写成对外 signal 已发送。

## 8. 本轮验证

已验证：

- python cli.py --help、python cli.py pi --help；
- python cli.py capabilities --json、python -m ai.capability.pi_tool_bridge --list；
- 真实远端 preflight：outputs/arbe_preflight_refresh_20260903_output_chain_v3.json；
- 真实详细报告：outputs/single_case_actual_CRGVI1829_20260903_final/diagnostic-report.html；
- report/narrative/output-chain/preflight schema；
- HTML 页面加载、条件表、数据表、场景图、FCT 映射卡；
- 产品 gate 定向测试：127 passed in 17.42s；
- 没有执行全量回归。

本轮还完成了一次定向清理：删除旧 V2/V3 规划、重复 CodeGraph 阶段 handoff、旧 phase/taskboard
和旧审查文档；保留当前统一产品主线、production/Gen5/ROS 研究和历史 runtime handoff。
outputs 删除了 26 个无引用或已被替代的顶层重复目录、11 个同案重复报告子目录和 87 个重复/临时
顶层文件，保留最新报告、当前 runtime/source 证据、AnalysisRun 及仍有 provenance 价值的历史证据。
清理前约 1.9 GB、1080 个文件；当前约 1.17 GB、850 个文件。剩余 output 仍是本地证据缓存，未纳入
产品提交。研究报告中对已删除历史报告的引用已改为当前统一报告入口，未留下失效的本轮清理引用。

## 9. 未闭环事项

| 事项 | 当前状态 | 后续证据 |
|---|---|---|
| FCT 内部信号 runtime 值 | source path 已找到，GDB 未抓到 | 映射执行点 GDB |
| 对外 signal runtime 值 | source expression 已找到 | writer 参数/返回值观察 |
| 正式 GUI parity | GUI source mapping 已知 | 同一 formal start 逐帧核对 |
| formal PID attach | ptrace_scope=1 可能阻断 | 用户允许的权限/启动方案 |
| public object exact frame | 部分 publication-order derived | callback stamped snapshot/GDB |
| output exact edge | 47876 与分析帧 47877 分离 | with-frame 同帧 edge 证据 |
| 点云 150–200 帧 | 只记录策略 | HILMODEL=1 现场 trace |
| 多报警真实现场 | 静态数据模型支持，主实测为 CRGVI-1829 | 多功能/多次报警 bag |
| Pi 现场长链 | catalog/CLI/bridge 已验证 | 独立 Pi 对话验收 |
| 第二个 Gen6 项目 | schema/provider 已设计 | 第二车型/COEM smoke |

## 10. 接手者执行顺序

1. 先读本 handoff、TODO、PRD、DDD acceptance、software design 和 research report。
2. 分类当前 dirty worktree，形成 commit scope；不 reset/clean。
3. 完成 TODO 的 P0：输出链 GDB 计划、单数据 runtime、失败路径、长链 AnalysisRun。
4. 用当前 CRGVI-1829 单条数据重新验收，再验证多功能/多次报警和文件夹批量。
5. 最后才做选择性提交和推送。

每项完成后都要记录输入、artifact、source/data/binary identity、测试、已知缺口和下一步。

## 11. 提交/清理交接要求

可清理文件必须同时满足：是临时生成物、不是用户输入/产品代码/正式文档、结论已经迁移到文档、并且有删除清单。本轮已删除 _capabilities_check.json、.playwright-cli/、旧 V2/V3 文档和一批重复 outputs；仍保留的大型历史 evidence 暂不删除，SQLite *.db-shm/*.db-wal、scripts/_*.py 和一次性扫描脚本列为后续独立清理项。

建议提交：

feat(product): complete Pi-driven CR60 diagnostic capability platform
docs(handoff): record productization audit and next execution plan

目标分支尚不存在时，用户已授权的后续执行者可以：

git push -u origin HEAD:codex/ros-debug-autonomous

不得强推、不得覆盖 main、不得提交凭据或大型数据。

## 12. 交接给后续 Agent 的提示

- 真实 token、函数、行号必须来自当前 source context/preflight，不得从本例固化；
- not_evaluable 不能当作 false；
- source assignment 不能当作 runtime execution；
- 不跨 radar 借用 objID 或 i；
- 当前 polygon、ROI gate、未来预测点和 TTM 必须分开解释；
- 用户需要自然语言结论，技术 token 放在表格、折叠源码和调试区；
- 每个阶段先更新 AnalysisRun/Step、TODO 和 handoff，再继续开发。
