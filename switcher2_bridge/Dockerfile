FROM ghcr.io/home-assistant/base:latest

RUN \
  apk add --no-cache \
    python3 \
    py3-pip \
    py3-setuptools \
    py3-wheel \
  && python3 -m pip install --break-system-packages --no-cache-dir \
    "flask>=3.0" \
    "pymodbus>=3.0" \
    "pyserial>=3.5" \
    "PyYAML>=6.0"

COPY rootfs /

RUN chmod a+x /etc/services.d/switcher2_bridge/run
