# AI Coding 助手实现提示词

> 这是一个**项目级 AI 编程助手**，不是简单的代码生成工具。它需要深度理解项目代码、内化成知识、并能根据需求自主修改代码。

---

## 【任务定义】

为 radarAnalyze 项目构建一个**AI Coding 助手**，具备以下能力：

1. **代码库理解** — 自动扫描、分析、索引整个项目代码
2. **知识内化** — 将代码结构、设计模式、业务逻辑固化到记忆系统
3. **需求驱动开发** — 根据客户需求文档（PDF/Excel）生成或修改代码
4. **智能代码修改** — 理解上下文，安全地修改现有代码
5. **变更影响分析** — 预测代码修改的影响范围

---

## 【项目背景】

### 项目信息

- **项目名称**: radarAnalyze（角雷达问题分析系统）
- **项目位置**: `D:/RamboStar/idea/radarAnalyze`
- **目标代码库**: `D:/cr60_light`（TI AWR2E44P 平台 C 代码）
- **语言**: Python (工具链) + C (目标代码)

### 代码库结构

```
D:/cr60_light/
├── coem/GWM_B26/components/AswPerception/func/
│   ├── adasFunc.c          # 核心报警逻辑（6500+ 行）
│   ├── adasFunc.h
│   └── ...
├── coem/GWM_B26/components/AswIf/ASW_IN/
│   ├── RteComMapping.c     # CAN 信号映射（需增强）
│   ├── RteComMapping.h
│   ├── ASWIN_SystemState.c # 状态机逻辑
│   └── ...
├── coem/GWM_B26/components/AswIf/ASW_OUT/
│   └── ASWOUT_OutCalc.c    # 输出协调逻辑
├── adas/symmetry/perception/src/
│   ├── track.c             # 目标跟踪
│   ├── objAttribCal.c      # 目标属性计算
│   └── postProcess.c       # 后处理
└── ...
```

### 已有知识资产

```
radarAnalyze/source_docs/
├── signal_mapping.json      # CAN 信号 ↔ 内部变量映射（91 条）
├── variable_chains.json     # 结构体别名链
├── SYSTEM_GUIDE.md          # 系统架构文档
├── {BSD,FCTA,FCTB,...}.md   # 功能规格文档
└── *_conditions.json        # 触发条件提取结果
```

---

## 【核心能力要求】

### 能力 1: 代码库深度理解

#### 1.1 自动代码索引

```python
# ai/codebase_indexer.py（新建）

class CodebaseIndexer:
    """自动扫描并索引整个 C 代码库"""
    
    def __init__(self, source_root: Path):
        self.source_root = source_root
        self.index = {
            "files": {},           # 文件信息
            "functions": {},       # 函数签名 + 位置
            "structures": {},      # struct 定义
            "macros": {},          # 宏定义
            "includes": {},        # 头文件依赖
            "call_graph": {},      # 函数调用关系
        }
    
    def scan(self) -> dict:
        """
        扫描整个代码库，提取：
        
        1. 文件级信息
           - 路径、行数、修改时间
           - #include 依赖列表
           - 文件注释/说明
        
        2. 函数级信息
           - 函数签名（返回类型、参数）
           - 所在文件、行号
           - 函数体摘要（AI 生成）
           - 被哪些函数调用（调用图）
        
        3. 数据结构
           - struct/typedef 定义
           - 字段列表及类型
           - 使用位置
        
        4. 宏定义
           - #define 名称、值
           - 条件编译 (#ifdef)
        
        5. 调用关系
           - 函数 A 调用函数 B
           - 构建调用图
        """
        pass
    
    def save_index(self, path: Path):
        """保存索引到 memory/codebase_index.json"""
        pass
    
    def query(self, pattern: str) -> list[dict]:
        """
        查询索引
        
        示例：
        - "所有包含 FCTB 的函数" → [FCTB_Calc, FCTB_Check, ...]
        - "调用 bFctbKeepBrakeFlg 的地方" → [adasFunc.c:6378, ...]
        - "RteComMapping 中处理 AEB 信号的代码" → [...]
        """
        pass
```

#### 1.2 代码语义理解

```python
def analyze_function_semantics(self, func_name: str, source_code: str) -> dict:
    """
    使用 AI 分析函数的语义：
    
    返回：
    {
        "name": "FCTB_Calc",
        "purpose": "FCTB 功能核心计算，判断是否触发制动",
        "inputs": ["目标 TTC", "自车速度", "功能使能标志"],
        "outputs": ["bFctbWarnFlg", "bFctbBrakeFlg"],
        "key_logic": [
            "1. 检查使能条件（车速、档位、AEB 状态）",
            "2. 遍历目标，计算 TTC",
            "3. TTC < 阈值 → 设置警告标志",
            "4. 满足制动条件 → 设置制动标志"
        ],
        "side_effects": ["修改全局变量 g_FctbState"],
        "complexity": "中等（含循环和条件分支）"
    }
    """
    pass
```

---

### 能力 2: 知识内化与记忆

#### 2.1 知识存储结构

```json
// memory/coding_knowledge.json（新建）
{
  "project_overview": {
    "name": "GWM_B26 ASW 系统",
    "platform": "TI AWR2E44P",
    "description": "角雷达 ADAS 功能实现，包含 BSD/LCA/FCTA/FCTB 等 8 个功能",
    "architecture": "分层架构：信号输入 → 状态机 → 算法计算 → 输出协调"
  },
  "modules": {
    "adasFunc.c": {
      "path": "coem/GWM_B26/components/AswPerception/func/adasFunc.c",
      "purpose": "ADAS 功能核心算法实现",
      "line_count": 6543,
      "key_functions": [
        {
          "name": "FCTB_Calc",
          "line": 6200,
          "purpose": "FCTB 制动逻辑计算",
          "inputs": ["TTC", "车速", "使能标志"],
          "outputs": ["制动标志", "警告标志"],
          "related_functions": ["FCTA_Calc", "FCTB_CheckConditions"]
        }
      ],
      "coding_patterns": [
        "bool 变量用 b 前缀（bFctbWarnFlg）",
        "float 变量用 f 前缀（fFctbTTC）",
        "条件检查用宏封装（IS_SPEED_VALID）"
      ]
    }
  },
  "signal_mapping_rules": {
    "description": "CAN 信号到内部变量的映射规则",
    "patterns": [
      {
        "type": "bool_signal",
        "template": "RteComMapping_ReadSignal({CAN_SIG}, &u8tmp); {INTERNAL_VAR} = (u8tmp != 0);",
        "examples": ["AEBBAActv_0x137 → bAEBBAActiveFlg"]
      },
      {
        "type": "scaled_value",
        "template": "RteComMapping_ReadSignal({CAN_SIG}, &u16tmp); {INTERNAL_VAR} = (float)u16tmp * {SCALE}f;",
        "examples": ["EgoVehSpd_0x137 → fEgoSpeed (scale=0.01)"]
      }
    ]
  },
  "common_tasks": {
    "add_signal_mapping": {
      "description": "添加新的 CAN 信号映射",
      "steps": [
        "1. 在 RteComMapping.c 找到对应消息 ID 的处理位置",
        "2. 添加 RteComMapping_ReadSignal 调用",
        "3. 根据信号类型进行转换（bool/scale/enum）",
        "4. 赋值到目标内部变量"
      ],
      "related_files": ["RteComMapping.c", "DBC 文件"],
      "risk_level": "低（局部修改）"
    },
    "modify_threshold": {
      "description": "修改功能阈值",
      "steps": [
        "1. 在 paraDefine.h 中找到阈值宏定义",
        "2. 修改阈值数值",
        "3. 验证相关功能的触发条件"
      ],
      "related_files": ["paraDefine.h", "adasFunc.c"],
      "risk_level": "中（影响功能行为）"
    }
  }
}
```

#### 2.2 知识自动更新

```python
# 每次代码扫描后，自动更新 coding_knowledge.json

def update_knowledge_from_scan(self, scan_result: dict):
    """
    从扫描结果中提取新知识：
    - 新增函数 → 添加到 modules
    - 新增 struct → 添加到 structures
    - 代码模式 → 提取到 coding_patterns
    """
    pass

def learn_from_user_feedback(self, task: str, success: bool, feedback: str):
    """
    从用户反馈中学习：
    - 成功的任务 → 固化为 common_tasks
    - 失败的尝试 → 记录为 pitfalls（陷阱）
    - 用户偏好 → 更新到 coding_conventions
    """
    pass
```

---

### 能力 3: 需求驱动开发

#### 3.1 客户需求文档解析

```python
# ai/requirement_parser.py（新建）

class RequirementParser:
    """解析客户需求文档（PDF/Excel/Word）"""
    
    def parse_pdf(self, pdf_path: Path) -> dict:
        """
        解析 PDF 需求文档
        
        返回：
        {
            "requirements": [
                {
                    "id": "REQ-001",
                    "title": "新增 BSD 抑制信号",
                    "description": "当转向灯激活时，抑制同侧 BSD 警告",
                    "type": "new_feature",  # new_feature / bug_fix / threshold_change
                    "affected_functions": ["BSD"],
                    "signals": ["TurnSignalLeft", "TurnSignalRight"],
                    "priority": "高"
                }
            ],
            "thresholds": [
                {"signal": "TTC_Threshold", "value": 2.0, "unit": "s"}
            ],
            "signal_mappings": [
                {"can_signal": "TurnSignalLeft_0x137", "internal_var": "bTurnSignalLeftFlg"}
            ]
        }
        """
        pass
    
    def parse_excel(self, excel_path: Path) -> dict:
        """
        解析 Excel 映射表
        
        格式示例：
        | CAN 信号 | 消息 ID | 起始位 | 长度 | 缩放 | 偏移 | 内部变量 | 类型 |
        | TurnSignalLeft | 0x137 | 0 | 1 | 1 | 0 | bTurnSignalLeftFlg | bool |
        """
        pass
```

#### 3.2 需求到代码的映射

```python
# ai/coding_assistant.py（核心）

class CodingAssistant:
    """AI Coding 助手核心"""
    
    def __init__(self, codebase_index: dict, knowledge: dict):
        self.index = codebase_index
        self.knowledge = knowledge
    
    def plan_implementation(self, requirement: dict) -> dict:
        """
        为需求制定实现计划
        
        输入：需求（来自 PDF/Excel 解析）
        输出：实现计划
        
        示例输出：
        {
            "requirement_id": "REQ-001",
            "tasks": [
                {
                    "task": "添加 TurnSignalLeft 信号映射",
                    "file": "RteComMapping.c",
                    "location": "消息 0x137 处理区域（约第 450 行）",
                    "code_template": "...",
                    "risk": "低"
                },
                {
                    "task": "在 BSD 逻辑中添加抑制条件",
                    "file": "adasFunc.c", 
                    "location": "BSD_Calc 函数（约第 2300 行）",
                    "modification": "在触发条件前添加 if (!bTurnSignalLeftFlg) 检查",
                    "risk": "中"
                }
            ],
            "test_cases": [
                "转向灯左开时，左侧 BSD 不触发",
                "转向灯关闭时，BSD 正常工作"
            ],
            "estimated_effort": "2 小时"
        }
        """
        pass
    
    def generate_code(self, task: dict) -> str:
        """
        生成具体代码
        
        关键：生成的代码必须符合项目现有风格
        - 变量命名（b/f/g_ 前缀）
        - 注释格式
        - 缩进风格
        - 错误处理模式
        """
        pass
    
    def apply_modification(self, file_path: Path, modification: dict) -> bool:
        """
        安全地修改现有代码
        
        流程：
        1. 读取文件
        2. 定位修改位置（基于行号或代码模式）
        3. 生成备份（.bak）
        4. 应用修改
        5. 验证语法（可选）
        
        返回：成功/失败
        """
        pass
```

---

### 能力 4: 智能代码修改

#### 4.1 上下文感知修改

```python
def modify_with_context(self, file_path: Path, instruction: str) -> dict:
    """
    基于自然语言指令修改代码
    
    示例指令：
    - "在 FCTB_Calc 函数中添加 AEB 状态检查"
    - "将 TTC 阈值从 2.0 改为 2.5"
    - "为 CR_BsdSuppression 信号添加映射"
    
    流程：
    1. 解析指令，提取意图
    2. 查询 codebase_index 找到相关代码位置
    3. 读取上下文（前后 50 行）
    4. 生成修改方案
    5. 用户确认 → 应用修改
    
    返回：
    {
        "file": "adasFunc.c",
        "original_code": "...",
        "modified_code": "...",
        "diff": "...",
        "explanation": "在 FCTB_Calc 的第 6250 行添加了 AEB 状态检查...",
        "rollback_available": true
    }
    """
    pass
```

#### 4.2 影响范围分析

```python
def analyze_impact(self, modification: dict) -> dict:
    """
    分析代码修改的影响范围
    
    返回：
    {
        "directly_affected": ["adasFunc.c:FCTB_Calc"],
        "callers": ["ASW_MainLoop", "FCTB_Entry"],  # 调用修改函数的地方
        "callees": ["FCTB_CheckTTC", "FCTB_UpdateState"],  # 被修改函数调用的地方
        "related_signals": ["CR_FctbWarnReq", "bFctbWarnFlg"],
        "risk_assessment": "中风险 — 影响 FCTB 触发逻辑，需回归测试",
        "test_recommendations": [
            "运行 FCTA001 案例验证 FCTA 不受影响",
            "运行 FCTB001 案例验证 FCTB 功能正常"
        ]
    }
    """
    pass
```

---

### 能力 5: CLI 交互界面

```python
# cli.py 扩展

parser.add_argument("--code-task", help="编码任务描述", 
                    example="添加 TurnSignalLeft 信号映射到 bTurnSignalLeftFlg")
parser.add_argument("--requirement-doc", help="需求文档路径（PDF/Excel）")
parser.add_argument("--generate-plan", action="store_true", help="仅生成计划，不执行")
parser.add_argument("--apply", action="store_true", help="应用修改（需确认）")
parser.add_argument("--dry-run", action="store_true", help="模拟执行，不修改文件")
parser.add_argument("--backup", action="store_true", help="修改前创建备份（默认开启）")

# 使用示例

# 1. 从需求文档生成实现计划
python cli.py --requirement-doc "requirements.pdf" --generate-plan

# 2. 执行编码任务（dry-run 模式）
python cli.py --code-task "添加 CR_BsdSuppression 信号映射" --dry-run

# 3. 执行编码任务（实际应用）
python cli.py --code-task "添加 CR_BsdSuppression 信号映射" --apply

# 4. 查询代码库
python cli.py --query "所有使用 bFctbKeepBrakeFlg 的地方"

# 5. 分析影响
python cli.py --code-task "修改 FCTB_Calc 阈值" --analyze-impact
```

---

## 【验收标准】

### 功能验收

| 能力 | 验收标准 |
|------|----------|
| 代码索引 | 能正确提取所有函数签名、struct 定义、调用关系 |
| 知识内化 | coding_knowledge.json 包含模块、模式、常见任务 |
| 需求解析 | 能从 PDF 提取需求条目，从 Excel 提取映射表 |
| 代码生成 | 生成的代码符合项目风格，可直接编译 |
| 代码修改 | 能安全修改现有代码，支持回滚 |
| 影响分析 | 能正确识别调用关系和影响范围 |

### 质量验收

- **准确性**: 代码索引准确率 > 95%
- **安全性**: 修改前必须备份，支持一键回滚
- **一致性**: 生成代码与现有代码风格一致
- **可解释性**: 每次修改都有清晰的说明

---

## 【交付物】

1. **ai/codebase_indexer.py** — 代码库扫描与索引
2. **ai/requirement_parser.py** — 需求文档解析（PDF/Excel）
3. **ai/coding_assistant.py** — Coding 助手核心
4. **memory/coding_knowledge.json** — 知识存储（初始版本）
5. **cli.py 修改** — 新增编码任务命令
6. **单元测试** — 验证各模块功能

---

## 【实施步骤建议】

### Phase 1: 代码索引（2 天）
1. 实现 codebase_indexer.py
2. 扫描 D:/cr60_light 生成初始索引
3. 验证索引准确性

### Phase 2: 知识内化（1 天）
1. 设计 coding_knowledge.json 结构
2. 从索引中提取知识
3. 实现知识更新机制

### Phase 3: 需求解析（1 天）
1. 实现 PDF 解析（使用 PyMuPDF/pdfplumber）
2. 实现 Excel 解析（使用 pandas）
3. 验证解析结果

### Phase 4: 代码生成与修改（2 天）
1. 实现 coding_assistant.py 核心逻辑
2. 实现安全修改机制（备份 + 回滚）
3. 实现影响分析

### Phase 5: CLI 集成（0.5 天）
1. 扩展 cli.py 命令
2. 测试完整流程

---

*提示词版本：1.0*
*生成时间：2026-04-17*
*适用项目：radarAnalyze + cr60_light*
