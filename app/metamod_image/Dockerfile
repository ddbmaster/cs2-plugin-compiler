# Build-Umgebung für Metamod:Source-Plugins (CS2, Linux)
# Basis: Source2ZE-Build-Container (Steam Runtime + Clang + lld + AMBuild + git)
ARG BASE=ghcr.io/source2ze/build-containers:steamrt3
FROM ${BASE}

ARG MMS_REF=master
ARG SDK_REF=cs2
ARG CACHE_BUST=0

# Metamod:Source, CS2-SDK (s2sdk) und HL2SDK-Manifests fest ins Image
RUN echo "${CACHE_BUST}" > /dev/null \
 && git clone --depth 1 --recurse-submodules --shallow-submodules -b "${MMS_REF}" \
        https://github.com/alliedmodders/metamod-source /sdk/mmsource-2.0 \
 && git clone --depth 1 -b "${SDK_REF}" https://github.com/alliedmodders/s2sdk /sdk/hl2sdk-cs2 \
 && git clone --depth 1 https://github.com/alliedmodders/hl2sdk-manifests /sdk/hl2sdk-manifests \
 && (cd /sdk/mmsource-2.0 && git log -1 --format=%h > /sdk/mmsource.rev) \
 && (cd /sdk/hl2sdk-cs2 && git log -1 --format='%h %cs' > /sdk/hl2sdk.rev) \
 && find /sdk -name .git -prune -exec rm -rf {} + \
 && chmod -R a+rX /sdk

COPY build.sh /usr/local/bin/mm-build
RUN chmod 755 /usr/local/bin/mm-build \
 && (command -v python3 >/dev/null || ln -s "$(command -v python)" /usr/local/bin/python3) \
 && python3 -c "import ambuild2" \
 && clang --version | head -1 > /sdk/clang.version

ENV MMSOURCE20=/sdk/mmsource-2.0 \
    HL2SDKCS2=/sdk/hl2sdk-cs2 \
    MM_DEFAULT_MANIFESTS=/sdk/hl2sdk-manifests \
    CC=clang \
    CXX=clang++

LABEL cssharp-compiler.metamod="1"
