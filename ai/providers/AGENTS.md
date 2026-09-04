# ai/providers/ — 外部系统窄适配器

## 目录职责

Provider 只负责把稳定的 Pi 输入契约转换为外部项目的 argv/API 调用，并把返回码、
stdout、stderr、产物和诊断原样带回。Provider 不拥有 bag 解析、源码语义、HTML 视图、
算法参数真值，也不允许把对话文本拼成 shell 命令。

## CR60 `cr60_harness.py`

| 公开对象 | 职责 |
|---|---|
| `convert_intake_to_manifest(...)` | 无副作用地将 `cr60-analysis-intake.v1` 转为 harness 的 `intake-manifest.v1` |
| `Cr60HarnessProvider` | 生成/执行 `folder-analyze` 或 `batch-analyze` argv，并收集标准产物 |
| `Cr60HarnessProvider.build_gdb_plan_command(...)` | 从 `runtime-debug-plan.v1` 生成 plan-bound sibling runner argv，不生成断点语义 |
| `Cr60HarnessProvider.run_gdb_plan(...)` | 默认 plan-only；批准后执行隔离 ROS/GDB runner，并收集 `gdb-session.v1` |
| `Cr60HarnessProvider.build_gdb_attach_plan_command(...)` | 将 source-bound plan 转为正式 existing-PID attach runner argv，不启动 arbe |
| `Cr60HarnessProvider.run_gdb_attach_plan(...)` | 重新发现 node/PID、校验 executable 后执行正式 GDB attach；需审批 |
| `Cr60HarnessProvider.run_formal_start(...)` | 调用 sibling formal-start runner，记录 `arbe-start-session.v1` ownership/PID |
| `Cr60HarnessProvider.run_formal_stop(...)` | 调用 guarded stop runner，仅处理 tool-owned process group；需审批 |
| `engines.arbe.build.run_catkin_make(...)` | 通过显式 SSH/local runner 运行 `catkin_make`，返回 `arbe-build-session.v1`；不承担 source/CUDA/start |
| `LocalHarnessCommandExecutor` | 使用 `subprocess.run(..., shell=False)` 执行已生成 argv |

执行默认由上层 `CR60PrecheckModule` 设为 `execute=false`；只有用户确认后才执行。对
`batch-analyze` 的 case-level 非零结果保留 `batch_summary.json`、报告和原始进程输出，
不能把部分成功误报成全局失败。Provider 不直接切分支、不改 arbe；`run_gdb_plan` 只在
显式批准后启动隔离 ROS/GDB，不隐式替代正式 `bash start` 或 existing-PID attach。
`run_gdb_attach_plan` 只 attach 已存在且 executable identity 通过的正式 PID；
`run_formal_start/stop` 是独立 lifecycle provider，不能由 attach 隐式调用。

`ai/capability/module_bridge.py` 将上层模块以受控方式暴露给 `AgentLoop`/`ReActPlanner`；
它不改变 Provider 的权限边界，默认只允许 `cr60-precheck` 生成计划，不能从 LLM 直接
执行 `execute=true`。

任何新 Provider/API/schema 变更必须同步更新根目录 `AGENTS.md`、模块设计文档、契约
测试和对应 handoff。

执行成功后，`Cr60HarnessProvider.run_command()` 额外返回 `output_dir` 和
`case_artifacts[]`，逐条列出 `diagnosis_bundle.json`、`viewer-model.json`、可用 runtime/debug
artifact 以及 `report.html`。这些是 Pi 从批量结果进入详细报告的权威引用；Pi 不应从目录名猜测
bundle/viewer 路径。
