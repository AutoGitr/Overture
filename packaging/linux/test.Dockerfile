ARG DISTRIBUTION=ubuntu:22.04@sha256:0a9887931b0e38af2e3487ed39e29436b0535c4f3f52e57745baaf79d1898956
FROM ${DISTRIBUTION}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    systemd systemd-sysv dbus ca-certificates passwd util-linux procps \
    && rm -rf /var/lib/apt/lists/*
COPY packaging/linux/test.sh scripts/container_smoke.py /srv/
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
