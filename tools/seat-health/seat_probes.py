import re
import subprocess
import time

from seat_inventory import _run, find_kwin_for_session

CORE_PROCESS_PATTERNS = (
    "systemd --user",
    "dbus-daemon",
    "dbus-broker",
    "startplasma",
    "kwin_wayland_wrapper",
    "kwin_wayland",
    "plasmashell",
    "ksmserver",
    "kded",
    "Xwayland",
    "sddm-helper",
    "logos-connector-bridge",
)


def probe_user_bus_ping(username: str, uid: int) -> dict:
    runtime_dir = f"/run/user/{uid}"
    bus = f"unix:path={runtime_dir}/bus"
    rc, out = _run(
        [
            "runuser",
            "-u",
            username,
            "--",
            "env",
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"DBUS_SESSION_BUS_ADDRESS={bus}",
            "timeout",
            "3s",
            "busctl",
            "--user",
            "call",
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus.Peer",
            "Ping",
        ],
        timeout=5,
    )
    return {
        "ok": rc == 0,
        "exit_code": rc,
        "detail": out[:200] if out else "",
        "duration_ms": 0,
    }


def probe_kwin_owner(username: str, uid: int) -> dict:
    runtime_dir = f"/run/user/{uid}"
    bus = f"unix:path={runtime_dir}/bus"
    rc, out = _run(
        [
            "runuser",
            "-u",
            username,
            "--",
            "env",
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"DBUS_SESSION_BUS_ADDRESS={bus}",
            "timeout",
            "3s",
            "busctl",
            "--user",
            "call",
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "GetNameOwner",
            "s",
            "org.kde.KWin",
        ],
        timeout=5,
    )
    return {
        "ok": rc == 0,
        "exit_code": rc,
        "detail": out[:200] if out else "",
        "duration_ms": 0,
    }


def probe_wayland(username: str, uid: int, socket_name: str = "wayland-0") -> dict:
    runtime_dir = f"/run/user/{uid}"
    rc, out = _run(["which", "wayland-info"], timeout=3)
    if rc != 0:
        return {
            "ok": False,
            "exit_code": -1,
            "detail": "wayland-info not installed",
            "skipped": True,
        }
    rc2, out2 = _run(
        [
            "runuser",
            "-u",
            username,
            "--",
            "env",
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"WAYLAND_DISPLAY={socket_name}",
            "timeout",
            "3s",
            "wayland-info",
        ],
        timeout=5,
    )
    return {
        "ok": rc2 == 0,
        "exit_code": rc2,
        "detail": out2[:200] if out2 else "",
        "duration_ms": 0,
    }


def probe_xwayland(username: str, uid: int, display: str) -> dict:
    rc, out = _run(["which", "xdpyinfo"], timeout=3)
    if rc != 0:
        return {
            "ok": False,
            "exit_code": -1,
            "detail": "xdpyinfo not installed",
            "skipped": True,
        }
    if not display:
        return {"ok": False, "exit_code": -1, "detail": "no display", "skipped": True}
    runtime_dir = f"/run/user/{uid}"
    rc2, out2 = _run(
        [
            "runuser",
            "-u",
            username,
            "--",
            "env",
            f"XDG_RUNTIME_DIR={runtime_dir}",
            f"DISPLAY={display}",
            "timeout",
            "3s",
            "xdpyinfo",
        ],
        timeout=5,
    )
    return {
        "ok": rc2 == 0,
        "exit_code": rc2,
        "detail": out2[:200] if out2 else "",
        "duration_ms": 0,
    }


def probe_sddm_bus() -> dict:
    rc, out = _run(
        [
            "timeout",
            "3s",
            "busctl",
            "call",
            "org.freedesktop.DisplayManager",
            "/org/freedesktop/DisplayManager",
            "org.freedesktop.DBus.Peer",
            "Ping",
        ],
        timeout=5,
    )
    return {"ok": rc == 0, "exit_code": rc, "detail": out[:200] if out else ""}


def probe_sddm_seat_object(seat_name: str) -> dict:
    rc, out = _run(
        ["timeout", "3s", "busctl", "tree", "org.freedesktop.DisplayManager"], timeout=5
    )
    has_seat = False
    if rc == 0:
        dbus_name = re.sub(r"^seat", "Seat", seat_name, count=1)
        has_seat = f"/org/freedesktop/DisplayManager/{dbus_name}" in (out or "")
    return {"ok": has_seat, "exit_code": rc, "detail": out[:200] if out else ""}


def probe_process_snapshot() -> list[dict]:
    rc, out = _run(
        ["ps", "-eo", "pid,ppid,pgid,sid,stat,etimes,cmd"],
        timeout=5,
    )
    if rc != 0:
        return []
    procs = []
    filters = (
        "sddm",
        "sddm-helper",
        "sddm-greeter",
        "kwin_wayland",
        "kwin_wayland_wrapper",
        "startplasma",
        "Xwayland",
        "dbus-daemon",
        "systemd --user",
    )
    for line in out.splitlines()[1:]:
        if any(f in line for f in filters):
            parts = line.split(None, 6)
            if len(parts) >= 7:
                try:
                    procs.append(
                        {
                            "pid": int(parts[0]),
                            "ppid": int(parts[1]),
                            "pgid": int(parts[2]),
                            "sid": int(parts[3]),
                            "stat": parts[4],
                            "etimes": int(parts[5]),
                            "cmd": parts[6],
                        }
                    )
                except (ValueError, IndexError):
                    pass
    return procs


def probe_user_process_summary(uid: int, username: str | None = None) -> dict:
    rc, out = _run(
        [
            "ps",
            "-u",
            str(uid),
            "-o",
            "pid,ppid,pgid,sid,etimes,stat,comm,args",
            "--no-headers",
        ],
        timeout=5,
    )
    if rc != 0:
        return {
            "ok": False,
            "exit_code": rc,
            "detail": out[:200] if out else "",
            "user": username,
            "uid": uid,
        }

    processes = []
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        try:
            proc = {
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "pgid": int(parts[2]),
                "sid": int(parts[3]),
                "etimes": int(parts[4]),
                "stat": parts[5],
                "comm": parts[6],
                "cmd": parts[7],
            }
        except ValueError:
            continue
        proc["category"] = (
            "core"
            if any(pattern in proc["cmd"] for pattern in CORE_PROCESS_PATTERNS)
            else "other"
        )
        processes.append(proc)

    core_processes = [p for p in processes if p["category"] == "core"]
    other_processes = [p for p in processes if p["category"] == "other"]
    core_processes.sort(key=lambda p: (-p["etimes"], p["pid"]))
    other_processes.sort(key=lambda p: (-p["etimes"], p["pid"]))
    return {
        "ok": True,
        "exit_code": 0,
        "user": username,
        "uid": uid,
        "core_processes": core_processes,
        "other_process_count": len(other_processes),
        "oldest_other_processes": other_processes[:10],
    }


def run_all_probes(session: dict, seat_name: str, logger=None) -> dict:
    results = {}
    uid = session.get("user") or session.get("uid")
    username = session.get("name") or session.get("user")
    session_id = session.get("id")

    if not uid or not username:
        results["error"] = "missing uid or username for probe"
        return results

    kwin_info = find_kwin_for_session(session)

    start = time.time()
    r = probe_user_bus_ping(username, uid)
    r["duration_ms"] = int((time.time() - start) * 1000)
    results["user_bus_ping"] = r
    if logger:
        logger.emit_probe(seat_name, str(session_id), "user_bus_ping", r)

    start = time.time()
    r = probe_kwin_owner(username, uid)
    r["duration_ms"] = int((time.time() - start) * 1000)
    results["kwin_bus_owner"] = r
    if logger:
        logger.emit_probe(seat_name, str(session_id), "kwin_bus_owner", r)

    socket_name = kwin_info.get("kwin_socket") or "wayland-0"
    start = time.time()
    r = probe_wayland(username, uid, socket_name)
    r["duration_ms"] = int((time.time() - start) * 1000)
    results["wayland_probe"] = r
    if logger:
        logger.emit_probe(seat_name, str(session_id), "wayland_probe", r)

    display = kwin_info.get("kwin_display")
    start = time.time()
    r = probe_xwayland(username, uid, display)
    r["duration_ms"] = int((time.time() - start) * 1000)
    results["xwayland_probe"] = r
    if logger:
        logger.emit_probe(seat_name, str(session_id), "xwayland_probe", r)

    results["kwin_info"] = kwin_info
    results["process_snapshot"] = probe_process_snapshot()
    results["user_process_summary"] = probe_user_process_summary(uid, username)

    return results


def run_compact_probes(session: dict, seat_name: str) -> dict:
    results = {}
    uid = session.get("user") or session.get("uid")
    username = session.get("name") or session.get("user")
    if not uid or not username:
        return {"error": "missing uid or username for compact probe"}
    results["user_bus_ping"] = probe_user_bus_ping(username, uid)
    results["kwin_bus_owner"] = probe_kwin_owner(username, uid)
    results["user_process_summary"] = probe_user_process_summary(uid, username)
    return results
