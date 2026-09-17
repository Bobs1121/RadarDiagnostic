# Gen6 AI：现状、环境、旧文档继承与差距

日期：2026-09-16 · 本轮为文档/有限源码核对，不是完整代码审计或远端健康检查。

## 1. 证据登记

| 来源 | 本轮读取内容与继承信息 | 边界 |
|---|---|---|
| [旧调研报告](../archive/2026-09-17/CR60_PI_UNIFIED_RESEARCH_REPORT_2026-08-26.md) §23 | arbe 仿真、公开 topic、GDB、几何、最终输出链、多次实现记录 | H：不同日期/版本，不能合并为一套当前运行事实 |
| [用户流程确认表](../archive/2026-09-17/technical/CR60_PI_UNIFIED_USER_WORKFLOW_QUESTIONNAIRE.md) §2.1 | 数据→版本/COEM/车型 CUDA→编译→启动→播放→debug；报警首帧的 CAN 输出语义 | H：业务口径继承；宏/预热/原仓默认被本轮更新 |
| [arbe 复用调研](../archive/2026-09-17/technical/CR60_PI_UNIFIED_ARBE_REUSE_ASSESSMENT.md)、[架构复盘](../archive/2026-09-17/technical/CR60_PI_UNIFIED_ARCHITECTURE_REVIEW_2026-08-30.md) | BagReader event/scene 与 ACK；ObjectList 无可靠算法 frame；统一工作页与证据账本 | H：运行前核对当前工具组仓库接口 |
| [旧系统](../archive/2026-09-17/technical/CR60_PI_UNIFIED_SYSTEM_DESIGN.md)、[模块](../archive/2026-09-17/technical/CR60_PI_UNIFIED_MODULE_DESIGN.md)、[软件设计](../archive/2026-09-17/technical/CR60_PI_UNIFIED_SOFTWARE_DESIGN.md) | 控制/证据/解释/状态职责；版本化 artifact；provider 窄适配 | D/H：继承责任划分，不继承强制全程流水线 |
| [仿真分析复盘](../archive/2026-09-17/technical/SIMULATION_ANALYSIS_DDD_REVIEW_2026-09-11.md) | raw dotTrans 版本布局、注入覆盖、reset/warmup/completion、identity 与本地回归补足 | H：日志多次追加，测试计数不代表当前发布能力 |
| [独立运行指南](../archive/2026-09-17/technical/CR60_PI_STANDALONE_RUN_GUIDE.md) | Python CLI→Pi RPC→生成扩展→Python bridge；外部运行依赖与环境变量名 | H/C：入口代码可见，零配置安装未证明 |
| [历史发布清单](../archive/2026-09-17/technical/release_acceptance.v1.json) | M0～M4/PC-AC 的 accepted/partially-verified 及 evidence refs | H：旧 scope 声明，非新整体验收 |
| [09-15 preflight](evidence/arbe_preflight_remote_refresh_20260915.json) | `blocked`、`remote_probe_timed_out`；目标 `_0909int` 工作区 | H：本轮读取产物，未重连服务器；不能由此断言今天仍故障或已恢复 |

## 2. 当前源码可见能力（C）

| 当前入口 | 本轮确认 | 尚不能据此宣称 |
|---|---|---|
| `ai/modules/pi.py`、`ai/pi_bridge.py` | `_select_pi_tools`、context 绑定、RPC 调用、AnalysisRun/tool step 记录，超时参数 | 任意问题均可自主完成或所有错误均可恢复 |
| `ai/capability/registry.py`、`pi_tool_bridge.py`、`scripts/gen_pi_extension.py` | catalog、工具桥和生成 registerTool 的责任链存在 | schema 注册等于能力可执行或完整副作用授权闭环 |
| `engines/analysis_ledger.py` | run/step/claim/hypothesis/experiment 持久化、锁及原子写入辅助逻辑 | 已有完整跨进程执行 Supervisor |
| `engines/analysis_workbench.py`、`ai/modules/analysis_workbench.py` | `analysis-workbench.v1` 只读投影与 JSON/HTML 产物 | 已有实时服务、浏览器动作回写及场景/代码联动成品 |
| `engines/event_code_path.py` | build_event_code_path、layer、source refs、required runtime tokens | 每个复杂别名/循环/跨帧因果链均能精确解析 |
| `engines/arbe/execution_binding.py` | identity derivation、binding build/verify | 所有执行器已在真正执行边界新鲜复核 |
| `ai/providers/cr60_harness.py` 与 provider 契约 | sibling harness 隔离 GDB/formal attach/start/stop adapter 责任明确 | 原生 GUI 和隔离回放在所有条件下等价 |
| `ai/code_fix_engine.py` | diff 建议、位置解析、安全审查、临时文件语法检查逻辑 | 隔离工作区真实应用→编译→验证闭环；`ai/modules/code_fix.py` 本轮不存在，目录和 CLI 注册需实际核验 |
| `tools/doctor.py`、`tools/release_gate.py` | 依赖/能力体检和 manifest gate 实现存在 | 干净机器可直接交付或新 G6 scope 已验收 |

本轮实际执行（V）：`python cli.py capabilities --json` 返回码 0，输出能力目录；仅验证目录入口可运行，未执行各 leaf，也未重新运行全量测试。当前工作树含大量修改与未跟踪模块，不能把 HEAD 或历史提交当当前完整身份。后续审计保存 dirty 内容指纹和边界。

## 3. 环境与配套资产清单

| 资产 | 已有信息 | 新运行必须确认 |
|---|---|---|
| 本地产品仓 | `D:\RamboStar\idea\radarAnalyze`，PowerShell/Python；Pi 外部 RPC | 实际 Python/Node/Pi/模型 provider 版本与依赖 health |
| 独立 harness | 历史 sibling `D:\RamboStar\idea\cr60-debug-harness` | CLI/contract compatibility、版本、路径可用性；不可硬编码全局路径 |
| 远端主机 | 历史 `10.190.171.44`，用户 `hoz2wx`；2026-09-17 只读探测：TCP22 超时、ICMP 由本机栈报 Destination host unreachable（无路由/ARP），网络层不可达，与 09-15 preflight 超时一致（证据 `docs/technical/evidence/gen6_remote_probe_20260917.json`） | 恢复/变更后重测；真实案例数据存于该服务器，本地 `cases/` 非真实数据；SSH 连通、权限、磁盘/内存、运行中会话；无需索要密钥正文 |
| arbe 工作区 | 历史 `/home/hoz2wx/CR60LIGHT/cr60_light_arbe`；较新 preflight `/home/hoz2wx/CR60LIGHT/cr60_light_arbe_0909int` | 以当前明确 profile 解析目标；不能擅自选择最近目录 |
| 算法 | arbe 的 `src/algo_source`，COEM 子目录与车型配置 | branch/ref→commit、dirty bytes、COEM/vehicle、录制版本映射的权威材料 |
| 构建/启动 | 历史 `catkin_make`、`bash start`；ROS Noetic `/opt/ros/noetic/setup.bash` | 当前构建脚本、有效宏、编译参数、符号与 executable |
| CUDA/车型参数 | `08_CustData` 候选、launch_config_4radars.yaml 的 xlsx/sheet/type；历史 BYD_UKE/03_QZH | 当前车型匹配、真实文件 hash，不复用历史客户配置 |
| 输入 | 单 bag＋问题，大部分有视频；可能来自 UNC/SMB/远端目录 | 可读路径、size/hash、录制协议、时间基准与视频关联 |
| 辅助工具链 | `bosch-data-transfert`、arbe build/启动脚本等既有 provider 接入来源 | 配置路径和版本、输入输出、安全参数传递；不复制执行逻辑 |

配置推荐延续最小 `project_intake`；用户仅在首次绑定工作环境或身份冲突时补充信息。生成 variant-scoped `.workspaces/<variant>/`，保存 source_docs、memory、索引、snapshot 等。代码快照可以本地缓存，但必须证明与实际执行的远端源码/config/binary 对齐。

## 4. 旧设计冲突裁决

| 历史表达 | 本轮统一处理 |
|---|---|
| production 系列固定管线，Agent 只补查 | Pi 总体调度；固定 pipeline 仅兼容能力 |
| 正式 bash start/PID attach 优先、原仓可改 | 用户本轮确认默认独立分析会话；正式会话显式选择；原仓旧许可不等于当前任意写入许可 |
| HILMODEL=2、SGU 3～5 帧、点云 150～200 帧 | 特定历史 profile 线索；当前源码/构建/状态验证后决定，不做全局默认 |
| 所有 GDB/symbol gate 都阻断整个诊断 | 仅阻断依赖该证据的实验/结论；静态可继续 |
| PlaySingleFrame 可控制跳转或播放 | 历史研究证明是 ACK；需独立能力探测，不能伪造 seek API |
| ObjectList 接近 warning 的时间可直接同帧 | 保留 unbound/derived 标签；需要同 callback/frame 证据才能用于精确条件 |
| 最终报警等同公共 warning 或 GUI 灯 | 继承算法向 CAN 输出的事件口径；内部/代理/Tx/录制 CAN 分层，缺层不冒充 |
| 无效/恒定值一律剔除 | 无效值拒绝；恒定只触发检查，不能单凭恒定判断无效 |
| 总是 Top-3 或修复复验后才允许根因 | 最多三个有区分价值候选，不强凑；行为解释、因果支持、用户裁决、修复验证分别表述 |
| 单数据单雷达开发成功等于产品完成 | 可作切片；产品需多雷达多事件、失败/无报警、可用性和性能验收 |
| standalone ready 或旧 gate green | 仅对应受测范围；新 scope 尚 pending |

## 5. 核心缺口与优先验证

1. 首次上手到首个可信成果是否无需用户准备内部 JSON/路径/索引。
2. 完整执行监督与授权恢复，隔离 workspace、进程所有权、数据/代码/binary 一致性。
3. 实时工作页：当前只读投影与目标的差距；用户动作到同一 Pi/run 的回流。
4. 点云真正执行与精准变量/帧绑定，最终输出端点、视频对齐和状态预热。
5. 从有依据的建议到真实补丁/编译/回灌/比较的缺口。
6. ≤10 GB 端到端解析/检索/模型/回放成本，以及用户实际省时。

本表是范围明确的核查结论，不以“未在所读文件找到”证明全仓没有实现。实施 WP0 对每项做最终定位和测试，沿用当前能力而非重写。
