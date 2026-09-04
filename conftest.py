"""conftest at project root — ensures harness package is importable during pytest."""

import sys
from pathlib import Path

# Script-style verifier: run directly with
# `python tests/test_infrastructure_verification.py`.
collect_ignore = ["tests/test_infrastructure_verification.py"]

# Add project root to sys.path (handles pytest invoked from any directory)
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
