#!/usr/bin/env python3
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    haproxy = shutil.which("haproxy")
    if not haproxy:
        raise SystemExit("haproxy is required for the service proxy smoke test")
    backend_port, http_port, raw_port = free_port(), free_port(), free_port()
    observations = []
    ready = threading.Event()

    def backend():
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", backend_port))
            listener.listen()
            listener.settimeout(5)
            ready.set()
            while len(observations) < 2:
                connection, peer = listener.accept()
                with connection:
                    payload = connection.recv(4096)
                    if not payload:
                        continue
                    observations.append((peer[0], payload))
                    if payload.startswith(b"GET "):
                        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                    else:
                        connection.sendall(b"ack")

    thread = threading.Thread(target=backend, daemon=True)
    thread.start()
    if not ready.wait(2):
        raise SystemExit("backend did not start")
    config = f"""global
  maxconn 32

defaults
  mode tcp
  timeout connect 1s
  timeout client 2s
  timeout server 2s

frontend http_input
  bind 127.0.0.1:{http_port}
  default_backend normalized

frontend raw_input
  bind 127.0.0.1:{raw_port}
  default_backend normalized

backend normalized
  server service 127.0.0.1:{backend_port}
"""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "haproxy.cfg"
        path.write_text(config, encoding="utf-8")
        subprocess.run([haproxy, "-c", "-f", str(path)], check=True, stdout=subprocess.DEVNULL)
        process = subprocess.Popen([haproxy, "-db", "-f", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(40):
                if process.poll() is not None:
                    raise SystemExit(process.stderr.read().decode("utf-8", "replace"))
                try:
                    with socket.create_connection(("127.0.0.1", http_port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise SystemExit("haproxy did not accept traffic")
            http = b"GET /healthz HTTP/1.1\r\nHost: service\r\nConnection: close\r\n\r\n"
            with socket.create_connection(("127.0.0.1", http_port), timeout=2) as client:
                client.sendall(http)
                if b"200 OK" not in client.recv(4096):
                    raise SystemExit("HTTP-shaped TCP flow failed")
            raw = b"\x00\x0bCBOR-FRAME"
            with socket.create_connection(("127.0.0.1", raw_port), timeout=2) as client:
                client.sendall(raw)
                if client.recv(3) != b"ack":
                    raise SystemExit("raw TCP flow failed")
            thread.join(3)
            if thread.is_alive() or observations != [("127.0.0.1", http), ("127.0.0.1", raw)]:
                raise SystemExit(f"source normalization or payload transparency failed: {observations!r}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    print("HTTP and raw TCP reach services through the same normalized source without payload metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
