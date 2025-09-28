#!/usr/bin/env python3
"""
Simple HTTP health server for Cloud Run compatibility.
Runs alongside the trading bot to satisfy Cloud Run's HTTP requirement.
This server starts IMMEDIATELY to satisfy Cloud Run's startup probe.
"""

from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sqlite3
from threading import Thread


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()

            # Get basic health info
            health_data = {
                "status": "healthy",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "service": "deltadefi-trading-bot",
                "database": self.check_database(),
                "uptime": self.get_uptime(),
            }

            self.wfile.write(json.dumps(health_data, indent=2).encode())
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def check_database(self):
        """Check if database is accessible"""
        try:
            db_path = os.getenv("SYSTEM__DB_PATH", "trading_bot.db")
            conn = sqlite3.connect(db_path)
            conn.execute("SELECT 1").fetchone()
            conn.close()
            return "accessible"
        except Exception as e:
            return f"error: {e!s}"

    def get_uptime(self):
        """Get system uptime info"""
        try:
            with open("/proc/uptime") as f:
                uptime_seconds = float(f.readline().split()[0])
                return f"{uptime_seconds:.1f}s"
        except:
            return "unknown"

    def log_message(self, format, *args):
        """Suppress default HTTP server logs"""


def start_health_server():
    """Start the health server in a separate thread"""
    port = int(os.getenv("PORT", 8080))

    # Configure server with minimal timeout for faster startup
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.timeout = 1.0  # Short timeout for faster response

    print(f"🏥 Health server starting on port {port}")
    print(f"📍 Health endpoint: http://0.0.0.0:{port}/health")

    # Run server in a separate thread so it doesn't block the main bot
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Verify server is listening
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        result = sock.connect_ex(("0.0.0.0", port))
        if result == 0:
            print(f"✅ Health server confirmed listening on port {port}")
        else:
            print(f"⚠️ Health server may not be ready on port {port}")
    except Exception as e:
        print(f"⚠️ Could not verify health server: {e}")
    finally:
        sock.close()

    return server


if __name__ == "__main__":
    # For testing the health server standalone
    start_health_server()
    try:
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Health server stopped")
