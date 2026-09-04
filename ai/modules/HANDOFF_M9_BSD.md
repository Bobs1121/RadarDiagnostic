# M9 BSD Data Bridge — Handoff Checklist

> 模块集成完成后，由后续开发者/维护者按此清单验证和跟进。

---

## 已完成 ✅

- [x] `ai/modules/bsd_data_bridge.py` 创建 — M9 BSD 模块完整实现
- [x] `ai/modules/__init__.py` 追加 M9 注册
- [x] `ai/modules/AGENTS.md` 创建 — M9 详细文档
- [x] `AGENTS.md` 更新 — 根目录跨模块依赖速查 + CLI 运行模式表
- [x] 模块 CLI 注册验证通过
- [x] 模块可从 `MODULE_REGISTRY` 发现

---

## 待验证 ⚠️

按依赖从强到弱排序，必须逐一验证：

### P0 — 模块功能验证

- [ ] `python -c "from ai.modules import MODULE_REGISTRY; print('bsd-data-bridge' in MODULE_REGISTRY)"` → 输出 `True`
- [ ] `python cli.py bsd-data-bridge --help` → 输出帮助文本
- [ ] `python cli.py bsd-data-bridge --mode summary --mf4-path X.MF4` → 有 MF4 时正常返回 summary
- [ ] `python cli.py bsd-data-bridge --mode validate --mf4-path X.MF4` → 有全部依赖时正常返回验证报告
- [ ] 无 `BSD_conditions.json` 时 `validate` 正确返回 `ModuleResult.fail`
- [ ] 无 `asammdf` 时正确返回 "asammdf is not installed" 失败消息

### P1 — 数据文件验证

- [ ] `source_docs/BSD_conditions.json` 存在且格式正确
   - 结构：`{"1": {"step_description": "...", "conditions": [...]}, "2": {...}}`
   - 每个 condition 有 `id`, `description`, `type`, `signal_name`, `threshold` 等
- [ ] `source_docs/gen5_bsd_signal_mapping.json` 存在且格式正确
   - 结构：`{"mappings": [{"internal_var": "...", "can_signal": "..."}, ...]}`

### P2 — 与项目其他组件的集成验证

- [ ] auto_dream 可从 Phase 0 调用 M9（当前未集成，需后续开发）
- [ ] `condition_extractor.ConditionExtractor.extract("BSD", ...)` 可产出 `BSD_conditions.json`
- [ ] BSD 源码路径 `BYD_OVS_CB` 是否在 `config.yaml` 中正确注册
- [ ] freshness 系统是否将 M9 产物纳入版本管理

### P3 — 回归测试

- [ ] `tests/test_bsd_data_bridge_smoke.py` — 冒烟测试通过
- [ ] M9 不破坏其他模块的导入：`import ai.modules` 无异常
- [ ] CLI dispatch 不干扰传统模式：`python cli.py --dream` 正常
- [ ] 已有测试（如 `test_temporal_pattern_engine`）不被破坏

---

## 已知约束 / TODO 📋

| 编号 | 描述 | 优先级 | 影响面 |
|------|------|--------|--------|
| T1 | M9 当前不被 orchestrator 调用 | medium | 诊断管线暂不验证 BSD |
| T2 | M9 当前不被 auto_dream 调用 | medium | M9 输出不参与记忆整合 |
| T3 | `BSD_conditions.json` 需手动准备或从 ConditionExtractor 生成 | high | 无此文件 validate 模式失败 |
| T4 | 信号关键词匹配是启发式算法，可能误匹配/漏匹配 | low | 需人工复核关键条件验证结果 |
| T5 | PAD 默认值可能不准确，需从 `gen5_bsd_signal_mapping.json` 覆盖 | medium | 建议 validate 前确认映射文件最新 |
| T6 | M9 不缓存 MF4 解析结果，每次 validate 全量读取 | low | 大 MF4 文件（>500MB）可能较慢 |
| T7 | `BSD_SIGNAL_LIST` 的 32 个信号可能不全（需定期从 BSD 代码复核） | medium | 建议每季度从代码仓库更新信号清单 |

---

## 开发规范摘要（新增模块时）

以下规则适用于 `ai/modules/` 下所有模块的创建/修改：

1. **继承 `BaseModule`** — 必须实现 `name`, `description`, `run()`, `register_cli()`, `from_cli_args()`
2. **返回 `ModuleResult`** — `run()` 的唯一返回值，不抛异常
3. **`__future__` 注解** — `from __future__ import annotations`
4. **模块级日志** — `log = logging.getLogger(__name__)`
5. **依赖保护** — 可选依赖通过 `_is_*_available()` 检查或在 `__init__.py` try/except
6. **CLI 注册** — `MODULE_REGISTRY[name] = cls` + `__all__` 追加
7. **自包含** — 不依赖其他模块的输出产物
8. **文档同步** — 修改模块文件时同步更新 `ai/modules/AGENTS.md`
9. **根目录 AGENTS.md** — 涉及跨模块交互时更新 "跨模块依赖速查表"

---

## 后续路线图

### Q1 （短期）

1. 确保 `source_docs/BSD_conditions.json` 和 `gen5_bsd_signal_mapping.json` 存在
2. 编写 `tests/test_bsd_data_bridge_smoke.py`
3. 验证完整端到端：MF4 + BSD_conditions → validate 报告

### Q2 （中期）

4. auto_dream Phase 0 集成 M9：`_run_bsd_validation()` 步骤
5. ConditionExtractor 支持 BSD 域（BYD_OVS_CB 源码）
6. orchestrator 诊断管线 Phase 5 调用 M9

### Q3 （长期）

7. 支持多 BSD 变体（不同车型/供应商配置）
8. M9 产物纳入 knowledge_manifest 新鲜度管理
9. 条件验证结果的时序存储与趋势分析

---

## 联系人

| 阶段 | 人员 | 说明 |
|------|------|------|
| 模块设计/实现 | AI Pair | M9 BSD Data Bridge 模块 |
| 模块集成 | TBD | auto_dream / orchestrator 集成 |
| 数据文件维护 | TBD | BSD_conditions.json, gen5_bsd_signal_mapping.json |
| M9 代码所有者 | TBD | 后续指定 |
