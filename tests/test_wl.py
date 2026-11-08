import struct
import sys
import unittest


@unittest.skipUnless(sys.platform.startswith("linux"), "wl uses fcntl (Linux only)")
class StartIbssTest(unittest.TestCase):
    """Seen 2026-11-08: right after the card had been on a WPA2 network the
    hotspot showed a lock for its first seconds and the iPhone asked for a
    password. The card kept the old encryption settings; start_ibss must
    clear them before the network comes up."""

    def calls(self):
        from bcmsoftap import wl

        class Rec(wl.Wl):
            def __init__(self):
                self.ifname, self.log = "wlp4s0", []

            @property
            def mac(self):
                return b"\x02\x11\x22\x33\x44\x55"

            def ioctl(self, cmd, buf, set_, size=None):
                self.log.append((cmd, buf))
                return buf

        r = Rec()
        r.start_ibss("BuzzParty-Setup", 6)
        return wl, r.log

    def test_open_network_settings_before_up(self):
        wl, log = self.calls()
        cmds = [c for c, _ in log]
        zero = struct.pack("<i", 0)
        for cmd in (wl.WLC_SET_WSEC, wl.WLC_SET_AUTH):
            self.assertIn((cmd, zero), log)
            self.assertLess(cmds.index(cmd), cmds.index(wl.WLC_UP))
        self.assertLess(cmds.index(wl.WLC_DOWN), cmds.index(wl.WLC_SET_WSEC))

    def test_broadcom_command_numbers(self):
        # from the driver's src/include/wlioctl.h
        from bcmsoftap import wl
        self.assertEqual((wl.WLC_SET_AUTH, wl.WLC_SET_WSEC), (22, 134))


if __name__ == "__main__":
    unittest.main()
