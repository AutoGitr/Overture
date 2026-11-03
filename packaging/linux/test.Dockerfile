ARG DISTRIBUTION=debian:13@sha256:2dc419c6d7fe3dad0a2f9fd469c34cc90b0f9ba642d8fde837fe3d7d34a0e7f1
FROM ${DISTRIBUTION}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    systemd systemd-sysv dbus ca-certificates passwd util-linux procps \
    && rm -rf /var/lib/apt/lists/*
COPY packaging/linux/test.sh scripts/container_smoke.py /srv/
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
