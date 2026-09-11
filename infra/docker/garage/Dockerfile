# Bootstrap image for the single-node Garage cluster (E13-02).
#
# Why an image at all: dxflrs/garage is built FROM scratch, so it ships the binary and
# nothing else -- no shell, no `sh -c`, therefore no way to run the multi-step, idempotent
# bootstrap below as a compose one-shot service. The binary is a static PIE, so copying it
# into a plain alpine yields the exact same CLI (version pinned by the FROM) plus a shell.
# Nothing is downloaded at build time.
#
# The version is a build arg, and docker-compose.yml passes the very same value it uses
# for the `garage` server image: a CLI/server skew would otherwise be silent, and its most
# likely symptom is init.sh failing to parse `garage layout show`.
ARG GARAGE_VERSION=v1.0.1
FROM dxflrs/garage:${GARAGE_VERSION} AS garage

FROM alpine:3.20
COPY --from=garage /garage /usr/local/bin/garage
COPY init.sh /usr/local/bin/garage-init
RUN chmod +x /usr/local/bin/garage-init
ENTRYPOINT ["/usr/local/bin/garage-init"]
