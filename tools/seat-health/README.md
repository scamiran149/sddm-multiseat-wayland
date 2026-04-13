# SDDM Seat Health Monitor

Diagnostics-only seat health monitor for SDDM multi-seat Wayland setups.

## What It Does

- Runs as a root systemd service
- Monitors all known seats at a low baseline rate (every 60s)
- Watches `journalctl` for SDDM and kernel events
- Bursts into high-rate per-seat telemetry on suspicious or severe events
- Logs structured JSON (for parsing) and human-readable summaries
- Does **not** kill or restart anything — diagnostics only

## Architecture

```
seat_health_monitor.py   Main daemon
├── journal_watch.py     Tails journalctl, classifies events
├── seat_inventory.py    Enumerates seats/sessions via loginctl
├── seat_probes.py       Runs per-seat control-plane probes
├── incident_manager.py  Baseline/burst orchestration, state tracking
└── logging_utils.py     JSON + summary logging
```

## Trigger Classes

| Class | Events | Action |
|-------|--------|--------|
| Info | Login success, session start, greeter start/stop, display add/remove | Compact snapshot + optional +10s delayed snapshot |
| Suspicious | Helper crash, auth error, process crash, multiple user sessions on one seat, stale closing sessions, missing KWin owner, leader PID gone | Burst capture (2s for 60s) |
| Severe | GPU fault, ring gfx timeout, VRAM lost, device wedged, PCIe AER uncorrectable, KWin named in GPU event | Immediate burst capture, extended on repeated triggers |

## Probes

For each affected seat, the monitor probes:

- `loginctl show-session` for all sessions on the seat
- Session leader existence / process tree
- User D-Bus ping
- KWin bus-name ownership (`org.kde.KWin`)
- Wayland socket probe (`wayland-info`)
- Xwayland probe (`xdpyinfo`) when available
- SDDM D-Bus seat object presence
- Filtered process snapshot

## Session Selection

The monitor does **not** probe the first session on a seat. It:

1. Enumerates all sessions on the seat
2. Classifies each (active, closing, leader missing)
3. Selects the **newest non-closing user session** as the primary probe target
4. Logs all sessions including stale ones

## Log Location

```
/var/log/sddm-seat-health/
├── events.jsonl       Structured JSON records
├── summary.log        Human-readable summaries
└── incidents/         Per-incident detail (future)
```

Rotation: daily, keep 5 days, compress old files.

## Quick Start

```bash
# Install
sudo ./install.sh

# Enable and start
sudo systemctl enable sddm-seat-health
sudo systemctl start sddm-seat-health

# Check status
sudo systemctl status sddm-seat-health

# Watch logs
tail -f /var/log/sddm-seat-health/summary.log

# Uninstall
sudo ./uninstall.sh
```

## Manual Run

```bash
# Run in foreground with custom log dir
sudo python3 seat_health_monitor.py --log-dir /tmp/seat-health

# Dry run (baselines only, no journal watch)
sudo python3 seat_health_monitor.py --dry-run --log-dir /tmp/seat-health
```

## Running Tests

```bash
cd tools/seat-health
python3 -m unittest tests.test_seat_health -v
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `--log-dir` | `/var/log/sddm-seat-health` | Log directory |
| `--baseline-interval` | 60 | Baseline snapshot interval (seconds) |
| `--burst-interval` | 2 | Burst snapshot interval (seconds) |
| `--burst-duration` | 60 | Initial burst duration (seconds) |
| `--burst-extension` | 60 | Burst extension on repeated triggers (seconds) |
| `--dry-run` | off | Baselines only, no journal watch |

## Failure Taxology

The monitor is designed to capture evidence for these failure classes:

1. **Stale session** — session stuck in `closing` state after logout
2. **Dead control-plane** — user bus ping fails but session persists
3. **KWin startup failure** — `org.kde.KWin` missing after login
4. **Wayland/Xwayland wedge** — compositor PID exists but display path is broken
5. **GPU-reset hang** — KWin survives GPU reset in a non-functional state
6. **Relogin freeze** — session startup hangs, SDDM does not auto-recover
7. **Helper crash** — `sddm-helper` exits with error during session startup