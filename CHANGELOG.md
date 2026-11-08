# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.0] - 2026-11-09

First public version, extracted from the setup hotspot that runs on the
[Buzz Party](https://github.com/nivobi/buzz-party) console PC.

### Added

- `driver/wl_linux-softap.patch` for `wl_linux.c` (broadcom-wl 6.30.223.271):
  - the kernel 5.15+ fix for private `wl` ioctls (`ndo_siocdevprivate`),
  - AP-like beacons from the ad-hoc firmware (`buzz_fake_ess`),
  - no deauth/disassoc kicks (`buzz_block_kick`),
  - frame send (`0x7B00`, `0x7B01`) and last-beacon (`0x7B02`) ioctls;
    both send commands refuse beacons and probe responses.
- `driver/build-wl.sh`: checks the blob's SHA-256, `objcopy`, patch, dkms build.
- `bcmsoftap`: the user-space hotspot (`softap`), frames, power-save buffering
  (`psbuf`), the driver commands (`wl`), and a demo with an "It works" page.
- The findings: how it works, the rules that keep the PC from freezing, limits.

Tested with an iPhone on an ASUS PCE-AC68 (kernel 7.2.14, Arch). The demo
script itself is new and not yet run on the card; the hotspot code it uses is.

[Unreleased]: https://github.com/nivobi/bcm4360-softap/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nivobi/bcm4360-softap/releases/tag/v0.1.0
