# radarAnalyze

## 当前 DDD 设计入口（2026-09-16）

持续开发必须先读 `docs/technical/GEN6_AI_EXECUTION_PROTOCOL.md`、`GEN6_AI_SPRINT_PLAN.md`、`gen6_execution_state.v1.json` 和 `GEN6_AI_HANDOFF.md`。每轮按依赖选择一个主集成切片，完成跨模块验证、自审和状态落盘后继续；不得将文档检查/旧 scope 的 gate 通过当作 G6 产品完成。`python tools/check_ddd.py` 检查文档与任务一致性，当前 `release_acceptance.v1.json` 是唯一 G6 发布状态。归档中的旧并行任务和“不得改设计”等规则不约束新任务；本轮没有启动开发 goal。

后续产品和架构开发先读 `docs/technical/GEN6_AI_DOCUMENT_INDEX.md`，依次查阅产品、当前状态/环境、完整用户体验、系统/模块设计、实施和验收。新用户确认默认独立分析会话、Pi 对话＋实时工作页；少打断、自主和稳定覆盖完整旅程，不限代码变量。旧文档已移入 docs/archive/2026-09-17，仅作历史证据参考；设计状态、当前代码和真实运行验收必须分开。执行授权仍按实际任务范围判断，设计文档不构成远端写入授权。

Corner Radar AI 诊断工具：对 ADAS 功能（BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB）的录制数据做自动化根因分析。

## 产品主链路（实现边界）

本项目是 **AI 诊断 Harness**，不是规则诊断器。核心链路固定为：

1. 用户疑问驱动检索相关功能、源码调用链、参数边界和需求约束
2. 数据管线只筛选并预处理最相关的信号、对象和时间窗口，控制上下文规模
3. 将实际数据值按确定的 CAN/内部变量转换回填到代码条件与调用链
4. Harness 输出可追溯证据、冲突和缺口；条件检查是证据标注，不是诊断硬门槛
5. AI 负责跨代码、数据、需求和案例知识做根因推理、Top-3 排序和下一步验证建议
6. Auto Dream 负责按 variant/customer/branch 隔离固化可复用知识，并通过 freshness 机制更新；不替代当次诊断

优化优先级应围绕“检索更准、窗口更小、映射更可靠、证据可追溯、AI 推理空间充分”，
避免扩张成复杂规则引擎或把未支持表达式直接判为条件失败。

### 用户交互约束

真实用户不应被要求理解 `frameID`、`radar_id`、`objInfo->trcOutData[i]`、ROI 点、PID、
GDB 表达式或源码行号等实现细节。Pi/工具应先从材料、当前 source context、binary 和
运行时探测中自动获取这些字段；只有当业务语义、证据口径或副作用授权会改变结果时，才
用业务语言向用户提问。无法确认技术候选时，先输出静态/隔离分析和缺口，不用用户猜测
技术答案；所有技术事实仍必须保留真实 token、来源和 provenance。

### 知识新鲜度硬约束

- variant 运行中，freshness 缺失、不可用或输入签名不匹配的学习产物不得进入 AI prompt
- Auto Dream 使用 `knowledge_manifest.json` 按能力模块发布；只发布本次成功刷新的 scope，失败模块继续 stale
- 功能知识使用细粒度 scope，如 `conditions:RCTA`、`source_docs:RCTA`、`code_knowledge:RCTA`
- 当前代码 commit/hash 变化会自动使旧 manifest 签名失配，无需删除旧文件，也不得回退到其他项目的全局 L6
- `signal_mapping` 等确定性、自带源文件 hash 的产物可以先重建后使用；不能自证新鲜的知识一律 fail closed

## 运行模式

| 模式 | CLI 入口 | 核心模块 |
|------|----------|----------|
| **pi 对话（V4）** | `cli.py pi "..."` / `cli.py pi` | 外部 Pi RPC + 生成的 `registerTool` + `ai/capability/pi_tool_bridge` — 唯一产品入口和总体编排 |
| **Pi 能力目录** | `cli.py capabilities --json` | 只读输出当前注册且可暴露给 Pi 的原子能力；用于操作员/CI 校验，不执行能力 |
| **signal-extract（V4）** | `cli.py signal-extract "车速" <case_dir> --plot` | `ai/modules/signal_extract.py` — 数据抽取 + 曲线 |
| **code-learn（V4/P5）** | `cli.py code-learn [--aggressive] [--no-ast]` | `ai/modules/code_learn.py` + `ai/codegraph` — AST 建图/增量刷新 CodeGraph |
| **code-analyze（V4/P5）** | `cli.py code-analyze --kind call_chain --name F --max-results 200` | `ai/modules/code_analyze.py` + `ai/codegraph/query` — 调用链/依赖/语义；列表默认有界返回 200 项并标注截断计数 |
| **sim-verify（V4/P4）** | `cli.py sim-verify --case-dir ... --mode local|remote_public` | `ai/modules/sim_verify.py` + `engines/arbe/` — 本地 trace/KPI 或远程公共 ROS 回放解析 |
| **point-cloud-plan / point-cloud-analyze / point-cloud-read / point-cloud-batch / point-cloud-validate** | `cli.py point-cloud-plan ...` / `cli.py point-cloud-analyze ...` / `cli.py point-cloud-read ...` / `cli.py point-cloud-batch ...` / `cli.py point-cloud-validate ...` | `ai/modules/point_cloud_plan.py`、`ai/modules/point_cloud.py`、`ai/modules/point_cloud_read.py`、`ai/modules/point_cloud_batch.py`、`ai/modules/point_cloud_validate.py` + `engines/point_cloud_replay.py` — 点云计划、source-bound 公开阶段/lineage、run/reset/warm-up、bounded report query、批次报告和独立 validation；raw `dotTrans` 必须绑定录制版本兼容性，freshness 需 context/plan/run identity 对齐；read 不重新分析、不启动 ROS |
| **arbe-execution-binding** | `cli.py arbe-execution-binding --plan-path ...` | `ai/modules/execution_binding.py` + `engines/arbe/execution_binding.py` — 生成 approved replay 的 identity-bound binding，不执行副作用 |
| **req-analyze（V4/P7）** | `cli.py req-analyze --req-dir <dir> --variant <id>` | `ai/modules/req_analyze.py` — 需求→代码 gap + requirement_trace |
| **Diagnosis** | `cli.py --mode diagnosis` | `ai/orchestrator.py` → 10+ 步管线（V4 中降级为 `diag` 能力之一） |
| **Query** | `cli.py --mode query` | `ai/data_query_engine.py` |
| **Dream** | `cli.py --mode dream` | `memory/auto_dream.py` → Phase 0-4 |
| **Project Init** | `cli.py project-init --name ... --code-root ... --dbc ...` | `ai/modules/project_init.py` |
| **Prewarm Timing** | `tools/measure_prewarm_timing.py --variant gen6/gwm_b26 --runs 2 [--source-docs-dir <isolated-dir>]` | `_run_prewarm` 缓存命中计时；RTE 选择绑定该 variant 的 `key_source_files`，默认走 variant 缓存，显式 override 可隔离首建/复用测量 |
| **Harness Gate** | `tools/run_harness_gate.py --allow-known-edge` | Harness 聚合回归 gate |
| **BSD Signal Validate** | `cli.py bsd-data-bridge --mode validate --mf4-path X.MF4 --output-dir source_docs` | `ai/modules/bsd_data_bridge.py` (M9) |

> **V4 架构说明**：本项目正从"固定 8 步诊断管线"演进为 **pi 统一对话入口 + registerTool 原子能力 + AI 灵活调度** 的能力平台。ReAct/AgentLoop 和直接 module CLI 只保留为离线/开发 fallback。
> 详见 `docs/technical/GEN6_AI_SYSTEM_DESIGN.md`（设计）· `docs/technical/GEN6_AI_SPRINT_PLAN.md`（Sprint）· `docs/technical/GEN6_AI_EXECUTION_PROTOCOL.md`（持续开发执行规范，开发前必读）。

## CLI real intake context

- Daily diagnosis should usually run as:
  `python cli.py cases/FCTB001/ -p "..." -e "..."`
- New CR60 Light onboarding should usually run as:
  `python cli.py project-init --name "CR60 Light BYD SC6H" --code-root D:\cr60_light --customer BYD --vehicle-project SC6H --coem-project BYD_SC6H --dbc D:\dbc\primary.dbc --requirements D:\cr60_light\coem\BYD_SC6H\requirements --expected-branch master --case-dir D:\cases\CASE001`
- User-facing `config.local.yaml` should prefer the minimal `project_intake` schema (`code_root`, `branch`, `coem`, optional `data`, `dbc`, `requirements`); internal `codebases` / `variants` / workspace paths / package profiles / knowledge policy should be generated by `config.load_config()`.
- When `config.local.yaml` sets an effective `default_variant`, `config.load_config()` must derive legacy-compatible `paths.source_code` / `key_source_files` / `dbc_files` / `source_docs` and active `source_domains` from that variant; `default_project` and global legacy domains are only fallbacks when no variant resolves.
- Daily diagnosis does **not** auto-run dream/code learning; use `--prewarm`, `--dream`, or single-run `--auto-dream` intentionally.
- If a case folder contains `case.yaml`, `case.yml`, or `metadata.json` identity metadata, CLI can auto-select the matching variant before falling back to `config.local.yaml` `default_variant`.
- Source code root, expected branch, and mismatch policy now live in `config.yaml` under top-level `source_context`, with optional per-variant override at `variants.<variant_id>.source_context`.
- New onboarded variants should keep generated `source_docs` / `memory` / `semantic index` / `codegraph` / `snapshots` under `.workspaces/<sanitized-variant>/` via variant-scoped `source_context` paths; do not mix caches across variants.
- Each variant memory carries deterministic `freshness_state.json` and `knowledge_manifest.json`; CLI compares current code/DBC/requirements/identity fingerprints before diagnosis/query/prewarm/dream, and only publishes successfully refreshed module scopes whose inputs stayed stable during the refresh.
- For the priority CR60 Light path, `code_root\coem\<customer_project>` is already the isolated customer code set, so do **not** model SIT/FCT as a separate onboarding dimension or package-profile split.
- `runtime.auto_dream_on_case_start` exists for explicit legacy opt-in and defaults to `false` when absent.
- `--source-root`, `--code-branch`, and `--allow-branch-mismatch` remain temporary per-run overrides only.
- Source-context validation/freshness probing are reporting-only: they never watch files continuously, and never check out, fetch, pull, or otherwise mutate the target git repo.

## 诊断管线步骤概览

| Step | 名称 | 模块 |
|------|------|------|
| 1 | init — source_docs / CodeGraph 保障 | `orchestrator._ensure_source_docs` |
| 2 | classify — 理解 + 分类 | `orchestrator._understand_problem` + `problem_classifier.classify` |
| 3 | extract — 数据解析 + 窗口检测 | `case_loader.load_case_data`（ParserRegistry 分发）+ `test_window_detector.detect` |
| 4 | evidence — 帧证据 + 条件 + TPE + probe + 确定性调查 | `frame_analyzer` / `condition_extractor` / `tpe` / `data_probe` / `investigation_engine`（EngineeringInvestigator） |
| 5 | signals — 抑制/输出/参数 | `_check_suppression_signals` / `_analyze_output_signals` / `parameter_analyzer` |
| 6 | diagnose — 专家面板 | `expert_panel.run_panel` (LLM, 3 轮) |
| 7 | fix — 修复建议 | `code_fix_engine` |
| 8 | deliver — 报告/可视化/记忆/Bundle | `visualizer` + `memory_system` + `DiagnosisBundle` |

## 目录结构与文档导航

```
radarAnalyze/
  cli.py                  # 统一 CLI 入口
  config.yaml             # 模型/路径/功能/学习 配置
  engines/                # 确定性引擎（无 LLM，可独立测试）→ temporal_analyzer / tpe / pattern_extractor / causal_aligner / data_probe / parameter_analyzer / test_window_detector / frame_analyzer / signal_mapper / signal_audit
  ai/                     # AI 分析模块（LLM 推理层）→ 详见 ai/AGENTS.md
    agent/                # 真 ReAct Agent（ReActPlanner：LLM 规划 + AgentLoop 确定性执行）
  core/                   # 身份/材料/诊断包模型 + plugin.py（统一插件注册表）→ 详见 core/AGENTS.md
  parsers/                # 数据解析层  → 详见 parsers/AGENTS.md
    plugins/              # ParserPlugin SPI：bag/blf/mf4 可插拔解析
  memory/                 # 记忆系统    → 详见 memory/AGENTS.md
  source_docs/            # 缓存知识    → 详见 source_docs/AGENTS.md
  cases/                  # 案例数据（.bag/.blf + 报告产物）
  scripts/                # 冒烟测试与 workspace 迁移脚本
  tools/                  # 辅助工具 → 详见 tools/AGENTS.md
  tests/                  # 测试（test_temporal_pattern_engine）
  docs/archive/           # 历史实现与设计资料，仅供证据查阅
```

> **架构说明**：确定性引擎统一收拢到 `engines/`（无 LLM 依赖），LLM 推理/编排在 `ai/`。插件通过 `core.plugin.PluginRegistry` 注册（parser 在 `parsers/plugins/`、平台适配器在 `ai/platform_adapters/`）。`ai/__init__.py` 惰性导出 `Orchestrator`/`CodeLearner`/engine 符号；`import ai.signal_mapper`（子模块形式）已不可用，请用 `from ai import signal_mapper` 或 `from engines import signal_mapper`。

## V4 能力模块速查（pi 驱动架构）

> V4 把能力封装为 `Engine + BaseTool + BaseModule` 三件套，由生成的 Pi `registerTool`
> 暴露给统一入口；每个能力可独立测试/CLI，但用户编排统一由 Pi 完成。详见
> `docs/technical/GEN6_AI_SYSTEM_DESIGN.md`。

| 能力 | name | 独立 CLI | 职责边界 |
|------|------|----------|----------|
| 数据抽取 | `signal-extract` | `cli.py signal-extract "车速" <case> --plot` | 信号查找/抽取/绘图 |
| 数据分析 | `data-analyze` | `cli.py data-analyze ...` | 统计/分布/窗口/TPE |
| 代码学习 | `code-learn` | `cli.py code-learn ...` | 代码索引/条件/映射（AST→索引→按需检索） |
| 代码分析 | `code-analyze` | `cli.py code-analyze ...` | 调用链/依赖/语义；列表结果按 `max_results` 有界返回并显示 `result_bounds` |
| 问题诊断 | `diag` | `cli.py diag ...` | 完整 8 步管线（保留，V3 兼容） |
| 代码修复 | `code-fix` | `cli.py code-fix ...` | 代码修改建议（diff） |
| 仿真验证 | `sim-verify` | `cli.py sim-verify ...` | arbe 回放 + KPI/结果验证 |
| arbe 环境预检查 | `arbe-preflight` | `cli.py arbe-preflight --host ... --arbe-root ...` | 只读探测 arbe/source/config/binary/GDB/进程/CAN Tx 候选 |
| arbe 源码版本解析 | `arbe-source-resolve` | `cli.py arbe-source-resolve ...` | 只读确认当前 algo_source、版本到 ref 的显式映射、local/remote ref 和 dirty 状态；不 checkout/fetch |
| arbe CUDA/config 解析 | `arbe-cuda-resolve` | `cli.py arbe-cuda-resolve ...` | 只读扫描当前车型 08_CustData、选择真实候选并核对 YAML；不复制/改配置 |
| arbe 仿真补丁计划 | `arbe-patch-plan` | `cli.py arbe-patch-plan ...` | 只读按配置检查仿真适配、文件 hash 和 dirty diff；不应用补丁 |
| CR60 输入绑定 | `cr60-intake` | `cli.py cr60-intake --data ... --material ...` | 材料优先解析数据/软件版本/车型/COEM/分支并保留 provenance；冲突或缺失时 fail-closed |
| CR60 数据传输前校验 | `cr60-data-prep-verify` | `cli.py cr60-data-prep-verify --intake ... --execute` | 只读映射 Linux 数据路径并核对文件/大小/SHA-256，可选核对目标目录；不复制 |
| CR60 数据传输执行 | `cr60-data-transfer` | `cli.py cr60-data-transfer --script-path ... --input-path ... --destination-root ...` | 审批后调用已配置的 `bosch-data-transfert` 远端脚本；不复制脚本逻辑 |
| CR60 Sprint1 预检查 | `cr60-precheck` | `cli.py cr60-precheck --mode ...` | 通过窄 adapter 调用独立 harness，生成 bundle/viewer/HTML；默认只生成计划 |
| 公共逐帧证据 | `public-topic-plan` / `public-evidence-audit` | `cli.py public-topic-plan ...` / `public-evidence-audit ...` | 规划和审计不依赖 GDB 的 LGU/ego/SGU/object/warning/ROI 证据；plan 保留 preflight server/workspace identity，供单消息 sample role 匹配时 fail-closed 校验 |
| 代码→GDB 指令 | `code-gdb-plan` | `cli.py code-gdb-plan ...` | 基于当前 code-index 定位真实函数/源码行，生成调用者条件下的 GDB commands |
| 通用 GDB 服务 | `gdb-service` | `cli.py gdb-service ...` | 只接收 target+commands；不内置功能断点，执行必须批准 |
| Runtime 证据规范化 | `runtime-evidence-normalize` | `cli.py runtime-evidence-normalize ...` | 将 GDB session/transcript 归一为 `runtime-case-evidence.v1`；保留真实 token/status，不绑定功能 |
| Runtime 证据校验 | `runtime-evidence-validate` | `cli.py runtime-evidence-validate ...` | 校验 schema、source/data/binary identity 和事件匹配；不修改产物 |
| Runtime 证据编排 | `runtime-evidence-compose` | `cli.py runtime-evidence-compose ...` | 合并已规范化的公共 runtime/GDB producer，保留各自历史和比较；不覆盖原 producer |
| Runtime 证据合并 | `runtime-evidence-merge` | `cli.py runtime-evidence-merge ...` | 将运行时证据以 additive overlay 合并到 bundle；身份冲突时禁止消费引用 |
| Runtime Debug 计划 | `runtime-debug-plan` | `cli.py runtime-debug-plan ...` | 按当前事件/source/preflight 生成 readiness gates、真实断点、GDB commands 和 VS Code handoff；只规划不执行 |
| Runtime Debug 执行 | `runtime-debug-run` | `cli.py runtime-debug-run ...` | 执行已批准的 plan-bound 隔离 ROS/GDB runner，并落盘 `gdb-session.v1`；默认只计划 |
| Formal arbe 启动 | `arbe-formal-start` | `cli.py arbe-formal-start ...` | 受审批启动正式 `bash start`，避免重复节点并记录 tool-owned session；默认只计划 |
| Formal arbe 停止 | `arbe-formal-stop` | `cli.py arbe-formal-stop ...` | 受审批停止且仅限 tool-owned、process-group 可证明的正式 session |
| Arbe 编译 | `arbe-build` | `cli.py arbe-build ...` | 受审批执行显式 workspace 的 `catkin_make`，只负责 build，不切分支/CUDA/start |
| Formal PID Attach | `runtime-debug-attach` | `cli.py runtime-debug-attach ...` | 对已发现且 executable 校验通过的正式 `arbe_visualization_engine` PID 执行 plan-bound GDB attach；默认只计划 |
| ROS 公共通道盘点 | `ros-topic-inventory` | `cli.py ros-topic-inventory --topic ...` | 只读获取 topic 类型/发布者/订阅者；传入当前 `--preflight-path` 可绑定 preflight 文件 SHA/server/workspace；可选 schema inspect 和 `--sample-once` 产生有界字段目录、客户端 UTC 采样时刻、stdout hash/截断状态 |
| 公共运行态快照归一化 | `public-runtime-normalize` | `cli.py public-runtime-normalize --capture-path ... [--topic-plan-path ...]` | 读取 collector/capture 或 `ros-topic-inventory.v1`；保存采样/消息 hash；按当前消息字段目录展开 ObjectList，无共同消息序号时不跨 topic 绑定报警帧 |
| 需求分析 | `req-analyze` | `cli.py req-analyze --req-dir <dir> --variant <id>` | 需求→代码 gap + requirement_trace |
| 记忆 | `memory` | `cli.py ...` | 记忆读写/召回/沉淀 |
| **对话中枢** | `pi` | `cli.py pi --question "..." [--tools ...] [--task-scope case_analysis|source_code] [--thinking ...]` | 意图理解/规划/调度/综合（唯一产品入口）；source_code 查询不要求录制数据，仍绑定 code-context snapshot |
| **Pi 编排上下文** | `pi-context` | `cli.py pi-context --task-scope case_analysis|source_code ...` | 组装 `pi-orchestration-context.v1`；case_analysis 显式绑定案件数据，source_code 可无 case；Pi 按有效 variant 配置自动刷新/复用 source snapshot，并校验 code-context/code-index 路径、schema、snapshot 与 hash |
| **项目能力清单** | `project-capability-manifest` | `cli.py project-capability-manifest --code-context ...` | 从当前 artifact 生成 Gen6 capability category、unsupported 和 freshness；不替代 `pi-context` |
| **Analysis Run** | `analysis-run-create` / `analysis-run-read` / `analysis-run-update` | `cli.py analysis-run-* ...` | 创建、读取和更新可恢复调查运行；不等同 Pi 对话 |
| **Analysis Step** | `analysis-step-record` | `cli.py analysis-step-record --action ...` | 持久化阶段输入、工具、观察、gap/conflict、摘要、下一步和成本 |
| **Feedback Review** | `feedback-review` | `cli.py feedback-review --analysis-run ...` | 只读汇总当前 run 的用户确认/否定/无关反馈，核验 binding 并返回 knowledge publish gate；不写 knowledge |
| **Feedback Knowledge Plan** | `feedback-knowledge-plan` | `cli.py feedback-knowledge-plan --feedback-review ...` | 校验候选 pattern 的 variant scope、用户确认、freshness 和显式批准；只生成 publish plan，不写 knowledge |
| **Feedback Knowledge Publish** | `feedback-knowledge-publish` | `cli.py feedback-knowledge-publish --publish-plan ... --knowledge-dir ... --approved` | 受 approval 的 variant-scoped RootCausePattern 写入 leaf；actor 必须 user，不接受普通 feedback 直写 |
| **Analysis Workbench** | `analysis-workbench` | `cli.py analysis-workbench --analysis-run ... --output-dir ...` | 将现有 AnalysisRun/ledger 投影为只读 JSON/HTML；不创建平行状态树、不写 ledger/knowledge |
| **Evidence Claim** | `analysis-claim-append` | `cli.py analysis-claim-append ...` | 追加 evidence-bound claim；AI 不能创建 `observed` claim |
| **Hypothesis / Experiment / User observation** | `analysis-hypothesis-record` / `debug-experiment-record` / `analysis-user-observation` | `cli.py analysis-hypothesis-record ...` 等 | 持久化候选状态、最小实验和人工回填；不执行 GDB，不把用户观察直接当 runtime |
| **Evidence Query** | `evidence-query` | `cli.py evidence-query --bundle ...` / `--runtime-snapshot ...` | 按事件/帧/字段从 bundle/viewer/runtime artifact 做有界查询；unbound ObjectList snapshot 可按 radar/消息字段查询，但不自动关联事件/报警帧 |
| **Diagnostic Report** | `diagnosis-report` | `cli.py diagnosis-report --bundle ... [--runtime-snapshot ...]` | 详细报告可携带独立 snapshot rows/evidence layer；unbound/identity-unbound 行保持 partial，不进入 selected event/condition trace |
| **Diagnostic Report** | `diagnosis-report` | `cli.py diagnosis-report --bundle ...` | 将静态/runtime/code/AI artifact 投影为详细 JSON/MD/HTML；AI 结果保持 inference |
| **Condition Trace** | `condition-trace` | `cli.py condition-trace --conditions ...` | 按当前 source 条件和同帧字段安全求值；输出满足/不满足/不可求值及来源 |
| **Memory Recall** | `memory-recall` | `cli.py memory-recall --project-root ...` | 读取 variant-scoped 历史记忆/相似案例；遵守 freshness，不写当前事实 |
| **Alert Timeline** | `alert-timeline` | `cli.py alert-timeline --bundle ...` | 将 raw/replay/runtime/GDB/CAN 报警按证据层和播放帧投影比较；缺层不伪造 |
| **Code Context** | `code-context-refresh` / `code-context-read` | `cli.py code-context-* ...` | 一次性读取当前 C/C++ source snapshot，生成/查询 `code-context.v1` + `code-index.v1`；RTE Tx mapping 按 COEM identity 选择并纳入 fingerprint，identity/path 缺失时不套用 legacy GWM |

**新增能力三步**：① 实现确定性 Engine（如需要）并提供 `BaseTool`/`BaseModule` 契约
（name/description/schema/run）；② 注册到对应 registry；③ 由 catalog/generator 自动
进入 Pi `registerTool`（无需修改总编排器）。

历史模块未声明 `input_schema` 时，catalog 会从 `run()` 签名和 `register_cli()` 自动
推导保守参数 schema，并复用 `from_cli_args` 构造映射；这只是兼容兜底，新模块仍应
显式声明 schema。

**质量属性**：每个模块须满足 开放/灵活/可靠/鲁棒/可插拔/AI 驱动/可观测（见架构文档 §8）。`run()` 必须返回 `ModuleResult`（不得抛未捕获异常）。

## 跨模块依赖速查

| 生产方 | 消费方 | 数据 |
|--------|--------|------|
| parsers/case_loader | orchestrator._parse_case_data | CaseLoadResult (store, bag_meta, blf_meta, sync, dbc) |
| engines/signal_mapper | orchestrator._run_tpe, _check_suppression_signals, code_learner, auto_dream | 当前 variant 的 RTE mapping（RX+TX 双向）与 `variable_chains`；COEM/source hashes 纳入 cache，缺失/歧义不回退 GWM |
| engines/signal_audit | orchestrator._run_signal_audit（Step 5）, ai/modules/signal_audit | 关键链路信号契约审计 markdown（枚举合法性 + UI 模式回传契约） |
| condition_extractor | orchestrator (conditions step) | {FUNC}_conditions.json |
| engines/frame_analyzer | orchestrator (analyze step) | evidence dict, frame_analysis str |
| engines/test_window_detector | orchestrator, frame_analyzer, data_probe | list[TestWindow] |
| engines/pattern_extractor | engines/tpe.TemporalPatternEngine | list[CodePattern] |
| engines/temporal_analyzer | engines/tpe, engines/causal_aligner | dict[str, TemporalFeature] |
| engines/causal_aligner | engines/tpe.TemporalPatternEngine | list[PatternEvidence] |
| engines/tpe | orchestrator._run_tpe | TPEResult |
| investigation_engine | orchestrator (evidence step), data_query_engine | InvestigationResult / ConditionCheck[]（确定性调查） |
| problem_classifier | orchestrator (classify step) | ClassificationResult |
| variable_query_planner | orchestrator (probe step) | list[QueryPlan] |
| engines/data_probe | orchestrator (probe step) | ProbeResult dict |
| expert_panel | orchestrator (diagnose step) | panel_result dict |
| engines/parameter_analyzer | orchestrator (params, tune/verify) | SensitivityReport, WhatIfEntry |
| core.materials | orchestrator (diagnose, bundle) | material summary, requirement_trace |
| context_budget | orchestrator (panel_prompt) | ContextBudget + compute_budget() → dynamic budget |
| visualizer | orchestrator (visualize step) | VisualizerResult |
| memory_system | orchestrator, auto_dream, data_query_engine | L1-L6 JSON 真值读写 + SemanticMemory provenance recall |
| semantic_memory | memory_system | 离线语义索引/召回（LanceDB 或 fallback），命中保留 case/report provenance |
| code_learner | auto_dream Phase 0, orchestrator._ensure_source_docs | L6 JSON, overview MD |
| model_router | 几乎所有 AI 模块 | chat/simple/complex 统一接口 |
| bsd_data_bridge (M9) | 独立运行，未来可调 auto_dream | BSD 条件验证报告, dynamic signals |
| source_docs/BSD_conditions.json | bsd_data_bridge | BSD 条件树 |
| source_docs/gen5_bsd_signal_mapping.json | bsd_data_bridge | PAD/变量映射 |
| engines/arbe/preflight | `ai/modules/arbe_preflight`、Pi | `arbe-preflight.v1`：workspace/source/config/binary/runtime/CAN chain 状态和 provenance |
| engines/arbe/intake | `ai/modules/cr60_intake`、数据准备 adapter、Pi | `cr60-analysis-intake.v1`：材料 hash、字段候选、冲突/缺口、数据路径校验状态 |
| engines/arbe/data_prep | `cr60-data-prep-verify`、Pi、上游 transfer skill | `cr60-data-prep-verification.v1`：源路径映射、文件 size/mtime/SHA-256、目标对比和缺口 |
| engines/arbe/transfer | `cr60-data-transfer`、Pi、上游 transfer skill | `cr60-data-transfer-session.v1`：显式脚本/输入/目标命令、审批、返回码和审计 |
| engines/arbe/source | `arbe-source-resolve`、Pi、后续 checkout planner | `arbe-source-resolution.v1`：当前 source identity、显式 version→ref mapping、local/remote ref 状态和 dirty gate |
| engines/arbe/cuda | `arbe-cuda-resolve`、Pi、后续 config/apply planner | `arbe-cuda-resolution.v1`：当前 08_CustData 候选、sha256、YAML xlsx/sheet/type 和 alignment |
| engines/arbe/patch_plan | `arbe-patch-plan`、Pi、后续 patch/apply planner | `arbe-patch-plan.v1`：可配置检查项、匹配行、文件 hash、git diff 和 action gate |
| `ai/providers/cr60_harness` | `ai/modules/cr60_precheck`、Pi | `cr60-harness-provider.v1`：只调用独立 harness CLI，保持 `diagnosis_bundle`/`viewer-model` 原样下游产出 |
| `ai/providers/cr60_harness.run_gdb_plan` | `runtime-debug-run`、Pi | 按 `runtime-debug-plan.v1` 调用 sibling 隔离 ROS/GDB runner，产出 `gdb-session.v1`；执行需审批 |
| `ai/providers/cr60_harness.run_formal_start/stop` | `arbe-formal-start` / `arbe-formal-stop`、Pi | 复用 sibling formal lifecycle runner，记录 ownership/PID/process group；启动/停止均需审批 |
| `ai/providers/cr60_harness.run_gdb_attach_plan` | `runtime-debug-attach`、Pi | 重新发现正式 ROS node/PID、校验 `/proc/<pid>/exe` 后按 plan attach，产出 `gdb-session.v1`；执行需审批 |
| `engines/arbe/build` | `arbe-build`、Pi | `arbe-build-session.v1`：显式 workspace/catkin_make command/result；执行需审批 |
| `ai/capability/module_bridge` | `AgentLoop`/`ReActPlanner` | 将选定 `BaseModule` 转成受控 `BaseTool`；默认只允许计划，执行开关由审批后的 supervisor 打开 |
| `ai/capability/pi_tool_bridge` | Pi Extension `registerTool` | Pi 的唯一 Python 调用边界；按能力名分派 BaseTool/Module adapter，默认不开放副作用 |
| `engines/arbe/public_evidence` | `public-topic-plan`、`public-evidence-audit`、Pi | `public-topic-plan.v1` / `public-evidence-audit.v1`：公共逐帧证据能力和缺口，不把 GUI 显示冒充 runtime 真值 |
| `engines/code_gdb_plan` | `code-gdb-plan`、`gdb-service`、Pi | `code-gdb-plan.v1`：按当前 code index 解析函数/条件/变量并生成 GDB 指令 |
| `engines/event_code_path` | `event-code-path`、Pi、HTML/Workbench | `event-code-path.v1`：事件→真实函数/调用/变量/条件/参数/断点组；不固化功能 |
| `engines/arbe/public_runtime` | `public-runtime-normalize`、PublicRuntimeCollector、Pi | `runtime-snapshot-with-frame.v1`：warning/radar_info/object rows 的明确帧/回调关联；可将 `ros-topic-inventory.v1` 独立样本按当前 schema 展开为 ObjectList 行并保存 capture provenance；topic plan 仅在当前 preflight identity 一致时参与 role mapping；不伪造跨 topic 帧，默认不按时间近邻绑定；runtime evidence 消费前仍需 AnalysisRun/data/source/binary/config/session binding |
| `engines/arbe/remote_replay` | `sim-verify`、Pi | `arbe-public-replay-session.v1`：SSH 公共 topic 回放/录制/capture/fetch；不复制 runtime 归一化、不新增平行 Pi 入口 |
| `ai/modules/sim_verify` | `point-cloud-analyze`、Pi | `analysis_handoff.analysis_inputs` 传递 capture/source/plan/verified binding 和 `perception-run.v1` sidecar；缺 lifecycle ACK 时仍是 `partial` |
| `engines/arbe/execution_binding` | `arbe-execution-binding`、`sim-verify`、Pi | `arbe-execution-binding.v1`：冻结 plan/data/source/binary/config/session identity 与 approval；执行前复核，失配 blocked |
| `engines/point_cloud_replay` | `point-cloud-plan`、`point-cloud-analyze`、`point-cloud-batch`、Pi | `point-cloud-replay-plan.v1` / `perception-artifact-audit.v1` / `perception-input-contract.v1` / `perception-stage-map.v1` / `perception-stage-evidence.v1` / `perception-lineage.v1` / `perception-lineage-index.v1` / `perception-code-flow.v1` / `perception-scene.v1` / `perception-timeline.v1` / `perception-warmup-analysis.v1` / `perception-injection-audit.v1` / `perception-hypothesis-set.v1` / `perception-capability-manifest.v1` / `perception-validation.v1` / `perception-run.v1` / `perception-comparison.v1` / `perception-batch-index.v1`：canonical relation pairs 与 raw relation rows 分开，带 endpoint kind/summary/scope；timeline 可在完整 callback binding 下投影相邻 public UID recurrence（derived、非物理身份）；raw `dotTrans` layout 必须绑定当前 source、精确 recording SHA 和兼容证据；capability freshness 必须匹配 ready plan/completed run 的 data/source/binary/config/session identity；大图按 callback byte-range/hash index 外置，按帧有界读取；不启动 ROS |
| `engines/gdb_service` | `gdb-service`、Pi | `gdb-session.v1`：通用 GDB argv/执行结果；无固定功能断点，执行需审批 |
| `engines/runtime_evidence` | runtime-evidence-*、viewer、Pi | `runtime-case-evidence.v1` / `runtime-evidence-merge.v1`：规范化 GDB/public runtime 证据、producer compose、identity gate、additive overlay |
| `engines/runtime_debug_plan` | `runtime-debug-plan`、Pi、HTML | `runtime-debug-plan.v1`：source/data/preflight bound 的 debug readiness、breakpoint/capture artifact |
| `engines/pi_context` | `pi-context`、Pi | `pi-orchestration-context.v1`：合并 intake/preflight/code-context 显式输入、capability manifest 和 runtime evidence；case_analysis 缺 case blocked，source_code 将 data 标为 not_required，并核验 code-context/code-index schema、source root、snapshot、context→index 引用与 SHA-256；缺失或冲突时 blocked，不回退 stale CodeGraph |
| `engines/arbe/intake_binding` | Pi 入口（pre-model gate）、run binding | `cr60-intake-binding.v1`：bag+问题→variant/版本/车型/COEM 确定性绑定；case 元数据 > 显式/intake 身份匹配 > 单项目自动复用；版本/分支与项目期望不一致时 blocked（错版本不进入 runtime），歧义/缺失产生业务语言 `business_questions`；不调用 LLM、不从路径名猜身份 |
| `engines/arbe/ros_inventory` | `ros-topic-inventory`、Pi、`public-runtime-normalize` | `ros-topic-inventory.v1`：ROS topic/type/publisher/subscriber 观察；可选 preflight hash/workspace binding、current ROS message definition 字段目录/SHA-256 和有界样本 hash/时间；不绑定跨 topic 帧 |
| `engines/analysis_ledger` | `analysis-run-*` / `analysis-step-record` / `analysis-claim-append`、Pi、Workbench | `analysis-run.v1` / `analysis-step.v1` / `claim.v1` + append-only ledger events |
| `engines/analysis_ledger` + `ai/modules/analysis_collaboration` | `analysis-hypothesis-record`、`debug-experiment-record`、`analysis-user-observation`、Pi、报告 | `hypothesis.v1` / `debug-experiment.v1` / `user-observation.v1`；状态历史、实验计划/结果、用户观察和 confirmed/rejected/irrelevant feedback 均保留 binding，不直接升级 runtime/knowledge 权威 |
| `engines/evidence_query` | `evidence-query`、`diagnosis-report`、Pi 对话 | `evidence-query.v1`：事件/帧/字段有界切片，保留 artifact provenance 和 not_available；可直接读 `runtime-snapshot-with-frame.v1` 并显式保留 unbound/identity gaps |
| `engines/diagnostic_report` | `diagnosis-report`、Pi、详细报告 | `diagnostic-report.v1`：事件索引、选中事件、ego/target/code/runtime、跨层 timeline、结论等级、缺口、AI inference 和 next actions |
| `engines/alert_timeline` | `alert-timeline`、`diagnosis-report`、Pi、HTML | `alert-timeline.v1`：跨证据层报警行、播放帧映射、compare 和 identity conflict；不实现功能规则 |
| `engines/diagnostic_narrative` | `diagnosis-report`、Pi、HTML | `diagnostic-narrative.v1`：逐条条件文字解释、报警判断状态和下一步；不替代 runtime/CAN 事实 |
| `engines/condition_trace` | `condition-trace`、`diagnosis-report`、Pi、HTML | `condition-trace.v1`：当前源码条件、同帧 bindings、求值状态和缺口；不把缺值当失败 |
| `engines/memory_recall` | `memory-recall`、`diagnosis-panel`、Pi | `memory-recall.v1`：现有记忆的结构化辅助线索和 freshness/provenance |
| `engines/code_context` | `code-context-refresh` / `code-context-read`、`code-analyze`、`code-gdb-plan`、Pi | `code-context.v1` + `code-index.v1`：source fingerprint、variant-bound RTE mapping、函数/调用/变量/信号/条件/参数 |
| `engines/project_capability` | `project-capability-manifest`、Pi、CapabilityPackRouter | `project-capability-manifest.v1`：当前 artifact 证明的 capability categories、unsupported、freshness 和 fingerprint |

## 文档维护规则

### 何时更新

以下变更发生时，更新对应目录的 `AGENTS.md`：

1. 新增/删除/重命名 `.py` 模块或公开类/函数
2. 修改公开 API 签名（参数、类型、默认值）
3. 修改 AI prompt 内容（system/user prompt、JSON schema）
4. 修改缓存/失效策略（hash、mtime、路径）
5. 修改阈值/魔数（如 `compute_budget()` 因子、`_PADDING_SEC=2.0`）
6. 修改数据结构 schema（FrameStore 表、JSON 文件、evidence dict）
7. 修改管线步骤顺序或新增步骤
8. 修改专家面板配置或记忆层级 API

### 更新方法

1. 定位变更所属目录 → 更新该目录的 `AGENTS.md`
2. 若涉及跨模块交互 → 两侧 AGENTS.md 都更新
3. 若影响管线步骤或依赖关系 → 同步更新本文件的速查表

### Review Checklist

- [ ] 公开接口签名与代码一致
- [ ] 数据结构字段与代码一致（含 JSON schema）
- [ ] AI prompt 内容与代码字符串常量一致
- [ ] 缓存失效条件与代码逻辑一致
- [ ] 阈值/魔数与代码值一致
- [ ] 处理流程步骤顺序与代码执行顺序一致
- [ ] 依赖关系正确

## M9 BSD Data Bridge — 整合说明

### 背景

BSD（Blind Spot Detection / 盲区检测）是 Corner Radar 核心功能之一。项目已有 `func_keywords["BSD"]`、`code_learner.FOCUS_FILES` 对 BSD 的支持，但缺少 **MF4 信号匹配 + PAD 条件交叉验证** 的独立能力模块。

### 整合产物

| 文件 | 说明 |
|------|------|
| `ai/modules/bsd_data_bridge.py` | M9 模块：BSD 信号索引 + 条件验证 |
| `ai/modules/__init__.py` | 追加 M9 注册 |
| `ai/modules/AGENTS.md` | M9 详细文档 |

### 验证流程

```bash
# 1. 检查模块是否注册成功
python -c "from ai.modules import MODULE_REGISTRY; print('bsd-data-bridge' in MODULE_REGISTRY)"

# 2. CLI 帮助
python cli.py bsd-data-bridge --help

# 3. 快速概览（需要 MF4 文件）
python cli.py bsd-data-bridge --mode summary --mf4-path path/to/record.MF4

# 4. 完整信号索引
python cli.py bsd-data-bridge --mode index --mf4-path path/to/record.MF4 --output-dir source_docs

# 5. 条件交叉验证（需要 BSD_conditions.json + gen5_bsd_signal_mapping.json）
python cli.py bsd-data-bridge --mode validate --mf4-path path/to/record.MF4 --output-dir source_docs
```

### 前置要求

1. **BSD_conditions.json** — `source_docs/` 目录下必须存在，由 ConditionExtractor 生成
2. **gen5_bsd_signal_mapping.json** — `source_docs/` 目录下存在（软依赖，可缺失）
3. **asammdf** — MF4 解析库，必须安装（`pip install asammdf`）

### 后续工作

1. **auto_dream 集成** — 在 `_run_dream_cycle()` Phase 0 增加 BSD 验证步骤
2. **ConditionExtractor BSD 域** — 确保 BSD 域覆盖 `BYD_OVS_CB/reco_fw` 代码
3. **orchestrator 集成** — 诊断管线 Phase 5 调用 M9 做 BSD 验证
