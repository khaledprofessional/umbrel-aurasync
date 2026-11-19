FROM debian:bookworm@sha256:268fb24c39bca92d326dd83ea3abebe4a3f7751c804ffef23bb6d857dd343ff8 AS builder

ARG OPENRGB_REF=release_1.1
ARG HIDAPI_REF=0.14.0

ENV PKG_CONFIG_PATH=/usr/local/lib/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        cmake \
        build-essential \
        pkgconf \
        libudev-dev \
        qtbase5-dev \
        qtchooser \
        qt5-qmake \
        qtbase5-dev-tools \
        libusb-1.0-0-dev \
        libmbedtls-dev \
        qttools5-dev-tools \
    && rm -rf /var/lib/apt/lists/*

# Debian bookworm's hidapi 0.13 is too old for OpenRGB 1.1's HID LampArray
# controller. Build 0.14+, which provides hid_get_report_descriptor().
RUN git clone --depth 1 --branch "hidapi-${HIDAPI_REF}" https://github.com/libusb/hidapi.git /src/hidapi \
    && cmake -S /src/hidapi -B /src/hidapi/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DHIDAPI_WITH_HIDRAW=ON \
        -DHIDAPI_WITH_LIBUSB=ON \
        -DHIDAPI_BUILD_TEST=OFF \
    && cmake --build /src/hidapi/build -j"$(nproc)" \
    && cmake --install /src/hidapi/build \
    && ldconfig

WORKDIR /src/OpenRGB
RUN git clone --depth 1 --branch "${OPENRGB_REF}" https://github.com/CalcProgrammer1/OpenRGB.git . \
    && qmake OpenRGB.pro \
    && make -j"$(nproc)"


FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        kmod \
        netcat-openbsd \
        libqt5core5a \
        libqt5dbus5 \
        libqt5gui5 \
        libqt5network5 \
        libqt5widgets5 \
        libqt5concurrent5 \
        libusb-1.0-0 \
        libudev1 \
        libmbedtls14 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/libhidapi-hidraw.so* /usr/local/lib/
COPY --from=builder /usr/local/lib/libhidapi-libusb.so* /usr/local/lib/
RUN ldconfig

COPY --from=builder /src/OpenRGB/openrgb /usr/local/bin/openrgb
COPY entrypoint.sh /usr/local/bin/openrgb-entrypoint
RUN chmod +x /usr/local/bin/openrgb-entrypoint \
    && mkdir -p /config \
    && /usr/local/bin/openrgb --help >/dev/null 2>&1 || true

ENV HOME=/config \
    OPENRGB_CONFIG_DIR=/config \
    OPENRGB_SERVER_PORT=6742 \
    QT_QPA_PLATFORM=offscreen

EXPOSE 6742
VOLUME ["/config"]

ENTRYPOINT ["/usr/local/bin/openrgb-entrypoint"]
