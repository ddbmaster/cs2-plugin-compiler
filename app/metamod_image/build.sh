#!/usr/bin/env bash
# Baut ein Metamod:Source-Plugin (AMBuild) in /src – läuft OHNE Netzwerk.
# Ergebnis: /src/build/package/... (vom Projekt-PackageScript erzeugt)
set -uo pipefail

cd /src || exit 2
export HOME=/tmp/home
mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL=/tmp/home/.gitconfig
git config --global safe.directory '*'
git config --global user.name "CS2 Plugin Compiler"
git config --global user.email "compiler@localhost"
git config --global init.defaultBranch main

echo "== Umgebung =="
echo "Compiler:  $(cat /sdk/clang.version 2>/dev/null)"
echo "Metamod:   $(cat /sdk/mmsource.rev 2>/dev/null)"
echo "CS2-SDK:   $(cat /sdk/hl2sdk.rev 2>/dev/null)"

# HL2SDK-Manifests: eigene Kopie des Projekts (Submodul) bevorzugen, sonst die mitgelieferte
if [ -f hl2sdk-manifests/SdkHelpers.ambuild ]; then
  echo "Manifests: aus dem Projekt"
else
  export HL2SDKMANIFESTS="$MM_DEFAULT_MANIFESTS"
  echo "Manifests: mitgeliefert (Submodul fehlt im Projekt)"
fi

# Viele AMBuildScripts lesen Version/Commit aus git – ohne Repo legen wir eins an
if ! git rev-parse HEAD >/dev/null 2>&1; then
  rm -rf .git
  git init -q && git add -A >/dev/null 2>&1 && git commit -q -m "build" >/dev/null 2>&1
  echo "Git:       lokales Repository angelegt"
fi
if ! git describe --tags >/dev/null 2>&1; then
  git tag "${MM_TAG:-v1.0.0}" >/dev/null 2>&1 || true
fi
echo "Version:   $(git describe --tags 2>/dev/null)"

OPT="--enable-optimize"
[ "${MM_CONFIG:-Release}" = "Debug" ] && OPT="--enable-debug"

rm -rf build && mkdir build && cd build || exit 2

echo
echo "== configure.py =="
python3 ../configure.py $OPT --sdks cs2 --targets x86_64 > /tmp/configure.log 2>&1
code=$?
if [ $code -ne 0 ] && grep -q "unrecognized arguments" /tmp/configure.log; then
  echo "(Projekt kennt --targets nicht – erneuter Versuch ohne)"
  python3 ../configure.py $OPT --sdks cs2 > /tmp/configure.log 2>&1
  code=$?
fi
cat /tmp/configure.log
if [ $code -ne 0 ]; then
  echo "__STEP_FAILED__ configure"
  exit $code
fi

echo
echo "== ambuild =="
ambuild
code=$?
if [ $code -ne 0 ]; then
  echo "__STEP_FAILED__ ambuild"
  exit $code
fi
echo "__BUILD_OK__"
