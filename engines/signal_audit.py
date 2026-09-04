# -*- coding: utf-8 -*-
"""
Key-chain signal audit engine (deterministic, no LLM).

Purpose: audit the CAN signals that form the "switch send/receive chain"
(HMI switch input -> radar enable -> radar status/echo output) for:

  1. presence          — is the signal actually observed on the bus?
  2. value distribution — which values appear and at what ratio
  3. enum validity     — observed values that are not legal DBC choices
  4. contract checks   — cross-signal expectations, e.g.:
       * ADCMode_UI_Status must be 1 (Old UI) or 2 (New UI); a sustained
         value 3 (Reserved) is an anomaly worth reporting
       * FCTA_FCTB_Status_S is the *echo* the radar sends back only in
         New-UI mode; in Old-UI mode the radar only consumes the HMI
         enable signals and does NOT transmit the echo, so a constant
         Invalid on that signal must NOT be read as "radar not responding"

The contract table encodes evidence-chain knowledge that a plain
"conditions vs data" checker cannot derive from code alone; each entry
carries the code reference that justifies the expectation.

The engine emits markdown that the orchestrator injects into the expert
panel context and that the report template surfaces as a dedicated
section ("关键链路信号审计").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# ── Key-chain signal contract ────────────────────────────────────────
# can_id is informational (used to look up the DBC message when the
# signal name is ambiguous across DBC files); the engine resolves the
# actual message via dbc_loader.find_message_by_signal().
SIGNAL_AUDIT_CONTRACT: list[dict[str, Any]] = [
    {
        "name": "ADCMode_UI_Status",
        "can_id": 0x432,
        "role": "UI 模式指示(开关收发链路根信号, RX from MPC)",
        "expect": "1=Old UI / 2=New UI",
        "contract": (
            "决定雷达用哪条开关链路: 新 UI 走 0x32B 合并开关, 旧 UI 走 0x4EF 独立开关。"
            "持续发 3=Reserved 不符合预期, 应排查 MPC 发送侧配置。"
            "代码: ASWIN_AdasFunc.c BYD_HMI_FCTA_AdasEnableCond (按 ADCMode_UI_Status 分流)"
        ),
        "anomaly_values": [3],
    },
    {
        "name": "FCTA_Enable_S",
        "can_id": 0x4EF,
        "role": "FCTA 开关输入 (RX from Media, 旧 UI 链路)",
        "expect": "1=Switchoff / 2=Switchon",
        "contract": (
            "旧 UI 下 HMI 只下发 enable 请求, 雷达不回传开关状态。"
            "观测到 Switchoff 但 0x2CA 无 OFF 状态属正常(回传契约不成立), "
            "不能据此断言雷达未响应。代码: ADAS_HMI.c ADAS_Swt_Update (0x4EF 分支)"
        ),
        "anomaly_values": [3],
    },
    {
        "name": "FCTB_Enable_S",
        "can_id": 0x4EF,
        "role": "FCTB 开关输入 (RX from Media, 旧 UI 链路)",
        "expect": "1=Switchoff / 2=Switchon",
        "contract": (
            "同 FCTA_Enable_S: 旧 UI 下雷达只收 enable 不回传状态。"
            "代码: ADAS_HMI.c ADAS_Swt_Update (0x4EF 分支)"
        ),
        "anomaly_values": [3],
    },
    {
        "name": "FCTA_FCTB_Enable_S",
        "can_id": 0x32B,
        "role": "FCTA/FCTB 合并开关输入 (RX from Media, 新 UI 链路)",
        "expect": "1=close / 2=earlywarning / 3=brake / 4=EarlywarningAndBrake",
        "contract": (
            "新 UI 链路信号。若 BLF 中缺席而 0x4EF 存在, 说明当前走旧 UI 链路; "
            "若新 UI 模式下缺席则是 HMI 发送侧问题。代码: "
            "ASW_ComMapping/RteComMapping_Rx.c (Media_0x32B 分支)"
        ),
        "anomaly_values": [0],
    },
    {
        "name": "FCTA_FCTB_Status_S",
        "can_id": 0x2CA,
        "role": "FCTA/FCTB 开关状态回传 (TX from FCR, 仅新 UI)",
        "expect": "1=FCTA_OFF_FCTB_OFF / 2=FCTA_ON_FCTB_OFF / 3=FCTA_OFF_FCTB_ON / 4=FCTA_ON_FCTB_ON",
        "contract": (
            "这是雷达对新 UI HMI 请求的响应回传信号; 旧 UI 模式下雷达不回传, "
            "持续 Invalid 属正常现象, 不能作为'雷达未响应'证据。"
            "代码: ADAS_HMI.c ADAS_FCTS_Status + RteComMapping_Tx.c (FCTA_FCTB_Status_S)"
        ),
        "anomaly_values": [],
    },
    {
        "name": "Sts_FCTA_S",
        "can_id": 0x2CA,
        "role": "FCTA 系统状态 (TX from FCR)",
        "expect": "0=OFF / 1=Standby / 2=Active / 3=Fault",
        "contract": (
            "雷达实际功能状态。若开关已下发 OFF 而 Sts 保持 Standby, "
            "需结合 ADCMode_UI_Status 判定: 旧 UI 下以 enable 链为准, "
            "新 UI 下应出现 OFF。代码: RteComMapping_Tx.c Sts_FCTA_S"
        ),
        "anomaly_values": [],
    },
    {
        "name": "Sts_FCTB_S",
        "can_id": 0x2CA,
        "role": "FCTB 系统状态 (TX from FCR)",
        "expect": "0=OFF / 1=Standby / 2=Active / 3=Fault",
        "contract": "同 Sts_FCTA_S。代码: RteComMapping_Tx.c Sts_FCTB_S",
        "anomaly_values": [],
    },
]


@dataclass
class SignalAuditEntry:
    """Audit result for a single key-chain signal."""

    name: str
    role: str
    expect: str
    contract: str
    present: bool = False
    message_name: str = ""
    can_id: Optional[int] = None
    frame_count: int = 0
    observed_values: dict[Any, int] = field(default_factory=dict)
    legal_choices: dict[Any, str] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_anomalous(self) -> bool:
        return bool(self.anomalies)

    def to_markdown_row(self) -> str:
        observed = ", ".join(
            f"{v}x{cnt}" for v, cnt in sorted(
                self.observed_values.items(), key=lambda kv: (-kv[1], str(kv[0]))
            )
        ) if self.observed_values else "(无帧)"
        verdict = "异常" if self.is_anomalous else ("正常" if self.present else "缺席")
        remarks = list(self.anomalies) + list(self.notes)
        identity = ""
        if self.message_name:
            identity = f"{self.message_name}"
            if self.can_id is not None:
                identity += f"(0x{self.can_id:X})"
        return (
            f"| {self.name} | {identity} | {self.role} | {verdict} | {observed} | "
            f"{'; '.join(remarks) if remarks else '-'} |"
        )


class SignalAuditEngine:
    """Audit key-chain CAN signals against the contract table.

    The engine is deliberately deterministic (no LLM) and reusable:
      * audit()          — contract-based audit for the diagnosis pipeline
      * extract_signal() — generic per-signal extraction used by the
                           signal-audit module and data queries
    """

    def __init__(self, contract: Optional[list[dict[str, Any]]] = None) -> None:
        self.contract = list(contract) if contract is not None else SIGNAL_AUDIT_CONTRACT

    # ── generic extraction (module / query reuse) ────────────────────
    def extract_signal(
        self, store, signal_name: str, dbc_loader=None, can_id: Optional[int] = None
    ) -> dict[str, Any]:
        """Extract value distribution and enum validity for one signal.

        Works for any signal on the bus (not only contract signals), so it
        can back ad-hoc user queries against a BLF.
        """
        result: dict[str, Any] = {
            "signal": signal_name,
            "present": False,
            "can_id": None,
            "message_name": "",
            "frame_count": 0,
            "observed_values": {},
            "legal_choices": {},
            "anomalies": [],
        }
        inv = self._signal_inventory(store).get(signal_name)
        if inv:
            result["can_id"] = inv["can_id"]
            result["message_name"] = inv.get("message_name", "")
        msg_info = None
        if dbc_loader is not None:
            msg_info = dbc_loader.find_message_by_signal(signal_name)
        if msg_info is not None and result["can_id"] is None:
            result["can_id"] = msg_info[0]
            result["message_name"] = msg_info[1]
        if can_id is not None:
            result["can_id"] = can_id

        if result["can_id"] is not None:
            if dbc_loader is not None:
                result["legal_choices"] = (
                    dbc_loader.get_signal_choices(result["can_id"], signal_name) or {}
                )
            timeline = store.query_signal_timeline(result["can_id"], signal_name)
            result["frame_count"] = len(timeline)
            for row in timeline:
                value = self._plain_value(row.get("value"))
                result["observed_values"][value] = (
                    result["observed_values"].get(value, 0) + 1
                )
            result["present"] = result["frame_count"] > 0

        legal_values = set(result["legal_choices"].keys())
        for value, count in sorted(result["observed_values"].items()):
            if legal_values and value not in legal_values:
                result["anomalies"].append(
                    f"非法枚举值 {value} x{count}(DBC 合法值: {sorted(legal_values)})"
                )
        return result

    def extract_signals(
        self, store, signal_names: list[str], dbc_loader=None
    ) -> dict[str, Any]:
        """Extract a batch of signals; missing ones are marked absent."""
        results = []
        for name in signal_names:
            try:
                results.append(self.extract_signal(store, name, dbc_loader))
            except Exception as exc:  # noqa: BLE001 - keep batch extraction robust
                results.append({
                    "signal": name, "present": False, "error": str(exc),
                })
        return {"signals": results}

    # ── contract audit (diagnosis pipeline) ──────────────────────────
    def audit(self, store, dbc_loader) -> dict[str, Any]:
        """Run the audit.

        Args:
            store: FrameStore-like object exposing get_signal_inventory()
                and query_signal_timeline(can_id, signal_name).
            dbc_loader: DBCLoader-like object exposing
                find_message_by_signal(name) and get_signal_choices(can_id, name).

        Returns:
            dict {entries: [SignalAuditEntry...], anomalies: [str...],
                  markdown: str, contract_note: str}
        """
        inventory = self._build_inventory(store)
        ui_mode = self._observe_ui_mode(store, dbc_loader, inventory)
        entries: list[SignalAuditEntry] = []
        anomalies: list[str] = []

        for spec in self.contract:
            entry = self._audit_one(spec, store, dbc_loader, inventory, ui_mode)
            entries.append(entry)
            if entry.is_anomalous:
                anomalies.append(
                    f"{entry.name}: {'; '.join(entry.anomalies)}"
                )

        markdown = self._render_markdown(entries)
        contract_note = self._render_contract_note(entries)
        return {
            "entries": entries,
            "anomalies": anomalies,
            "markdown": markdown,
            "contract_note": contract_note,
        }

    # ── internals ────────────────────────────────────────────────────
    @staticmethod
    def _plain_value(value: Any) -> Any:
        """Normalize decoded values to JSON-safe scalars.

        cantools may return NamedSignalValue objects when a DBC value
        table exists; keep the numeric code so enum checks and output
        stay deterministic and JSON-serializable.
        """
        if hasattr(value, "value"):
            return value.value
        return value

    def _signal_inventory(self, store) -> dict[str, dict]:
        """Map signal name -> {can_id, message_name} from actual frames."""
        inventory: dict[str, dict] = {}
        for item in store.get_signal_inventory() or []:
            for sig in item.get("signals", []):
                inventory[sig] = {
                    "can_id": item.get("can_id"),
                    "message_name": item.get("message_name", ""),
                }
        return inventory

    def _build_inventory(self, store) -> dict[str, dict]:
        return self._signal_inventory(store)

    def _observe_ui_mode(self, store, dbc_loader, inventory) -> Optional[int]:
        """Observe ADCMode_UI_Status from frames; None if absent or not constant."""
        spec = next((s for s in self.contract if s["name"] == "ADCMode_UI_Status"), None)
        if spec is None:
            return None
        inv = inventory.get("ADCMode_UI_Status")
        can_id = inv["can_id"] if inv else None
        if can_id is None and dbc_loader is not None:
            msg_info = dbc_loader.find_message_by_signal("ADCMode_UI_Status")
            if msg_info is not None:
                can_id = msg_info[0]
        if can_id is None:
            return None
        timeline = store.query_signal_timeline(can_id, "ADCMode_UI_Status")
        if not timeline:
            return None
        values = {self._plain_value(row.get("value")) for row in timeline}
        if len(values) == 1:
            value = next(iter(values))
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    def _audit_one(self, spec, store, dbc_loader, inventory, ui_mode=None) -> SignalAuditEntry:
        name = spec["name"]
        entry = SignalAuditEntry(
            name=name,
            role=spec.get("role", ""),
            expect=spec.get("expect", ""),
            contract=spec.get("contract", ""),
        )

        # Resolve actual message: prefer frame inventory, fall back to DBC.
        inv = inventory.get(name)
        msg_info = None
        if inv:
            entry.can_id = inv["can_id"]
            entry.message_name = inv.get("message_name", "")
        if dbc_loader is not None:
            msg_info = dbc_loader.find_message_by_signal(name)
        if msg_info is not None and entry.can_id is None:
            entry.can_id = msg_info[0]
            entry.message_name = msg_info[1]

        # Legal choices from DBC value table.
        if dbc_loader is not None and entry.can_id is not None:
            entry.legal_choices = (
                dbc_loader.get_signal_choices(entry.can_id, name) or {}
            )

        # Presence + value distribution from frames.
        if entry.can_id is not None:
            timeline = store.query_signal_timeline(entry.can_id, name)
            entry.frame_count = len(timeline)
            for row in timeline:
                value = self._plain_value(row.get("value"))
                entry.observed_values[value] = entry.observed_values.get(value, 0) + 1
            entry.present = entry.frame_count > 0

        # Enum validity vs DBC choices (physical values already decoded).
        legal_values = set(entry.legal_choices.keys())
        for value, count in sorted(entry.observed_values.items()):
            if legal_values and value not in legal_values:
                entry.anomalies.append(
                    f"非法枚举值 {value} x{count}(DBC 合法值: {sorted(legal_values)})"
                )

        # Contract rule 1: sustained Reserved/Invalid on the mode signal.
        anomaly_values = [int(v) for v in spec.get("anomaly_values", [])]
        if anomaly_values and entry.observed_values:
            obs = set(entry.observed_values.keys())
            try:
                hits = [v for v in anomaly_values if v in obs]
            except TypeError:
                hits = []
            if hits and set(obs) <= set(hits):
                entry.anomalies.append(
                    f"持续发送异常枚举 {hits} (期望 {entry.expect})"
                )
            elif hits:
                entry.anomalies.append(f"出现异常枚举 {hits} (期望 {entry.expect})")

        # Contract rule 2: echo signal contract (old UI does not echo).
        if name == "FCTA_FCTB_Status_S" and entry.present and not entry.anomalies:
            obs = set(entry.observed_values.keys())
            if obs and all(v == 0 for v in obs):
                if ui_mode is not None and ui_mode != 2:
                    entry.notes.append(
                        f"全程 Invalid(0) 且 ADCMode_UI_Status={ui_mode}(非新 UI): "
                        "符合'旧 UI 不回传状态'契约, 不构成雷达未响应证据"
                    )
                else:
                    entry.notes.append(
                        "全程 Invalid(0): 若为新 UI 则回传缺失, 需确认 UI 模式"
                    )
        return entry

    def _render_markdown(self, entries: list[SignalAuditEntry]) -> str:
        lines = [
            "关键链路信号审计(确定性枚举/契约校验, 非 LLM 推断):",
            "",
            "| 信号 | 消息(0xID) | 角色 | 判定 | 观测值(值x帧数) | 异常/备注 |",
            "|------|-----------|------|------|------------------|----------|",
        ]
        for entry in entries:
            lines.append(entry.to_markdown_row())
        return "\n".join(lines)

    def _render_contract_note(self, entries: list[SignalAuditEntry]) -> str:
        notes = [
            e for e in entries
            if (e.is_anomalous or e.notes) and e.name in ("ADCMode_UI_Status", "FCTA_FCTB_Status_S")
        ]
        if not notes:
            return ""
        lines = ["契约判定(证据链知识):"]
        for entry in notes:
            for note in (entry.notes or []):
                lines.append(f"- {entry.name}: {note}")
            if entry.is_anomalous:
                lines.append(f"- {entry.name}: {entry.contract}")
        return "\n".join(lines)
