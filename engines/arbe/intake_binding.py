# -*- coding: utf-8 -*-
"""intake_binding — 材料/数据身份到已配置项目（variant）的确定性绑定门。

T10（G6-AC01/G6-R01/03/13）的核心确定性步骤：把 ``cr60-analysis-intake.v1``
中已解析的身份字段（customer/vehicle/coem/software_version/code_branch）绑定到
``config.variants`` 中唯一匹配的项目，并对版本/分支做 fail-closed 比对。

设计约束（与 intake/pi_context 一致）：

* 路径名、bag 文件名不作为身份证据；身份只来自显式输入或材料中已解析
  （``status=resolved``）的字段；
* 绑定歧义、身份缺失以**业务语言问题**返回（只问影响结果的项），不抛异常、
  不调用 LLM、不访问网络；
* 版本/分支与项目期望不一致时 ``blocked``——错误版本不得进入当前 runtime
  绑定（G6-AC01 红线）；
* 输出 ``cr60-intake-binding.v1``：status/binding/version_gate/
  business_questions/provenance，可直接进入 Pi 的 pre-model gate 与 AnalysisRun
  绑定。
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "cr60-intake-binding.v1"

#: 绑定门会向用户澄清的身份字段（影响 runtime 绑定结果）。
BINDING_FIELDS = ("customer", "vehicle", "coem", "software_version", "code_branch")

#: 身份字段 → 业务语言措辞（只问必要业务信息，不给技术 token）。
FIELD_BUSINESS_TERMS = {
    "software_version": "录制数据对应的软件版本",
    "vehicle": "车型项目",
    "coem": "客户项目（COEM）",
    "code_branch": "算法代码分支",
    "customer": "客户",
}

#: 缺失字段的业务影响说明（为什么必须问）。
FIELD_MISSING_IMPACT = {
    "software_version": (
        "不同软件版本对应的算法代码和参数不同，版本对不上会导致结论与实际运行不符。"
    ),
    "vehicle": "车型决定配置、雷达布置和输出定义，选错项目会引用错误代码。",
    "coem": "客户项目（COEM）决定当前分析的源码集合，不同 COEM 代码不同。",
    "code_branch": "代码分支决定当前分析的源码版本。",
    "customer": "客户决定项目归属和代码集合。",
}


def _resolved_value(group: Mapping[str, Any] | None, field: str) -> tuple[Any, dict[str, Any] | None]:
    """只读取显式 resolved 的 intake 字段（与 engines.pi_context 同语义）。"""
    if not isinstance(group, Mapping) or field not in group:
        return None, None
    entry = group.get(field)
    if isinstance(entry, Mapping):
        if entry.get("status") != "resolved" or entry.get("value") in (None, "", []):
            return None, None
        return entry.get("value"), deepcopy(dict(entry.get("selected_from") or {}))
    if entry not in (None, "", []):
        return entry, {"source": "normalised_input", "field": field}
    return None, None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _coem_leaf(value: Any) -> str:
    """COEM 目录用末级目录名比较，兼容绝对路径写法。"""
    text = str(value or "").strip().replace("\\", "/").rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1].lower()


def _business_question(
    qid: str,
    field: str,
    question: str,
    *,
    why: str = "",
    candidates: list[Any] | None = None,
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "id": qid,
        "field": field,
        "question": question,
        "why": why or FIELD_MISSING_IMPACT.get(field, ""),
        "candidates": list(candidates or []),
        "blocking": bool(blocking),
    }


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _variant_expectations(variant: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """合并 per-variant 与 top-level source_context 的期望分支/版本。"""
    variant_context = variant.get("source_context") if isinstance(variant.get("source_context"), Mapping) else {}
    top_context = config.get("source_context") if isinstance(config.get("source_context"), Mapping) else {}
    expected_branch = (
        variant_context.get("code_branch")
        or top_context.get("code_branch")
        or ""
    )
    expected_version = (
        variant.get("expected_software_version")
        or variant_context.get("expected_software_version")
        or ""
    )
    return {
        "code_branch": str(expected_branch or "").strip(),
        "software_version": str(expected_version or "").strip(),
    }


def _match_variants(
    identity: Mapping[str, Any],
    variants: Mapping[str, Any],
) -> tuple[list[str], str]:
    """按 customer+vehicle 成对和/或 coem 末级目录匹配 variant。

    返回 (matched_ids, mode)；mode ∈ customer_vehicle|coem|both|none。
    """
    customer = _norm(identity.get("customer"))
    vehicle = _norm(identity.get("vehicle"))
    coem = _coem_leaf(identity.get("coem"))
    has_customer_vehicle = bool(customer and vehicle)
    has_coem = bool(coem)
    if not has_customer_vehicle and not has_coem:
        return [], "none"

    matches: list[str] = []
    for variant_id, variant_raw in variants.items():
        if not isinstance(variant_raw, Mapping):
            continue
        if has_customer_vehicle:
            if (
                _norm(variant_raw.get("customer")) != customer
                or _norm(variant_raw.get("vehicle_project")) != vehicle
            ):
                continue
        if has_coem:
            if _coem_leaf(variant_raw.get("coem_project_dir")) != coem:
                continue
        matches.append(str(variant_id))

    if has_customer_vehicle and has_coem:
        mode = "both"
    elif has_customer_vehicle:
        mode = "customer_vehicle"
    else:
        mode = "coem"
    return matches, mode


def bind_intake_identity(
    intake: Mapping[str, Any] | None,
    config: Mapping[str, Any],
    *,
    case_variant: Mapping[str, Any] | None = None,
    case_variant_error: str = "",
    explicit_variant_id: str = "",
    intake_path: str = "",
    intake_sha256: str = "",
) -> dict[str, Any]:
    """把 intake 身份绑定到已配置 variant，并做版本/分支 fail-closed 门。

    参数
    ----
    intake:
        ``cr60-analysis-intake.v1`` 映射（可为 None：仅用 case 元数据/单项目回退）。
    config:
        已加载的项目配置（含 ``variants``）。
    case_variant:
        可选的 case 元数据匹配结果（``{"variant_id","origin"}``），来自
        ``cli._resolve_variant_from_case_metadata``；优先于 intake 身份匹配。
    case_variant_error:
        case 元数据匹配产生歧义时的错误说明（多命中）；转为业务确认项。
    explicit_variant_id:
        用户显式指定的 variant；优先级低于 case 元数据、高于身份匹配。
    intake_path / intake_sha256:
        可选的 intake artifact 引用（进入 provenance）。

    返回
    ----
    ``cr60-intake-binding.v1`` dict。status ∈ resolved / needs_confirmation / blocked。
    """
    diagnostics: list[str] = []
    identity: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    intake_identity = intake.get("identity", {}) if isinstance(intake, Mapping) else {}
    for field in BINDING_FIELDS + ("ticket_id",):
        value, source = _resolved_value(intake_identity, field)
        if value not in (None, "", []):
            identity[field] = value
            if source:
                provenance[field] = source

    variants = config.get("variants") if isinstance(config.get("variants"), dict) else {}
    variant_id = ""
    variant_origin = ""
    variant_candidates: list[str] = []
    business_questions: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    missing: list[str] = []
    status = "resolved"

    # ── 1. variant 解析 ────────────────────────────────────────────
    case_vid = str((case_variant or {}).get("variant_id") or "").strip()
    explicit_vid = str(explicit_variant_id or "").strip()
    if case_variant_error:
        status = "needs_confirmation"
        variant_origin = "case_metadata_ambiguous"
        business_questions.append(
            _business_question(
                "choose_project",
                "coem",
                "案例元数据匹配到多个已配置项目，无法自动选择。请确认本次分析针对哪个车型项目。",
                why="不同项目的源码、配置和输出定义不同，选错项目会引用错误代码。",
                blocking=True,
            )
        )
        diagnostics.append(f"case_variant_ambiguous: {case_variant_error}")
    elif case_vid and case_vid in variants:
        variant_id = case_vid
        variant_origin = str((case_variant or {}).get("origin") or "case_metadata")
    elif case_vid:
        # case 元数据声明了不存在的 variant：fail-closed，需要用户确认。
        status = "needs_confirmation"
        variant_origin = "case_metadata_unresolved"
        business_questions.append(
            _business_question(
                "choose_project",
                "variant_id",
                (
                    f"案例元数据声明的项目 {case_vid} 当前未配置。"
                    "请确认数据属于哪个已配置的车型项目，或先完成项目绑定。"
                ),
                why="不同项目的源码、配置和输出定义不同，选错项目会引用错误代码。",
                candidates=sorted(str(key) for key in variants),
                blocking=True,
            )
        )
    elif explicit_vid and explicit_vid in variants:
        variant_id = explicit_vid
        variant_origin = "explicit_input"
    elif explicit_vid:
        status = "needs_confirmation"
        variant_origin = "explicit_input_unresolved"
        business_questions.append(
            _business_question(
                "choose_project",
                "variant_id",
                f"指定的项目 {explicit_vid} 当前未配置。请确认数据属于哪个已配置的车型项目。",
                why="不同项目的源码、配置和输出定义不同，选错项目会引用错误代码。",
                candidates=sorted(str(key) for key in variants),
                blocking=True,
            )
        )
    else:
        matches, match_mode = _match_variants(identity, variants)
        if matches:
            if len(matches) == 1:
                variant_id = matches[0]
                variant_origin = f"intake_identity_{match_mode}"
            else:
                status = "needs_confirmation"
                variant_origin = "intake_identity_ambiguous"
                variant_candidates = sorted(matches)
                business_questions.append(
                    _business_question(
                        "choose_project",
                        "coem",
                        (
                            "材料中的车型/客户信息匹配到多个已配置项目："
                            f"{'、'.join(variant_candidates)}。本次分析针对哪个项目？"
                        ),
                        why="不同项目的源码、配置和输出定义不同，选错项目会引用错误代码。",
                        candidates=variant_candidates,
                        blocking=True,
                    )
                )
        elif match_mode != "none":
            status = "needs_confirmation"
            variant_origin = "intake_identity_no_match"
            business_questions.append(
                _business_question(
                    "no_matching_project",
                    "coem",
                    (
                        f"材料显示车型 {identity.get('vehicle', '?')}、"
                        f"客户项目 {identity.get('coem', '?')}，"
                        "但当前没有已配置的对应项目。请确认信息或先完成项目绑定。"
                    ),
                    why="无法把数据绑定到任何已配置项目时，不能引用任意项目的代码作结论。",
                    blocking=True,
                )
            )
        else:
            # 材料没有任何已解析身份字段：唯一已配置项目可自动复用（正确身份自动复用）。
            if len(variants) == 1:
                variant_id = next(iter(variants))
                variant_origin = "single_configured_variant"
                diagnostics.append("identity_from_single_configured_variant")
            elif len(variants) == 0:
                status = "needs_confirmation"
                variant_origin = "no_configured_project"
                business_questions.append(
                    _business_question(
                        "no_configured_project",
                        "coem",
                        "当前没有已配置的项目。请先完成一次项目绑定（提供代码根目录与 COEM），或告知本次分析对应的车型项目。",
                        why="没有项目绑定时无法确定用哪份代码分析这份数据。",
                        blocking=True,
                    )
                )
            else:
                status = "needs_confirmation"
                variant_origin = "identity_missing_multiple_projects"
                business_questions.append(
                    _business_question(
                        "choose_project",
                        "coem",
                        "当前配置了多个项目，而材料中没有可识别的车型/客户信息。本次分析针对哪个项目？",
                        why="不同项目的源码、配置和输出定义不同，选错项目会引用错误代码。",
                        candidates=sorted(str(key) for key in variants),
                        blocking=True,
                    )
                )

    # ── 2. 绑定字段补全（来自 variant 配置的派生不算缺失） ─────────
    binding: dict[str, Any] = {}
    variant = variants.get(variant_id) if isinstance(variants, Mapping) else None
    variant = variant if isinstance(variant, Mapping) else {}
    if variant_id:
        binding["variant_id"] = variant_id
        for field, variant_key in (
            ("customer", "customer"),
            ("vehicle", "vehicle_project"),
            ("coem", "coem_project_dir"),
        ):
            if field not in identity and variant.get(variant_key):
                binding[field] = variant.get(variant_key)
                provenance[field] = {"source": "variant_config", "field": variant_key}
            elif field in identity:
                binding[field] = identity[field]
    else:
        for field in ("customer", "vehicle", "coem"):
            if field in identity:
                binding[field] = identity[field]

    for field in ("customer", "vehicle", "coem"):
        if field not in binding:
            missing.append(field)
    if "software_version" in identity:
        binding["software_version"] = identity["software_version"]
    else:
        missing.append("software_version")
    if "code_branch" in identity:
        binding["code_branch"] = identity["code_branch"]
    else:
        missing.append("code_branch")

    # ── 3. 版本/分支门（错版本不进入 runtime） ────────────────────
    version_gate: dict[str, Any] = {
        "checked": False,
        "status": "not_checked",
        "expected": {},
        "observed": {},
        "source": "",
    }
    if variant_id:
        expectations = _variant_expectations(variant, config)
        observed_branch = str(identity.get("code_branch") or "").strip()
        observed_version = str(identity.get("software_version") or "").strip()
        version_gate["expected"] = {k: v for k, v in expectations.items() if v}
        version_gate["observed"] = {
            key: value
            for key, value in (("code_branch", observed_branch), ("software_version", observed_version))
            if value
        }
        checks: list[dict[str, Any]] = []
        if expectations["code_branch"] and observed_branch:
            checks.append(
                {
                    "field": "code_branch",
                    "expected": expectations["code_branch"],
                    "observed": observed_branch,
                    "aligned": _norm(observed_branch) == _norm(expectations["code_branch"]),
                }
            )
        if expectations["software_version"] and observed_version:
            checks.append(
                {
                    "field": "software_version",
                    "expected": expectations["software_version"],
                    "observed": observed_version,
                    "aligned": _norm(observed_version) == _norm(expectations["software_version"]),
                }
            )
        if checks:
            version_gate["checked"] = True
            version_gate["status"] = (
                "aligned" if all(item["aligned"] for item in checks) else "mismatch"
            )
            version_gate["source"] = "variant_source_context"
            mismatched = [item for item in checks if not item["aligned"]]
            if mismatched:
                status = "blocked"
                for item in mismatched:
                    field_label = FIELD_BUSINESS_TERMS.get(item["field"], item["field"])
                    conflicts.append(
                        {
                            "field": item["field"],
                            "expected": item["expected"],
                            "observed": item["observed"],
                            "reason": "version_gate_mismatch",
                        }
                    )
                    business_questions.append(
                        _business_question(
                            f"version_mismatch_{item['field']}",
                            item["field"],
                            (
                                f"材料中的{field_label}（{item['observed']}）与项目 "
                                f"{variant_id} 的期望值（{item['expected']}）不一致。"
                                "请确认这份数据是否属于该项目。"
                            ),
                            why=(
                                "版本/分支不一致时，当前项目代码可能无法解释这份录制数据；"
                                "继续分析会得到与实际运行不符的结论，因此已暂停。"
                            ),
                            candidates=[item["expected"]],
                            blocking=True,
                        )
                    )
        elif expectations["code_branch"] and not observed_branch:
            if not observed_version:
                # 项目声明了期望分支且材料连版本都没有：这是影响结果的关键输入。
                status = "needs_confirmation" if status == "resolved" else status
                business_questions.append(
                    _business_question(
                        "missing_software_version",
                        "software_version",
                        (
                            f"未能从材料中确定录制数据对应的软件版本"
                            f"（项目 {variant_id} 期望分支 {expectations['code_branch']}）。"
                            "请提供软件版本号，用于核对代码分支。"
                        ),
                        why=FIELD_MISSING_IMPACT["software_version"],
                        blocking=True,
                    )
                )
            else:
                # 版本已知但版本→分支映射尚未提供：不把技术映射问题抛给用户。
                version_gate["status"] = "not_checked"
                version_gate["source"] = "version_to_branch_mapping_unavailable"
                diagnostics.append(
                    "version_gate_not_checked: software_version known but version-to-branch mapping not configured"
                )

    if status == "blocked":
        binding_status_note = "runtime_binding_blocked"
    elif status == "needs_confirmation":
        binding_status_note = "awaiting_user_confirmation"
    else:
        binding_status_note = "runtime_binding_ready"

    intake_ref: dict[str, Any] = {}
    if intake_path:
        intake_ref["path"] = str(intake_path)
        resolved = Path(str(intake_path)).expanduser()
        intake_ref["exists"] = resolved.is_file()
        if not intake_sha256 and resolved.is_file():
            intake_sha256 = _sha256_file(resolved) or ""
        if intake_sha256:
            intake_ref["sha256"] = intake_sha256

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "binding_status_note": binding_status_note,
        "binding": binding,
        "identity": {
            "resolved": {key: identity[key] for key in BINDING_FIELDS + ("ticket_id",) if key in identity},
            "missing": missing,
        },
        "variant": {
            "variant_id": variant_id,
            "origin": variant_origin,
            "candidates": variant_candidates,
        },
        "version_gate": version_gate,
        "business_questions": business_questions,
        "missing": missing,
        "conflicts": conflicts,
        "intake_ref": intake_ref,
        "provenance": provenance,
        "diagnostics": diagnostics,
    }
    if isinstance(intake, Mapping) and intake.get("handoff_id"):
        payload["intake_handoff_id"] = intake.get("handoff_id")
    if isinstance(intake, Mapping):
        payload["intake_status"] = intake.get("intake_status") or intake.get("status")
    return payload


def load_intake_artifact(path: str | Path) -> tuple[dict[str, Any] | None, str]:
    """读取 intake JSON artifact；返回 (payload, sha256)。不可读返回 (None, "")。"""
    resolved = Path(str(path)).expanduser()
    if not resolved.is_file():
        return None, ""
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, ""
    if not isinstance(payload, dict):
        return None, ""
    sha = _sha256_file(resolved) or ""
    return payload, sha


__all__ = [
    "SCHEMA_VERSION",
    "BINDING_FIELDS",
    "bind_intake_identity",
    "load_intake_artifact",
]
