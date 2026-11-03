#!/usr/bin/env bash
set -euo pipefail

fail() { echo "Error: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "Run this installer with sudo."
[[ $(uname -m) == x86_64 ]] || fail "This release supports Linux x86_64 only."
[[ -d /run/systemd/system ]] || fail "A running systemd installation is required."
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# The build verified that no bundled binary needs a newer glibc than this.
required=$(<"$bundle/glibc-minimum")
glibc=$(getconf GNU_LIBC_VERSION 2>/dev/null | cut -d' ' -f2) || glibc=""
[[ -n $glibc && $(printf '%s\n' "$required" "$glibc" | sort -V | head -1) == "$required" ]] \
    || fail "glibc $required or newer is required (found ${glibc:-none})."

media_groups=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --media-group)
            [[ $# -ge 2 ]] || fail "--media-group requires an existing group."
            getent group "$2" >/dev/null || fail "Media group does not exist."
            media_groups+=("$2"); shift 2 ;;
        *) fail "Usage: install.sh [--media-group GROUP]..." ;;
    esac
done

version=$("$bundle/bin/overture" --version)
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Invalid release version."
target="/opt/overture/$version"
previous=$(readlink -f /opt/overture/current || true)
if [[ -n $previous && -x $previous/bin/overture ]]; then
    old_version=$("$previous/bin/overture" --version)
    [[ $(printf '%s\n' "$old_version" "$version" | sort -V | tail -1) == "$version" ]] || fail "Use the documented manual rollback procedure to downgrade."
fi

getent group overture >/dev/null || groupadd --system overture
id overture >/dev/null 2>&1 || useradd --system --gid overture --home-dir /var/lib/overture --no-create-home --shell /usr/sbin/nologin overture
[[ $(id -u overture) -ne 0 ]] || fail "The overture service account must not have UID 0."
for group in "${media_groups[@]}"; do usermod --append --groups "$group" overture; done
install -d -o root -g root -m 0755 /opt/overture
install -d -o root -g overture -m 0750 /etc/overture
install -d -o overture -g overture -m 0750 /var/lib/overture

systemctl stop overture.service 2>/dev/null || {
    [[ ! -f /etc/systemd/system/overture.service ]] || fail "Could not stop Overture."
}

# Reinstalling a version replaces it, which also repairs a damaged copy.
staging=$(mktemp -d /opt/overture/.install-XXXXXXXX)
trap 'rm -rf -- "$staging"' EXIT
cp -a "$bundle/." "$staging/"
chown -R root:root "$staging"
chmod -R go-w "$staging"
chmod 0755 "$staging"
rm -rf -- "$target"
mv -- "$staging" "$target"
trap - EXIT

[[ -f /etc/overture/overture.env ]] || "$target/bin/overture" setup
chown root:overture /etc/overture/overture.env
chmod 0640 /etc/overture/overture.env

# A failed validation/start leaves the service stopped, including after migrations.
failed() {
    systemctl stop overture.service 2>/dev/null || true
    echo "Installation did not start successfully. Overture is stopped." >&2
    echo "Previous release: ${previous:-none}. Pre-upgrade database backups are in the backups folder of the config directory." >&2
    echo "Inspect journalctl -u overture and $target/README.md for recovery." >&2
}
trap failed ERR
runuser -u overture -- "$target/bin/overture" check
ln -sfn "$target" /opt/overture/.current-next
mv -Tf /opt/overture/.current-next /opt/overture/current
ln -sfn /opt/overture/current/bin/overture /usr/local/bin/overture
install -m 0644 "$target/overture.service" /etc/systemd/system/overture.service
systemctl daemon-reload
systemctl enable overture.service
systemctl start overture.service
"$target/bin/overture" probe
trap - ERR

# Keep only the installed release and the one before it.
for release in /opt/overture/*; do
    [[ -L $release || $release == "$target" || $release == "$previous" ]] || rm -rf -- "$release"
done
echo "Overture $version installed. Logs: journalctl -u overture"
