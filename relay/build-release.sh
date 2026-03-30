#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"

DEFAULT_TARGETS=(
  "windows/amd64"
  "linux/amd64"
  "linux/arm64"
  "linux/arm/v7"
  "linux/mips/softfloat"
  "linux/mipsle/softfloat"
  "linux/mips64"
  "linux/mips64le"
  "android/amd64"
  "android/arm64"
  "android/arm/v7"
)

if [[ $# -gt 0 ]]; then
  TARGETS=("$@")
else
  TARGETS=("${DEFAULT_TARGETS[@]}")
fi

mkdir -p "${DIST_DIR}"

build_target() {
  local target="$1"
  local goos=""
  local goarch=""
  local goarm=""
  local gomips=""
  local suffix=""
  local ext=""
  local buildmode="default"
  local cgo_enabled="0"
  local cc=""
  local cxx=""

  IFS="/" read -r goos goarch suffix <<< "${target}"
  if [[ -z "${goos}" || -z "${goarch}" ]]; then
    echo "Invalid target: ${target}" >&2
    return 1
  fi

  local label="${goos}-${goarch}"
  if [[ -n "${suffix:-}" ]]; then
    label="${label}-${suffix}"
  fi

  if [[ "${goarch}" == "arm" && "${suffix:-}" == v7 ]]; then
    goarm="7"
  fi

  if [[ "${goarch}" == "mips" || "${goarch}" == "mipsle" ]]; then
    if [[ "${suffix:-}" != "softfloat" ]]; then
      echo "MIPS target must include softfloat suffix: ${target}" >&2
      return 1
    fi
    gomips="softfloat"
  fi

  if [[ "${goos}" == "windows" ]]; then
    ext=".exe"
  fi

  if [[ "${goos}" == "android" ]]; then
    buildmode="pie"
    cgo_enabled="1"
    local sdk_root="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
    local ndk_version="${ANDROID_NDK_VERSION:-26.3.11579264}"
    local ndk_root="${ANDROID_NDK_HOME:-$sdk_root/ndk/$ndk_version}"
    local host_tag="linux-x86_64"
    local toolchain="$ndk_root/toolchains/llvm/prebuilt/$host_tag/bin"

    if [[ ! -d "$toolchain" ]]; then
      echo "Android NDK toolchain not found: $toolchain" >&2
      return 1
    fi

    case "${goarch}" in
      amd64)
        cc="$toolchain/x86_64-linux-android24-clang"
        cxx="$toolchain/x86_64-linux-android24-clang++"
        ;;
      arm64)
        cc="$toolchain/aarch64-linux-android24-clang"
        cxx="$toolchain/aarch64-linux-android24-clang++"
        ;;
      arm)
        if [[ "${goarm}" != "7" ]]; then
          echo "Unsupported Android ARM target: ${target}" >&2
          return 1
        fi
        cc="$toolchain/armv7a-linux-androideabi24-clang"
        cxx="$toolchain/armv7a-linux-androideabi24-clang++"
        ;;
      *)
        echo "Unsupported Android target: ${target}" >&2
        return 1
        ;;
    esac
  fi

  local outfile="${DIST_DIR}/tg-ws-relay-${label}${ext}"
  echo "==> Building ${label}"
  (
    cd "${SCRIPT_DIR}"
    if [[ "${buildmode}" == "pie" ]]; then
      env \
        CGO_ENABLED="${cgo_enabled}" \
        GOOS="${goos}" \
        GOARCH="${goarch}" \
        GOARM="${goarm}" \
        GOMIPS="${gomips}" \
        TMPDIR="${TMPDIR:-/tmp}" \
        TMP="${TMP:-/tmp}" \
        TEMP="${TEMP:-/tmp}" \
        CC="${cc}" \
        CXX="${cxx}" \
        go build -buildmode=pie -trimpath -ldflags="-s -w" \
        -o "${outfile}" .
    else
      env \
        CGO_ENABLED="${cgo_enabled}" \
        GOOS="${goos}" \
        GOARCH="${goarch}" \
        GOARM="${goarm}" \
        GOMIPS="${gomips}" \
        TMPDIR="${TMPDIR:-/tmp}" \
        TMP="${TMP:-/tmp}" \
        TEMP="${TEMP:-/tmp}" \
        CC="${cc}" \
        CXX="${cxx}" \
        go build -trimpath -ldflags="-s -w" -o "${outfile}" .
    fi
  )
}

for target in "${TARGETS[@]}"; do
  build_target "${target}"
done

echo
echo "Built relay artifacts:"
find "${DIST_DIR}" -maxdepth 1 -type f -printf '  %f\n' | sort
