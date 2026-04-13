import re
import json
import subprocess

TRIGGER_PATTERNS_INFO = [
    (re.compile(r"Authentication for user.*successful"), "login_success"),
    (re.compile(r"Session started"), "session_started"),
    (re.compile(r"Greeter stopped"), "greeter_stopped"),
    (re.compile(r"Greeter session started successfully"), "greeter_started"),
    (re.compile(r"Adding new display"), "display_added"),
    (re.compile(r"Removing display"), "display_removed"),
    (re.compile(r"Auth: sddm-helper exited successfully"), "helper_exited_success"),
]

TRIGGER_PATTERNS_LOGIND = [
    (
        re.compile(r"Session\s+(\d+)\s+logged out\. Waiting for processes to exit\."),
        "info",
        "logout_waiting_for_processes",
    ),
    (
        re.compile(r"Removed session\s+(\d+)\."),
        "info",
        "session_removed",
    ),
    (
        re.compile(r"New session\s+(\d+)\s+of user\s+(.+?)\."),
        "info",
        "new_session_opened",
    ),
]

TRIGGER_PATTERNS_SUSPICIOUS = [
    (re.compile(r"[Pp]rocess crashed|crashed \(exit code"), "process_crashed"),
    (re.compile(r"Auth: sddm-helper exited with (?!\b0\b)"), "helper_exited_error"),
    (re.compile(r"Authentication error"), "auth_error"),
    (re.compile(r"pam_unix\(sddm:session\): session closed"), "session_closed"),
]

TRIGGER_PATTERNS_SEVERE = [
    (re.compile(r"GPU fault detected"), "gpu_fault"),
    (re.compile(r"ring gfx timeout"), "ring_gfx_timeout"),
    (re.compile(r"VRAM is lost"), "vram_lost"),
    (re.compile(r"device wedged"), "device_wedged"),
    (re.compile(r"Failed to initialize parser"), "amdgpu_parser_failure"),
    (re.compile(r"amdgpu:\s*PCI error"), "amdgpu_pci_error"),
    (re.compile(r"AER:.*Uncorrectable"), "pcie_aer_uncorrectable"),
    (re.compile(r"Process kwin_wayland pid"), "kwin_in_gpu_event"),
]


class JournalEvent:
    def __init__(
        self,
        severity: str,
        event_type: str,
        message: str,
        source: str,
        seat_hint: str = None,
        pid: int = None,
        raw: dict = None,
        session_id: int = None,
        username: str = None,
    ):
        self.severity = severity
        self.event_type = event_type
        self.message = message
        self.source = source
        self.seat_hint = seat_hint
        self.pid = pid
        self.raw = raw
        self.session_id = session_id
        self.username = username

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "event_type": self.event_type,
            "message": self.message[:300],
            "source": self.source,
            "seat_hint": self.seat_hint,
            "pid": self.pid,
            "session_id": self.session_id,
            "username": self.username,
        }


def classify_journal_line(
    msg: str, unit: str = "", syslog_identifier: str = ""
) -> JournalEvent | None:
    source = unit or syslog_identifier or "unknown"

    if source in ("sddm",) or syslog_identifier in ("sddm", "sddm-helper"):
        for pat, etype in TRIGGER_PATTERNS_SEVERE:
            if pat.search(msg):
                return JournalEvent("severe", etype, msg, source)
        for pat, etype in TRIGGER_PATTERNS_SUSPICIOUS:
            if pat.search(msg):
                return JournalEvent("suspicious", etype, msg, source)
        for pat, etype in TRIGGER_PATTERNS_INFO:
            if pat.search(msg):
                return JournalEvent("info", etype, msg, source)

    if source == "kernel" or syslog_identifier == "kernel":
        for pat, etype in TRIGGER_PATTERNS_SEVERE:
            if pat.search(msg):
                return JournalEvent("severe", etype, msg, source)

    if source == "systemd-logind" or syslog_identifier == "systemd-logind":
        for pat, severity, etype in TRIGGER_PATTERNS_LOGIND:
            m = pat.search(msg)
            if not m:
                continue
            session_id = None
            username = None
            if etype in ("logout_waiting_for_processes", "session_removed"):
                session_id = int(m.group(1))
            elif etype == "new_session_opened":
                session_id = int(m.group(1))
                username = m.group(2).strip()
            return JournalEvent(
                severity,
                etype,
                msg,
                source,
                session_id=session_id,
                username=username,
            )

    return None


def extract_seat_hint(event: JournalEvent, msg: str) -> str | None:
    seat_match = re.search(r"seat\d+", msg)
    if seat_match:
        return seat_match.group(0)
    if event.pid:
        try:
            with open(f"/proc/{event.pid}/environ", "rb") as f:
                environ = f.read().decode(errors="replace")
            for token in environ.split("\0"):
                if token.startswith("XDG_SEAT="):
                    return token.split("=", 1)[1]
        except Exception:
            pass
        try:
            with open(f"/proc/{event.pid}/cgroup", "r") as f:
                cgroup = f.read()
            for line in cgroup.splitlines():
                m = re.search(r"seat(\d+)", line)
                if m:
                    return f"seat{m.group(1)}"
        except Exception:
            pass
    return None


def iter_journal(follow: bool = True):
    cmd = [
        "journalctl",
        "-f",
        "-o",
        "json",
        "-u",
        "sddm",
        "-k",
        "_COMM=systemd-logind",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        buf = b""
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = entry.get("MESSAGE", "")
                if isinstance(msg, list):
                    msg = bytes(msg).decode(errors="replace")
                unit = entry.get("_SYSTEMD_UNIT", "") or entry.get(
                    "SYSLOG_IDENTIFIER", ""
                )
                syslog_id = entry.get("SYSLOG_IDENTIFIER", "")
                pid = entry.get("_PID")
                try:
                    pid = int(pid) if pid else None
                except (ValueError, TypeError):
                    pid = None
                event = classify_journal_line(msg, unit, syslog_id)
                if event:
                    event.pid = pid
                    event.seat_hint = extract_seat_hint(event, msg)
                    event.raw = {
                        "__CURSOR": entry.get("__CURSOR"),
                        "__MONOTONIC_TIMESTAMP": entry.get("__MONOTONIC_TIMESTAMP"),
                    }
                    yield event
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
