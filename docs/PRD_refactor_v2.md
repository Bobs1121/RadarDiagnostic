# radarAnalyze — 角雷达 ADAS AI 诊断系统改造 PRD

> 版本: 2.1.1
> 日期: 2026-06-09
> 作者: AI Agent (PM + 架构师 + 开发者)
> 状态: Confirmed — 用户已确认方向
> 分支: `refactor/v2`

---

## 1. 文档基础信息

| 项 | 值 |
|---|---|
| 产品名称 | radarAnalyze — 角雷达 ADAS AI 诊断系统 |
| 版本 | 2.1.1 (多项目支持 + 基础加固 + 变体/软件包/材料设计补充) |
| 修订历史 | v2.0.0: 第一性原理重构规划 (2026-06-08) → v2.1.0: 多项目支持 + 基础优先策略 (2026-06-09) → v2.1.1: variant/package/material 设计补充 (2026-06-13) |
| 目标用户 | 内部 ASW 工程师 — ADAS 软件问题分析 |
| 术语表 | **BAG**: ROS1 录制数据; **BLF**: Vector CAN 日志; **MF4**: ASAM MCDF 测量数据; **TPE**: 时序模式引擎; **CodeGraph**: C 源码静态分析图谱; **FrameStore**: SQLite 内存数据库 |
| 干系人 | 产品经理=用户; 架构师+开发者=Agent; 终端用户=Bosch ADAS ASW 工程师 |

---

## 2. 项目背景与目标

### 2.1 第一性原理：用户需要什么？

**使用场景**: ASW 工程师收到"某个 ADAS 功能在特定场景下不工作"的 bug 报告，需要回答：

> **为什么这个功能没有按预期工作？根因是什么？怎么改？**

回答这个问题的**最小必要动作**是：

1. **看懂数据** — BLF/BAG 里实际发生了什么（信号值、目标状态、自车状态）
2. **理解代码** — 代码期望什么条件才能激活/退出功能
3. **找到差距** — 实际数据和代码期望之间的差异 = 根因
4. **给出方案** — 怎么改代码或参数

### 2.2 产品定位

| 维度 | 定义 |
|------|------|
| **目标用户** | 内部 ADAS ASW 工程师 |
| **使用场景** | 离线分析问题案例，定位根因 |
| **支持平台** | 多代角雷达项目（5 代 CR5CB、6 代 SC6H-cr60light 等） |
| **交付形态** | CLI 工具 — 输入案例目录 + 问题描述，输出诊断报告 |
| **不在范围** | Web UI、实时在线诊断、自动提交/PR、视频辅助诊断 |

### 2.3 支持的多项目

| 项目代号 | 平台 | 工作目录 | 说明 |
|---------|------|---------|------|
| `cr5cb` | BYD_OVS_CB — 5 代角雷达 | `C:\BYD_OVS_CB` | CR5CB 平台，17 子模块，CodeGraph 24,186 文件 |
| `sc6h` | BYD-SC6H-cr60light — 6 代角雷达 | `D:\BYD-SC6H-cr60light\cr60_light` | CR60Light 平台，CodeGraph 1,381 节点 |
| *(可扩展)* | 未来新增平台 | 配置添加 | 无需修改代码，仅配置驱动 |

### 2.3.1 多项目身份模型（设计补充）

多项目不能再由单一 `project_key` 表达；真实工程对象至少包含：

| 层级 | 作用 | 示例 |
|------|------|------|
| `platform_family` | 技术族/平台插件 | `gen6_c_radar`, `gen5_cpp_radar` |
| `codebase` | 实际代码工作区 | `D:\GWM-CR60LIGHT\cr60_light`, `C:\BYD_OVS_CB` |
| `variant` | 客户项目级变体（知识隔离主键） | `coem/GWM_B26`, `coem/BYD_SC6H`, `apl/byd` |
| `package_profile` | 构建参数组合，决定软件包形态 | `GWM_B26 + KL15 + SYMMETRY + T66MS` |
| `snapshot` | 一次可复现分析快照 | `代码/DBC/材料/config/model` 的 hash 组合 |

设计原则：
- 客户项目隔离按 `variant` 定义，不按 repo 或单文件路径定义
- 软件包差异按 `package_profile` 定义，不滥拆 `variant`
- DBC/需求材料变化默认进入新的 `snapshot`

构建脚本依据：
- Gen6: `coem/<variant>/buildscripts/build.bat` 通过 `coemDir + build.cfg + patch + scons_gen.bat 参数` 决定软件包
- Gen5: `apl/<customer>/tools/build.bat` 通过客户子目录 + `cmake_gen.bat` 参数决定软件包

### 2.4 当前系统的核心矛盾

| 矛盾 | 说明 | 改造优先级 |
|------|------|-----------|
| **项目配置硬编码** | `config.yaml` 写死 `GWM_B26` 路径，换项目要改配置 | **P0** |
| **变量 false positives** | CodeGraph 797 变量中大量局部变量 (i, j, tmp) | **P1** |
| **数据-变量映射不完整** | BLF CAN signal → 内部变量链路不完整 | **P1** |
| **CodeGraph 语义层为空** | `semantic_annotations` 表空，只有结构无语义 | **P1** |
| LLM 链路过长 | 8-12 次串行调用 | P2 |
| 管线步骤过多 | 15+ 步 | P2 |
| **记忆层级消费不均衡** | L4/L5 写入多消费少 | P2 |
| ContextBudget 固定预算 | 60K 硬上限 | P3 |
| MF4 解析缺失 | asammdf 内网不可用 | **Deferred** |

### 2.5 产品愿景

```
输入: 项目配置 + 问题描述 + 案例数据 (BAG/BLF)
  ↓
自动诊断 (确定性数据解析 + CodeGraph 代码分析 + LLM 专家推理)
  ↓
输出:
  1. 根因诊断 (LangGraph 专家面板 → 结构化结论)
  2. 代码修改方案 (CodeFixEngine → unified diff + 效果预估)
  3. 可视化报告 (交互式 HTML 时间线)
```

### 2.6 成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 诊断准确率 | ~70% (估算) | >85% |
| 端到端耗时 | 5-10 min | <5 min |
| LLM 调用次数 | 8-12 次 | 5-7 次 |
| 数据解析覆盖率 | BAG+BLF (2/3) | BAG+BLF (MF4 待改造) |
| 代码修改能力 | 结构化 diff + 效果模拟 | 已实现 |
| **多项目支持** | **仅 GWM_B26** | **配置化支持 N 个项目** |
| **变量映射准确率** | **不完整** | **CAN signal → C 变量全链路** |

---

## 3. 用户画像与场景

### 3.1 目标用户

| 角色 | 描述 | 核心诉求 |
|------|------|---------|
| **ADAS ASW 工程师** | 负责角雷达应用层软件，日常分析功能 bug | 快速定位根因，减少看 BLF 波形和 C 代码的时间 |
| **产品经理** | 评估功能表现，推动问题闭环 | 结构化报告，可转给其他 AI/团队继续处理 |

### 3.2 典型使用场景

**场景 1: 新 bug 诊断**
```
用户: "FCTA 在低速场景没有触发预警"
操作: python cli.py cases/FCTA_NEW -P sc6h -p "低速 FCTA 无预警" -e "应该触发 FCTA 预警"
期望: 5 分钟内得到根因分析报告 + 代码修改建议
```

**场景 2: 数据快查**
```
用户: "FCTB 触发时 AEBIB 信号是什么值"
操作: python cli.py cases/FCTA001 -P cr5cb -q "FCTB 触发时 AEBIB 信号值"
期望: 30 秒内返回信号时间线和统计
```

**场景 3: 跨项目对比**
```
用户: 同样的问题在 5 代和 6 代平台表现不同
操作: 分别指定 -P cr5cb 和 -P sc6h 运行诊断
期望: 两个平台的诊断报告可对比，快速发现平台差异
```

**场景 4: 批量复盘**
```
用户: 一周积累了 5 个 FCTA 漏报案例
操作: 逐个运行诊断 → 自动写入记忆 → AutoDream 整合
期望: 形成跨案例的模式库，越用越准
```

---

## 4. 功能需求详述

### 4.1 改造核心原则

**原则 1: 基础优先，渐进优化**
- 先解决影响诊断准确率的基础问题（变量过滤、数据-变量映射、语义层）
- 基础打牢后再做管线精简、ContextBudget 优化等效率提升
- 每个 Phase 可独立验证，不阻塞后续工作

**原则 2: 确定性层和 LLM 层分离**
- 数据解析、时间同步、信号映射、CodeGraph 构建 → 纯确定性代码
- 问题理解、条件提取、专家面板 → LLM 推理
- 确定性层出错率应接近 0%，LLM 层负责模糊推理

**原则 3: 配置驱动，代码不变**
- 项目切换通过配置完成，不修改代码
- CodeGraph DB、source_docs、记忆按项目隔离
- 新增项目只需在 `config.yaml` 添加 `projects` 配置

**原则 4: LLM 调用最小化**
- 当前 8-12 次串行 LLM 调用 → 目标 5-7 次
- 合并可合并的步骤
- 能用确定性代码解决的不用 LLM

**原则 5: 可观测性**
- 每个管线步骤记录输入/输出摘要、耗时、状态
- LLM 调用记录 prompt 大小、token 消耗、响应时间
- 失败必须有明确的降级策略

### 4.2 模块级改造需求

#### FR-001: 多项目可配置化 (P0 — 基础)

**目标**: 支持多个角雷达项目，通过配置切换，无需修改代码。

**设计升级**:
- 用户入口短期仍可保留 `-P <project_key>`，但内部主身份应升级为 `variant_id`
- `variant_id` 表示客户项目级边界
- `package_profile_id` 表示构建包配置
- `snapshot_id` 表示一次可审计分析快照
- `project_key` 仅作为过渡兼容字段，不再承担全部身份语义

**设计方案**:

```yaml
# config.yaml — 设计演进方向
platforms:
  gen6_c_radar:
    language: c
    build_system: scons
  gen5_cpp_radar:
    language: cpp
    build_system: cmake

codebases:
  gwm_cr60light:
    root: "D:\\GWM-CR60LIGHT\\cr60_light"
    platform: gen6_c_radar
  byd_ovs_cb:
    root: "C:\\BYD_OVS_CB"
    platform: gen5_cpp_radar

variants:
  gen6/gwm_b26:
    codebase: gwm_cr60light
    scope:
      include:
        - "coem/GWM_B26/**"
    build_entry: "coem/GWM_B26/buildscripts/build.bat"
    dbc_sets:
      default:
        files: ["CR_DBC_V3.2_20260331.dbc"]
    file_hints:
      key_source_files: [...]
    overlays:
      source_domains: [...]

package_profiles:
  gen6/gwm_b26/default:
    variant: gen6/gwm_b26
    build_flags:
      vehicleType: GWM_B26
      powerSupply: KL15
      antenna: SYMMETRY
      cyctime: T66MS
      swBuildType: DEVELOP
      funTestType: "OFF"

# 全局配置（所有项目共享）
default_variant: "gen6/gwm_b26"
ai: ...                         # 模型配置（全局共享）
functions: ...                  # ADAS 功能定义（全局共享）
auto_dream: ...                 # AutoDream 配置（全局共享）
```

**CLI 参数**:
- 短期：`-P <project_key>` 或 `--project <project_key>`
- 中期：`--variant <variant_id>` + `--package <package_profile_id>`
- 长期：所有诊断、评估、知识沉淀统一绑定 `snapshot_id`

**项目隔离策略**:

| 资源 | 隔离方式 | 示例 |
|------|---------|------|
| CodeGraph DB | `variant` 级隔离 | `memory/codegraph/gen6_gwm_b26.db` |
| source_docs | `variant` 级隔离 | `source_docs/gen6_gwm_b26/` |
| 记忆系统 | `variant` 级隔离 | `memory/variants/gen6_gwm_b26/` |
| 构建包配置 | `package_profile` 级隔离 | `build_profiles/gen6_gwm_b26/default.yaml` |
| 审计快照 | `snapshot` 级追踪 | 代码/DBC/材料/config/model hash 组合 |
| 案例数据 | 不隔离 | `cases/` 共享，案例内标记来源项目 |
| 模型配置 | 共享 | 所有项目使用同一组 LLM 端点 |

**数据-变量映射设计**:

CodeGraph SIGNAL 节点存储完整链路：

```
CAN Signal Name (BLF/DBC)
  → DBC Message (CAN ID + Signal)
    → RteComMapping_ReadSignal/WriteSignal (C 代码中的宏调用)
      → Internal Variable (C 代码中的全局变量/静态变量)
        → CodeGraph VARIABLE 节点
```

SIGNAL 节点扩展字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `can_signal_name` | string | BLF/DBC 中的信号名 |
| `dbc_message` | string | DBC Message 名 |
| `can_id` | int | CAN ID |
| `rte_mapping_file` | string | RteComMapping.c 文件路径 |
| `rte_mapping_line` | int | 宏调用行号 |
| `internal_var_name` | string | 映射到的 C 内部变量名 |
| `direction` | enum | READ (外部→内部) / WRITE (内部→外部) |
| `platform` | string | 项目代号 (sc6h/cr5cb) |

**验收标准**:
- `python cli.py cases/FCTA001 -P sc6h` 和 `python cli.py cases/FCTA001 -P cr5cb` 分别使用各自配置
- CodeGraph DB 按项目隔离，数据不混
- 新增项目只需在 `config.yaml` 添加配置，无需改代码

#### FR-002: 变量过滤 — 只保留有意义的变量 (P1 — 基础)

**目标**: CodeGraph 变量节点只保留对诊断有意义的变量。

**当前问题**: 797 个变量中大量是 `i`, `j`, `tmp`, `idx` 等局部循环变量，污染查询结果。

**过滤规则**:

| 保留 | 过滤 |
|------|------|
| 全局变量 (`file_scope` + non-static) | 局部循环变量 (`for(int i=0;`) |
| 静态全局变量 (`static` at file scope) | 局部临时变量 (`tmp`, `idx`, `cnt` 等短名) |
| RTE 读写变量 (`Rte_*` 前缀) | 结构体成员变量 (除非是关键状态) |
| 状态机变量 (`State_e`, `Mode_e` 等枚举) | 函数参数 |
| 校准参数 (`Calib_` 前缀) | 标准库函数内部变量 |

**实现**: 在 CodeGraph 构建阶段增加变量过滤逻辑（规则可配置，允许不同项目按需覆盖）。

**验收标准**（从“数量目标”改为“质量目标”）:
- 噪声变量（C 关键字/短循环变量/常见临时变量名）在 CodeGraph 中为 0
- 抽样检查 100 个保留变量，≥95% 可用于诊断（状态/阈值/输出/门控/关键中间量）
- 关键变量召回率 ≥95%（以关键文件白名单 + SIGNAL/输出链路相关变量为基准）

#### FR-003: CodeGraph 语义层填充 (P1 — 基础)

**目标**: 让 CodeGraph 不仅存储"代码结构"，还存储"代码意图"。

**当前问题**: `semantic_annotations` 表为空，CodeGraph 只有语法级信息。

**设计方案 — 代码理解 Pipeline**:

```
tree-sitter AST (结构层)
  → ASTBuilder (节点/边)
    → CodeGraph SQLite (结构图谱)
      → LLM 语义标注 (意图层)
        → semantic_annotations 表 (语义图谱)
```

**语义标注内容**:

| 标注对象 | 标注内容 | 示例 |
|---------|---------|------|
| FUNCTION | 功能描述 + 输入输出 | "计算 TTC (Time To Collision)，输入=相对距离+相对速度，输出=TTC 秒数" |
| VARIABLE | 语义角色 | "FCTA 激活状态标志，1=Active, 0=Inactive" |
| SIGNAL | 物理含义 | "车速信号，单位 km/h，0-200 范围" |
| STATE_MACHINE | 状态机语义 | "FCTA 功能状态机：None→Init→Standby→Active→Off" |
| PATTERN | 行为模式语义 | "TTC 阈值滞回：激活阈值 2.0s，退出阈值 2.5s" |

**标注流程**:
1. CodeGraph 构建完成后触发
2. 按模块分批（每次 1 个源文件）
3. LLM 读取 AST 结构 + 源码片段，输出语义标注 JSON
4. 写入 `semantic_annotations` 表
5. 缓存 + hash 校验，源码不变时跳过

**标注时机**: AutoDream 阶段或首次 CodeGraph 构建后。

**验收标准**: 核心文件（adasFunc.c, ASWIN_SystemState.c, RteComMapping.c）的函数/变量/信号均有语义标注。

#### FR-004: 管线精简 — 15→8 步 (P2 — 优化)

**目标**: 减少管线步骤，降低出错面和调试复杂度。

**合并方案**:

| 合并前 | 合并后 | 理由 |
|--------|--------|------|
| understand + classify | `classify` (1 次 LLM) | 同一 LLM 调用同时完成 |
| parse + detect_window | `extract` (确定性) | 都是数据解析，无 LLM |
| conditions + tpe + probe | `evidence` (并行) | conditions(LLM) 和 tpe(确定性) 可并行 |
| suppression + output_signals | `signals` (确定性) | 都是 CAN 信号查询 |
| diagnose | `diagnose` (LangGraph) | 不变 |
| fix | `fix` (CodeFixEngine) | 不变 |
| visualize + memory + done | `deliver` (确定性) | 都是收尾工作 |

**目标管线 (8 步)**:

```
1. init       → 项目配置加载 + source_docs + CodeGraph 构建 (确定性)
2. classify   → 问题理解 + 任务分类 (1 LLM)
3. extract    → 数据解析 + 窗口检测 (确定性)
4. evidence   → 条件提取(LLM) + TPE(确定性) + 变量探测(LLM) — 并行
5. signals    → 抑制信号 + 输出信号 (确定性)
6. diagnose   → LangGraph 专家面板 (多 LLM)
7. fix        → CodeFixEngine 生成 diff (1 LLM)
8. deliver    → 报告 + 可视化 + 记忆更新 (确定性)
```

**注意**: evidence 步骤内部保留并行结构，conditions 和 TPE 并行执行，probe 依赖两者完成后执行。

#### FR-005: ContextBudget 智能优化 (P3 — 优化)

**目标**: 从固定 60K 字符变为动态 token 预算。

**当前实现评估**: 已有 priority 排序 + min_chars 保底 + greedy 分配 + format_report。不是纯被动截断。

**真正需要加的能力**:

1. **动态总预算**: 根据 CodeGraph 大小 + 案例复杂度调整
2. **截断反馈**: 记录截断内容，专家面板可见

```python
def dynamic_budget(codegraph_size: int, case_complexity: str) -> int:
    base = 50_000
    cg_bonus = min(codegraph_size // 100, 20_000)
    complexity_mult = {"simple": 0.8, "normal": 1.0, "complex": 1.3}[case_complexity]
    return int((base + cg_bonus) * complexity_mult)
```

#### FR-006: 记忆系统简化 — 6→3 层 (P2 — 优化)

**目标**: 减少记忆层级，保持 API 兼容。

**简化方案**:

| 当前层级 | 改造后 | 理由 |
|---------|--------|------|
| L1: project.md | 保留 → `memory/project.md` | 项目级知识，AutoDream 写入 |
| L2: functions/*.json | 保留 → `memory/knowledge/{FUNC}.json` | 功能级知识，诊断时读取 |
| L3: patterns.json | 保留 → `memory/knowledge/patterns.json` | 模式库，跨案例学习 |
| L4: sessions/*.json | 精简 → 只保留最近 20 条 | 90% 不会被消费 |
| L5: cases/*/memory.json | 合并到 L3 patterns | 案例记忆 = 特化模式 |
| L6: code_knowledge/*.json | 保留 → `memory/knowledge/code/` | 代码知识是诊断核心 |

**简化后目录**:

```
memory/
  project.md                    # 项目级总览
  knowledge/
    patterns.json               # 跨功能模式库
    code/                       # 代码结构化知识
    {FUNC}.json                 # 功能级知识
  sessions/                     # 最近 20 条会话
  codegraph_{project}.db        # CodeGraph (按项目隔离)
```

#### FR-007: 降级策略 (已在 Phase 1 实现，补充完善)

| 步骤 | 降级策略 |
|------|---------|
| classify | 默认 `diagnose` + 全 5 专家 |
| evidence (conditions) | 使用缓存的 `{FUNC}_conditions.json` |
| evidence (probe) | 跳过，`probe_results = {}` |
| diagnose (专家面板) | 单专家直接输出 |
| fix (CodeFixEngine) | 返回文字修复建议 |
| **CodeGraph 构建** | **跳过，使用上一次缓存** |

#### FR-008: MF4 Parser (Deferred — 待改造)

**状态**: `parsers/mf4_parser.py` 已有框架 + stub，但因 `asammdf` 在内网环境不可安装，推迟为待改造项。

**后续方案**:
- 方案 A: 在内网部署 asammdf 或 mffparser 依赖
- 方案 B: 使用 mf4-converter CLI 工具转 BLF 后处理
- 方案 C: 等待网络环境支持后补全

#### FR-009: Harness 评估体系 — 诊断质量可量化 (P0 — 基础)

**目标**: 建立可复现、可扩展的评估体系，回答“诊断准不准、好不好用、迭代有没有变好”。

**评估层级**:
- **L0 结构完整性**：报告结构/字段是否齐全（确定性规则）
- **L1 证据链覆盖度**：关键信号/条件/窗口/链路是否被引用与解释（确定性规则）
- **L2 结论一致性**：根因分类/定位/因果描述/修复建议是否与黄金答案一致（确定性 baseline）

**设计原则**:
- 默认不引入重量依赖（例如 sklearn），先用确定性 baseline 跑通“可复现下限”
- 在 baseline 之上增加可选增强：**LLM-as-judge**（仅提升 L2 语义一致性，不替代确定性评分）

**验收标准**:
- 至少 3 个案例具备 ground truth（覆盖 rear/front 各至少 1 个功能）
- Harness 可批量跑全量案例并输出聚合报告（平均分、最差分、回归对比）
- L0/L1 在无 LLM 环境下可运行；L2 baseline 在无 LLM 环境下可运行；LLM judge 缺失时自动跳过

#### FR-010: 客户需求材料接入与结构化转化 (P0 — 基础)

**目标**: 将客户需求材料纳入正式诊断约束源，而不是作为散乱 prompt 上下文。

**输入材料范围**:
- 规范类：客户需求文档、功能说明、状态机说明、接口协议
- 标定/配置类：DBC、参数表、阈值表、功能开关
- 验证类：测试用例、issue 单、验收标准

**设计原则**:
- 权威材料 (`AuthoritativeMaterial`) 优先于经验知识 (`LearnedKnowledge`)
- 材料先解析，再转结构化对象；诊断链路消费结构化对象，不直接消费原文
- 材料接入按 `variant` 绑定，材料版本变化进入新的 `snapshot`

**结构化对象**:
- `RequirementSpec`
- `SignalConstraint`
- `StateMachineConstraint`
- `ThresholdRule`
- `AcceptanceCriterion`
- `ProjectGlossary`

**验收标准**:
- 至少支持 `pdf/md/xlsx/dbc/json/yaml` 六类材料导入
- 每份材料生成 `material_id/hash/version`
- 结构化结果可关联到 `variant`、信号、文件、函数、状态机

#### FR-011: 可审计诊断产物与修复知识沉淀 (P0 — 基础)

**目标**: 将输出从单纯报告升级为可审计的结构化诊断包，并优先沉淀“根因模式 + 修复逻辑”。

**核心对象**:
- `DiagnosisBundle`
- `RootCausePattern`
- `FixPlaybook`

**门禁规则**:
- 无完整证据链，不输出 `confirmed_root_cause`
- 无可靠代码定位，不输出可执行 `diff`

**验收标准**:
- 每次诊断绑定 `snapshot_id`
- 每条根因模式与修复逻辑都携带来源 case、来源快照、证据引用
- 报告、diff、Harness 评估都能回链到同一 `DiagnosisBundle`

---

## 5. 数据模型

### 5.1 核心实体关系

```
PlatformFamily (平台插件)
  ├── language (C / C++)
  ├── build_system (SCons / CMake)
  ├── codegraph_plugin
  └── parser_plugin

Codebase (代码工作区)
  ├── root_path
  ├── repo_url / branch / commit (可选)
  └── platform_family

Variant (客户项目级变体)
  ├── code_scope (include/exclude globs)
  ├── build_entry
  ├── dbc_sets
  ├── file_hints
  └── requirement_overlays

PackageProfile (软件包配置)
  ├── build_flags
  ├── patch_set
  └── artifact_rules

Snapshot (可复现分析快照)
  ├── code_snapshot
  ├── dbc_snapshot
  ├── material_snapshot
  ├── config_version
  └── model_profile

Material (材料注册)
  ├── source_path
  ├── material_type
  ├── hash / version
  └── authoritative

StructuredRequirementSet (结构化需求)
  ├── RequirementSpec
  ├── SignalConstraint
  ├── StateMachineConstraint
  ├── ThresholdRule
  └── AcceptanceCriterion

Case (案例)
  ├── BAG/BLF Files (数据源)
  ├── FrameStore (SQLite — 临时)
  │     ├── bag_frames
  │     ├── can_frames
  │     ├── radar_objects
  │     ├── radar_debug
  │     └── warning_events
  ├── DiagnosisBundle (诊断包)
  │     ├── evidence_chain
  │     ├── reasoning_graph
  │     ├── root_cause_assessment
  │     ├── code_localization
  │     ├── change_proposal
  │     └── requirement_trace
  └── Reports (报告产物)
        ├── report.md
        ├── report.html
        ├── expert_opinions.md
        └── fix.patch

CodeGraph (代码图谱 — SQLite, 按项目隔离)
  ├── functions (函数节点)
  ├── variables (变量节点 — 过滤后)
  ├── signals (信号节点 — 含完整链路)
  ├── files (文件节点)
  ├── edges (关系边: CALLS, READS, WRITES, READS_SIGNAL, WRITES_SIGNAL)
  ├── patterns (行为模式)
  └── semantic_annotations (语义标注 — 待填充)

Memory (记忆系统 — 按项目隔离)
  ├── project.md (项目级)
  ├── knowledge/ (功能级 + 代码级 + 模式库)
  └── sessions/ (会话日志 — 最近 20 条)

LearnedKnowledge
  ├── RootCausePattern
  └── FixPlaybook
```

### 5.2 SIGNAL 节点数据模型（扩展）

```sql
CREATE TABLE signals (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,           -- 信号名
  can_signal_name TEXT,         -- CAN/BLF 中的信号名
  dbc_message TEXT,             -- DBC Message
  can_id INTEGER,               -- CAN ID
  rte_mapping_file TEXT,        -- RteComMapping.c 路径
  rte_mapping_line INTEGER,     -- 宏调用行号
  internal_var_name TEXT,       -- 映射的内部变量名
  direction TEXT CHECK(direction IN ('READ', 'WRITE')),
  platform TEXT,                -- 项目代号
  file_path TEXT,               -- 所在文件
  line INTEGER,
  semantic_description TEXT     -- LLM 语义标注
);
```

---

## 6. 非功能需求

### 6.1 性能

| 指标 | 当前 | 目标 |
|------|------|------|
| 单次诊断总耗时 | 5-10 min | <5 min |
| LLM 调用总次数 | 8-12 | 5-7 |
| 数据解析耗时 | 10-30s | <15s |
| CodeGraph 构建 | 首次 6s, 增量 <1s | 首次 <5s |
| HTML 报告生成 | <5s | <5s |
| **项目切换耗时** | **需改配置 + 重建** | **CLI 参数切换，增量构建** |

### 6.2 可靠性

- 确定性步骤（数据解析、CodeGraph）不依赖 LLM，成功率 >99%
- LLM 步骤有降级策略，最坏情况仍能产出基础报告
- 所有中间结果缓存，支持断点续跑
- **项目隔离：一个项目的 CodeGraph 损坏不影响其他项目**

### 6.3 可维护性

- 配置驱动：新增项目只需改 `config.yaml`
- 管线步骤从 15+ 减到 8，代码量减少 30%+
- 专家面板 LangGraph，prompt 外部化
- 代码解析 tree-sitter AST，维护成本降低

---

## 7. 假设、约束与依赖

### 7.1 技术约束

- 模型: Qwen3.5-27B-FP16 (远端) + qwen3-coder:30b (编码)
- 单 GPU (RTX A2000 12GB)，KV cache 有限
- 内网环境，部分外部库可能无法直接安装
- **Python 3.12.10**

### 7.2 外部依赖

| 依赖 | 用途 | 状态 |
|------|------|------|
| tree-sitter + tree-sitter-c | C 代码 AST 解析 | ✅ 已安装 |
| langgraph | 专家面板编排 | ✅ 需要（专家面板路径）；建议作为可选依赖/单独安装说明，缺失时需有降级路径 |
| cantools | DBC 解码 | ✅ 已安装 |
| rosbags | BAG 解析 | ✅ 已安装 |
| asammdf / mffparser | MF4 解析 | ❌ Deferred |

### 7.3 风险与应对

| 风险 | 可能性 | 影响 | 应对措施 |
|------|--------|------|---------|
| 多项目 CodeGraph 膨胀 | 中 | 中 | 按项目隔离 DB，定期清理 |
| 变量过滤过度/不足 | 中 | 高 | 渐进式过滤，先保留静态变量 |
| 语义标注 LLM 质量不稳定 | 中 | 中 | 人工审核关键标注，cache + hash 校验 |
| asammdf 始终无法安装 | 高 | 低 | MF4 作为待改造项，不影响主线 |

---

## 8. 里程碑与实施路线

### Phase 5A: 多项目可配置化 (P0 — 3 天)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 5A.1 | config.yaml 重构为 projects 配置 | 1 天 | `-P sc6h` / `-P cr5cb` 可切换 |
| 5A.2 | CodeGraph DB 按项目隔离 | 0.5 天 | `codegraph_{project}.db` 独立 |
| 5A.3 | source_docs 按项目隔离 | 0.5 天 | `source_docs/{project}/` 独立 |
| 5A.4 | 记忆系统按项目隔离 | 0.5 天 | `memory/projects/{project}/` 独立 |
| 5A.5 | SIGNAL 节点扩展（数据-变量映射字段） | 0.5 天 | SIGNAL 节点含完整链路信息 |
| 5A.6 | E2E 验证：两个项目各跑一次 FCTA001 | 0.5 天 | 两个平台产出不同结果 |

### Phase 5B: 变量过滤 (P1 — 2 天)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 5B.1 | 增加变量过滤规则（构建阶段） | 1 天 | 噪声变量为 0 + 抽样质量 ≥95% |
| 5B.2 | 过滤规则可配置（白名单/黑名单） | 0.5 天 | config.yaml 可覆盖默认规则 |
| 5B.3 | CodeGraph 重建 + 验证 | 0.5 天 | 验证保留变量均为诊断相关 |

### Phase 5C: CodeGraph 语义层 (P1 — 3 天)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 5C.1 | 设计 semantic_annotations 表结构 | 0.5 天 | SQL schema 确定 |
| 5C.2 | 实现 LLM 语义标注 pipeline | 1.5 天 | 函数/变量/信号/状态机/模式均可标注 |
| 5C.3 | 缓存 + hash 校验机制 | 0.5 天 | 源码不变时不重复标注 |
| 5C.4 | 专家面板注入语义标注 | 0.5 天 | ContextBudget 包含语义描述 |
| 5C.5 | 核心文件首次标注 + 质量检查 | 0.5 天 | adasFunc.c 等核心文件标注完整 |

### Phase 5D: 管线精简 (P2 — 2 天)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 5D.1 | orchestrator.py 重构为 8 步 | 1 天 | 等价输出，步骤数 8 |
| 5D.2 | evidence 步骤并行化 | 0.5 天 | conditions + TPE 并行 |
| 5D.3 | 回归测试 | 0.5 天 | FCTA001 诊断结果一致 |

### Phase 5E: 优化项 (P2-3 — 2 天)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 5E.1 | ContextBudget 动态总预算 | 0.5 天 | 根据 CodeGraph 大小调整 |
| 5E.2 | 记忆系统简化 6→3 层 | 1 天 | API 向后兼容 |
| 5E.3 | 端到端回归测试 | 0.5 天 | 两个项目 × FCTA001 均通过 |

### Phase 6: 评估与闭环 (P0-P2 — 按优先级推进)

| # | 任务 | 工时 | 验收标准 |
|---|------|------|---------|
| 6A | SIGNAL internal_var 映射补全 | 1 天 | 301/301 SIGNAL 具备 internal_var，BLF 信号可关联到 C 变量 |
| 6B | Harness Phase 1（L0） | 1-2 天 | StructuralEvaluator + 首个 ground truth + pytest 可跑 |
| 6C | 知识沉淀闭环 | 1-2 天 | 每次诊断可增量沉淀到 L6 code_knowledge |
| 6D | source_docs + L6 按项目隔离 | 1 天 | 多项目不互相污染，含 legacy fallback |
| 6E | 专家面板 prompt 多项目适配 | 1 天 | prompt 中不写死文件路径，来自配置/CodeGraph 动态生成 |
| H2 | Harness Phase 2（L1/L2） | 1 天 | L1/L2 baseline 可运行，输出 overall + 明细 |
| H3 | Harness Phase 3（样本扩充 + L2 增强） | 2-3 天 | 3-5 个案例基线 + 可选 LLM judge + 聚合报告 |

### Deferred: 待改造项

| 项 | 说明 | 触发条件 |
|---|------|---------|
| MF4 Parser | asammdf 依赖不可用 | 内网安装 asammdf 或 mffparser |
| 多平台 CodeGraph 合并查询 | 跨平台对比分析 | 用户明确提出需求 |
| Web UI | 前端可视化 | 产品方向调整 |

### 总工期

| Phase | 工时 | 优先级 |
|-------|------|--------|
| 5A: 多项目可配置化 | 3 天 | **P0** |
| 5B: 变量过滤 | 2 天 | P1 |
| 5C: 语义层 | 3 天 | P1 |
| 5D: 管线精简 | 2 天 | P2 |
| 5E: 优化项 | 2 天 | P2-3 |
| **合计** | **12 天** | — |

---

## 9. 附录

### A. 现有文档索引

| 文档 | 路径 |
|------|------|
| Master Handoff | `docs/technical/codegraph-handoff-master.md` |
| 实施规划 | `docs/IMPLEMENTATION_PLAN_v2.md` |
| ai/ 模块说明 | `ai/AGENTS.md` |
| memory/ 模块说明 | `memory/AGENTS.md` |
| parsers/ 模块说明 | `parsers/AGENTS.md` |

### B. 用户确认项（2026-06-09）

| 确认项 | 用户决定 |
|--------|---------|
| 多项目支持 | 必须，5 代 CR5CB + 6 代 SC6H，配置化 |
| 数据-变量映射 | 必须，关注 BLF signal → C 变量全链路 |
| 代码理解 | AST 结构 + LLM 语义标注两阶段 |
| 改造顺序 | 基础优先：配置化 → 变量过滤 → 语义层 → 管线精简 |
| MF4 | 待改造项，暂不阻塞主线 |
| PRD/文档 | 根据确认信息立即更新 |
| 产品定位 | 内部 ASW 工程师工具 |
| 配置要求 | 精简，不增加复杂度 |

### C. 配置精简设计原则

1. **一个 config.yaml 管所有项目** — 不创建项目级子配置文件
2. **全局共享的配置放顶层** — 模型端点、ADAS 功能定义、AutoDream 策略
3. **项目特有的配置放 projects.* 下** — source_code, dbc_files, key_source_files, source_domains
4. **CLI 一个参数切换** — `-P sc6h` 或 `-P cr5cb`
5. **默认项目** — `default_project` 配置，省略 `-P` 时使用默认
