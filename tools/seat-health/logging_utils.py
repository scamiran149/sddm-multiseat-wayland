import json
import os
import time
from datetime import datetime, timezone


class SeatHealthLogger:
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        self.events_path = os.path.join(log_dir, "events.jsonl")
        self.summary_path = os.path.join(log_dir, "summary.log")
        os.makedirs(log_dir, exist_ok=True)

    def _ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def emit(self, record: dict) -> None:
        record["ts"] = self._ts()
        record["epoch"] = time.time()
        with open(self.events_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def summary(self, line: str) -> None:
        with open(self.summary_path, "a") as f:
            f.write(f"[{self._ts()}] {line}\n")

    def emit_trigger(
        self,
        severity: str,
        source: str,
        reason: str,
        seat: str = None,
        extra: dict = None,
    ) -> None:
        record = {
            "type": "trigger",
            "severity": severity,
            "source": source,
            "reason": reason,
            "seat": seat,
        }
        if extra:
            record.update(extra)
        self.emit(record)
        seat_tag = f" seat={seat}" if seat else ""
        self.summary(f"TRIGGER [{severity}] {source}: {reason}{seat_tag}")

    def emit_baseline(self, seats: list) -> None:
        self.emit({"type": "baseline", "seats": seats})
        self.summary(f"BASELINE {len(seats)} seats")

    def emit_snapshot(
        self,
        seat: str,
        sessions: list,
        probes: dict = None,
        trigger_reason: str = None,
        severity: str = None,
    ) -> None:
        record = {
            "type": "seat_snapshot",
            "seat": seat,
            "sessions": sessions,
            "primary_session_id": self._pick_primary(sessions),
            "trigger_reason": trigger_reason,
            "severity": severity,
        }
        if probes:
            record["probes"] = probes
        self.emit(record)
        n = len(sessions)
        stale = sum(1 for s in sessions if s.get("state") == "closing")
        primary = record["primary_session_id"] or "<none>"
        tag = f" trigger={trigger_reason}" if trigger_reason else ""
        self.summary(
            f"  SNAPSHOT {seat}: {n} sessions ({stale} stale) primary={primary}{tag}"
        )

    @staticmethod
    def _pick_primary(sessions: list) -> str | None:
        candidates = [
            s
            for s in sessions
            if s.get("state") not in ("closing",)
            and s.get("class") == "user"
            and s.get("leader_exists", False)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda s: s.get("id", 0), reverse=True)
        return str(candidates[0]["id"])

    def emit_probe(
        self, seat: str, session_id: str, probe_name: str, result: dict
    ) -> None:
        record = {
            "type": "probe_result",
            "seat": seat,
            "session_id": session_id,
            "probe": probe_name,
        }
        record.update(result)
        self.emit(record)
        status = "OK" if result.get("ok") else "FAIL"
        detail = result.get("detail", "")
        self.summary(f"    PROBE {seat}/{session_id} {probe_name}: {status} {detail}")

    def emit_burst(self, event: str, seat: str, detail: str = "") -> None:
        self.emit({"type": f"burst_{event}", "seat": seat, "detail": detail})
        self.summary(f"BURST {event} seat={seat} {detail}")

    def emit_info(self, msg: str) -> None:
        self.summary(f"INFO {msg}")

    def emit_logout_event(
        self,
        phase: str,
        seat: str = None,
        session_id: int = None,
        uid: int = None,
        user: str = None,
        extra: dict = None,
    ) -> None:
        record = {
            "type": "logout_event",
            "phase": phase,
            "seat": seat,
            "session_id": session_id,
            "uid": uid,
            "user": user,
        }
        if extra:
            record.update(extra)
        self.emit(record)
        bits = [f"phase={phase}"]
        if seat:
            bits.append(f"seat={seat}")
        if session_id is not None:
            bits.append(f"session={session_id}")
        if user:
            bits.append(f"user={user}")
        self.summary("LOGOUT " + " ".join(bits))
