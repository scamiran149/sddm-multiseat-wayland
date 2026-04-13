import time
from collections import defaultdict

DEFAULT_BASELINE_INTERVAL = 60
DEFAULT_BURST_INTERVAL = 2
DEFAULT_BURST_DURATION = 60
DEFAULT_BURST_EXTENSION = 60
STALE_CLOSING_THRESHOLD = 2


class SeatState:
    def __init__(self, name: str):
        self.name = name
        self.in_burst = False
        self.burst_end = 0.0
        self.burst_count = 0
        self.last_burst_snapshot = 0.0
        self.last_baseline = 0.0
        self.stale_closing_count = 0
        self.last_trigger = None
        self.last_primary_id = None


class IncidentManager:
    def __init__(
        self,
        logger,
        baseline_interval=DEFAULT_BASELINE_INTERVAL,
        burst_interval=DEFAULT_BURST_INTERVAL,
        burst_duration=DEFAULT_BURST_DURATION,
        burst_extension=DEFAULT_BURST_EXTENSION,
        stale_closing_threshold=STALE_CLOSING_THRESHOLD,
    ):
        self.logger = logger
        self.baseline_interval = baseline_interval
        self.burst_interval = burst_interval
        self.burst_duration = burst_duration
        self.burst_extension = burst_extension
        self.stale_closing_threshold = stale_closing_threshold
        self.seats: dict[str, SeatState] = defaultdict(lambda: SeatState("__unknown__"))
        self._global_last_baseline = -baseline_interval

    def _seat(self, name: str) -> SeatState:
        if name not in self.seats:
            self.seats[name] = SeatState(name)
        return self.seats[name]

    def should_run_baseline(self, now: float) -> bool:
        return (now - self._global_last_baseline) >= self.baseline_interval

    def record_baseline(self, now: float) -> None:
        self._global_last_baseline = now

    def start_burst(self, seat: str, reason: str, severity: str, now: float) -> None:
        s = self._seat(seat)
        s.in_burst = True
        extension = self.burst_extension if s.burst_count > 0 else self.burst_duration
        s.burst_end = max(s.burst_end, now + extension)
        s.burst_count += 1
        s.last_trigger = reason
        self.logger.emit_burst(
            "start" if s.burst_count == 1 else "extend", seat, f"{severity}/{reason}"
        )

    def should_burst_snapshot(self, seat: str, now: float) -> bool:
        s = self._seat(seat)
        if not s.in_burst:
            return False
        if now >= s.burst_end:
            s.in_burst = False
            self.logger.emit_burst("end", seat, f"count={s.burst_count}")
            s.burst_count = 0
            return False
        return True

    def should_sample_burst(self, seat: str, now: float) -> bool:
        s = self._seat(seat)
        return (now - s.last_burst_snapshot) >= self.burst_interval

    def record_burst_snapshot(self, seat: str, now: float) -> None:
        self._seat(seat).last_burst_snapshot = now

    def check_suspicious_state(
        self, seat: str, sessions: list[dict], now: float
    ) -> list[str]:
        triggers = []
        s = self._seat(seat)

        user_sessions = [sess for sess in sessions if sess.get("class") == "user"]
        if len(user_sessions) > 1:
            triggers.append("multiple_user_sessions")

        stale = [sess for sess in sessions if sess.get("state") == "closing"]
        if stale:
            s.stale_closing_count += 1
            if s.stale_closing_count >= self.stale_closing_threshold:
                triggers.append("stale_closing_sessions")
        else:
            s.stale_closing_count = 0

        primary = None
        for sess in sorted(sessions, key=lambda x: x.get("id", 0), reverse=True):
            if sess.get("class") == "user" and sess.get("state") != "closing":
                primary = sess
                break
        if primary:
            if not primary.get("leader_exists", False):
                triggers.append("primary_leader_missing")
            s.last_primary_id = primary.get("id")
        else:
            if user_sessions:
                triggers.append("no_primary_session")
            s.last_primary_id = None

        return triggers

    def check_severe_state(
        self, seat: str, sessions: list[dict], now: float
    ) -> list[str]:
        triggers = []
        has_user = any(
            s.get("class") == "user" and s.get("state") != "closing" for s in sessions
        )
        has_greeter = any(s.get("class") == "greeter" for s in sessions)
        if not has_user and not has_greeter:
            triggers.append("seat_empty_no_greeter")
        return triggers

    def handle_journal_event(self, event, now: float) -> list[tuple[str, str, str]]:
        actions = []
        severity = event.severity
        etype = event.event_type
        seat = event.seat_hint or "__unknown__"

        if severity in ("suspicious", "severe"):
            if seat != "__unknown__":
                self.start_burst(seat, etype, severity, now)
                actions.append((seat, severity, etype))
            else:
                for seat_name in self.seats:
                    if seat_name != "__unknown__":
                        self.start_burst(seat_name, etype, severity, now)
                        actions.append((seat_name, severity, etype))
            if seat == "__unknown__" and not any(
                n != "__unknown__" for n in self.seats
            ):
                actions.append(("__all__", severity, etype))

        elif severity == "info":
            etype_lower = etype.lower()
            if any(
                kw in etype_lower
                for kw in (
                    "login_success",
                    "session_started",
                    "greeter_started",
                    "greeter_stopped",
                    "display_added",
                    "display_removed",
                )
            ):
                if seat != "__unknown__":
                    actions.append((seat, "info", etype))
                else:
                    for seat_name in self.seats:
                        if seat_name != "__unknown__":
                            actions.append((seat_name, "info", etype))
        return actions
