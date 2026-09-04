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
    "key_conditions 中的 status/bindings/substituted_expression 必须原样解释，不能从源码表达式自行补齐 missing token；"
    "不得把旧 report.html/report.md、模型常识或静态字段改写成 runtime/GDB/CAN observed。"
    "每次分析必须先绑定本次 data、arbe/source 子仓、COEM/车型、branch/commit、binary/config 和 replay mode；"
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
    "用户从 VSCode/GDB/截图/备注提供的内容使用 analysis-user-observation 保存，不能直接当作 runtime observed；"
    "不要输出隐藏思维链，只输出可核验的工程观察和 inference。"
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
        session_dir: Optional[str] = None,
        no_session: bool = True,
        system_prompt: str = "",
        tools: Optional[list[str]] = None,
        on_event: Optional[Callable[[dict], None]] = None,
        project_root: Optional[str] = None,
        extension_path: Optional[str] = None,
        load_project_extension: bool = True,
        auto_generate_extension: bool = True,
        allow_builtin_tools: bool = False,
        context: Optional[Mapping[str, Any]] = None,
        context_path: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.provider = str(provider or os.environ.get("CR60_PI_PROVIDER", "")).strip()
        self.model = str(model or os.environ.get("CR60_PI_MODEL", "Qwen3.5-27B-FP16")).strip()
        self.session_dir = session_dir
        self.no_session = no_session
        self.system_prompt = system_prompt or DEFAULT_PI_SYSTEM_PROMPT
        self.tools = tools
        self.on_event = on_event
        self.project_root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
        self.extension_path = Path(extension_path).expanduser().resolve() if extension_path else None
        self.load_project_extension = bool(load_project_extension)
        self.auto_generate_extension = bool(auto_generate_extension)
        self.allow_builtin_tools = bool(allow_builtin_tools)
        self.context = dict(context) if isinstance(context, Mapping) else None
        self.context_path = Path(context_path).expanduser().resolve() if context_path else None
        self.session_id = str(session_id or "").strip()
        self._context_prompt_file: Optional[Path] = None
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
            cmd += ["--append-system-prompt", self.system_prompt]
        context_prompt = self._context_system_prompt()
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
        if self.tools:
            cmd += ["--tools", ",".join(self.tools)]
        if not self.allow_builtin_tools:
            cmd.append("--no-builtin-tools")
        if extension is not None:
            cmd += ["--extension", str(extension)]
        log.info("PiBridge spawn: %s", " ".join(shlex.quote(c) for c in cmd))
        return subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
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
        compact = {
            "schema_version": context.get("schema_version"),
            "status": context.get("status"),
            "run_id": context.get("run_id"),
            "project": context.get("project", {}),
            "data": {
                "root": context.get("data", {}).get("root") if isinstance(context.get("data"), dict) else "",
                "case_count": len(context.get("data", {}).get("cases", []) or []) if isinstance(context.get("data"), dict) else 0,
                "data_fingerprint": context.get("data", {}).get("data_fingerprint") if isinstance(context.get("data"), dict) else "",
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
             "last_event":dict, "message":str}
        """
        try:
            self._proc = self._spawn()
        except FileNotFoundError as exc:
            if getattr(exc, "winerror", None) == 2 or getattr(exc, "errno", None) == 2:
                message = "pi 未安装或不可用"
            else:
                message = f"pi 启动失败: {exc}"
            return {"status": "error", "answer": "", "message": message,
                    "event_count": 0}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "answer": "", "message": f"spawn 失败: {exc}",
                    "event_count": 0}

        # 发送 prompt
        try:
            self._send({"type": "prompt", "message": message,
                        "images": images or [], "id": "p-1"})
        except Exception as exc:  # noqa: BLE001
            self._close_proc()
            return {"status": "error", "answer": "", "message": f"发 prompt 失败: {exc}",
                    "event_count": 0}

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
                    "message": f"读事件流失败: {exc}", "event_count": count}

        self._close_proc()
        if stream_error is not None:
            return {"status": "error", "answer": answer,
                    "message": f"读事件流失败: {stream_error}", "event_count": count,
                    "last_event": last}
        return {
            "status": "ok" if settled else "timeout",
            "answer": answer,
            "message": "agent_settled" if settled else "timeout/无回答",
            "event_count": count,
            "last_event": last,
        }

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
