"""Evidence-bound textual explanation for a selected alarm event.

This is a report read-model service, not a feature rule engine.  It turns the
already projected event, condition trace and cross-layer timeline into short
Chinese engineering statements.  The service deliberately returns an
``indeterminate`` alarm assessment when the available evidence cannot prove
the selected code path or the final CAN output.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re
from typing import Any, Mapping


SCHEMA_VERSION = "diagnostic-narrative.v1"


_FACT_HINTS: tuple[tuple[str, int], ...] = (
    ("frameid", 110),
    ("objid", 108),
    ("carspd", 106),
    ("actual_spd", 106),
    ("actual_gear", 100),
    ("gear", 96),
    ("distx", 94),
    ("disty", 94),
    ("velabsx", 94),
    ("velabsy", 94),
    ("velx", 92),
    ("vely", 92),
    ("finter", 91),
    ("fint", 90),
    ("ttm", 89),
    ("fttc", 91),
    ("fddci", 90),
    ("yaw", 88),
    ("length", 86),
    ("width", 86),
    ("bfc", 84),
    ("warning", 84),
    ("flag", 82),
    ("roi", 80),
    ("brake", 78),
    ("dynflg", 76),
    ("lifecycle", 72),
    ("position.x", 88),
    ("position.y", 88),
    ("velocity.x_dot", 86),
    ("velocity.y_dot", 86),
    ("scale_x", 84),
    ("scale_y", 84),
    ("orientation", 74),
    ("radar_info", 68),
    ("data[", 35),
)


def _fact_token(row: Mapping[str, Any]) -> str:
    return str(row.get("token") or row.get("code_token") or row.get("access_path") or "").strip()


def _fact_family(token: str) -> str:
    """Collapse equivalent pointer/array prefixes for first-screen ranking."""
    return str(token or "").replace("->", ".").rsplit(".", 1)[-1].lower()


def _fact_value_is_displayable(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        # GDB can return a complete C struct as one string.  It remains in
        # the raw observation, but is not a useful first-screen fact.
        return bool(value.strip()) and len(value) <= 180 and not value.lstrip().startswith("(")
    return isinstance(value, (bool, int, float))


def _fact_score(row: Mapping[str, Any]) -> int:
    token = _fact_token(row).lower()
    score = 0
    for hint, weight in _FACT_HINTS:
        if hint in token:
            score = max(score, weight)
    if token == "i" or token.endswith("[i]"):
        score = max(score, 112)
    if not _fact_value_is_displayable(row.get("value")):
        score -= 1000
    return score


def _feature_hint(function: str) -> str:
    normalized = str(function or "").lower().replace("_", "")
    for token in ("fcta", "fctb", "rcta", "rctb", "rcw", "lca", "bsd", "dow"):
        if token in normalized:
            return token
    return ""


def _fact_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        items = value.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, Mapping)]
        if _fact_token(value):
            return [value]
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _select_facts(
    rows: list[Mapping[str, Any]],
    *,
    limit: int,
    preferred_tokens: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Select useful first-screen facts while retaining real source tokens."""
    candidates: list[tuple[int, int, Mapping[str, Any]]] = []
    for order, row in enumerate(rows):
        token = _fact_token(row)
        if not token or not _fact_value_is_displayable(row.get("value")):
            continue
        token_lower = token.lower()
        preferred_score = max((35 for hint in preferred_tokens if hint and hint.lower() in token_lower), default=0)
        candidates.append((_fact_score(row) + preferred_score, -order, row))
    candidates.sort(reverse=True, key=lambda item: (item[0], item[1]))
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, _, row in candidates:
        token = _fact_token(row)
        key = _fact_family(token) or token.lower()
        if key in seen:
            continue
        seen.add(key)
        selected.append({
            "token": token,
            "value": row.get("value"),
            "unit": row.get("unit"),
            "status": row.get("status") or row.get("evidence_status") or row.get("source_kind") or "observed_or_derived",
            "source_kind": row.get("source_kind") or row.get("source") or "not_available",
            "source": row.get("source") or row.get("source_ref"),
        })
        if len(selected) >= max(1, int(limit)):
            break
    # Sorting by source order makes the prose stable and easier to compare
    # with the original ego/target table after priority selection.
    order_by_token = { _fact_token(row): index for index, row in enumerate(rows) }
    selected.sort(key=lambda row: order_by_token.get(row["token"], 10**9))
    return selected


def _format_fact(row: Mapping[str, Any]) -> str:
    token = _fact_token(row) or "not_available"
    value = row.get("value")
    if isinstance(value, float):
        value_text = f"{value:.6g}"
    else:
        value_text = str(value)
    unit = str(row.get("unit") or "").strip()
    return f"{token}={value_text}{(' ' + unit) if unit else ''}"


def _collect_operating_facts(event: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    details = event.get("details") if isinstance(event.get("details"), Mapping) else event
    summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
    selected_target_id = str(summary.get("target_obj_id") or "")
    groups: dict[str, list[dict[str, Any]]] = {}
    function_hint = _feature_hint(str(summary.get("function") or ""))
    preferred_tokens = (function_hint,) if function_hint else ()
    for group_name in ("ego", "target"):
        group = details.get(group_name) if isinstance(details, Mapping) and isinstance(details.get(group_name), Mapping) else {}
        groups[group_name] = _select_facts(
            _fact_rows(group.get("fields")),
            limit=14,
            preferred_tokens=preferred_tokens if group_name == "target" else (),
        )

    runtime_rows: list[dict[str, Any]] = []
    observations = [item for item in event.get("runtime_observations", []) or [] if isinstance(item, Mapping)]
    for observation_order, observation in enumerate(observations):
        identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else {}
        layer = str(observation.get("layer") or "runtime")
        if layer == "objectlist_candidate" and selected_target_id:
            observation_object_id = str(identity.get("object_id") or "")
            # Do not surface every object in a public object-list callback.
            # Only an explicit identity match is relevant to the selected
            # event; an absent/zero identity is not a match.
            if observation_object_id != selected_target_id:
                continue
        observation_rows = _fact_rows(observation.get("fields"))
        filtered_rows: list[Mapping[str, Any]] = []
        for row in observation_rows:
            token = _fact_token(row).lower()
            value = row.get("value")
            # Generic public arrays are useful only when the value is active;
            # a page full of zero warning slots hides the selected function.
            if layer == "runtime_with_frame" and token.startswith("warning_status_with_frame.data[") and value in (0, False, "0"):
                continue
            if layer == "runtime_with_frame" and token.startswith("radar_info.data[") and value in (0, False, "0"):
                continue
            if layer == "objectlist_candidate" and token.endswith(".id") and value in (0, False, "0") and identity.get("object_id") not in (None, "", 0, "0"):
                continue
            if layer == "objectlist_candidate" and value in (0, False, "0") and any(
                marker in token for marker in (".position.z", ".position.dx", ".position.dy", ".position.dz", ".velocity.dx", ".velocity.dy", ".velocity.dz", "_unc", "obj_conf", "class_conf", "obj_class", ".age", "last_frame_update", ".power", ".rcs", ".azimuth", ".elevation")
            ):
                continue
            filtered_rows.append(row)
        for field in _select_facts(filtered_rows, limit=20, preferred_tokens=preferred_tokens):
            field["layer"] = layer
            field["frame_id"] = identity.get("frame_id") or observation.get("frame_id")
            field["association"] = identity.get("frame_source") or observation.get("association_status") or "not_available"
            field["object_id"] = identity.get("object_id")
            field["_observation_order"] = observation_order
            runtime_rows.append(field)
    layer_rank = {"gdb_observation": 0, "runtime_with_frame": 1, "can_tx_observation": 1, "objectlist_candidate": 2}
    runtime_rows.sort(key=lambda row: (
        layer_rank.get(str(row.get("layer")), 3),
        -_fact_score(row),
        int(row.get("_observation_order", 0)),
    ))
    bounded: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in runtime_rows:
        key = (
            str(row.get("layer") or "runtime"),
            _fact_token(row),
            str(row.get("frame_id") or ""),
            repr(row.get("value")),
        )
        if key in seen:
            continue
        seen.add(key)
        row.pop("_observation_order", None)
        bounded.append(row)
        if len(bounded) >= 42:
            break
    return groups, bounded


def _condition_priority(
    row: Mapping[str, Any],
    order: int,
    feature_hint: str = "",
    side_hint: str = "",
) -> tuple[int, int, int, int, int, int, int, int]:
    evaluation = row.get("evaluation") if isinstance(row.get("evaluation"), Mapping) else {}
    status = str(evaluation.get("status") or "not_evaluable")
    expression = str(row.get("expression") or "").lower()
    missing = len(row.get("missing_tokens", []) or [])
    feature_terms = ("fcta", "fctb", "rcta", "rctb", "rcw", "lca", "bsd", "dow")
    explicit_feature = next((term for term in feature_terms if term in expression), "")
    if feature_hint and explicit_feature:
        feature_rank = 0 if explicit_feature == feature_hint else 2
    else:
        feature_rank = 1
    side_rank = 1
    if side_hint and ("left" in expression or "right" in expression):
        expected_side = "right" if str(side_hint).upper() == "R" else "left" if str(side_hint).upper() == "L" else ""
        if expected_side:
            side_rank = 0 if expected_side in expression else 2
    stage, _ = _condition_flow_category(expression)
    stage_rank = {
        "state_machine": 0,
        "motion": 1,
        "target": 2,
        "roi": 3,
        "prediction": 4,
        "output": 5,
        "source": 6,
    }.get(stage, 6)
    chain_relation = str(row.get("chain_relation") or "")
    if stage == "state_machine":
        stage_detail_rank = (
            0 if "systemstate" in expression and "adaswarning" in expression
            else 1 if "systemstate" in expression
            else 2 if "enable" in expression
            else 3 if any(item in expression for item in ("dtc", "selfinsp", "failure", "calibrat", "brakenotready"))
            else 4
        )
    elif stage == "motion":
        stage_detail_rank = 0 if any(item in expression for item in ("carspd", "carspeed", "vehicle_speed")) else 1
    elif stage == "target":
        has_dyn_field = bool(re.search(r"(?:->|\.)dynflg\b", expression))
        stage_detail_rank = (
            0 if has_dyn_field and chain_relation == "event_callee" and "sobj" in expression
            else 1 if has_dyn_field
            else 2 if any(item in expression for item in ("objtype", "objid", "track"))
            else 3
        )
    elif stage == "output":
        stage_detail_rank = 0 if "warningnum" in expression else 1
    else:
        stage_detail_rank = 0
    if status in {"satisfied", "not_satisfied"}:
        status_rank = 0
    elif missing <= 1:
        status_rank = 1
    else:
        status_rank = 2
    core_rank = 0 if any(item in expression for item in ("fttmx", "fttmxobj", "fttmy", "finter", "fddci")) else 1
    signal_rank = 0 if any(item in expression for item in ("warning", "roi", "ttc", "ddci", "flag", "brake", "spd", "vel", "dist")) else 1
    return stage_rank, stage_detail_rank, feature_rank, side_rank, status_rank, core_rank, signal_rank, order


def _condition_in_scope(row: Mapping[str, Any], *, feature_hint: str, side_hint: str) -> bool:
    expression = str(row.get("expression") or "").lower()
    feature_terms = ("fcta", "fctb", "rcta", "rctb", "rcw", "lca", "bsd", "dow")
    if feature_hint:
        explicit_feature = next((term for term in feature_terms if term in expression), "")
        if explicit_feature and explicit_feature != feature_hint:
            return False
    if str(side_hint or "").upper() in {"L", "R"} and ("left" in expression or "right" in expression):
        expected_side = "right" if str(side_hint).upper() == "R" else "left"
        if expected_side not in expression and "left" not in expression and "right" not in expression:
            return True
        # A compound condition containing both sides is shared by both sides;
        # a single opposite-side branch is not part of this event's scope.
        if expected_side not in expression and ("left" in expression or "right" in expression):
            return False
    return True


def _condition_missing_digest(rows: list[Mapping[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for token in row.get("missing_tokens", []) or []:
            text = str(token).strip()
            if text:
                counts[text] += 1
    return [token for token, _ in counts.most_common(12)]


def _condition_row_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    counts = {"total": len(rows), "satisfied": 0, "not_satisfied": 0, "not_evaluable": 0, "unsupported": 0}
    for row in rows:
        evaluation = row.get("evaluation") if isinstance(row.get("evaluation"), Mapping) else {}
        status = str(evaluation.get("status") or "not_evaluable")
        if status not in counts:
            status = "not_evaluable"
        counts[status] += 1
    return counts


def _condition_alias_hints(
    rows: list[Mapping[str, Any]],
    runtime_facts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Find pointer/dot spelling candidates without binding them as aliases."""
    observed = {_fact_token(item): item for item in runtime_facts if _fact_token(item)}
    normalized_observed = {}
    for token in observed:
        normalized = token.replace("->", ".").replace("*", "").strip()
        normalized_observed.setdefault(normalized, []).append(token)
    hints: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        for missing in row.get("missing_tokens", []) or []:
            missing_token = str(missing).strip()
            normalized = missing_token.replace("->", ".").replace("*", "").strip()
            for runtime_token in normalized_observed.get(normalized, []):
                key = (missing_token, runtime_token)
                if key in seen or missing_token == runtime_token:
                    continue
                seen.add(key)
                hints.append({
                    "missing_token": missing_token,
                    "observed_token": runtime_token,
                    "reason": "pointer/dot spelling is similar; source alias is not proven",
                })
    return hints[:12]


def _as_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _match_scope(row: Mapping[str, Any], *, function: str, side: str, radar_id: Any) -> bool:
    actual_function = str(row.get("function") or row.get("signal") or "").upper()
    if function and actual_function and actual_function != function.upper() and not actual_function.startswith(function.upper() + "_"):
        return False
    if side and row.get("side") not in (None, "") and str(row.get("side")).upper() != side.upper():
        return False
    if radar_id not in (None, "") and row.get("radar_id") not in (None, "") and str(row.get("radar_id")) != str(radar_id):
        return False
    return True


def _condition_assessment(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(trace, Mapping):
        return {
            "status": "not_available",
            "counts": {"total": 0, "satisfied": 0, "not_satisfied": 0, "not_evaluable": 0, "unsupported": 0},
            "evaluated": False,
        }
    summary = trace.get("summary") if isinstance(trace.get("summary"), Mapping) else {}
    counts = {
        key: int(summary.get(key, 0) or 0)
        for key in ("total", "satisfied", "not_satisfied", "not_evaluable", "unsupported")
    }
    if counts["total"] == 0:
        status = "not_available"
    elif counts["not_evaluable"] or counts["unsupported"]:
        status = "not_evaluable"
    elif counts["not_satisfied"] and counts["satisfied"]:
        status = "mixed"
    elif counts["not_satisfied"]:
        status = "selected_conditions_not_satisfied"
    else:
        status = "all_selected_conditions_satisfied"
    return {"status": status, "counts": counts, "evaluated": not bool(counts["not_evaluable"] or counts["unsupported"])}


def _resolve_output_policy(
    *,
    requested_endpoint: str,
    can_data_status: str,
    can_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Choose the alarm endpoint without making CAN a default prerequisite."""
    requested = str(requested_endpoint or "auto").strip().lower()
    if requested not in {"auto", "algorithm", "can", "can_tx"}:
        requested = "auto"
    data_status = str(can_data_status or "not_detected").strip().lower()
    if data_status not in {"present", "absent", "not_detected", "unknown"}:
        data_status = "unknown"
    if data_status in {"not_detected", "unknown"} and can_rows:
        data_status = "present"
    if requested == "algorithm":
        effective = "algorithm"
        reason = "caller_selected_algorithm_output"
    elif requested in {"can", "can_tx"}:
        effective = "can_tx"
        reason = "caller_selected_can_tx"
    else:
        # The arte visualization alarm lamp is the product-level output for
        # this diagnostic tool. CAN remains optional downstream evidence and
        # does not change the report endpoint unless explicitly requested.
        effective = "algorithm"
        reason = "arbe_alarm_lamp_is_canonical_endpoint"
    can_required = effective == "can_tx"
    return {
        "requested_endpoint": requested,
        "can_data_status": data_status,
        "effective_endpoint": effective,
        "output_authority": "can_tx" if effective == "can_tx" else "algorithm",
        "can_required": can_required,
        "algorithm_output_is_terminal": effective == "algorithm",
        "can_observation_count": len(can_rows),
        "reason": reason,
        "statement": (
            "CAN 数据在当前输入中可用，优先以 CAN Tx 作为输出终点。"
            if effective == "can_tx"
            else "本报告以 arbe 可视化工具报警灯对应的算法最终输出作为报警终点。"
        ),
    }


def _condition_lines(
    trace: Mapping[str, Any] | None,
    *,
    max_items: int,
    feature_hint: str = "",
    side_hint: str = "",
) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    lines: list[str] = []
    if not isinstance(trace, Mapping):
        return items, lines
    all_rows = _as_rows(trace.get("conditions"))
    ranked = sorted(
        [
            (index, row)
            for index, row in enumerate(all_rows)
            if _condition_in_scope(row, feature_hint=feature_hint, side_hint=side_hint)
        ],
        key=lambda item: _condition_priority(item[1], item[0], feature_hint, side_hint),
    )
    limit = max(1, int(max_items))
    # Keep the compact story representative of the source chain.  One row is
    # selected from each stage that the current source actually exposes, then
    # the remaining slots are filled by the source/feature priority ranking.
    # This prevents a large block of satisfied leaf conditions from hiding an
    # unevaluable system gate or target dyn/track filter.
    # This order is only a first-screen coverage preference.  Execution truth
    # remains the source-provided condition_chain order; no stage is required
    # for a project that does not expose it.
    presentation_stage_order = ("state_machine", "motion", "target", "roi", "prediction", "output", "source")
    selected_indexes: set[int] = set()
    for stage in presentation_stage_order:
        candidate = next(
            (
                index for index, row in ranked
                if index not in selected_indexes and _condition_flow_category(str(row.get("expression") or ""))[0] == stage
            ),
            None,
        )
        if candidate is not None:
            selected_indexes.add(candidate)
        if len(selected_indexes) >= limit:
            break
    for index, _ in ranked:
        if len(selected_indexes) >= limit:
            break
        selected_indexes.add(index)
    # Preserve source order in the report.  The ranking only decides which
    # rows are important enough for the first-screen explanation.
    for index, row in enumerate(all_rows):
        if index not in selected_indexes:
            continue
        evaluation = row.get("evaluation") if isinstance(row.get("evaluation"), Mapping) else {}
        source = row.get("source_ref") if isinstance(row.get("source_ref"), Mapping) else {}
        status = str(evaluation.get("status") or "not_evaluable")
        source_text = f"{source.get('file_path', 'source') }:{source.get('line', '')}".rstrip(":")
        expression = str(row.get("expression") or "").strip()
        substituted = str(row.get("substituted_expression") or expression).strip()
        reason = str(evaluation.get("reason") or "")
        missing = [str(item) for item in row.get("missing_tokens", []) or []]
        item = {
            "condition_id": row.get("condition_id"),
            "function": row.get("function"),
            "source_ref": deepcopy(dict(source)),
            "status": status,
            "expression": expression,
            "substituted_expression": substituted,
            "reason": reason,
            "missing_tokens": missing,
            "bindings": deepcopy(row.get("bindings") or []),
        }
        for key in (
            "condition_kind",
            "chain_function",
            "chain_relation",
            "chain_function_order",
            "chain_source_order",
            "chain_call_site_line",
        ):
            if row.get(key) not in (None, ""):
                item[key] = row.get(key)
        items.append(item)
        if status == "satisfied":
            lines.append(f"{source_text} 的条件 `{expression}` 已代入 `{substituted}`，求值为 true。")
        elif status == "not_satisfied":
            lines.append(f"{source_text} 的条件 `{expression}` 代入 `{substituted}` 后为 false；该条件路径当前未满足。")
        elif status == "unsupported":
            lines.append(f"{source_text} 的条件 `{expression}` 无法由安全求值器处理：{reason}。")
        else:
            missing_text = ", ".join(missing) if missing else reason
            lines.append(f"{source_text} 的条件 `{expression}` 暂不能判断；缺少运行时量：{missing_text or 'not_available'}。")
    if len(all_rows) > len(selected_indexes):
        lines.append(
            f"其余 {len(all_rows) - len(selected_indexes)} 条候选条件保留在 condition-trace artifact 中；"
            "当前只展示影响报警判断的关键条件。"
        )
    return items, lines


def _condition_flow_category(expression: str) -> tuple[str, str]:
    """Give a source condition a display category without feature rules."""
    token = re.sub(r"[^a-z0-9_]", "", str(expression or "").lower())
    if any(item in token for item in ("systemstate", "selfinsp", "calibrating", "failureflg", "brakenotready", "standby", "passive", "init")):
        return "state_machine", "状态机/系统门"
    if "adaswarning" in token or "warningnum" in token or "output" in token or "send" in token or "publish" in token:
        return "output", "输出/汇总"
    if "roi" in token or "polygon" in token:
        return "roi", "ROI/区域"
    if any(item in token for item in ("ttm", "ttc", "inter", "ddci", "collision", "cross")):
        return "prediction", "预测/时空"
    if (
        re.search(r"(?:->|\.)dynflg\b", str(expression or "").lower())
        or any(item in token for item in ("objtype", "objid", "track", "history", "lastobj", "object"))
    ):
        return "target", "目标筛选"
    if any(item in token for item in ("warning", "flag", "enable", "valid")):
        return "state_machine", "状态机/对象状态"
    if any(item in token for item in ("spd", "speed", "vel", "yaw", "gear", "accel")):
        return "motion", "自车/运动"
    return "source", "源码条件"


def _flow_condition_rows(condition_items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(condition_items, start=1):
        if not isinstance(item, Mapping):
            continue
        expression = str(item.get("expression") or "")
        category, category_label = _condition_flow_category(expression)
        status = str(item.get("status") or "not_evaluable")
        source = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
        if status == "satisfied":
            explanation = "代入后的表达式求值为 true，当前证据支持该条件。"
        elif status == "not_satisfied":
            explanation = "代入后的表达式求值为 false，该分支条件当前未满足。"
        elif status == "unsupported":
            explanation = "当前安全求值器不支持该表达式，不能把它当成 false。"
        else:
            explanation = "缺少同帧运行时量，当前不能判断该条件。"
        result.append({
            "step_id": str(item.get("condition_id") or f"condition-{index}"),
            "stage": "source_condition",
            "category": category,
            "category_label": category_label,
            "status": status,
            "source_ref": deepcopy(dict(source)),
            "expression": expression,
            "substituted_expression": str(item.get("substituted_expression") or expression),
            "bindings": deepcopy(item.get("bindings") or []),
            "missing_tokens": [str(value) for value in item.get("missing_tokens", []) or []],
            "reason": str(item.get("reason") or ""),
            "explanation": explanation,
        })
    return result


def _build_analysis_flow(
    *,
    event: Mapping[str, Any],
    summary: Mapping[str, Any],
    operating_facts: Mapping[str, Any],
    condition_items: Sequence[Mapping[str, Any]],
    condition_digest: Mapping[str, Any],
    condition_counts: Mapping[str, Any],
    geometry_projection: Mapping[str, Any] | None,
    output_chain: Mapping[str, Any] | None,
    output_policy: Mapping[str, Any],
    alert_status: str,
    should_alert: str,
    alert_statement: str,
) -> dict[str, Any]:
    """Build the compact, ordered explanation consumed by HTML and Pi.

    This is a read model. It orders already observed/derived facts and source
    condition evaluations; it never evaluates a new feature rule or infers a
    missing branch.
    """
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    target_id = summary.get("target_obj_id")
    conditions = _flow_condition_rows(condition_items)
    projection = geometry_projection if isinstance(geometry_projection, Mapping) else {}
    current_relation = str(projection.get("collision_status") or "not_evaluated")
    prediction = projection.get("predicted_intersection") if isinstance(projection.get("predicted_intersection"), Mapping) else {}
    geometry_status = "observed" if current_relation.startswith("observed_") else "derived" if current_relation.startswith("source_derived_") else "not_evaluated"
    condition_status = "partial" if any(item.get("status") in {"not_evaluable", "unsupported"} for item in conditions) else "ready"
    ego_facts = [dict(item) for item in operating_facts.get("ego", []) or [] if isinstance(item, Mapping)]
    target_facts = [dict(item) for item in operating_facts.get("target", []) or [] if isinstance(item, Mapping)]
    supporting_conditions = [
        {
            "source_ref": deepcopy(item.get("source_ref") or {}),
            "expression": item.get("expression"),
            "substituted_expression": item.get("substituted_expression"),
        }
        for item in conditions
        if item.get("status") == "satisfied"
    ]
    not_satisfied_conditions = [
        {
            "source_ref": deepcopy(item.get("source_ref") or {}),
            "expression": item.get("expression"),
            "substituted_expression": item.get("substituted_expression"),
        }
        for item in conditions
        if item.get("status") == "not_satisfied"
    ]
    return {
        "schema_version": "diagnostic-analysis-flow.v1",
        "status": "partial" if condition_status == "partial" or geometry_status == "not_evaluated" else "ready",
        "steps": [
            {
                "step_id": "input_context",
                "order": 1,
                "kind": "input_context",
                "title": "输入工况",
                "status": "observed" if event else "not_available",
                "scope": {
                    "function": summary.get("function"),
                    "side": summary.get("side"),
                    "radar_id": summary.get("radar_id"),
                    "frame_id": first.get("frame_id"),
                    "target_obj_id": target_id,
                },
                "ego_facts": ego_facts,
                "target_facts": target_facts,
                "summary": "先固定报警功能、侧别、雷达、分析帧、目标 ID 及同帧自车/目标属性。",
            },
            {
                "step_id": "source_condition_walk",
                "order": 2,
                "kind": "source_condition_walk",
                "title": "代码条件逐级代入",
                "status": condition_status,
                "scope": condition_digest.get("scope"),
                "counts": deepcopy(dict(condition_counts)),
                "conditions": conditions,
                "summary": "按当前 source 的源代码顺序展示真实表达式、同帧值代入和求值结果；不同 if/else 分支不强行拼成一个 AND 链。",
            },
            {
                "step_id": "geometry_and_prediction",
                "order": 3,
                "kind": "geometry_and_prediction",
                "title": "当前几何与预测关系",
                "status": geometry_status,
                "current_relation": current_relation,
                "prediction": deepcopy(dict(prediction)) if prediction else {},
                "algorithm_branch": deepcopy(dict(projection.get("algorithm_branch") or {})) if isinstance(projection.get("algorithm_branch"), Mapping) else {},
                "summary": "当前目标 polygon/ROI 关系与代码预测穿越关系分开呈现，不能用报警结果反推当前矩形已进入 ROI。",
            },
            {
                "step_id": "output_decision",
                "order": 4,
                "kind": "output_decision",
                "title": "算法报警输出",
                "status": alert_status,
                "should_alert": should_alert,
                "output_policy": deepcopy(dict(output_policy)),
                "statement": alert_statement,
                "supporting_conditions": supporting_conditions[:12],
                "not_satisfied_conditions": not_satisfied_conditions[:8],
                "summary": "最后根据当前选定的报警输出端点给出结论；缺失变量只作为缺口，不被默认为 false。",
            },
            {
                "step_id": "fct_output_mapping",
                "order": 5,
                "kind": "fct_output_mapping",
                "title": "FCT / 对外映射链",
                "status": str((output_chain or {}).get("status") or "not_available"),
                "output_chain": deepcopy(dict(output_chain or {})),
                "summary": "报警输出之后，沿当前源码查找 FCT/ASW 内部信号、对外映射和发送函数；源码候选与同帧运行时值分开标注。",
            },
        ],
        "policy": "The flow is an evidence-bound read model: source order and explicit facts are shown, missing/unsupported conditions remain indeterminate, and AI may explain but cannot create observed facts.",
    }


def _story_source_text(item: Mapping[str, Any]) -> str:
    source = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
    function = str(item.get("chain_function") or item.get("function") or "").strip()
    prefix = f"{function} @ " if function else ""
    return f"{prefix}{source.get('file_path', 'source')}:{source.get('line', 'N/A')}"


def _story_binding_text(item: Mapping[str, Any]) -> str:
    bindings = [binding for binding in item.get("bindings", []) or [] if isinstance(binding, Mapping) and binding.get("status") == "bound"]
    return "；".join(
        f"{_fact_token(binding) or binding.get('token') or 'token'}={binding.get('value')}"
        + (f" {binding.get('unit')}" if binding.get('unit') else "")
        for binding in bindings
    )


def _story_binding_preview(item: Mapping[str, Any], *, limit: int = 8) -> str:
    bindings = [binding for binding in item.get("bindings", []) or [] if isinstance(binding, Mapping) and binding.get("status") == "bound"]
    values = []
    for binding in bindings[: max(1, int(limit))]:
        token = _fact_token(binding) or binding.get("token") or "token"
        value = binding.get("value")
        unit = f" {binding.get('unit')}" if binding.get("unit") else ""
        values.append(f"{token}={value}{unit}")
    suffix = f"；另有 {len(bindings) - len(values)} 个已绑定值见表格" if len(bindings) > len(values) else ""
    return "；".join(values) + suffix


def _normalise_member_token(value: Any) -> str:
    """Compare C/C++ member paths without changing the displayed token."""
    return re.sub(r"\s+", "", str(value or "")).replace("->", ".").lower()


def _runtime_value_for_token(
    token: str,
    facts: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    wanted = _normalise_member_token(token)
    if not wanted:
        return None
    for item in facts:
        candidate = _fact_token(item)
        if candidate and _normalise_member_token(candidate) == wanted:
            return item
    return None


def _build_output_chain(
    *,
    can_output: Mapping[str, Any] | None,
    algorithm_output_facts: Sequence[Mapping[str, Any]],
    runtime_facts: Sequence[Mapping[str, Any]],
    function: str = "",
    side: str = "",
) -> dict[str, Any]:
    """Build the source-derived output path after the algorithm alarm.

    The chain is deliberately feature-neutral.  It consumes whatever output
    rows the active source provider found and reports lexical/source/runtime
    status separately.  A source assignment is never upgraded to a runtime
    observation merely because it looks like the expected path.
    """
    payload = can_output if isinstance(can_output, Mapping) else {}
    rows = [item for item in payload.get("signals", []) or [] if isinstance(item, Mapping)]
    source_chain = payload.get("source_output_chain") if isinstance(payload.get("source_output_chain"), Mapping) else {}
    output_steps: list[dict[str, Any]] = []
    feature = _feature_hint(function)
    side_token = re.sub(r"[^a-z0-9]", "", str(side or "").lower())
    scoped_algorithm_facts = [
        item for item in algorithm_output_facts
        if (
            not feature
            or not side_token
            or f"b{('left' if side_token == 'l' else 'right' if side_token == 'r' else side_token)}{feature}" in re.sub(r"[^a-z0-9]", "", _fact_token(item).lower())
        )
    ]
    if not scoped_algorithm_facts:
        scoped_algorithm_facts = list(algorithm_output_facts)
    algorithm_fact = next(
        (
            item for item in scoped_algorithm_facts
            if _fact_value_is_displayable(item.get("value"))
            and item.get("value") not in (None, 0, False, "0", "")
        ),
        None,
    )
    if algorithm_fact is not None:
        output_steps.append({
            "order": 1,
            "kind": "algorithm_output",
            "status": "observed",
            "token": _fact_token(algorithm_fact),
            "value": algorithm_fact.get("value"),
            "source": deepcopy(dict(algorithm_fact.get("source") or {})) if isinstance(algorithm_fact.get("source"), Mapping) else {},
            "text": (
                f"算法层已在同一分析帧观测到 `{_fact_token(algorithm_fact)}`="
                f"{algorithm_fact.get('value')}；这就是本报告采用的 arbe 报警灯对应算法输出终点。"
            ),
        })
    elif scoped_algorithm_facts:
        algorithm_fact = scoped_algorithm_facts[0]
        output_steps.append({
            "order": 1,
            "kind": "algorithm_output",
            "status": "observed_zero_or_unknown",
            "token": _fact_token(algorithm_fact),
            "value": algorithm_fact.get("value"),
            "source": deepcopy(dict(algorithm_fact.get("source") or {})) if isinstance(algorithm_fact.get("source"), Mapping) else {},
            "text": f"算法层观测到 `{_fact_token(algorithm_fact)}`={algorithm_fact.get('value')}，当前值没有证明为非零报警。",
        })
    else:
        output_steps.append({
            "order": 1,
            "kind": "algorithm_output",
            "status": "not_available",
            "token": "adasWarning output token not_available",
            "value": None,
            "source": {},
            "text": "当前没有找到可与选定事件同帧绑定的 adasWarning 输出字段。",
        })

    for row in rows[:12]:
        signal = str(row.get("signal") or "").strip()
        expression = str(row.get("expression") or "").strip()
        internal_paths = [str(item) for item in row.get("internal_member_paths", []) or [] if str(item).strip()]
        assignments = [item for item in row.get("internal_assignments", []) or [] if isinstance(item, Mapping)]
        active_assignments = [item for item in assignments if item.get("active") is True]
        producer_function_names = [str(item) for item in row.get("producer_function_names", []) or [] if str(item).strip()]
        producer_function_refs = [item for item in row.get("producer_function_refs", []) or [] if isinstance(item, Mapping)]
        internal_token = internal_paths[0] if internal_paths else ""
        runtime_internal = _runtime_value_for_token(internal_token, runtime_facts) if internal_token else None
        algorithm_tokens = {
            _normalise_member_token(_fact_token(item))
            for item in scoped_algorithm_facts
            if _fact_token(item)
        }
        primary_assignment = next(
            (
                item for item in active_assignments
                if any(
                    token and token in _normalise_member_token(" ".join(str(item.get(key) or "") for key in ("rhs", "snippet")))
                    for token in algorithm_tokens
                )
            ),
            active_assignments[0] if active_assignments else None,
        )
        primary_assignment_line = (
            ((primary_assignment.get("source_ref") or {}).get("line"))
            if isinstance(primary_assignment, Mapping) else None
        )
        producer_definition = next(
            (
                item for item in producer_function_refs
                if str(((item.get("source_ref") or {}).get("path") or "")).lower().endswith((".c", ".cc", ".cpp"))
                and ((item.get("source_ref") or {}).get("line")) != primary_assignment_line
            ),
            producer_function_refs[0] if producer_function_refs else None,
        )
        producer_location = ""
        if isinstance(producer_definition, Mapping):
            ref = producer_definition.get("source_ref") if isinstance(producer_definition.get("source_ref"), Mapping) else {}
            if ref.get("path") and ref.get("line") not in (None, ""):
                producer_location = f"（{ref.get('path')}:{ref.get('line')}）"
        output_steps.append({
            "order": len(output_steps) + 1,
            "kind": "fct_internal_assignment",
            "status": "runtime_observed" if runtime_internal is not None else "source_candidate",
            "signal": signal,
            "token": internal_token or "internal signal not_available",
            "value": runtime_internal.get("value") if runtime_internal is not None else None,
            "expression": expression,
            "source_ref": deepcopy(dict(row.get("source_ref") or {})),
            "assignment_status": row.get("assignment_status") or "not_scanned",
            "assignments": deepcopy(assignments[:8]),
            "producer_function_names": producer_function_names,
            "producer_function_refs": deepcopy(producer_function_refs[:8]),
            "producer_definition_ref": deepcopy(dict(producer_definition)) if isinstance(producer_definition, Mapping) else {},
            "primary_assignment": deepcopy(dict(primary_assignment)) if isinstance(primary_assignment, Mapping) else {},
            "text": (
                f"FCT/ASW 侧将 `{internal_token}`="
                f"{runtime_internal.get('value')} 作为运行时内部值继续映射。"
                if runtime_internal is not None and internal_token
                else f"FCT/ASW 侧的内部信号候选是 `{internal_token or 'not_available'}`；"
                + (
                    f"当前 source 找到 {len(active_assignments)} 个有效赋值位置，"
                    + (
                        f"其中生产该报警值的候选赋值位于 {((primary_assignment.get('source_ref') or {}).get('path') or 'source')}:{((primary_assignment.get('source_ref') or {}).get('line') or 'N/A')}。"
                        if isinstance(primary_assignment, Mapping) else "说明源码存在生产路径。"
                    )
                    + (
                        f"生产函数候选为 `{', '.join(producer_function_names[:3])}`{producer_location}。"
                        if producer_function_names else ""
                    )
                    + "本次停点没有观察到该内部字段。"
                    if active_assignments
                    else "当前 source 没有找到有效赋值位置，不能证明该内部字段在本事件路径中被写入。"
                )
            ),
        })
        if signal:
            transport_rows = [item for item in row.get("transport_mappings", []) or [] if isinstance(item, Mapping)]
            output_steps.append({
                "order": len(output_steps) + 1,
                "kind": "external_mapping",
                "status": "source_candidate",
                "signal": signal,
                "token": signal,
                "expression": expression,
                "source_ref": deepcopy(dict(row.get("source_ref") or {})),
                "transport_mappings": deepcopy(transport_rows[:4]),
                "text": (
                    f"随后在当前 source 的对外映射中，`{signal}` 使用 `{expression or 'not_available'}`；"
                    "这是输出映射候选，除非同帧运行时抓到该函数/字段，否则不把它写成已发送事实。"
                ),
            })
            for transport in transport_rows[:2]:
                output_steps.append({
                    "order": len(output_steps) + 1,
                    "kind": "transport_mapping",
                    "status": "source_candidate",
                    "signal": signal,
                    "token": transport.get("rte_lite_function") or "RteLite_Write",
                    "source_ref": deepcopy(dict(transport.get("source_ref") or {})),
                    "send_ref": deepcopy(dict(transport.get("com_send_source_ref") or {})),
                    "text": (
                        f"代码继续经过 `{transport.get('rte_lite_function') or 'RteLite_Write'}`，"
                        f"其下游调用点为 `Com_SendSignal`（{((transport.get('com_send_source_ref') or {}).get('path') or 'source')}:{((transport.get('com_send_source_ref') or {}).get('line') or 'N/A')}）。"
                    ),
                })
    if not rows:
        output_steps.append({
            "order": len(output_steps) + 1,
            "kind": "external_mapping",
            "status": "not_available",
            "token": "source output mapping not_available",
            "text": "当前 source 没有为本事件提供可追溯的对外映射候选。",
        })

    observed_algorithm = any(item.get("kind") == "algorithm_output" and item.get("status") == "observed" for item in output_steps)
    internal_observed = any(item.get("kind") == "fct_internal_assignment" and item.get("status") == "runtime_observed" for item in output_steps)
    source_mapping = any(item.get("kind") in {"external_mapping", "transport_mapping"} and item.get("status") == "source_candidate" for item in output_steps)
    if observed_algorithm and internal_observed:
        status = "partially_runtime_observed"
    elif observed_algorithm and source_mapping:
        status = "algorithm_observed_source_mapping_candidate"
    elif source_mapping:
        status = "source_mapping_candidate"
    else:
        status = "not_available"
    primary_internal = next(
        (item for item in output_steps if item.get("kind") == "fct_internal_assignment"),
        {},
    )
    primary_external = next(
        (item for item in output_steps if item.get("kind") == "external_mapping"),
        {},
    )
    summary_parts: list[str] = []
    seen_summary_kinds: set[str] = set()
    for item in output_steps:
        kind = str(item.get("kind") or "")
        if kind in seen_summary_kinds or not item.get("text"):
            continue
        seen_summary_kinds.add(kind)
        summary_parts.append(str(item.get("text")))
        if len(summary_parts) >= 4:
            break
    return {
        "schema_version": "diagnostic-output-chain.v1",
        "status": status,
        "source_status": str(source_chain.get("status") or "not_scanned"),
        "steps": output_steps,
        "primary_internal_signal": primary_internal.get("token"),
        "primary_external_signal": primary_external.get("signal") or primary_external.get("token"),
        "text": "\n\n".join(str(item) for item in summary_parts),
        "policy": (
            "The algorithm output may be the report terminal according to output_policy. "
            "FCT/internal/external mappings are shown as runtime observations only when observed; "
            "otherwise they remain source candidates."
        ),
    }


def _build_diagnostic_story(
    *,
    event: Mapping[str, Any],
    summary: Mapping[str, Any],
    event_code_path: Mapping[str, Any] | None,
    operating_facts: Mapping[str, Any],
    condition_items: Sequence[Mapping[str, Any]],
    condition_digest: Mapping[str, Any],
    condition_counts: Mapping[str, Any],
    geometry_projection: Mapping[str, Any] | None,
    output_policy: Mapping[str, Any],
    can_output: Mapping[str, Any] | None,
    algorithm_output_facts: Sequence[Mapping[str, Any]],
    runtime_facts: Sequence[Mapping[str, Any]],
    alert_status: str,
    should_alert: str,
    alert_statement: str,
    algorithm_rise_rows: Sequence[Mapping[str, Any]],
    exact_algorithm_rows: Sequence[Mapping[str, Any]],
    object_warning_facts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the user-facing narrative read model.

    Internal evidence layers stay in the machine-readable artifacts. This
    model exposes only the engineering story: operating point, source
    substitutions, branch outcomes, geometry and final output.
    """
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    frame_id = first.get("frame_id") or "not_available"
    function = str(summary.get("function") or "当前功能")
    side = str(summary.get("side") or "")
    radar = summary.get("radar_id") if summary.get("radar_id") not in (None, "") else "not_available"
    target_id = summary.get("target_obj_id") if summary.get("target_obj_id") not in (None, "") else "not_available"
    ego = [dict(item) for item in operating_facts.get("ego", []) or [] if isinstance(item, Mapping)]
    target = [dict(item) for item in operating_facts.get("target", []) or [] if isinstance(item, Mapping)]
    ego_text = "；".join(_format_fact(item) for item in ego[:8]) or "没有可确认的自车属性"
    target_text = "；".join(_format_fact(item) for item in target[:12]) or "没有可确认的目标属性"
    operating_text = (
        f"在 frameID={frame_id}，分析对象是 {function}{('/' + side) if side else ''}，"
        f"radar={radar}，目标 objID={target_id}。自车数据为：{ego_text}。目标数据为：{target_text}。"
    )

    steps: list[dict[str, Any]] = []
    for index, item in enumerate(condition_items, start=1):
        if not isinstance(item, Mapping):
            continue
        expression = str(item.get("expression") or "not_available")
        substituted = str(item.get("substituted_expression") or expression)
        status = str(item.get("status") or "not_evaluable")
        category, category_label = _condition_flow_category(expression)
        source = _story_source_text(item)
        binding_text = _story_binding_preview(item)
        missing = ", ".join(str(value) for value in item.get("missing_tokens", []) or [])
        if status == "satisfied":
            stage_text = {
                "state_machine": "状态机/系统门",
                "motion": "自车运动/速度",
                "target": "目标筛选",
                "roi": "ROI/区域",
                "prediction": "预测/时空",
                "output": "输出/汇总",
            }.get(category, category_label)
            prose = (
                f"第{index}步，{stage_text}条件在 {source} 已成立。"
                + (f"关键值为 {binding_text}。" if binding_text else "")
                + "算法继续沿当前源码路径处理。"
            )
        elif status == "not_satisfied":
            if "skip" in str(item.get("chain_function") or item.get("function") or "").lower():
                branch_text = "该筛选分支未触发，目标继续进入后续判断。"
            else:
                branch_text = "当前代码不沿这条分支继续。"
            prose = (
                f"第{index}步，{category_label}条件在 {source} 未成立。"
                + (f"关键值为 {binding_text}。" if binding_text else "")
                + branch_text
            )
        elif status == "unsupported":
            prose = f"第{index}步，{category_label}条件在 {source} 暂不能由当前求值器解释，不能把它当成未成立。"
        else:
            prose = (
                f"第{index}步，{category_label}条件在 {source} 暂不能判断。"
                + (f"缺少同帧运行时量：{missing}。" if missing else "当前没有足够的同帧变量。")
                + "因此这一步不作为报警成立或不成立的依据。"
            )
        steps.append({
            "order": index,
            "source": source,
            "category": category,
            "category_label": category_label,
            "status": status,
            "prose": prose,
            "expression": expression,
            "substituted_expression": substituted,
            "bindings": deepcopy(item.get("bindings") or []),
            "missing_tokens": [str(value) for value in item.get("missing_tokens", []) or []],
            "chain_function": item.get("chain_function"),
            "chain_relation": item.get("chain_relation"),
            "chain_function_order": item.get("chain_function_order"),
            "chain_source_order": item.get("chain_source_order"),
            "chain_call_site_line": item.get("chain_call_site_line"),
        })

    geometry = geometry_projection if isinstance(geometry_projection, Mapping) else {}
    relation = str(geometry.get("collision_status") or "not_evaluated")
    prediction = geometry.get("predicted_intersection") if isinstance(geometry.get("predicted_intersection"), Mapping) else {}
    branch = geometry.get("algorithm_branch") if isinstance(geometry.get("algorithm_branch"), Mapping) else {}
    geometry_sentences: list[str] = []
    if relation != "not_evaluated":
        geometry_sentences.append(f"当前目标多边形与对应 ROI 的空间关系是 `{relation}`。")
    if branch.get("expression"):
        assignment = branch.get("source_assignment") if isinstance(branch.get("source_assignment"), Mapping) else {}
        assignment_text = f"源码随后执行 `{assignment.get('expression')}`。" if assignment.get("expression") else ""
        geometry_sentences.append(
            f"源码中的 `{branch.get('expression')}` 表示 ROI 已生成、该区域分支可用，{assignment_text}"
            "它不是目标多边形已经侵入 ROI 的判断。"
        )
    if prediction.get("x") not in (None, "") and prediction.get("y") not in (None, ""):
        time_text = (
            f"，{prediction.get('time_token')}={prediction.get('time')}s"
            if prediction.get("time") not in (None, "") and prediction.get("time_token") else ""
        )
        relation_text = ", ".join(
            str(item.get("relation")) for item in prediction.get("roi_relations", []) or [] if isinstance(item, Mapping)
        )
        geometry_sentences.append(
            f"运行时预测点为 `{prediction.get('x_token')}={prediction.get('x')}`、"
            f"`{prediction.get('y_token')}={prediction.get('y')}`{time_text}"
            + (f"，预测点与 ROI 的关系为 `{relation_text}`。" if relation_text else "。")
            + "图中的虚线表示这条预测关系，不是把当前目标矩形强行画进 ROI。"
        )
    geometry_text = "".join(geometry_sentences) or "当前没有足够几何或预测数据形成空间描述。"

    output_chain = _build_output_chain(
        can_output=can_output,
        algorithm_output_facts=algorithm_output_facts,
        runtime_facts=runtime_facts,
        function=function,
        side=side,
    )

    output_text = alert_statement
    if exact_algorithm_rows:
        outputs = "; ".join(
            f"{row.get('function') or row.get('signal') or '算法输出'}={row.get('value')}（frame={row.get('frame_id')}）"
            for row in exact_algorithm_rows[:6]
        )
        output_text = f"在当前选定帧已观测到算法最终输出：{outputs}。{alert_statement}"
    elif algorithm_rise_rows:
        outputs = "; ".join(
            f"{row.get('function') or row.get('signal') or '算法输出'}={row.get('value')}（frame={row.get('frame_id')}）"
            for row in algorithm_rise_rows[:6]
        )
        output_text = f"运行窗口中观测到算法输出上升沿：{outputs}。{alert_statement}"

    unknown_count = sum(1 for item in steps if item.get("status") in {"not_evaluable", "unsupported"})
    if should_alert == "yes_observed":
        output_values = "; ".join(
            f"{row.get('function') or row.get('signal') or '算法输出'}={row.get('value')}（frame={row.get('frame_id')}）"
            for row in exact_algorithm_rows[:3]
        ) or "当前帧算法输出已观测为非零"
        roi_condition = next(
            (
                item for item in steps
                if item.get("status") == "satisfied"
                and any(marker in str(item.get("expression") or "") for marker in (".num", "->num"))
                and ">" in str(item.get("expression") or "")
            ),
            None,
        )
        ttm_condition = next(
            (
                item for item in steps
                if item.get("status") == "satisfied"
                and any(token in str(item.get("expression") or "") for token in ("fTTM", "time_to", "intersection"))
            ),
            None,
        )
        state_gate = next(
            (
                item for item in steps
                if item.get("status") in {"satisfied", "not_satisfied", "not_evaluable"}
                and "systemstate" in str(item.get("expression") or "").lower()
                and "adaswarning" in str(item.get("expression") or "").lower()
            ),
            None,
        )
        motion_condition = next(
            (
                item for item in steps
                if item.get("category") == "motion"
                and "carspd" in str(item.get("expression") or "").lower()
            ),
            None,
        )
        target_condition = next(
            (
                item for item in steps
                if item.get("category") == "target"
                and re.search(r"(?:->|\.)dynflg\b", str(item.get("expression") or "").lower())
            ),
            None,
        )
        conclusion_parts = [
            f"总结结论：{function}{('/' + side) if side else ''}（radar={radar}，objID={target_id}）在 frameID={frame_id} 的 arbe 报警灯对应算法输出已观测为报警：{output_values}。",
            "按当前 source 的条件链，已确认的判断结果如下：",
        ]
        if state_gate:
            if state_gate.get("status") == "not_evaluable":
                conclusion_parts.append(
                    "1）前置状态机 gate 的同帧状态暂未获取，保留为无法确认；但 GDB 调用栈已经进入该 gate 下的目标处理函数。"
                )
            else:
                conclusion_parts.append(
                    f"1）前置状态机 gate 已求值为 {state_gate.get('status')}，关键值：{_story_binding_preview(state_gate)}。"
                )
        if motion_condition:
            motion_status = {
                "satisfied": "满足",
                "not_satisfied": "不满足",
                "not_evaluable": "暂不能确认",
                "unsupported": "暂不支持求值",
            }.get(str(motion_condition.get("status") or ""), str(motion_condition.get("status") or "未确认"))
            conclusion_parts.append(
                f"2）自车车速条件{motion_status}，关键值：{_story_binding_preview(motion_condition)}。"
            )
        if target_condition:
            target_outcome = (
                "条件为 false，FctaSkipFlg 不跳过该目标，继续进入后续判断"
                if target_condition.get("status") == "not_satisfied"
                else "条件为 true，该目标会在此筛选处被跳过"
                if target_condition.get("status") == "satisfied"
                else "同帧值不足，暂不能确认是否跳过该目标"
            )
            conclusion_parts.append(
                f"3）目标动态/跟踪筛选的关键值为 {_story_binding_preview(target_condition) or '同帧值未完整获取'}；{target_outcome}"
            )
        if roi_condition:
            conclusion_parts.append(
                f"4）对应侧 ROI 已生成并可用，关键值：{_story_binding_preview(roi_condition)}；这里表示区域路径可用，不表示目标矩形此刻已经与 ROI 相交。"
            )
        if ttm_condition:
            ttm_bindings = [
                item for item in ttm_condition.get("bindings", []) or []
                if isinstance(item, Mapping) and item.get("status") == "bound"
            ]
            ttm_values = "、".join(
                f"{item.get('token')}={item.get('value')}"
                for item in ttm_bindings
                if item.get("token") and item.get("value") not in (None, "")
            )
            conclusion_parts.append(
                f"5）目标运动预测/到达条件整体成立，关键量为 {ttm_values or '当前条件绑定值'}。"
            )
        conclusion_parts.append("因此，按当前代码逻辑，这个目标满足已确认的报警路径，算法输出报警与代码条件一致。")
        mapping_steps = [
            item for item in output_chain.get("steps", []) or []
            if isinstance(item, Mapping)
        ]
        internal_step = next(
            (item for item in mapping_steps if item.get("kind") == "fct_internal_assignment"),
            None,
        )
        external_step = next(
            (item for item in mapping_steps if item.get("kind") == "external_mapping"),
            None,
        )
        if internal_step or external_step:
            internal_token = str((internal_step or {}).get("token") or "internal signal not_available")
            internal_value = (internal_step or {}).get("value")
            assignment = (internal_step or {}).get("primary_assignment") if isinstance((internal_step or {}).get("primary_assignment"), Mapping) else {}
            assignment_ref = assignment.get("source_ref") if isinstance(assignment.get("source_ref"), Mapping) else {}
            assignment_location = (
                f"{assignment_ref.get('path')}:{assignment_ref.get('line')}"
                if assignment_ref.get("path") and assignment_ref.get("line") not in (None, "")
                else "当前 source 未给出赋值位置"
            )
            if internal_value not in (None, ""):
                internal_text = f"运行时已观察到 `{internal_token}={internal_value}`"
            elif assignment:
                internal_text = f"当前 source 在 `{assignment_location}` 找到该内部量的赋值候选，但本次 GDB 停点没有取到 `{internal_token}` 的值"
            else:
                internal_text = f"当前 source 只找到 `{internal_token}` 这一内部量候选，尚未证明它在本路径中被赋值"
            external_token = str((external_step or {}).get("signal") or "对外输出信号未确认")
            external_expression = str((external_step or {}).get("expression") or "not_available")
            conclusion_parts.append(
                f"6）算法输出之后进入 FCT/ASW 下游映射：{internal_text}；"
                f"随后对外信号候选 `{external_token}` 使用 `{external_expression}`。"
                "因此，当前报告已经把算法报警、FCT 内部信号和对外映射接在同一条源码链上；"
                "其中没有同帧运行时观测的环节仍保留为源码候选，不能替代实际执行结果。"
            )
        if relation == "observed_disjoint" and prediction.get("x") not in (None, ""):
            conclusion_parts.append(
                "图上目标当前矩形与 ROI 不相交并不推翻上述结论：本版本使用的是未来运动交点/到达时间，而不是当前矩形的瞬时相交。"
            )
        if unknown_count:
            conclusion_parts.append(
                f"少量后续状态/计数变量（{unknown_count} 项）没有在本次停点完整取到；它们不改变已观测的报警输出，但需要补充后才能对正报/误报作最终定性。"
            )
        conclusion_text = "\n\n".join(conclusion_parts)
    else:
        conclusion_text = alert_statement
    code_path = event_code_path if isinstance(event_code_path, Mapping) else {}
    resolution = code_path.get("resolution") if isinstance(code_path.get("resolution"), Mapping) else {}
    function_resolution = resolution.get("function") if isinstance(resolution.get("function"), Mapping) else {}
    entry_name = str(function_resolution.get("name") or summary.get("function") or "当前报警处理函数")
    entry_ref = ""
    if function_resolution.get("file_path") and function_resolution.get("start_line") not in (None, ""):
        entry_ref = f"（{function_resolution.get('file_path')}:{function_resolution.get('start_line')}）"
    callers = [str(item) for item in resolution.get("callers", []) or [] if str(item).strip()]
    callees = [str(item) for item in resolution.get("callees", []) or [] if str(item).strip()]
    condition_chain_functions = [
        dict(item) for item in resolution.get("condition_chain_functions", []) or []
        if isinstance(item, Mapping)
    ]
    code_path_parts = [f"事件进入 `{entry_name}`{entry_ref}"]
    if callers:
        code_path_parts.append(f"，调用者为 `{callers[0]}`")
    if callees:
        code_path_parts.append(f"，函数内继续经过 {', '.join(f'`{item}`' for item in callees[:8])}")
    if condition_chain_functions:
        chain_text = " → ".join(
            f"`{item.get('function')}`"
            for item in condition_chain_functions[:12]
            if item.get("function")
        )
        if chain_text:
            code_path_parts.append(f"；条件链候选按当前调用关系为 {chain_text}")
    code_path_parts.append("；随后进入目标循环、条件判断和报警状态更新")
    code_path_text = "".join(code_path_parts) + "。"
    return {
        "schema_version": "diagnostic-story.v1",
        "status": "partial" if unknown_count or relation == "not_evaluated" else "ready",
        "title": f"{function}{('/' + side) if side else ''} 报警工况分析",
        "operating_condition": {
            "text": operating_text,
            "ego_facts": ego,
            "target_facts": target,
            "frame_id": frame_id,
            "radar_id": radar,
            "target_obj_id": target_id,
        },
        "condition_walk": {
            "text": "下面按当前 source 的实际顺序说明变量如何代入条件；没有证据的条件会明确保留为未知。",
            "scope": condition_digest.get("scope"),
            "counts": deepcopy(dict(condition_counts)),
            "steps": steps,
        },
        "code_path": {
            "text": code_path_text,
            "entry_function": entry_name,
            "entry_source_ref": deepcopy(function_resolution),
            "callers": callers,
            "callees": callees,
            "condition_chain_functions": condition_chain_functions,
        },
        "geometry": {"text": geometry_text, "relation": relation, "prediction": deepcopy(dict(prediction)), "algorithm_branch": deepcopy(dict(branch))},
        "output": {"text": output_text, "status": alert_status, "should_alert": should_alert, "policy": deepcopy(dict(output_policy))},
        "output_chain": output_chain,
        "conclusion": {"text": conclusion_text, "should_alert": should_alert, "confidence": "observed_algorithm_output" if should_alert == "yes_observed" else "condition_or_evidence_limited"},
        "object_warning_facts": deepcopy([dict(item) for item in object_warning_facts[:8] if isinstance(item, Mapping)]),
        "policy": "This is a deterministic, evidence-bound engineering narrative. It never fills missing variables or converts a branch result into an unproven final verdict.",
    }


def build_diagnostic_narrative(
    *,
    selected_event: Mapping[str, Any] | None,
    condition_trace: Mapping[str, Any] | None,
    alert_timeline: Mapping[str, Any] | None,
    geometry_projection: Mapping[str, Any] | None = None,
    frame_mapping_conflicts: list[Mapping[str, Any]] | None = None,
    can_output: Mapping[str, Any] | None = None,
    event_code_path: Mapping[str, Any] | None = None,
    output_endpoint: str = "algorithm",
    can_data_status: str = "not_detected",
    max_conditions: int = 10,
) -> dict[str, Any]:
    event = selected_event if isinstance(selected_event, Mapping) else {}
    summary = event.get("summary") if isinstance(event.get("summary"), Mapping) else {}
    function = str(summary.get("function") or "").strip()
    side = str(summary.get("side") or "").strip()
    radar_id = summary.get("radar_id")
    first = summary.get("first_frame") if isinstance(summary.get("first_frame"), Mapping) else {}
    frame_id = first.get("frame_id")
    target_id = summary.get("target_obj_id")
    rows = [
        row for row in _as_rows(alert_timeline.get("rows") if isinstance(alert_timeline, Mapping) else None)
        if _match_scope(row, function=function, side=side, radar_id=radar_id)
    ]
    recorded_rows = [row for row in rows if row.get("layer") == "recorded_raw"]
    algorithm_rows = [row for row in rows if row.get("layer") in {"replay_algorithm", "runtime_with_frame"}]
    can_rows = [row for row in rows if row.get("layer") == "can_tx_observation"]
    exact_can_rises = [
        row for row in can_rows
        if row.get("frame_status") == "observed"
        and row.get("transition") in {"rising", "rising_candidate", "active"}
        and row.get("value") not in (None, 0, False, "0")
    ]
    exact_algorithm_rows = [
        row for row in algorithm_rows
        if row.get("frame_status") == "observed"
        and row.get("value") not in (None, 0, False, "0")
        and (frame_id in (None, "") or str(row.get("frame_id")) == str(frame_id))
    ]
    algorithm_rise_rows = [
        row for row in algorithm_rows
        if row.get("frame_status") == "observed"
        and row.get("transition") in {"rising", "rising_candidate"}
        and row.get("value") not in (None, 0, False, "0")
    ]
    window_algorithm_rows = [
        row for row in algorithm_rows
        if row.get("frame_status") == "observed"
        and row.get("value") not in (None, 0, False, "0")
    ]
    condition = _condition_assessment(condition_trace)
    feature_hint = _feature_hint(function)
    condition_items, condition_lines = _condition_lines(
        condition_trace,
        max_items=max(1, int(max_conditions)),
        feature_hint=feature_hint,
        side_hint=side,
    )
    operating_facts, runtime_facts = _collect_operating_facts(event)
    runtime_alias_facts = [
        field
        for observation in _as_rows(event.get("runtime_observations"))
        for field in _fact_rows(observation.get("fields"))
        if _fact_token(field) and _fact_value_is_displayable(field.get("value"))
    ]
    all_condition_rows = _as_rows(condition_trace.get("conditions") if isinstance(condition_trace, Mapping) else None)
    scoped_condition_rows = [
        row for row in all_condition_rows
        if _condition_in_scope(row, feature_hint=feature_hint, side_hint=side)
    ]
    condition_digest = {
        "total": len(all_condition_rows),
        "selected_count": len(condition_items),
        "omitted_count": max(0, len(all_condition_rows) - len(condition_items)),
        "scope": (feature_hint.upper() if feature_hint else "event_source_candidate_set") + (f"/{side.upper()}" if side.upper() in {"L", "R"} else ""),
        "scoped_counts": _condition_row_counts(scoped_condition_rows),
        "key_missing_tokens": _condition_missing_digest(scoped_condition_rows),
        "alias_hints": _condition_alias_hints(scoped_condition_rows, runtime_alias_facts),
        "selection_policy": "satisfied/not_satisfied first, then conditions with few missing tokens and alarm-related source tokens",
    }
    source_alias_bindings = [
        item for item in (condition_trace or {}).get("source_alias_bindings", []) or []
        if isinstance(item, Mapping)
    ]
    if source_alias_bindings:
        condition_digest["source_alias_bindings"] = deepcopy(source_alias_bindings[:12])
    source_output_rows = [
        item for item in (can_output or {}).get("signals", []) or []
        if isinstance(item, Mapping)
    ]
    feature_token = feature_hint.lower()
    object_warning_facts = [
        item for item in runtime_alias_facts
        if feature_token
        and f"obj{feature_token}warningflag" in re.sub(r"[^a-z0-9]", "", _fact_token(item).lower())
        and _fact_value_is_displayable(item.get("value"))
        and item.get("value") not in (None, 0, False, "0", "")
    ]
    object_side_facts = [
        item for item in runtime_alias_facts
        if feature_token
        and f"{side.lower()}{feature_token}flag" in re.sub(r"[^a-z0-9]", "", _fact_token(item).lower())
        and _fact_value_is_displayable(item.get("value"))
        and item.get("value") not in (None, 0, False, "0", "")
    ]
    # The output chain starts from the actual algorithm field when the
    # runtime/GDB layer exposed it.  The fallback remains empty rather than
    # fabricating a token from a feature name.
    algorithm_output_facts = []
    seen_algorithm_tokens: set[str] = set()
    for item in runtime_alias_facts:
        token = _fact_token(item)
        normalized = re.sub(r"[^a-z0-9]", "", token.lower())
        if "adaswarning" not in normalized:
            continue
        key = _normalise_member_token(token)
        if key in seen_algorithm_tokens:
            continue
        seen_algorithm_tokens.add(key)
        algorithm_output_facts.append(item)
    output_policy = _resolve_output_policy(
        requested_endpoint=output_endpoint,
        can_data_status=can_data_status,
        can_rows=can_rows,
    )
    if output_policy["effective_endpoint"] == "can_tx" and exact_can_rises:
        alert_status = "can_tx_observed"
        should_alert = "yes_observed"
        alert_statement = "在选定 scope 内观测到 CAN Tx 报警信号的 0→非零上升沿；这可以证明该输出信号实际报警。"
    elif output_policy["effective_endpoint"] == "algorithm" and exact_algorithm_rows:
        alert_status = "algorithm_output_observed"
        should_alert = "yes_observed"
        alert_statement = "同帧已观测到 arbe 报警灯对应的算法最终输出为非零，判定为报警。"
    elif exact_algorithm_rows:
        alert_status = "algorithm_output_observed"
        should_alert = "supported_yes"
        alert_statement = "观测到算法/公共运行态输出报警，但当前没有同帧 CAN Tx 观测，不能把它等同于最终 CAN 首帧。"
    elif window_algorithm_rows:
        alert_status = "algorithm_output_window_only"
        should_alert = "indeterminate"
        alert_statement = "运行态窗口内观测到算法输出报警，但它与当前选定分析帧不完全同帧，不能据此判断选定帧是否应该报警。"
    elif object_warning_facts:
        alert_status = "object_warning_observed"
        should_alert = "indeterminate"
        alert_statement = "同一分析帧的目标级 warning flag 已在运行态观测为非 Normal；这证明目标级状态已置位，但当前仍缺少最终 adasWarning/CAN Tx 证据，不能直接判定最终报警。"
    elif condition["status"] == "all_selected_conditions_satisfied":
        alert_status = "conditions_supported"
        should_alert = "supported_yes"
        alert_statement = "选定代码条件在当前输入下均已求值为 true；由于尚未观测完整输出链，结论仍是条件层支持，不是最终 CAN 事实。"
    elif recorded_rows:
        alert_status = "recorded_raw_only"
        should_alert = "indeterminate"
        alert_statement = "原始录制中存在报警事件，但当前没有足够的同帧运行态/输出链证据判断当前代码是否应该报警。"
    elif condition["status"] == "selected_conditions_not_satisfied":
        alert_status = "conditions_not_satisfied"
        should_alert = "indeterminate"
        alert_statement = "部分选定条件在当前证据下未满足；由于条件行可能属于不同分支，不能仅凭这一结果宣称最终不应报警。"
    else:
        alert_status = "insufficient_evidence"
        should_alert = "indeterminate"
        alert_statement = "当前没有足够的同帧报警输出和条件证据，无法判断是否应该报警。"

    output_chain_obj = _build_output_chain(
        can_output=can_output,
        algorithm_output_facts=algorithm_output_facts,
        runtime_facts=runtime_alias_facts,
        function=function,
        side=side,
    )

    narrative: list[str] = []
    if recorded_rows:
        narrative.append(
            f"数据层：{function or '当前事件'}{('/' + side) if side else ''} 在 radar={radar_id if radar_id not in (None, '') else 'N/A'} 的原始录制中存在报警事件。"
        )
    if frame_id not in (None, ""):
        frame_confidence = str(first.get("confidence") or "")
        narrative.append(
            f"帧层：当前选定分析帧为 {frame_id}，证据等级为 {frame_confidence or 'not_available'}；"
            + (
                "本报告以 arbe 报警灯对应的算法输出作为判断终点。"
                if output_policy["effective_endpoint"] == "algorithm"
                else "CAN Tx 或精确 runtime 观测可进一步确认最终输出首帧。"
            )
        )
    if target_id not in (None, ""):
        indices = summary.get("target_index") if isinstance(summary.get("target_index"), Mapping) else {}
        index_text = ", ".join(f"{key}={value}" for key, value in indices.items() if value not in (None, ""))
        narrative.append(f"目标层：selected objID={target_id}" + (f"，索引映射为 {index_text}" if index_text else "，索引映射未完整证明") + "。")
        runtime_object_rows: list[Mapping[str, Any]] = []
        for observation in _as_rows(event.get("runtime_observations")):
            identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else observation
            if identity.get("object_id") not in (None, "") and str(identity.get("object_id")) == str(target_id):
                runtime_object_rows.append(observation)
        if runtime_object_rows:
            associations = []
            for observation in runtime_object_rows:
                identity = observation.get("identity") if isinstance(observation.get("identity"), Mapping) else observation
                association = identity.get("frame_source") or observation.get("association_status")
                if not association and observation.get("layer") == "gdb_observation":
                    association = "gdb_stop_exact_frame"
                associations.append(str(association or "not_available"))
            narrative.append(
                f"运行态目标层：同一 objID={target_id} 有 {len(runtime_object_rows)} 条运行态目标属性记录，"
                f"关联方式为 {', '.join(dict.fromkeys(associations))}；若不是 frame_verified/callback，仍不能视为算法绝对同帧。"
            )
    ego_summary_facts = operating_facts.get("ego", [])[:6]
    target_summary_facts = operating_facts.get("target", [])[:10]
    ego_text = "；".join(_format_fact(item) for item in ego_summary_facts) or "not_available"
    target_text = "；".join(_format_fact(item) for item in target_summary_facts) or "not_available"
    frame_text = str(frame_id) if frame_id not in (None, "") else "not_available"
    frame_definition = str(first.get("definition") or "")
    if first.get("confidence") == "selected_frame_not_alarm_edge":
        frame_label = "分析帧（不是已证明的报警上升沿）"
    elif "alarm" in frame_definition or "output" in frame_definition:
        frame_label = "报警帧候选"
    else:
        frame_label = "当前分析帧"
    narrative.insert(
        0,
        f"报警工况：{function or '当前功能'}{('/' + side) if side else ''}，radar={radar_id if radar_id not in (None, '') else 'N/A'}；"
        f"frameID={frame_text}（{frame_label}）。自车：{ego_text}。目标 objID={target_id if target_id not in (None, '') else 'N/A'}：{target_text}。",
    )
    if runtime_facts:
        runtime_summary = sorted(
            enumerate(runtime_facts),
            key=lambda item: (-_fact_score(item[1]), item[0]),
        )[:12]
        runtime_text = "；".join(_format_fact(item) for _, item in runtime_summary)
        runtime_layers = ", ".join(dict.fromkeys(str(item.get("layer") or "runtime") for item in runtime_facts))
        narrative.insert(1, f"实时补充：来自 {runtime_layers} 的同帧/运行态关键量为 {runtime_text}。")
    if object_warning_facts:
        warning_text = "; ".join(
            f"{_fact_token(item)}={item.get('value')}"
            for item in object_warning_facts[:4]
        )
        side_text = "; ".join(
            f"{_fact_token(item)}={item.get('value')}"
            for item in object_side_facts[:4]
        )
        narrative.insert(
            2,
            f"目标级报警状态：{warning_text}；"
            + (f"侧别标志：{side_text}；" if side_text else "")
            + (
                "这是算法对象状态，最终判断仍以算法输出为准。"
                if output_policy["effective_endpoint"] == "algorithm"
                else "这是算法对象状态，不等同于最终 CAN Tx。"
            ),
        )
    collision_status = str((geometry_projection or {}).get("collision_status") or "not_evaluated")
    if collision_status != "not_evaluated":
        collision_source = str((geometry_projection or {}).get("source") or "geometry_projection")
        collision_rows = [
            item for item in (geometry_projection or {}).get("collision_evidence", []) or []
            if isinstance(item, Mapping)
        ]
        collision_detail = "; ".join(
            f"{item.get('roi')} relation={item.get('relation')}"
            + (f", num={item.get('roi_num')}" if item.get("roi_num") not in (None, "") else "")
            for item in collision_rows
        )
        narrative.append(
            f"几何层：目标多边形与当前 ROI 的几何关系为 `{collision_status}`（来源：{collision_source}"
            + (f"；{collision_detail}" if collision_detail else "")
            + "）。"
            "这表示目标在当前时刻没有直接压入该多边形。"
        )
        branch = (geometry_projection or {}).get("algorithm_branch") if isinstance((geometry_projection or {}).get("algorithm_branch"), Mapping) else {}
        if branch.get("expression"):
            assignment = branch.get("source_assignment") if isinstance(branch.get("source_assignment"), Mapping) else {}
            branch_side = (
                "左侧" if "left" in str(branch.get("expression") or "").lower()
                else "右侧" if "right" in str(branch.get("expression") or "").lower()
                else "对应侧"
            )
            assignment_text = (
                f"源码还明确执行 `{assignment.get('expression')}`（{assignment.get('file_path')}:{assignment.get('line')}）"
                if assignment.get("expression")
                else f"源码条件 `{branch.get('expression')}` 已被求值为 {branch.get('status')}"
            )
            narrative.append(
                f"ROI 分支解释：当前实现把 `{branch.get('expression')}` 当作 ROI 可用性门，而不是对目标 polygon 做相交判断；"
                f"{assignment_text}。因此 `{collision_status}` 与{branch_side}源分支进入并不矛盾。"
            )
        predicted = (geometry_projection or {}).get("predicted_intersection") if isinstance((geometry_projection or {}).get("predicted_intersection"), Mapping) else {}
        if predicted.get("x") not in (None, "") and predicted.get("y") not in (None, ""):
            prediction_relations = [
                str(item.get("relation"))
                for item in predicted.get("roi_relations", []) or []
                if isinstance(item, Mapping)
            ]
            relation_text = f"；对 ROI 的预测关系为 {', '.join(prediction_relations)}" if prediction_relations else ""
            time_token = str(predicted.get("time_token") or predicted.get("ttm_y_token") or "")
            time_value = predicted.get("time") if predicted.get("time") not in (None, "") else predicted.get("fTTMY")
            ttm_text = f"，{time_token}={time_value}s" if time_value not in (None, "") and time_token else ""
            narrative.append(
                f"预测层：代码运行态给出交点 `{predicted.get('x_token')}={predicted.get('x')}`、"
                f"`{predicted.get('y_token')}={predicted.get('y')}`{ttm_text}{relation_text}；"
                "图中的虚线和交点表示预测结果，不是把目标当前矩形强行画进 ROI。"
            )
    if frame_mapping_conflicts:
        conflict_text = "; ".join(
            f"{item.get('field')}={item.get('actual_radar_id')}（expected={item.get('expected_radar_id')}）"
            for item in frame_mapping_conflicts
            if isinstance(item, Mapping)
        )
        narrative.append(
            f"映射质量：事件内部存在 radar/frame 冲突：{conflict_text or 'not_available'}；"
            "本报告按 selected event 的 radar/源 topic 取值，冲突映射未参与结论。"
        )
    if source_output_rows:
        def source_output_text(item: Mapping[str, Any]) -> str:
            source_ref = item.get("source_ref") if isinstance(item.get("source_ref"), Mapping) else {}
            location = ""
            if source_ref.get("path") and source_ref.get("line") not in (None, ""):
                location = f"（{source_ref.get('path')}:{source_ref.get('line')}）"
            transport_rows = [
                row for row in item.get("transport_mappings", []) or []
                if isinstance(row, Mapping)
            ]
            transport_text = ""
            if transport_rows:
                transport = transport_rows[0]
                send_ref = transport.get("com_send_source_ref") if isinstance(transport.get("com_send_source_ref"), Mapping) else {}
                send_location = ""
                if send_ref.get("path") and send_ref.get("line") not in (None, ""):
                    send_location = f" @ {send_ref.get('path')}:{send_ref.get('line')}"
                transport_text = f" -> {transport.get('rte_lite_function') or 'RteLite_Write'} -> Com_SendSignal{send_location}"
            return (
                f"{item.get('signal') or 'CAN signal'} <- {item.get('expression') or 'not_available'}"
                f"{location}{transport_text}"
            )

        output_text = "; ".join(
            dict.fromkeys(
                source_output_text(item) for item in source_output_rows
            )
        )
        narrative.append(
            f"源码输出映射：当前 source 为该事件筛选出 {output_text}；"
            "这些是当前 source 的下游输出映射候选；本报告的报警终点仍以 arbe 报警灯对应算法输出为准。"
        )
    if output_chain_obj.get("text"):
        narrative.append(f"报警输出之后：{output_chain_obj.get('text')}")
    if exact_algorithm_rows:
        output_text = "; ".join(
            dict.fromkeys(
                f"{row.get('layer')}:{row.get('function') or row.get('signal') or 'warning'}="
                f"{row.get('value')}（frame={row.get('frame_id')}，{row.get('transition') or 'active'}）"
                for row in exact_algorithm_rows
            )
        )
        narrative.insert(2, f"报警输出层：{output_text}。")
    if algorithm_rise_rows:
        rise_text = "; ".join(
            dict.fromkeys(
                f"{row.get('function') or row.get('signal') or 'warning'}={row.get('value')}（frame={row.get('frame_id')}）"
                for row in algorithm_rise_rows
            )
        )
        narrative.insert(
            2,
            f"运行态上升沿线索：{rise_text}；"
            + (
                "该算法输出的 0→非零转换作为报警首帧线索。"
                if output_policy["effective_endpoint"] == "algorithm"
                else "这是算法/公共输出的 0→非零转换，不等同于已观测 CAN Tx 上升沿。"
            ),
        )
    if condition["counts"]["total"]:
        counts = condition["counts"]
        narrative.append(
            f"代码条件层：当前 source index 给出 {counts['total']} 条候选条件；"
            f"satisfied={counts['satisfied']}、not_satisfied={counts['not_satisfied']}、"
            f"not_evaluable={counts['not_evaluable']}、unsupported={counts['unsupported']}；"
            f"在 {condition_digest['scope']} scope 内为 {condition_digest['scoped_counts']}。"
        )
        narrative.extend(condition_lines)
        missing = ", ".join(condition_digest["key_missing_tokens"][:8])
        if missing:
            narrative.append(f"尚未能代入的关键运行时量：{missing}。这些量必须从同一 frame 的公共通道或 GDB 获取，不能用邻帧值替代。")
        alias_hints = condition_digest.get("alias_hints", [])
        if alias_hints:
            hint_text = "; ".join(
                f"{item.get('missing_token')} ↔ {item.get('observed_token')}"
                for item in alias_hints
            )
            narrative.append(
                f"变量映射线索（未绑定）：{hint_text}；这些 token 只在指针/点号形态上相近，必须回到当前源码或同一栈帧确认，不能直接当作同一个变量。"
            )
        if source_alias_bindings:
            alias_text = "; ".join(
                f"{item.get('alias')} <- {item.get('source')}（声明 {((item.get('source_ref') or {}).get('file_path') or 'source')}:{((item.get('source_ref') or {}).get('line') or 'N/A')}）"
                for item in source_alias_bindings[:6]
            )
            narrative.append(
                f"源码别名绑定：{alias_text}；只对声明后未再次赋值的字段回填，因此 `objInfo->trcOutData[i]` 的运行时值可以安全用于对应的 `sObj` 条件。"
            )
    disturbance = alert_timeline.get("disturbance") if isinstance(alert_timeline, Mapping) and isinstance(alert_timeline.get("disturbance"), Mapping) else {}
    if str(disturbance.get("status") or "").lower() in {"suspected", "confirmed"}:
        narrative.append(
            f"运行质量层：当前 runtime/GDB 结果标记为 {disturbance.get('status')}（{disturbance.get('reason') or '存在回放/调试扰动'}），不能把它当作无扰动实车真值。"
        )
    narrative.append(f"报警判断：{alert_statement}")
    missing_layers = [
        str(item.get("layer"))
        for item in _as_rows(alert_timeline.get("sources") if isinstance(alert_timeline, Mapping) else None)
        if item.get("status") == "not_available"
    ]
    if not output_policy["can_required"]:
        missing_layers = [item for item in missing_layers if item != "can_tx_observation"]
    next_actions: list[dict[str, Any]] = []
    if "runtime_with_frame" in missing_layers:
        next_actions.append({"tool": "sim-verify", "reason": "先采集 warning_status_with_frame、radar_info 和 objectlist 的运行态证据。"})
    if condition["status"] in {"not_evaluable", "not_available", "mixed"}:
        next_actions.append({"tool": "runtime-debug-plan", "reason": "为缺失的局部变量、状态机计数器、ROI 和 output chain 生成当前 source 绑定的 GDB 计划。"})
    if "can_tx_observation" in missing_layers and output_policy["can_required"]:
        next_actions.append({"tool": "code-gdb-plan", "reason": "继续解析实际 RTE/Com signal token；在可执行链路中观测 CAN Tx 上升沿。"})
    assessment_summary = alert_statement
    scoped_counts = condition_digest["scoped_counts"]
    geometry_summary = ""
    if collision_status != "not_evaluated":
        geometry_summary = f" 几何投影为 {collision_status}，但不替代功能分支条件。"
    mapping_summary = ""
    if frame_mapping_conflicts:
        mapping_summary = " 事件内存在 radar/frame 映射冲突，已按 selected event scope 隔离。"
    output_mapping_summary = ""
    if source_output_rows:
        output_mapping_summary = f" 当前 source 输出映射候选 {len(source_output_rows)} 条，供回看输出链路使用。"
    executive_summary = (
        f"{function or '当前功能'}{('/' + side) if side else ''} 在 frameID={frame_text} 的分析对象为 "
        f"radar={radar_id if radar_id not in (None, '') else 'N/A'}、objID={target_id if target_id not in (None, '') else 'N/A'}；"
        f"自车关键状态为 [{ego_text}]，目标关键状态为 [{target_text}]。"
        f"代码侧共有 {condition['counts']['total']} 条候选条件；在 {condition_digest['scope']} scope 内，"
        f"satisfied={scoped_counts['satisfied']}、not_satisfied={scoped_counts['not_satisfied']}、"
        f"not_evaluable={scoped_counts['not_evaluable']}；"
        f"{assessment_summary}{geometry_summary}{mapping_summary}{output_mapping_summary}"
    )
    analysis_flow = _build_analysis_flow(
        event=event,
        summary=summary,
        operating_facts=operating_facts,
        condition_items=condition_items,
        condition_digest=condition_digest,
        condition_counts=condition["counts"],
        geometry_projection=geometry_projection,
        output_chain=output_chain_obj,
        output_policy=output_policy,
        alert_status=alert_status,
        should_alert=should_alert,
        alert_statement=alert_statement,
    )
    diagnostic_story = _build_diagnostic_story(
        event=event,
        summary=summary,
        event_code_path=event_code_path,
        operating_facts=operating_facts,
        condition_items=condition_items,
        condition_digest=condition_digest,
        condition_counts=condition["counts"],
        geometry_projection=geometry_projection,
        output_policy=output_policy,
        can_output=can_output,
        algorithm_output_facts=algorithm_output_facts,
        runtime_facts=runtime_alias_facts,
        alert_status=alert_status,
        should_alert=should_alert,
        alert_statement=alert_statement,
        algorithm_rise_rows=algorithm_rise_rows,
        exact_algorithm_rows=exact_algorithm_rows,
        object_warning_facts=object_warning_facts,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if event and narrative else "partial",
        "scope": {
            "event_id": summary.get("event_id") or event.get("event_id"),
            "function": function,
            "side": side,
            "radar_id": radar_id,
            "frame_id": frame_id,
            "target_obj_id": target_id,
        },
        "alarm_assessment": {
            "status": alert_status,
            "should_alert": should_alert,
            "statement": alert_statement,
            "recorded_alarm_observed": bool(recorded_rows),
            "algorithm_output_observed": bool(exact_algorithm_rows),
            "object_warning_observed": bool(object_warning_facts),
            "can_tx_observed": bool(exact_can_rises),
            "algorithm_rising_frames": [
                row.get("frame_id") for row in algorithm_rise_rows if row.get("frame_id") not in (None, "")
            ],
            "can_tx_rising_frames": [
                row.get("frame_id") for row in exact_can_rises if row.get("frame_id") not in (None, "")
            ],
            "output_endpoint": output_policy["effective_endpoint"],
            "output_authority": output_policy["output_authority"],
            "can_data_status": output_policy["can_data_status"],
            "can_required": output_policy["can_required"],
            "algorithm_output_is_terminal": output_policy["algorithm_output_is_terminal"],
        },
        "condition_assessment": condition,
        "condition_digest": condition_digest,
        "condition_items": condition_items,
        "operating_condition": operating_facts,
        "runtime_facts": runtime_facts,
        "can_output": deepcopy(dict(can_output or {})),
        "output_chain": deepcopy(output_chain_obj),
        "output_policy": output_policy,
        "object_warning_observed": bool(object_warning_facts),
        "object_warning_facts": deepcopy(object_warning_facts[:8]),
        "executive_summary": executive_summary,
        "diagnostic_story": diagnostic_story,
        "analysis_flow": analysis_flow,
        "narrative": narrative,
        "next_actions": next_actions,
        "evidence_summary": {
            "timeline_row_count": len(rows),
            "recorded_row_count": len(recorded_rows),
            "algorithm_row_count": len(algorithm_rows),
            "can_tx_row_count": len(can_rows),
            "runtime_target_match_count": sum(
                1
                for observation in _as_rows(event.get("runtime_observations"))
                if isinstance(observation.get("identity"), Mapping)
                and target_id not in (None, "")
                and str(observation["identity"].get("object_id")) == str(target_id)
            ),
            "missing_layers": missing_layers,
            "disturbance_status": disturbance.get("status", "not_evaluated"),
            "output_endpoint": output_policy["effective_endpoint"],
            "can_data_status": output_policy["can_data_status"],
        },
        "policy": "This text is deterministic evidence interpretation. It cannot replace unobserved runtime/CAN facts or create a feature rule.",
    }


__all__ = ["SCHEMA_VERSION", "build_diagnostic_narrative"]
