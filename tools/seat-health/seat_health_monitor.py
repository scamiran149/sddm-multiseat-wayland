#!/usr/bin/env python3

import argparse
import os
import signal
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logging_utils import SeatHealthLogger
from seat_inventory import (
    all_seats,
    enumerate_seat_sessions,
    pick_primary_session,
    session_details,
)
from seat_probes import (
    run_all_probes,
    run_compact_probes,
    probe_sddm_bus,
    probe_sddm_seat_object,
    probe_user_process_summary,
)
from journal_watch import iter_journal
from incident_manager import IncidentManager

DEFAULT_LOG_DIR = "/var/log/sddm-seat-health"
DEFAULT_BASELINE_INTERVAL = 60
DEFAULT_BURST_INTERVAL = 2
DEFAULT_BURST_DURATION = 60
DEFAULT_BURST_EXTENSION = 60


class SeatHealthMonitor:
    def __init__(
        self,
        log_dir: str,
        baseline_interval: int,
        burst_interval: int,
        burst_duration: int,
        burst_extension: int,
        dry_run: bool = False,
    ):
        self.log_dir = log_dir
        self.dry_run = dry_run
        self.logger = SeatHealthLogger(log_dir)
        self.incident = IncidentManager(
            self.logger,
            baseline_interval=baseline_interval,
            burst_interval=burst_interval,
            burst_duration=burst_duration,
            burst_extension=burst_extension,
        )
        self.baseline_interval = baseline_interval
        self.burst_interval = burst_interval
        self.running = True
        self._journal_events = []
        self._journal_lock = threading.Lock()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        self.logger.emit_info(f"received signal {signum}, shutting down")
        self.running = False

    def _compact_snapshot(
        self, seat_name: str, reason: str = None, severity: str = None
    ) -> dict:
        sessions = enumerate_seat_sessions(seat_name)
        primary = pick_primary_session(sessions)
        probes = {}
        if primary:
            probes = run_compact_probes(primary, seat_name)
        self.logger.emit_snapshot(
            seat_name, sessions, probes, trigger_reason=reason, severity=severity
        )
        return {
            "seat": seat_name,
            "sessions": sessions,
            "primary": primary,
            "probes": probes,
        }

    def _deep_snapshot(
        self, seat_name: str, reason: str = None, severity: str = None
    ) -> dict:
        sessions = enumerate_seat_sessions(seat_name)
        primary = pick_primary_session(sessions)
        probes = {
            "sddm_bus": probe_sddm_bus(),
            "sddm_seat_object": probe_sddm_seat_object(seat_name),
        }
        if primary:
            all_probes = run_all_probes(primary, seat_name, logger=self.logger)
            probes.update(all_probes)
        self.logger.emit_snapshot(
            seat_name, sessions, probes, trigger_reason=reason, severity=severity
        )
        return {
            "seat": seat_name,
            "sessions": sessions,
            "primary": primary,
            "probes": probes,
        }

    def _session_for_event(
        self, event, seat_name: str, sessions: list[dict]
    ) -> dict | None:
        if event.session_id is not None:
            for session in sessions:
                if session.get("id") == event.session_id:
                    return session
            detail = session_details(event.session_id)
            if detail and not detail.get("raw_error"):
                if detail.get("seat") == seat_name or detail.get("seat") is None:
                    return detail
        for session in sessions:
            if event.username and session.get("name") == event.username:
                return session
        primary = pick_primary_session(sessions)
        if primary:
            return primary
        user_sessions = [s for s in sessions if s.get("class") == "user"]
        if not user_sessions:
            return None
        user_sessions.sort(key=lambda s: s.get("id", 0), reverse=True)
        return user_sessions[0]

    def _capture_lifecycle_event(self, event) -> None:
        detail = (
            session_details(event.session_id) if event.session_id is not None else {}
        )
        seat_name = detail.get("seat") or event.seat_hint
        if not seat_name:
            return
        sessions = enumerate_seat_sessions(seat_name)
        target = self._session_for_event(event, seat_name, sessions)
        uid = None
        username = event.username
        if target:
            uid = target.get("user") or target.get("uid")
            username = target.get("name") or username or target.get("user")
        self.logger.emit_logout_event(
            event.event_type,
            seat=seat_name,
            session_id=event.session_id,
            uid=uid,
            user=username,
            extra={
                "source": event.source,
                "message": event.message[:300],
                "pid": event.pid,
            },
        )
        probes = {}
        if uid:
            probes["user_process_summary"] = probe_user_process_summary(uid, username)
        self.logger.emit_snapshot(
            seat_name,
            sessions,
            probes,
            trigger_reason=event.event_type,
            severity=event.severity,
        )

    def run_baseline(self, now: float) -> None:
        seats = all_seats()
        all_snapshots = []
        for seat_name in seats:
            sessions = enumerate_seat_sessions(seat_name)
            suspicious = self.incident.check_suspicious_state(seat_name, sessions, now)
            severe = self.incident.check_severe_state(seat_name, sessions, now)
            for trig in suspicious:
                self.incident.start_burst(seat_name, trig, "suspicious", now)
                self.logger.emit_trigger(
                    "suspicious", "seat_inventory", trig, seat=seat_name
                )
            for trig in severe:
                self.incident.start_burst(seat_name, trig, "severe", now)
                self.logger.emit_trigger(
                    "severe", "seat_inventory", trig, seat=seat_name
                )
            all_snapshots.append({"seat": seat_name, "sessions": sessions})
        self.logger.emit_baseline(all_snapshots)
        self.incident.record_baseline(now)

    def _process_journal_events(self) -> None:
        with self._journal_lock:
            events = list(self._journal_events)
            self._journal_events.clear()
        now = time.time()
        for event in events:
            self.logger.emit_trigger(
                event.severity,
                event.source,
                event.event_type,
                seat=event.seat_hint,
                extra={
                    "pid": event.pid,
                    "session_id": event.session_id,
                    "username": event.username,
                },
            )
            if event.event_type in (
                "logout_waiting_for_processes",
                "session_removed",
                "new_session_opened",
            ):
                self._capture_lifecycle_event(event)
            actions = self.incident.handle_journal_event(event, now)
            for seat_name, sev, etype in actions:
                if seat_name == "__all__":
                    for s in all_seats():
                        if sev == "info":
                            self._compact_snapshot(s, reason=etype, severity=sev)
                        else:
                            self.incident.start_burst(s, etype, sev, now)
                            self._deep_snapshot(s, reason=etype, severity=sev)
                else:
                    if sev == "info":
                        self._compact_snapshot(seat_name, reason=etype, severity=sev)
                    else:
                        self.incident.start_burst(seat_name, etype, sev, now)
                        self._deep_snapshot(seat_name, reason=etype, severity=sev)

    def _journal_thread(self) -> None:
        try:
            for event in iter_journal(follow=True):
                if not self.running:
                    break
                with self._journal_lock:
                    self._journal_events.append(event)
        except Exception as e:
            if self.running:
                self.logger.emit_info(f"journal thread error: {e}")

    def run(self) -> None:
        self.logger.emit_info("seat-health-monitor starting")
        now = time.time()
        self.run_baseline(now)
        last_baseline = now

        if not self.dry_run:
            jthread = threading.Thread(target=self._journal_thread, daemon=True)
            jthread.start()
        else:
            self.logger.emit_info("dry-run mode: journal watch disabled, baseline-only")

        try:
            while self.running:
                now = time.time()

                if now - last_baseline >= self.baseline_interval:
                    self.run_baseline(now)
                    last_baseline = now

                self._process_journal_events()

                for seat_name in list(self.incident.seats.keys()):
                    if self.incident.should_burst_snapshot(
                        seat_name, now
                    ) and self.incident.should_sample_burst(seat_name, now):
                        self._deep_snapshot(seat_name, reason="burst", severity="burst")
                        self.incident.record_burst_snapshot(seat_name, now)

                if self.dry_run:
                    time.sleep(self.baseline_interval)
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.logger.emit_info("seat-health-monitor stopping")


def main():
    parser = argparse.ArgumentParser(description="SDDM Seat Health Monitor")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help="Log directory")
    parser.add_argument(
        "--baseline-interval",
        type=int,
        default=DEFAULT_BASELINE_INTERVAL,
        help="Baseline snapshot interval in seconds",
    )
    parser.add_argument(
        "--burst-interval",
        type=int,
        default=DEFAULT_BURST_INTERVAL,
        help="Burst snapshot interval in seconds",
    )
    parser.add_argument(
        "--burst-duration",
        type=int,
        default=DEFAULT_BURST_DURATION,
        help="Burst duration in seconds",
    )
    parser.add_argument(
        "--burst-extension",
        type=int,
        default=DEFAULT_BURST_EXTENSION,
        help="Burst extension on repeated triggers in seconds",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Baseline-only mode, no journal watch"
    )
    args = parser.parse_args()

    monitor = SeatHealthMonitor(
        log_dir=args.log_dir,
        baseline_interval=args.baseline_interval,
        burst_interval=args.burst_interval,
        burst_duration=args.burst_duration,
        burst_extension=args.burst_extension,
        dry_run=args.dry_run,
    )
    monitor.run()


if __name__ == "__main__":
    main()
