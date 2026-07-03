# tools/ 辅助工具说明

| 文件 | 用途 |
|------|------|
| `render_report_from_md.py` | 从已有 `report.md` 渲染 HTML 报告 |
| `run_tpe_smoke.py` | 对真实案例运行无 LLM 的 TPE 冒烟 |
| `measure_prewarm_timing.py` | Phase 16.1：重复调用 `_run_prewarm()`，输出 prewarm 缓存命中计时 JSON |
| `run_harness_gate.py` | Phase 16.4：运行 Harness 聚合回归 gate，生成 JSON 并用 exit code 表示是否阻塞 |

## 常用命令

```bash
python tools/measure_prewarm_timing.py --variant gen6/gwm_b26 --runs 2
python tools/run_harness_gate.py --allow-known-edge
```

`run_harness_gate.py` 默认运行全部 golden-truth 案例；`--allow-known-edge` 会允许已知边缘案例 `sc6hrcta001` 失败但仍返回 0。输出 JSON 默认写入 `reports/harness_gate_<timestamp>.json`。
