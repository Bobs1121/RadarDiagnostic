#!/usr/bin/env python
"""
Direct test of orchestrator.run_diagnosis — bypasses CLI dream step.
Validates the 8-step pipeline refactoring.
"""
import sys, os, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

from cli import load_config
from config import get_project
from ai.orchestrator import Orchestrator

# Load config
config = load_config()
project = get_project(config)

case_dir = PROJECT_ROOT / "cases" / "FCTA001"

print(f"Project: {project.get('display_name', 'unknown')}")
print(f"Case dir: {case_dir}")
print(f"Case exists: {case_dir.exists()}")

# List case files
for f in sorted(case_dir.iterdir()):
    print(f"  {f.name} ({f.stat().st_size} bytes)")

# Check baseline report
baseline = case_dir / "report.md"
baseline_size = baseline.stat().st_size if baseline.exists() else 0
print(f"\nBaseline report: {baseline_size} bytes")

# Track steps
steps_log = []
def on_status(step, detail=""):
    steps_log.append(step)
    print(f"  [STEP] {step}: {detail}")

# Create orchestrator directly
orch = Orchestrator(config, PROJECT_ROOT)

print(f"\nStarting diagnosis at {time.strftime('%H:%M:%S')}...")
start = time.time()

try:
    report_path = orch.run_diagnosis(
        case_dir=str(case_dir),
        problem="FCTA功能在60km/h速度下没有触发",
        expected="FCTA应该在车辆后方有接近目标时触发告警",
        on_status=on_status,
    )
    elapsed = time.time() - start
    
    print(f"\n{'='*60}")
    print(f"Completed in {elapsed:.1f}s")
    print(f"Steps recorded: {len(steps_log)}")
    for i, s in enumerate(steps_log, 1):
        print(f"  {i}. {s}")
    print(f"\nReport path: {report_path}")
    
    # Check report
    if report_path and Path(report_path).exists():
        report_size = Path(report_path).stat().st_size
        print(f"Report size: {report_size} bytes")
        print(f"Baseline was: {baseline_size} bytes")
        print(f"Size delta: {report_size - baseline_size:+,d}")
    print(f"{'='*60}")

except Exception as e:
    import traceback
    elapsed = time.time() - start
    print(f"\nFAILED after {elapsed:.1f}s:")
    print(f"Error: {e}")
    traceback.print_exc()
    sys.exit(1)
