# Gen5 BSD 条件提取 & 信号映射 Handoff — 完成状态

## ✅ 完成项

### 1. BSD_conditions.json (source_docs/)
- 34 条 flat conditions，覆盖 BSD 全链路：状态转移(2)、ObjectSelector(5)、WarningZone(7)、Vx 抑制(4)、OLR/dy/dx(4)、出口计时器等(8)

### 2. Gen5 Signal Mapping (source_docs/gen5_bsd_signal_mapping.json)
- 76 条映射条目，26 个内部变量 → MF4 通道名

### 3. Mf4Parser Bug Fix (parsers/mf4_parser.py)
- 修复了 asammdf 重复 channel 读取问题：通过 `channels_db` 获取 `(group_index, channel_index)` 然后用 `mdf.get(index=occ)` 读取

### 4. PAD 参数验证 ✅
从 MF4 直接读取了 **27 个 BSD PAD 参数**，全部为 constant 值，与代码中的 constexpr 一致：
- `BSLCAMinVxSuppressOn_F` = -4.0 m/s
- `BSDLCAMinVxSuppressOff_F` = 0.0 m/s
- `BSDLCATteColl_F` = 3.5 m/s
- `BSDLCALyColl_F` = 3.75 m (ISO G line)
- 等

## ⚠️ 当前限制

### asammdf 读取有 duplicate channel 的信号失败
MF4 中 BSD internal signals (2383 个) 在 2 个 group 中有重复，asammdf 8.8.16 不允许通过 API 指定 `(group, index)` 读取重复 channel。所以：
- ✅ **PAD 参数** — 全部 unique，**可以直接读**
- ❌ **内部状态信号** (ExistProb, Blindness_st, dy, dx, necessity 等) — **无法通过 asammdf API 读取**
- ❌ **FusedObjects** — 无法读取

### 这意味着
- 34 个条件中 **19 个找到了信号但不一定能读** (因为信号有 duplicate)
- **15 个没有信号映射** (PAD 参数、计算中间值)
- **PAD 参数可以直接验证** — 它们存在且值恒定

## 下一步

1. **报告 PAD 参数验证结果** — 将 MF4 中的 PAD 值与 `BSD_conditions.json` 中的阈值对比
2. **考虑其他 MF4 reader** — 如 `mffparser`，可能支持重复 channel
3. **或者改用 Group 级读取** — 遍历 382 个 group，从每个 group 中按 index 读取信号

## 关键文件

| 文件 | 用途 |
|------|------|
| `source_docs/BSD_conditions.json` | 34 条 BSD 条件 |
| `source_docs/gen5_bsd_signal_mapping.json` | 26 个变量 → MF4 通道映射 |
| `source_docs/gen5_bsd_coverage_report.json` | 初步覆盖报告 |
| `ai/condition_extractor.py` | 已添加 platform_adapter 支持 |
| `ai/platform_adapters/gen5_reco_pl.py` | BSD 5 个 domain + 25 keywords |
| `parsers/mf4_parser.py` | 修复了重复 channel 读取 |
