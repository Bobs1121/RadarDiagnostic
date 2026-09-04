# Gen5 ReCo (Xpeng/BYD) 集成方案
## 从 代码扫描 → 知识抽取 → 数据联合分析

---

## 一、问题定义

当前 radarAnalyze 工具只支持 Gen6 Symmetry（C 单体），需要支持 Gen5 ReCo（C++ Flux/DADDY 分布式）。

| 维度 | Gen6 Symmetry | Gen5 ReCo |
|------|---------------|-----------|
| **语言** | C | C++ |
| **架构** | monolithic adasFunc.c | Flux 组件 + PER/SIT/FCT/HMI |
| **文件数** | ~10 key files | 661+ component/core files |
| **状态机** | 单一 if-else (0-6 states) | PSS StateMachine<T> 模板 |
| **通信** | RteComMapping.c (AUTOSAR RTE) | DADDY RPC (Distributed Data framework) |
| **参数** | #define/float 全局变量 | PAD XML/Header |
| **信号映射** | RteComMapping ReadSignal/WriteSignal | DADDY channels → MF4/DBC 直接输出 |
| **构建** | Scons | Flux build system |
| **AST** | tree-sitter-c ✅ | tree-sitter-cpp ❌ (需安装+适配) |

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Orchestrator (ai/orchestrator.py)                                       │
│                                                                          │
│  1. 从 config.yaml 读取 variant 的 platform_id                           │
│  2. 根据 platform_id 加载对应的平台适配器 (platform_adapters)             │
│  3. 将适配器注入: CodeLearner / ConditionExtractor / CodeGraphBuilder    │
│  4. 自动执行: auto_dream learn → codegraph build → 诊断分析              │
│  │                                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  Platform Detection & Adapter Resolution                         │    │
│  │                                                                  │    │
│  │  config.yaml → variant → codebase_id → platform_id              │    │
│  │       gen5/byd          → byd_ovs_cb → gen5_cpp_radar (fallback)│    │
│  │       gen5/xpeng        → pl_xpeng_reco → gen5_reco_pl ✨        │    │
│  │                                                                  │    │
│  │  get_code_learner_adapter(platform_id) → Gen5RecoAdapter         │    │
│  │  get_condition_extractor_adapter(p_i) → Gen5RecoConditionAdapter│    │
│  │  get_signal_mapper_adapter(p_i)       → Gen5RecoSignalMapper    │    │
│  └──────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
     │ CodeLearner  │ │ConditionExt. │ │SignalMapper  │
     │              │ │              │ │              │
     │ get_focus_   │ │ get_source_  │ │ extract_     │
     │   files()    │ │ domains()    │ │   mapping()  │
     │              │ │              │ │              │
     │ get_funcs_   │ │ get_prompt() │ │ resolve_     │
     │   keywords() │ │              │ │   internal_  │
     │              │ │ extract()    │ │   to_can()   │
     │ AI 调用 →    │ │ ───────────→ │ │              │
     │ JSON知识     │ │  conditions  │ │  空 (Gen5    │
     │              │ │              │ │   无RteCom)  │
     └──────────────┘ └──────────────┘ └──────────────┘
            │                 │                 │
            ▼                 ▼                 ▼
     ┌──────────────────────────────────────────────────┐
     │  CodeGraphBuilder (codegraph/builder.py)          │
     │                                                  │
     │  gen6: 扫描 key_source_files (~15 个 C 文件)      │
     │  gen5: 扫描 reco_fw/**/*.{cpp,hpp} (661+ 文件)   │
     │                                                  │
     │  C++ AST 解析:                                   │
     │   ├── ASTParser: 提取 FunctionDef, FunctionCall   │
     │   ├── 模板实例化: StateMachine<T>, Runnable<T>   │
     │   ├── DADDY 通道: TSenderPort<T>, TLatestPort    │
     │   └── 模块绑定: BELONGS_TO → PER/SIT/FCT/HMI     │
     └──────────────────────────────────────────────────┘
                              │
                              ▼
                    memory/codegraph.db (SQLite)
                    查询 API: get_callers, get_callees, search
```

---

## 三、实现计划 — 5 步

### Step 1: AST C++ 支持 (tree-sitter-cpp 适配)

**文件修改**:
- `ai/codegraph/ast_parser.py` — 新增 `_cpp_parser` 模块
- `ai/codegraph/ast_builder.py` — 新增 `CPPBuilder` 类

**变更内容**:
```python
# ast_parser.py
import tree_sitter_cpp as ts_cpp  # NEW

class CppParser:
    """C++ parser wrapper for tree-sitter-cpp."""
    
    def parse_file(self, path: Path):
        # 使用 tree_sitter_cpp 语言
        with open(path, 'rb') as f:
            source = f.read()
        tree = self.parser.parse(source)
        return tree, source
    
    def extract_functions(self, tree, source):
        # C++ 特有:
        # - class 方法和静态成员
        # - 模板实例化 (StateMachine<Bsd>)
        # - 继承链 (class RunnableFsm : public RunnableWithControllers<...>)
        # - 命名空间 (namespace PlReCo::Sit)
        # - 泛型参数解析 ...
    
    def get_class_hierarchy(self, tree, source):
        # 提取 class/struct 继承关系
        # 用于理解 PSS StateMachine 模板和 Runnable 继承链
```

**关键点**:
1. C++ 特有解析: class, namespace, template, inheritance
2. 保留与 C 解析器的兼容 (shared base methods)
3. 支持 `StateMachine<Bsd>` → 解析为 class="StateMachine", template_arg="Bsd"
4. 支持 `Runnable<Controller>` → 解析为 class="Runnable", template_arg="Controller"

### Step 2: Gen5 平台适配器

**新增文件**:
- `ai/platform_adapters/gen5_reco_pl.py` — Gen5 所有适配器实现

**核心内容**:

```python
# CodeLearnerAdapter
class Gen5RecoCodeLearnerAdapter(BaseCodeLearnerAdapter):
    def get_key_source_files(self) -> list[str]:
        # 返回所有 PER/SIT/FCT 的关键文件
        return [
            # FCT - 状态机
            "reco_fw\\component\\fct\\modules\\stateMachine\\pss\\*.hpp",
            # SIT - 行为策略
            "reco_fw\\component\\sit\\modules\\behaviorStrategies\\TIPL\\*.hpp",
            "reco_fw\\component\\sit\\runnables\\behaviors\\FM\\*.hpp",
            # PER - 雷达感知
            "reco_fw\\component\\per\\runnables\\*.cpp",
            # PAD 参数
            "reco_fw\\configuration\\rearcorner\\params\\*.hpp",
            "apl\\base\\component\\fct\\config\\padfct\\*.h",
        ]
    
    # Gen5 特有的 Prompt —— 理解 Flux/DADDY 架构
    def build_prompt_template(self, focus: str):
        system = "你是 Bosch ReCo (RCC1010) C++ 源码分析专家，精通 Flux 架构、DADDY RPC、PSS 状态机。"
        # ... 见下方详细 prompt
```

**ConditionExtractorAdapter**:
```python
class Gen5RecoConditionExtractorAdapter(BaseConditionExtractorAdapter):
    def get_source_domains(self):
        return {
            "fct_fsm": [...],        # BSD/LCA/RCTA/FCTA 状态机
            "sit_behavior": [...],    # TIPL/FM 行为策略
            "per_spp": [...],         # 雷达感知
            "fct_fsm": [...],         # FCT 决策
        }
    
    # Gen5 提取 prompt —— 不同于 Gen6 的 if-else
    def get_extraction_prompt(self, func_name):
        # 提取 FCT StateMachine 的状态转换:
        # - ActiveState handleState() 方法
        # - FCP (Functional Condition Processing) 条件
        # - FIP (Functional Input Processor) 计算逻辑
        # - DADDY 通道连接
```

**SignalMapperAdapter**:
```python
class Gen5RecoSignalMapperAdapter(BaseSignalMapperAdapter):
    # Gen5 没有 RteComMapping.c
    # 信号映射方案:
    #   1. 从 PAD header 文件提取默认值
    #   2. 从 Flux channel.xml 提取通道定义
    #   3. 从 MF4 信号名反推 (通过 classifier)
    
    def extract_signal_mapping(self, source_root, output_dir):
        return {"mappings": [], "reason": "Gen5 uses MF4/DADDY, not RteComMapping"}
    
    def get_output_signals_for_function(self, func_name):
        # 返回 Gen5 特定输出命名空间
        return {
            "BSD": ["BSD_Status", "BSD_WarnL", "BSD_WarnR", "BsdlcaWarnL", ...],
            "RCTA": ["RCTA_Warn", ...],
        }
```

### Step 3: CodeGraph Builder 全量扫描

**文件修改**: `ai/codegraph/builder.py`

**变更内容**:

```python
class CodeGraphBuilder:
    
    def _discover_source_files(self) -> list[dict]:
        """根据平台发现源码文件。
        
        Gen6: 扫描 config.yaml 中的 key_source_files (~15 个文件)
        Gen5: 扫描 reco_fw/ 下所有 .cpp/.hpp 文件 (661+ 文件)
        """
        # 现有: key_source_files + calib_files
        # 新增: platform-aware glob
        
        platform_id = getattr(self, '_platform_id', None)
        if platform_id.startswith("gen5"):
            # Gen5: 递归扫描
            files = []
            for root, dirs, filenames in self.source_root.rglob("*"):
                if root.suffix in (".cpp", ".hpp", ".h", ".c"):
                    files.append(self._make_file_info(root))
            return files
        else:
            # Gen6: 现有逻辑不变
            return analyzer.phase1_file_index(
                self.source_root, self.key_files + self.calib_files
            )
    
    def _use_ast_or_cpp(self) -> bool:
        """检测是否需要使用 AST 解析 (C++ 或 C 都支持)。"""
        return True  # 全量启用 AST
```

### Step 4: Orchestrator 平台路由

**文件修改**: `ai/orchestrator.py`

**变更内容**:

```python
class Orchestrator:
    
    @property
    def platform_id(self) -> str:
        """从当前 variant 解析 platform_id。"""
        from config import get_variant, get_codebase, get_platform
        variant = get_variant(self.config, self.variant_id)
        codebase = get_codebase(self.config, variant.codebase_id)
        platform = get_platform(self.config, codebase.platform_id)
        return platform.id  # e.g. "gen5_reco_pl", "gen6_c_radar"
    
    def _init_analysis_modules(self):
        """初始化分析模块，根据 platform_id 加载对应适配器。"""
        from .platform_adapters.factory import (
            get_code_learner_adapter,
            get_condition_extractor_adapter,
            get_signal_mapper_adapter,
        )
        
        platform_id = self.platform_id
        
        # 加载适配器实例
        self._cl_adapter = get_code_learner_adapter(
            platform_id, self.source_root, self.config, self.project_root
        )
        self._ce_adapter = get_condition_extractor_adapter(
            platform_id, self.source_root, self.config, self.project_root
        )
        self._sm_adapter = get_signal_mapper_adapter(
            platform_id, self.source_root, self.source_docs_dir,
            self.config, self.project_root
        )
    
    def _build_codegraph(self, status):
        """构建 CodeGraph，传入 platform_id。"""
        # 现有代码 ...
        builder = CodeGraphBuilder(
            db_path=db_path,
            source_root=source_root,
            key_files=key_files,
            func_keywords=self._sm_adapter.get_func_keywords() 
                if hasattr(self._sm_adapter, 'get_func_keywords') else FUNC_KEYWORDS,
            calib_files=calib_files,
            source_docs_dir=self.source_docs_dir,
            variable_filter=variable_filter,
            _platform_id=self.platform_id,  # ✨ 新增: 传递 platform_id
        )
```

### Step 5: 测试与验证

**测试清单**:
1. `tree-sitter-cpp` 解析 `fct_s_bsdStateMachine.hpp` 正确提取 class/method
2. CodeGraph 构建对 `reco_fw/` 下 661 文件不超时/不出错
3. `CodeGraph.search("Blindness")` 能搜到 PER/SIT/FCT 中的相关函数
4. `CodeGraph.get_callers("bsdWarningZoneEvaluation")` 返回正确
5. CodeLearner `learn()` 成功生成 BSD/FCTA/RCTA 的知识 JSON
6. ConditionExtractor `extract("BSD")` 返回 FCT 状态机条件
7. 完整诊断流程: `python cli.py --variant gen5/xpeng <case>` 不崩溃

---

## 四、关键设计决策

### Q1: 为什么不在 condition_extractor 中继续硬编码 Gen5 支持？

**A**: 之前的条件分支尝试（条件检查 Gen5 源文件路径）已经证明维护困难。
适配器模式将 Gen6/Gen5 的特定逻辑完全隔离，新增 Gen7 只需注册新 adapter。

### Q2: Gen5 全量扫描 661 文件会不会很慢？

**A**: 
- CodeGraphBuilder 已有增量机制：hash 未变跳过
- AST 解析单个 .cpp 约 200ms，661 个 ≈ 2min（首次）
- 后续增量 ≈ 10s（仅 1-2 个文件变更时）
- 可在 Orchestrator 后台静默运行

### Q3: Gen5 没有 RteComMapping.c，信号映射怎么办？

**A**: 
1. **PAD 参数文件** (`padfct_s_par_gen.h`, `reco_fw_config_sit_bsd*.hpp`) 提取阈值
2. **DADDY 通道定义** (Flux XML) 提取信号名
3. **MF4 信号名** 通过 classifier 映射到 ReCo 内部信号
4. **DBC 文件** 作为已知信号名参考
5. SignalMapper adapter 返回空结果 + 注释说明，不影响分析流程

### Q4: C++ 模板和泛型怎么处理？

**A**:
- `StateMachine<Bsd>` → 解析为 class "StateMachine"，template_arg "Bsd"
- `Runnable<Controller>` → 解析为 class "Runnable"，template_arg "Controller"
- 模块绑定 (BELONGS_TO) 根据命名空间和文件名推断

---

## 五、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| tree-sitter-cpp 对 C++ 语法覆盖不完整 | 部分代码解析失败 | 回退到 regex 解析 (analyzer.py) |
| 661 文件 AST 解析内存/时间 | 首次构建超时 | 分批处理 + timeout + 后台 |
| Gen5 文件路径变体 (BYD vs XPENG) | 关键文件未找到 | adapter 中处理路径差异 |
| PAD 参数格式差异 (XML vs header) | 阈值提取不准 | LLM 辅助提取 fallback |

---

## 六、最终架构全景

```
                           config.yaml
                        ┌─────────────┐
                        │ platform_id │ ← gen5_reco_pl / gen6_c_radar / gen5_cpp_radar
                        └──────┬──────┘
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
        ┌────────────┐  ┌────────────┐  ┌────────────┐
        │Gen5Reco    │  │Gen5Cpp     │  │Gen6Symmetry│
        │Adapter     │  │Adapter     │  │Adapter     │
        │            │  │(fallback)  │  │            │
        │- flux aware│  │- C++ files │  │- adasFunc  │
        │- DADDY RPC │  │  scan      │  │  C单体      │
        │- PAD params│  │           │  │- RteCom    │
        │- no RteCom │  │           │  │- if-else   │
        └──────┬─────┘  └──────┬─────┘  └──────┬─────┘
               │               │               │
               └───────────────┼───────────────┘
                               ▼
                  ┌────────────────────────┐
                  │  Orchestrator          │
                  │  (统一调度层)           │
                  │                        │
                  │  auto_dream learn      │
                  │  codegraph build       │
                  │  condition extract     │
                  │  signal mapping        │
                  │  expert panel          │
                  └───────────┬────────────┘
                              │
                              ▼
                  ┌────────────────────────┐
                  │  CodeGraph + Knowledge  │
                  │  SQLite + JSON          │
                  │  (平台无关查询API)        │
                  └────────────────────────┘
```

---

## 七、文件变更清单

### 新增文件
1. `ai/platform_adapters/__init__.py` — 包管理
2. `ai/platform_adapters/base.py` — 统一适配器接口
3. `ai/platform_adapters/factory.py` — 注册表 + 工厂
4. `ai/platform_adapters/gen6_symmetry.py` — Gen6 适配器实现
5. `ai/platform_adapters/gen5_reco_pl.py` — Gen5 ReCo 适配器 (核心)

### 修改文件
6. `ai/codegraph/ast_parser.py` — 新增 C++ 解析 (`tree_sitter_cpp`)
7. `ai/codegraph/ast_builder.py` — 新增 C++ 转换 (`CPPBuilder`)
8. `ai/codegraph/builder.py` — 全量扫描 + platform_id 支持
9. `ai/code_learner.py` — 改为通过 adapter 获取配置 (解耦)
10. `ai/condition_extractor.py` — 改为通过 adapter 获取配置 (解耦)
11. `ai/signal_mapper.py` — 改为通过 adapter 获取配置 (解耦)
12. `ai/orchestrator.py` — 新增 platform detection + adapter 注入
13. `config.yaml` / `config.local.yaml` — Gen5 平台定义 + 变体配置

---

## 八、时间估算

| Step | 工作量 | 备注 |
|------|--------|------|
| Step 1: AST C++ 支持 | 1 day | tree-sitter-cpp 安装 + 适配 C++ class/template/namespace |
| Step 2: Gen5 Adapter | 1.5 days | CodeLearner + ConditionExtractor + SignalMapper 三个 adapter |
| Step 3: CodeGraph 全量扫描 | 0.5 days | 改造 _discover_source_files |
| Step 4: Orchestrator 路由 | 0.5 days | platform_id 解析 + adapter 注入 |
| Step 5: 测试验证 | 1 day | 端到端测试 + 修复 |
| **合计** | **4.5 days** | 可分拆并行 |

---

*Created: 2026-07-24*
*Target: Enable full Gen5 ReCo (Xpeng/BYD RCC1010) analysis in radarAnalyze*
