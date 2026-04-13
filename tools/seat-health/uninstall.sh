#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-/usr/local}"
SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
LOGROTATE_DIR="${LOGROTATE_DIR:-/etc/logrotate.d}"
TMPFILES_DIR="${TMPFILES_DIR:-/etc/tmpfiles.d}"

echo "=== SDDM Seat Health Monitor - Uninstall ==="

echo "Stopping service (if running)..."
systemctl stop sddm-seat-health 2>/dev/null || true
systemctl disable sddm-seat-health 2>/dev/null || true

echo "Removing installed files..."
rm -f "${PREFIX}/bin/seat-health-monitor"
rm -rf "${PREFIX}/lib/sddm-seat-health"
rm -f "${SYSTEMD_UNIT_DIR}/sddm-seat-health.service"
rm -f "${LOGROTATE_DIR}/sddm-seat-health"
rm -f "${TMPFILES_DIR}/sddm-seat-health.conf"

echo "Reloading systemd..."
systemctl daemon-reload

echo ""
echo "Uninstall complete."
echo ""
echo "Log data was NOT removed. To delete it:"
echo "  rm -rf /var/log/sddm-seat-health"