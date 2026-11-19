# Minimal ffmpeg + libass image used by the rootless "Docker-wrapped ffmpeg" option
# (see docker/ffmpeg-wrapper/README.md). All binaries come from Debian's official archive.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT []
CMD ["ffmpeg", "-version"]
