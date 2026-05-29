"""Audit logger for coding-agent permission decisions and command execution."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AuditEntry:
    """A single auditable event."""

    timestamp: str
    event: str
    operation: str
    target: str
    decision: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "operation": self.operation,
            "target": self.target,
            "decision": self.decision,
            "reason": self.reason,
            "metadata": self.metadata,
        }


class AuditLogger:
    """Records permission decisions and command executions for audit trails."""

    def __init__(self, log_path: str | Path | None = None) -> None:
        self._log_path = Path(log_path) if log_path else None
        self._entries: list[AuditEntry] = []

    def record(
        self,
        event: str,
        operation: str,
        target: str,
        decision: str,
        reason: str,
        **metadata: Any,
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            event=event,
            operation=operation,
            target=target,
            decision=decision,
            reason=reason,
            metadata=metadata,
        )
        self._entries.append(entry)
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[AuditEntry]:
        """Return a copy of all entries."""
        return list(self._entries)

    def recent(self, count: int = 20) -> list[AuditEntry]:
        """Return the most recent entries."""
        return self._entries[-count:] if self._entries else []

    def flush(self) -> None:
        """No-op for in-memory; file writes are immediate."""

    def summary(self) -> dict[str, object]:
        allowed = sum(1 for e in self._entries if e.decision == "allow")
        asked = sum(1 for e in self._entries if e.decision == "ask")
        denied = sum(1 for e in self._entries if e.decision == "deny")
        return {
            "total_entries": len(self._entries),
            "allowed": allowed,
            "asked": asked,
            "denied": denied,
        }
