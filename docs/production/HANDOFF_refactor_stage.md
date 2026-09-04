# 阶段性 Handoff — radarAnalyze 生产级大重构

> **日期**: 2026-08-14（**2026-08-17 更新**）
> **分支**: `feature/production-refactor`（从 `feature/v3-architecture-redesign` 切出）
> **性质**: 8 阶段大重构的阶段交接。**更新：Stage 0-7 已全部实施并通过测试（465 passed / 1 skipped / 2 xfailed）。**

---

## 1. 总目标（复盘）

把 radarAnalyze 收敛到**生产级插件化目标态**（`docs/production/` 系列设计）：
- 三套并行系统收敛（确定性调查接入诊断）
- 真 ReAct Agent（LLM 规划 + 确定性执行，包在固定管线外）
- LanceDB 语义记忆 + 单一 L6 writer + freshness 覆盖 L1-L5
- 引擎层纯净（`engines/` 无 LLM）、插件 SPI 统一、项目隔离

**验收基线**：每个阶段 pytest 全绿（已知 1 个 stale 测试在 Stage 7 修）。

---

## 2. 当前测试状态

**最新全量**: `465 passed / 1 skipped / 2 xfailed`（2026-08-17，含新增 `tests/test_engine_package.py` 20 用例）

原唯一失败 `tests/test_phase16_identity_context.py::test_identity_context_resolves_default_variant`（硬编码 default_variant，属环境依赖的 stale 测试）**已在 Stage 7 修复**，现全绿。已知 1 skipped / 2 xfailed 为既有预期。

---

## 3. 已完成阶段（Stage 0-4）

### Stage 0 · 安全网 + 基线 ✅
- 新分支 `feature/production-refactor`
- 新增 `tests/test_refactor_smoke.py`（10 测试）：覆盖此前**零覆盖**的 `parameter_analyzer` / `frame_analyzer` / `platform_adapters`
- **发现并修复 P0-3**：`factory.py:108` 引用未导入的 `_SignalMapperDefault` → 任何未注册平台崩溃。改为惰性导入。

### Stage 1 · P0 止血 ✅
- **P0-1**：`ai/orchestrator.py` 新增真正的 `@property codegraph_db_path`（原 270-274 是死代码，orchestrator 无任何活路径解析）→ 恢复 CodeGraph 上下文 + Step7 代码修复
- **P0-1b**：`platform_id` 正确解包 `get_variant()` 三元组（`variant, codebase, _ = ...`）
- **P0-2**：adapter 分发 key 从 `self.identity.variant_id` → `self.platform_id`
- 新增 `tests/test_p0_fixes.py`（5 测试）

### Stage 2 · 插件框架 ✅
- 新建 `core/plugin.py`：统一 `PluginRegistry`（`register/get/registered/clear(kind)/discover`，装饰器 + importlib 自动扫包）。**`clear(kind)` 支持按命名空间清空**，避免测试污染内置插件
- 新建 `parsers/plugins/`：`base.py`（ParserPlugin SPI + ParserContext/ParserResult）+ bag/blf/mf4 三个插件
- `parsers/case_loader.py` blf/mf4 改走注册表（保留 bag 深解析 legacy + 旧 glob fallback）
- `ai/platform_adapters/factory.py` 改为经统一注册表 + `PluginRegistry.discover` 自动发现
- 新增 `tests/test_plugin_framework.py`（8 测试）
- **⚠️ P0-4 重大事故**：`gen5_gen.py`（一次性脚手架）**import 即覆盖 `gen5_reco_pl.py`** 为 19 字节占位 → 从 `.pyc` 反编译**完整恢复**（3 类 + 30 关键源文件 + 14 源码域 + 8 功能关键词 + 8 输出信号）。已把 `gen5_gen.py` 移到 `scripts/gen5_gen_scaffold.py.bak`
- 记录 `docs/production/02-surgery-defects.md` P0-3/P0-4

### Stage 3 · 引擎抽取（`engines/` 包）✅
- 新建 `engines/` 包，`git mv` 9 个确定性引擎：
  `temporal_analyzer / tpe / pattern_extractor / causal_aligner / data_probe / parameter_analyzer / test_window_detector / frame_analyzer / signal_mapper`
- **解决循环 import**：`engines.frame_analyzer` → `ai.utils` → `ai/__init__` → `ai.orchestrator` → `engines.frame_analyzer`
  → 方案：`ai/__init__.py` 改为 **PEP 562 惰性 `__getattr__`**，不再顶层 import orchestrator/code_learner/engine 子模块
- 更新所有 import（orchestrator/investigation_engine/condition_extractor/visualizer/modules/tools/memory/cli/scripts/tests）
- 遗留：部分 `:class:`ai.xxx`` **docstring** 未改（不影响 import，但建议 Stage 7 清理）
- 新增 `tests/test_engine_package.py`（待补，见「未完成」）

### Stage 4 · 收敛（investigation 接入诊断）✅
- `ai/orchestrator.py` Step4 新增**确定性调查块**：构建 `signal_lookup` → `EngineeringInvestigator.investigate()` → `investigation_section`（限长 `to_prompt_text`，默认 10000 字符）
- `ContextBudget` 新增 `investigation` 块（priority=92，min_chars=1000）
- 模块组合：`BaseModule`/`ModuleResult`/`MODULE_REGISTRY` 契约已就位，`DiagnosisPanelModule` 等可作为 orchestrator 的替代组合
- 测试：`test_modules_standalone` / `test_diagnosis_panel_module` / `test_signal_bridge_module` / `test_cli_module_dispatch` 全过

---

## 4. 已完成（Stage 5 · 真 ReAct Agent）✅

**已完成**：
- `ai/agent_loop.py`（`AgentLoop` 确定性顺序执行器 + `AgentState`/`AgentStep`/`AgentToolCall`）、`ai/model_router.py`（`chat(messages, complexity, tools, response_format)`）、`ai/agent_tool_registry.py`（`build_agent_tool_registry`/`resolve_agent_tool_context`）、`ai/tools/__init__.py`（TOOL_REGISTRY 6 工具）
- `ai/agent/react_planner.py`：真正的 **ReActPlanner**（LLM 规划子步骤 → `AgentToolCall` 序列）+ `run_react()` 便捷入口
- `ai/modules/react_agent.py`：**ReActModule**（`agent-repl` CLI 子命令），支持 `--objective`/`--context`/`--tool-call`（确定性 fallback）/`--no-llm`
- ReAct 循环**包在固定 8 步管线之外**，每个行动仍调确定性工具（DataProbe/TPE/CodeGraph）
- 测试：`test_react_agent.py` / `test_agent_loop*.py` / `test_agent_tool_registry.py` / `tools/run_agent_loop_smoke.py`

---

## 5. 已完成（Stage 6-7）✅

### Stage 6 · 记忆统一 ✅
- LanceDB 启用（`requirements.txt: lancedb>=0.5.0`），统一路径 `.workspaces/<variant>/memory/lancedb/`；`memory/semantic_memory.py` 支持 lancedb + fallback 双后端，`backend` 字段可断言
- 单一 L6 writer：`merge_code_knowledge` 统一 `CodeLearner` 与 precipitate 数据（`tests/test_memory_unification.py`）
- freshness 门控扩展到 L1-L5：L3 patterns + semantic hits（`TestFreshnessGatingL1L5`）

### Stage 7 · 清理收尾 ✅（部分）
- ✅ **修 stale 测试** `test_phase16_identity_context`（硬编码 default_variant）→ 全量现无失败
- ✅ `.gitignore` 加 `cases/**/*.mf4`
- ✅ **文档同步**：`ai/AGENTS.md` 模块概览 + 引擎章节标到 `engines/` 前缀，根 `AGENTS.md` 已更新
- ⚠️ **孤儿/死代码清理 保留**：`platforms/gen5_selena`（`test_config_gen`/`test_mf4_reader` 依赖）、`plugins/analysis/rule_engine`（`test_rule_engine` 依赖）**仍被测试引用，非死代码，未删除**；一次性 `scripts/bsd_*` 多数为历史探索脚本，保留待定
- 🔧 遗留小项：docstring 中 `:class:`ai.xxx`` 引用仅剩 `ai.agent_loop`/`ai.codegraph`（均有效，agent_loop 与 codegraph 仍在 `ai/`），无失效引用

---

## 6. 关键架构变更（后续继续必须知道）

### 新包结构
```
core/plugin.py            # 统一 PluginRegistry
parsers/plugins/          # ParserPlugin SPI + bag/blf/mf4 插件
engines/                  # 9 个确定性引擎（无 LLM）
  temporal_analyzer / tpe / pattern_extractor / causal_aligner
  data_probe / parameter_analyzer / test_window_detector
  frame_analyzer / signal_mapper
ai/                       # LLM 推理层（orchestrator/investigation/...）
ai/agent_loop.py          # 确定性顺序执行器（Stage 5 复用）
```

### ai/__init__.py 惰性加载（关键）
- **不要**恢复 `ai/__init__.py` 顶层 `from .orchestrator import ...` —— 那会重新引入循环 import
- 惰性 `__getattr__` 提供 `from ai import Orchestrator/CodeLearner/FrameAnalyzer/signal_mapper/...`
- **注意**：`import ai.signal_mapper`（子模块形式）**不再可用**（无物理文件）；测试/脚本请用 `from ai import signal_mapper` 或 `from engines import signal_mapper`

### 引擎 import 约定
- 引擎之间相对 import（`engines/tpe` 依赖 `causal_aligner/pattern_extractor/temporal_analyzer/signal_mapper`）→ 保持 `from .X` ✅
- 引擎依赖 ai 帮助函数 → 用 `from ai.utils import ...`（会触发 ai/__init__，但惰性后安全）
- 引擎**禁止** import `ai.orchestrator`

### 测试约定
- `PluginRegistry.clear()` 必须传 `kind` 参数（否则清空内置 parser 插件，导致跨文件污染）
- 新增引擎移动/插件测试用 `tests/test_refactor_smoke.py` / `test_plugin_framework.py` / `test_p0_fixes.py` 命名

---

## 7. 事故记录（后续必须规避）

| 事故 | 根因 | 修复 | 教训 |
|---|---|---|---|
| P0-3 `_SignalMapperDefault` 未定义 | factory 引用未导入类 | 惰性导入 | 引用即导入，或用统一注册表 |
| P0-4 `gen5_reco_pl.py` 被覆盖 | `gen5_gen.py` 模块顶层 `write_text` | 从 .pyc 反编译恢复 + 移到 scripts/ | **包内禁止 import 时文件写入副作用** |

---

## 8. 如何继续（下一步）

1. **Stage 5-7 主体已完成**，全量 465 passed 全绿。后续进入打磨/发布：
   - docstring 中 `:class:`ai.xxx`` 引用均为有效引用（`ai.agent_loop`/`ai.codegraph`），无需清理。
   - 决策一次性 `scripts/bsd_*` / `scripts/debug_*` 探索脚本的保留/归档（多数是历史探索，可移入 `scripts/archive/`）。
2. 每阶段完成后跑全量 `python -m pytest tests/ -q --no-header`（当前应 465 passed / 1 skipped / 2 xfailed）。
3. 合并前走一次 Harness gate（`tools/run_harness_gate.py`）确认报告回归。

---

## 9. 交接检查单

- [x] 分支 `feature/production-refactor` 存在
- [x] 465 passed（含 20 个 `test_engine_package.py` 用例）
- [x] 9 引擎已入 `engines/`，循环 import 已解
- [x] 插件框架就位（core/plugin + parsers/plugins + factory 自动发现）
- [x] investigation 接入诊断 Step4
- [x] P0-1/P0-1b/P0-2/P0-3/P0-4 已修
- [x] Stage 5 ReActPlanner（`ai/agent/react_planner.py` + `ReActModule` + CLI）
- [x] Stage 6 LanceDB + L6 统一 + freshness L1-L5
- [x] Stage 7 stale 测试 + .gitignore + AGENTS.md 同步
- [x] `tests/test_engine_package.py`（引擎包冒烟 20 用例）✅
- [ ] 归档一次性 `scripts/*` 探索脚本（打磨项，可选）

## 8.5 清理记录（2026-08-17）

按「保留最终项目，清空相关项目资料」清理工作区：

**已删除**（均已被 .gitignore 忽略，未影响 git 跟踪）：
- `cr60_light_arbe/`（288M，Arbe 雷达驱动 ROS 样例仓，含 .git/.vs，参考物料非产品代码）
- `cr60_light_convert_radar_dataset/`（5.9M，BLF→ROS bag 转换工具）
- `radarAnalyze_introduction.html/md`（生成介绍文档）、`blind_test_BSDLCA001.log`（一次性日志）

**保留**（与产品功能绑定，勿删）：
- `cases/`（2.4G 诊断测试数据，AGENTS.md 记录为产品输入）、`msg_defs/`（产品解析层，parsers/AGENTS.md 引用）
- 根目录 3 个 `.dbc`（config.yaml 多个 variant 的 DBC 路径直接引用，删除会破坏 DBC 解析）
- `platforms/`、`plugins/`、`source_docs/`、`.workspaces/` 等全部功能/缓存项

**验证**：删除参考仓后全量 `465 passed / 1 skipped / 2 xfailed`；Harness gate **6/6 passed**（blocking=0，`reports/harness_gate_20260817_230724.json`）。

> 注：工作区内**无压缩包**（zip/rar/tar/gz 全空）；`parsers/bag_parser.py` 对参考仓仅剩注释引用，无运行时依赖。

## 8.6 六代分析流程优化（2026-08-17）

按「五代保留框架，主力优化 6 代分析流程」推进。

**审阅结论**：六代（`gen6/byd_sc6h`）分析能力全量就位（L6/signal_mapping 76 条/variable_chains/codegraph 800 节点），但被知识新鲜度门控 fail-closed 卡死（`freshness_state.json` 缺失 + manifest 签名陈旧 → 知识进不了 AI 推理）。且六代源码路径为 GWM_B26/`adas\symmetry\` 硬编码，对 BYD_SC6H（`coem\BYD_UKE\`）定位不到。

**代码优化（已落地并通过测试）**：
1. `ai/code_learner.py` — 新增 `_resolve_constants_source_files()`：数值常量读取按 variant 自适应（从 `paths.key_source_files` 筛出存在的 `paraDefine/dotCalibDefine/adasFunc` 等），BYD 现在能读到自己的 `adasFunc.c`（ROI 线）+ `dotCalibDefine.h`（几何常量），不再「常量读不到」。
2. `config.py` — `_INTAKE_KEY_SOURCE_BASENAMES` 补 `ASWIN_AdasState`（BYD 系统状态）+ 新增 `constants` domain（`dotCalibDefine.h`/`AswIfSchedule.c`）：project_intake 推断对 BYD 产出 **9 条全部存在**的源码。
3. `config.yaml` — `variants.gen6/byd_sc6h.key_source_files` 修正为 BYD_UKE 真实文件（供非 intake 场景）。
4. `ai/orchestrator.py` — 新增 `_resolve_signal_mapping_source()`：`_init_signal_maps` 从 `paths.key_source_files` 定位 RteComMapping，避免默认 GWM_B26 路径导致 signal_mapping 重建为空。修复后 BYD 重建出 **76 条映射**（`RteComMapping.c` + `_Rx.c`，来源正确）。

**验证**：全量 `465 passed / 1 skipped / 2 xfailed`（无回归）。确定性链路已实证：
- `--learn-constants` 已能从 `D:\BYD-SC6H.../adasFunc.c` 读 40K 字符发送 LLM（原为「读不到跳过」）
- `cli.load_config(variant_id='gen6/byd_sc6h')` 的 `paths.key_source_files` 9 条全存在
- signal_mapping **76 条**双向映射可追溯：`internal_to_can`（代码变量→CAN）76 条、`can_to_internal` 67 条、`fullpath_to_can`（`VehcleInfoUpdate.actual_spd ↔ Vehicle_speed`）

**待续 — prewarm 刷新**：`--prewarm --prewarm-force --allow-branch-mismatch` 可刷新 L6 知识并解除 fail-closed。注意：当前 remote LLM 生成速率极低（约 0.1 tok/s），一次 40K 字符常量调用已观察 20+ 分钟未返回，**全量刷新在现有算力下不可行**；建议在 remote LLM 提速后执行，或减速 input 大小。确定性映射/追溯链路已不依赖该刷新即可工作。

## 附 · 记忆索引

- `production-design-decisions.md` — 4 个确认决策
- `p0-codegraph-deadcode.md` — P0-1/P0-1b 修复点
- `p0-gen5-gen-data-loss.md` — P0-4 事故与恢复
