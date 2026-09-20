import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from invoice_agent.schema import dumps, loads


def redact(value):
    """Defense in depth: remove API-key-like strings from persisted actions."""
    if isinstance(value, str):
        return re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    if isinstance(value, dict):
        return {str(redact(k)): redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Trace:
    def __init__(self, directory: Path):
        self.run_id = uuid4().hex
        self.directory = directory
        self.path = directory / "traces" / f"{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.actions_path = directory / "actions.json"
        self.sequence = 0

    def emit(self, actor: str, event: str, message: str, **data) -> dict:
        self.sequence += 1
        entry = redact({
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "event": event,
            "message": f"[agent] {message}" if actor == "agent" else message,
            "data": data,
        })
        # Serialize concurrent Streamlit sessions / CLI runs into the shared JSON array.
        with FileLock(str(self.actions_path) + ".lock", timeout=10):
            actions = loads(self.actions_path.read_text()) if self.actions_path.exists() else []
            if not isinstance(actions, list):
                raise ValueError("actions.json must contain a JSON array.")
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(dumps(entry) + "\n")
            actions.append(entry)
            temporary = self.actions_path.with_suffix(".json.tmp")
            temporary.write_text(dumps(actions, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.actions_path)
        return entry
