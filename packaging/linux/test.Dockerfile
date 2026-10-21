ARG DISTRIBUTION
FROM ${DISTRIBUTION}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    systemd systemd-sysv dbus ca-certificates passwd util-linux procps \
    && rm -rf /var/lib/apt/lists/*
COPY packaging/linux/test.sh scripts/container_smoke.py /srv/
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
