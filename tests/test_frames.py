import struct
import unittest

from bcmsoftap import frames

SNAP = b"\xaa\xaa\x03\x00\x00\x00"
PHONE = bytes.fromhex("4257b7ec1160")
BSSID = bytes.fromhex("1c872cb6bb75")
TAP = bytes.fromhex("02872cb6bb75")


def ie(i, data):
    return bytes([i, len(data)]) + data


def radiotap(frame):
    return bytes([0, 0]) + struct.pack("<H", 8) + b"\0" * 4 + frame


class FramesTest(unittest.TestCase):
    def test_parse_ies_stops_at_truncated(self):
        data = ie(0, b"abc") + ie(1, b"\x82\x84") + bytes([45, 26, 1, 2])
        self.assertEqual(frames.parse_ies(data), [(0, b"abc"), (1, b"\x82\x84")])

    def test_assoc_ies_keep_ht_and_vendor_drop_ssid_tim_ds(self):
        ids = [0, 1, 3, 5, 42, 47, 50, 45, 61, 127, 221, 221]
        body = b"\0" * 8 + struct.pack("<HH", 100, 0x0001) + b"".join(ie(i, bytes([i])) for i in ids)
        cap, ies = frames.assoc_ies_from_beacon(body)
        self.assertEqual([i for i, _ in frames.parse_ies(ies)], [1, 50, 45, 61, 127, 221, 221])

    def test_assoc_cap_sets_ess_clears_ibss(self):
        body = b"\0" * 8 + struct.pack("<HH", 100, 0x0422) + ie(1, b"\x82")
        cap, _ = frames.assoc_ies_from_beacon(body)
        self.assertEqual(cap, 0x0421)

    def test_assoc_response_aid(self):
        body = frames.assoc_response(0x0001, ie(1, b"\x82"))
        self.assertEqual(body[0:2], b"\x01\x00")
        self.assertEqual(body[2:4], b"\x00\x00")
        self.assertEqual(body[4:6], b"\x01\xc0")
        self.assertEqual(body[6:], ie(1, b"\x82"))

    def test_auth_response_is_open_seq2_ok(self):
        self.assertEqual(frames.auth_response(), struct.pack("<HHH", 0, 2, 0))

    def test_parse_radiotap_qos_header(self):
        hdr = bytes([0x88, 0x01]) + b"\0\0" + BSSID + PHONE + TAP + b"\x10\x00" + b"\x00\x00"
        f = frames.parse_radiotap(radiotap(hdr + SNAP + b"\x08\x00" + b"payload"))
        self.assertEqual((f.fc, f.flags, f.a1, f.a2, f.a3), (0x88, 0x01, BSSID, PHONE, TAP))
        self.assertEqual(f.seq, 1)
        self.assertEqual(f.body, SNAP + b"\x08\x00payload")

    def test_parse_radiotap_too_short(self):
        self.assertIsNone(frames.parse_radiotap(radiotap(b"\x48\x01" + b"\0" * 10)))

    def test_data_to_ether_roundtrip(self):
        ether = TAP + PHONE + b"\x08\x00" + b"hello ip"
        dst, src, body = frames.ether_to_data(ether)
        self.assertEqual((dst, src), (TAP, PHONE))
        hdr = bytes([0x08, 0x01]) + b"\0\0" + BSSID + PHONE + TAP + b"\0\0"
        f = frames.parse_radiotap(radiotap(hdr + body))
        self.assertEqual(frames.data_to_ether(f), ether)

    def test_null_frame_gives_none(self):
        hdr = bytes([0x48, 0x11]) + b"\0\0" + BSSID + PHONE + BSSID + b"\0\0"
        self.assertIsNone(frames.data_to_ether(frames.parse_radiotap(radiotap(hdr))))

    def test_from_ds_data_is_not_to_ap(self):
        hdr = bytes([0x08, 0x02]) + b"\0\0" + PHONE + BSSID + TAP + b"\0\0"
        f = frames.parse_radiotap(radiotap(hdr + SNAP + b"\x08\x00x"))
        self.assertIsNone(frames.data_to_ether(f))


if __name__ == "__main__":
    unittest.main()
