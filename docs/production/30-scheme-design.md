# radarAnalyze 生产级设计体系 · 30 · 方案设计（迁移路线图 + 方案对比）

> **版本**: PROD-1.0 · 2026-08-13
> **本篇定位**: 把「现状」(00-02) 收敛到「目标态」(31-software-architecture) 的分阶段实现路径。每阶段标注目标/改动文件/不破坏现有诊断的保障/验收。

---

## 1. 总体思路

**先修 P0 止血，再统一分发 key，再建 Parser SPI，再收敛模块注册表，最后接入 orchestrator。** 每阶段可独立发布、可回滚、不破坏现有诊断。

---

## 2. 分阶段迁移路线图

### Phase 0 · 止血（P0-1, P0-1b, P0-2）

**目标**：恢复 CodeGraph 上下文 + 代码修复 + 平台适配器。细粒度任务分解：

| 任务 | 改动文件:行 | 验收 |
|---|---|---|
| 提取 `codegraph_db_path` 为独立 property | `ai/orchestrator.py:270-274` | 单测：`platform_id` 与 `codegraph_db_path` 独立 |
| 修 `platform_id` tuple 解包 | `ai/orchestrator.py:264-266` | 解包 `variant, codebase, _ = get_variant(...)`；注入非 gen6 variant 断言返回真实值 |
| 统一 adapter 分发用 `self.platform_id` | `ai/orchestrator.py:286-314` | 单测：adapter 非 None |
| `_ensure_adapters_loaded` 显式告警而非静默 | `ai/platform_adapters/factory.py:53-61` | 缺 adapter 时 logging.error |

**保障**：改动仅涉及 orchestrator 内部 + factory，不触碰管线其余部分。

**Phase 0 验收门**：
- [ ] 新增 `test_platform_id_and_codegraph_path_independent`
- [ ] 新增 `test_platform_id_resolves_real_platform`（非 gen6）
- [ ] 新增 `test_adapter_uses_platform_id`（非 None）
- [ ] 现有测试全绿（基线 408 pass）

### Phase 1 · 统一调查能力接入（P1-2, P1-3, P1-5）

**目标**：让 `investigation_engine`（确定性调查）服务诊断，统一 L6 写入，门控 L1-L5。

| 任务 | 改动文件 | 验收 |
|---|---|---|
| 统一 L6 写入者为单一 writer | `memory/memory_system.py` + `code_learner.py` + `orchestrator._precipitate_knowledge` | 无覆盖冲突 |
| freshness 门控扩展到 L1-L5 | `memory/memory_system.py:1047-1112` | 过期知识不注入 |
| 信号映射标注置信度 | `ai/signal_mapper.py:429-497` | 低置信→unknown |

### Phase 2 · 建 Parser SPI（FR-9.2）

**目标**：数据格式接入零改核心。

| 任务 | 改动文件 | 验收 |
|---|---|---|
| 定义 `ParserPlugin` 抽象接口 | `parsers/plugins/base.py` | 见 31 |
| 建 `ParserRegistry` + 自动发现 | `parsers/plugins/registry.py` | 装饰器注册 |
| `case_loader` 改为查注册表 | `parsers/case_loader.py:59-238` | 现有 .bag/.blf/.mf4 行为不变 |
| 迁移 3 个 parser 为插件 | bag/blf/mf4_parser.py | 回归测试通过 |

**保障**：`case_loader` 保留旧 glob 作为 fallback，新注册表优先。

### Phase 3 · 建统一模块 SPI（FR-9.3, 9.4）

**目标**：平台适配器/插件字段真正生效。

| 任务 | 改动文件 | 验收 |
|---|---|---|
| 统一 PluginRegistry 模型 | `ai/platform_adapters/factory.py` + `core/plugin.py` | 见 31 |
| 分发 `codegraph_plugin/parser_plugin/symbol_ruleset` | `builder.py`/`case_loader`/`signal_mapper` | 配置驱动生效 |
| 自动发现替代硬编码导入 | factory.py:53-61 | 新增模块零改 factory |

### Phase 4 · 收敛三套系统（P1-1）+ 真 ReAct Agent

**目标**：让 orchestrator 复用 `investigation_engine` 与模块 SPI；将 agent/tool 补全为**真 ReAct 自主循环**（用户已确认）。

| 任务 | 改动文件 | 验收 |
|---|---|---|
| 诊断 Step4 接入 `EngineeringInvestigator` | `ai/orchestrator.py:447-595` | 确定性调查进 prompt |
| 把 `ai/modules/*` 包装为 orchestrator 可组合 | `ai/modules/base.py` + orchestrator | 模块可 compose |
| 新增 `ReActPlanner`（LLM 规划子步骤） | `ai/agent/` | LLM 生成 plan |
| `AgentLoop` 接入 `ReActPlanner`，循环直到收敛 | `ai/agent_loop.py` | 真 ReAct（thought→action→observation） |
| ReAct 包在固定管线之外，行动仍调确定性工具 | orchestrator | 不颠覆确定性取证 |

### Phase 5 · 卫生与观测（P2）

| 任务 | 验收 |
|---|---|
| 修 stale 测试 + .gitignore 加 `*.mf4` | 测试全绿 |
| 文档同步（修 P2-1） | AGENTS.md 与代码一致 |
| 清理孤儿/死代码 | config 驱动 |

---

## 3. 关键设计方案对比与选型

### 3.1 解析分发：硬编码 glob vs 插件注册表

| 方案 | 优点 | 缺点 | 选型 |
|---|---|---|---|
| 硬编码 glob（现状） | 简单 | 新格式需改 case_loader | ✗ |
| **插件注册表 + 自动发现** | 零改核心 | 需建 SPI | ✅ FR-9.2 |

### 3.2 插件发现：装饰器+显式导入 vs entry_point

| 方案 | 优点 | 缺点 | 选型 |
|---|---|---|---|
| 装饰器+显式导入（现状） | 无依赖 | 需手改导入列表 | △ 过渡期 |
| **装饰器+自动扫包(importlib)** | 零改核心 | 需扫包约定 | ✅ |
| entry_point | 标准 | 需安装为包，离线不便 | ✗ |

### 3.3 investigation 接入：query 专用 vs 诊断复用

| 方案 | 优点 | 缺点 | 选型 |
|---|---|---|---|
| 仅 query 用（现状） | 简单 | 诊断缺确定性调查 | ✗ |
| **诊断 Step4 复用** | 证据更强 | 需接 prompt | ✅ Phase 4 |

### 3.4 L6 写入：双 writer vs 单一 writer

| 方案 | 优点 | 缺点 | 选型 |
|---|---|---|---|
| 双 writer + 覆盖（现状） | 无 | 数据丢失风险 | ✗ |
| **单一 writer + 单一 schema** | 一致 | 需迁移 | ✅ Phase 1 |

### 3.5 记忆后端：LanceDB vs fallback

| 方案 | 优点 | 缺点 | 选型 |
|---|---|---|---|
| LanceDB | 语义召回强 | 需装依赖、路径统一 | △ 决策后 |
| fallback（现状） | 零依赖 | 召回弱 | △ 若诉求不高 |

---

## 4. 阶段依赖关系

```
Phase 0 (止血) ─► Phase 1 (调查/记忆) ─► Phase 2 (Parser SPI)
      │                                        │
      └───────────────► Phase 3 (模块 SPI) ◄───┘
                              │
                              └► Phase 4 (收敛) ─► Phase 5 (卫生)
```

---

## 5. 验收门（每阶段）

- 现有测试全绿（基线 408 pass）。
- 新增单测覆盖改动点。
- 真实案例（CR60 Light）诊断不回归。
- Harness 回归门（`tools/run_harness_gate.py`）通过。

---

> **下一篇** → `31-software-architecture.md`：软件架构设计（目标态，最细）。