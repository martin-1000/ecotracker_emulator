import http.server
import json
import urllib.request
import time
import socket
from zeroconf import IPVersion, ServiceInfo, Zeroconf

# --- KONFIGURATION ---
SHELLY_IP = "192.168.178.97"  # <-- IP deines Shelly Pro 3EM anpassen
LISTEN_PORT = 80

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_shelly_power():
    try:
        url = f"http://{SHELLY_IP}/rpc/Shelly.GetStatus"
        req = urllib.request.Request(url, headers={'User-Agent': 'EcoTrackerBridge'})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            em0 = data.get("em:0", {})
            emdata0 = data.get("emdata:0", {})

            p1 = em0.get("a_act_power", 0.0)
            p2 = em0.get("b_act_power", 0.0)
            p3 = em0.get("c_act_power", 0.0)
            total = em0.get("total_act_power", p1 + p2 + p3)

            # Energiewerte in Wattstunden (Wh)
            energy_in = emdata0.get("total_act", 100000.0)
            energy_out = emdata0.get("total_act_ret", 0.0)

            return total, p1, p2, p3, energy_in, energy_out
    except Exception as e:
        return 0.0, 0.0, 0.0, 0.0, 100000.0, 0.0

class EcoTrackerHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Verhindert hässliche WinError-10054-Tracebacks beim Schließen von Handy-Verbindungen
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def do_GET(self):
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        total, p1, p2, p3, e_in, e_out = get_shelly_power()
        
        # Vollständige EcoTracker-Payload inklusive Energiezähler
        payload = {
            "power": round(total, 1),
            "powerAvg": round(total, 1),
            "agePower": 0,
            "energyCounterIn": round(e_in, 1),
            "energyCounterOut": round(e_out, 1),
            "powerPhase1": round(p1, 1),
            "powerPhase2": round(p2, 1),
            "powerPhase3": round(p3, 1),
            "serverTime": int(time.time())
        }
        body = json.dumps(payload).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[{self.date_time_string()}] Client: {self.client_address[0]} -> {format % args}")

def register_mdns(local_ip):
    # Hardware-nahe Konfiguration gemäß everHome EcoTracker Spezifikation
    mac_clean = "b43a45112233"  # B4:3A:45 ist die offizielle everHome OUI
    service_name = f"ecotracker-{mac_clean}._everhome._tcp.local."
    server_host = f"ecotracker-{mac_clean}.local."

    desc = {
        'serial': '293d45273261',
        'productid': '1137',      # Exakte Product-ID des originalen EcoTracker
        'ip': local_ip
    }

    info = ServiceInfo(
        "_everhome._tcp.local.",
        service_name,
        addresses=[socket.inet_aton(local_ip)],
        port=LISTEN_PORT,
        properties=desc,
        server=server_host,
    )

    zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
    zeroconf.register_service(info)
    print(f"mDNS Service '{service_name}' registriert auf {local_ip}:{LISTEN_PORT}")
    return zeroconf, info

if __name__ == "__main__":
    local_ip = get_local_ip()
    print(f"Ermittelte Windows-IP: {local_ip}")
    
    zc, s_info = register_mdns(local_ip)

    try:
        # Multi-Threaded Server: Parallele Anfragen blockieren sich nicht mehr
        with http.server.ThreadingHTTPServer(("", LISTEN_PORT), EcoTrackerHandler) as httpd:
            print(f"EcoTracker Emulator läuft parallelisiert auf Port {LISTEN_PORT}...")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBeende Emulator...")
    finally:
        zc.unregister_service(s_info)
        zc.close()