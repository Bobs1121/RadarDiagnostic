# radarAnalyze 生产级设计体系 · 02 · 缺陷清单与根因

> **版本**: PROD-1.0 · 2026-08-13
> **本篇定位**: 生产级设计的「现状基线」。每条缺陷含：现象 / 复现位置(file:line) / 根因 / 影响面 / 修复方向。P0=功能失效，P1=架构一致性，P2=卫生与文档。

---

## P0 · 功能失效

### P0-1 `codegraph_db_path` 死代码 → CodeGraph 上下文 + 代码修复功能失效

- **现象**：`ai/orchestrator.py` 中 `self.codegraph_db_path` 被 5 处引用，但该属性**根本不存在**。
- **复现位置**：`ai/orchestrator.py:270-274`（死代码，被 `except` 块吞掉）；引用点 `680 / 865 / 1990 / 2065 / 2118`。
- **根因**：`codegraph_db_path` 的 property 函数体**孤儿化**——被错误地嵌在 `platform_id` property 的 `except` 分支之后（270-274），永远不可达。AST 确认全文件只有 `def platform_id`、无 `def codegraph_db_path`。
- **影响面**：
  - 680 行 → 诊断 prompt 的 CodeGraph 语义上下文恒为空。
  - 865 行 → CG 节点统计恒为 0。
  - 2065 行 → **代码修复功能（Step 7）恒失败**（此处 try 之外直抛）。
  - 1990/2118 行 → CG 构建/渲染失败。
- **修复方向**：把 270-274 行提取为独立 `@property def codegraph_db_path`，删除孤儿代码块；补单测断言 `platform_id` 与 `codegraph_db_path` 各自独立。

### P0-1b `platform_id` property 的 tuple 解包 bug（连带缺陷）

- **现象**：`ai/orchestrator.py:264-266` 写成
  ```python
  variant = get_variant(self.config, self.variant_id)   # 返回 (variant, codebase, platform)
  codebase = get_codebase(self.config, variant.codebase_id)  # tuple 当对象用 → AttributeError
  ```
  但 `get_variant()`（config.py:798-830）**返回三元组** `(variant, codebase, platform)`。
- **根因**：property 把 tuple 当单对象解引用 `variant.codebase_id`，恒抛 `AttributeError` → 恒走 `except` 返回 `"gen6_c_radar"` fallback。
- **影响面**：`platform_id` **任何真实平台都无法解析**（恒回落 gen6_c_radar）。即使 `codegraph_db_path` 修好，GC 路径仍可能因 platform 错判而选错扫描策略。
- **修复方向**：解包
  ```python
  variant, codebase, _ = get_variant(self.config, self.variant_id)
  return codebase.platform_id
  ```
- **验收**：单测注入一个非 gen6 的 variant，断言 `platform_id` 返回真实值而非 fallback。

### P0-2 PlatformAdapter 分发用错 key → 平台适配器静默失效

- **现象**：`_get_code_learner_adapter` / `_get_condition_extractor_adapter` 用 `self.identity.variant_id`（如 `gen6/gwm_b26`）查注册表，而注册表按 `platform_id`（如 `gen6_c_radar`）key。
- **复现位置**：`ai/orchestrator.py:286-314`；注册表 `ai/platform_adapters/factory.py:22-45`。
- **根因**：调用方传错 key；`except` 静默吞掉 `KeyError`，adapter 置 `None`。
- **影响面**：Gen6/Gen5 的 func_keywords、source_domains、focus_files 等平台定制**从未生效**（除 codegraph 扫描路径 2011 行正确用 `self.platform_id`）。
- **修复方向**：统一用 `self.platform_id`；`_ensure_adapters_loaded` 改为自动发现（见 31-software-architecture）；失败显式告警而非静默。

### P0-3 `_SignalMapperDefault` 未定义 → 未注册平台崩溃（Stage 0 发现）

- **现象**：`factory.py:108` 引用 `_SignalMapperDefault`，但该类定义在 `gen6_symmetry.py:309`，**从未被 factory 导入**。
- **复现位置**：`ai/platform_adapters/factory.py:108`；定义 `ai/platform_adapters/gen6_symmetry.py:309`。
- **根因**：factory 的 fallback 分支引用了未导入的类 → 任何未注册 platform_id 触发 `NameError` 崩溃。
- **影响面**：新增平台/未知 platform 一律崩溃，而非优雅 fallback。**已在 Stage 0 修复**（factory 惰性导入 `_SignalMapperDefault_cls`）。
- **修复后**：`_SignalMapperDefault` fallback 生效，未注册平台返回空映射不崩溃。

### P0-4 `gen5_gen.py` 危险脚手架：import 即覆盖真实适配器（Stage 2 发现）

- **现象**：`ai/platform_adapters/gen5_gen.py` 是一个一次性脚手架脚本，**只要被 import 就会把 `gen5_reco_pl.py` 覆盖为 19 字节 `PLACEHOLDER_CONTENT`**（模块顶层直接 `write_text`）。
- **复现位置**：`ai/platform_adapters/gen5_gen.py:8`（顶层 `write_text`）。
- **根因**：该脚本是早期「生成占位适配器」的一次性工具，被遗留在包内；任何自动发现/批量导入（如本重构的 `PluginRegistry.discover`）都会执行它。
- **影响面**：`gen5_reco_pl.py`（真实 Gen5 ReCo 适配器）被**永久覆盖**，需从 `.pyc` 反编译恢复（本次已恢复全部数据：3 类 + 30 关键源文件 + 14 源码域 + 8 功能关键词 + 8 组输出信号）。
- **修复**：已将 `gen5_gen.py` 移出包（→ `scripts/gen5_gen_scaffold.py.bak`），禁止自动导入触发写入；恢复的 `gen5_reco_pl.py` 已验证 import 正确。
- **教训**：包内**禁止任何模块顶层执行文件写入副作用**；脚手架/生成器应放 `scripts/` 并显式调用。

---

## P1 · 架构一致性

### P1-1 三套并行系统未统一（诊断/查询/Agent）

- **现象**：orchestrator 不 import `investigation_engine`、`agent_loop`、`agent_tool_registry`、`ai/modules/*`、`ai/tools/*`、`ai/requirements/*`。
- **复现位置**：`ai/orchestrator.py:13-31`（import 列表）。
- **根因**：V3 模块化设计与 legacy 管线并行演进，未做收敛。
- **影响面**：`investigation_engine` 的确定性调查能力（query 模式已证明有价值）未服务诊断；Agent/tool 半成品无生产价值。
- **修复方向**：见 `30-scheme-design.md` 收敛路线图。

### P1-2 两个 L6 写入者冲突，可能互相覆盖

- **现象**：`orchestrator._precipitate_knowledge`（2359-2507）与 `CodeLearner`（auto_dream Phase0）都写 `memory/code_knowledge/{FUNC}.json`，schema/id 约定不同。
- **根因**：`_precipitate_knowledge` 走受门控的 `read_code_knowledge`，stale 时从 `{}` 起，可能覆盖 CodeLearner 新学数据。
- **修复方向**：统一 L6 写入者为单一 writer + 单一 schema；或 `_precipitate_knowledge` 改为 append-only 不覆盖。

### P1-3 freshness「硬约束」仅护 L6，L1-L5 绕过

- **现象**：AGENTS.md 声称「freshness 缺失/不匹配的学习产物不得进入 prompt」，但 `build_context_for_diagnosis`（memory_system.py:1047-1112）L1-L5 无条件注入。
- **根因**：门控只实现在 `read_code_knowledge/read_constants`（L6）。`runtime_knowledge_decision`（knowledge_guard.py:104-119）在无 variant_id 时完全放行。
- **修复方向**：将门控扩展到 L1-L5 或明确标注其不受约束；legacy 模式禁止静默放行。

### P1-4 LanceDB 语义记忆休眠 + 路径不一致

- **现象**：`lancedb` 未安装（requirements.txt:20 注释掉），实际跑 fallback（纯 Python cosine）。`MemorySystem` 用 `memory_dir/semantic`，`SemanticMemory.for_variant` 用 `.workspaces/<variant>/memory/lancedb`。
- **复现位置**：`memory/semantic_memory.py:61-67, 194-206, 213-246`；`memory/memory_system.py:172`。
- **修复方向**：决策二选一——启用 LanceDB 并统一路径，或删除 LanceDB 代码、明确 fallback 为唯一实现。

### P1-5 信号映射模糊启发式可误判

- **现象**：`resolve_internal_to_can`（signal_mapper.py:429-497）第 4-7 级是子串模糊猜测（大小写不敏感、≥5字符核心子串双向 in 匹配），可能错配。
- **影响面**：错误但存在的映射会让条件检查给出误导性结论。
- **修复方向**：映射结果标注置信度；低置信映射降级为 `unknown` 而非盲目比对。

---

## P2 · 卫生与文档

### P2-1 文档与代码漂移

- 早期设计曾引用不存在的 `cli.py triage` 和 `cli.py data plot`；当前入口请以
  `python cli.py --help`、`python cli.py capabilities --json` 和统一文档索引为准。
- M5(MemoryFabric)/M8(RequirementReview) 在 `ai/modules/` 无对应文件。
- `memory/AGENTS.md` 声称「不用锁/Path.write_text」→ 代码实际用 `atomic_write_json`。
- `memory/AGENTS.md` 行号已过期（如 `add_pattern` 引 113-132，实际 375）。

### P2-2 stale 测试

- `tests/test_phase16_identity_context.py::test_identity_context_resolves_default_variant` 硬编码 `default_variant=gen6/gwm_b26`，config 已改为 `gen6/byd_sc6h` → **唯一失败测试**。

### P2-3 仓库卫生

- 12MB `cases/TestMF4/*.mf4` 被 git 跟踪，`.gitignore` 无 `*.mf4` 规则。
- 根目录 3 个重复 `.dbc` 文件。
- 166 个未提交变更；~50 个一次性 `scripts/*.py`。
- 根目录散落 `__pycache__`、`.pytest_cache_codex`。

### P2-4 孤儿/死代码

- `platforms/gen5_selena/*`、`plugins/analysis/rule_engine.py` 仅测试引用。
- `gen5_gen.py` 是占位 stub。
- `ai/fallback.py` 的 `fallback_*` 函数多数未被调用。

---

## 缺陷优先级矩阵

| ID | 严重度 | 影响链路 | 修复成本 | 建议时机 |
|---|---|---|---|---|
| P0-1 | 🔴 高 | 诊断 L1 | 低 | Phase 0 立即 |
| P0-1b | 🔴 高 | 诊断 L1 | 极低 | Phase 0 立即 |
| P0-2 | 🔴 高 | 诊断 L1 | 低 | Phase 0 立即 |
| P0-3 | 🔴 高 | 全平台 | 极低 | ✅ 已修 (Stage 0) |
| P0-4 | 🔴 高 | 平台适配器 | 中 | ✅ 已修 (Stage 2) |
| P1-1 | 🟠 中 | 全架构 | 高 | Phase 2-3 |
| P1-2 | 🟠 中 | 记忆 | 中 | Phase 1 |
| P1-3 | 🟠 中 | 记忆 | 中 | Phase 1 |
| P1-4 | 🟡 低 | 记忆 | 中 | 决策后 |
| P1-5 | 🟡 低 | 调查 | 低 | Phase 1 |
| P2-x | 🟡 低 | 维护性 | 低 | 随时 |

> **下一篇** → `10-prd.md`：生产级产品需求文档。
