# source_docs/ 文件 Schema 与缓存规则

> 用于「需求 ↔ 实现」review。AI 编辑涉及 source_docs/ 文件的模块时参考本文档。

---

## 文件清单与生成方式

| 文件 | 生成模块 | 生成方式 | 失效条件 |
|------|---------|---------|---------|
| `{FUNC}.md` (×8) | `code_learner.ensure_overview_docs` | AI 生成 | 源码片段 hash 变更 (`.overview_hashes.json`) |
| `signal_chain.md` | `signal_mapper.build_signal_chain_summary` | 确定性 | 随 signal_mapping.json 重建 |
| `signal_mapping.json` | `signal_mapper.extract_signal_mapping` | 确定性 (正则) | RteComMapping.c SHA256 前 16 位变更 |
| `output_mapping.json` | `signal_mapper.extract_output_signal_mapping` | 确定性 (正则) | 同上 source_hash |
| `variable_chains.json` | `signal_mapper.trace_variable_chains` | 确定性 (正则) | **无增量缓存**，每次调用重写 |
| `{FUNC}_conditions.json` (×8) | `condition_extractor.extract` | AI 提取 | 源码文件 mtime 比缓存 mtime 新 |
| `code_patterns.json` | `pattern_extractor.extract_all` | 确定性 (正则) | 源码目录 hash 变更 |
| `parameters.json` | `parameter_analyzer.scan_parameters` | 确定性 (正则) | 源码 SHA1 变更 |
| `variables.json` | AI 生成 | AI | 手动删除后重新生成 |
| `radar_knowledge.json` | 手工维护 | 手工 | — |
| `.overview_hashes.json` | `code_learner` | 确定性 | 随 ensure_overview_docs 更新 |

---

## signal_mapping.json

```
{
  "source_hash": "16位hex",
  "source_file": "相对路径",
  "mapping_count": int,
  "mappings": [
    {
      "can_signal": str,
      "internal_var": str,
      "internal_full_path": str,
      "transform": str,
      "scaling": str,
      "data_type": "bool|float|uint8",
      "direction": "read"
    }
  ],
  "internal_to_can": { "短名": ["CAN名"] },
  "can_to_internal": { "CAN名": ["短名"] },
  "fullpath_to_can": { "全路径": ["CAN名"] }
}
```

## output_mapping.json

```
{
  "source_hash": "16位hex",
  "mapping_count": int,
  "mappings": [
    { "can_signal": str, "expression": str, "direction": "write" }
  ],
  "signal_to_expr": { "CAN名": ["表达式"] }
}
```

## variable_chains.json

```
{
  "struct_aliases": { "g_前缀": "RTE前缀" },
  "alias_details": { ... },
  "ambiguous": { ... },
  "raw_copies": [
    { "global_var", "param_name", "param_type", "function", "copy_type", "source_file" }
  ],
  "rte_write_prefixes": [...],
  "scanned_files": [...]
}
```

## {FUNC}_conditions.json

```
{
  "function": str,
  "system_state": {
    "state_values": { "状态码": "名称" },
    "transitions": [
      { "from", "to", "conditions": [{ "condition", "variable", "threshold", "source" }] }
    ]
  },
  "target_filter": { ... },
  "detect_enable": { ... },
  "ego_speed_ranges": { "active"/"deactive"/"detect": { "low", "high", "unit" } },
  "target_speed_ranges": { ... },
  "external_suppression": [
    {
      "source_system", "condition", "variable", "can_signal",
      "suppression_trigger", "normal_value", "effect", "source",
      "_can_resolved": bool
    }
  ],
  "other_conditions": [{ "category", "condition", "variable", "threshold" }]
}
```

**极性字段**: `suppression_trigger` = 抑制发生时条件为真的写法; `normal_value` = 不抑制时的典型值。消费侧在 `orchestrator._evaluate_threshold` 中做数据占比判断。

## code_patterns.json

```
{
  "source_hash": str,
  "pattern_type_catalogue": { "类型": "说明" },
  "patterns": [
    {
      "pattern_type", "file", "line_start", "line_end", "function",
      "trigger_condition", "trigger_variables", "consequence_variables",
      "adas_function", "snippet", "notes"
    }
  ]
}
```

## parameters.json

```
{
  "source_hash": str,
  "count": int,
  "parameters": [
    { "name", "func", "category", "value", "value_raw", "unit_hint", "file", "line", "comment" }
  ]
}
```

## .overview_hashes.json

各功能名 → 16 字符 hex hash，加 `_updated_at` 时间戳。用于与当前源码片段 hash 比对决定是否重生成对应 `FUNC.md`。

## radar_knowledge.json

手工维护: `can_id_to_radar`, `topic_to_radar`, `warning_status_raw_byte_map`, `a2l_to_egoCarInfo`, `wfAutosarData_structure`, `adas_functions` (rear/front + system_state_enum)。

---

## 缓存失效汇总

| 机制 | 使用模块 | 说明 |
|------|---------|------|
| SHA256 前 16 位 | signal_mapping, output_mapping | 源文件全文 hash |
| SHA1 | parameters | 多文件拼接 hash |
| 源码目录 hash | code_patterns | 目标文件集 hash |
| 片段 hash | overview (.overview_hashes.json) | 按功能关键词提取片段后 hash |
| mtime 比较 | conditions | 任一域内源码文件 mtime > 缓存文件 mtime |
| 无缓存 | variable_chains | 每次调用 trace_variable_chains 都重写 |

## Review 关注点

- signal_mapping 缓存命中时若 `signal_chain.md` 不存在会补建
- conditions 用 mtime 而非内容 hash，触摸文件即可触发重新提取 (AI 漂移风险)
- variable_chains 无增量缓存，频繁调用浪费 I/O
- extract_signal_mapping 源文件缺失时返回结构与成功路径字段不一致
