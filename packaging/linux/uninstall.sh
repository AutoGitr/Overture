#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
if [[ -f /etc/systemd/system/overture.service ]]; then
    systemctl disable --now overture.service
fi
rm -f /etc/systemd/system/overture.service /usr/local/bin/overture
systemctl daemon-reload
# Fixed application directory only. Persistent data and the service user remain.
[[ ! -L /opt/overture ]] || { echo "Refusing a symlinked application directory." >&2; exit 1; }
rm -rf -- /opt/overture
echo "Application removed. Configuration, data and the overture user remain."
