# -*- coding: utf-8 -*-
"""PiBridge — 驱动 pi CLI（--mode rpc）的 Python 客户端（V4 P1）。

pi = https://pi.dev/（earendil-works/pi）minimal agent harness。
通过 JSON-over-stdio 协议驱动 pi 作为统一对话/调度中枢。

参考官方 Python 示例：subprocess.Popen(["pi","--mode","rpc",...]) + 逐行 JSON。

关键设计：
- fail-soft：provider 不可用/超时/异常 → 返回结构化错误，绝不挂起。
- 事件流：逐行读 stdout JSON，遇 `agent_settled` 结束；流式文本经 on_event 回调。
- 复用当前 Pi 配置中的 Bosch 模型端点；provider/model 可由调用方或
  `CR60_PI_PROVIDER`/`CR60_PI_MODEL` 指定，不把某个 provider 名称写死。
- 会话绑定：`--session-dir <workspace>/sessions/<project>`（多项目隔离）。
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from queue import Empty, Queue
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

log = logging.getLogger(__name__)

DEFAULT_PI_SYSTEM_PROMPT = (
    "你是 CR60 radarAnalyze 的 Pi 编排中枢。所有工程事实必须来自已注册的 Pi "
    "registerTool 结果；优先建立/使用 pi-orchestration-context.v1，再按用户目标 "
    "如果上下文包含 evidence_anchor，必须先以它为确定性事实底稿；anchor 外的值只能标为未确认，"
    "点云报告中的 points/clusters/tracks/outputs/edges 数量只可引用 evidence_anchor.perception_report.lineage 的全量计数字段；"
    "不得从 inline nodes、截断数组、比例估算或别的查询结果推算总量；anchor 未提供某个计数时写 not_available。"
    "查询点云 lineage 时，point-cloud-read 的 callback_key 取 evidence_anchor.perception_report.scene.selected_frame；"
    "只有用户明确指定另一个 frame/callback 时才替换。lineage 节点/边行是有界样本，完整总量只取 node_counts/edge_count；默认 limit=40，需要更多时用 offset 分页。"
    "不能从 lineage 边页样本推断关系不存在；callback 的关系总量只取 point-cloud-read relation_counts，关键 ID 分布和 distinct 数量分别只取 field_counts/field_summaries；不得手工数分页样本的字段值。"
    "读取 track 数量前必须检查 lineage.track_population；若 scope=`public_objectlist_output_rows`，tracks 只是公开 ObjectList 输出行的投影，不代表完整 candidate/mature 内部航迹集合，内部集合必须标为 not_available；track_emits_output 也只描述已观测输出行。"
    "lineage.relation_counts 是通过校验后的规范关系边数量；raw_relation_counts 统计提交的原始边行，可能包含重复或无效行，不是唯一关系数；拓扑覆盖必须使用 relation_summaries 的 unique_from_node_count/unique_to_node_count，并明确同 population 的分子、分母和 track_population scope。"
    "interpret relation_summaries by its from_node_kind/to_node_kind: for cluster_supports_track, unique_from_node_count counts clusters and unique_to_node_count counts tracks. Never subtract or compare an endpoint count against a different node kind; a cluster remainder from unique_from may only mean no captured-public-output edge under the declared scope, not no internal track/gate."
    "若 relation_scopes.point_supports_cluster 指定 inclusion_condition=`cluster_id > 0`，该 relation 只覆盖严格正 cluster_id 的公开点行；cluster_id=0 与 -1 都没有此边，但缺边不说明是哪一算法阶段造成，也不得改写成 >=0。"
    "timeline.uid_recurrence_status=`derived` 时，timeline.public_uid_recurrences 只表示同一 capture、同一 radar、相邻 source-proven public ObjectList callback 出现相同 UID 的 derived 连续性；不是同一物理目标的确认，也不是内部 track lifecycle observed。跨缺帧、跨 session 或跨 radar 不建立关联；UID 消失/重现只报告缺口，不推断 ID reuse 或目标出生/消失。"
    "用户追问跨帧目标/UID 时，应读取 point-cloud-read section=timeline；区分 public UID recurrence 与 physical identity，未匹配/缺帧只能报 not_available，不把 ID 未出现解释为删除或漏检。"
    "对于 cluster_supports_track，raw_relation_counts 中同一 (from,to) 的重复行被规范边去重；若 invalid_edge_count=0，raw 与规范计数差只应解释为重复关系行，不得称为无效边或算法过滤。"
    "同 node kind 的总量减 unique endpoint count 只能表示该 relation scope 下没有边的节点数；不得称 lost/untracked/gate failure，也不得把 report 边范围扩展为内部 tracker 状态。"
    "同一 track_population 若说明 cluster_supports_track_scope=`unique_cluster_track_pairs_where_point_track_uid_matches_captured_public_objectlist_id`，关系计数只覆盖点迹 UID 命中已捕获 ObjectList ID 的唯一派生边，不代表所有 cluster→内部 track 关联，也不能推断 gate/maturity；track_emits_output_scope 若为一行派生边，也不能当成独立内部转移观察。"
    "若 unclustered_point_scope 说明 cluster_id=-1 没有 cluster node/point_supports_cluster 边，不得据此断言它进入或未进入 track gate、candidate/mature track、删除/过滤阶段；只报告该点缺少 cluster 关联。"
    "candidate hypothesis 必须有当前源码/runtime 证据支持其具体机制，不能只是 count mismatch 的一种可想象解释；关键内部 population/stage 缺失且 relation 仅为公开输出子集时，若没有独立证据区分机制，应返回 0 个 hypothesis，并给出最小区分实验，不要为了 Top-3 配额填满候选。"
    "不得把 points/cluster 数量相除称为点迹聚类覆盖率；只有同一来源 population 的已关联行数除以同一 population 总行数，才可称该 population 的关联覆盖率，并写明分子/分母。跨点迹数、簇数、航迹数的比值必须标成实体数之比，不能称覆盖率/成功率/过滤率。"
    "同类型 node_count 减 relation_summaries 的对应 unique endpoint count 可以描述为‘该报告关系 scope 下无边的节点数’，但必须说明端点类型、frame/population 和关系 scope，不得叫 lost/untracked/gate failure；例如 cluster_count 减 cluster_supports_track.unique_from_node_count 只表示没有 captured public-ID-match edge 的 cluster nodes，不代表内部无 track。除非用户需要，优先报告计数而不计算比例；若报告比例，cluster 的比例只能称 observed-cluster public-ID-match fraction，不称 algorithm tracking coverage。"
    "计数差异只证明存在差异，不能单独证明过滤、删除、关联失败或代码缺陷；提出此类因果 hypothesis 前必须给出能连接这些字段/阶段的当前源码或 runtime 证据，并明确区分 observed 与 inference。"
    "不得用一个字段的哨兵/未关联值解释另一个字段的生命周期；例如 cluster_id=-1 本身不能证明 track 被 TrackManage 删除或 track_id 残留，除非当前源码/runtime 明确建立该联系。"
    "public capture message_seq/callback suffix 只表示 recorder 顺序，不是原始算法 frameID/frame counter；不得将 callback 序号与 warmup_requested 帧数比较。"
    "用户询问当前 ObjectList/目标属性时，先复用当前 preflight 生成 public-topic-plan，再用 ros-topic-inventory 对计划中的公开 channel 执行 bounded sample_once 与 inspect_message_schemas；public-topic-plan、ros-topic-inventory 和 public-runtime-normalize 必须传同一个 preflight_path，inventory 需要输出该 preflight 文件 hash。若随后要归一化，必须先给 inventory 写入一个新本地 output artifact 并把返回的 artifact_path 传给 public-runtime-normalize，不得覆盖 preflight/topic plan/输入 capture。topic_plan 必须绑定同一个 preflight server/workspace identity。需要对已生成的快照看具体字段时调用 evidence-query runtime_snapshot_path，fields 使用当前 message schema 的真实 token，保持 max_targets/max_field_rows 有界。若 SSH/preflight、消息 schema 或样本完整性缺失，输出 partial/gap。单消息独立采样没有共同 message_seq，即使时间接近也不得将 ObjectList 与 warning/ego 绑定到同一帧；frame_id 查询不能命中 unbound ObjectList；快照的 identity_binding=not_bound 或 event_association_status=not_available 时不得作为已绑定的 runtime diagnosis 证据。"
    "若 callback_binding.warmup_frame_relation=`not_evaluable` 或 algorithm_frame_counter_status=`not_available`，禁止判断 callback 发生在 warm-up 的第几帧或在 warm-up 前/后；只报告 reset/warm-up gap。"
    "key_conditions 中的 status/bindings/substituted_expression 必须原样解释，不能从源码表达式自行补齐 missing token；"
    "不得把旧 report.html/report.md、模型常识或静态字段改写成 runtime/GDB/CAN observed。"
    "case_diagnosis 必须先绑定本次 data、arbe/source 子仓、COEM/车型、branch/commit、binary/config 和 replay mode；"
    "若 PiRunContext.task_scope=source_code 且 data.status=not_required，纯源码查询不等待录制数据，可用 code-context/code-analyze 获取当前 source-bound 结果；"
    "此范围只允许陈述静态源码候选，不得扩展为编译、binary、runtime、GDB hit 或根因事实。"
    "任一 identity fingerprint 冲突时禁止跨 artifact 合并，必须标记 blocked 或向用户说明缺口。"
    "代码逻辑绝不能套用固定功能模板、固定变量名或固定条件顺序；必须从本次 code-context/code-learn/"
    "code-analyze/event-code-path 获取真实 entry、caller/callee、源码条件、参数、变量和输出，按调用关系与源码行号顺序组织。"
    "只有当前 source 实际存在的阶段才可进入结论，例如状态机/gate、自车运动、目标 dyn/track、ROI/筛选、"
    "预测/阈值、保持/计数和输出汇总；这些只是从当前源码归纳出的解释标签，不是固定必经流程；"
    "某阶段未在当前 source 发现时要明确写未发现，不能自行补齐。"
    "组合原子工具。不要猜测车型、COEM、branch、tag、radar、frame、目标 ID、ROI "
    "或变量下标；遇到 missing/conflicts 先向用户确认。把 observed、derived、"
    "not_available 和 inference 分开。任何远程写入、编译、启动、GDB attach/execute "
    "只能先生成计划并等待批准。你要支持三个用户出口：用户给文件夹时优先调用 "
    "cr60-precheck 做逐数据批量预检查；用户要求某次报警的详细诊断时，先用 "
    "evidence-query 按功能/侧别/radar/event/frame 切片，再用当前 code-context/code-analyze/"
    "event-code-path 关联真实代码，再用 alert-timeline 对齐 recorded_raw/replay_algorithm/runtime_with_frame/gdb_observation/can_tx_observation，公共 runtime 优先于 GDB，最后用 diagnosis-report 投影报告；"
    "cr60-precheck 返回的 case_artifacts 是逐数据 bundle/viewer 的权威路径，必须使用它们而不是猜路径；详细目标/自车/连续帧查询同时传入对应的 viewer_model_path；"
    "evidence-query 的参数名必须严格使用 schema 中的 function（不能写 func），fields 必须是 artifact 的真实点号路径，"
    "例如 target.fields、ego.fields、frame、code.call_chain；如果字段不存在，接受 not_available。普通对话追问不要设置 "
    "include_details=true，默认返回有界场景字段；普通 evidence-query 不要传 output（output 只有在用户明确给出文件路径时才使用）；"
    "只有生成 diagnosis-report 时才展开当前事件详情。"
    "需要解释源码条件时可调用 condition-trace；它只接受当前 source 条件/参数和同帧字段，"
    "必须保留 not_evaluable，不得把缺失变量当作条件失败。"
    "需要参考历史案例或已存知识时调用 memory-recall；记忆只作为带 provenance 的辅助线索，"
    "代码型记忆 freshness 不满足时必须接受 blocked_stale，不得当作当前代码事实。"
    "event_id 只能填写从 artifact 原样复制的完整 ID，不要把功能名放进 event_id；例如应使用 "
    "function=FCTA_R、radar_id=2、frame_id=47877，而不是 event_id=FCTA_R 或 func_name。"
    "用户在同一任务中追问属性、代码或下一步时，优先复用已有 artifact，不重新解析大数据或全仓扫描。需要回答是否应该报警时，必须先给出总结性结论，再按当前 source 的真实执行顺序说明每项条件、同帧值、阈值和结果，最后说明输出是否与代码路径一致；"
    "默认以 arbe 可视化工具报警灯对应的算法输出作为报警终点，CAN 只在用户明确要求时作为辅助证据。模型不得使用‘已观测/已满足/已上升沿’等措辞，除非对应 artifact 明确给出 observed 状态和 frame。"
    "需要交付详细报告时，先用 evidence-query/event-code-path 获取有界事实；如果用户要求诊断、正误报、根因或问题报告，必须再调用 diagnosis-panel，"
    "最后调用 diagnosis-report；调用 diagnosis-report 必须提供 output_dir，通常使用 response_mode=summary，完整报告从返回的 artifact_path 查看。"
    "若记录阶段，analysis-step-record 必须先 action=begin，再使用返回的真实 step_id 和 analysis_ledger_root 完成；"
    "不得凭空创建 step_id，也不得用 analysis-step-record complete 替代 begin。"
    "每个有价值阶段都应通过 analysis-run/analysis-step 工具留下可见摘要、证据引用、缺口和下一步；"
    "候选原因使用 analysis-hypothesis-record，实验必须先用 debug-experiment-record action=plan 再回填结果；"
    "诊断/根因请求最多记录 3 个候选并按当前证据排序；每个候选必须引用本 run 的真实 artifact/claim，写明支持、反证、关键缺口、required evidence 和 status。不得为 Top-3 配额补候选；无独立源码/runtime 机制证据时保留 0 个因果假设并明确说明。"
    "有可区分候选时优先计划成本最低且区分度最高的一个实验；expected_discrimination 必须说明不同结果分别支持/削弱什么。公共 runtime 已足够时不选择 GDB。新证据只追加状态变化和 refs；confirmed_by_user 只能由用户确认。"
    "用户从 VSCode/GDB/截图/备注提供的内容使用 analysis-user-observation 保存，不能直接当作 runtime observed；"
    "Pi ledger tools 已绑定本次 AnalysisRun 和 ledger root；不要传 run_id/ledger_root 或另建 run，bridge 会注入并拒绝跨 run 覆盖。"
    "不要输出隐藏思维链，只输出可核验的工程观察和 inference。"
)

DEFAULT_PI_SOURCE_SYSTEM_PROMPT = (
    "你是 radarAnalyze 源码查询助手，事实只依据 Pi tools。source_code 不需 case 数据；查询当前 code-context/code-analyze。"
    "用户问函数的直接调用目标、它调用了谁或下游时，code-analyze 用 kind=callees（或 call_chain 且 max_depth=1）；只有问谁调用该函数、调用者或上游时才用 kind=callers。回答必须说明调用方向，并保持工具返回的函数与数量。"
    "源码查询工具的结构化结果以内联方式返回，不要传 output 文件路径。"
    "code-analyze 的函数名参数字段固定为 name，不要使用 function_name。"
    "当前 variant 的 code context/index 已绑定到本次 PiRunContext；调用 code-context-read/event-code-path/code-analyze/code-gdb-plan 时不要自行填写 context_path、code_index_path、inline code_index 或 db_path，bridge 会注入并校验当前 artifact。"
    "保留 snapshot hash；结果只标静态候选，不推断 runtime/build/GDB/CAN/根因。冲突和 unknown 不得猜测或当 false。"
)


def _find_pi() -> str:
    """定位 pi 可执行：PATH 优先，必要时使用显式环境变量。"""
    exe = shutil.which("pi")
    if exe:
        return exe
    # A standalone installation may not put Pi on PATH.  Let the operator
    # provide its executable without baking the developer workstation path
    # into the product.
    configured = str(os.environ.get("CR60_PI_EXECUTABLE", "") or "").strip()
    if configured and os.path.exists(configured):
        return configured
    return "pi"


def _pi_command() -> list[str]:
    """Return a direct Pi command, avoiding Windows wrapper process leaks."""
    exe = _find_pi()
    if os.name == "nt":
        candidate = Path(exe)
        if candidate.name.lower() in {"pi", "pi.cmd", "pi.ps1"}:
            node = candidate.parent / "node.exe"
            entry = candidate.parent / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "cli.js"
            if not node.exists():
                node_on_path = shutil.which("node")
                if node_on_path:
                    node = Path(node_on_path)
            if node.exists() and entry.exists():
                return [str(node), str(entry)]
    return [exe]


class PiBridge:
    """Pi RPC 驱动的对话/调度客户端（headless）。"""

    def __init__(
        self,
        *,
        provider: str = "",
        model: str = "",
        thinking: str = "",
        load_context_files: bool = True,
        replace_system_prompt: bool = False,
        session_dir: Optional[str] = None,
        no_session: bool = True,
        system_prompt: str = "",
        tools: Optional[list[str]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        project_root: Optional[str] = None,
        extension_path: Optional[str] = None,
        load_project_extension: bool = True,
        auto_generate_extension: bool = True,
        discover_extensions: bool = True,
        load_skills: bool = True,
        allow_builtin_tools: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        context_path: Optional[str] = None,
        session_id: Optional[str] = None,
        analysis_run_id: str = "",
        analysis_ledger_root: str = "",
        code_index_binding: Optional[Mapping[str, Any]] = None,
    ):
        self.provider = str(provider or os.environ.get("CR60_PI_PROVIDER", "")).strip()
        self.model = str(model or os.environ.get("CR60_PI_MODEL", "Qwen3.5-27B-FP16")).strip()
        self.thinking = str(thinking or "").strip().lower()
        self.load_context_files = bool(load_context_files)
        self.replace_system_prompt = bool(replace_system_prompt)
        if self.thinking and self.thinking not in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"unsupported Pi thinking level: {self.thinking}")
        self.session_dir = session_dir
        self.no_session = no_session
        self.system_prompt = system_prompt or DEFAULT_PI_SYSTEM_PROMPT
        self.tools = tools
        self.on_event = on_event
        self.project_root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
        self.extension_path = Path(extension_path).expanduser().resolve() if extension_path else None
        self.load_project_extension = bool(load_project_extension)
        self.auto_generate_extension = bool(auto_generate_extension)
        self.discover_extensions = bool(discover_extensions)
        self.load_skills = bool(load_skills)
        self.allow_builtin_tools = bool(allow_builtin_tools)
        self.context = dict(context) if isinstance(context, Mapping) else None
        self.context_path = Path(context_path).expanduser().resolve() if context_path else None
        self.session_id = str(session_id or "").strip()
        self.analysis_run_id = str(analysis_run_id or "").strip()
        self.analysis_ledger_root = str(analysis_ledger_root or "").strip()
        self.code_index_binding = (
            {
                str(key): str(value)
                for key, value in code_index_binding.items()
                if value not in (None, "", [])
            }
            if isinstance(code_index_binding, Mapping)
            else {}
        )
        self._context_prompt_file: Optional[Path] = None
        self._context_prompt_chars = 0
        self._proc: Optional[subprocess.Popen] = None

    # ── 生命周期 ────────────────────────────────────────────────────

    def _spawn(self) -> subprocess.Popen:
        extension = self._resolve_extension()
        provider, model = self._resolve_provider_model()
        cmd = _pi_command() + ["--mode", "rpc"]
        if provider:
            cmd += ["--provider", provider]
        if model:
            cmd += ["--model", model]
        if self.session_id:
            cmd += ["--session-id", self.session_id]
        elif self.no_session:
            cmd.append("--no-session")
        if self.session_dir:
            cmd += ["--session-dir", self.session_dir]
        if self.system_prompt:
            flag = "--system-prompt" if self.replace_system_prompt else "--append-system-prompt"
            cmd += [flag, self.system_prompt]
        if self.thinking:
            cmd += ["--thinking", self.thinking]
        context_prompt = self._context_system_prompt()
        self._context_prompt_chars = len(context_prompt)
        if context_prompt:
            # Windows CreateProcess has a relatively small command-line
            # budget.  A real viewer/runtime context can exceed it even when
            # the context is deliberately bounded.  Pi accepts a file path
            # for --append-system-prompt, so keep the command short and let Pi
            # read the same exact text from a temporary file.
            if os.name == "nt" or len(context_prompt) > 8_000:
                prompt_file = tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    suffix=".txt",
                    prefix="cr60-pi-context-",
                    delete=False,
                )
                try:
                    prompt_file.write(context_prompt)
                finally:
                    prompt_file.close()
                self._context_prompt_file = Path(prompt_file.name)
                cmd += ["--append-system-prompt", str(self._context_prompt_file)]
            else:
                cmd += ["--append-system-prompt", context_prompt]
        if self.tools is not None:
            if self.tools:
                cmd += ["--tools", ",".join(self.tools)]
            else:
                # An explicit empty allowlist means no tools. Omitting both
                # flags would let Pi enable the whole extension catalog.
                cmd.append("--no-tools")
        if not self.allow_builtin_tools:
            cmd.append("--no-builtin-tools")
        if not self.discover_extensions:
            cmd.append("--no-extensions")
        if not self.load_skills:
            cmd.append("--no-skills")
        if not self.load_context_files:
            cmd.append("--no-context-files")
        if extension is not None:
            cmd += ["--extension", str(extension)]
            generated_extension = (
                self.project_root / ".pi" / "extensions" / "radar-capabilities.ts"
            ).resolve()
            if extension.resolve() == generated_extension:
                # Trust only the generated project capability registry. A
                # caller-supplied extension outside this path is never
                # auto-approved by the product bridge.
                cmd.append("--approve")
        log.info("PiBridge spawn: %s", " ".join(shlex.quote(c) for c in cmd))
        child_env = os.environ.copy()
        binding_env = {
            "CR60_PI_TASK_SCOPE": "task_scope",
            "CR60_PI_CODE_CONTEXT_PATH": "code_context_path",
            "CR60_PI_CODE_CONTEXT_SHA256": "code_context_sha256",
            "CR60_PI_CODE_INDEX_PATH": "code_index_path",
            "CR60_PI_CODE_INDEX_SHA256": "code_index_hash",
            "CR60_PI_SOURCE_ROOT": "source_root",
            "CR60_PI_SOURCE_SNAPSHOT_HASH": "source_snapshot_hash",
            "CR60_PI_PROJECT_ID": "project_id",
            "CR60_PI_VARIANT_ID": "variant_id",
        }
        analysis_env_names = (
            "CR60_PI_ANALYSIS_RUN_ID",
            "CR60_PI_ANALYSIS_LEDGER_ROOT",
        )
        for env_name in (*binding_env, *analysis_env_names):
            child_env.pop(env_name, None)
        if self.code_index_binding:
            for env_name, field in binding_env.items():
                value = self.code_index_binding.get(field)
                if value:
                    child_env[env_name] = value
        if self.analysis_run_id:
            child_env["CR60_PI_ANALYSIS_RUN_ID"] = self.analysis_run_id
        if self.analysis_ledger_root:
            child_env["CR60_PI_ANALYSIS_LEDGER_ROOT"] = self.analysis_ledger_root
        return subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            env=child_env,
        )

    def _resolve_provider_model(self) -> tuple[str, str]:
        """Resolve a configured provider or discover the exact local Pi entry.

        Pi provider names can change independently of model IDs (the current
        machine exposes ``bosch-qwen3_6`` rather than an older
        ``bosch-qwen35`` alias).  Discovery is local and read-only; explicit
        constructor/environment values always win.
        """
        if self.provider:
            return self.provider, self.model
        try:
            completed = subprocess.run(
                _pi_command() + ["--list-models"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "", self.model
        candidates: list[tuple[str, str]] = []
        for raw_line in (completed.stdout or "").splitlines():
            line = raw_line.strip()
            if not line or line.lower().startswith("provider "):
                continue
            columns = line.split()
            if len(columns) < 2:
                continue
            candidate_provider, candidate_model = columns[0], columns[1]
            if candidate_model == self.model:
                candidates.append((candidate_provider, candidate_model))
        if not candidates:
            return "", self.model
        # Prefer a Bosch entry when several providers expose the same model.
        candidates.sort(key=lambda item: (not item[0].lower().startswith("bosch-"), item[0]))
        return candidates[0]

    def _resolve_extension(self) -> Optional[Path]:
        """Return the generated project extension, creating it when enabled."""
        if not self.load_project_extension:
            return None
        path = self.extension_path or (
            self.project_root / ".pi" / "extensions" / "radar-capabilities.ts"
        )
        if self.auto_generate_extension:
            generator = self.project_root / "scripts" / "gen_pi_extension.py"
            if not generator.exists():
                raise FileNotFoundError(f"Pi extension generator not found: {generator}")
            path.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(
                [sys.executable, str(generator), "--out", str(path)],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if completed.returncode != 0 or not path.exists():
                detail = (completed.stderr or completed.stdout or "generation failed").strip()
                raise RuntimeError(f"Pi extension generation failed: {detail}")
        if not path.exists():
            raise FileNotFoundError(f"Pi project extension not found: {path}")
        return path

    def _context_system_prompt(self) -> str:
        """Load a compact, read-only context hint for Pi's planner."""
        context = self._load_context()
        if not context:
            return ""
        # Keep large bag/preflight payloads out of the LLM prompt.  Full data
        # remains available through artifact paths and Pi tools.
        context_data = context.get("data", {})
        if not isinstance(context_data, dict):
            context_data = {}
        has_case_data = bool(context_data.get("paths") or context_data.get("cases"))
        data_status = context_data.get("status") or (
            "available" if has_case_data else "not_provided"
        )
        task_scope = str(context.get("task_scope") or "case_analysis")
        if task_scope == "source_code":
            project = context.get("project", {})
            source = context.get("source", {})
            if not isinstance(project, Mapping):
                project = {}
            if not isinstance(source, Mapping):
                source = {}
            code_context = source.get("code_context")
            code_context = code_context if isinstance(code_context, Mapping) else {}
            source_root = source.get("source_root") or code_context.get("source_root")
            source_hash = source.get("source_snapshot_hash") or code_context.get("source_snapshot_hash")
            source_compact = {
                key: value
                for key, value in {
                    "source_root": source_root,
                    "source_snapshot_hash": source_hash,
                }.items()
                if value not in (None, "", [])
            }
            compact_source = {
                "task_scope": task_scope,
                "status": context.get("status"),
                "project": {
                    key: project.get(key)
                    for key in ("project_id", "variant_id")
                    if project.get(key) not in (None, "", [])
                },
                "data": {
                    "status": data_status,
                    "required": context_data.get("required", True),
                },
                "source": source_compact,
            }
            if context.get("missing"):
                compact_source["missing"] = context.get("missing")
            if context.get("conflicts"):
                compact_source["conflicts"] = context.get("conflicts")
            import json as _json
            text = _json.dumps(compact_source, ensure_ascii=False, sort_keys=True, default=str)
            return (
                "Source-only PiRunContext needs no case data. Use bound project/source snapshot; "
                "report static candidates only, never runtime/build/GDB/CAN proof. Preserve conflicts/unknowns. "
                "Context: "
                + text
            )
        compact = {
            "schema_version": context.get("schema_version"),
            "task_scope": context.get("task_scope", "case_analysis"),
            "status": context.get("status"),
            "run_id": context.get("run_id"),
            "project": context.get("project", {}),
            "data": {
                "status": data_status,
                "required": context_data.get("required", True),
                "root": context_data.get("root", ""),
                "case_count": len(context_data.get("cases", []) or []),
                "data_fingerprint": context_data.get("data_fingerprint", ""),
            },
            "source": self._compact_source_context(context.get("source", {})),
            "build": self._compact_build_context(context.get("build", {})),
            "runtime": self._compact_runtime_context(context.get("runtime", {})),
            "policy": context.get("policy", {}),
            "artifacts": self._compact_artifact_refs(context.get("artifacts", [])),
            "freshness": context.get("freshness", {}),
            "missing": context.get("missing", []),
            "conflicts": context.get("conflicts", []),
            "evidence_anchor": context.get("evidence_anchor", {}),
        }
        import json as _json
        text = _json.dumps(compact, ensure_ascii=False, sort_keys=True, default=str)
        return (
            "本次任务的 PiRunContext 是只读、权威的编排上下文。"
            "只能追加工具 artifact，不能猜测或覆盖 identity/source fingerprint；"
            "遇到 missing/conflicts 必须先请求确认。evidence_anchor 是确定性报告摘要，"
            "task_scope=source_code 且 data.required=false 时，缺少录制数据是预期状态；继续使用源码能力，但不声称任何 runtime/编译结论。"
            "case_diagnosis 仍必须满足所需材料和身份绑定。"
            "它优先于模型记忆和旧 report.md；anchor 中没有的 observed/runtime 事实不得补写。"
            "每次代码分析必须以当前 source 的实际调用链和源码行号为顺序，动态组织状态机/gate、"
            "自车、目标、ROI、预测、保持计数和输出等阶段；不存在的阶段标记未发现，不能用固定功能模板补齐。"
            "报告里的 can_output/source output chain 只表示当前 source 的静态 RteCom/WriteSignal 候选，"
            "不能把它解释成该 frame 已发送 CAN；只有用户明确要求 CAN 侧核验时才把 CAN 作为独立辅助证据。"
            "上下文摘要如下：\n" + text
        )

    @staticmethod
    def _compact_source_context(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        keys = (
            "server_host", "server_user", "arbe_root", "algo_source_root", "code_root",
            "source_context_id", "source_context_fingerprint", "source_snapshot_hash", "code_index_hash", "outer_head",
            "outer_branch", "outer_dirty", "algo_head", "algo_branch", "algo_dirty",
            "outer_status", "algo_status", "configuration", "build_probe",
        )
        result: dict[str, Any] = {}
        for key in keys:
            item = value.get(key)
            if key in {"configuration", "build_probe"}:
                if isinstance(item, Mapping):
                    result[key] = {
                        "keys": sorted(str(name) for name in item)[:60],
                        "status": item.get("status"),
                    }
                continue
            if item not in (None, "", []):
                result[key] = item
        return result

    @staticmethod
    def _compact_build_context(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, Any] = {}
        for key in ("status", "binary", "binary_fingerprint", "macros", "gdb", "processes"):
            item = value.get(key)
            if item in (None, "", []):
                continue
            if isinstance(item, list):
                result[key] = item[:8]
            elif isinstance(item, Mapping):
                result[key] = {str(name): item[name] for name in list(item)[:40]}
            else:
                result[key] = item
        return result

    @staticmethod
    def _compact_runtime_context(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, Any] = {}
        for key in (
            "status", "strategy", "radar_id", "strategy_status", "strategy_source",
            "radar_id_source", "evidence_status", "debug_plan_status", "evidence_ref",
        ):
            item = value.get(key)
            if item not in (None, "", []):
                result[key] = item
        evidence = value.get("evidence")
        if isinstance(evidence, Mapping):
            evidence_run = evidence.get("run") if isinstance(evidence.get("run"), Mapping) else {}
            result["evidence_summary"] = {
                "status": evidence.get("status"),
                "run": {
                    key: evidence_run.get(key)
                    for key in ("run_id", "data_fingerprint", "source_context_id", "source_snapshot_hash", "bag")
                    if evidence_run.get(key) not in (None, "", [])
                },
                "observation_count": len(evidence.get("observations", []) or []),
                "layer_count": len(evidence.get("evidence_layers", []) or []),
                "diagnostics": list(evidence.get("diagnostics", []) or [])[:12],
            }
        return result

    @staticmethod
    def _compact_artifact_refs(value: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, Mapping):
                continue
            ref = {
                key: item[key]
                for key in ("kind", "path", "source", "schema_version")
                if item.get(key) not in (None, "", [])
            }
            if ref and ref not in result:
                result.append(ref)
        return result[:80]

    def _load_context(self) -> dict[str, Any] | None:
        """Load and validate a supplied PiRunContext before spawning Pi."""
        context = self.context
        if context is None and self.context_path is not None:
            import json as _json
            value = _json.loads(self.context_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("PiRunContext root must be a JSON object")
            context = value
        if context is None:
            return None
        if not isinstance(context, dict):
            raise ValueError("PiRunContext must be a JSON object")
        if context.get("schema_version") != "pi-orchestration-context.v1":
            raise ValueError(
                "PiRunContext schema_version must be pi-orchestration-context.v1"
            )
        required = {
            "status", "run_id", "context_fingerprint", "project", "data",
            "source", "build", "runtime", "policy", "artifacts", "freshness",
            "missing", "conflicts", "diagnostics",
        }
        missing = sorted(name for name in required if name not in context)
        if missing:
            raise ValueError("PiRunContext missing required fields: " + ", ".join(missing))
        return context

    def prompt(
        self, message: str,
        *,
        timeout: Optional[float] = 300,
        images: Optional[list[dict]] = None,
    ) -> dict[str, Any]:
        """发送 prompt，消费事件流直到 agent_settled。

        Returns:
            {"status":"ok"|"error", "answer":str, "event_count":int,
             "last_event":dict, "event_summary":dict, "message":str}
        """
        event_summary: dict[str, Any] = {
            "assistant_messages": [],
            "tool_calls": [],
            "tool_events": [],
            "extension_error_count": 0,
            "provider": self.provider,
            "model": self.model,
            "thinking_level": self.thinking or "user_default",
            "enabled_tools": list(self.tools) if self.tools is not None else [],
            "tool_allowlist_mode": "explicit" if self.tools is not None else "all_extensions",
            "load_context_files": self.load_context_files,
            "discover_extensions": self.discover_extensions,
            "load_skills": self.load_skills,
            "extension_enabled": self.load_project_extension,
            "system_prompt_chars": len(self.system_prompt or ""),
            "replace_system_prompt": self.replace_system_prompt,
            "user_prompt_chars": len(str(message or "")),
        }
        try:
            self._proc = self._spawn()
            event_summary["context_prompt_chars"] = self._context_prompt_chars
        except FileNotFoundError as exc:
            if getattr(exc, "winerror", None) == 2 or getattr(exc, "errno", None) == 2:
                message = "pi 未安装或不可用"
            else:
                message = f"pi 启动失败: {exc}"
            return {"status": "error", "answer": "", "message": message,
                    "event_count": 0, "event_summary": event_summary}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "answer": "", "message": f"spawn 失败: {exc}",
                    "event_count": 0, "event_summary": event_summary}

        # 发送 prompt
        try:
            self._send({"type": "prompt", "message": message,
                        "images": images or [], "id": "p-1"})
        except Exception as exc:  # noqa: BLE001
            self._close_proc()
            return {"status": "error", "answer": "", "message": f"发 prompt 失败: {exc}",
                    "event_count": 0, "event_summary": event_summary}

        # 消费事件流。stdout.readline() 本身是阻塞的，直接在主线程调用会
        # 让 timeout 失效；由 daemon reader 放入有界等待队列，主线程始终
        # 保留 deadline 和进程清理控制权。
        answer = ""
        count = 0
        last: dict = {}
        settled = False
        stream_error: Exception | None = None
        events: Queue[tuple[str, Any]] = Queue()
        proc = self._proc

        def _read_events() -> None:
            try:
                if proc is None or proc.stdout is None:
                    events.put(("eof", None))
                    return
                for raw_line in proc.stdout:
                    events.put(("line", raw_line))
            except Exception as exc:  # noqa: BLE001 - subprocess boundary
                events.put(("error", exc))
            finally:
                events.put(("eof", None))

        threading.Thread(target=_read_events, name="pi-rpc-reader", daemon=True).start()
        try:
            import time
            deadline = time.time() + (timeout or 300)
            while time.time() < deadline:
                remaining = max(0.0, deadline - time.time())
                try:
                    kind, value = events.get(timeout=min(0.25, remaining))
                except Empty:
                    continue
                if kind == "eof":
                    break
                if kind == "error":
                    stream_error = value if isinstance(value, Exception) else RuntimeError(str(value))
                    break
                line = str(value or "")
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                count += 1
                last = ev
                self._record_event_summary(event_summary, ev)
                if self.on_event:
                    try:
                        self.on_event(ev)
                    except Exception:  # noqa: BLE001
                        pass
                etype = ev.get("type")
                if etype == "message_update":
                    delta = ev.get("assistantMessageEvent", {})
                    if delta.get("type") == "text_delta":
                        answer_append = delta.get("delta", "")
                        answer += answer_append
                elif etype == "agent_settled":
                    settled = True
                    break
                elif etype == "extension_error":
                    log.warning("pi extension_error: %s", ev)
        except Exception as exc:  # noqa: BLE001
            self._close_proc()
            return {"status": "error", "answer": answer,
                    "message": f"读事件流失败: {exc}", "event_count": count,
                    "event_summary": event_summary}

        self._close_proc()
        if stream_error is not None:
            return {"status": "error", "answer": answer,
                    "message": f"读事件流失败: {stream_error}", "event_count": count,
                    "last_event": last, "event_summary": event_summary}
        return {
            "status": "ok" if settled else "timeout",
            "answer": answer,
            "message": "agent_settled" if settled else "timeout/无回答",
            "event_count": count,
            "last_event": last,
            "event_summary": event_summary,
        }

    @staticmethod
    def _record_event_summary(summary: dict[str, Any], event: Mapping[str, Any]) -> None:
        """Keep bounded RPC telemetry without retaining assistant text or CoT."""
        event_type = str(event.get("type") or "")
        message = event.get("message")
        if event_type == "message_end" and isinstance(message, Mapping):
            if message.get("role") != "assistant":
                return
            usage = message.get("usage") if isinstance(message.get("usage"), Mapping) else {}
            content = message.get("content") if isinstance(message.get("content"), list) else []
            summary["assistant_messages"].append({
                "provider": message.get("provider"),
                "model": message.get("model"),
                "api": message.get("api"),
                "stop_reason": message.get("stopReason"),
                "raw_stop_reason": message.get("rawStopReason"),
                "usage": {
                    key: usage.get(key)
                    for key in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
                    if usage.get(key) is not None
                },
                "content_types": [
                    str(block.get("type"))
                    for block in content
                    if isinstance(block, Mapping) and block.get("type") not in (None, "", "thinking")
                ],
            })
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "toolCall":
                    summary["tool_calls"].append({
                        "id": str(block.get("id") or ""),
                        "name": str(block.get("name") or ""),
                    })
            return
        lowered = event_type.lower()
        if "tool_execution" in lowered:
            result = event.get("result") if isinstance(event.get("result"), Mapping) else {}
            details = result.get("details") if isinstance(result.get("details"), Mapping) else {}
            name = event.get("toolName") or event.get("tool_name") or event.get("name")
            summary["tool_events"].append({
                "event_type": event_type,
                "name": str(name or ""),
                "tool_call_id": str(event.get("toolCallId") or event.get("tool_call_id") or ""),
                "status": str(event.get("status") or result.get("status") or details.get("status") or ""),
            })
        elif event_type == "extension_error":
            summary["extension_error_count"] = int(summary.get("extension_error_count", 0)) + 1

    # ── 内部 ────────────────────────────────────────────────────────

    def _send(self, cmd: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("pi 进程未启动")
        self._proc.stdin.write(json.dumps(cmd) + "\n")
        self._proc.stdin.flush()

    def steer(self, message: str) -> None:
        """运行时注入用户决定（HITL 用）。"""
        self._send({"type": "steer", "message": message})

    def _close_proc(self) -> None:
        if self._proc is None:
            if self._context_prompt_file is not None:
                try:
                    self._context_prompt_file.unlink(missing_ok=True)
                except OSError:
                    pass
                self._context_prompt_file = None
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            pid = self._proc.pid
            if os.name == "nt" and pid:
                # Pi extensions may spawn helper processes.  Kill only the
                # process tree owned by this bridge invocation.
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                self._proc.kill()
        except Exception:
            pass
        if self._context_prompt_file is not None:
            try:
                self._context_prompt_file.unlink(missing_ok=True)
            except OSError:
                pass
            self._context_prompt_file = None
        self._proc = None

    def close(self) -> None:
        self._close_proc()


__all__ = ["PiBridge", "DEFAULT_PI_SYSTEM_PROMPT", "_find_pi", "_pi_command"]
