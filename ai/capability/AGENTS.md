# ai/capability 维护说明

本目录是 Pi 与确定性能力之间的控制面，不承载具体的 bag 解码、算法判断或
远程 shell 业务逻辑。

## 公开边界

| 文件 | 职责 | 关键约束 |
|---|---|---|
| `registry.py` | 从 `MODULE_REGISTRY`/`TOOL_REGISTRY` 生成能力 catalog | name/description/schema/审批元数据单一来源 |
| `module_bridge.py` | 把 leaf `BaseModule` 适配成 AgentLoop/ReAct 可执行的 `BaseTool` | 默认只计划；递归编排根不进入 leaf registry |
| `tool_bridge.py` | 兼容现有确定性 `BaseTool` 的 JSON bridge | 不猜上下文，不吞掉错误 |
| `pi_tool_bridge.py` | Pi Extension 的唯一 Python 调用边界 | 同时分派 BaseTool/Module adapter；默认不开放副作用 |
| `project_context.py` | variant/workspace 隔离和 fail-closed 资源检查 | 不跨项目回退缓存 |

## Pi 扩展契约

`scripts/gen_pi_extension.py` 从 catalog 生成 `.pi/extensions/radar-capabilities.ts`。
生成的 `registerTool.execute` 必须：

1. 将 Pi 的 `params` 作为独立 JSON argv 传给 `python -m ai.capability.pi_tool_bridge`；
2. 不复制任何算法、ROI、功能名或远程操作逻辑；
3. 排除 `pi`、`agent-loop`、`agent-repl` 和 `ask_user` 等编排/交互根；
4. 显式加载当前项目的 extension，不能依赖未确认的 project trust；
5. 保留统一 `{status,message,data,artifacts}` envelope。

未声明 `input_schema` 的历史 BaseModule 由 `registry.module_input_schema()` 从真实
`run()` 签名和 `register_cli()` 保守推导参数；ModuleToolAdapter 调用已有
`from_cli_args(SimpleNamespace(**params))`，使构造期的 BLF/MF4/source 路径仍可被
Pi 使用。明确声明的 schema 优先，不被推导结果覆盖。

生成的 extension 使用 `CR60_RADAR_ANALYZE_PYTHON`（未设置时为 `python`）选择
bridge 解释器，适配不同用户的 Python/venv；生成文件用原子替换更新，避免并发 Pi
会话读到半个文件。

## PiRunContext

`engines.pi_context.build_pi_orchestration_context()` 与
`ai.modules.pi_context.PiContextModule` 生成 `pi-orchestration-context.v1`。
它只合并显式输入、intake 和 preflight artifact；字段缺失或冲突必须进入
`partial`/`blocked`，不得由 LLM 或路径名称补全。Pi 可以追加 artifact 引用，
不能覆盖 `project`、source fingerprint 和 policy。

Pi 详细分析请求可由 `ai/modules/pi.py` 生成确定性 `evidence_anchor`：它复用
`diagnostic-report` 的 `executive_summary`、condition digest、几何关系和 runtime 层，
并按显式 function/side/frame/radar 绑定。anchor 中没有的 observed/runtime/CAN 事实不能
由 Pi 补全；报告请求自动生成的 HTML/JSON/Markdown 必须作为 artifact refs 和
`evidence-anchor` AnalysisStep 记录。多事件且没有唯一业务 scope 时必须 partial，不得选第一个事件。

## 变更与测试

- 修改 catalog 字段、Pi bridge 参数或 context schema 时，同时更新
  `contracts/`、`docs/technical/CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md`、
  模块设计和测试。
- 运行 `tests/test_pi_context.py`、`tests/test_pi_tool_bridge.py`，再跑完整
  radarAnalyze pytest。
- 远程写入、编译、启动、GDB attach/execute 不得通过默认 Pi bridge；必须有
  supervisor 的批准结果和 audit artifact。
