"""The patched Broadcom wl driver's private commands (see driver/)."""
import ctypes
import fcntl
import os
import socket
import struct
import subprocess
import time

SIOCDEVPRIVATE = 0x89F0
WLC_UP, WLC_DOWN = 2, 3
WLC_SET_INFRA = 20
WLC_SET_AUTH = 22    # 0 = open system
WLC_SET_WSEC = 134   # 0 = no encryption
WLC_SET_BSSID = 24
WLC_SET_SSID = 26
WLC_SET_CHANNEL = 30
WLC_SET_MONITOR = 108
BUZZ_TX = 0x7B01
BUZZ_LAST_BEACON = 0x7B02
PARAMS = "/sys/module/wl/parameters/"


class _WlIoctl(ctypes.Structure):
    _fields_ = [("cmd", ctypes.c_uint), ("buf", ctypes.c_void_p), ("len", ctypes.c_uint),
                ("set", ctypes.c_uint8), ("used", ctypes.c_uint), ("needed", ctypes.c_uint)]


class _IfReq(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char * 16), ("data", ctypes.c_void_p), ("pad", ctypes.c_char * 16)]


class Wl:
    def __init__(self, ifname: str):
        self.ifname = ifname
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    @property
    def mac(self) -> bytes:
        with open(f"/sys/class/net/{self.ifname}/address") as f:
            return bytes.fromhex(f.read().strip().replace(":", ""))

    def ioctl(self, cmd: int, buf: bytes, set_: bool, size: "int | None" = None) -> bytes:
        size = size or max(len(buf), 4)
        b = ctypes.create_string_buffer(buf, size)
        io = _WlIoctl(cmd, ctypes.cast(b, ctypes.c_void_p), size, 1 if set_ else 0, 0, 0)
        req = _IfReq(self.ifname.encode(), ctypes.cast(ctypes.pointer(io), ctypes.c_void_p), b"")
        fcntl.ioctl(self._sock.fileno(), SIOCDEVPRIVATE, req)
        return b.raw

    def _set_int(self, cmd: int, v: int) -> None:
        self.ioctl(cmd, struct.pack("<i", v), True)

    def set_param(self, name: str, value: int) -> None:
        with open(PARAMS + name, "w") as f:
            f.write(str(value))

    def start_ibss(self, ssid: str, channel: int) -> None:
        """Ad-hoc network whose BSSID is the card's own MAC (so the chip ACKs phones)."""
        s = ssid.encode()
        self._set_int(WLC_DOWN, 1)
        # Open network. The card keeps the last WPA2 join's settings otherwise,
        # and the hotspot shows a lock until something clears them (2026-11-08).
        self._set_int(WLC_SET_WSEC, 0)
        self._set_int(WLC_SET_AUTH, 0)
        self._set_int(WLC_SET_INFRA, 0)
        self._set_int(WLC_UP, 1)
        self._set_int(WLC_SET_CHANNEL, channel)
        self.ioctl(WLC_SET_BSSID, self.mac, True)
        self.ioctl(WLC_SET_SSID, struct.pack("<I", len(s)) + s.ljust(32, b"\0"), True)

    def stop(self) -> None:
        """Back to normal client mode by reloading the driver.
        Switching the live card from IBSS back to infra (down / infra 1 / up)
        froze the whole PC on 2026-11-08; a reload never has. After a reload,
        wpa_supplicant and NetworkManager must restart or the card stays
        'unavailable'."""
        if any(n.startswith("radiotap") for n in os.listdir("/sys/class/net")):
            raise RuntimeError("monitor interface still present; refusing to reload wl (would deadlock)")
        time.sleep(1)
        for cmd in (["ip", "link", "set", self.ifname, "down"], ["modprobe", "-r", "wl"], ["modprobe", "wl"],
                    ["systemctl", "restart", "wpa_supplicant"], ["systemctl", "restart", "NetworkManager"]):
            subprocess.run(cmd, check=False, capture_output=True, timeout=30)
        for _ in range(50):
            if os.path.exists(f"/sys/class/net/{self.ifname}"):
                break
            time.sleep(0.1)
        self._sock.close()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def monitor(self, on: bool) -> "str | None":
        before = set(os.listdir("/sys/class/net"))
        try:
            self._set_int(WLC_SET_MONITOR, 2 if on else 0)
        except OSError:
            pass
        if not on:
            # The driver removes radiotapN in a background task. Reloading the
            # driver before it is gone deadlocks the network core (2026-11-08).
            for _ in range(100):
                if not any(n.startswith("radiotap") for n in os.listdir("/sys/class/net")):
                    break
                time.sleep(0.1)
            return None
        for _ in range(20):
            mons = sorted(n for n in os.listdir("/sys/class/net") if n.startswith("radiotap"))
            if mons:
                return mons[0]
            time.sleep(0.1)
        new = sorted(set(os.listdir("/sys/class/net")) - before)
        return new[0] if new else None

    def send(self, fc: int, a1: bytes, a2: bytes, a3: bytes, body: bytes) -> None:
        if (fc & 0xFC) in (0x80, 0x50):
            raise ValueError("beacons and probe responses are never sent by hand (they hang the PC)")
        self.ioctl(BUZZ_TX, struct.pack("<H", fc) + a1 + a2 + a3 + body, True)

    def last_beacon(self) -> bytes:
        raw = self.ioctl(BUZZ_LAST_BEACON, b"\0" * 1028, False, 1028)
        n = struct.unpack("<i", raw[:4])[0]
        return raw[4:4 + max(0, min(n, 1024))]
