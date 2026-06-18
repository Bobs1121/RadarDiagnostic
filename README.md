# Corner Radar Analysis Tool

**雷达 ADAS 功能自动化根因诊断系统** — 对 BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB 等功能的录制数据进行自动化分析，输出结构化的诊断报告。

## 快速开始

### 1. 安装

```bash
# 克隆仓库
git clone <repo-url> radarAnalyze
cd radarAnalyze

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制 .env.example）
cp .env.example .env
```

编辑 `.env` 填入 LLM API 配置：
```
REMOTE_BASE_URL=http://your-llm-server/v1
REMOTE_API_KEY=your-api-key
```

### 2. 配置项目

编辑 `config.yaml` 中的 `default_project` 或首次运行时使用 `--variant` 指定：

```bash
python cli.py --variant gen6/gwm_b26 cases/FCTB001 -p "FCTB 未触发" -e "FCTB 应该在目标出现后 2 秒内触发"
```

### 3. 运行诊断

#### 诊断模式（完整分析）

```bash
python cli.py <案例目录> -p "问题描述" -e "预期行为"
```

**参数说明**：

| 参数 | 说明 | 示例 |
|------|------|------|
| `<案例目录>` | 包含 .bag/.blf 录制数据的目录 | `cases/FCTB001/` |
| `-p` / `--problem` | 问题描述 | `"FCTB 在目标接近时未触发"` |
| `-e` / `--expected` | 预期行为 | `"距离小于 30m 时 FCTB 应激活"` |
| `--variant` | 项目标识 | `gen6/gwm_b26` |
| `--snapshot` | 代码快照（diagnosis 默认 auto） | `auto` / `2026-06-15-abc123` |

**示例**：
```bash
# 最简用法（自动选择模式）
python cli.py cases/FCTB001/

# 明确诊断
python cli.py cases/FCTB001/ -p "FCTB 报警太晚" -e "目标进入 ROI 即报警"

# 指定项目和快照
python cli.py cases/FCTB001/ -p "FCTB 报警太晚" -e "目标进入 ROI 即报警" \
  --variant gen6/gwm_b26 --snapshot auto
```

#### 数据查询模式（轻量分析）

```bash
python cli.py <案例目录> -q "自然语言问题"
```

**示例**：
```bash
python cli.py cases/FCTB001/ -q "FCTB 触发时 AEBIB 信号状态是什么？"
python cli.py cases/FCTB001/ -q "车速在报警窗口期间的变化情况？"
```

### 4. 查看报告

诊断完成后自动生成 HTML 报告：
```
cases/<案例名>/report_诊断时间戳.html
```

## 三种运行模式

| 模式 | CLI 入口 | 用途 |
|------|----------|------|
| **Diagnosis** | `python cli.py <dir> -p "问题" -e "预期"` | 完整根因分析（15 步管线） |
| **Query** | `python cli.py <dir> -q "问题"` | 数据查询（轻量问答） |
| **Dream** | `python cli.py --dream` | 记忆巩固（自动知识沉淀） |

## 辅助命令

| 命令 | 说明 |
|------|------|
| `--learn-constants` | 学习全局数值常量表（阈值、车速限制等） |
| `--codegraph-stats` | 查看 CodeGraph 统计信息（调试用） |

## 项目配置

### config.yaml 结构

```yaml
ai:
  # 本地模型（简单任务）
  local:
    base_url: "http://localhost:11434/v1"
    api_key: "ollama"
    model: "qwen2.5:7b"
  # 远端模型（复杂推理）
  remote:
    base_url: "${REMOTE_BASE_URL}"
    api_key: "${REMOTE_API_KEY}"
    model: "Qwen3.5-27B-FP16"
  # 思考模式: off / synth / full
  thinking: "full"

# 项目身份系统（variant 层级）
variants:
  gen6/gwm_b26:
    display_name: "GWM B26"
    codebase: "gwm_b26_code"
    key_source_files: [...]
    dbc_sets: [...]

default_variant: "gen6/gwm_b26"
```

### .env 环境变量

| 变量 | 说明 |
|------|------|
| `REMOTE_BASE_URL` | 远端 LLM API 地址 |
| `REMOTE_API_KEY` | 远端 LLM API Key |
| `LOCAL_BASE_URL` | 本地 Ollama 地址（可选） |

## 目录结构

```
radarAnalyze/
  cli.py                  # 统一 CLI 入口
  config.yaml             # 模型/项目/功能配置
  .env                    # 环境变量（API Key 等）
  requirements.txt        # Python 依赖
  IMPLEMENTATION.md       # 完整实现文档（归档用）

  ai/                     # AI 分析核心模块
    orchestrator.py       # 诊断管线编排器（15 步）
    pattern_extractor.py  # 代码模式提取器（6 种模式）
    causal_aligner.py     # 因果对齐引擎
    temporal_analyzer.py  # 时序特征分析器
    condition_extractor.py # 条件提取器（双层：规则+LLM）
    rule_condition_extractor.py # 规则条件引擎（13 类规则）
    expert_panel.py       # 专家面板（3 轮 LLM 诊断）
    frame_analyzer.py     # 帧级证据提取
    data_probe.py         # 数据探测（按需 SQL 查询）
    variable_query_planner.py # 变量查询规划器
    data_query_engine.py  # 数据查询引擎
    visualizer.py         # HTML 报告生成器
    model_router.py       # LLM 路由（local/remote/coder）
    utils.py              # 公共工具函数
    ...

  parsers/                # 数据解析层
    case_loader.py        # 案例加载器（.bag/.blf/.mf4）
    frame_store.py        # 帧存储（SQLite）
    signal_mapper.py      # 信号映射表

  memory/                 # 记忆系统
    memory_system.py      # 记忆读写（L1-L6）
    auto_dream.py         # 自动记忆巩固
    code_learner.py       # 代码知识学习者

  source_docs/            # 缓存的知识文档（按项目隔离）

  cases/                  # 案例数据目录
    FCTB001/
      recording.bag       # 原始录制数据
      recording.blf       # CAN 日志
      report_*.html       # 诊断报告产物

  tests/                  # 测试
    test_temporal_pattern_engine.py  # TPE 测试
    test_harness/         # 评估 Harness
```

## 支持的案例格式

| 格式 | 说明 |
|------|------|
| `.bag` | ROS bag（雷达原始数据） |
| `.blf` | Vector CAN log（CAN 信号日志） |
| `.mf4` | Measurement File 4（可选，需 asammdf） |

## 常见问题

### 诊断报错 "Case folder not found"
确保案例目录存在且包含 .bag 或 .blf 文件：
```bash
ls cases/FCTB001/*.bag
```

### LLM 连接失败
检查 `.env` 中的 `REMOTE_BASE_URL` 和 `REMOTE_API_KEY` 是否正确。

### 诊断报告不完整
运行 `--learn-constants` 预学习常量：
```bash
python cli.py --learn-constants --variant gen6/gwm_b26
```

### 想先看前端效果
直接运行诊断，报告为 HTML 文件，浏览器打开即可。

## 技术栈

- **Python 3.12+**（运行环境）
- **LLM 调用**：OpenAI 兼容 API（qwen3.5, claude, gpt-4o 等）
- **数据存储**：SQLite（帧数据）
- **报告**：HTML（浏览器查看）
- **CLI 框架**：argparse + rich（终端美化）
