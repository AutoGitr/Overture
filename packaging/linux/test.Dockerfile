ARG DISTRIBUTION=debian:13@sha256:3cda3ca472ce45507a5109c6a3907093e24d9ae67d55954c9a07a45665dafba2
FROM ${DISTRIBUTION}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    systemd systemd-sysv dbus ca-certificates passwd util-linux procps \
    && rm -rf /var/lib/apt/lists/*
COPY packaging/linux/test.sh scripts/container_smoke.py /srv/
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
