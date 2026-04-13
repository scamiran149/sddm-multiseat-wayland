#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/usr/local}"
SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
LOGROTATE_DIR="${LOGROTATE_DIR:-/etc/logrotate.d}"
TMPFILES_DIR="${TMPFILES_DIR:-/etc/tmpfiles.d}"

echo "=== SDDM Seat Health Monitor - Install ==="
echo "Prefix:          ${PREFIX}"
echo "Systemd unit:    ${SYSTEMD_UNIT_DIR}"
echo "Logrotate:       ${LOGROTATE_DIR}"
echo "Tmpfiles:        ${TMPFILES_DIR}"
echo ""

echo "Creating log directory..."
mkdir -p /var/log/sddm-seat-health
mkdir -p /var/log/sddm-seat-health/incidents

echo "Installing monitor script..."
install -m 755 "${SCRIPT_DIR}/seat_health_monitor.py" "${PREFIX}/bin/seat-health-monitor"

echo "Installing Python modules..."
mkdir -p "${PREFIX}/lib/sddm-seat-health/"
for mod in logging_utils.py seat_inventory.py seat_probes.py journal_watch.py incident_manager.py; do
    install -m 644 "${SCRIPT_DIR}/${mod}" "${PREFIX}/lib/sddm-seat-health/${mod}"
done

echo "Patching module paths in monitor script..."
sed -i "s|sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))|sys.path.insert(0, '${PREFIX}/lib/sddm-seat-health')|" "${PREFIX}/bin/seat-health-monitor"

echo "Installing systemd unit..."
install -m 644 "${SCRIPT_DIR}/systemd/sddm-seat-health.service" "${SYSTEMD_UNIT_DIR}/sddm-seat-health.service"

echo "Installing logrotate config..."
install -m 644 "${SCRIPT_DIR}/systemd/sddm-seat-health.logrotate" "${LOGROTATE_DIR}/sddm-seat-health"

echo "Installing tmpfiles config..."
install -m 644 "${SCRIPT_DIR}/systemd/sddm-seat-health.tmpfiles.conf" "${TMPFILES_DIR}/sddm-seat-health.conf"

echo "Reloading systemd..."
systemctl daemon-reload

echo ""
echo "Install complete."
echo ""
echo "To enable and start the monitor:"
echo "  systemctl enable sddm-seat-health"
echo "  systemctl start sddm-seat-health"
echo ""
echo "To check status:"
echo "  systemctl status sddm-seat-health"
echo ""
echo "Logs:"
echo "  /var/log/sddm-seat-health/events.jsonl"
echo "  /var/log/sddm-seat-health/summary.log"