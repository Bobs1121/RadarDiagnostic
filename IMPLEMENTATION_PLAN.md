# radarAnalyze 实施计划

> 生成时间：2026-04-17  
> 最近更新：Temporal Pattern Engine (TPE) 上线  
> 目标：让工具能够根据代码 + 有限信息，自动分析问题数据并输出根因

---

## 0. 最新里程碑 — Temporal Pattern Engine (TPE) 已落地

### 0.1 解决的问题类别（不是单点）

FCATB001 盲测暴露了旧管线的共性缺陷：**无法诊断"时序耦合"问题**。
`adasFunc.c:6378-6383` 中 `if ((!bAEBBAActiveFlg) && (!bAEBIBActiveFlg))
{ bFctbKeepBrakeFlg = false; fFctbBrakeEventTime = 0; fFctbHoldEventTime = 0; }`
这种"短暂的信号跌落 → 累积器清零 → 功能退出激活"的模式，旧管线只看值分布
(`Counter(values)`) 和静态条件，永远无法识别。

TPE 是**第一性原理**的系统性回应：把 C 代码中的"行为模式"和数据中的"时序
特征"分别抽取，再做因果对齐。凡是符合下列 6 类代码模式 × 对应时序特征，
都能被自动定位：

| 代码模式 | C 代码形态 | 对应时序现象 |
|----------|-----------|------------|
| HoldRelease  | `if (cond) { flag = false; time = 0; }` | 短脉冲解除保持（FCATB001 根因） |
| HoldEntry    | `if (cond) { flag = true; ... }`         | 短脉冲进入保持 |
| Accumulate   | `time += dt` 配对 `time = 0`              | 累积器反复清零 |
| Hysteresis   | 不对称进入/退出阈值                         | 抖动边界 |
| Debounce     | `cnt++; if (cnt >= N)`                    | 脉冲计数被截断 |
| EdgeTrigger  | `prev == A && cur == B`                   | 边沿转换耦合 |

### 0.2 新模块

| 模块 | 作用 | 行数 |
|------|------|------|
| `ai/pattern_extractor.py` | 从 `D:\cr60_light` 扫出 6 类模式 | ~500 |
| `ai/temporal_analyzer.py` | 从 BAG/BLF 提取边沿/段/时长/短脉冲 | ~380 |
| `ai/causal_aligner.py`    | 把模式触发条件和信号 runs 做交集 | ~620 |
| `ai/tpe.py`               | facade，一把手封装三件套 | ~260 |
| `tests/test_temporal_pattern_engine.py` | 6 个 dry-run 测试（脱离 BAG/BLF） | ~430 |

### 0.3 已集成到主管线

- `ai/orchestrator.py`：新增 **Phase 3.55 — TPE 因果对齐**，在条件抽取后、
  抑制检查前执行；结果追加到 `evidence['KEY_FACTS']` 并以独立板块注入
  专家上下文。
- `ai/frame_analyzer.py`：新增 `append_tpe_block` 入口，`tpe_report` 作为结构化
  字段写入 evidence；不破坏旧 `KEY_FACTS` 契约。
- `ai/expert_panel.py`：
  * MODERATOR 原 4 层因果链扩展为 **5 层（新增 L2.5 时序耦合层）**
  * 每位专家 Round 1 prompt 中加入 **TPE 一致性检查**项
  * 收敛模板新增 **时序耦合(TPE触发清单)** 板块

### 0.4 验证结果

所有 6 个 dry-run 测试 PASS：

```
TEST 1 · TemporalAnalyzer 捕获短脉冲                   ✅
TEST 2 · PatternExtractor 在真实 adasFunc.c 中找到 HoldRelease ✅
TEST 3 · CausalAligner 在短脉冲数据上触发 HoldRelease 证据      ✅
TEST 4 · 对照组：AEBBA/AEBIB 恒为 1 时，HoldRelease 不触发       ✅
TEST 5 · Accumulate 触发器：累积器被反复清零                  ✅
TEST 6 · TemporalPatternEngine facade 端到端 (mock FrameStore)  ✅
```

Test 2 实测：在 `D:\cr60_light` 中命中 FCATB001 的根因位置
`adasFunc.c:6378-6383`，触发变量含 `AEBBA`，副作用变量含 `bFctbKeepBrakeFlg`，
**刚好就是你指出的那段**。

### 0.5 真实 BAG/BLF 数据验证（FCATB001 实测）

在 `cases/FCATB001/` 的真实 BAG + BLF 上运行 TPE smoke 工具，结果见
`cases/FCATB001/tpe_report.md`（UTF-8）：

```
## ★★ 代码模式 × 数据时序 因果对齐 (TPE) ★★
- 总模式数: 6 | 触发: 1 | 未触发: 0 | 无法判定: 5

#### ⚠️ 已触发模式（高优先级）

**HoldRelease** @ adasFunc.c:6378-6382 (UpdateFctbWarningStatus) · FCTB
  触发条件: (!g_DTCCode.bAEBBAActiveFlg) && (!g_DTCCode.bAEBIBActiveFlg)
  清零副作用: bFctbKeepBrakeFlg, fFctbBrakeEventTime, fFctbHoldEventTime
  ⚠ 模式 HoldRelease 在数据中触发 3 次 (首次 t=1775999201.56s,
                                        最长持续 123740ms)
  → 触发信号：AEBBAActv_0x137=0, AEBIBActv_0x137=0
  · 段1 21840ms   · 段2 123740ms   · 段3 12540ms

### 时序特征
AEBBAActv_0x137 (7938帧, 158.7s, 2次跳变, brief_pulses)
  值=1: 1段 120ms @ t=1775999223.556s（唯一一次"1"的短脉冲）
AEBIBActv_0x137 (7938帧, 158.7s, 4次跳变, brief_pulses)
  值=1: 2段 160ms + 339.6ms
```

**诊断意义**：
- FCATB001 的实际测试场景下 AEB 信号几乎**完全没激活**
  （AEBBA 7938 帧只有 6 帧=1，AEBIB 只有 25 帧=1），这意味着
  `!bAEBBAActiveFlg && !bAEBIBActiveFlg` **几乎一直成立**
- 代码 `adasFunc.c:6378-6382` 在每个 FCTB 运行周期都执行
  `bFctbKeepBrakeFlg = false; fFctbBrakeEventTime = 0;`，
  FCTB 的制动保持标志从未有机会"延时生效"
- 这就是 FCTB "刚触发就退出" 的直接原因。

### 0.6 如何复现上述验证

```bash
cd D:\RamboStar\idea\radarAnalyze
# 不走 LLM，只跑 TPE，大约 40s
python -m tools.run_tpe_smoke cases/FCATB001 --func FCTB -o cases/FCATB001/tpe_report.md

# 或者跑全链路，会触发 AI 专家面板（需要远程 API 可用）
python cli.py cases/FCATB001 \
    --problem "FCTB 激活时间很短，刚触发就退出" \
    --expected "FCTB 应保持激活至少 XX 秒"
# 新报告应在"根因"中出现 HoldRelease @ adasFunc.c:6378 的因果链。
```

### 0.7 TPE 可扩展方向

- **模式自动扩充**：目前 6 类是最常见的，用户后续可在 `pattern_extractor.py`
  的 `_scan_*` 系列加新模式；`causal_aligner._intersect_runs` 的交集逻辑
  对任何"多信号同时满足某条件"都适用，不需要改对齐器。
- **阈值比较的条件解析**：`causal_aligner._parse_condition_terms` 目前对
  `a >= b` 这种比较表达式只走"truthy"分支；后续可以拉数值 feature 做 AND。
- **跨 case 学习**：把每次 TPE 命中的模式写入 `memory/patterns.json`，
  下次同类型问题出现时直接优先检查这些模式。

---

## 一、当前状态评估

### 1.1 核心能力（已实现）

| 能力 | 状态 | 说明 |
|------|------|------|
| 数据解析 | ✅ | BAG + BLF 双源解析，时间同步 |
| 窗口检测 | ✅ | 自动定位测试激活时间段 |
| 条件提取 | ✅ | 从 C 代码提取触发条件 |
| **TPE 因果对齐** | ✅ | **代码模式 × 数据时序（2026-04-17 新增）** |
| 专家面板 | ✅ | 5 专家×3 轮辩论，已注入 TPE 指令 |
| 记忆系统 | ✅ | 5 层记忆（项目/功能/模式/会话/案例） |
| 报告生成 | ✅ | Markdown 格式诊断报告 |

### 1.2 待优化项

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P0 | config.yaml 明文 API Key | 安全风险 |
| P0 | 逐帧数据库插入 | 100 万消息需 5 分钟 |
| P1 | 诊断模板系统未实现 | 诊断质量不稳定 |
| P1 | 置信度评分未实现 | 无法量化结果可信度 |
| P2 | 可视化时间线未实现 | 时序关系不直观 |

---

## 二、实施路线图

### Phase 1: 安全与性能（1 天）

```
Day 1:
├─ [ ] config.yaml 环境变量化
├─ [ ] 流式 CSV 导出（parse_data.py）
└─ [ ] 批量数据库插入（case_loader.py + frame_store.py）
```

**验收标准：**
- API Key 从环境变量读取
- 100 万消息处理时间 < 1 分钟
- 内存峰值 < 100MB

---

### Phase 2: 诊断质量提升（2 天）

```
Day 2-3:
├─ [ ] 诊断模板系统（ai/diagnosis_templates.py）
│   ├─ 8 功能模板定义（BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB）
│   ├─ 每个功能 4+ 检查点
│   └─ 专家提示注入
├─ [ ] 置信度评分（ai/expert_panel.py）
│   ├─ 4 因子计算（专家一致性/数据完整性/代码证据/历史匹配）
│   └─ 报告头部展示
└─ [ ] 数据完整性检查清单
```

**验收标准：**
- 8 个功能模板完整定义
- 每次诊断输出置信度分数
- 报告包含检查表完成情况

---

### Phase 3: 可视化与体验（1 天）

```
Day 4:
├─ [ ] 可视化时间线（ai/timeline_viz.py）
│   ├─ HTML 交互式时间线图
│   ├─ 测试窗口/状态跳变/抑制信号轨道
│   └─ 悬停显示详情
├─ [ ] CLI 参数增强
│   ├─ --output 指定报告路径
│   ├─ --verbose/--quiet 日志级别
│   └─ --non-interactive CI 模式
└─ [ ] 统一报告格式
```

**验收标准：**
- 每个案例生成 timeline.html
- 浏览器可打开并交互
- CLI 支持非交互模式

---

### Phase 4: 代码质量（1 天）

```
Day 5:
├─ [ ] 异常系统重构
│   ├─ 定义专用异常类（RadarAnalysisError 等）
│   └─ 消除静默失败
├─ [ ] 类型注解完善
│   ├─ store 参数类型定义
│   └─ config 使用 TypedDict
├─ [ ] 重复代码提取
│   └─ utils.StatsCalculator
└─ [ ] orchestrator.py 拆分（可选）
```

**验收标准：**
- 所有异常有明确类型
- 关键函数有类型注解
- 统计计算统一封装

---

## 三、实施优先级

### 立即执行（今天）

1. **config.yaml 环境变量化** — 5 分钟
2. **诊断模板系统** — 4 小时（对诊断质量影响最大）

### 本周完成

3. **置信度评分** — 3 小时
4. **批量数据库插入** — 2 小时
5. **流式 CSV 导出** — 1 小时

### 下周完成

6. **可视化时间线** — 6 小时
7. **异常系统重构** — 2 小时
8. **CLI 参数增强** — 1 小时

---

## 四、使用流程

### 4.1 准备阶段

```bash
# 1. 设置环境变量
export REMOTE_API_KEY="sk-xxx..."
export REMOTE_BASE_URL="http://xxx:xxx/v1"

# 2. 安装依赖
cd D:/RamboStar/idea/radarAnalyze
pip install -r requirements.txt

# 3. 准备案例数据
# 将 bag + blf 文件放入 cases/新案例目录
```

### 4.2 诊断阶段

```bash
# 交互式模式
python cli.py

# 或直接指定案例
python cli.py cases/FCTA001 --problem "FCTA 未触发" --expected "检测到行人时应报警"

# 非交互模式（CI）
python cli.py cases/FCTA001 --problem "xxx" --expected "xxx" --non-interactive
```

### 4.3 结果查看

```
cases/FCTA001/
├── report.md           # 诊断报告
├── expert_opinions.md  # 专家详细意见
├── timeline.html       # 可视化时间线（Phase 3 后）
└── memory.json         # 案例记忆
```

---

## 五、技术债务

| 债务 | 风险 | 计划 |
|------|------|------|
| orchestrator.py 994 行 | 维护困难 | Phase 4 拆分 |
| 硬编码偏移（bag_parser.py） | 固件升级失效 | 动态解析 |
| 缺少单元测试 | 回归风险 | 后续补充 |
| DBC 版本未检查 | 解析错误 | 添加校验 |

---

## 六、成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 100 万消息处理时间 | 5 分钟 | <1 分钟 |
| 内存峰值 | 400MB | <100MB |
| 诊断置信度 | 无 | 0.0-1.0 |
| 功能模板覆盖 | 0% | 100%（8/8） |
| 可视化时间线 | 无 | 每个案例生成 |

---

## 七、下一步行动

**立即执行：**

1. 确认是否开始 Phase 1（安全与性能）
2. 确认远程 API 配置（是否需要切换模型）
3. 确认是否有新的案例数据需要分析

**需要决策：**

- 是否保留 Ollama 本地模型作为 fallback
- 可视化时间线是否需要支持缩放/拖动
- 是否需要生成 Excel 格式报告

---

*此计划基于当前代码库分析生成，可根据实际需求调整优先级。*
