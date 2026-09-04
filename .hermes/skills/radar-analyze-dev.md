---
name: radar-analyze-dev
description: Use when working on the radarAnalyze project — ADAS corner radar AI diagnostic system. Covers architecture design, feature development, CodeGraph integration, pipeline optimization, and multi-session coordination.
---

# radarAnalyze 产品开发

## 概述

radarAnalyze 是 AI 驱动的角雷达 (Corner Radar) 问题诊断系统，用于 TI AWR2E44P 嵌入式 ADAS 软件的 Bug 诊断和参数调优。支持 ROS1 Bag + Vector CAN BLF + DBC 数据格式。

**核心模式**: 产品经理 × 架构师 × 开发者三合一协作。你既是产品决策者也是执行者。每次对话结束时更新 handoff 文档。

## 协作流程

```
用户提需求/想法 → 你分析并提问澄清 → 达成共识 → 设计 → 实现 → 验证 → 更新 handoff → 下次对话继续
```

### 每次对话必须做

1. **读 handoff** — `docs/technical/codegraph-handoff-master.md` 是项目主 handoff
2. **读 AGENTS.md** — 根目录和各子模块的 AGENTS.md 是项目结构
3. **读 00-总览.md** — 架构文档入口
4. **结束时更新 handoff** — 记录完成内容、决策、待办

### Handoff 文档位置

| 文档 | 用途 |
|------|------|
| `docs/technical/codegraph-handoff-master.md` | **主 handoff** — 项目全局状态、架构决策、需求池 |
| `docs/technical/codegraph-phase1-handoff.md` | Phase 1 交付清单 |
| `docs/technical/codegraph-phase2-handoff.md` | Phase 2 交付清单 |
| `docs/technical/codegraph-handoff-v2.md` | 完整设计文档 (schema, query API, 适配层) |

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.11 |
| AI 模型 | Qwen3.5-27B (推理/规划), qwen3-coder:30b (编码) |
| AI Server | 10.190.161.39:8080 (Ollama + Nginx) |
| 远程 API | aigc.bosch.com.cn (Bosch Model Farm) |
| 数据存储 | SQLite (FrameStore, CodeGraph) |
| 可视化 | Plotly → 离线 HTML 报告 |
| 代码目标 | TI AWR2E44P C 代码 (AUTOSAR BSW + ASW + coem) |

## 诊断管线 (15 步)

| Step | 名称 | 模块 | CodeGraph 集成 |
|------|------|------|---------------|
| 1 | init + source_docs | code_learner | ✅ 静默构建 CodeGraph |
| 2 | understand | orchestrator | ✅ 注入 CodeGraph context |
| 3 | classify | problem_classifier | - |
| 4 | parse | case_loader | - |
| 5 | detect_window | test_window_detector | - |
| 6 | analyze | frame_analyzer | - |
| 7 | conditions | condition_extractor | ✅ CodeGraph 精确定位代码 |
| 8 | tpe | TemporalPatternEngine | - |
| 9 | probe | variable_query_planner | ✅ 优先查 CodeGraph |
| 10 | suppression | orchestrator | - |
| 11 | output_signals | orchestrator | - |
| 12 | params | parameter_analyzer | - |
| 13 | diagnose | expert_panel | 待做 |
| 14 | report | visualizer | 待做 |
| 15 | memory + done | memory_system | - |

## CodeGraph 架构

```
ai/codegraph/
  schema.py     — SQLite schema (7 节点 + 12 边 + 语义层 + 构建日志)
  analyzer.py   — 10 阶段 C 代码静态分析 (regex)
  builder.py    — 增量构建器 (hash 比对 → purge → rebuild)
  query.py      — 查询 API (CodeGraph 类)
  render.py     — 4 种 prompt 渲染器
```

**数据**: memory/codegraph.db (1381 节点, 9897 边, 首次 6s, 增量 15ms)

**模型路由**:
- `complexity='complex'` → Qwen3.5-27B (推理/规划)
- `complexity='coder'` → qwen3-coder:30b (编码, max_tokens≤2000, temp≤0.3)
- `complexity='simple'` → local (轻量任务)

## 关键约束

1. **用户无感** — CodeGraph 后台运行，不新增 CLI 命令
2. **零行为变更** — 诊断输出格式不变
3. **静默失败** — 构建失败不影响诊断
4. **分支** — 工作在 `refactor/codegraph`
5. **KV cache 保护** — coder 模型 max_tokens ≤ 2000
6. **max_tokens 控制** — 每个 prompt 都设 max_tokens，不浪费

## 运行命令

```bash
cd /d/RamboStar/idea/radarAnalyze

# 诊断
py -3.11 cli.py cases/FCATB001 -p "问题描述" -e "预期结果"

# CodeGraph 统计
py -3.11 cli.py --codegraph-stats

# 记忆巩固
py -3.11 cli.py --dream
```

## 相关 Skill

- `cr60light-issue-workflow`: CR60Light 问题单分析流程
- `chinese-code-review`: 中文 code review 沟通

## 目标代码库

| 项目 | 路径 |
|------|------|
| CR60Light (主) | D:/BYD-SC6H-cr60light/cr60_light |
| GWM_B26 平台 | coem/GWM_B26/ |
| BYD_SC6H 定制 | coem/BYD_SC6H/ |
| BYD_UKE (并行) | coem/BYD_UKE/ |
| 感知算法 | adas/symmetry/perception/ |
