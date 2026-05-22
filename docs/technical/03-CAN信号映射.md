# CAN 信号映射器 — SignalMapper

## 职责

从 AUTOSAR RteComMapping.c 源码中自动提取 **CAN 信号 <-> 内部变量** 的双向映射关系，支持：
1. ReadSignal 方向（CAN → 内部变量）
2. WriteSignal 方向（内部变量 → CAN）
3. 6 级优先级解析（精确匹配 → 全路径 → 后缀 → 别名 → 大小写 → 子串）
4. 变量链追踪（struct 别名、指针解引用）

## 类定义

```python
class SignalMapper:
    def __init__(self, source_root: Path, docs_dir: Path):
        self.source_root = source_root
        self.docs_dir = docs_dir
        self.signal_mapping = {}
        self.variable_chains = {}
        self.output_mapping = {}
        self.output_aliases = {}
```

## 工作流程

### Phase 1: 解析 ReadSignal

```python
def extract_signal_mapping(source_root: Path, docs_dir: Path) -> dict:
    """
    从 RteComMapping.c 提取 ReadSignal 映射。
    
    返回结构:
    {
        "source_hash": "abc123...",     # SHA256 前 16 位
        "source_file": "coem/.../RteComMapping.c",
        "mapping_count": 150,           # 映射总数
        "mappings": [...],              # 完整映射列表
        "internal_to_can": {...},       # 内部变量 → CAN 信号
        "can_to_internal": {...},       # CAN 信号 → 内部变量
        "fullpath_to_can": {...}        # 全路径 → CAN 信号
    }
    """
```

### Phase 2: 构建双向索引

```python
def _build_indices(mappings: list[dict]) -> dict:
    """
    构建双向查找索引。
    
    internal_to_can: {
        "ego_speed": ["EgoSpeed", "VehSpeed"],
        "steering_angle": ["SteerAngle"],
        ...
    }
    
    can_to_internal: {
        "EgoSpeed": ["ego_speed"],
        "VehSpeed": ["ego_speed"],
        ...
    }
    
    fullpath_to_can: {
        "g_ego.ego_speed": ["EgoSpeed"],
        ...
    }
    """
```

### Phase 3: 变量链追踪

```python
def trace_variable_chains(source_root: Path, docs_dir: Path) -> dict:
    """
    追踪 C 源码中的变量链。
    
    分析:
    1. struct 定义 → 提取 struct 别名
    2. 指针赋值 → 追踪指针目标
    3. 宏展开 → 简化宏引用
    4. 类型别名 → typedef 追踪
    
    返回:
    {
        "struct_aliases": {
            "EgoData": {"fields": ["speed", "steer", ...]},
            ...
        },
        "pointer_chains": {
            "ptr_ego": {"target": "g_ego_data", "type": "EgoData*"},
            ...
        },
        "macro_expansions": {
            "EGO_SPEED": "g_ego.speed",
            ...
        }
    }
    """
```

## 6 级优先级解析

SignalMapper 的核心创新是**多级降级解析**，即使映射不完整也能找到信号：

| 优先级 | 方法 | 示例 |
|--------|------|------|
| 1 | 精确匹配 | `ego_speed` → `EgoSpeed` (100% 匹配) |
| 2 | 全路径匹配 | `g_ego.ego_speed` → `EgoSpeed` |
| 3 | 后缀匹配 | `bRctaEnable` → `RctaEnable` |
| 4 | 别名匹配 | `ptr_ego->speed` → `EgoSpeed` (通过变量链) |
| 5 | 大小写不敏感 | `EGO_SPEED` → `EgoSpeed` |
| 6 | 子串匹配 | `speed` → `EgoSpeed` (最弱匹配) |

```python
def resolve_internal_to_can(
    internal_var: str,
    signal_mapping: dict,
    variable_chains: dict,
    output_mapping: dict = None,
    output_aliases: dict = None,
) -> list[str]:
    """
    将内部变量名解析为 CAN 信号名列表。
    
    返回按优先级排序的 CAN 信号名列表。
    如果无法解析，返回空列表。
    
    示例:
    >>> resolve_internal_to_can("ego_speed", mapping, chains)
    ["EgoSpeed", "VehSpeed"]
    
    >>> resolve_internal_to_can("unknown_var", mapping, chains)
    []
    """
```

## 解析算法

### ReadSignal 解析

```python
_READ_SIGNAL_RE = re.compile(
    r'^\s*\(void\)\s*RteComMapping_ReadSignal\((\w+)\)\s*\(\s*&\s*(\w+)\s*\)',
)

_ASSIGN_RE = re.compile(
    r'^\s*([\w.]+(?:\[[\w\d]+\])?)\s*=\s*(.+?)\s*;',
)

def _parse_rte_com_mapping(source_text: str) -> list[dict]:
    """
    解析 RteComMapping.c 中的 ReadSignal 调用。
    
    典型代码模式:
    (void) RteComMapping_ReadSignal(EgoSpeed, (&ftmp));
    g_ego.speed = ftmp;
    
    解析步骤:
    1. 逐行扫描，匹配 RteComMapping_ReadSignal 调用
    2. 提取 CAN 信号名 (第一个参数)
    3. 提取临时变量名 (第二个参数)
    4. 扫描后续 6 行，找到赋值语句
    5. 从赋值语句提取目标变量全路径和表达式
    6. 判断转换类型: passthrough / bool / transform
    7. 提取缩放因子 (如果有)
    """
```

### WriteSignal 解析

```python
_WRITE_SIGNAL_RE = re.compile(
    r'\(void\)\s*RteComMapping_WriteSignal\((\w+)\)\((.+)\)\s*;',
)

def _parse_rte_write_mapping(source_text: str) -> list[dict]:
    """
    解析 RteComMapping.c 中的 WriteSignal 调用。
    
    典型代码模式:
    (void) RteComMapping_WriteSignal(RCTA_warningReqRight, (g_rcta.warning_flag));
    
    解析步骤:
    1. 匹配 RteComMapping_WriteSignal 调用
    2. 提取 CAN 信号名 (第一个参数)
    3. 提取源表达式 (第二个参数)
    4. 从表达式提取变量名
    5. 构建 CAN → 内部变量映射
    """
```

## 输出信号映射

每个 ADAS 功能有预定义的输出信号列表：

| 功能 | 输出信号 |
|------|---------|
| FCTB | CR_BrkgReq, CR_BrkgReqVal, FCTBTrig, FCTA_Warn, FCTA_B_FuncSts |
| FCTA | FCTA_Warn, FCTA_B_FuncSts, CR_FCTA_Resp, CR_FCTB_Resp |
| RCTB | RSDS_BrkgReq, RSDS_BrkgReqVal, RSDS_BrkgTrig, RCTB_State |
| RCTA | RCTA_warningReqRight, RCTA_warningReqLeft, RCTA_State |
| BSD | BSD_LCA_warningReqRight, BSD_LCA_warningReqleft, BSD_State |
| LCA | BSD_LCA_warningReqRight, BSD_LCA_warningReqleft, LCA_State |
| DOW | DOW_warningReqRight, DOW_warningReqleft, DOW_State |
| RCW | RSDS_RCW_Trigger, RCW_State, RSDS_RCWResp, RCW_TTC |

```python
_FUNC_OUTPUT_SIGNALS: dict[str, list[str]] = {
    "FCTB": ["CR_BrkgReq", "CR_BrkgReqVal", "FCTBTrig", ...],
    "FCTA": ["FCTA_Warn", "FCTA_B_FuncSts", ...],
    ...
}

def get_output_signals_for_function(func_name: str) -> list[str]:
    """获取指定功能的输出信号列表"""
```

## 缓存机制

```python
# SHA256 前 16 位作为缓存键
source_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]

# 缓存文件: source_docs/signal_mapping.json
cache_path = output_dir / "signal_mapping.json"

# 缓存失效条件: 源码 hash 变更
if cached.get("source_hash") == source_hash:
    return cached  # 使用缓存
```

## 错误处理

| 错误场景 | 处理策略 |
|---------|---------|
| RteComMapping.c 不存在 | 返回空映射，记录警告 |
| 正则匹配失败 | 跳过该行，继续处理 |
| 赋值语句不在 6 行内 | 不记录该映射 |
| 缓存 JSON 损坏 | 重新解析源码 |
| 多 DBC 信号冲突 | 收集所有匹配，按优先级排序 |

## 性能考虑

- 首次解析: ~50ms (正则扫描 + 索引构建)
- 缓存命中: < 1ms (JSON 读取)
- 内存占用: ~10KB (典型映射表)
- 6 级解析: 每变量 ~100μs (字典查找 + 字符串匹配)
