from .memory_system import MemorySystem
from .auto_dream import AutoDream

# M5 · semantic memory layer (optional). Guarded so a missing backend never
# breaks the base memory package import.
try:
    from .semantic_memory import SemanticMemory
except Exception:  # noqa: BLE001
    SemanticMemory = None  # type: ignore[assignment]
