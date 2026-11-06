ARG DISTRIBUTION=debian:13@sha256:9c6e381421d0f48d1b8133e573f33c185ee16cbf505eda9c4a8a4791b25ea8a6
FROM ${DISTRIBUTION}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    systemd systemd-sysv dbus ca-certificates passwd util-linux procps \
    && rm -rf /var/lib/apt/lists/*
COPY packaging/linux/test.sh scripts/container_smoke.py /srv/
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
