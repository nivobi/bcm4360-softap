#!/usr/bin/env bash
# Build the patched Broadcom wl driver (softap support, see README.md).
# Run as root on the machine with the card:  sudo bash driver/build-wl.sh
# It never edits the package's original files in place without a stock copy:
# Makefile.orig / wl_linux.c.orig are the untouched originals.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VER=6.30.223.271
SRC=/usr/src/broadcom-wl-$VER
LIB=/usr/lib/broadcom-wl-dkms
BLOB=$LIB/wlc_hybrid.o_shipped
OUT=$LIB/wlc_hybrid_buzz.o_shipped
WANT_SHA=352a6e349f74c69b78e76f68c63752c99b8f6b22dc942af531b754211d7f4743

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
got=$(sha256sum "$BLOB" | cut -d' ' -f1)
[[ $got == "$WANT_SHA" ]] || { echo "unexpected blob $got: the addresses below only fit $WANT_SHA" >&2; exit 1; }

# 1. Make the hidden core functions callable / replaceable (original blob untouched).
objcopy \
  --globalize-symbol=wlc_frame_get_mgmt --globalize-symbol=wlc_sendmgmt \
  --globalize-symbol=wlc_bcn_prb_body --weaken-symbol=wlc_bcn_prb_body \
  --add-symbol buzz_orig_bcn_prb_body=.text:0x2d81c,global,function \
  --globalize-symbol=wlc_senddeauth --weaken-symbol=wlc_senddeauth \
  --add-symbol buzz_orig_senddeauth=.text:0x4107d,global,function \
  --globalize-symbol=wlc_senddisassoc --weaken-symbol=wlc_senddisassoc \
  --add-symbol buzz_orig_senddisassoc=.text:0x437fd,global,function \
  "$BLOB" "$OUT"

# 2. Fresh copies of the originals, then the Makefile switch and the patch.
for f in Makefile src/wl/sys/wl_linux.c; do
  [[ -s $SRC/$f.orig ]] || cp "$SRC/$f" "$SRC/$f.orig"
  cp "$SRC/$f.orig" "$SRC/$f"
done
sed -i "s|^ldflags-y\( *\):= $BLOB|ldflags-y\1:= $OUT|" "$SRC/Makefile"
grep -q "wlc_hybrid_buzz.o_shipped" "$SRC/Makefile" || { echo "Makefile switch failed" >&2; exit 1; }
# Name the target explicitly: the patch's --- line is the .orig file, never patch that.
patch --forward "$SRC/src/wl/sys/wl_linux.c" < "$HERE/wl_linux-softap.patch"

# 3. Build and install for the running kernel, and make sure it is on disk.
dkms remove broadcom-wl/$VER -k "$(uname -r)" >/dev/null 2>&1 || true
dkms install broadcom-wl/$VER -k "$(uname -r)"
sync
echo "done: reload with  modprobe -r wl && modprobe wl"
