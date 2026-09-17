# -*- coding: utf-8 -*-
"""Normalize public arbe runtime samples into frame-bound snapshots.

The current arbe GUI receives three useful public channels, but their frame
guarantees differ.  This engine keeps that distinction explicit:

* ``warning_status_with_frame`` and ``radar_info`` carry a frame value;
* an objectlist row is frame-verified only when it carries an explicit frame;
* a future collector may provide a callback id to obtain
  ``callback_correlated``;
* a current objectlist row with only a publish timestamp stays ``unbound``.

This is a normalizer, not a ROS player or a time-neighbour matcher.  It can be
fed by a live subscriber, a bag adapter, or a stamped arbe bridge without
changing the Pi contract.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .ros_inventory import SCHEMA_VERSION as ROS_TOPIC_INVENTORY_SCHEMA


SCHEMA_VERSION = "runtime-snapshot-with-frame.v1"
ASSOCIATION_STATUSES = frozenset({
    "frame_verified", "callback_correlated", "publication_correlated", "unbound",
})
OBJECT_ASSOCIATION_MODES = frozenset({"strict", "publication_order", "auto"})
OBJECT_VALIDITY_POLICIES = frozenset({"preserve", "arbe_wf_sobj"})
_ROS_MESSAGE_ARRAY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*/[A-Za-z][A-Za-z0-9_]*\[(?:\d+)?\]$")
_MAX_RUNTIME_OBJECT_FIELDS = 512


class PublicRuntimeError(ValueError):
    """Raised when a public runtime capture cannot be normalized."""


def _topic_plan_channel(topic: str, topic_plan: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(topic_plan, Mapping):
        return {}
    channels = topic_plan.get("channels")
    if not isinstance(channels, Sequence) or isinstance(channels, (str, bytes, bytearray)):
        return {}
    for channel in channels:
        if not isinstance(channel, Mapping):
            continue
        pattern = str(channel.get("topic") or "").strip()
        if pattern == topic:
            return dict(channel)
        if "{radar_id}" in pattern:
            prefix, suffix = pattern.split("{radar_id}", 1)
            if topic.startswith(prefix) and topic.endswith(suffix):
                middle = topic[len(prefix) : len(topic) - len(suffix) if suffix else None]
                if middle.isdigit():
                    return {**dict(channel), "resolved_radar_id": int(middle)}
    return {}


def _object_array_field(message_schema: Mapping[str, Any]) -> dict[str, Any] | None:
    message_type = str(message_schema.get("message_type") or "")
    field_catalog = message_schema.get("field_catalog")
    if not isinstance(field_catalog, Sequence) or isinstance(field_catalog, (str, bytes, bytearray)):
        return None
    candidates = [
        dict(item)
        for item in field_catalog
        if isinstance(item, Mapping)
        and str(item.get("message_type") or "") == message_type
        and _ROS_MESSAGE_ARRAY_RE.fullmatch(str(item.get("type") or ""))
    ]
    return candidates[0] if len(candidates) == 1 else None


def _sample_radar_id(topic: str, channel: Mapping[str, Any]) -> tuple[int | None, str]:
    resolved = channel.get("resolved_radar_id")
    if isinstance(resolved, int) and not isinstance(resolved, bool):
        return resolved, "public_topic_plan"
    channel_id = str(channel.get("channel_id") or "")
    match = re.search(r"_(\d+)$", channel_id)
    if match:
        return int(match.group(1)), "public_topic_plan_channel_id"
    tail = str(topic).rstrip("/").rsplit("/", 1)[-1]
    match = re.search(r"_(\d+)$", tail)
    if match:
        return int(match.group(1)), "topic_suffix"
    return None, "not_available"


def _read_frame_key(payload: Mapping[str, Any], frame_key: str) -> Any:
    value = str(frame_key or "").strip()
    if not value or value in {"not_in_message", "unknown"}:
        return None
    indexed = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\[(\d+)\]", value)
    if indexed:
        rows = payload.get(indexed.group(1))
        index = int(indexed.group(2))
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)) and index < len(rows):
            return rows[index]
        return None
    current: Any = payload
    for component in value.split("."):
        if isinstance(current, Mapping):
            current = current.get(component)
        else:
            return None
    return current


def runtime_capture_from_topic_inventory(
    inventory: Mapping[str, Any],
    *,
    inventory_path: str = "",
    inventory_sha256: str = "",
    topic_plan: Mapping[str, Any] | None = None,
    topic_plan_path: str = "",
    topic_plan_sha256: str = "",
    preflight: Mapping[str, Any] | None = None,
    preflight_sha256: str = "",
) -> dict[str, Any]:
    """Project bounded, independently sampled ROS inventory rows for normalization.

    Only active message schemas and exact public-topic-plan channels are used.
    One-message samples have no shared message sequence, so this adapter never
    creates cross-topic frame association evidence.
    """
    if inventory.get("schema_version") != ROS_TOPIC_INVENTORY_SCHEMA:
        raise PublicRuntimeError("capture is not ros-topic-inventory.v1")
    topic_rows = inventory.get("topics")
    if not isinstance(topic_rows, Sequence) or isinstance(topic_rows, (str, bytes, bytearray)):
        raise PublicRuntimeError("ros-topic-inventory topics must be an array")
    server_value = inventory.get("server")
    server = dict(server_value) if isinstance(server_value, Mapping) else {}
    raw_diagnostics = inventory.get("diagnostics")
    diagnostics: list[str] = (
        [str(item) for item in raw_diagnostics if str(item)]
        if isinstance(raw_diagnostics, Sequence) and not isinstance(raw_diagnostics, (str, bytes, bytearray))
        else []
    )
    active_topic_plan: Mapping[str, Any] | None = topic_plan
    topic_plan_binding_status = "not_provided"
    topic_plan_diagnostic = ""
    if topic_plan is not None:
        plan_schema = topic_plan.get("source_schema")
        plan_schema = plan_schema if isinstance(plan_schema, Mapping) else {}
        plan_server = plan_schema.get("preflight_server")
        plan_server = plan_server if isinstance(plan_server, Mapping) else {}
        plan_workspace = plan_schema.get("preflight_workspace")
        plan_workspace = plan_workspace if isinstance(plan_workspace, Mapping) else {}
        plan_preflight_sha256 = str(plan_schema.get("preflight_sha256") or "")
        inventory_binding = inventory.get("runtime_binding")
        inventory_binding = inventory_binding if isinstance(inventory_binding, Mapping) else {}
        inventory_preflight_sha256 = str(inventory_binding.get("preflight_sha256") or "")
        current_server = preflight.get("server") if isinstance(preflight, Mapping) else None
        current_server = current_server if isinstance(current_server, Mapping) else {}
        current_workspace = preflight.get("workspace") if isinstance(preflight, Mapping) else None
        current_workspace = current_workspace if isinstance(current_workspace, Mapping) else {}
        server_keys = ("host", "user", "port", "transport")
        comparable_server_keys = [
            key for key in server_keys
            if key in plan_server and key in current_server and key in server
        ]
        server_identity_matches = bool(comparable_server_keys) and all(
            str(plan_server[key]) == str(current_server[key]) == str(server[key])
            for key in comparable_server_keys
        )
        workspace_identity_matches = bool(plan_workspace) and dict(plan_workspace) == dict(current_workspace)
        if not isinstance(preflight, Mapping):
            topic_plan_binding_status = "preflight_required"
            topic_plan_diagnostic = "topic_plan_requires_current_preflight"
        elif topic_plan.get("status") != "ready":
            topic_plan_binding_status = "plan_not_ready"
            topic_plan_diagnostic = "topic_plan_not_ready"
        elif not plan_server or not plan_workspace:
            topic_plan_binding_status = "plan_identity_missing"
            topic_plan_diagnostic = "topic_plan_preflight_identity_missing"
        elif not preflight_sha256 or not plan_preflight_sha256 or not inventory_preflight_sha256:
            topic_plan_binding_status = "preflight_hash_missing"
            topic_plan_diagnostic = "topic_plan_inventory_preflight_hash_missing"
        elif inventory_binding.get("status") != "preflight_bound":
            topic_plan_binding_status = "inventory_not_preflight_bound"
            topic_plan_diagnostic = "inventory_preflight_binding_not_ready"
        elif not (
            plan_preflight_sha256 == str(preflight_sha256)
            and inventory_preflight_sha256 == str(preflight_sha256)
        ):
            topic_plan_binding_status = "preflight_hash_conflict"
            topic_plan_diagnostic = "topic_plan_inventory_preflight_hash_conflict"
        elif not server_identity_matches or not workspace_identity_matches:
            topic_plan_binding_status = "identity_conflict"
            topic_plan_diagnostic = "topic_plan_inventory_preflight_identity_conflict"
        else:
            topic_plan_binding_status = "bound"
        if topic_plan_binding_status != "bound":
            active_topic_plan = None
            diagnostics.append(topic_plan_diagnostic)
    warning_rows: list[dict[str, Any]] = []
    radar_info_rows: list[dict[str, Any]] = []
    object_rows: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    observed_sample_count = 0
    observed_objectlist_topic_count = 0

    for raw_topic in topic_rows:
        if not isinstance(raw_topic, Mapping):
            continue
        topic = str(raw_topic.get("topic") or "")
        message_type = str(raw_topic.get("type") or "")
        sample = raw_topic.get("sample")
        sample = sample if isinstance(sample, Mapping) else {}
        message_schema = raw_topic.get("message_schema")
        message_schema = message_schema if isinstance(message_schema, Mapping) else {}
        channel = _topic_plan_channel(topic, active_topic_plan)
        sample_status = str(sample.get("status") or "not_requested")
        sample_observed = bool(sample.get("message_observed")) and sample_status == "observed"
        if sample_observed:
            observed_sample_count += 1
        topic_summary = {
            "topic": topic,
            "message_type": message_type,
            "channel_id": str(channel.get("channel_id") or ""),
            "source_kind": str(channel.get("source_kind") or ""),
            "sample_status": sample_status,
            "message_observed": sample_observed,
            "observed_at_utc": sample.get("observed_at_utc"),
            "sample_sha256": sample.get("stdout_sha256"),
            "sample_char_count": sample.get("stdout_char_count"),
            "sample_truncated": bool(sample.get("stdout_truncated")),
            "message_schema_status": str(message_schema.get("status") or "not_requested"),
            "message_definition_sha256": message_schema.get("message_definition_sha256"),
            "field_count": message_schema.get("field_count"),
            "field_catalog_truncated": bool(message_schema.get("field_catalog_truncated")),
        }
        samples.append(topic_summary)
        if not sample_observed:
            if sample_status not in {"not_requested", "no_message"}:
                diagnostics.append(f"topic_sample_unavailable:{topic}:{sample_status}")
            continue
        if bool(sample.get("stdout_truncated")):
            diagnostics.append(f"topic_sample_truncated:{topic}")
            continue
        text = str(sample.get("stdout") or "")
        sample_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        expected_sample_hash = str(sample.get("stdout_sha256") or "")
        if expected_sample_hash and expected_sample_hash != sample_hash:
            diagnostics.append(f"topic_sample_hash_mismatch:{topic}")
            continue
        expected_char_count = sample.get("stdout_char_count")
        if (
            isinstance(expected_char_count, int)
            and not isinstance(expected_char_count, bool)
            and expected_char_count != len(text)
        ):
            diagnostics.append(f"topic_sample_length_mismatch:{topic}")
            continue
        if "stdout_truncated" not in sample and len(text) >= 20_000:
            diagnostics.append(f"topic_sample_truncation_unknown:{topic}")
            continue
        try:
            message = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            diagnostics.append(f"topic_sample_yaml_invalid:{topic}:{type(exc).__name__}")
            continue
        if not isinstance(message, Mapping):
            diagnostics.append(f"topic_sample_not_object:{topic}")
            continue
        source_kind = str(channel.get("source_kind") or "")
        channel_id = str(channel.get("channel_id") or "")
        radar_id, radar_id_source = _sample_radar_id(topic, channel)

        is_object_message = (
            source_kind == "ros_wfObjectMsg"
            or message_type.rsplit("/", 1)[-1] == "wfObjectMsg"
        )
        if is_object_message:
            observed_objectlist_topic_count += 1
            if (
                message_schema.get("status") != "ready"
                or bool(message_schema.get("field_catalog_truncated"))
                or bool(message_schema.get("definition_truncated"))
                or str(message_schema.get("message_type") or "") != message_type
                or not str(message_schema.get("message_definition_sha256") or "")
            ):
                diagnostics.append(f"objectlist_schema_not_ready:{topic}")
                continue
            array_field = _object_array_field(message_schema)
            if not array_field:
                diagnostics.append(f"objectlist_message_has_no_unique_object_array:{topic}")
                continue
            object_message_type = re.sub(
                r"\[(?:\d+)?\]$", "", str(array_field.get("type") or "")
            )
            nested_field_catalog = [
                {
                    "token": str(item.get("name") or ""),
                    "type": str(item.get("type") or ""),
                    "source_path": str(item.get("path") or ""),
                }
                for item in message_schema.get("field_catalog", []) or []
                if isinstance(item, Mapping)
                and str(item.get("message_type") or "") == object_message_type
                and str(item.get("name") or "")
            ]
            topic_summary.update({
                "object_array_field_path": str(array_field.get("path") or ""),
                "object_message_type": object_message_type,
                "object_field_catalog": nested_field_catalog[:_MAX_RUNTIME_OBJECT_FIELDS],
                "object_field_count": len(nested_field_catalog),
                "object_field_catalog_truncated": (
                    len(nested_field_catalog) > _MAX_RUNTIME_OBJECT_FIELDS
                    or bool(message_schema.get("field_catalog_truncated"))
                    or bool(message_schema.get("definition_truncated"))
                ),
            })
            field_name = str(array_field.get("name") or "")
            rows = message.get(field_name)
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
                diagnostics.append(f"objectlist_array_missing_from_sample:{topic}:{field_name}")
                continue
            if not rows:
                diagnostics.append(f"objectlist_sample_observed_empty:{topic}")
            for object_index, item in enumerate(rows):
                if not isinstance(item, Mapping):
                    diagnostics.append(f"objectlist_row_not_object:{topic}:{object_index}")
                    continue
                object_rows.append({
                    **dict(item),
                    "topic": topic,
                    "message_type": message_type,
                    "source": "ros-topic-inventory",
                    "radar_id": radar_id,
                    "radar_id_source": radar_id_source,
                    "object_index": object_index,
                    "sample_observed_at_utc": sample.get("observed_at_utc"),
                    "source_ref": {
                        "topic": topic,
                        "message_type": message_type,
                        "channel_id": channel_id,
                        "message_definition_sha256": message_schema.get("message_definition_sha256"),
                        "field_path": array_field.get("path"),
                        "sample_sha256": sample.get("stdout_sha256") or sample_hash,
                        "inventory_sha256": inventory_sha256 or None,
                    },
                })
            continue

        if source_kind == "ros_algorithm_warning" or channel_id.lower().startswith("algorithm_warning"):
            row = dict(message)
            row.setdefault("topic", topic)
            row.setdefault("source", "warning_status_with_frame" if "with_frame" in channel_id else "warning_status")
            if radar_id is not None:
                row.setdefault("radar_id", radar_id)
            frame_value = _read_frame_key(message, str(channel.get("frame_key") or ""))
            if frame_value not in (None, ""):
                row.setdefault("frame_id", frame_value)
            if "data" in message or "bits" in message or "warnings" in message:
                warning_rows.append(row)
            else:
                diagnostics.append(f"warning_sample_has_no_recognized_values:{topic}")
            continue

        if "radar_info" in channel_id.lower() or topic.rstrip("/").endswith("/radar_info"):
            row = dict(message)
            row.setdefault("topic", topic)
            row.setdefault("source", "radar_info")
            if radar_id is not None:
                row.setdefault("radar_id", radar_id)
            radar_info_rows.append(row)
            continue

        diagnostics.append(f"topic_sample_role_not_resolved:{topic}")

    return {
        "warning_rows": warning_rows,
        "radar_info_rows": radar_info_rows,
        "object_rows": object_rows,
        "source_context": {
            "runtime_source": "ros-topic-inventory.v1",
            "server": server,
            "topic_plan_path": topic_plan_path or None,
            "topic_plan_sha256": topic_plan_sha256 or None,
            "preflight_sha256": preflight_sha256 or None,
            "topic_plan_binding_status": topic_plan_binding_status,
        },
        "capture_metadata": {
            "schema_version": "public-runtime-capture-metadata.v1",
            "origin_schema_version": ROS_TOPIC_INVENTORY_SCHEMA,
            "inventory_path": inventory_path or None,
            "inventory_sha256": inventory_sha256 or None,
            "inventory_status": str(inventory.get("status") or "unknown"),
            "requested_topics": [str(item) for item in inventory.get("requested_topics", []) or []],
            "inventory_observed_at_utc": inventory.get("observed_at_utc"),
            "server": server,
            "topic_plan_binding_status": topic_plan_binding_status,
            "preflight_sha256": preflight_sha256 or None,
            "identity_binding": {
                "status": "not_bound",
                "required_before_runtime_evidence_consumption": [
                    "analysis_run_id",
                    "data_fingerprint",
                    "source_snapshot_hash",
                    "binary_fingerprint",
                    "config_fingerprint",
                    "session_id",
                ],
            },
            "observed_sample_count": observed_sample_count,
            "observed_objectlist_topic_count": observed_objectlist_topic_count,
            "topic_samples": samples,
            "association_policy": {
                "topics_sampled_independently": True,
                "cross_topic_frame_association": "not_asserted",
                "time_neighbour_matching": False,
            },
        },
        "diagnostics": list(dict.fromkeys(diagnostics)),
    }


def _as_rows(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(row) for row in value if isinstance(row, Mapping)]
    raise PublicRuntimeError("runtime channel must be an object or array of objects")


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _identity_value(value: Any) -> Any:
    """Canonicalize numeric identity values without changing raw payloads."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _identity_key(value: Any) -> str:
    return str(_identity_value(value))


def _data(row: Mapping[str, Any]) -> list[Any]:
    value = row.get("data")
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _radar_id(row: Mapping[str, Any]) -> Any:
    value = _first(row, "radar_id", "radar", "radarId")
    if value is None:
        value = _data(row)[0] if _data(row) else None
    return _identity_value(value)


def _is_warning_with_frame(row: Mapping[str, Any]) -> bool:
    explicit = _first(row, "frame_id", "frameID", "frame_counter", "frameCounter")
    if explicit is not None:
        return True
    source = f"{row.get('source', '')} {row.get('topic', '')}".lower()
    if "with_frame" in source:
        return True
    # Current layout: [radar + 15 bits] is 16 values, while
    # [radar + frame + 15 bits] is 17 values. An explicit source/frame field
    # is preferred; this is only the shape fallback.
    return len(_data(row)) >= 17


def _frame_id(row: Mapping[str, Any], *, channel: str) -> Any:
    value = _first(row, "frame_id", "frameID", "frame_counter", "frameCounter")
    if value is not None:
        return _identity_value(value)
    data = _data(row)
    if channel == "warning" and _is_warning_with_frame(row) and len(data) > 1:
        return data[1]
    if channel == "radar_info" and len(data) > 4:
        return _identity_value(data[4])
    return None


def _callback_id(row: Mapping[str, Any]) -> Any:
    return _first(row, "callback_id", "callbackId", "cycle_id", "cycleId")


def _message_sequence(row: Mapping[str, Any]) -> int | None:
    """Return a capture/message sequence without treating it as frameID."""
    value = _first(
        row, "message_seq", "message_sequence", "capture_sequence", "object_message_seq"
    )
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_negative_object_id(row: Mapping[str, Any]) -> bool:
    value = _first(row, "ID", "id", "object_id", "objectId")
    if value in (None, ""):
        return False
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


def _warning_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    if "warnings" not in payload:
        payload["warnings"] = _warning_bits(row)
    if not payload.get("source"):
        payload["source"] = (
            "warning_status_with_frame" if _is_warning_with_frame(row) else "warning_status"
        )
    return payload


def _radar_info_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    data = _data(row)
    payload = dict(row)
    if data:
        payload.setdefault("ego_speed", data[1] if len(data) > 1 else None)
        payload.setdefault("yaw_rate", data[2] if len(data) > 2 else None)
        payload.setdefault("detections_number", data[3] if len(data) > 3 else None)
        payload.setdefault("cycle_time_ms", data[5] if len(data) > 5 else None)
    payload.setdefault("source", "radar_info")
    return payload


def _warning_bits(row: Mapping[str, Any]) -> list[int]:
    value = row.get("bits")
    if value is None:
        value = row.get("warnings")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [int(item) for item in value]
    data = _data(row)
    if not data:
        return []
    source = str(row.get("source", "") or "").lower()
    # with-frame carries [radar, frame, warning...]; the raw/algorithm
    # status channel carries [radar, warning...].  A caller can avoid this
    # convention entirely by passing an explicit bits/warnings array.
    offset = 2 if _is_warning_with_frame(row) or "with_frame" in source else 1
    return [int(item) for item in data[offset:]]


def detect_warning_rising_edges(
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    *,
    warning_names: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Detect per-radar 0-to-nonzero transitions in a warning stream.

    The function name mapping is supplied by the active project/source.  If
    it is absent, generic ``w1``/``w2`` labels are used and no feature claim
    is made.
    """
    samples = _as_rows(rows)
    names = [str(item) for item in (warning_names or [])]
    previous: dict[tuple[str, str], list[int]] = {}
    result: list[dict[str, Any]] = []
    for row in samples:
        radar_id = _radar_id(row)
        if radar_id in (None, ""):
            continue
        bits = _warning_bits(row)
        source = str(row.get("source") or row.get("topic") or "warning_stream")
        key = (_identity_key(radar_id), source)
        old = previous.get(key, [0] * len(bits))
        if len(old) < len(bits):
            old = [*old, *([0] * (len(bits) - len(old)))]
        frame_id = _frame_id(row, channel="warning")
        for index, value in enumerate(bits):
            if value != 0 and old[index] == 0:
                result.append({
                    "radar_id": radar_id,
                    "frame_id": frame_id,
                    "frame_status": "observed" if frame_id not in (None, "") else "not_available",
                    "signal_index": index + 1,
                    "signal_name": names[index] if index < len(names) else f"w{index + 1}",
                    "value": value,
                    "source": source,
                })
        previous[key] = bits
    return result


def normalize_public_runtime(
    *,
    warning_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    radar_info_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    object_rows: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    source_context: Mapping[str, Any] | None = None,
    warning_names: Sequence[str] | None = None,
    object_association_mode: str = "strict",
    object_validity_policy: str = "preserve",
    preflight: Mapping[str, Any] | None = None,
    capture_metadata: Mapping[str, Any] | None = None,
    capture_diagnostics: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Join public rows using an explicitly selected, source-aware policy.

    strict is the engine default and only accepts an object frame/callback carried
    by the input row. publication_order is an opt-in derived association for
    a collector that recorded message order and whose current source analysis
    proves that objectlist publication precedes warning_status_with_frame in
    one processing cycle. It never treats a capture sequence as an algorithm
    frame by itself.

    ``auto`` is the Pi-facing convenience mode: it selects
    ``publication_order`` only when the supplied arbe preflight contains a
    source-verified objectlist-before-warning contract; otherwise it falls
    back to strict.
    """
    requested_object_association_mode = object_association_mode
    source_contract = (
        preflight.get("public_evidence", {}).get("objectlist_frame_contract", {})
        if isinstance(preflight, Mapping)
        and isinstance(preflight.get("public_evidence"), Mapping)
        and isinstance(preflight.get("public_evidence", {}).get("objectlist_frame_contract"), Mapping)
        else {}
    )
    if object_association_mode == "auto":
        object_association_mode = (
            "publication_order"
            if source_contract.get("status") == "source_verified"
            else "strict"
        )
    if object_association_mode not in OBJECT_ASSOCIATION_MODES:
        raise PublicRuntimeError(
            f"unsupported object_association_mode: {object_association_mode}"
        )
    if object_validity_policy not in OBJECT_VALIDITY_POLICIES:
        raise PublicRuntimeError(
            f"unsupported object_validity_policy: {object_validity_policy}"
        )
    warnings = _as_rows(warning_rows)
    radar_infos = _as_rows(radar_info_rows)
    objects = _as_rows(object_rows)
    ignored_objects: list[dict[str, Any]] = []
    if object_validity_policy == "arbe_wf_sobj":
        valid_objects: list[dict[str, Any]] = []
        for row in objects:
            if _is_negative_object_id(row):
                ignored_objects.append({
                    "reason": "arbe_wf_sobj_negative_ID_sentinel",
                    "fields": dict(row),
                })
            else:
                valid_objects.append(row)
        objects = valid_objects
    diagnostics: list[str] = [str(item) for item in (capture_diagnostics or []) if str(item)]
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    callback_frames: dict[tuple[str, str], Any] = {}
    publication_frames: dict[str, list[dict[str, Any]]] = {}
    object_message_sequences: dict[str, set[int]] = {}

    if object_association_mode == "publication_order":
        for row in warnings:
            if not _is_warning_with_frame(row):
                continue
            radar_id = _radar_id(row)
            frame_id = _frame_id(row, channel="warning")
            message_seq = _message_sequence(row)
            if radar_id in (None, "") or frame_id in (None, "") or message_seq is None:
                continue
            publication_frames.setdefault(_identity_key(radar_id), []).append({
                "frame_id": frame_id,
                "message_seq": message_seq,
                "source": str(row.get("source") or row.get("topic") or "warning_status_with_frame"),
            })
        for candidates in publication_frames.values():
            candidates.sort(key=lambda item: item["message_seq"])
        for row in objects:
            radar_id = _radar_id(row)
            message_seq = _message_sequence(row)
            if radar_id not in (None, "") and message_seq is not None:
                object_message_sequences.setdefault(_identity_key(radar_id), set()).add(message_seq)

    def publication_order_frame(row: Mapping[str, Any]) -> dict[str, Any] | None:
        """Correlate one object message with the next frame message.

        The object message must be the only objectlist publication for that
        radar between two adjacent with-frame publications. If the capture
        is incomplete or the order is ambiguous, return None rather than
        guessing by timestamp.
        """
        radar_id = _radar_id(row)
        message_seq = _message_sequence(row)
        if radar_id in (None, "") or message_seq is None:
            return None
        candidates = publication_frames.get(_identity_key(radar_id), [])
        next_frame = next(
            (item for item in candidates if item["message_seq"] > message_seq),
            None,
        )
        if next_frame is None:
            return None
        previous_frames = [
            item for item in candidates if item["message_seq"] < message_seq
        ]
        previous_seq = previous_frames[-1]["message_seq"] if previous_frames else None
        between = {
            value for value in object_message_sequences.get(_identity_key(radar_id), set())
            if (previous_seq is None or value > previous_seq)
            and value < next_frame["message_seq"]
        }
        if between != {message_seq}:
            return None
        return next_frame

    def snapshot_for(radar_id: Any, frame_id: Any) -> dict[str, Any] | None:
        if radar_id in (None, "") or frame_id in (None, ""):
            return None
        key = (_identity_key(radar_id), _identity_key(frame_id))
        if key not in snapshots:
            snapshots[key] = {
                "radar_id": radar_id,
                "frame_id": frame_id,
                "association_status": "frame_verified",
                "warning": None,
                "radar_info": None,
                "objects": [],
                "object_association_status": "unbound",
            }
        return snapshots[key]

    for row in warnings:
        radar_id = _radar_id(row)
        frame_id = _frame_id(row, channel="warning")
        snapshot = snapshot_for(radar_id, frame_id)
        if snapshot is None:
            diagnostics.append("warning_row_missing_radar_or_frame")
            continue
        snapshot["warning"] = _warning_payload(row)
        callback = _callback_id(row)
        if callback is not None:
            callback_frames[(_identity_key(radar_id), str(callback))] = frame_id

    for row in radar_infos:
        radar_id = _radar_id(row)
        frame_id = _frame_id(row, channel="radar_info")
        snapshot = snapshot_for(radar_id, frame_id)
        if snapshot is None:
            diagnostics.append("radar_info_row_missing_radar_or_frame")
            continue
        snapshot["radar_info"] = _radar_info_payload(row)
        callback = _callback_id(row)
        if callback is not None:
            callback_frames[(_identity_key(radar_id), str(callback))] = frame_id

    unbound_objects: list[dict[str, Any]] = []
    publication_ambiguous = 0
    publication_missing_sequence = 0
    for row in objects:
        radar_id = _radar_id(row)
        explicit_frame = _frame_id(row, channel="object")
        callback = _callback_id(row)
        association_status = "unbound"
        frame_id = explicit_frame
        if explicit_frame not in (None, ""):
            association_status = "frame_verified"
        elif callback is not None and (_identity_key(radar_id), str(callback)) in callback_frames:
            frame_id = callback_frames[(_identity_key(radar_id), str(callback))]
            association_status = "callback_correlated"
        elif object_association_mode == "publication_order":
            publication = publication_order_frame(row)
            if publication is not None:
                frame_id = publication["frame_id"]
                association_status = "publication_correlated"
            elif _message_sequence(row) is None:
                publication_missing_sequence += 1
            else:
                publication_ambiguous += 1
        evidence = row.get("association_evidence")
        if not isinstance(evidence, Mapping):
            evidence = None
        if association_status == "publication_correlated":
            evidence = {
                **dict(evidence or {}),
                "method": "same_radar_publication_order",
                "confidence": "derived",
                "basis": "objectlist was the only same-radar object publication between adjacent with-frame publications",
                "object_message_seq": _message_sequence(row),
                "warning_message_seq": publication["message_seq"] if publication is not None else None,
                "warning_frame_id": publication["frame_id"] if publication is not None else None,
            }
        snapshot = snapshot_for(radar_id, frame_id)
        object_record = {
            "association_status": association_status,
            "radar_id": radar_id,
            "frame_id": frame_id,
            "callback_id": callback,
            "object_index": _first(row, "object_index", "index", "message_index"),
            "fields": dict(row),
        }
        if evidence is not None:
            object_record["association_evidence"] = evidence
        if snapshot is None or association_status == "unbound":
            unbound_objects.append(object_record)
            continue
        snapshot["objects"].append(object_record)
        if association_status == "callback_correlated":
            snapshot["object_association_status"] = "callback_correlated"
        elif association_status == "publication_correlated":
            if snapshot["object_association_status"] == "unbound":
                snapshot["object_association_status"] = "publication_correlated"
        elif snapshot["object_association_status"] == "unbound":
            snapshot["object_association_status"] = "frame_verified"

    rows = sorted(snapshots.values(), key=lambda row: (str(row["radar_id"]), str(row["frame_id"])))
    observed_sample_count = (
        capture_metadata.get("observed_sample_count", 0)
        if isinstance(capture_metadata, Mapping)
        else 0
    )
    has_observed_capture = isinstance(observed_sample_count, int) and not isinstance(observed_sample_count, bool) and observed_sample_count > 0
    if rows:
        status = "ready"
    elif warnings or radar_infos or objects:
        status = "partial"
    elif has_observed_capture:
        status = "partial"
        diagnostics.append("observed_runtime_samples_not_projected")
    else:
        status = "blocked"
        diagnostics.append("no_public_runtime_rows")
    if unbound_objects:
        diagnostics.append("objectlist_rows_without_frame_or_callback_remain_unbound")
    if object_association_mode == "publication_order" and publication_ambiguous:
        diagnostics.append("objectlist_publication_association_ambiguous")
    if object_association_mode == "publication_order" and publication_missing_sequence:
        diagnostics.append("objectlist_rows_missing_publication_sequence")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_context": dict(source_context or {}),
        "warning_names": [str(item) for item in (warning_names or []) if str(item).strip()],
        "warning_rising_edges": detect_warning_rising_edges(
            warnings, warning_names=warning_names
        ),
        "snapshots": rows,
        "unbound_objects": unbound_objects,
        "association_policy": {
            "time_neighbour_matching": False,
            "objectlist_current_message_frame": "not_in_message",
            "requested_object_association_mode": requested_object_association_mode,
            "object_association_mode": object_association_mode,
            "source_contract": dict(source_contract) if source_contract else {},
            "object_validity_policy": object_validity_policy,
            "publication_order_requires_current_source_proof": True,
            "accepted_statuses": sorted(ASSOCIATION_STATUSES),
        },
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "ignored_objects": ignored_objects,
    }
    if isinstance(capture_metadata, Mapping):
        payload["capture_metadata"] = dict(capture_metadata)
    return payload


def load_capture(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicRuntimeError(f"cannot read public runtime capture {target}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise PublicRuntimeError("public runtime capture root must be object")
    return dict(value)


__all__ = [
    "ASSOCIATION_STATUSES",
    "OBJECT_ASSOCIATION_MODES",
    "OBJECT_VALIDITY_POLICIES",
    "SCHEMA_VERSION",
    "PublicRuntimeError",
    "load_capture",
    "normalize_public_runtime",
]
