#!/usr/bin/env bash
# Exercise the real archive in an offline systemd container built from
# test.Dockerfile. The workflow restarts the container between the phases.
set -euo pipefail

smoke() { runuser -u overture -- /opt/overture/current/bin/python /srv/container_smoke.py "$@"; }

if [[ ${1:-} == after-restart ]]; then
    /opt/overture/current/bin/overture probe
    smoke --expected-tab themes
    bash /opt/overture/current/uninstall.sh
    test -f /var/lib/overture/overture.db
    test -f /etc/overture/overture.env
    test ! -e /opt/overture
    exit 0
fi

bundle=$(find /srv/release -mindepth 1 -maxdepth 1 -type d -name 'overture-*')
[[ -n $bundle && ! -e /opt/overture ]]
! command -v uv
! command -v python3

# Install unattended from a prepared configuration file.
groupadd media-test
install -d -o root -g media-test -m 2770 /srv/media-test
install -d -m 0700 /etc/overture
{
    echo "MEDIA_SERVER=plex"
    echo "MEDIA_SERVER_URL=http://127.0.0.1:32400"
    echo "MEDIA_SERVER_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    echo smoke-password-long | "$bundle/bin/overture" password hash --password-stdin
} > /etc/overture/overture.env
bash "$bundle/install.sh" --media-group media-test
runuser -u overture -- touch /srv/media-test/service-can-write
systemctl is-enabled --quiet overture
systemctl is-active --quiet overture
test "$(stat -c '%U:%G:%a' /etc/overture)" = root:overture:750
test "$(stat -c '%U:%G:%a' /etc/overture/overture.env)" = root:overture:640
! runuser -u overture -- test -w /opt/overture/current/bin/overture
smoke --set-tab themes

# Pose as a prior release, then upgrade and keep settings. When an earlier
# schema revision exists the database is also stepped one revision behind. With
# only the baseline revision there is nothing to step back to (a downgrade would
# drop every table and the settings under test), so only the release is replaced.
systemctl stop overture
current=$(readlink -f /opt/overture/current)
cp -a "$current" /opt/overture/0.0.0
sed -i 's/^Version: .*/Version: 0.0.0/' /opt/overture/0.0.0/runtime/lib/python3.*/site-packages/overture-*.dist-info/METADATA
schema_revisions=$(runuser -u overture -- /opt/overture/0.0.0/bin/python - <<'EOF'
from alembic.script import ScriptDirectory

from overture.db.session import alembic_config

print(len(list(ScriptDirectory.from_config(alembic_config()).walk_revisions())))
EOF
)
if ((schema_revisions > 1)); then
runuser -u overture -- /opt/overture/0.0.0/bin/python - <<'EOF'
from alembic import command
from sqlalchemy import create_engine

from overture.db.session import alembic_config

engine = create_engine("sqlite:////var/lib/overture/overture.db")
with engine.begin() as connection:
    config = alembic_config()
    config.attributes["connection"] = connection
    command.downgrade(config, "-1")
EOF
fi
ln -sfn /opt/overture/0.0.0 /opt/overture/current
rm -rf -- "$current"
install -d /opt/overture/stale-release
bash "$bundle/install.sh"
smoke --expected-tab themes
test -d /opt/overture/0.0.0
test ! -e /opt/overture/stale-release
if ((schema_revisions > 1)); then
    # A pending schema upgrade backs the database up first.
    find /var/lib/overture/backups -name 'overture_*.db' | grep -q .
fi

# A failed start must leave the service stopped and the database in place.
install -d /etc/systemd/system/overture.service.d
printf '[Service]\nExecStartPre=/bin/false\n' > /etc/systemd/system/overture.service.d/failure.conf
systemctl daemon-reload
if bash "$bundle/install.sh"; then echo 'Expected a failed start' >&2; exit 1; fi
! systemctl is-active --quiet overture
test -f /var/lib/overture/overture.db
rm /etc/systemd/system/overture.service.d/failure.conf
systemctl daemon-reload
systemctl reset-failed overture
systemctl start overture
/opt/overture/current/bin/overture probe

# Stopping the service also stops every process in its cgroup.
sleep 300 &
child=$!
cgroup=$(systemctl show --property=ControlGroup --value overture)
echo "$child" > "/sys/fs/cgroup$cgroup/cgroup.procs"
systemctl stop overture
! kill -0 "$child" 2>/dev/null
systemctl start overture
/opt/overture/current/bin/overture probe
