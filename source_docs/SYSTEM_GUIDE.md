# radarAnalyze 系统全功能报告

## 1. 系统概述

角雷达 (Corner Radar) 问题分析系统，基于 AI (Qwen3.5-27B-FP16 + 本地 qwen3:14b) 驱动的自动化诊断平台。
目标平台：TI AWR2E44P，覆盖 8 大 ADAS 功能：

| 分组 | 功能 | 全称 |
|------|------|------|
| 后角雷达 | BSD | Blind Spot Detection |
| | LCA | Lane Change Assist |
| | DOW | Door Open Warning |
| | RCW | Rear Collision Warning |
| | RCTA | Rear Cross Traffic Alert |
| | RCTB | Rear Cross Traffic Braking |
| 前角雷达 | FCTA | Front Cross Traffic Alert |
| | FCTB | Front Cross Traffic Braking |

## 2. 三种使用模式

### 2.1 诊断模式 (Diagnosis)

```bash
python cli.py <case_folder> -p "问题描述" -e "预期结果"
```

**全自动诊断管线（10步）**：

| 步骤 | 阶段 | 说明 |
|------|------|------|
| 1 | 记忆整合 (Dream) | 自动整合积累的诊断知识（可跳过） |
| 2 | 源码文档检查 | 确保 8 大功能的 MD 分析文档已生成 |
| 3 | 信号映射构建 | 从 RteComMapping.c 确定性提取 CAN↔内部变量映射 |
| 4 | 问题理解 | AI 识别涉及的 ADAS 功能 |
| 5 | 数据解析 | 解析 BAG/BLF 文件入 FrameStore (SQLite) |
| 6 | 测试窗口检测 | 自动定位功能活跃的时间段（状态跳变/目标出现/速度变化） |
| 7 | 帧级分析 | 提取状态跳变、警告时间线、目标速度、CAN 值 |
| 8 | 条件提取 | AI 从源码提取激活/抑制条件树，含外部抑制信号极性 |
| 9 | 外部抑制检查 | 通过信号映射 + 变量链在 BLF 数据中实测抑制信号状态 |
| 10 | 专家面板 | 5 位专家 × 3 轮研讨 → 综合报告 |

**输出文件**：
- `cases/<CASE>/report.md` — 诊断报告（根因、条件检查表、数据链路、修复建议）
- `cases/<CASE>/expert_opinions.md` — 5 专家详细分析记录
- `cases/<CASE>/memory.json` — 案例级记忆 (L5)

### 2.2 数据查询模式 (Query)

```bash
python cli.py <case_folder> -q "FCTB触发时AEBIB是否激活"
```

**增强能力**：
- 接入 `signal_mapping.json` — 回答 "bAEBBAActiveFlg 对应什么 CAN 信号"
- 接入 `*_conditions.json` — 回答 "FCTB 的触发条件是什么"
- 接入 `*.md` 功能文档 — 提供逻辑背景

### 2.3 记忆整理模式 (Dream)

```bash
python cli.py --dream
```

**4 阶段自动整合**：Orient → Gather → Consolidate → Prune

**自动触发条件**：距上次 ≥4h 且新增 ≥2 个诊断会话

### 2.4 交互模式

```bash
python cli.py <case_folder>
```

不指定 `-q` 或 `-p` 时，交互式选择模式。

## 3. 信号映射与变量链追踪

### 3.1 信号映射 (signal_mapping.json)

**确定性、无 AI**。从 `RteComMapping.c` 用正则解析 `RteComMapping_ReadSignal` 调用及后续赋值语句。

```
RteComMapping_ReadSignal(AEBBAActv_0x137)(&u8tmp)
→ PERInputCapture.DTCCode.bAEBBAActiveFlg = (u8tmp != 0)
```

生成双向索引：
- `internal_to_can`: 内部变量 → CAN 信号名
- `can_to_internal`: CAN 信号名 → 内部变量
- `fullpath_to_can`: 完整路径 → CAN 信号名（支持点号路径直查）

当前提取 **91 条** 映射。

### 3.2 变量链追踪 (variable_chains.json)

**确定性、无 AI**。扫描 `globalVariDef.c` 中的结构体指针拷贝模式：

```c
void VarGlobal(DTCStruct* DTCCode, ...) {
    g_DTCCode = *DTCCode;   // struct copy via pointer
}
```

结合 RteComMapping.c 的写入前缀，建立别名：

```
g_DTCCode  →  PERInputCapture.DTCCode
```

使得 `g_DTCCode.bAEBBAActiveFlg`（代码中使用）可追溯到 `AEBBAActv_0x137`（CAN 信号）。

### 3.3 完整解析优先级

```
1. 精确匹配 short name / fullpath
2. 点号路径末段提取 (g_DTCCode.bAEBBAActiveFlg → bAEBBAActiveFlg)
3. 结构体别名展开 (g_DTCCode.X → PERInputCapture.DTCCode.X)
4. 大小写不敏感匹配
5. 核心关键字 (≥5字符)
6. 严格模糊兜底 (cutoff=0.7 + 语义token重叠≥45%, 仅简单信号名)
```

### 3.4 signal_chain.md

按语义分类的信号链路参考：Vehicle Dynamics / Function Switches / Safety Systems / Door & Body / Wheel Speed / Other。

## 4. 条件提取与抑制检测

### 4.1 条件提取 (FUNC_conditions.json)

AI 从多域源码提取结构化条件树，包含：
- `system_state.transitions` — 状态机转换条件及阈值
- `external_suppression` — 外部抑制信号，含 `suppression_trigger`（触发值）和 `normal_value`（正常值）
- `ego_speed_ranges` / `target_speed_ranges` — 速度范围
- `other_conditions` — Brake Hold 时长阈值等

**极性规则强化**：prompt 明确要求"变量名含 Active 不代表 TRUE 是抑制条件"，并提供反直觉模式示例：
```
代码: if((!bAEBBAActiveFlg) && (!bAEBIBActiveFlg)) { bKeepBrake=false; }
→ suppression_trigger='== FALSE', normal_value='== TRUE'
```

### 4.2 抑制信号实测

`_check_suppression_signals` 流程：
1. 加载 signal_mapping + variable_chains
2. 对每个抑制条件，通过映射解析到 BLF 中的 CAN 信号
3. 提取信号时间线，用 `_evaluate_threshold` 评估条件满足率
4. **双极性交叉检查**：同时评估反向阈值，当两者结论矛盾时输出警告
5. 未找到的信号明确标注"未在 BLF 中找到"（不猜测）

### 4.3 阈值评估器

`_evaluate_threshold` 支持的格式：
`TRUE`, `FALSE`, `== TRUE`, `== FALSE`, `== 0`, `!= 0`, `> N`, `>= N`, `< N`, `<= N`

## 5. 专家面板

5 位领域专家并行分析 × 3 轮迭代：

| 专家 | 职责 |
|------|------|
| signal_chain | 信号链路追踪、CAN→内部变量映射验证 |
| algorithm | 算法逻辑、状态机转换条件检查 |
| system_state | 系统状态时序分析、防抖机制 |
| perception | 感知目标特征、TTC/TTM 分析 |
| architecture | 左右雷达合并逻辑、架构级风险 |

**数据溯源规则**：每个结论必须注明数据出处（抑制信号实测/条件检查表/帧分析数据/BAG数据），禁止引用系统未提供的信号。

## 6. 记忆系统 (5 层)

| 层级 | 文件 | 作用域 | 内容 |
|------|------|--------|------|
| L1 | `memory/project.md` | 全局 | 系统架构、通用知识、用户偏好 |
| L2 | `memory/functions/FUNC.json` | 按功能 | 功能知识、已知问题、诊断经验 |
| L3 | `memory/patterns.json` | 全局 | 学习到的诊断模式库 |
| L4 | `memory/sessions/*.json` | 按会话 | 中间过程、推理链 |
| L5 | `cases/CASE/memory.json` | 按案例 | 案例级结论、关键发现 |

**隔离原则**：L1 只存通用架构知识，不存个案结论。

**AutoDream 整合**：每次 dream cycle 自动刷新 variable_chains.json，并将信号映射统计、变量链别名纳入整合上下文。

## 7. 缓存与失效机制

| 缓存文件 | 位置 | 生成方式 | 失效条件 |
|----------|------|----------|----------|
| `signal_mapping.json` | source_docs/ | 确定性正则 | RteComMapping.c SHA256 变更 |
| `signal_chain.md` | source_docs/ | 确定性 | 随 signal_mapping.json |
| `variable_chains.json` | source_docs/ | 确定性正则 | 手动删除或 AutoDream 刷新 |
| `FUNC_conditions.json` | source_docs/ | AI 提取 | 任一源码 mtime > 缓存 mtime |
| `FUNC.md` | source_docs/ | AI 生成 | 手动删除后重新生成 |
| `variables.json` | source_docs/ | AI 生成 | 手动删除后重新生成 |

## 8. 模型配置

| 模型 | 用途 | 部署 |
|------|------|------|
| Qwen3.5-27B-FP16 | 复杂任务（诊断、条件提取、专家面板） | 远端服务器 10.190.179.61 |
| qwen3:14b | 简单任务（摘要、格式化） | 本地 Ollama |

**思考模式** (`config.yaml → ai.thinking`)：
- `off` — 全部关闭，最快
- `synth` — 仅 Round 3 综合开启
- `full` — 所有 complex 调用开启（深度分析用）

## 9. 目录结构

```
radarAnalyze/
├── cli.py                          # 统一入口（诊断/查询/Dream）
├── config.yaml                     # 模型、路径、功能配置
├── parse_data.py                   # 独立数据解析脚本
├── requirements.txt                # 依赖
├── *.dbc                           # CAN 数据库定义文件
│
├── ai/                             # AI 核心引擎
│   ├── orchestrator.py             # 诊断总调度（10步管线）
│   ├── expert_panel.py             # 5专家面板
│   ├── condition_extractor.py      # 条件提取（含极性规则）
│   ├── signal_mapper.py            # CAN信号映射 + 变量链追踪
│   ├── frame_analyzer.py           # 帧级数据分析
│   ├── test_window_detector.py     # 测试窗口检测
│   ├── data_query_engine.py        # 数据查询引擎
│   ├── code_analyzer.py            # 源码分析文档生成
│   ├── model_router.py             # 双模型路由
│   └── utils.py                    # 共享工具
│
├── parsers/                        # 数据解析层
│   ├── bag_parser.py               # ROS Bag V1 解析
│   ├── blf_parser.py               # Vector BLF 解析
│   ├── dbc_loader.py               # DBC 加载与路由解码
│   ├── frame_store.py              # SQLite 内存数据仓库
│   └── time_sync.py                # BAG/BLF 时间对齐
│
├── memory/                         # 5层记忆系统
│   ├── memory_system.py            # L1-L5 读写 API
│   ├── auto_dream.py               # 记忆整合引擎
│   ├── project.md                  # L1 全局记忆
│   ├── patterns.json               # L3 模式库
│   ├── dream_log.json              # Dream 运行记录
│   ├── functions/                  # L2 按功能知识
│   │   └── {BSD,LCA,...,FCTB}.json
│   └── sessions/                   # L4 会话快照
│       └── CASE_YYYYMMDD_HHMMSS.json
│
├── source_docs/                    # 固化知识缓存
│   ├── signal_mapping.json         # CAN↔内部变量映射 (91条)
│   ├── signal_chain.md             # 分类信号链路参考
│   ├── variable_chains.json        # 结构体别名 (g_DTCCode等)
│   ├── FCTB_conditions.json        # 条件提取缓存
│   ├── {BSD,...,FCTB}.md           # 功能分析文档
│   ├── variables.json              # 关键变量目录
│   └── SYSTEM_GUIDE.md             # 本文档
│
├── cases/                          # 测试案例
│   └── CASE_NAME/
│       ├── *.bag / *.blf           # 原始数据
│       ├── report.md               # 诊断报告
│       ├── expert_opinions.md      # 专家意见
│       └── memory.json             # L5 案例记忆
│
├── msg_defs/                       # ROS 消息定义
│   └── canfd_sgu_pub.py
└── scripts/
    └── ollama_models_on_d_drive.ps1
```

## 10. 盲测验证记录

### FCATB001 — FCTB 触发中断

| 项目 | 内容 |
|------|------|
| 问题 | FCTA 已触发 warning，FCTB 未触发制动 |
| 真实根因 | AEBIB/AEBBA 信号在 adasFunc.c 中为 0 时抑制 FCTB |
| 系统诊断 | ✅ 正确识别 AEBBAActv_0x137 / AEBIBActv_0x137 信号为 0 → 触发制动释放 |
| 数据链路 | ✅ ESP_FD2.AEBBAActv_0x137(CAN) → g_DTCCode.bAEBBAActiveFlg(内部) → 制动释放 |
| 极性 | ✅ 正确理解 ==FALSE 为抑制触发条件 |
| 置信度 | 85/100 |

**历次盲测演进**：
1. 第1次 — 未识别 AEB 抑制逻辑（缺少条件提取和 CAN 关联分析）
2. 第2次 — 识别了逻辑但 CAN 信号名不匹配（缺少 signal_mapping）
3. 第3次 — 匹配到信号但极性搞反 + 车门信号误匹配（fuzzy cutoff 过低 + 极性未验证）
4. 第4次 — ✅ 三项修复后正确归因（映射优先 + 极性修复 + 变量链追踪）
