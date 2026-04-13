import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from logging_utils import SeatHealthLogger
from seat_inventory import (
    pick_primary_session,
    stale_sessions,
    user_sessions_on_seat,
    find_kwin_for_session,
)
from journal_watch import classify_journal_line, JournalEvent
from incident_manager import IncidentManager, SeatState
from seat_health_monitor import SeatHealthMonitor
from seat_probes import probe_user_process_summary
from unittest.mock import patch, MagicMock


class TestPickPrimarySession(unittest.TestCase):
    def test_single_healthy_session(self):
        sessions = [
            {
                "id": 10,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "online",
                "leader_exists": True,
            }
        ]
        result = pick_primary_session(sessions)
        self.assertEqual(result["id"], 10)

    def test_skip_closing_session(self):
        sessions = [
            {
                "id": 5,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "closing",
                "leader_exists": False,
            },
            {
                "id": 10,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "online",
                "leader_exists": True,
            },
        ]
        result = pick_primary_session(sessions)
        self.assertEqual(result["id"], 10)

    def test_newest_wins(self):
        sessions = [
            {
                "id": 10,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "online",
                "leader_exists": True,
            },
            {
                "id": 20,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "online",
                "leader_exists": True,
            },
        ]
        result = pick_primary_session(sessions)
        self.assertEqual(result["id"], 20)

    def test_all_closing_returns_none(self):
        sessions = [
            {
                "id": 10,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "closing",
                "leader_exists": False,
            },
        ]
        result = pick_primary_session(sessions)
        self.assertIsNone(result)

    def test_greeter_session_skipped(self):
        sessions = [
            {
                "id": 5,
                "uid": 112,
                "user": "sddm",
                "seat": "seat1",
                "class": "greeter",
                "state": "online",
                "leader_exists": True,
            },
            {
                "id": 10,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "online",
                "leader_exists": True,
            },
        ]
        result = pick_primary_session(sessions)
        self.assertEqual(result["id"], 10)

    def test_no_leader_fallback(self):
        sessions = [
            {
                "id": 10,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "online",
                "leader_exists": False,
            },
        ]
        result = pick_primary_session(sessions)
        self.assertEqual(result["id"], 10)

    def test_empty_list(self):
        result = pick_primary_session([])
        self.assertIsNone(result)

    def test_multiple_stale_plus_one_live(self):
        sessions = [
            {
                "id": 4,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "closing",
                "leader_exists": False,
            },
            {
                "id": 5,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "closing",
                "leader_exists": False,
            },
            {
                "id": 6,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "closing",
                "leader_exists": False,
            },
            {
                "id": 20,
                "uid": 1002,
                "user": "samiran",
                "seat": "seat0",
                "class": "user",
                "state": "online",
                "leader_exists": True,
            },
        ]
        result = pick_primary_session(sessions)
        self.assertEqual(result["id"], 20)


class TestStaleSessions(unittest.TestCase):
    def test_stale_detected(self):
        sessions = [
            {"id": 4, "state": "closing"},
            {"id": 5, "state": "online"},
        ]
        stale = stale_sessions(sessions)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["id"], 4)

    def test_no_stale(self):
        sessions = [{"id": 5, "state": "online"}]
        self.assertEqual(len(stale_sessions(sessions)), 0)


class TestUserSessionsOnSeat(unittest.TestCase):
    def test_filters_greeter(self):
        sessions = [
            {"id": 5, "class": "greeter"},
            {"id": 10, "class": "user"},
        ]
        result = user_sessions_on_seat(sessions)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 10)


class TestJournalClassify(unittest.TestCase):
    def test_login_success(self):
        event = classify_journal_line(
            'Authentication for user  "samiran"  successful', unit="sddm"
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "info")
        self.assertEqual(event.event_type, "login_success")

    def test_helper_crash(self):
        event = classify_journal_line("Auth: sddm-helper exited with 1", unit="sddm")
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "suspicious")
        self.assertEqual(event.event_type, "helper_exited_error")

    def test_helper_success_not_suspicious(self):
        event = classify_journal_line(
            "Auth: sddm-helper exited successfully", unit="sddm"
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "info")

    def test_gpu_fault(self):
        event = classify_journal_line(
            "amdgpu 0000:07:00.0: amdgpu: GPU fault detected: 147 0x00024402",
            unit="kernel",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "severe")
        self.assertEqual(event.event_type, "gpu_fault")

    def test_ring_gfx_timeout(self):
        event = classify_journal_line(
            "amdgpu 0000:07:00.0: amdgpu: ring gfx timeout, signaled seq=1735020, emitted seq=1735023",
            unit="kernel",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "severe")
        self.assertEqual(event.event_type, "ring_gfx_timeout")

    def test_vram_lost(self):
        event = classify_journal_line(
            "amdgpu 0000:07:00.0: amdgpu: VRAM is lost due to GPU reset!", unit="kernel"
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "severe")
        self.assertEqual(event.event_type, "vram_lost")

    def test_kwin_in_gpu_event(self):
        event = classify_journal_line(
            "amdgpu 0000:07:00.0: amdgpu:  Process kwin_wayland pid 14790 thread kwin_wayla:cs0 pid 14896",
            unit="kernel",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "severe")
        self.assertEqual(event.event_type, "kwin_in_gpu_event")

    def test_process_crashed(self):
        event = classify_journal_line(
            'Authentication error: SDDM::Auth::ERROR_INTERNAL "Process crashed"',
            unit="sddm",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "suspicious")
        self.assertEqual(event.event_type, "process_crashed")

    def test_process_crashed_sddm_format(self):
        event = classify_journal_line(
            "Auth: sddm-helper (--socket ...) crashed (exit code 1)", unit="sddm"
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "suspicious")
        self.assertEqual(event.event_type, "process_crashed")

    def test_unrelated_line(self):
        event = classify_journal_line("some random log line", unit="sddm")
        self.assertIsNone(event)

    def test_pcie_aer_uncorrectable(self):
        event = classify_journal_line(
            "pcieport 0000:40:03.1: AER: Multiple Uncorrectable (Non-Fatal) error message received",
            unit="kernel",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "severe")
        self.assertEqual(event.event_type, "pcie_aer_uncorrectable")

    def test_device_wedged(self):
        event = classify_journal_line(
            "amdgpu 0000:07:00.0: [drm] device wedged, but recovered through reset",
            unit="kernel",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "severe")

    def test_amdgpu_parser_failure(self):
        event = classify_journal_line(
            "[drm:amdgpu_cs_ioctl [amdgpu]] *ERROR* Failed to initialize parser -125!",
            unit="kernel",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "severe")
        self.assertEqual(event.event_type, "amdgpu_parser_failure")

    def test_auth_error(self):
        event = classify_journal_line(
            'Authentication error: SDDM::Auth::ERROR_AUTHENTICATION "Authentication failure"',
            unit="sddm",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "suspicious")

    def test_session_closed(self):
        event = classify_journal_line(
            "pam_unix(sddm:session): session closed for user samiran", unit="sddm"
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "suspicious")
        self.assertEqual(event.event_type, "session_closed")

    def test_logind_logout_waiting(self):
        event = classify_journal_line(
            "Session 278 logged out. Waiting for processes to exit.",
            syslog_identifier="systemd-logind",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.severity, "info")
        self.assertEqual(event.event_type, "logout_waiting_for_processes")
        self.assertEqual(event.session_id, 278)

    def test_logind_new_session(self):
        event = classify_journal_line(
            "New session 278 of user samiran.",
            syslog_identifier="systemd-logind",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "new_session_opened")
        self.assertEqual(event.session_id, 278)
        self.assertEqual(event.username, "samiran")


class TestIncidentManager(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = tempfile.mkdtemp()
        self.logger = SeatHealthLogger(self.tmpdir)
        self.incident = IncidentManager(
            self.logger, baseline_interval=60, burst_duration=60, burst_extension=60
        )

    def test_should_run_baseline_initially(self):
        self.assertTrue(self.incident.should_run_baseline(0))
        self.assertTrue(self.incident.should_run_baseline(1))

    def test_should_not_run_baseline_within_interval(self):
        self.incident.record_baseline(100)
        self.assertFalse(self.incident.should_run_baseline(150))
        self.assertTrue(self.incident.should_run_baseline(161))

    def test_burst_start_and_end(self):
        now = 1000.0
        self.incident.start_burst("seat0", "test_trigger", "suspicious", now)
        self.assertTrue(self.incident.should_burst_snapshot("seat0", now + 1))
        self.assertFalse(self.incident.should_burst_snapshot("seat0", now + 61))

    def test_burst_extend(self):
        now = 1000.0
        self.incident.start_burst("seat0", "trigger1", "suspicious", now)
        self.assertTrue(self.incident.should_burst_snapshot("seat0", now + 1))
        self.incident.start_burst("seat0", "trigger2", "severe", now + 30)
        self.assertTrue(self.incident.should_burst_snapshot("seat0", now + 50))
        self.assertFalse(self.incident.should_burst_snapshot("seat0", now + 91))

    def test_check_multiple_user_sessions(self):
        sessions = [
            {"id": 10, "class": "user", "state": "online", "leader_exists": True},
            {"id": 20, "class": "user", "state": "online", "leader_exists": True},
        ]
        triggers = self.incident.check_suspicious_state("seat0", sessions, 100.0)
        self.assertIn("multiple_user_sessions", triggers)

    def test_check_stale_closing(self):
        sessions = [
            {"id": 10, "class": "user", "state": "closing", "leader_exists": False},
        ]
        for i in range(3):
            t = self.incident.check_suspicious_state("seat0", sessions, 100.0 + i * 60)
        self.assertIn("stale_closing_sessions", t)

    def test_check_primary_leader_missing(self):
        sessions = [
            {"id": 10, "class": "user", "state": "online", "leader_exists": False},
        ]
        triggers = self.incident.check_suspicious_state("seat0", sessions, 100.0)
        self.assertIn("primary_leader_missing", triggers)

    def test_empty_seat_triggers_severe(self):
        triggers = self.incident.check_severe_state("seat0", [], 100.0)
        self.assertIn("seat_empty_no_greeter", triggers)

    def test_info_event_targets_only_hint_seat(self):
        self.incident._seat("seat0")
        self.incident._seat("seat2")
        event = JournalEvent("info", "login_success", "msg", "sddm", seat_hint="seat2")

        actions = self.incident.handle_journal_event(event, 100.0)

        self.assertEqual(actions, [("seat2", "info", "login_success")])
        self.assertFalse(self.incident._seat("seat2").in_burst)

    def test_severe_event_targets_only_hint_seat(self):
        self.incident._seat("seat0")
        self.incident._seat("seat2")
        event = JournalEvent("severe", "gpu_fault", "msg", "kernel", seat_hint="seat2")

        actions = self.incident.handle_journal_event(event, 100.0)

        self.assertEqual(actions, [("seat2", "severe", "gpu_fault")])
        self.assertTrue(self.incident._seat("seat2").in_burst)
        self.assertFalse(self.incident._seat("seat0").in_burst)

    def test_burst_interval_is_enforced(self):
        self.incident.start_burst("seat0", "test", "suspicious", 100.0)

        self.assertTrue(self.incident.should_sample_burst("seat0", 102.0))
        self.incident.record_burst_snapshot("seat0", 102.0)
        self.assertFalse(self.incident.should_sample_burst("seat0", 103.0))
        self.assertTrue(self.incident.should_sample_burst("seat0", 104.0))


class TestSeatHealthMonitor(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = tempfile.mkdtemp()

    def test_info_event_uses_compact_snapshot_only(self):
        monitor = SeatHealthMonitor(self.tmpdir, 60, 2, 60, 60, dry_run=True)
        monitor._journal_events = [
            JournalEvent("info", "login_success", "msg", "sddm", seat_hint="seat2")
        ]

        with (
            patch.object(monitor, "_compact_snapshot") as compact,
            patch.object(monitor, "_deep_snapshot") as deep,
        ):
            monitor._process_journal_events()

        compact.assert_called_once_with(
            "seat2", reason="login_success", severity="info"
        )
        deep.assert_not_called()

    def test_severe_event_uses_deep_snapshot(self):
        monitor = SeatHealthMonitor(self.tmpdir, 60, 2, 60, 60, dry_run=True)
        monitor._journal_events = [
            JournalEvent("severe", "gpu_fault", "msg", "kernel", seat_hint="seat2")
        ]

        with (
            patch.object(monitor, "_compact_snapshot") as compact,
            patch.object(monitor, "_deep_snapshot") as deep,
        ):
            monitor._process_journal_events()

        deep.assert_called_once_with("seat2", reason="gpu_fault", severity="severe")
        compact.assert_not_called()

    @patch("seat_health_monitor.probe_user_process_summary")
    @patch("seat_health_monitor.enumerate_seat_sessions")
    @patch("seat_health_monitor.session_details")
    def test_logout_lifecycle_event_logs_snapshot(
        self, mock_session_details, mock_enumerate, mock_process_summary
    ):
        monitor = SeatHealthMonitor(self.tmpdir, 60, 2, 60, 60, dry_run=True)
        mock_session_details.return_value = {
            "id": 232,
            "seat": "seat0",
            "user": 1002,
            "name": "samiran",
            "class": "user",
            "state": "closing",
            "leader_exists": False,
        }
        mock_enumerate.return_value = [mock_session_details.return_value]
        mock_process_summary.return_value = {"ok": True, "core_processes": []}
        event = JournalEvent(
            "info",
            "logout_waiting_for_processes",
            "msg",
            "systemd-logind",
            session_id=232,
        )

        with (
            patch.object(monitor.logger, "emit_logout_event") as emit_logout,
            patch.object(monitor.logger, "emit_snapshot") as emit_snapshot,
        ):
            monitor._capture_lifecycle_event(event)

        emit_logout.assert_called_once()
        emit_snapshot.assert_called_once()

    @patch("seat_health_monitor.probe_user_process_summary")
    @patch("seat_health_monitor.enumerate_seat_sessions")
    @patch("seat_health_monitor.session_details")
    def test_new_session_lifecycle_event_prefers_matching_user(
        self, mock_session_details, mock_enumerate, mock_process_summary
    ):
        monitor = SeatHealthMonitor(self.tmpdir, 60, 2, 60, 60, dry_run=True)
        mock_session_details.return_value = {"id": 278, "seat": "seat0"}
        mock_enumerate.return_value = [
            {"id": 232, "name": "other", "user": 1001, "class": "user"},
            {"id": 278, "name": "samiran", "user": 1002, "class": "user"},
        ]
        mock_process_summary.return_value = {"ok": True, "core_processes": []}
        event = JournalEvent(
            "info",
            "new_session_opened",
            "msg",
            "systemd-logind",
            session_id=278,
            username="samiran",
        )

        with patch.object(monitor.logger, "emit_snapshot") as emit_snapshot:
            monitor._capture_lifecycle_event(event)

        probes = emit_snapshot.call_args.args[2]
        self.assertEqual(probes["user_process_summary"]["ok"], True)


class TestLoggingUtils(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = tempfile.mkdtemp()
        self.logger = SeatHealthLogger(self.tmpdir)

    def test_emit_creates_jsonl(self):
        self.logger.emit({"type": "test", "value": 42})
        with open(os.path.join(self.tmpdir, "events.jsonl")) as f:
            lines = f.readlines()
        self.assertEqual(len(lines), 1)
        import json

        record = json.loads(lines[0])
        self.assertEqual(record["type"], "test")
        self.assertEqual(record["value"], 42)
        self.assertIn("ts", record)
        self.assertIn("epoch", record)

    def test_summary_creates_log(self):
        self.logger.summary("test line")
        with open(os.path.join(self.tmpdir, "summary.log")) as f:
            content = f.read()
        self.assertIn("test line", content)

    def test_emit_trigger(self):
        self.logger.emit_trigger("suspicious", "sddm", "helper crash", seat="seat2")
        with open(os.path.join(self.tmpdir, "events.jsonl")) as f:
            import json

            record = json.loads(f.readline())
        self.assertEqual(record["type"], "trigger")
        self.assertEqual(record["severity"], "suspicious")
        self.assertEqual(record["seat"], "seat2")

    def test_pick_primary_in_snapshot(self):
        sessions = [
            {"id": 4, "state": "closing", "class": "user", "leader_exists": False},
            {"id": 10, "state": "online", "class": "user", "leader_exists": True},
        ]
        self.logger.emit_snapshot("seat0", sessions)
        with open(os.path.join(self.tmpdir, "events.jsonl")) as f:
            import json

            record = json.loads(f.readline())
        self.assertEqual(record["primary_session_id"], "10")

        self.assertEqual(record["primary_session_id"], "10")

    def test_emit_logout_event(self):
        self.logger.emit_logout_event(
            "logout_waiting_for_processes",
            seat="seat0",
            session_id=232,
            uid=1002,
            user="samiran",
        )
        with open(os.path.join(self.tmpdir, "events.jsonl")) as f:
            import json

            record = json.loads(f.readline())
        self.assertEqual(record["type"], "logout_event")
        self.assertEqual(record["phase"], "logout_waiting_for_processes")
        self.assertEqual(record["seat"], "seat0")


class TestProbeSddmSeatObject(unittest.TestCase):
    @patch("seat_probes._run")
    def test_seat_name_capitalized_in_dbus_path(self, mock_run):
        mock_run.return_value = (
            0,
            "/org/freedesktop/DisplayManager\n"
            "/org/freedesktop/DisplayManager/Seat0\n"
            "/org/freedesktop/DisplayManager/Session0\n",
        )
        from seat_probes import probe_sddm_seat_object

        result = probe_sddm_seat_object("seat0")
        self.assertTrue(result["ok"])

    @patch("seat_probes._run")
    def test_seat2_capitalized(self, mock_run):
        mock_run.return_value = (
            0,
            "/org/freedesktop/DisplayManager\n/org/freedesktop/DisplayManager/Seat2\n",
        )
        from seat_probes import probe_sddm_seat_object

        result = probe_sddm_seat_object("seat2")
        self.assertTrue(result["ok"])

    @patch("seat_probes._run")
    def test_missing_seat_not_found(self, mock_run):
        mock_run.return_value = (
            0,
            "/org/freedesktop/DisplayManager\n/org/freedesktop/DisplayManager/Seat0\n",
        )
        from seat_probes import probe_sddm_seat_object

        result = probe_sddm_seat_object("seat5")
        self.assertFalse(result["ok"])


class TestFindKwinForSession(unittest.TestCase):
    @patch("seat_inventory._run")
    @patch("builtins.open")
    def test_lowercase_user_key(self, mock_open, mock_run):
        mock_run.side_effect = [(0, "1234"), (0, "5678")]

        def open_side_effect(path, mode="r", *args, **kwargs):
            if path == "/proc/1234/cmdline":
                return MagicMock(
                    read=MagicMock(
                        return_value=b"/usr/bin/kwin_wayland\0--socket\0wayland-0\0"
                    )
                )
            if path == "/proc/1234/stat":
                return MagicMock(
                    read=MagicMock(return_value="1234 (kwin_wayland) S 1233 0 0 0 0")
                )
            raise FileNotFoundError(path)

        mock_open.side_effect = open_side_effect
        result = find_kwin_for_session({"user": 1002, "uid": 1002})
        self.assertEqual(result["kwin_pid"], 1234)

    @patch("seat_inventory._run")
    @patch("builtins.open")
    def test_uid_fallback(self, mock_open, mock_run):
        mock_run.side_effect = [(0, "5678"), (0, "6789")]

        def open_side_effect(path, mode="r", *args, **kwargs):
            if path == "/proc/5678/cmdline":
                return MagicMock(
                    read=MagicMock(
                        return_value=b"/usr/bin/kwin_wayland\0--xwayland-display\0:1\0"
                    )
                )
            if path == "/proc/5678/stat":
                return MagicMock(
                    read=MagicMock(return_value="5678 (kwin_wayland) S 5677 0 0 0 0")
                )
            raise FileNotFoundError(path)

        mock_open.side_effect = open_side_effect
        result = find_kwin_for_session({"uid": 1002})
        self.assertEqual(result["kwin_pid"], 5678)

    @patch("seat_inventory._run")
    def test_no_uid(self, mock_run):
        result = find_kwin_for_session({})
        self.assertIsNone(result["kwin_pid"])

    @patch("seat_inventory._run")
    @patch("builtins.open")
    def test_skips_wrapper_pid(self, mock_open, mock_run):
        mock_run.side_effect = [(0, "100\n101"), (0, "555")]

        def open_side_effect(path, mode="r", *args, **kwargs):
            if path == "/proc/100/cmdline":
                return MagicMock(
                    read=MagicMock(
                        return_value=b"/usr/bin/kwin_wayland_wrapper\0--xwayland\0"
                    )
                )
            if path == "/proc/101/cmdline":
                return MagicMock(
                    read=MagicMock(
                        return_value=b"/usr/bin/kwin_wayland\0--socket\0wayland-0\0--xwayland-display\0:0\0"
                    )
                )
            if path == "/proc/101/stat":
                return MagicMock(
                    read=MagicMock(return_value="101 (kwin_wayland) S 99 0 0 0 0")
                )
            raise FileNotFoundError(path)

        mock_open.side_effect = open_side_effect
        result = find_kwin_for_session({"uid": 1002})
        self.assertEqual(result["kwin_pid"], 101)
        self.assertEqual(result["kwin_socket"], "wayland-0")
        self.assertEqual(result["kwin_display"], ":0")


class TestUserProcessSummary(unittest.TestCase):
    @patch("seat_probes._run")
    def test_splits_core_and_other_processes(self, mock_run):
        mock_run.return_value = (
            0,
            "100 1 100 100 50 Ss systemd /usr/lib/systemd/systemd --user\n"
            "101 100 101 100 40 Sl kwin_wayland /usr/bin/kwin_wayland --socket wayland-0\n"
            "102 100 102 100 300 S python python /home/samiran/dev/server.py\n"
            "103 100 103 100 200 S node node /home/samiran/app/server.js",
        )

        result = probe_user_process_summary(1002, "samiran")

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["core_processes"]), 2)
        self.assertEqual(result["other_process_count"], 2)
        self.assertEqual(
            result["oldest_other_processes"][0]["cmd"],
            "python /home/samiran/dev/server.py",
        )


class TestExtractSeatHint(unittest.TestCase):
    def test_seat_in_message(self):
        from journal_watch import extract_seat_hint

        event = JournalEvent("info", "login_success", "msg", "sddm")
        result = extract_seat_hint(event, "session started on seat2")
        self.assertEqual(result, "seat2")

    def test_no_seat_info(self):
        from journal_watch import extract_seat_hint

        event = JournalEvent("info", "login_success", "msg", "sddm")
        result = extract_seat_hint(event, "something happened")
        self.assertIsNone(result)

    @patch("builtins.open")
    def test_xdg_seat_from_environ(self, mock_open):
        from journal_watch import extract_seat_hint

        file_obj = MagicMock()
        file_obj.__enter__.return_value.read.return_value = b"XDG_SEAT=seat1\0"
        mock_open.side_effect = [file_obj]
        event = JournalEvent("info", "login_success", "msg", "sddm", pid=123)

        result = extract_seat_hint(event, "something happened")

        self.assertEqual(result, "seat1")


class TestIterJournal(unittest.TestCase):
    @patch("journal_watch.subprocess.Popen")
    def test_iter_journal_sets_seat_hint(self, mock_popen):
        import json
        from journal_watch import iter_journal

        proc = MagicMock()
        entry = {
            "MESSAGE": 'Authentication for user "samiran" successful on seat2',
            "_SYSTEMD_UNIT": "sddm",
            "SYSLOG_IDENTIFIER": "sddm",
            "_PID": "123",
        }
        proc.stdout.read.side_effect = [json.dumps(entry).encode() + b"\n", b""]
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        events = list(iter_journal())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].seat_hint, "seat2")

    @patch("journal_watch.subprocess.Popen")
    def test_iter_journal_parses_logind_session(self, mock_popen):
        import json
        from journal_watch import iter_journal

        proc = MagicMock()
        entry = {
            "MESSAGE": "Session 278 logged out. Waiting for processes to exit.",
            "SYSLOG_IDENTIFIER": "systemd-logind",
            "_PID": "2673",
        }
        proc.stdout.read.side_effect = [json.dumps(entry).encode() + b"\n", b""]
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        events = list(iter_journal())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "logout_waiting_for_processes")
        self.assertEqual(events[0].session_id, 278)


if __name__ == "__main__":
    unittest.main()
