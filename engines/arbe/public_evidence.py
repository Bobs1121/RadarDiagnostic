# -*- coding: utf-8 -*-
"""Public arbe evidence planning and bundle audit.

This module describes what can be observed without GDB and audits the
deterministic Sprint1 bundle.  It never subscribes to ROS itself and never
claims that a display topic is a complete algorithm structure.  A future ROS
collector can implement the same channel contract without changing Pi.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any, Mapping


TOPIC_PLAN_SCHEMA = "public-topic-plan.v1"
AUDIT_SCHEMA = "public-evidence-audit.v1"


def load_json_mapping(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def load_profile_mapping(path: str | Path) -> dict[str, Any]:
    with Path(path).expanduser().open("rb") as handle:
        value = tomllib.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"profile root must be an object: {path}")
    return value


def _configured(profile: Mapping[str, Any], key: str) -> str:
    arbe = profile.get("arbe", {})
    return str(arbe.get(key, "")).strip() if isinstance(arbe, Mapping) else ""


def _radar_ids(profile: Mapping[str, Any]) -> list[int]:
    arbe = profile.get("arbe", {})
    result: list[int] = []
    if isinstance(arbe, Mapping):
        for key in arbe:
            if str(key).startswith("radar") and str(key)[5:].isdigit():
                result.append(int(str(key)[5:]))
    # Do not assume a four-radar vehicle.  A profile without explicit radar
    # entries can still expose generic topic patterns, but no per-radar topic
    # expansion is emitted.
    return sorted(set(result))


def build_public_topic_plan(
    *,
    profile: Mapping[str, Any] | None = None,
    preflight: Mapping[str, Any] | None = None,
    runtime_schema: Mapping[str, Any] | None = None,
    topic_inventory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe configured public channels and their evidence guarantees."""
    profile = profile or {}
    preflight = preflight or {}
    runtime_schema = runtime_schema or {}
    topic_inventory = topic_inventory or {}
    inventory_rows = {
        str(item.get("topic")): item
        for item in topic_inventory.get("topics", []) or []
        if isinstance(item, Mapping) and item.get("topic")
    }
    radar_ids = _radar_ids(profile)
    lgu_pattern = _configured(profile, "lgu_topic_pattern")
    object_pattern = _configured(profile, "object_topic_pattern")
    warning_topic = _configured(profile, "warning_topic")
    warning_with_frame = _configured(profile, "warning_with_frame_topic")
    raw_warning = _configured(profile, "raw_warning_topic")
    channels: list[dict[str, Any]] = []

    def add(
        channel_id: str,
        topic: str,
        *,
        source_kind: str,
        frame_key: str,
        guarantee: str,
        gdb_required: bool,
        notes: list[str] | None = None,
    ) -> None:
        channels.append(
            {
                "channel_id": channel_id,
                "topic": topic,
                "source_kind": source_kind,
                "frame_key": frame_key,
                "guarantee": guarantee,
                "gdb_required": gdb_required,
                "notes": list(notes or []),
            }
        )
        if topic in inventory_rows:
            observed = inventory_rows[topic]
            channels[-1]["runtime_observation"] = {
                "status": observed.get("status", ""),
                "type": observed.get("type", ""),
                "publisher_count": observed.get("publisher_count", 0),
                "subscriber_count": observed.get("subscriber_count", 0),
                "publisher_present": observed.get(
                    "publisher_present", bool(observed.get("publisher_count", 0))
                ),
                "message_observable": observed.get("message_observable"),
                "observability_basis": observed.get("observability_basis", "publisher_presence"),
                "data_observable": bool(observed.get("data_observable", False)),
            }
        elif inventory_rows and "{" not in topic:
            channels[-1]["runtime_observation"] = {
                "status": "not_in_inventory",
                "data_observable": False,
            }

    if lgu_pattern:
        add(
            "lgu_input",
            lgu_pattern,
            source_kind="bag_or_ros_wfAutosarData",
            frame_key="wfAutosarData.frameID",
            guarantee="current source layout can decode per-frame ego/SGU input",
            gdb_required=False,
            notes=["preserve raw_sgu_index=i and algorithm_object_index=k"],
        )
        for radar_id in radar_ids:
            add(
                f"lgu_input_{radar_id}",
                lgu_pattern.replace("{radar_id}", str(radar_id)),
                source_kind="bag_or_ros_wfAutosarData",
                frame_key="wfAutosarData.frameID",
                guarantee="per-radar input frame with source-layout decode candidate",
                gdb_required=False,
                notes=["preserve raw_sgu_index=i and algorithm_object_index=k"],
            )
    if object_pattern:
        add(
            "algorithm_object_display",
            object_pattern,
            source_kind="ros_wfObjectMsg",
            frame_key="not_in_message",
            guarantee="display subset of algorithm object output",
            gdb_required=False,
            notes=["correlate with frame-bearing channel; wfObjectMsg has no frameID"],
        )
    if warning_topic:
        add(
            "algorithm_warning",
            warning_topic,
            source_kind="ros_algorithm_warning",
            frame_key="not_in_message",
            guarantee="algorithm warning status without explicit frame",
            gdb_required=False,
            notes=["do not call this CAN Tx evidence"],
        )
    if warning_with_frame:
        add(
            "algorithm_warning_with_frame",
            warning_with_frame,
            source_kind="ros_algorithm_warning",
            frame_key="data[1]",
            guarantee="algorithm warning status aligned to visualization frame_counter",
            gdb_required=False,
            notes=["proxy for CAN Tx when RTE/Com chain is not observed"],
        )
    if raw_warning:
        add(
            "raw_can_warning",
            raw_warning,
            source_kind="ros_can_decoder",
            frame_key="not_in_message",
            guarantee="CAN/ECU-side warning status",
            gdb_required=False,
            notes=["keep separate from algorithm event"],
        )
    for radar_id in radar_ids:
        if object_pattern:
            add(
                f"algorithm_object_display_{radar_id}",
                object_pattern.replace("{radar_id}", str(radar_id)),
                source_kind="ros_wfObjectMsg",
                frame_key="not_in_message",
                guarantee="per-radar display object subset",
                gdb_required=False,
            )

    runtime_identity = preflight.get("workspace", {}) if isinstance(preflight, Mapping) else {}
    public_contract = (
        preflight.get("public_evidence", {})
        if isinstance(preflight, Mapping) and isinstance(preflight.get("public_evidence"), Mapping)
        else {}
    )
    return {
        "schema_version": TOPIC_PLAN_SCHEMA,
        "status": "ready" if channels else "blocked",
        "radar_ids": radar_ids,
        "channels": channels,
        "source_schema": {
            "source_context": runtime_schema.get("source_context", {}),
            "message_contract": runtime_schema.get("message_contract", {}),
            "preflight_workspace": runtime_identity,
            "preflight_public_evidence": public_contract,
        },
        "without_gdb": [
            "wfAutosarData.frameID",
            "PERInfoOutStruct.egoCarInfoTrans fields present in the active layout",
            "PERInfoOutStruct.objTrans[i] fields present in the active layout",
            "algorithm warning/frame topic payloads",
            "wfObjectMsg display subset",
            "radar_info summary",
        ],
        "gdb_or_probe_required": [
            "g_egoCarAddInfo derived state",
            "sObj/objPoly/local gate variables and exact i scope",
            "runtime-only parameters not published to a public channel",
            "internal FCTA/FCTB warning counter absent from compressed objOutStrunct",
            "actual RteComMapping_TxRunnable -> RteLite_Write_* -> Com_SendSignal hit",
        ],
    }


def _walk_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _field_names(rows: list[Mapping[str, Any]], key: str) -> list[str]:
    names: set[str] = set()
    for row in rows:
        child = row.get(key)
        if isinstance(child, Mapping):
            names.update(str(name) for name in child.keys())
    return sorted(names)


def audit_public_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Audit public evidence available in one deterministic bundle."""
    # Do not recursively treat every dictionary in a bundle as a frame.  Event
    # metadata, breakpoint packs and nested target summaries contain fields
    # named `frame_id` too, but they are not frame samples.
    frame_rows: list[Mapping[str, Any]] = []
    for event in bundle.get("alarm_events", []) or []:
        if not isinstance(event, Mapping):
            continue
        for frame in event.get("frame_evidence", []) or []:
            if isinstance(frame, Mapping):
                frame_rows.append(frame)
    for frame in bundle.get("frame_evidence", []) or []:
        if isinstance(frame, Mapping):
            frame_rows.append(frame)
    ego_rows = [item for item in frame_rows if isinstance(item.get("ego"), Mapping)]
    frame_object_rows: list[Mapping[str, Any]] = []
    for frame in frame_rows:
        for item in frame.get("objects", []) or []:
            if isinstance(item, Mapping):
                frame_object_rows.append(item)
    object_rows = list(frame_object_rows)
    for item in bundle.get("object_candidates", []) or []:
        if isinstance(item, Mapping):
            object_rows.append(item)
    for event in bundle.get("alarm_events", []) or []:
        if isinstance(event, Mapping):
            selected = event.get("selected_target")
            if isinstance(selected, Mapping):
                object_rows.append(selected)
    explicit_frame_ids = [
        item.get("frame_id")
        for item in frame_rows
        if item.get("frame_id") not in (None, 0, "")
    ]
    frame_sources = sorted(
        {
            str(item.get("frame_id_source") or "wfAutosarData.frameID")
            for item in frame_rows
            if item.get("frame_id") not in (None, "")
        }
    )
    warning = bundle.get("recorded_warning", {})
    warning = warning if isinstance(warning, Mapping) else {}
    warning_topics = warning.get("topics", {})
    warning_topics = warning_topics if isinstance(warning_topics, Mapping) else {}
    if not warning_topics:
        precheck = bundle.get("arbe_precheck", {})
        precheck_warning = precheck.get("warning", {}) if isinstance(precheck, Mapping) else {}
        warning_topics = (
            precheck_warning.get("topics", {})
            if isinstance(precheck_warning, Mapping)
            else {}
        )
        warning_topics = warning_topics if isinstance(warning_topics, Mapping) else {}
    with_frame = warning_topics.get("with_frame", {})
    with_frame = with_frame if isinstance(with_frame, Mapping) else {}
    object_fields = sorted(
        {
            str(key)
            for row in object_rows
            for key in row.keys()
            if key not in {"raw", "flags"}
        }
    )
    source_layers = sorted(
        {
            str(item.get("source_layer", ""))
            for item in object_rows
            if item.get("source_layer")
        }
    )
    ego_fields = _field_names(ego_rows, "ego")
    decoder_contract = bundle.get("decoder_contract", {})
    decoder_contract = decoder_contract if isinstance(decoder_contract, Mapping) else {}
    has_lgu = bool(frame_rows)
    has_object = bool(object_rows)
    has_explicit_warning_frame = bool(with_frame.get("present") and explicit_frame_ids)
    gaps = [str(item) for item in bundle.get("evidence_gaps", []) or []]
    status = "ready" if has_lgu else "partial" if has_object else "blocked"
    return {
        "schema_version": AUDIT_SCHEMA,
        "status": status,
        "case": bundle.get("case", {}),
        "source_context": bundle.get("source_context", {}),
        "frame_evidence": {
            "row_count": len(frame_rows),
            "explicit_frame_id_count": len(explicit_frame_ids),
            "frame_id_sources": frame_sources,
            "exact_frame_available": bool(explicit_frame_ids),
            "source_preference": "wfAutosarData.frameID",
        },
        "ego_evidence": {
            "available_without_gdb": bool(ego_rows),
            "row_count": len(ego_rows),
            "fields_observed": ego_fields,
            "source": "wfAutosarData decoded active PERInfoOutStruct layout"
            if ego_rows
            else "not_available",
        },
        "object_evidence": {
            "available_without_gdb": has_object,
            "row_count": len(object_rows),
            "fields_observed": object_fields,
            "source_layers": source_layers,
            "index_tokens": [
                "raw_sgu_index",
                "algorithm_object_index",
                "objectlist_message_index",
                "trc_index_i",
            ],
        },
        "warning_evidence": {
            "recorded_topics": {
                str(key): dict(value)
                for key, value in warning_topics.items()
                if isinstance(value, Mapping)
            },
            "explicit_algorithm_frame_warning": has_explicit_warning_frame,
            "can_tx_observed": False,
            "can_tx_status": "not_observed_by_public_bundle",
        },
        "decoder_contract": decoder_contract,
        "without_gdb": [
            "bag-carried frameID and decoded ego input",
            "bag-carried raw SGU fields supported by active decoder layout",
            "public algorithm object display subset",
            "warning/radar_info/ROI public payloads when recorded",
        ],
        "gdb_required_or_unavailable": [
            "algorithm-local g_egoCarAddInfo/sObj/objPoly values",
            "all objOutDataStruct fields not present in the public message",
            "internal warning counter absent from compressed objOutStrunct",
            "exact final CAN Tx hit",
        ],
        "evidence_gaps": gaps,
    }


__all__ = [
    "AUDIT_SCHEMA",
    "TOPIC_PLAN_SCHEMA",
    "audit_public_bundle",
    "build_public_topic_plan",
    "load_json_mapping",
    "load_profile_mapping",
]
