import subprocess
import os


def _run(args: list, timeout: int = 5) -> tuple[int, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return -1, "<timeout>"
    except Exception as e:
        return -2, str(e)


def list_sessions() -> list[dict]:
    rc, out = _run(["loginctl", "list-sessions", "--no-legend"])
    if rc != 0 or not out:
        return []
    sessions = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 7:
            continue
        sessions.append(
            {
                "id": int(parts[0]),
                "uid": int(parts[1]),
                "user": parts[2],
                "seat": parts[3] if parts[3] != "-" else None,
                "leader": int(parts[4]) if parts[4].isdigit() else None,
                "class": parts[5],
                "tty": parts[6] if len(parts) > 6 else None,
                "idle": parts[7] if len(parts) > 7 else None,
            }
        )
    return sessions


def show_session(session_id: int) -> dict:
    rc, out = _run(["loginctl", "show-session", str(session_id), "-a"])
    if rc != 0:
        return {"id": session_id, "raw_error": out}
    result = {"id": session_id}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            key = k.strip().lower()
            result[key] = v.strip()
    for int_key in ("leader", "user", "audit", "vtnr"):
        if int_key in result and str(result[int_key]).isdigit():
            result[int_key] = int(result[int_key])
    return result


def session_details(session_id: int) -> dict:
    detail = show_session(session_id)
    if detail.get("raw_error"):
        return detail
    detail["id"] = session_id
    seat_name = detail.get("seat")
    leader_pid = detail.get("leader", 0)
    detail["leader_exists"] = leader_exists(leader_pid)
    if seat_name == "":
        detail["seat"] = None
    return detail


def seat_status(seat_name: str) -> str:
    rc, out = _run(["loginctl", "seat-status", seat_name])
    return out if rc == 0 else f"<error rc={rc}>"


def leader_exists(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    return os.path.exists(f"/proc/{pid}")


def session_tree(pid: int) -> str:
    if not leader_exists(pid):
        return f"<leader pid={pid} not found>"
    rc, out = _run(["pstree", "-aps", str(pid)], timeout=5)
    return out if rc == 0 else f"<error rc={rc}>"


def enumerate_seat_sessions(seat_name: str) -> list[dict]:
    all_sessions = list_sessions()
    seat_sessions = []
    for s in all_sessions:
        if s.get("seat") != seat_name:
            continue
        detail = show_session(s["id"])
        merged = {**s, **detail}
        merged["id"] = s["id"]
        merged["seat"] = seat_name
        leader_pid = detail.get("leader", s.get("leader", 0))
        merged["leader_exists"] = leader_exists(leader_pid)
        if leader_pid and not merged.get("leader"):
            merged["leader"] = leader_pid
        seat_sessions.append(merged)
    return seat_sessions


def pick_primary_session(seat_sessions: list[dict]) -> dict | None:
    candidates = [
        s
        for s in seat_sessions
        if s.get("state") not in ("closing",)
        and s.get("class") == "user"
        and s.get("leader_exists", False)
    ]
    if not candidates:
        no_leader = [
            s
            for s in seat_sessions
            if s.get("state") not in ("closing",) and s.get("class") == "user"
        ]
        if no_leader:
            candidates = no_leader
        else:
            return None
    candidates.sort(key=lambda s: s.get("id", 0), reverse=True)
    return candidates[0]


def stale_sessions(seat_sessions: list[dict]) -> list[dict]:
    return [s for s in seat_sessions if s.get("state") == "closing"]


def user_sessions_on_seat(seat_sessions: list[dict]) -> list[dict]:
    return [s for s in seat_sessions if s.get("class") == "user"]


def find_kwin_for_session(session: dict) -> dict:
    uid = session.get("user") or session.get("uid")
    if not uid:
        return {
            "kwin_pid": None,
            "kwin_display": None,
            "kwin_socket": None,
            "wrapper_pid": None,
            "xwayland_pid": None,
        }
    rc, out = _run(["pgrep", "-u", str(uid), "-f", "kwin_wayland"], timeout=5)
    pids = [p for p in out.splitlines() if p.strip().isdigit()] if rc == 0 else []
    kwin_pid = None
    kwin_display = None
    kwin_socket = None
    for pid_str in pids:
        try:
            pid = int(pid_str)
            cmdline = open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace")
        except Exception:
            continue
        if "kwin_wayland_wrapper" in cmdline:
            continue
        if "kwin_wayland" in cmdline:
            kwin_pid = pid
            tokens = cmdline.split("\0")
            i = 0
            while i < len(tokens):
                tok = tokens[i]
                if tok == "--xwayland-display" and i + 1 < len(tokens):
                    kwin_display = tokens[i + 1]
                elif tok == "--socket" and i + 1 < len(tokens):
                    kwin_socket = tokens[i + 1]
                elif tok.startswith("--xwayland-display="):
                    kwin_display = tok.split("=", 1)[1]
                elif tok.startswith("--socket="):
                    kwin_socket = tok.split("=", 1)[1]
                i += 1
            break
    if kwin_pid:
        try:
            stat_data = open(f"/proc/{kwin_pid}/stat", "r").read()
            ppid_str = stat_data.split(")")[1].split()[1]
            wrapper_pid = int(ppid_str)
        except Exception:
            wrapper_pid = None
    else:
        wrapper_pid = None
    xwayland_pid = None
    if uid:
        rc2, out2 = _run(["pgrep", "-u", str(uid), "-f", "Xwayland"], timeout=5)
        xpids = (
            [p for p in out2.splitlines() if p.strip().isdigit()] if rc2 == 0 else []
        )
        xwayland_pid = int(xpids[0]) if xpids else None
    return {
        "kwin_pid": kwin_pid,
        "kwin_display": kwin_display,
        "kwin_socket": kwin_socket,
        "wrapper_pid": wrapper_pid,
        "xwayland_pid": xwayland_pid,
    }


def all_seats() -> list[str]:
    all_sessions = list_sessions()
    seats = set()
    for s in all_sessions:
        if s.get("seat"):
            seats.add(s["seat"])
    try:
        rc, out = _run(["loginctl", "list-seats", "--no-legend"])
        if rc == 0:
            for line in out.splitlines():
                seat_name = line.strip().split()[0] if line.strip() else None
                if seat_name:
                    seats.add(seat_name)
    except Exception:
        pass
    return sorted(seats)
