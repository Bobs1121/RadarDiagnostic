# CR60 Pi Unified Platform：Analysis Ledger MVP handoff

版本：`handoff.v1`  
日期：2026-08-31  
阶段：S1A Analysis Ledger MVP  
状态：`partially-verified`

## 1. 目标与 DDD 追踪

实现 `US-015` 的最小闭环：分析过程不再只存在于 Pi 对话或最终 HTML，而是持久化为
可恢复的 `AnalysisRun → AnalysisStep → Claim`。Hypothesis/DebugExperiment 先提供 contract，
本阶段不宣称已实现根因闭环。

## 2. 代码与契约

| 层 | 交付 |
|---|---|
| Ledger engine | `engines/analysis_ledger.py` |
| Pi modules | `ai/modules/analysis_ledger.py` |
| Contracts | `analysis-run.v1`、`analysis-step.v1`、`claim.v1`、`analysis-ledger-event.v1` |
| Planned contracts | `hypothesis.v1`、`debug-experiment.v1` |
| Pi registration | `.pi/extensions/radar-capabilities.ts`，由 catalog 自动生成 |
| Tests | `tests/test_analysis_ledger.py` |

已注册的 Pi 原子能力：

```text
analysis-run-create
analysis-run-read
analysis-run-update
analysis-step-record
analysis-claim-append
```

## 3. 持久化设计

```text
outputs/analysis_runs/<run_id>/
  analysis-run.json
  events.jsonl
  .ledger.lock
  steps/<step_id>.json
  claims/<claim_id>.json
  hypotheses/
  experiments/
  user-observations/
```

`analysis-run.json` 只保存小摘要和 entity refs；实体保存详细 observations/gaps/conflicts。
JSON 更新使用临时文件 + `os.replace`，事件以 append-only JSONL 记录，写操作使用原子锁。
缺少新版本 compact ref 字段的旧 step，读取时只读回查 entity，不静默丢失关键 gap。

## 4. 准确性门禁

- observed claim 必须有 evidence ref；
- AI 创建的 claim 不能标记为 observed；
- step 只能从 running 完成一次；重复操作返回 conflict；
- run/step/claim ID 不能目录穿越；
- tool、AI、user 的创建者身份保留；
- 历史结论用新 claim/step 更正，不覆盖原 claim；
- ledger 不解码数据、不读 HTML、不计算根因，不替代确定性 evidence。

## 5. 真实 CRGVI-1829 恢复 smoke

本阶段没有重解 bag、重跑 GDB 或访问远程 arbe；使用已有 artifact 恢复 run：

```text
run: crgvi1829-progressive-20260831-v1
steps: 3
claims: 9
critical gaps: 7
current stage: debug-ready
run status: partial
replay attempts: 1
gdb stops: 7
bag full reads in this reconstruction: 0
```

已记录：

- Linux bag size/hash；
- 当前 source tag/HEAD/dirty；
- CUDA/config alignment；
- 28 个静态报警事件；
- `FCTA_R/radar2/frameID=47877/objID=44` 的 derived 对齐；
- isolated GDB 的 `i=0/objID=44` runtime observation；
- formal PID attach 因 `ptrace_scope=1` blocked；
- 最终 CAN Tx 首帧和正式 GUI parity 缺口；
- AI inference 与工具 observed claim 分离。

运行 artifact：[crgvi1829-progressive-20260831-v1](../../outputs/analysis_runs/crgvi1829-progressive-20260831-v1/analysis-run.json)

## 6. 测试结果

```text
python -m pytest -q tests/test_analysis_ledger.py
8 passed
```

本阶段代码加入后，全量回归尚未在本 handoff 生成时完成；之前基础能力回归为
`651 passed, 1 skipped, 2 xfailed, 10 warnings`，不能直接当成本阶段最终回归证据。

## 7. 未完成

- Hypothesis/DebugExperiment 的持久化 module；
- user decision/user observation 回填；
- Analysis Trail/Hypothesis Board Workbench 投影；
- 现有 precheck/runtime 工具自动落 ledger，而不是由调用方手工记录；
- EventCodePath 和 PublicRuntimeCollector。

## 8. 下一步

1. 先实现 `code-context-refresh/read`，把一次性代码处理做成可复用、可校验的 source snapshot；
2. 将 `cr60-intake`、`cr60-precheck`、`code-analyze`、`runtime-evidence` 的 provider wrapper
   统一接入 step recorder；
3. 实现 `event-code-path.v1`，把用户选择事件连接到五层代码链和 breakpoint groups；
4. 实现 hypothesis/experiment loop，再开发 Workbench 交互；
5. 继续遵守 DDD：先更新需求/契约，再代码、测试、真实 artifact 和 handoff。
