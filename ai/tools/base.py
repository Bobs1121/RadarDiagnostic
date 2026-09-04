# -*- coding: utf-8 -*-
"""
BaseTool — shared contract for Agent-callable deterministic tools.

Each tool exposes a lightweight JSON-schema-like input description and returns a
uniform JSON-serializable result envelope:

    {
        "status": "ok" | "error",
        "message": "...",
        "data": {...},
        "artifacts": ["..."],
    }

Unlike module wrappers, tools cross an Agent boundary directly, so
``safe_execute()`` always catches exceptions and never raises.
"""
from __future__ import annotations

import abc
import dataclasses
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RESULT_KEYS = frozenset({"status", "message", "data", "artifacts"})
_SCHEMA_TYPES = frozenset({
    "string", "integer", "number", "boolean", "object", "array", "null",
})


def serialize_jsonable(value: Any) -> Any:
    """Convert common Python objects into JSON-friendly values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            key: serialize_jsonable(item)
            for key, item in dataclasses.asdict(value).items()
        }
    if isinstance(value, Mapping):
        return {
            str(key): serialize_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [serialize_jsonable(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return serialize_jsonable(to_dict())
    if hasattr(value, "__dict__") and not isinstance(value, type):
        public_fields = {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
        if public_fields:
            return serialize_jsonable(public_fields)
    return str(value)


def build_tool_result(
    *,
    status: str,
    data: Any = None,
    message: str = "",
    artifacts: Any = None,
) -> dict[str, Any]:
    """Build and validate a JSON-serializable tool result envelope."""
    if status not in {"ok", "error"}:
        raise ValueError(f"invalid tool status {status!r}")

    serialized_artifacts = serialize_jsonable(artifacts if artifacts is not None else [])
    if not isinstance(serialized_artifacts, list):
        serialized_artifacts = [serialized_artifacts]

    result = {
        "status": status,
        "message": "" if message is None else str(message),
        "data": serialize_jsonable(data if data is not None else {}),
        "artifacts": serialized_artifacts,
    }
    json.dumps(result)
    return result


def _validate_schema_like(schema: Any) -> None:
    if not isinstance(schema, dict):
        raise TypeError("parameters_schema must be a dict")

    schema_type = schema.get("type", "object")
    if schema_type != "object":
        raise ValueError("parameters_schema.type must be 'object'")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise TypeError("parameters_schema.properties must be a dict")

    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise TypeError("parameters_schema.required must be a list[str]")

    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, (bool, dict)):
        raise TypeError(
            "parameters_schema.additionalProperties must be a bool or dict",
        )

    for key, value in properties.items():
        if not isinstance(key, str):
            raise TypeError("parameters_schema property names must be strings")
        if not isinstance(value, dict):
            raise TypeError(
                f"parameters_schema for property {key!r} must be a dict",
            )
        _validate_property_schema(key, value)


def _validate_property_schema(name: str, schema: dict[str, Any]) -> None:
    expected = schema.get("type")
    if expected is None:
        return
    if isinstance(expected, list):
        if not expected or any(item not in _SCHEMA_TYPES for item in expected):
            raise ValueError(
                f"parameters_schema type list for {name!r} must use JSON schema types",
            )
        return
    if expected not in _SCHEMA_TYPES:
        raise ValueError(
            f"parameters_schema type for {name!r} must be a JSON schema type",
        )


def _matches_schema_type(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_matches_schema_type(value, item) for item in expected)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return False


class BaseTool(abc.ABC):
    """Abstract base for deterministic tools callable by an Agent loop."""

    name: str = "base-tool"
    description: str = ""
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "additionalProperties": True,
    }

    @abc.abstractmethod
    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Run the tool. Implementations may raise; callers should use
        :meth:`safe_execute` across Agent boundaries."""
        raise NotImplementedError

    def safe_execute(self, params: Any) -> dict[str, Any]:
        """Run the tool and convert failures into a structured error result."""
        try:
            _validate_schema_like(self.parameters_schema)
            if not isinstance(params, dict):
                raise TypeError("params must be a dict")
            self._validate_params(params)
            raw_result = self.execute(dict(params))
            return self._normalize_result(raw_result)
        except Exception as exc:  # noqa: BLE001 - boundary guard by design
            if not isinstance(exc, (TypeError, ValueError)):
                log.exception("Tool '%s' failed", self.name)
            return self.error(f"{type(exc).__name__}: {exc}")

    def ok(
        self,
        *,
        data: Any = None,
        message: str = "",
        artifacts: Any = None,
    ) -> dict[str, Any]:
        return build_tool_result(
            status="ok",
            data=data,
            message=message,
            artifacts=artifacts,
        )

    def error(
        self,
        message: str,
        *,
        data: Any = None,
        artifacts: Any = None,
    ) -> dict[str, Any]:
        return build_tool_result(
            status="error",
            data=data,
            message=message,
            artifacts=artifacts,
        )

    def _validate_params(self, params: dict[str, Any]) -> None:
        schema = self.parameters_schema
        required = schema.get("required", [])
        missing = [name for name in required if name not in params]
        if missing:
            raise ValueError(
                "missing required parameter(s): " + ", ".join(sorted(missing)),
            )

        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        if additional is False:
            unknown = sorted(key for key in params if key not in properties)
            if unknown:
                raise ValueError(
                    "unexpected parameter(s): " + ", ".join(unknown),
                )

        for key, value in params.items():
            prop_schema = properties.get(key)
            if not isinstance(prop_schema, dict):
                continue
            expected_type = prop_schema.get("type")
            if expected_type and not _matches_schema_type(value, expected_type):
                raise TypeError(
                    f"parameter {key!r} must match schema type {expected_type!r}",
                )

    def _normalize_result(self, raw_result: Any) -> dict[str, Any]:
        if not isinstance(raw_result, dict):
            raise TypeError(
                f"{self.name}.execute() returned {type(raw_result).__name__}, "
                "expected dict",
            )

        extra_payload = {
            key: value
            for key, value in raw_result.items()
            if key not in _RESULT_KEYS
        }
        data = raw_result.get("data")
        if data is None:
            data = extra_payload
        elif extra_payload:
            if isinstance(data, dict):
                merged = dict(data)
                merged.update(extra_payload)
                data = merged
            else:
                data = {"result": data, **extra_payload}

        return build_tool_result(
            status=raw_result.get("status", "ok"),
            data=data,
            message=raw_result.get("message", ""),
            artifacts=raw_result.get("artifacts", []),
        )
