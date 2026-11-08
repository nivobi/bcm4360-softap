"""Start an open hotspot, show every phone that joins a small page, then stop.

    sudo python3 -m bcmsoftap.demo [--ifname wlp4s0] [--ssid Setup] [--channel 6] [--seconds 120]

Needs the patched driver (driver/build-wl.sh), dnsmasq, and root. The card is
taken away from NetworkManager while the hotspot runs and handed back after,
so WiFi client mode is gone meanwhile: run it over Ethernet or at the machine.
"""
import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .softap import GATEWAY, SoftAp
from .wl import Wl

PAGE = b"""<!doctype html><meta name="viewport" content="width=device-width">
<title>bcm4360-softap</title>
<body style="font:20px system-ui;margin:2em">
<h1>It works</h1><p>This page comes from the hotspot on a Broadcom BCM4360.</p>
"""


class Page(BaseHTTPRequestHandler):
    """Answers every request with the page, so phones show it as a captive portal."""

    def do_GET(self):
        print(time.strftime("%H:%M:%S"), "page", self.headers.get("Host", "?"), self.path[:60], flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *a):
        pass


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--ifname", default="wlp4s0")
    a.add_argument("--ssid", default="Setup")
    a.add_argument("--channel", type=int, default=6, help="2.4 GHz channel (1-13)")
    a.add_argument("--seconds", type=float, default=120)
    o = a.parse_args()

    ap = SoftAp(Wl(o.ifname), ssid=o.ssid)
    ap.start(o.channel)
    srv = ThreadingHTTPServer((GATEWAY, 80), Page)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"hotspot '{o.ssid}' up on channel {o.channel}; join it from a phone", flush=True)
    try:
        end = time.time() + o.seconds
        while time.time() < end:
            time.sleep(5)
            print(time.strftime("%H:%M:%S"), "stations:", [s.hex(":") for s in ap.stations] or "none", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()
        srv.server_close()
        ap.stop()  # reloads wl and hands the card back to NetworkManager
        print("stopped", flush=True)


if __name__ == "__main__":
    main()
