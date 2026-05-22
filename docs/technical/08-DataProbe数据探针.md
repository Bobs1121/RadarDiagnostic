# DataProbe — 数据探针引擎

## 职责

DataProbe 是无状态的数据查询执行器。它不携带任何业务领域知识，只回答一个问题："给定字段（或字段间的算术表达式），按某维度分组，用过滤条件筛选，返回统计数据"。

设计原则：**零业务逻辑**。不知道 ADAS 功能是什么，不知道 BSD/LCA 的区别，不知道哪些变量"重要"。那些知识在 `VariableQueryPlanner` 中。

## 数据源表

| 表名 | 粒度 | 用途 |
|------|------|------|
| `radar_objects` | 每帧每目标 | 目标属性、告警标志 |
| `radar_debug` | 每帧每雷达 | 自车状态快照 |
| `warning_events` | 预计算事件 | 告警边沿事件 |
| `bag_frames` | 原始 bag | 结构化 JSON |
| `can_frames` | CAN 解码 | JSON 信号 |

## 表达式引擎

### 安全求值 — asteval

```python
class _SafeEvaluator:
    """
    asteval 薄封装，用于向量化 numpy 求值。
    
    绝不使用 Python eval()。
    asteval 白名单化 Python 操作 + 限制符号表为已知列 + 安全的 numpy 辅助函数。
    """
    
    # 暴露的安全 numpy 函数:
    # abs, sqrt, where, clip, minimum, maximum,
    # isfinite, isnan, log, exp
```

### 支持的表达式

- 列名: `dist_y`, `vel_x`, `ttc`
- 算术: `dist_y + 0.25 * obj_length`
- 布尔过滤: `abs(dist_y) < 4.12`
- 位运算: `in_window & (dist_x < 0)`

### 语义字段

| 字段 | 定义 | 可用表 |
|------|------|--------|
| `side` | `'left' if dist_y >= 0 else 'right'` | radar_objects |
| `in_window` | 时间戳落在测试窗口内 | 所有表 |
| `is_stable_target` | `life_cycle >= 5` | radar_objects |

## 查询接口

```python
probe = DataProbe(store, windows=[(t0_ns, t1_ns), ...])

result = probe.query(
    field="dist_y + 0.25 * obj_width",   # 字段或表达式
    table="radar_objects",                  # 目标表
    group_by="side",                        # 分组维度
    filter="in_window & (dist_x < 0)",     # 过滤条件
    stats=["count", "min", "max", "p50", "p90"],  # 统计量
)
```

## 执行流程

```
1. 解析表达式 → 提取所需列名 (collect_names)
2. 分离语义字段 vs 物理列
3. 构建 SQL: SELECT 所需列 FROM 表 LIMIT 500000
4. 拉取原始行 → 转为 numpy 列字典
5. 物化语义字段:
   - side: np.where(dist_y < 0, "right", "left")
   - in_window: 逐窗口比对 timestamp_ns
   - is_stable_target: life_cycle >= 5
6. 应用过滤:
   - 自动重写 and/or/not → &amp;&amp;/||/~~ (numpy 元素级操作符)
   - asteval 求值过滤表达式
   - 生成布尔 mask，过滤所有列
7. 求值目标字段表达式 (asteval)
8. 分组统计 (numpy):
   - 按 group_by 列分组
   - 计算 count/min/max/mean/std/p10/p50/p90
9. 返回 ProbeResult.to_dict()
```

## 统计量

| 统计量 | 计算方式 |
|--------|---------|
| `count` | 行数 |
| `min` | 最小值 |
| `max` | 最大值 |
| `mean` | 算术平均 |
| `std` | 标准差 |
| `p10` | 10 分位 |
| `p50` | 中位数 |
| `p90` | 90 分位 |

## 布尔操作符自动重写

```python
def _rewrite_bool_ops(expr: str) -> str:
    """
    将 Python 布尔操作符重写为 numpy 元素级操作符。
    
    Python 短路逻辑调用 bool(array) 会报 ambiguity 错误，
    所以必须用 &amp;&amp;/||/~~。
    
    重写规则:
    - " and " → " & "
    - " or "  → " | "
    - " not " → " ~ "
    """
```

## 输出格式

```python
{
    "field": "dist_y + 0.25 * obj_width",
    "table": "radar_objects",
    "row_count": 12345,
    "group_by": "side",
    "filter": "in_window & (dist_x < 0)",
    "groups": {
        "left": {
            "count": 7000,
            "min": -4.26,
            "max": 4.22,
            "mean": 0.03,
            "p10": -4.15,
            "p50": 0.01,
            "p90": 4.08,
            "std": 2.15,
        },
        "right": { ... }
    },
    "global": { ... }
}
```

## 性能

- SQL 查询: < 50ms (SQLite in-memory)
- numpy 向量化: < 10ms/百万行
- asteval 求值: < 20ms/表达式
- 总查询: < 100ms

## 安全

- 不使用 Python eval()
- asteval minimal 模式: 只允许算术/比较/布尔/函数调用
- 符号表严格限制为已知列 + numpy 白名单函数
- 最大行数限制: 500,000 (安全保险丝)
