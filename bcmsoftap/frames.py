"""802.11 frame pieces for the soft access point: pure functions, no I/O."""
import struct
from dataclasses import dataclass

SNAP = b"\xaa\xaa\x03\x00\x00\x00"
# Elements an association response repeats from the beacon: rates, extended
# rates, HT capabilities/operation, extended capabilities, VHT, vendor (WMM).
ASSOC_IE_IDS = (1, 50, 45, 61, 127, 191, 192, 221)


def parse_ies(data: bytes) -> list[tuple[int, bytes]]:
    out, i = [], 0
    while i + 2 <= len(data):
        n = data[i + 1]
        if i + 2 + n > len(data):
            break
        out.append((data[i], data[i + 2:i + 2 + n]))
        i += 2 + n
    return out


def assoc_ies_from_beacon(body: bytes) -> tuple[int, bytes]:
    """Capability (ESS on, IBSS off) and the elements to repeat, from a beacon body."""
    cap = struct.unpack("<H", body[10:12])[0]
    cap = (cap & ~0x0002) | 0x0001
    keep = [(i, v) for i, v in parse_ies(body[12:]) if i in ASSOC_IE_IDS]
    return cap, b"".join(bytes([i, len(v)]) + v for i, v in keep)


def auth_response() -> bytes:
    return struct.pack("<HHH", 0, 2, 0)


def assoc_response(cap: int, ies: bytes, aid: int = 1) -> bytes:
    return struct.pack("<HHH", cap, 0, 0xC000 | aid) + ies


@dataclass
class Frame:
    fc: int
    flags: int
    a1: bytes
    a2: bytes
    a3: bytes
    seq: int
    body: bytes


def parse_radiotap(pkt: bytes) -> "Frame | None":
    if len(pkt) < 4:
        return None
    rtlen = struct.unpack("<H", pkt[2:4])[0] if pkt[0] == 0 else 0
    f = pkt[rtlen:]
    if len(f) < 24:
        return None
    fc, flags = f[0], f[1]
    hdr = 26 if (fc & 0x8c) == 0x88 else 24
    return Frame(fc, flags, f[4:10], f[10:16], f[16:22], struct.unpack("<H", f[22:24])[0] >> 4, f[hdr:])


def data_to_ether(f: "Frame | None") -> "bytes | None":
    """A station's data frame to the AP (ToDS) as an Ethernet frame, else None."""
    if f is None or (f.fc >> 2) & 3 != 2 or f.fc & 0x40 or (f.flags & 0x03) != 0x01:
        return None
    if f.body[:6] != SNAP or len(f.body) < 8:
        return None
    return f.a3 + f.a2 + f.body[6:8] + f.body[8:]


def ether_to_data(ether: bytes) -> tuple[bytes, bytes, bytes]:
    """(destination, source, 802.11 data body) for an Ethernet frame."""
    return ether[0:6], ether[6:12], SNAP + ether[12:14] + ether[14:]
