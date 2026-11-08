"""An open WiFi hotspot on a Broadcom card with the patched wl driver.

The card runs an ad-hoc (IBSS) network whose BSSID is its own MAC; the patched
driver makes its beacons look like an access point's. Phones then try to join
it like any access point, and this module answers them from user space:
authentication and association replies sent through the driver, and the data
path through a TAP device (`softap0`, 10.42.0.1/24) with dnsmasq handing out
addresses and answering every name with the gateway (captive portal style).
"""
import fcntl
import os
import select
import socket
import struct
import subprocess
import threading
import time

from . import frames
from .psbuf import PsBuffer
from .wl import Wl

TAP_NAME = "softap0"
GATEWAY = "10.42.0.1"
TUNSETIFF, IFF_TAP, IFF_NO_PI = 0x400454CA, 0x0002, 0x1000
RUN_DIR = "/run/bcm4360-softap"


class CardStuck(Exception):
    """Stopping the hotspot failed and the card is in an unknown state. Reload
    the driver (the `wl` module) once the radiotap interface is gone."""


def _log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def _ip(*args: str) -> None:
    subprocess.run(["ip", *args], check=False, capture_output=True)


def _nm_managed(ifname: str, on: bool) -> None:
    """Hand the card to NetworkManager, or take it away (no-op without nmcli)."""
    try:
        subprocess.run(["nmcli", "device", "set", ifname, "managed", "yes" if on else "no"],
                       check=False, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


class SoftAp:
    def __init__(self, wl: Wl, ssid: str = "Setup"):
        self.wl = wl
        self.ssid = ssid
        self.running = False
        self.last_activity: "float | None" = None
        self._thread: "threading.Thread | None" = None
        self._dns: "subprocess.Popen | None" = None
        self._tap: "int | None" = None
        self._raw: "socket.socket | None" = None
        self.stations: set[bytes] = set()
        self._pm: dict[bytes, bool] = {}
        self._diag_left: dict[bytes, int] = {}
        self._tx: dict[bytes, int] = {}
        self._ps = PsBuffer(lambda sta, fr: self.wl.send(*fr))

    def start(self, channel: int) -> None:
        if self.running:
            return
        try:
            self._start(channel)
        except Exception as e:
            # Half started: undo it all and give the card back.
            # If even that fails, _teardown raises CardStuck.
            _log("hotspot start failed:", repr(e), "- tearing down")
            self._teardown()
            raise

    def _start(self, channel: int) -> None:
        _nm_managed(self.wl.ifname, False)
        time.sleep(1)
        self.wl.set_param("buzz_fake_ess", 1)
        self.wl.set_param("buzz_block_kick", 1)
        self.wl.start_ibss(self.ssid, channel)
        time.sleep(1)
        self.bssid = self.wl.mac
        bcn = self.wl.last_beacon()
        self.cap, self.ies = frames.assoc_ies_from_beacon(bcn) if len(bcn) > 12 else (0x0001, b"")
        mon = self.wl.monitor(True)
        self._raw = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
        self._raw.bind((mon, 0))
        _ip("link", "set", mon, "up")
        self._tap = os.open("/dev/net/tun", os.O_RDWR)
        fcntl.ioctl(self._tap, TUNSETIFF, struct.pack("16sH", TAP_NAME.encode(), IFF_TAP | IFF_NO_PI))
        self.tap_mac = bytes([0x02]) + self.bssid[1:]
        _ip("link", "set", TAP_NAME, "address", self.tap_mac.hex(":"))
        _ip("addr", "flush", "dev", TAP_NAME)
        _ip("addr", "add", f"{GATEWAY}/24", "dev", TAP_NAME)
        _ip("link", "set", TAP_NAME, "up")
        os.makedirs(RUN_DIR, exist_ok=True)
        self._dns = subprocess.Popen(
            ["dnsmasq", "--no-daemon", f"--interface={TAP_NAME}", "--bind-interfaces", "--except-interface=lo",
             "--dhcp-range=10.42.0.10,10.42.0.50,255.255.255.0,10m", f"--dhcp-option=3,{GATEWAY}",
             f"--dhcp-option=6,{GATEWAY}", f"--address=/#/{GATEWAY}", "--no-resolv", "--dhcp-authoritative",
             f"--dhcp-leasefile={RUN_DIR}/leases", "--pid-file="],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.stations = set()
        self.running = True
        self._thread = threading.Thread(target=self._loop, name="softap", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self._teardown()

    def _teardown(self) -> None:
        """Undo everything start did, each step on its own so one failure does
        not skip the rest. Raises CardStuck if any step failed."""
        self.running = False
        errors = []

        def attempt(what, fn, *a):
            try:
                fn(*a)
            except Exception as e:
                _log("teardown:", what, "failed:", repr(e))
                errors.append(e)

        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        if self._dns:
            dns = self._dns
            def stop_dns():
                dns.terminate()
                try:
                    dns.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    dns.kill()
            attempt("dnsmasq", stop_dns)
        if self._tap is not None:
            attempt("tap", os.close, self._tap)
        if self._raw:
            attempt("raw socket", self._raw.close)
        self._tap = self._raw = self._dns = None
        attempt("monitor off", self.wl.monitor, False)
        attempt("driver reload", self.wl.stop)
        attempt("fake_ess off", self.wl.set_param, "buzz_fake_ess", 0)
        attempt("block_kick off", self.wl.set_param, "buzz_block_kick", 0)
        attempt("managed", _nm_managed, self.wl.ifname, True)
        if errors:
            raise CardStuck(f"{len(errors)} teardown step(s) failed, first: {errors[0]!r}") from errors[0]

    # --- the radio loop ---

    def _loop(self) -> None:
        seen: dict[bytes, tuple[int, int]] = {}
        while self.running:
            try:
                r, _, _ = select.select([self._raw, self._tap], [], [], 0.5)
            except (OSError, ValueError):
                return
            try:
                if self._raw in r:
                    self._radio(self._raw.recv(4096), seen)
                if self._tap in r:
                    self._from_tap(os.read(self._tap, 2048))
            except OSError:
                continue

    def _radio(self, pkt: bytes, seen: dict) -> None:
        f = frames.parse_radiotap(pkt)
        if f is None or f.a1 != self.bssid:
            return
        if f.flags & 0x08 and seen.get(f.a2) == (f.fc, f.seq):
            return  # a retry of something already handled
        seen[f.a2] = (f.fc, f.seq)
        self._diag(f)
        if f.a2 in self.stations:
            if f.fc == 0xA4:
                self._ps.ps_poll(f.a2)
                return
            self._ps.power(f.a2, sleeping=bool(f.flags & 0x10))
        if f.fc == 0xB0 and f.body[:4] == struct.pack("<HH", 0, 1):
            self.last_activity = time.monotonic()
            _log("phone auth", f.a2.hex(":"))
            self.wl.send(0xB0, f.a2, self.bssid, self.bssid, frames.auth_response())
        elif f.fc in (0x00, 0x20):
            self.last_activity = time.monotonic()
            self.wl.send(0x10 if f.fc == 0x00 else 0x30, f.a2, self.bssid, self.bssid,
                         frames.assoc_response(self.cap, self.ies))
            self.stations.add(f.a2)
            self._pm[f.a2], self._diag_left[f.a2], self._tx[f.a2] = False, 40, 0
            self._ps.forget(f.a2)
            _log("phone assoc", f.a2.hex(":"))
        elif f.fc in (0xA0, 0xC0):
            self.stations.discard(f.a2)
            self._ps.forget(f.a2)
            _log("phone left", f.a2.hex(":"))
        else:
            ether = frames.data_to_ether(f)
            if ether is not None:
                os.write(self._tap, ether)

    def _diag(self, f) -> None:
        """Diagnostics for the slow captive sheet: power-save (PM bit) changes and
        PS-Polls from a phone, with how many frames went to it meanwhile."""
        sta = f.a2
        if sta not in self.stations or self._diag_left.get(sta, 0) <= 0:
            return
        if f.fc == 0xA4:
            self._diag_left[sta] -= 1
            _log("phone ps-poll", sta.hex(":"), "tx", self._tx.get(sta, 0))
            return
        pm = bool(f.flags & 0x10)
        if pm != self._pm.get(sta):
            self._pm[sta] = pm
            self._diag_left[sta] -= 1
            _log("phone sleeps" if pm else "phone awake", sta.hex(":"), "fc %02x" % f.fc, "tx", self._tx.get(sta, 0))

    def _from_tap(self, ether: bytes) -> None:
        dst, src, body = frames.ether_to_data(ether)
        if dst in self.stations:
            self._tx[dst] = self._tx.get(dst, 0) + 1
        # FromDS data: a1 = destination, a2 = BSSID, a3 = source
        if dst in self.stations:
            self._ps.send(dst, (0x0208, dst, self.bssid, src, body))
        elif dst[0] & 1:
            self.wl.send(0x0208, dst, self.bssid, src, body)
