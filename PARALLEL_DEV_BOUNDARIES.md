# 并行开发协调规范（subagent 交互边界）

> 三个 subagent 并行实施 V4 分片 P2 / P2b / P3。本规范防止文件冲突、保证可集成。

## 硬性规则

1. **文件所有权唯一**：每个 agent 只能写自己拥有的文件（见下）。公共/共享文件**一律不写**，只读。
2. **新增文件互不冲突**：三个 agent 的新增文件集合完全不相交。
3. **公共文件收口**：`ai/orchestrator.py`、`ai/modules/__init__.py`、`ai/tools/__init__.py`、`ai/tools/base.py`、`parsers/frame_store.py`、`requirements.txt` 只在各自 agent 的内部按 "唯一 owner" 规则交给**一个** agent 改，其余只读引用。
4. **不得 git commit / push / merge**：所有 agent 只改工作区文件，交回后由主线程统一集成、测试、提交。
5. **不改文档/设计**：设计已定稿（V4_*.md），agent 只实现，不改设计。
6. **不跑 LLM 长调用**：只做确定性实现 + 本地可跑的自测（pytest 或 python -c import 验证）。
7. **编码规范**：匹配现有代码风格（中文注释、`from __future__ import annotations`、dataclass、类型注解）；新增能力仍复用 `BaseTool`/`BaseModule`/`ModuleResult` 契约（见 `ai/tools/base.py`、`ai/modules/base.py`）。

## 各 agent 文件所有权

### Agent A — P2 数据统一 + 降级
**新增**：
- `parsers/providers/base.py`
- `parsers/providers/__init__.py`
- `parsers/providers/bag_provider.py`
- `parsers/providers/blf_provider.py`
- `parsers/providers/mf4_provider.py`
- `parsers/providers/dbc_provider.py`
- `parsers/providers/code_repo_provider.py`
- `engines/data_quality.py`
- `engines/data_availability.py`
**修改（唯一 owner）**：
- `parsers/frame_store.py`（加 `signal_catalog`、`data_quality` 表 + 兼容列）
- `parsers/case_loader.py`（接入 availability 分类，加 banner/data_gaps 挂点）
- `requirements.txt`（补 tree-sitter + tree-sitter-c）
**只读引用**：`ai/orchestrator.py`（知道 `_parse_case_data` 返回结构，不修改它）

### Agent B — P2b bug 修复 + HITL 基座
**新增**：
- `ai/tools/ask_user.py`（AskHumanTool）
- `ai/capability/artifacts.py`（per-step artifact 通道）
**唯一 owner 修改**：
- `ai/orchestrator.py`（修 B1 `probe_results`→`probe_results_list`；B2 包 router.chat）
- `ai/tools/base.py`（如需要 artifact 支持；尽量不改，用现有 envelope）
- `ai/tools/__init__.py`（注册 AskHumanTool）
- `tools/plot_signals.py`（扩展 radar_objects/radar_debug 绘图）

### C — P3 signal-extract 能力
**新增**：
- `engines/signal_catalog.py`
- `engines/signal_extract.py`
- `ai/modules/signal_extract.py`
**修改（唯一 owner）**：
- `ai/modules/__init__.py`（注册 SignalExtractModule）——注意这是共享文件，Agent C 唯一改它，Agent A/B 不得改。

## 各 agent 不得触碰的文件（防冲突）
- Agent A 不写 `ai/` 任何文件、不写 `tools/`。
- Agent B 不写 `parsers/`、`engines/` 新建文件（除 read）、不写 `requirements.txt`。
- Agent C 不写 `parsers/`、不写 `ai/orchestrator.py`、不写 `ai/tools/`、不写 `requirements.txt`。

## 集成 & 验收（主线程做）
1. 三个 agent 完成后，主 agent 汇总：
   - 检查无文件冲突（文件所有权不相交）。
   - `python -c "import ai.modules, engines, parsers"` 冒烟。
   - `pytest tests/ -x -q`（至少不新增失败）。
   - `tools/run_harness_gate.py --allow-known-edge`（如 LLM 无关）。
2. 统一解决 import / 契约问题。