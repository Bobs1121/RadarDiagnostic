# CR60 Pi Unified Platform Handoff 模板

版本：`handoff.v1`

> Handoff 是 docu dev 的阶段交接物。没有 handoff，下一阶段不能假设上一阶段已经完成或事实仍然新鲜。

## 1. 基本信息

```text
handoff_id:
run_id:
date:
owner:
source_task:
target_task:
status: complete | partial | blocked
```

## 2. 用户目标

```text
用户问题：
期望输出：
已确认范围：
不在范围：
```

## 3. 输入身份

```text
project_id:
variant_id:
server:
arbe_workspace:
outer_arbe_branch/commit:
algo_source_branch/commit:
coem:
vehicle:
data_paths:
data_software_version:
data_binding_source:
data_fingerprint:
source_fingerprint:
binary_fingerprint:
```

所有不确定项必须写成 `unknown`/`blocked_missing_input`，不能留空后让下一阶段自行猜测。

## 4. 已完成能力

```text
data_prepare:
source_context:
cr60_sprint1_precheck:
geometry_contract:
arbe_preflight:
arbe_build:
runtime_debug:
report:
pi_explain:
```

## 5. Artifact 清单

| artifact | schema | path | sha256 | producer | status |
|---|---|---|---|---|---|
| intake | `cr60-analysis-intake.v1` |  |  |  |  |
| source | `analysis-context.v1` |  |  |  |  |
| static | `diagnosis-bundle.v1` |  |  |  |  |
| viewer | `viewer-model.v1` |  |  |  |  |
| runtime plan | `runtime-debug-plan.v1` |  |  |  |  |
| runtime trace | `runtime-trace.v1` |  |  |  |  |
| report | `report.html` |  |  |  |  |

## 6. 证据和结论

```text
observed facts:
derived facts:
runtime facts:
inferences:
blocked gaps:
conflicts:
```

## 7. Runtime 状态

```text
mode: sgu_injection | point_cloud
hilmodel:
sgu_frame_warmup: 3-5 frameID
point_cloud_warmup_frames:
feature_state_warmup_frames:
target_frame:
obj_id:
raw_sgu_index:
algorithm_index:
gdb_status:
replay_status:
teardown_status:
perturbation:
workspace_update_detected:
workspace_lock:
```

## 8. 未完成和风险

- 未完成：
- 失败命令：
- 缺少权限：
- 缺少输入：
- source/binary mismatch：
- 下一步不能自动做的动作：

## 9. 下一阶段动作

| 顺序 | 工具/人工动作 | 输入 artifact | 预期输出 | 是否需要确认 |
|---:|---|---|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |

## 10. 用户确认记录

```text
确认人：
确认时间：
确认内容：
允许的副作用：
不允许的副作用：
```
