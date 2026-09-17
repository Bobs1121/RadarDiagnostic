# radarAnalyze M0–M4 暂停交接

> **归档：2026-09-17。本文仅保留历史设计/证据，不再是当前开发指令。当前唯一套件见 [DDD 入口](../../../technical/GEN6_AI_DOCUMENT_INDEX.md)。**


日期：2026-09-09  
状态：`local_m0_m4_verified / external_acceptance_pending`  
目标：按“文档驱动开发”把 radarAnalyze 收敛到算法工程师本地/内网可交付的首版，覆盖数据分析、仿真验证和证据报告。

## 当前结论

本轮已经把 M0–M4 的本地工程闭环落到代码、测试、机器验收索引和体检命令中，但不能把本地 gate 通过解释为真实远端仿真或干净机器安装已经验收。

当前首版本地/现场 gate：`9/9` 个必需条目通过。点云前级真实 `HILMODEL=0` build/replay 和第二异构项目仍是后续扩展验收项。

## 已完成的实现

- `core/knowledge_guard.py`：variant 下没有 `knowledge_manifest.json`、scope 未发布或输入签名失配时 fail-closed；legacy 无 variant 模式保留兼容放行。
- `core/diagnosis_bundle.py`：静态 evidence + source localization 只能形成 candidate；`confirmed_root_cause` 必须有 `metadata.confirmation_gate`，包含 `identity_verified`、非空 `evidence_refs`，以及 runtime/replay/user confirmation 之一。
- `harness/harness_runner.py`：L1/L2 evaluator 缺失时不能通过加权分数门。
- `engines/arbe/execution_binding.py`：冻结 data/source/binary/config/session identity、approval、plan hash 和 run id，并在副作用前重新校验。
- `derive_execution_identity()`：从 preflight 的 workspace/build/config/runtime 嵌套结构自动解析 source/binary/config/session 字段并保留字段 provenance；data fingerprint 仍来自 intake/bundle。
- `ai/modules/sim_verify.py`：`remote_public` 执行要求 `execution_binding`；缺失或漂移时返回 `blocked`，不启动 SSH。
- `ai/modules/execution_binding.py`：Pi/CLI 自动从 plan + preflight/source identity 生成 `arbe-execution-binding.v1`；默认先返回 `approval_required`，批准后才生成 binding。
- `engines/arbe/remote_replay.py`：执行 attempt 使用唯一后缀；远端 recorder 命令加入 `trap`，SSH 中断时清理 tool-owned recorder/child process。
- `tools/doctor.py`：只读检查 Python、核心依赖、入口文件和 Pi capability catalog。
- `requirements.lock`：记录本轮已验收的直接依赖版本组合；doctor 会检查锁定版本是否与当前环境一致。
- 点云第一条代码切片：`engines/point_cloud_replay.py`、`ai/modules/point_cloud_plan.py`、
  `ai/modules/point_cloud.py` 和 `contracts/perception-*.v1.schema.json` 已注册到 Pi；
  `point-cloud-plan` 在当前 `HILMODEL=2` preflight 上明确返回 `blocked`，
  `point-cloud-analyze` 对点迹/阶段/lineage 证据生成 `perception-report.v1`，缺阶段 evidence 返回 `partial`。
- `tools/release_gate.py`：读取 `docs/archive/2026-09-17/technical/release_acceptance.v1.json`，检查证据路径/sha256，重跑 required commands，并输出当前 commit 和结果。
- `docs/archive/2026-09-17/technical/CR60_PI_DDD_REQUIREMENTS_AND_ACCEPTANCE.md`：追加 M0–M4 当前实现检查点。
- `README.md`、`AGENTS.md`、`core/AGENTS.md`、`engines/AGENTS.md`、`ai/modules/AGENTS.md`、`tools/AGENTS.md`：同步入口、契约和边界说明。

## 已验证证据

以下均为当前工作树执行结果：

```text
python -m pytest tests/test_knowledge_guard.py tests/test_conclusion_publication.py \
  tests/test_execution_binding.py tests/test_arbe_remote_replay.py \
  tests/test_replay_provider_mapping.py tests/test_harness_phase2.py -q
54 passed in 19.17s

python -m pytest tests/test_release_acceptance.py tests/test_knowledge_guard.py \
  tests/test_conclusion_publication.py tests/test_execution_binding.py -q
23 passed in 51.90s

python -m pytest tests/test_cli_capabilities.py tests/test_pi_tool_bridge.py \
  tests/test_modules_standalone.py tests/test_arbe_remote_replay.py \
  tests/test_project_isolation.py tests/test_project_capability.py -q
51 passed in 5.85s

python tools/doctor.py --json
status=ready; capability_count=59; failures=[]

python tools/release_gate.py
release gate: accepted (9/9 required entries)
```

本轮另执行了一次只读远端 preflight：
`python cli.py arbe-preflight --host 10.190.171.44 --user hoz2wx --arbe-root /home/hoz2wx/CR60LIGHT/cr60_light_arbe --timeout-sec 20 --output outputs/arbe_preflight_m0_m4_20260909.json`。
结果 `arbe-preflight:ready`，记录了 outer HEAD `4c171298b2c3583509ea3e9da222b90ba0a9e513`、algo HEAD
`a81b08a38f316a3d25bfcbcad6dcfc822d24b990`、`HILMODEL=2`、`BUILDMODEL=2`、binary fingerprint
`93a8f2b2c11a6d8ba1abadbc7eb480e8867352f261a71c4bb5023f4c4ef80890`、GDB 12.1、`ptrace_scope=1`
和 4 个 `arbe_visualization_engine` PID。outer/algo 均 dirty；本次没有启动回放、编译、GDB 或修改远端。

M3 还在临时 clean venv `C:\Users\HOZ2WX\AppData\Local\Temp\radar-analyze-m3-venv-20260909213153`
中按 `requirements.lock` 完成安装；doctor 初次因 capability 冷启动超过 45 秒报告 timeout，
将 `--catalog-timeout-sec` 默认值调到 180 秒后重新验证为 `status=ready`、59 capabilities、
`lock_mismatches=[]`。这证明当前 Windows 主机上的 clean venv 可复现，仍不等同于另一台机器验收。

基于该 preflight 和现有 Pi context 还生成了一个本地 replay 计划：
`outputs/remote_public_plan_m0_m4_20260909.json`，状态为 `planned`；随后调用
`arbe-execution-binding` 生成了 `outputs/remote_execution_binding_approval_required_m0_m4_20260909.json`，
得到 `approval_required` 且 `missing_identity=[]`，说明计划已经具备
完整 data/source/binary/config/session identity，但尚未获得用户批准，因此没有生成 approved binding、
没有启动 SSH/rosbag。

2026-09-10 已按用户批准执行该计划的同等 fresh-preflight 版本：

- preflight：`outputs/arbe_preflight_execute_20260910.json`，`status=ready`；
- plan：`outputs/remote_public_plan_execute_20260910.json`；
- approved binding：`outputs/remote_execution_binding_approved_20260910.json`，
  `binding_hash=29980821323bf53fc8625046c59ea2625a1e301508bb36aac1e74ea287912688`；
- session：`outputs/remote_public_execute_20260910.json`，`status=completed`，
  `attempt_id=remote-public-execute-20260910-01`；
- capture：`outputs/remote_public_capture_execute_20260910.json`，SCP `returncode=0`；
- marker：`play_rc=0`、`record_rc=0`、`extract_rc=0`、`capture_json_present=yes`；
- normalized runtime：`61` 个 `frame_verified` snapshot、`4` 个 rising-edge，
  `objID=44` 在 `frame=47871/47872` 观测到，`radar_id=2`；
- recorder cleanup：远端 `pgrep` 未发现该 attempt 的 recorder 进程；capture bag/json/log 保留在
  `/tmp/radarAnalyze_m0_m4_execute_20260910.remote-public-execute-20260910-01.*`，便于审计和复取；
- 证据缺口：raw `warning_status` 没有 frame，8 个 objectlist rows 仍为 `unbound`，
  因此本次运行证明了公共 replay/capture/fetch/身份绑定闭环，但不把 objectlist 时间邻近结果升级为同帧事实。

另外对独立 attempt `remote-public-interrupt-20260910-01` 做了 SSH 中断注入：本地 runner 返回
`4294967295`，远端 `pgrep` 未发现 recorder，partial bag/log/play.log 保留，capture JSON 未生成。
证据：[remote_public_interrupt_evidence_20260910.json](../../../../RamboStar/idea/radarAnalyze/outputs/remote_public_interrupt_evidence_20260910.json)。

全量回归第一次执行结果为 `788 passed, 1 failed, 1 skipped, 2 xfailed`；唯一失败是旧测试没有发布 manifest，却期望 variant 条件可用。测试已改为先发布 `conditions:RCTA` 和 `codegraph` scope。第二次完整回归曾在 `72%` 被暂停；恢复后发现 release acceptance 在完整 pytest 中嵌套运行 `tests/test_analysis_ledger.py` 会放大 Windows 文件访问间歇问题。release gate 已改为无嵌套 pytest 的 M0–M4 smoke contract；随后修复 ledger lock/atomic replace 的 Windows 有界重试，加入 binding 计划读取和 preflight identity 派生，最终全量回归为 `794 passed, 1 skipped, 2 xfailed, 10 warnings in 472.78s`，独立 `tests/test_release_acceptance.py` 为 `3 passed`，release gate `9/9` 通过；点云切片定向测试另为 `7 passed`。

此前 `analysis_ledger` 有一次 Windows `os.replace` `WinError 5`，以及并发创建 `.ledger.lock` 的 `PermissionError`；现在 `_RunLock` 和 `_atomic_write_json` 都对短暂访问拒绝做有界重试，超时仍返回明确错误。独立 `python -m pytest tests/test_analysis_ledger.py -q` 为 `12 passed`；M2 smoke 直接验证 ledger 的 create/begin/complete/read 生命周期。

## 恢复后第一步

```powershell
cd D:\RamboStar\idea\radarAnalyze
python -m pytest -q
python tools/doctor.py --json
python tools/release_gate.py --json
git diff --check
```

全量回归若再次需要确认，执行 `python -m pytest -q`；发布前仍要检查 release gate 的每个 entry 输出和当前 commit，不要用旧报告替代本次运行结果。

## 尚未完成的现场验收

1. 注入 SSH 中断、录制挂起、fetch 失败，确认 attempt 隔离、trap 清理、已有 capture 可复取且不覆盖旧证据。
2. 在另一台干净机器按 README 安装，验证 Python/Pi/provider/sibling harness 版本组合和首个样例；当前主机 clean venv 已通过。
3. 用第二个异构真实项目/数据格式执行 M4，保留同一 `US → AC → artifact → hash → status` 追踪。
4. 对旧 `diag` 和新 `diagnosis-report` 用同一输入复跑，确认没有未经 runtime/replay/user gate 的 `confirmed_root_cause`。

以上项目涉及真实远端、正式 workspace、外部 provider 或新的受测输入；本轮没有执行，也没有请求或改变这些权限。

## 工作树注意事项

暂停时未提交、未 reset、未 clean，也未覆盖已有用户修改。当前工作树还包含先前已有的案例报告、SQLite/codegraph 修改和大量未跟踪 BSD 探索脚本；恢复时应先分类，不要用全局清理命令处理它们。

本交接只记录当前状态，不代表所有改动已经提交或 release branch 已冻结。

## 2026-09-13 本地回归与点云增量

最终全量回归：`860 passed, 1 skipped, 2 xfailed, 10 warnings`；`python tools/release_gate.py`
accepted `10/10` required entries；`python tools/doctor.py --json` 为 `ready`、64 capabilities、
`lock_mismatches=[]`。工作树仍未提交，保留已有用户改动。

Windows memory persistence 的 `atomic_write_text()` 也改为唯一 sibling temp，并对 `os.replace` 的短暂
`PermissionError` 做 6 次有界指数退避；新增瞬态锁和并发 writer 回归，避免偶发 `WinError 5` 使全量测试失败。

点云报告的 lineage 现把 canonical unique `(from,to)` pairs 与原始支持行分开，公开
`tracks` 节点标为 ObjectList 输出投影，内部 candidate/mature population 为 `not_available`；
selected-frame HTML/browser 证据与 Pi P2 只读检查见
`outputs/offline_browser_verification_20260913_v4.json` 和
`outputs/pi_point_cloud_hypothesis_review_runtime_20260913_v13.json`。report 仍为
`partial / valid_with_warnings`；PC-AC-03/04/05/06/07/11/12、第二异构项目、干净机器和现场内部 trace
继续待验收。此次仅重跑既有本地 capture，没有新的远端 replay/build/source 写入。
