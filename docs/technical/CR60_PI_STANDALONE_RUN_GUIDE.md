# CR60 radarAnalyze：脱离 ChatGPT 的 Pi 独立运行指南

版本：`standalone-run-guide.v1`  
日期：`2026-09-03`  
适用范围：CR60/arbe 数据预检查、代码链路分析、公共运行态、GDB、报告和 Pi 对话编排

## 1. 结论先行

当前项目已经具备独立产品入口：

```text
用户 → python cli.py pi → pi --mode rpc
                    → .pi/extensions/radar-capabilities.ts
                    → ai.capability.pi_tool_bridge
                    → 当前注册的原子能力
                    → artifact / HTML / Pi 回答
```

因此可以脱离 ChatGPT 使用本项目的 Pi 入口完成分析。当前状态是“可独立运行的开发/验收版”，
不是“安装后零配置发行版”：本机需要 Python 依赖、Node/Pi、可用的模型 provider（只有确定性
报告时可以不需要模型）、项目配置和数据对应的 source context；要操作远程 arbe，还需要 SSH、
ROS 和远端 workspace 条件。

已验证的独立能力包括：Pi `registerTool` 生成、Python bridge 参数透传、54 个 module 能力目录、
AnalysisRun/AnalysisStep、确定性报告、当前 source 的动态条件链和真实 CRGVI-1829 报告生成。
远程写入、编译、启动、正式 PID attach 和完整长链路自主执行仍采用“计划→确认→执行”，并需要
针对目标服务器做现场验收。

## 2. 用户真正需要提供什么

用户只需要提供业务上知道的信息；技术字段优先由工具从材料、数据和当前代码自动获取。

### 2.1 最小输入

| 输入 | 是否必需 | 说明 |
|---|---|---|
| 数据文件或数据文件夹 | 是 | `.bag`、`.blf`、`.mf4`，或已经生成 bundle/viewer 的案例目录 |
| 用户问题 | 是 | 例如“分析报警为什么发生，按代码条件说明” |
| 预期行为 | 诊断时建议 | 例如“这个目标不应触发 FCTA” |

### 2.2 可由上游传入或自动发现的输入

| 输入 | 来源 |
|---|---|
| `cr60-analysis-intake.v1` | 上游 `bosch-data-transfert`；包含数据路径、问题单、软件版本、车型、COEM 和目标服务器 |
| `downstream.harness_profile` | 下游 harness profile；包含远程 host、arbe 路径、ROS、topic、回放策略和输出目录 |
| `analysis-context.v1` / `code-context.v1` | 当前 arbe 外层仓、`src/algo_source`、分支/commit、车型配置和代码索引 |
| `arbe-preflight.v1` | 当前 workspace 的 HILMODEL、binary、ROS 节点、报警 topic 和可用公共证据 |
| runtime/GDB artifact | 由 `sim-verify`、`runtime-debug-run` 或人工 VSCode/GDB 回填 |

缺少技术输入时，Pi 应先调度对应的只读能力；无法确认时保留 `blocked`、`partial` 或
`not_evaluable`，不要求用户手工猜 `i`、函数名、断点变量或 ROI 参数。

## 3. 入口和调用方法

### 3.1 交互式入口

```powershell
python cli.py pi --interactive --case-dir <case-dir>
```

进入后直接用自然语言提问，例如：

```text
分析当前数据中的所有报警。先给我每条数据的报警功能、侧别、雷达、目标 ID 和 frame，
然后选出一条报警，读取当前代码和运行态变量，按代码实际顺序说明为什么报警，并生成 HTML 报告。
```

### 3.2 单轮入口

```powershell
python cli.py pi `
  --question "分析这条数据的报警工况，按当前代码条件说明为什么报警，并生成详细报告" `
  --case-dir <case-dir> `
  --generate-report `
  --output-dir <output-dir>
```

已有 artifact 时可以显式挂载：

```powershell
python cli.py pi `
  --question "分析 FCTA_R 报警时的目标、自车和代码条件" `
  --case-dir <case-dir> `
  --diagnosis-bundle <diagnosis_bundle.json> `
  --viewer-model <viewer-model.json> `
  --runtime-evidence <runtime-evidence.json> `
  --code-context <code-context.json> `
  --event-code-path <event-code-path.json> `
  --gdb-session-path <gdb-session.json> `
  --function <real-function> `
  --side <L-or-R> `
  --generate-report `
  --output-dir <output-dir>
```

### 3.3 批量入口

```powershell
python cli.py pi `
  --question "批量预检查每条数据并列出报警事件" `
  --batch <batch-question.json> `
  --case-dir <data-folder>
```

如果只需要不经过模型的确定性报告：

```powershell
python cli.py diagnosis-report `
  --bundle <diagnosis_bundle.json> `
  --viewer-model <viewer-model.json> `
  --runtime-evidence <runtime-evidence.json> `
  --event-code-path <event-code-path.json> `
  --gdb-session <gdb-session.json> `
  --output-dir <report-dir>
```

查看当前安装的能力目录：

```powershell
python cli.py capabilities --json
```

### 3.4 环境变量

```powershell
$env:CR60_PI_PROVIDER = "<当前 Pi provider>"
$env:CR60_PI_MODEL = "<当前 Pi model>"
$env:CR60_RADAR_ANALYZE_PYTHON = "<本机 Python 解释器>"
$env:CR60_PI_EXECUTABLE = "<Pi 可执行文件路径>"  # Pi 不在 PATH 时才需要
```

provider/model 不写死在代码中；使用者可以换 provider、模型、服务器和用户。远程 arbe 的
host、user、workspace、ROS setup 和 source root 必须从 intake/profile/context 传入，不能依赖
本项目默认值。

## 4. Pi 如何组合工具

Pi 是用户入口和编排器，确定性 engine、BaseTool、BaseModule 和远程 provider 都是被调用的
原子能力。常见的分析链如下；实际工具由当前意图和 artifact 状态决定，不是固定死的流水线：

```text
cr60-intake
  → cr60-data-prep-verify / cr60-data-transfer（需要时）
  → arbe-preflight / arbe-source-resolve / arbe-cuda-resolve
  → code-context-refresh / code-learn / code-analyze / event-code-path
  → cr60-precheck（批量）
  → evidence-query / public-topic-plan / public-evidence-audit
  → runtime-debug-plan
  → runtime-debug-run 或 runtime-debug-attach（批准后）
  → runtime-evidence-normalize / validate / merge
  → diagnosis-panel（需要 AI 根因解释时）
  → diagnosis-report
```

所有工具通过生成的 `registerTool` 进入 Pi；TS extension 不复制业务逻辑，实际执行经过
`ai.capability.pi_tool_bridge`。工具结果必须返回 artifact 引用和状态，后续工具消费引用而不是
把大段 bag、全仓源码或完整 transcript 重复塞入 prompt。

## 5. Pi 的代码分析能力如何使用

Pi 的模型可以阅读代码、解释逻辑、比较条件、提出假设和规划下一步；当前 source 的事实由
代码工具提供。Pi 默认使用 `--no-builtin-tools`，不能绕过 context 直接扫描任意工作区。

每次代码分析按以下原则执行：

1. 绑定本次 data、arbe/source 子仓、COEM/车型、branch/commit、binary/config 和 replay mode；
2. 使用当前 source 的 `code-context`/`code-learn`/`code-analyze`/`event-code-path` 获取真实
   entry、caller、callee、条件、参数、变量和输出；
3. 使用 `resolution.condition_chain` 按当前 caller→helper→event root→callee 候选关系和
   源码行号组织条件；
4. 只在当前 source 实际出现时展示状态机/gate、自车、目标 dyn/track、ROI、预测、保持/计数
   和输出阶段；某一阶段不存在就写“当前 source 未发现”；
5. 同一 `data/source/binary/config/replay` 身份下，优先使用同帧公共运行态，缺失项再生成
   当前 source 绑定的 GDB 计划；不能用相邻帧或其他 case 的值补齐；
6. Pi 可以给出“按当前代码应当报警/不应当报警”的解释和候选根因，但模型推理不能创建
   `observed` runtime 事实。

### 5.1 用户可见的详细结论格式

详细报警报告固定按以下顺序呈现：

```text
总结性分析结论
  → 报警帧关键数据表（真实 code token、值、单位、来源、frame）
  → 报警工况图（自车、目标矩形、yaw、ROI、预测交点）
  → 按当前源码执行链的自然语言条件说明
  → 可展开的源码表达式、GDB 断点、完整 artifact 和 Analysis Ledger
```

结论必须能够读成：变量是什么值、命中了哪条源码条件、代入后结果是什么、经过哪个分支、
最后哪个算法报警灯输出置位。图形的瞬时 polygon/ROI 关系与代码预测交点必须分开，不能看到
当前矩形不相交就直接判定“不应报警”。

## 6. 必须执行的约束

### 6.1 身份和新鲜度

- source/data/binary/context fingerprint 冲突时禁止合并 runtime 证据；
- 代码、车型、COEM、DBC、需求或配置发生变化时，旧 code knowledge 不能进入当前 prompt；
- 不同 case、不同功能、不同雷达、不同 frame、不同 `objID` 的字段不能互相借用；
- `report.status=ready` 只代表报告文件生成成功，不代表根因已确认。

### 6.2 条件和运行态

- 条件顺序来自当前 source 的调用关系和源码位置，不固定为 FCTA/FCTB 或任何单一模板；
- 缺少值为 `not_evaluable`，不等于 false；不支持的表达式为 `unsupported`；
- `i`、`objID`、`frameID`、radar ID、message index 和 objectlist index 必须分开记录；
- 运行态字段必须保留 observation、frame、source location 和 association；GDB 命令成功不等于
  所有变量都已准确获取。

### 6.3 报警输出

- 默认报警终点是 arbe 可视化工具报警灯对应的算法输出（例如 `adasWarning`/`warning_status`）；
- CAN 只在用户明确要求时作为下游辅助证据，不是默认诊断前置条件；
- 原始录制报警、算法回放报警、公共 runtime 报警、GDB 状态和 CAN 输出必须分开；
- 算法报警上升沿、选定分析帧和 GDB 停止帧必须分别标注，不能混称。

### 6.4 副作用和协同

- 数据传输、切分支、改 CUDA/配置、补丁、编译、`bash start`、回放、attach 和 GDB execute
  先生成计划；未确认不产生副作用；
- 每个有价值阶段写入 AnalysisRun/AnalysisStep，记录观察、证据引用、缺口、下一步和成本；
- 用户提供的 VSCode/GDB 观察写入 `analysis-user-observation`，不能直接升级为 runtime observed；
- Pi 不输出隐藏思维链，只输出可核验的工程事实、解释、假设和下一步。

## 7. 当前边界和验收方法

当前不能宣称已经完成的部分：

1. 一套跨所有 Gen6 项目的零配置安装包；
2. 不提供项目 profile/SSH/ROS/source context 时自动连接任意服务器；
3. 正式 `bash start` 后所有版本的 GUI player parity；
4. 所有项目和版本的 caller/helper 条件均有准确运行态值；
5. 任意环境下的正式 PID attach 权限和无扰动 GDB；
6. 自动从候选根因到代码修改并完成用户确认的闭环。

发布前至少执行：

```powershell
python cli.py capabilities --json
python -m pytest tests/test_pi_tool_bridge.py tests/test_pi_context.py tests/test_event_code_path.py -q
python -m pytest tests/test_diagnostic_narrative.py tests/test_condition_trace.py tests/test_runtime_debug_plan.py -q
```

然后使用一条真实数据验证：

```text
数据 → 当前 source context → 动态 condition_chain → 公共报警灯输出 →（需要时）GDB → HTML
```

验证重点不是工具数量，而是：报告能否用当前真实变量和源码条件讲清楚报警；换功能、换代码
版本、换数据后，是否重新生成对应的 chain/schema，而不是沿用旧 case 的规则。
