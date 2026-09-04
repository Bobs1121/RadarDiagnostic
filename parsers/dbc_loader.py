# -*- coding: utf-8 -*-
"""
DBC file loader and CAN signal decoder.
Manages multiple DBC files and routes CAN IDs to the correct decoder.
"""
import cantools
from pathlib import Path
from typing import Optional


class DbcLoader:
    """Load and manage multiple DBC files for CAN signal decoding.

    First-loaded DBC wins for any CAN ID conflict. This prevents
    rear-corner private DBC from overwriting front-corner or public
    definitions when they share the same ID range on different buses.
    """

    def __init__(self, dbc_paths: list[str | Path], base_dir: Optional[Path] = None):
        self.databases: list[cantools.database.Database] = []
        self._id_to_db: dict[int, cantools.database.Database] = {}
        self._id_to_msg: dict[int, cantools.database.Message] = {}
        self._id_to_dbc_name: dict[int, str] = {}
        self.conflicts: list[dict] = []

        for p in dbc_paths:
            path = Path(p)
            if not path.is_absolute() and base_dir:
                path = base_dir / path
            if not path.exists():
                print(f"[WARN] DBC not found: {path}")
                continue
            try:
                db = cantools.database.load_file(str(path))
                self.databases.append(db)
                for msg in db.messages:
                    if msg.frame_id in self._id_to_msg:
                        prev = self._id_to_msg[msg.frame_id]
                        self.conflicts.append({
                            "frame_id": msg.frame_id,
                            "hex": f"0x{msg.frame_id:X}",
                            "kept_name": prev.name,
                            "kept_dbc": self._id_to_dbc_name[msg.frame_id],
                            "skipped_name": msg.name,
                            "skipped_dbc": path.name,
                        })
                    else:
                        self._id_to_db[msg.frame_id] = db
                        self._id_to_msg[msg.frame_id] = msg
                        self._id_to_dbc_name[msg.frame_id] = path.name
            except Exception as e:
                print(f"[WARN] Failed to load DBC {path.name}: {e}")

        if self.conflicts:
            skipped_count = len(self.conflicts)
            dbc_names = {c["skipped_dbc"] for c in self.conflicts}
            print(f"[INFO] DBC: {skipped_count} conflicting IDs skipped "
                  f"(first-loaded wins). Affected DBCs: {', '.join(dbc_names)}")

    @property
    def known_ids(self) -> set[int]:
        return set(self._id_to_msg.keys())

    def get_message_name(self, can_id: int) -> Optional[str]:
        msg = self._id_to_msg.get(can_id)
        return msg.name if msg else None

    def get_signal_names(self, can_id: int) -> list[str]:
        msg = self._id_to_msg.get(can_id)
        if not msg:
            return []
        return [s.name for s in msg.signals]

    def decode(self, can_id: int, data: bytes) -> Optional[dict]:
        """
        Decode a CAN frame's data bytes into physical signal values.
        Returns dict of {signal_name: physical_value} or None if unknown ID.
        """
        msg = self._id_to_msg.get(can_id)
        if not msg:
            return None
        try:
            return msg.decode(data, decode_choices=False)
        except Exception:
            try:
                return msg.decode(data[:msg.length], decode_choices=False)
            except Exception:
                return None

    def get_message_info(self, can_id: int) -> Optional[dict]:
        """Get detailed info about a CAN message definition."""
        msg = self._id_to_msg.get(can_id)
        if not msg:
            return None
        signals = []
        for s in msg.signals:
            signals.append({
                "name": s.name,
                "start_bit": s.start,
                "length": s.length,
                "byte_order": s.byte_order,
                "scale": s.scale,
                "offset": s.offset,
                "minimum": s.minimum,
                "maximum": s.maximum,
                "unit": s.unit or "",
                "comment": s.comment or "",
            })
        return {
            "name": msg.name,
            "frame_id": msg.frame_id,
            "frame_id_hex": f"0x{msg.frame_id:X}",
            "length": msg.length,
            "comment": msg.comment or "",
            "signals": signals,
        }

    def get_all_messages_summary(self) -> list[dict]:
        """Get a summary of all known CAN messages across all DBCs."""
        result = []
        for can_id, msg in sorted(self._id_to_msg.items()):
            result.append({
                "can_id": can_id,
                "can_id_hex": f"0x{can_id:X}",
                "name": msg.name,
                "length": msg.length,
                "signal_count": len(msg.signals),
                "signal_names": [s.name for s in msg.signals],
            })
        return result

    def get_signal_choices(self, can_id: int, signal_name: str) -> Optional[dict]:
        """Return the DBC value table (VAL_) for a signal, if defined.

        Keys are raw ints and values are plain strings, so the result is
        JSON-serializable; None is returned when the signal or message is
        unknown or the DBC declares no choices for it.
        """
        msg = self._id_to_msg.get(can_id)
        if not msg:
            return None
        for sig in msg.signals:
            if sig.name == signal_name:
                if sig.choices:
                    plain = {}
                    for k, v in sig.choices.items():
                        # NamedSignalValue.__str__ yields the label text
                        # (e.g. "Invalid"); its .value is the raw code.
                        try:
                            plain[int(k)] = str(v)
                        except (TypeError, ValueError):
                            plain[str(k)] = str(v)
                    return plain
                return None
        return None

    def find_message_by_signal(self, signal_name: str) -> Optional[tuple[int, str]]:
        """Locate (can_id, message_name) for a signal across all loaded DBCs.

        First-loaded DBC wins for conflicting IDs (same rule as __init__),
        so the result is deterministic for a given DBC set.
        """
        for can_id, msg in sorted(self._id_to_msg.items()):
            for sig in msg.signals:
                if sig.name == signal_name:
                    return can_id, msg.name
        return None
