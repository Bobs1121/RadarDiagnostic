# -*- coding: utf-8 -*-
"""P0 · pi RPC 冒烟（preflight）— 验证 pi --mode rpc 可用，能力可被调度。

对应 V4_PI_BASED_PLAN.md Slice P0 验收：``python scripts/pi_rpc_smoke.py``
报告 pi RPC 往返结果。脚本 fail-soft：pi 未安装 / provider 不可达时报明确
错误并返回非零，但绝不挂起（带超时）。

用法::

    python scripts/pi_rpc_smoke.py [--timeout 30]
    python scripts/pi_rpc_smoke.py --provider bosch-qwen3_6 --model Qwen3.5-27B-FP16
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

# Windows may launch this script with a legacy code page (for example
# cp1252).  The user-facing status is Chinese, so configure the stream before
# the first progress message; this keeps a console encoding issue from being
# mistaken for a Pi RPC/provider failure.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 让 `python scripts/pi_rpc_smoke.py` 可从项目根导入 ai.pi_bridge
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.pi_bridge import PiBridge, _find_pi


def _ping(timeout: int, *, provider: str = "", model: str = "") -> dict:
    """通过 PiBridge 发一个最小 prompt，等待 agent_settled 或超时。"""
    exe = _find_pi()
    if not exe or (shutil.which(exe) is None and "\\" not in exe):
        return {"status": "error", "message": f"pi 可执行不可用: {exe!r}"}

    del exe
    bridge = PiBridge(
        provider=provider,
        model=model,
        load_project_extension=False,
        allow_builtin_tools=False,
    )
    result = bridge.prompt("Reply with the single word PONG.", timeout=timeout)
    bridge.close()
    if result.get("status") == "ok":
        return {"status": "success", "evidence": "agent_settled", "raw": result}
    return {
        "status": result.get("status", "error"),
        "message": result.get("message", "pi RPC failed"),
        "last_line": json.dumps(result, ensure_ascii=False),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="pi RPC 冒烟 preflight")
    p.add_argument("--timeout", type=int, default=30, help="RPC 等待秒数")
    p.add_argument(
        "--provider",
        default="",
        help="可选的 Pi provider；不传则使用 CR60_PI_PROVIDER/本机探测",
    )
    p.add_argument(
        "--model",
        default="",
        help="可选的 Pi model；不传则使用 CR60_PI_MODEL/默认模型",
    )
    args = p.parse_args(argv)

    print(f"[{datetime.datetime.now():%H:%M:%S}] pi RPC 冒烟 ...")
    result = _ping(args.timeout, provider=args.provider, model=args.model)
    if result.get("status") == "success":
        print("[OK] pi RPC 往返成功")
        print("  证据:", result.get("evidence"))
        print("  raw: ", result.get("raw"))
        return 0
    print(f"[FAIL] pi RPC 冒烟未通过: {result.get('message', result.get('status'))}")
    if result.get("last_line"):
        print("  末行:", result["last_line"])
    return 1


if __name__ == "__main__":
    sys.exit(main())
