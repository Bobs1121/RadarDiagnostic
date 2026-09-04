# Corner Radar Analysis Tool

**雷达 ADAS 功能自动化根因诊断系统** — 对 BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB 等功能的录制数据进行自动化分析，输出结构化的诊断报告。

## 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone <repo-url> radarAnalyze
cd radarAnalyze

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制 .env.example）
cp .env.example .env
```

编辑 `.env` 填入 LLM API 配置：
```
REMOTE_BASE_URL=http://your-llm-server/v1
REMOTE_API_KEY=your-api-key
```

### 2. 最小本地配置

`config.local.yaml` 现在推荐只保留用户真正需要提供的输入：**源码根目录、branch、COEM 项目、案例目录、DBC 路径、requirements 路径**。其余 `codebases` / `variants` / `source_context` / `package_profiles` / `knowledge_policy` / workspace 路径都会在加载配置时由 `project_intake` 自动展开：

```yaml
project_intake:
  default: byd_sc6h
  projects:
    byd_sc6h:
      code_root: D:\cr60_light
      branch: feature/byd
      coem: BYD_SC6H
      data: D:\cases\CASE001
      dbc:
        - D:\dbc
      requirements:
        - D:\cr60_light\coem\BYD_SC6H\components\com\doc
```

对于这条优先路径，`D:\cr60_light\coem\<customer_project>` 已经是隔离后的单一客户代码集，因此**不单独配置 SIT/FCT 维度**，也不要求手写 package profile、knowledge policy 或 variant workspace。系统会把 `source_docs`、`memory`、`semantic index`、`codegraph`、`snapshots` 自动落到 `.workspaces/<variant>/` 沙盒下，不与其他项目混用。日常诊断随后直接使用：

```bash
python cli.py D:\cases\CASE001 -p "FCTB 未触发" -e "目标进入 ROI 后应报警"
```

### 3. 共享基线配置

`config.yaml` 继续保存共享基线：模型、默认 `source_context`、运行时开关、以及仓库级预置 variant。日常诊断直接运行最简命令，默认**不会**先跑 auto-dream；`--source-root` / `--code-branch` / `--allow-branch-mismatch` 仅作为单次覆盖：

```yaml
default_variant: "gen6/gwm_b26"

source_context:
  source_root: ""               # 留空时继续使用 codebases.*.root_path
  code_branch: ""               # 可选：期望源码分支
  allow_branch_mismatch: false  # 可选：允许记录 mismatch 后继续

runtime:
  auto_dream_on_case_start: false  # 日常诊断默认关闭；仅在明确要旧行为时打开
```

```bash
python cli.py cases/FCTB001/ -p "FCTB 未触发" -e "FCTB 应该在目标出现后 2 秒内触发"
```

`config.local.yaml` 会以深度合并方式覆盖 `config.yaml`：嵌套字典保留未覆盖字段，列表与标量按本地值替换。推荐优先使用 `project_intake`，只维护项目私有路径和 branch；内部 variant/workspace 结构由系统生成，避免把实现细节写进本地配置。

### 4. 运行诊断

#### Pi 正式入口（推荐）

本项目的产品入口是 Pi。用户不需要编排内部脚本顺序；Pi 会根据问题和
`PiRunContext` 组合 intake、preflight、Sprint1、源码、公共 ROS、GDB 和报告工具。
第一次运行 `python cli.py pi` 时，`PiBridge` 会按当前 catalog 刷新
`.pi/extensions/radar-capabilities.ts`，并显式加载该项目 extension。

```bash
# 已有上下文 artifact 时，带上下文进入 Pi
python cli.py pi --question "检查这条数据的报警首帧和目标属性" \
  --context-path outputs/pi-orchestration-context.json

# 交互模式
python cli.py pi --interactive

# provider/model 可按用户或服务器配置；未指定 provider 时只读探测 pi --list-models
set CR60_PI_PROVIDER=bosch-qwen3_6
set CR60_PI_MODEL=Qwen3.5-27B-FP16
# 如果 Pi 进程找不到正确的 Python，可指定 bridge 使用的解释器
set CR60_RADAR_ANALYZE_PYTHON=C:\Python312\python.exe
```

脱离 ChatGPT 的完整输入、入口、工具组合、提示词边界和当前可用范围见
[CR60_PI_STANDALONE_RUN_GUIDE.md](docs/technical/CR60_PI_STANDALONE_RUN_GUIDE.md)。

详细诊断时，如果 runtime/GDB artifact 不在 `--case-dir` 的 canonical 目录中，显式挂载它们；
要求生成报告时可以直接给 `--output-dir`。Pi 会先生成确定性 `evidence_anchor`，再交给模型解释，
不会因为模型漏调报告工具而没有交付物：

```bash
python cli.py pi --question "生成 FCTA_R/R 详细诊断报告，说明工况、代码条件、ROI 和正误报结论" \
  --case-dir <case-dir> --runtime-evidence <runtime-evidence.json> \
  --function FCTA_R --side R --output-dir <report-dir>
```

`evidence_anchor` 只使用当前 bundle/viewer/runtime 的确定性投影；多事件且没有唯一功能/帧/
雷达 scope 时会返回 `partial` 并要求选择，不会默认取第一个事件。Pi 的最终回答必须遵守
anchor 的 `observed/derived/not_available` 状态；超时会返回失败状态，但保留已生成的报告。

Pi tool 的唯一执行链是：

```text
Pi registerTool → ai.capability.pi_tool_bridge → BaseTool/BaseModule adapter
                 → deterministic engine/provider → artifact
```

`python cli.py <module>`、`AgentLoop` 和 `ReActPlanner` 仍可用于开发、测试和 Pi
不可用时的离线 fallback，但不是与 Pi 并列的产品编排入口。远程写入、编译、启动、
GDB attach/execute 仍须由 supervisor 在计划后审批。

当 `--case-dir` 指向已经产生 `diagnosis_bundle.json`、`runtime_evidence.json` 或
`runtime_debug_plan.json` 的目录时，Pi 会自动发现这些 canonical artifact；其中 merged
bundle 内嵌的 runtime evidence 也会被自动取出放入 `pi-orchestration-context.v1`。用户不
需要手工拼接内部文件名，source/data/binary 缺口仍会原样进入 context。

当前 Pi 入口支持三个连续出口：

```text
给一个数据文件夹
  → cr60-precheck：批量 index + 每条数据 HTML/JSON
选一条报警/一帧
  → evidence-query → 当前代码链 → diagnosis-report：详细事实/断点/缺口/诊断输入
继续自然语言追问
  → 同一 AnalysisRun/session：按意图查字段、查代码、查信号或继续 runtime
```

独立使用时，用户只需要启动 Pi 入口，不需要记住下面各个模块的调用顺序。Pi 会把当前数据、
source context、viewer-model、代码索引和 AnalysisRun 作为本次任务上下文；数据传输、arbe
部署/补丁、编译、启动、回放和 GDB 等动作仍由原子工具执行，并在副作用前展示确认点。

这里的“独立使用”指脱离 ChatGPT，由本地 Pi + radarAnalyze 自己完成编排；当前版本已经有
独立入口和工具注册，但还不是零配置安装包。使用者需要准备 Python 依赖、Node/Pi、可用的
provider/model、项目配置以及当前数据对应的 source context/远程 arbe profile。静态预检查和
已有 artifact 的报告可以不依赖模型直接运行；需要 Pi 自主解释时才需要 provider。Pi 不把自身
的代码常识当作事实，而是先读取当前 source-bound code context/code index，再组合代码分析、
公共运行态和 GDB 工具。不同功能、代码版本和数据只能使用本次 identity/freshness 通过的条件链。

详细报告现在还包含 `condition-trace.v1`：它逐项列出当前源码的真实 C 条件、源码位置、同帧
字段/当前源码参数的代入值、`satisfied` / `not_satisfied` / `not_evaluable` / `unsupported`
状态和缺失 token；报告同时提供 ego/target/heading/ROI 场景 SVG。缺少运行时量时不会把条件
判为 false，用户可以直接从缺失 token 进入 public runtime 或 GDB 追问。

详细报告还包含功能无关的 `alert-timeline.v1`：把 `recorded_raw`、`replay_algorithm`、
`runtime_with_frame`、`gdb_observation` 和 `can_tx_observation` 分层展示，给出播放帧
（warm-up/selected/context）、同帧报警信号和 compare 状态。没有对应 artifact 时只显示
`not_available`/`not_evaluated`，不会把静态 nearest-frame 候选写成最终 CAN 报警首帧。
报告还会生成 `diagnostic_narrative`，按真实源码条件逐条描述“已满足/未满足/暂不能判断”，
并给出 `should_alert=yes_observed|supported_yes|indeterminate`；没有精确 CAN/runtime 证据时
不会给出最终正报/误报结论。

详细报告的直接命令（开发/验收入口，正式用户仍从 Pi 调度）：

```bash
python cli.py evidence-query --bundle <diagnosis_bundle.json> \
  --viewer-model <viewer-model.json> --function <real-function> \
  --fields '["target.fields","ego.fields","code.call_chain"]' \
  --output <evidence-query.json>

python cli.py diagnosis-report --bundle <diagnosis_bundle.json> \
  --viewer-model <viewer-model.json> --function <real-function> \
  --output-dir <detailed-report-dir>

python cli.py condition-trace --conditions '<current-source-condition-json>' \
  --values '<same-frame-field-facts-json>' --parameters '<source-parameter-json>'

python cli.py alert-timeline --bundle <diagnosis_bundle.json> \
  --viewer-model <viewer-model.json> --event-id <real-event-id> \
  --output <alert-timeline.json>
```

`diagnosis-report` 的 JSON/Markdown/HTML 是证据报告 companion；正式可交互的 scene、逐帧属性、
ROI 和 runtime 面板继续由 sibling `cr60-debug-harness` viewer 提供。报告没有 runtime 时仍然
可以交付，但会显示 `runtime_probe_required`，不把静态推导写成 runtime 真值。默认页面先呈现
`executive_summary`、关键条件、`should_alert`、几何关系和 `Debug anchors`；完整对象列表、
条件 trace、连续帧和 GDB transcript 在折叠区及 JSON 中保留。

#### Pi 编排上下文

可先用确定性 `pi-context` 将上游输入绑定为不可由模型覆盖的 context：

```bash
python cli.py pi-context \
  --intake outputs/cr60-analysis-intake.json \
  --preflight outputs/arbe-preflight.json \
  --output outputs/pi-orchestration-context.json
```

上下文契约为 `contracts/pi-orchestration-context.v1.schema.json`，会保留
project/variant、data、source/binary、runtime、policy、freshness、artifact 引用、
缺口和冲突。缺失或冲突不会被默认值掩盖。

#### 诊断模式（完整分析）

```bash
python cli.py <案例目录> -p "问题描述" -e "预期行为"
```

**参数说明**：

| 参数 | 说明 | 示例 |
|------|------|------|
| `<案例目录>` | 包含 .bag/.blf 录制数据的目录 | `cases/FCTB001/` |
| `-p` / `--problem` | 问题描述 | `"FCTB 在目标接近时未触发"` |
| `-e` / `--expected` | 预期行为 | `"距离小于 30m 时 FCTB 应激活"` |
| `--variant` | 单次覆盖 `config.yaml` 中的 variant | `gen6/gwm_b26` |
| `--source-root` | 单次覆盖 `source_context.source_root`，不修改 `config.yaml` | `D:\code\gwm_b26` |
| `--code-branch` | 单次覆盖 `source_context.code_branch`；只做校验，不切换 git 分支 | `feature/FCTB_fix` |
| `--allow-branch-mismatch` | 单次覆盖 mismatch 策略；允许继续运行但只记录元数据 | `--allow-branch-mismatch` |
| `--snapshot` | 代码快照（diagnosis 默认 auto） | `auto` / `2026-06-15-abc123` |
| `--auto-dream` | 本次 case 启动前补跑一次 gated auto-dream | `--auto-dream` |

**示例**：
```bash
# 推荐：source_context 放在 config.yaml，命令保持最简
python cli.py cases/FCTB001/ -p "FCTB 报警太晚" -e "目标进入 ROI 即报警"

# 单次需要旧行为时，显式补跑 auto-dream
python cli.py cases/FCTB001/ -p "FCTB 报警太晚" -e "目标进入 ROI 即报警" --auto-dream

# 指定项目和快照
python cli.py cases/FCTB001/ -p "FCTB 报警太晚" -e "目标进入 ROI 即报警" \
  --variant gen6/gwm_b26 --snapshot auto

# 临时覆盖 source_context（只校验，不 checkout/fetch/pull）
python cli.py cases/FCTB001/ -p "FCTB 报警太晚" -e "目标进入 ROI 即报警" \
  --variant gen6/gwm_b26 \
  --source-root D:\code\gwm_b26 \
  --code-branch feature/FCTB_fix
```

#### 数据查询模式（轻量分析）

```bash
python cli.py <案例目录> -q "自然语言问题"
```

**示例**：
```bash
python cli.py cases/FCTB001/ -q "FCTB 触发时 AEBIB 信号状态是什么？"
python cli.py cases/FCTB001/ -q "车速在报警窗口期间的变化情况？"
```

### 5. 查看报告

诊断完成后自动生成 HTML 报告：
```
cases/<案例名>/report_诊断时间戳.html
```

## 运行入口与兼容模式

| 模式 | CLI 入口 | 用途 |
|------|----------|------|
| **Pi（正式入口）** | `python cli.py pi --question "..."` | 唯一用户入口；理解问题并组合原子能力 |
| **Diagnosis** | `python cli.py <dir> -p "问题" -e "预期"` | 完整根因分析（15 步管线） |
| **Query** | `python cli.py <dir> -q "问题"` | 数据查询（轻量问答） |
| **Dream** | `python cli.py --dream` | 记忆巩固（自动知识沉淀） |

Diagnosis、Query、Dream 是兼容和维护入口，不替代 Pi 的产品编排入口；新能力优先
实现为 deterministic engine + Pi `registerTool`，再按需要提供 BaseModule/CLI。

## 辅助命令

| 命令 | 说明 |
|------|------|
| `--auto-dream` | 仅本次 case 启动前执行 gated auto-dream；日常诊断默认不跑 |
| `--prewarm` | 预热 source_docs / code knowledge / variable_chains 缓存，不做 memory consolidation |
| `--learn-constants` | 学习全局数值常量表（阈值、车速限制等） |
| `--codegraph-stats` | 查看 CodeGraph 统计信息（调试用） |
| `python cli.py capabilities --json` | 只读查看当前 Pi 可调度的原子能力目录；支持 `--kind module/tool` |

### CR60 Pi 原子能力（当前首版）

统一平台把数据、公共证据、代码分析和 GDB 拆成可组合能力；先生成/审计确定性
artifact，再由 Pi 决定是否进入 GDB：

阶段性分析不再只依赖最终报告。Pi 可以创建持久化 AnalysisRun，并在每个阶段记录
step/claim：

```bash
python cli.py analysis-run-create --run-id <run-id> --question "分析这条报警并保留中间线索"
python cli.py analysis-step-record --action begin --run-id <run-id> --step-id <step> --stage event-map
python cli.py analysis-step-record --action complete --run-id <run-id> --step-id <step> \
  --status partial --observations '[{"statement":"发现多个报警事件"}]' \
  --gaps '[{"code":"can_tx_unobserved","critical":true}]'
python cli.py analysis-claim-append --run-id <run-id> --step-id <step> \
  --scope event --statement "当前 artifact 记录了多个事件" --status observed \
  --created-by tool --evidence-refs '[{"path":"outputs/events.json"}]'
python cli.py analysis-run-read --run-id <run-id> --include-entities
```

AI 创建的 claim 不能标记为 `observed`；Hypothesis/DebugExperiment 已提供 S2B ledger
原子能力和报告摘要投影，但自动候选生成、实验选择和根因确认仍未完成。

协同 Debug 的三个原子动作也可以由 Pi 自动组合，或在故障兜底时直接调用：

```bash
python cli.py analysis-hypothesis-record --run-id <run-id> --category situation \
  --statement "当前 ROI/状态机仍缺同帧运行时证据" --status open
python cli.py debug-experiment-record --action plan --run-id <run-id> \
  --question "读取报警帧局部变量" --method gdb \
  --target '{"frame_id":47877,"radar_id":2,"object_id":44}'
python cli.py analysis-user-observation --run-id <run-id> --kind manual_vscode \
  --summary "用户在 VSCode 看到断点命中，但尚未确认 CAN Tx"
```

实验必须先 `plan` 再记录结果；人工观察会写入 `user-observation.v1`，不会直接变成
`gdb_observation` 或条件绑定。

一次性建立并查询当前源码上下文（不绑定具体功能）：

```bash
python cli.py code-context-refresh --source-root <current-source-root> \
  --output-dir outputs/code-context/<variant> --no-ast
python cli.py code-context-read --context-path outputs/code-context/<variant>/code-context.json \
  --section call_chain --query <function>
python cli.py event-code-path --context-path outputs/code-context/<variant>/code-context.json \
  --event '{"function":"<real-function>","frame_scope":{"variable":"<real-frame>","start":1,"end":2}}'
python cli.py public-runtime-normalize --capture-path <public-runtime-capture.json> \
  --output outputs/runtime-snapshot-with-frame.json
```

`code-context-refresh` 生成的 `code-index.json` 可直接作为
`code-analyze --code-index-path` 与 `code-gdb-plan --code-index-path` 的输入；源码指纹变化
会重建，输出目录若已经绑定另一源码根则阻断，避免跨车型/branch 混用。

```bash
# 1) 材料优先绑定；缺失或冲突不会猜车型/COEM/版本/分支
python cli.py cr60-intake --data /home/.../record.bag --material <handoff-or-xlsx> --output outputs/intake.json

# 1a) 数据传输前只读核对 Linux 源文件的存在、大小和 SHA-256；不复制数据
python cli.py cr60-data-prep-verify --intake outputs/intake.json \
  --host <server> --user <user> --execute --output outputs/data-verify.json

# 1b) 用户确认后调用已部署的上游传输脚本；未加 --approved 只返回 approval_required
python cli.py cr60-data-transfer --host <server> --user <user> \
  --script-path <remote-data_transfert.py> --input-path <remote-list-or-xlsx> \
  --destination-root <remote-data-root> --source-type list \
  --execute --approved --output outputs/data-transfer-session.json

# 2) 只读验证 arbe/source/config/binary/GDB/运行目标
python cli.py arbe-preflight --host <server> --user <user> --arbe-root <remote-arbe> --output outputs/preflight.json

# 2a) 只读确认当前 algo_source 与版本到 tag/ref 的显式映射；不 checkout/fetch
python cli.py arbe-source-resolve --host <server> --user <user> \
  --algo-source-root <remote-arbe>/src/algo_source \
  --software-version <version> --ref-prefix <configured-prefix> \
  --version-suffix-strip <configured-suffix> --remote-query --execute \
  --output outputs/source-resolution.json

# 2b) 只读扫描当前车型 08_CustData，并核对 launch YAML；不复制/改配置
python cli.py arbe-cuda-resolve --host <server> --user <user> \
  --arbe-root <remote-arbe> --vehicle <coem-model> --cuda-sheet <sheet> \
  --preflight outputs/preflight.json --execute --output outputs/cuda-resolution.json

# 2c) 只读检查仿真适配、文件 hash 和 dirty diff；缺项只输出 needs_action，不改代码
python cli.py arbe-patch-plan --host <server> --user <user> \
  --arbe-root <remote-arbe> --algo-source-root <remote-arbe>/src/algo_source \
  --preflight outputs/preflight.json --execute --output outputs/patch-plan.json

# 3) 只读盘点 ROS 公共通道
python cli.py ros-topic-inventory --host <server> --user <user> --topic /wf/objectlist_2 --topic /corner_radar/warning_status_with_frame

# 4) Sprint1 由独立 harness 解析；默认只生成计划，执行需用户确认
python cli.py cr60-precheck --mode manifest --harness-root <harness-root> --profile <profile.toml> \
  --manifest-path <manifest.json-or-toml> --output-dir <batch-output> --context <analysis-context.json>

# 5) 当前 source code-index → 通用 GDB commands；再交给 gdb-service
python cli.py code-gdb-plan --code-index-path <current-code-index.json> --function-name <real-function> \
  --condition '<observed-condition>' --watch-variable '<real-source-token>'
python cli.py gdb-service --target '<target-json>' --command '<generated-gdb-command>'

# 6) 事件 → readiness/断点/GDB commands 计划（只规划）
python cli.py runtime-debug-plan --bundle-path <diagnosis_bundle.json> \
  --event-id <event-id> --preflight-path <arbe-preflight.json> \
  --output outputs/runtime-debug-plan.json

# 7) 用户批准后，按 plan 启动隔离 ROS/GDB；默认仍是 plan-only
python cli.py runtime-debug-run --harness-root <harness-root> --profile <profile.toml> \
  --bag <remote-bag> --debug-plan-path outputs/runtime-debug-plan.json \
  --target-frame <frame> --radar-id <radar> --session-output outputs/gdb-session.json \
  --execute --approved

# 7b) 正式 bash start / existing-PID attach（两者均需显式批准）
python cli.py arbe-formal-start --harness-root <harness-root> --profile <profile.toml> \
  --ros-master-uri http://localhost:11311 --session-output outputs/arbe-start-session.json \
  --execute --approved
python cli.py runtime-debug-attach --harness-root <harness-root> --profile <profile.toml> \
  --bag <remote-bag> --debug-plan-path outputs/runtime-debug-plan.json \
  --target-frame <frame> --radar-id <radar> --ros-master-uri http://localhost:11311 \
  --replay --session-output outputs/gdb-attach-session.json --execute --approved
python cli.py arbe-formal-stop --harness-root <harness-root> --profile <profile.toml> \
  --session-path outputs/arbe-start-session.json --execute --approved \
  --output outputs/arbe-stop-session.json

# 8) GDB session → runtime evidence → additive bundle
python cli.py runtime-evidence-normalize --gdb-session-path outputs/gdb-session.json \
  --run '<run-binding-json>' --output outputs/runtime-evidence.json
python cli.py runtime-evidence-merge --bundle-path <diagnosis_bundle.json> \
  --runtime-evidence-path outputs/runtime-evidence.json \
  --output outputs/merged-diagnosis-bundle.json
```

`gdb-service` 不内置 FCTA/FCTB 或任何固定断点；`execute=true` 可能暂停/扰动进程，
必须由上层审批后显式开启。完整输入输出、证据分层和真实 arbe 现场结论见
`docs/technical/CR60_PI_UNIFIED_DOCUMENT_INDEX.md`。

Pi 继续编排时可以直接把 merged `diagnosis_bundle.v1` 和
`runtime-debug-plan.v1` 交给 `pi-context`；它会从 bundle 中已明确声明的 case/data/source
字段恢复上下文并保留 provenance，不要求用户重复填写技术字段。若 bundle 没有明确数据
路径，仍会 `blocked`，不会按目录名或 bag 文件名猜测身份。

## 项目配置

### config.yaml 结构

```yaml
ai:
  # 本地模型（简单任务）
  local:
    base_url: "http://localhost:11434/v1"
    api_key: "ollama"
    model: "qwen2.5:7b"
  # 远端模型（复杂推理）
  remote:
    base_url: "${REMOTE_BASE_URL}"
    api_key: "${REMOTE_API_KEY}"
    model: "Qwen3.5-27B-FP16"
  # 思考模式: off / synth / full
  thinking: "full"

# 项目身份系统（variant 层级）
source_context:
  source_root: ""
  code_branch: ""
  allow_branch_mismatch: false

runtime:
  auto_dream_on_case_start: false

memory:
  semantic_index:
    enabled: true
    max_hits: 3

variants:
  gen6/gwm_b26:
    display_name: "GWM B26"
    codebase: "gwm_b26_code"
    source_context:            # 可选：覆盖 top-level source_context
      source_root: ""
      code_branch: ""
      allow_branch_mismatch: false
    key_source_files: [...]
    dbc_sets: [...]

default_variant: "gen6/gwm_b26"
```

对于新接入项目，推荐在 `config.local.yaml` 里只写 `project_intake`；加载时会自动生成 variant 级 `source_context.{workspace_dir,source_docs_dir,memory_dir,codegraph_db_path,snapshots_dir,semantic_index_dir}`，让每个 variant 的知识缓存和快照都固定落到自己的 `.workspaces/<variant>/` 沙盒中。CR60 Light 场景下系统还会自动补齐 `customer`、`vehicle_project`、`coem_project_dir`、`requirement_overlays`、`package_profiles.<variant>/default` 与 `knowledge_policy`，并在 `.workspaces/<variant>/manifest.yaml` 记录 branch/DBC/requirements 的只读校验元数据。

每个 variant 的 `memory/` 目录还会维护一个轻量 `freshness_state.json`：CLI 在 diagnosis/query/prewarm/dream 前会重新计算源码作用域、关键源码、参数/条件文件、DBC、requirements 和 identity 指纹；如果发现漂移，会提示 `source_docs` / `code_knowledge` / dream knowledge 可能过期，但不会默认失败，也不会 watch 文件或修改 git 状态。`--prewarm` 和成功完成的 dream 会把新的 freshness state 写回当前 variant workspace。

### .env 环境变量

| 变量 | 说明 |
|------|------|
| `REMOTE_BASE_URL` | 远端 LLM API 地址 |
| `REMOTE_API_KEY` | 远端 LLM API Key |
| `LOCAL_BASE_URL` | 本地 Ollama 地址（可选） |

## 目录结构

```
radarAnalyze/
  cli.py                  # 统一 CLI 入口
  config.yaml             # 模型/项目/功能配置
  .env                    # 环境变量（API Key 等）
  requirements.txt        # Python 依赖
  IMPLEMENTATION.md       # 完整实现文档（归档用）

  ai/                     # AI 分析核心模块
    orchestrator.py       # 诊断管线编排器（15 步）
    pattern_extractor.py  # 代码模式提取器（6 种模式）
    causal_aligner.py     # 因果对齐引擎
    temporal_analyzer.py  # 时序特征分析器
    condition_extractor.py # 条件提取器（双层：规则+LLM）
    rule_condition_extractor.py # 规则条件引擎（13 类规则）
    expert_panel.py       # 专家面板（3 轮 LLM 诊断）
    frame_analyzer.py     # 帧级证据提取
    data_probe.py         # 数据探测（按需 SQL 查询）
    variable_query_planner.py # 变量查询规划器
    data_query_engine.py  # 数据查询引擎
    visualizer.py         # HTML 报告生成器
    model_router.py       # LLM 路由（local/remote/coder）
    utils.py              # 公共工具函数
    ...

  parsers/                # 数据解析层
    case_loader.py        # 案例加载器（.bag/.blf/.mf4）
    frame_store.py        # 帧存储（SQLite）
    signal_mapper.py      # 信号映射表

  memory/                 # 记忆系统
    memory_system.py      # 记忆读写（L1-L6）
    auto_dream.py         # 自动记忆巩固
    semantic_memory.py    # 离线语义索引/召回（不替代 JSON 真值）
    code_learner.py       # 代码知识学习者

  source_docs/            # 缓存的知识文档（按项目隔离）

  cases/                  # 案例数据目录
    FCTB001/
      recording.bag       # 原始录制数据
      recording.blf       # CAN 日志
      report_*.html       # 诊断报告产物

  tests/                  # 测试
    test_temporal_pattern_engine.py  # TPE 测试
    test_harness/         # 评估 Harness
```

**说明**：L1-L6 JSON 记忆仍是可审计真值；`SemanticMemory` 仅作为离线索引/召回层使用，命中会携带 `case_id`、`memory.json` / `report.md` 等 provenance，且在 `lancedb` 不可用时自动退回本地 fallback 存储。

## 支持的案例格式

| 格式 | 说明 |
|------|------|
| `.bag` | ROS bag（雷达原始数据） |
| `.blf` | Vector CAN log（CAN 信号日志） |
| `.mf4` | Measurement File 4（可选，需 asammdf） |

## 常见问题

### 诊断报错 "Case folder not found"
确保案例目录存在且包含 .bag 或 .blf 文件：
```bash
ls cases/FCTB001/*.bag
```

### LLM 连接失败
检查 `.env` 中的 `REMOTE_BASE_URL` 和 `REMOTE_API_KEY` 是否正确。

### 诊断报告不完整
如果只是想减少 Step-1 冷启动时间，优先运行 `--prewarm`；只有在明确要做记忆整理/代码学习时才运行 `--dream` 或在单次 case 上追加 `--auto-dream`。

### 想主动维护记忆/源码知识
```bash
python cli.py --prewarm
python cli.py --dream
python cli.py cases/FCTB001/ -p "FCTB 报警太晚" -e "目标进入 ROI 即报警" --auto-dream
```

### 想补齐常量知识
运行 `--learn-constants` 预学习常量：
```bash
python cli.py --learn-constants --variant gen6/gwm_b26
```

### 想先看前端效果
直接运行诊断，报告为 HTML 文件，浏览器打开即可。

## 技术栈

- **Python 3.12+**（运行环境）
- **LLM 调用**：OpenAI 兼容 API（qwen3.5, claude, gpt-4o 等）
- **数据存储**：SQLite（帧数据）
- **报告**：HTML（浏览器查看）
- **CLI 框架**：argparse + rich（终端美化）
