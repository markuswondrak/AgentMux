from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def debug_log_ndjson(
    feature_dir: Path | None, *, message: str, data: dict[str, Any]
) -> None:
    """Best-effort debug log to <feature_dir>/debug.log when enabled.

    Controlled by env var AGENTMUX_DEBUG_LOG. Any non-empty value enables logging.
    """
    if not feature_dir:
        return
    if not os.environ.get("AGENTMUX_DEBUG_LOG", "").strip():
        return

    try:
        feature_dir = Path(feature_dir)
        feature_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp_ms": int(time.time() * 1000),
            "message": message,
            "data": data,
        }
        with (feature_dir / "debug.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return
