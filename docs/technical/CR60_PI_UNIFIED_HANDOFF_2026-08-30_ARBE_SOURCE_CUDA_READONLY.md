# CR60 Pi Unified Platform：上游 source/CUDA 只读绑定 handoff

版本：`handoff.v1`  
日期：2026-08-30  
阶段：S1 前置绑定增量  
状态：`partially-verified`

## 1. 本阶段目标

按照 DDD 基线 `US-002/US-012/US-013`，把上游
`bosch-data-transfert` 与 `cr60light-arbe-build` 流程中最容易造成版本漂移的两步，
拆成 Pi 可调用、可测试、无副作用的原子能力：

1. 从当前 `algo_source` 读取 HEAD、branch/detached、exact tag、dirty 和目标 ref 存在性；
2. 从当前 source 的车型 `08_CustData` 读取 CUDA 候选，并核对 arbe 当前 launch YAML；
3. 在数据传输前验证 Linux 可访问路径、文件身份和目标目录（如已存在）；
4. 给后续 checkout、配置写入、编译和启动提供带 provenance 的输入，而不是直接执行写操作。

## 2. 交付物

| 层 | 交付 |
|---|---|
| Engine | `engines/arbe/source.py`、`engines/arbe/cuda.py` |
| Pi modules | `ai/modules/arbe_source_resolve.py`、`ai/modules/arbe_cuda_resolve.py` |
| Contract | `contracts/arbe-source-resolution.v1.schema.json`、`contracts/arbe-cuda-resolution.v1.schema.json` |
| Patch plan | `engines/arbe/patch_plan.py`、`ai/modules/arbe_patch_plan.py`、`contracts/arbe-patch-plan.v1.schema.json` |
| Data verify | `engines/arbe/data_prep.py`、`ai/modules/cr60_data_prep_verify.py`、`contracts/cr60-data-prep-verification.v1.schema.json` |
| Data transfer adapter | `engines/arbe/transfer.py`、`ai/modules/cr60_data_transfer.py`、`contracts/cr60-data-transfer-session.v1.schema.json` |
| Pi registration | `.pi/extensions/radar-capabilities.ts`，由 catalog generator 自动生成 |
| Tests | `tests/test_arbe_source_resolve.py`、`tests/test_arbe_cuda_resolve.py` |

## 3. 输入与输出边界

### 3.1 `arbe-source-resolve`

输入可以来自 `cr60-analysis-intake.v1`，也可以显式提供 `algo_source_root`。
版本到 ref 的转换不是代码内置规则；只有调用方提供
`software_version + ref_prefix + version_suffix_strip` 时才生成派生 ref。
显式 `requested_ref` 与派生 ref 冲突时直接 `blocked`。

输出 `arbe-source-resolution.v1`，保存：

- 当前 `HEAD`、branch 或 `DETACHED`、exact tag、dirty 状态；
- effective ref、ref 来源（explicit 或 configured mapping）；
- local branch/tag 和可选 `git ls-remote` 结果；
- `source_resolution_command`、服务器和 workspace provenance；
- `partial`（例如 source dirty）、`needs_confirmation`、`blocked` 和 `failed` 原因。

它不执行 `git fetch`、`git checkout` 或任何 source 写入。

### 3.2 `arbe-cuda-resolve`

输入可以来自 intake/preflight，或显式提供 `arbe_root`、`algo_source_root`、`vehicle` 和
期望 sheet。它只扫描：

```text
<algo_source_root>/coem/<vehicle>/tools/container_input/08_CustData/CUDA_*.xlsx
```

每个候选保留远程 mtime、size、sha256、完整路径和来源；选择规则为“mtime 最大，路径
作为稳定 tie-break”。同时读取当前：

```text
<arbe_root>/src/arbe_phoenix_radar_driver-master/arbe_gui/Config/launch_config_4radars.yaml
```

的 `xlsx_path`、`xlsx_sheet`、`type`，返回 `configuration.alignment`：
`aligned`、`needs_update` 或 `not_available`。

它不执行 `cp`、YAML 写入、`catkin_make`、`bash start` 或 ROS 操作。

## 4. 真实现场验证

验证时间：2026-08-30（本机 `radarAnalyze` 调用 SSH，只读命令）。

目标：

```text
host: 10.190.171.44
user: hoz2wx
arbe: /home/hoz2wx/CR60LIGHT/cr60_light_arbe
algo_source: /home/hoz2wx/CR60LIGHT/cr60_light_arbe/src/algo_source
```

### 4.1 source

artifact：[arbe_source_resolution_current_20260830.json](../../outputs/arbe_source_resolution_current_20260830.json)

- 当前 HEAD：`a81b08a38f316a3d25bfcbcad6dcfc822d24b990`；
- 当前状态：`DETACHED`、exact tag=`BYD_UKE_BL03RC02.7`、`dirty=yes`；
- 由显式配置 `BL03RC02.7_S` + `BYD_UKE_` + `_S` 派生的 ref 为
  `BYD_UKE_BL03RC02.7`；
- local tag 和 remote tag 都存在，remote 返回同一 HEAD；
- 因 source dirty，整体状态为 `partial`，工具没有尝试 checkout。

### 4.2 CUDA/config

artifact：[arbe_cuda_resolution_current_20260830.json](../../outputs/arbe_cuda_resolution_current_20260830.json)

- `coem/BYD_UKE/tools/container_input/08_CustData` 存在；
- 当前扫描到一个候选：`CUDA_BYD_UKE_Bundle_V2.0.xlsx`；
- size：`52295` bytes；
- SHA-256：`a555d8a5a86e7a26c6671f9eb8838d6f4e360d803219a7b6fad71360ea315856`；
- YAML 第 53/54/75 行分别为该 xlsx、`03_QZH`、`BYD_UKE`；
- `configuration.alignment=aligned`，整体状态 `ready`。

### 4.3 仿真适配检查

artifact：[arbe_patch_plan_current_20260830_v4.json](../../outputs/arbe_patch_plan_current_20260830_v4.json)

- outer/algo 都是 `dirty=yes`，因此不能把当前工作区当作干净的目标构建上下文；
- `paraDefine.h` 中 `BUILDMODEL=2`、`HILMODEL=2` 命中，且记录了文件 SHA-256 和 diff；
- `visualization_node.cpp` 中发现 `PostProcessMainTI` 和局部 `taskTime`，但真实调用
  尾部是 `3,3`，required `taskTime, taskTime` 检查未命中；
- 当前 `PF_BUILD_FUNTEST_SGU_INJECTION` 只有 `#ifdef` 引用，没有 `#define` 命中，工具不把
  引用误报为“已启用”；
- 总体状态为 `needs_action`，这只是检查结果，不是自动补丁建议；没有任何远程写操作。

### 4.4 数据路径验证

artifact：[cr60_data_prep_verify_CRGVI1829_20260830.json](../../outputs/cr60_data_prep_verify_CRGVI1829_20260830.json)

对用户给出的 bag 执行了远程只读校验：

```text
/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829/corner_radar_net_2026-07-19-11-56-15_11.bag
size=1087066183 bytes
sha256=241e732ada70dd809894d3bed5f3f6603358c0ea5cd45f6204ab11628d11e18c
status=ready
```

没有设置 destination，因此结果只证明当前 Linux source file 可达且 hash 已记录，
不证明一次数据传输已经发生或目标目录与源一致。

随后对目录 `/home/hoz2wx/CR60LIGHT/data/qzh/CRGVI-1829` 走了目录扫描分支，artifact
为 [cr60_data_prep_verify_CRGVI1829_folder_20260830.json](../../outputs/cr60_data_prep_verify_CRGVI1829_folder_20260830.json)。目录中发现 5 个 `.bag`，
全部完成 size/mtime/SHA-256 读取并返回 `status=ready`；目录扫描仍未检查目标目录，
也未执行传输。

### 4.5 上游传输执行边界

新增 `cr60-data-transfer` 作为受审批的上游 adapter。它不实现 `cp/rsync`，只接受显式
远端 `script_path`、`input_path`、`destination_root`、`source_type`，生成调用
`bosch-data-transfert` 的命令。未批准时实测/单测均保证 runner 不被调用；批准后的返回码、
stdout、stderr、timeout 会写入 `cr60-data-transfer-session.v1`。当前现场没有执行该写
操作，因为用户尚未指定远端传输脚本部署路径和要写入的目标目录。

## 5. 测试证据

```text
python -m pytest -q tests/test_arbe_source_resolve.py tests/test_arbe_cuda_resolve.py
15 passed
python -m pytest -q tests/test_arbe_patch_plan.py
7 passed
python -m pytest -q tests/test_cr60_data_prep_verify.py
8 passed
python -m pytest -q tests/test_cr60_data_transfer.py
5 passed
python scripts/gen_pi_extension.py
42 Pi capabilities (36 modules + 6 tools)
python -m pytest -q
651 passed, 1 skipped, 2 xfailed, 10 warnings
```

测试覆盖计划态不触发 runner、正常解析、缺输入、路径/ref 安全门、显式/派生 ref 冲突、
source dirty、blocked intake、模块注册、CLI wiring 和 artifact 写入。

## 6. 当前未完成与下一步

本 handoff 没有完成正式工作区写入链，不能据此声称以下动作已完成：

- 数据从源端传输到 Linux 的实际执行与 checksum 闭环；
- 目标 ref checkout；
- CUDA 文件复制及 YAML 更新；
- 仿真补丁检查/应用；
- `catkin_make`、`bash start` 和正式 PID attach。

下一步应继续按 DDD 顺序实现：

1. `data-prep plan/verify`：把上游清单/UNC/本地路径转换为远程数据校验结果；
2. `arbe-source-apply`、`arbe-config-apply`：同一 source fingerprint + approval + 可回退审计；
3. 处理当前 required patch check，先由用户确认维护者的 dirty diff 归属，再考虑应用最小补丁；
4. 用用户确认后的隔离工作区完成 build/start，再进入 runtime/GDB 正式验收。

任何涉及正式 `arbe` 的写操作仍需单独审批；当前 `algo_source` dirty 不能被自动覆盖。
