"""
RebalanceKeeper — Audit trail logger.

Records every monitor check and rebalance trigger with full context:
  timestamp → trigger → decision → execution → tx hash → gas → result

Output: JSONL file (one JSON object per line) + human-readable summary.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class AuditLogger:
    """Append-only audit log in JSONL format."""

    def __init__(self, log_path: str = "logs/audit.jsonl"):
        self.log_path = log_path
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    def log(
        self,
        event_type: str,
        trigger: str,
        decision: str,
        execution: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Write a single audit entry. Returns the entry dict."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,        # "monitor" | "trigger" | "execution" | "error"
            "trigger": trigger,              # e.g. "health_factor=1.42 < 1.50"
            "decision": decision,            # e.g. "repay 15% of USDC debt"
            "execution": execution or {},    # {tx_hash, gas_used, status, explorer_link}
            "error": error,
            "extra": extra or {},
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def log_monitor(self, health_factor: str, collateral: str, debt: str):
        """Log a routine monitor check (no action taken)."""
        return self.log(
            event_type="monitor",
            trigger=f"health_factor={health_factor}",
            decision="no_action",
            extra={
                "total_collateral_base": collateral,
                "total_debt_base": debt,
            },
        )

    def log_trigger(
        self,
        health_factor: str,
        action: str,
        params: Dict[str, Any],
        tx_hash: Optional[str] = None,
        gas_used: Optional[str] = None,
        status: str = "success",
        error: Optional[str] = None,
        explorer_link: Optional[str] = None,
    ):
        """Log a rebalance trigger with execution details."""
        return self.log(
            event_type="trigger",
            trigger=f"health_factor={health_factor}",
            decision=action,
            execution={
                "tx_hash": tx_hash,
                "gas_used": gas_used,
                "status": status,
                "explorer_link": explorer_link,
                "params": params,
            },
            error=error,
        )

    def read_all(self) -> List[Dict[str, Any]]:
        """Read all entries from the log file."""
        if not os.path.exists(self.log_path):
            return []
        entries = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def summary(self) -> str:
        """Human-readable summary of the audit log."""
        entries = self.read_all()
        if not entries:
            return "No audit entries yet."

        monitors = [e for e in entries if e["event_type"] == "monitor"]
        triggers = [e for e in entries if e["event_type"] == "trigger"]
        errors = [e for e in entries if e.get("error")]

        lines = [
            f"Audit Summary ({len(entries)} entries)",
            f"  Monitor checks: {len(monitors)}",
            f"  Rebalance triggers: {len(triggers)}",
            f"  Errors: {len(errors)}",
            "",
        ]

        if triggers:
            lines.append("Recent triggers:")
            for t in triggers[-10:]:
                tx = t["execution"].get("tx_hash", "N/A")
                status = t["execution"].get("status", "?")
                lines.append(f"  [{t['timestamp']}] {t['decision']} → {status} (tx: {tx})")

        return "\n".join(lines)
