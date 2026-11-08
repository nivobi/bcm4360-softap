# bcm4360-softap

[![CI](https://github.com/nivobi/bcm4360-softap/actions/workflows/ci.yml/badge.svg)](https://github.com/nivobi/bcm4360-softap/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An **open WiFi hotspot on a Broadcom BCM4360 under Linux**, with Broadcom's
closed `wl` driver, which officially only does client mode.

It is a hack: the card runs an ad-hoc network, a small driver patch makes it
look like an access point, and a Python program answers the phones from user
space. Phones (tested: iPhone) join it like any open network, get an address,
and see a page from the computer as a captive portal. Good enough for a setup
hotspot ("join this network, then pick your home WiFi"), which is what it was
built for. It is not a general-purpose access point.

> **Warning.** This drives the chip in ways Broadcom never meant. Two mistakes
> described below **freeze the whole PC** (no oops, no log: power button).
> Work over SSH from another machine, run `sync` before risky steps, and keep
> your own WiFi profile backed up.

## Also useful on its own: the kernel 5.15 fix

Since Linux 5.15 the kernel delivers `SIOCDEVPRIVATE` ioctls to
`ndo_siocdevprivate`, not `ndo_do_ioctl`. The `wl` driver only has the latter,
so **every private `wl` ioctl silently stopped working** (anything that talks
to the driver directly, like the `wl` utility or `WLC_*` commands). The first
hunk of `driver/wl_linux-softap.patch` adds the missing hook. It is safe and
useful without the rest.

## Tested on

| | |
|---|---|
| Card | ASUS PCE-AC68: Broadcom BCM4360 `[14e4:43a0]` |
| Driver | `broadcom-wl-dkms 6.30.223.271` (Arch), blob `wlc_hybrid.o_shipped` sha256 `352a6e349f74c69b78e76f68c63752c99b8f6b22dc942af531b754211d7f4743` |
| Kernel | 7.2.14 (Arch) |
| Userland | Python 3.14, dnsmasq 2.93, NetworkManager |
| Phones | iPhone (iOS). Android not tested yet. |

**The driver patch only fits this exact blob.** `build-wl.sh` checks its
SHA-256 and stops otherwise: the symbol addresses differ in other builds. Other
BCM43xx cards that use the same blob may work; nothing else is tested.

## How it works

1. **Ad-hoc base.** The card starts an IBSS (ad-hoc) network on a 2.4 GHz
   channel, with the BSSID set to its own MAC so the chip acknowledges frames
   sent to it.
2. **Beacons that look like an AP.** The firmware sends the beacons itself.
   The patch overrides the function that builds the beacon body
   (`wlc_bcn_prb_body`): ESS capability instead of IBSS, no IBSS parameter
   set, and a TIM element. Module parameter `buzz_fake_ess`.
3. **No kicking.** In ad-hoc mode the firmware de-authenticates stations it
   doesn't know. The patch blocks `wlc_senddeauth` / `wlc_senddisassoc`
   (module parameter `buzz_block_kick`).
4. **Send any management or data frame.** Private ioctl `0x7B01` hands a frame
   to the firmware's own `wlc_sendmgmt`; `0x7B02` reads the current beacon
   body (to copy its rates and HT information into association replies).
5. **Receive** through the driver's monitor (radiotap) interface.
6. **User space does the rest** (`bcmsoftap/softap.py`): it answers
   authentication and association requests and converts data frames to
   Ethernet and back through a TAP device (`softap0`, 10.42.0.1/24). dnsmasq
   hands out addresses and answers every DNS name with the gateway, so phones
   open the page as a captive portal.
7. **Power save.** Right after joining, iPhones flip their power-management bit
   many times a second while they scan other channels. Frames sent while a
   phone "sleeps" are lost and the phone gives up. `psbuf.py` holds frames
   while a phone sleeps and sends them when it wakes, like a real access point.
   This turned "the page opens on the third or fourth try, after ~40 s" into
   "the page opens on the first join, in 2-7 s".

To make the hidden firmware functions callable and replaceable, `build-wl.sh`
uses `objcopy` on **your own copy** of the blob: it globalizes and weakens a few
symbols and adds aliases for the originals. The original file is left as is.

## Hard-won rules

- **Never send beacons or probe responses by hand** (frame types `0x80`,
  `0x50`). The chip locks up the whole PC. The patched driver refuses them in
  both send commands, and `wl.py` refuses them too.
- **Never switch the live card from ad-hoc back to client mode** (down,
  infra 1, up). That froze the PC too. Stopping the hotspot means **reloading
  the driver** (`modprobe -r wl && modprobe wl`).
- **Wait for the radiotap interface to disappear before reloading.** The
  driver removes it in the background; reloading before that deadlocks the
  network stack.
- **After every reload, restart `wpa_supplicant` and NetworkManager,** or the
  card stays "unavailable". Then NetworkManager's scan list is empty for about
  6 seconds: joining a network in that window fails with "No network with SSID".
- **Turn encryption off before starting the hotspot** (`WLC_SET_WSEC 0`,
  `WLC_SET_AUTH 0`). After a WPA2 join the card keeps those settings, and the
  hotspot then shows a lock for its first seconds.
- **The card can't be hotspot and client at once.** Hotspot first, then a
  driver reload, then join the chosen network.
- Not a hotspot rule, but found on the way: **`wl` never scans the 5 GHz DFS
  channels (52-144) in client mode**, whatever the regulatory domain says. A
  router that only offers those is invisible to this card.

## Security

The hotspot is **open**: anyone in range can join it and reach every service
listening on this PC at `10.42.0.1` (SSH, web servers, ...). It does **not**
route to the internet or your LAN (no forwarding, no NAT). Keep it up only as
long as you need it, or firewall the `softap0` interface down to the ports your
page needs.

## Limits

- **Open network only.** No WPA2: the 4-way handshake isn't implemented.
- Fixed addresses: `10.42.0.1/24` with DHCP from `.10` to `.50`. Change
  `GATEWAY` and the dnsmasq range in `softap.py` if your LAN uses that range.
- Expects systemd, NetworkManager and wpa_supplicant: stopping the hotspot
  reloads `wl` and restarts both.
- One blob version, 2.4 GHz, one radio for either hotspot or client.
- Speed and many stations are untested; it is meant for a setup page.
- Very small frames (under 24 bytes, such as PS-Poll) are dropped by the
  radiotap parser; iPhones wake up with power-management toggles instead, so
  that hasn't mattered.

## Use it

You need root, `objcopy` (binutils), dkms, the `broadcom-wl-dkms` package,
dnsmasq, and Python 3.10 or newer. `build-wl.sh` uses Arch's paths
(`/usr/src/broadcom-wl-6.30.223.271`, `/usr/lib/broadcom-wl-dkms`); on other
distributions (Debian/Ubuntu: `broadcom-sta-dkms`) adjust `SRC`, `LIB` and the
dkms name at the top of the script. Run everything from the repository folder.

```sh
# 1. Build the patched driver (checks the blob, keeps .orig copies of the originals)
sudo bash driver/build-wl.sh
sudo modprobe -r wl && sudo modprobe wl
# An update of the driver package would overwrite the patched source; hold it back,
# e.g. on Arch in /etc/pacman.conf:   IgnorePkg = broadcom-wl-dkms
# (Kernel updates are fine: dkms rebuilds from the patched source.)

# 2. Start a hotspot for two minutes (over SSH or Ethernet: WiFi client mode is off meanwhile)
sudo python3 -m bcmsoftap.demo --ifname wlp4s0 --ssid Setup --channel 6 --seconds 120
```

Join `Setup` from a phone: the "It works" page should open by itself. The
demo then stops the hotspot, reloads the driver and gives the card back to
NetworkManager.

Both module parameters default to `0`, so the patched driver behaves like the
stock one until the hotspot code switches them on. To go back to the stock
driver: restore `Makefile.orig` and `src/wl/sys/wl_linux.c.orig` in
`/usr/src/broadcom-wl-6.30.223.271/` and run `dkms install` again.

## Code

| Path | What |
|---|---|
| `driver/wl_linux-softap.patch` | The patch to `wl_linux.c`: the 5.15 ioctl hook, the beacon and kick overrides, the frame ioctls, the two module parameters |
| `driver/build-wl.sh` | Checks the blob, runs `objcopy`, applies the patch, builds with dkms |
| `bcmsoftap/wl.py` | The driver's private commands from Python (ioctls, module parameters, reload) |
| `bcmsoftap/frames.py` | 802.11 frame parsing and building (radiotap, auth/assoc replies, data to Ethernet) |
| `bcmsoftap/psbuf.py` | Power-save buffering per phone |
| `bcmsoftap/softap.py` | The hotspot: start, the radio loop, stop |
| `bcmsoftap/demo.py` | A small hotspot with an "It works" page |
| `tests/` | Unit tests (`python3 -m unittest`) |

The parameter and ioctl names start with `buzz_` because the hack was built
for [Buzz Party](https://github.com/nivobi/buzz-party), where a console PC
uses it to let the host pick the house WiFi from a phone. They are kept as
they are, so the code here is exactly what was tested.

## Issues and contributions

Reports are welcome, especially "it works / doesn't on card X, distribution Y,
phone Z" and Android results. Other chips and other blob versions are **not
supported**; if you adapt it, a pull request with your findings is the best way
to help the next person. Please report anything security related privately
(the repository's **Security** tab).

## License

The Python code and scripts: [MIT](LICENSE). `driver/wl_linux-softap.patch` is
a patch to Broadcom's `wl_linux.c`, which is under Broadcom's own permissive
notice (kept in that file). This repository contains **no Broadcom binary**:
`build-wl.sh` works on the copy already installed on your machine.

Not affiliated with Broadcom or ASUS.
