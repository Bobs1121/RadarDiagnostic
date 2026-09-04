# CR60 / Gen6 AI 诊断平台架构复盘 handoff

版本：`handoff.v1`  
日期：2026-08-30  
状态：`design-baseline-updated`  
范围：文档、架构和产品流程；本轮未修改算法/arbe/runtime 代码

## 1. 用户目标

用户需要的是 AI 参与的数据分析、代码查询、仿真、Debug 和问题根因定位平台。系统不能
隐藏中间调查过程后直接给最终代码方案；每一步的线索、条件、冲突、缺口和候选原因都要
可见，帮助用户自己判断和接手 debug。平台还要兼顾效率、准确性和不同 Gen6 项目适配。

## 2. 总体判断

当前 Pi + 原子工具 + 独立 cr60-debug-harness + arbe adapter 的方向合理，不需要重构为
单体仓库。当前主要问题不是缺工具，而是缺少：

- 持久化 AnalysisRun/AnalysisStep；
- Claim/Gap/Conflict/Hypothesis/DebugExperiment；
- 事件级代码调查链；
- public runtime→GDB→人工 VSCode 的连续协同；
- Live Workbench；
- Gen6 ProjectCapabilityManifest；
- capability pack 和效率指标。

本轮确定：最终 HTML 是 AnalysisRun snapshot，不再是唯一主流程。

## 3. arbe 当前源码调研

只读目标：

```text
host: 10.190.171.44
arbe: /home/hoz2wx/CR60LIGHT/cr60_light_arbe
```

重新确认：

1. BagReader 将 radar0..4 LGU 按 bag time 稳定排序；
2. event/scene 两种选择，辅助 topic 有 latest-before/closest-within 和时间阈值；
3. 每 radar 最多一帧在途，ACK 后才能继续，bag 末尾等待全部完成；
4. `PlaySingleFrame status=0/1` 是接收/完成 ACK，不是外部 seek API；
5. `warning_status_with_frame` 携带 radar/frame/warning；
6. `radar_info` 携带 ego speed/yaw、detections、frame、周期等；
7. `objectlist_<radar>` 携带位置、尺寸、yaw、速度、TTC/DDCI 和所有 object warning flag；
8. GUI Object Table 区分 RAW_SGU/ALGO 并逐目标展示中间属性；
9. 当前 objectlist 无 algorithm frameID，header stamp 是发布时 `ros::Time::now()`，不能
   只按时间邻近宣称同帧。

结论：优先复用 BagReader 和 public runtime；精确帧缺口用关联等级或默认关闭的
`runtime_snapshot_with_frame` bridge；GDB 只补局部变量、临时状态、栈和 CAN Tx。

## 4. 文档变更

### 新增

- `CR60_PI_UNIFIED_ARCHITECTURE_REVIEW_2026-08-30.md`

### 更新

- PRD v2.2：过程可见、人机协同、Analysis Trail、Hypothesis Board、capability pack；
- DDD：新增领域对象和 `US-015..US-020`；
- 系统设计 v2：四平面、Ledger、public snapshot、Gen6 manifest、效率/准确性；
- 模块设计 v2：Ledger/EventCodePath/Hypothesis/PublicRuntime/Workbench；
- 软件设计 v2：run/step/claim/hypothesis/experiment/manifest 契约草案；
- Sprint v2：S1A/S1B/S2A/S2B/S3A/S3B；
- ADR：新增 ADR-017..ADR-021；
- arbe 复用调研 v2：当前源码刷新；
- 调研报告：记录本轮架构结论；
- 用户流程问卷：新增 P1 Workbench 产品问题；
- 文档索引：更新阅读顺序和状态。

## 5. 推荐下一开发切片

第一优先不是继续添加更多功能工具，而是 `S1A Analysis Ledger MVP`：

```text
analysis-run.v1
analysis-step.v1
claim.v1
hypothesis.v1
debug-experiment.v1
```

用已有 CRGVI-1829 intake/precheck/code/runtime artifact 重建一个完整 run，不重解 bag、不
重跑 GDB。HTML 增加 Analysis Trail，验证“中间过程本身能产生用户价值”。

第二优先是 `EventCodePath`，把 event 对应的 output→feature→situation→target→input 代码
链、条件、参数、runtime gap、断点和 watch group 产品化。

第三优先是 `PublicRuntimeCollector`，复用 arbe 逐帧 public 字段并评估最小 stamped bridge。

## 6. 当前边界

- 本轮没有实现 Ledger/Workbench schema 代码；文档状态为 specified/proposed；
- 没有执行远程写、checkout、编译、start 或 GDB；
- objectlist public 字段丰富，但精确 frame 绑定仍未解决；
- formal attach、CAN Tx 和 point-cloud runtime 仍为后续现场验收；
- Gen6 manifest 需至少两个实际项目才能从设计升级为 accepted。

## 7. 需要真实用户确认

1. 默认自动跑到 Debug-ready 再停，还是每个阶段都停？当前建议自动到 Debug-ready；
2. 人工 VSCode 结果首版用页面粘贴/表单回填是否可接受；
3. Gen6 页面采用统一三栏骨架 + 功能/项目专属 panel 是否符合预期；
4. 第一阶段是否需要多人批注/接力同一个 AnalysisRun；
5. 最终根因是否必须由算法工程师/问题负责人确认。当前建议必须人工确认。

