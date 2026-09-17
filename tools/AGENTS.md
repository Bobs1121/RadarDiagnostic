# tools/ 辅助工具说明

| 文件 | 用途 |
|------|------|
| `check_ddd.py` | 检查唯一 GEN6 文档链接、archive hash、任务 DAG、M01～M12/G6-AC 覆盖及状态证据；documents_valid 不是产品验收；支持 `--root`/`--output` |
| `render_report_from_md.py` | 从已有 `report.md` 渲染 HTML 报告 |
| `run_tpe_smoke.py` | 对真实案例运行无 LLM 的 TPE 冒烟 |
| `run_agent_loop_smoke.py` | PR5：用内存 FrameStore / requirement set / fake CodeGraph 组合真实 AgentLoop tools，输出 JSON 并以 exit code 表示 smoke 是否完成 |
| `measure_prewarm_timing.py` | Phase 16.1：重复调用 `_run_prewarm()`，输出 prewarm 缓存命中计时 JSON；把 active variant 的 `key_source_files` 绑定给 RTE variable-chain scan；可用 `--source-docs-dir` 隔离首建/复用测量，默认仍用 variant cache |
| `run_harness_gate.py` | Phase 16.4：运行 Harness 聚合回归 gate，生成 JSON 并用 exit code 表示是否阻塞 |
| `doctor.py` | 本地/内网交付前体检：Python、锁定依赖、入口文件和 Pi capability catalog；只读；`--catalog-timeout-sec` 支持 clean venv 冷启动 |
| `release_gate.py` | 默认读取当前 G6 `docs/technical/release_acceptance.v1.json`；required 项必须有命令/证据，G6 须覆盖 required_test_levels 的 hash-bound evidence；plan-only 保持 blocked |
| `release_smoke.py` | 历史 M0–M4 局部契约检查；M0 明确读取归档清单，不宣称当前 G6 通过；无远程副作用，不嵌套 pytest |
| `decode_lgu_output.py` | 只读从 `wfAutosarData.outputData` 解码源码绑定的 `PERInfoOutStruct.dotTrans/objTrans`，并提供标准 `PointCloud2` 字段解码，生成 point/output artifact；使用显式固定前缀和混合 signed/unsigned `dotOutStrunct` profile。source header 已验证不代表录制布局已兼容；只有当前 source hash、精确 BAG SHA-256、录制版本和带 hash 的兼容性证据一致时才标 `layout_verified`，否则点记录带 warning、BAG 结果 partial；不启动 ROS、不修改远端 workspace。ROS1 BAG adapter 在 `engines.point_cloud_replay` 中惰性调用该 decoder |

## arbe 资产（V4 · sim-verify / arbe-replay 输入参考）

> 从 Linux 服务器 10.190.171.44（工作区 `~/CR60LIGHT/cr60_light_arbe/`）拉取的 arbe 工具链资产，供 `sim-verify` / `arbe-replay` 能力模块解析与对接。完整工具链操作见 `FCTB_Batch_Replay_Operation_Guide.md`，skill `cr60light-arbe-build` 覆盖切分支/编译/启动流程。

| 文件 | 用途 |
|------|------|
| `bag_csv_kpi_framesync.py` / `bag_csv_kpi_batch.py` | ROS bag KPI 统计（需 source `/opt/ros/noetic/setup.bash`）→ `*_adas_kpi_summary*.csv/xlsx` |
| `find_triggered_warning_bags.py` | 遍历 bag 目录，标出 warning 非全零的 bag |
| `FCTB_Batch_Replay_Operation_Guide.md` | bag-only 批量回灌模式操作说明；产出 `_algo_warning_trace.csv`（event_sec, radar_id, w1..w15，w14=LeftFctb, w15=RightFctb）+ `batch_fctb_trigger_report.csv` |
| `src/common_can_signal_publisher/` | bag 内 `/front/signals`、`/rear/signals` 的发布者（DBC 生成信号字典 `generated_signal_map.py` + `generate_public_can_msg.py`）；**bag 回放无真实 CAN 时输出占位值（signal_valid=0）** |
| `src/arbe_phoenix_radar_driver-master/arbe_gui/src/arbe_visualization_engine/` | 离线重跑算法 → `warning_status`（16 数组） |
| `src/rviz_bag_2e44lc_AtoSar_LGU_Folder/` | bag 回放插件（my_rviz_plugin + bag_reader） |

**关键数据准确性提醒**：bag 里的 CAN 输出信号（front/rear signals）在**回放无真实 CAN**时是无效占位数据（恒定值 + signal_valid=0），不得当真实证据；V4 数据统一层（DataProvider/DataStore）负责标记 `signal_valid`。

## 常用命令

```bash
python tools/run_agent_loop_smoke.py
python tools/measure_prewarm_timing.py --variant gen6/gwm_b26 --runs 2
python tools/run_harness_gate.py --allow-known-edge
```

`run_harness_gate.py` 默认运行全部 golden-truth 案例；`--allow-known-edge` 会允许已知边缘案例 `sc6hrcta001` 失败但仍返回 0。输出 JSON 默认写入 `reports/harness_gate_<timestamp>.json`。

`run_agent_loop_smoke.py` 不解析真实录制文件，也不调用 LLM；它默认打印 `ModuleResult.to_dict()` JSON，并且仅当 `ModuleResult.ok=True` 且 `state.status=="completed"` 时返回 0。
