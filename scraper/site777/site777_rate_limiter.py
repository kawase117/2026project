from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class SharedRateLimiter:
    def __init__(self, interval_ms: int) -> None:
        self.interval_seconds = interval_ms / 1000.0
        self.condition = threading.Condition()
        self.next_allowed_at = 0.0
        self.pause_until = 0.0
        self.next_ticket = 0
        self.serving_ticket = 0

    def acquire(self, stream: str) -> dict[str, int | str]:
        started = time.monotonic()
        with self.condition:
            ticket = self.next_ticket
            self.next_ticket += 1
            while True:
                now = time.monotonic()
                allowed_at = max(self.next_allowed_at, self.pause_until)
                if ticket == self.serving_ticket and now >= allowed_at:
                    self.next_allowed_at = now + self.interval_seconds
                    self.serving_ticket += 1
                    self.condition.notify_all()
                    break
                timeout = 0.05 if ticket != self.serving_ticket else max(0.01, allowed_at - now)
                self.condition.wait(timeout=timeout)
        return {
            "stream": stream,
            "waitMs": round((time.monotonic() - started) * 1000),
        }

    def pause(self, pause_ms: int) -> dict[str, int]:
        with self.condition:
            self.pause_until = max(
                self.pause_until,
                time.monotonic() + max(0, pause_ms) / 1000.0,
            )
            self.condition.notify_all()
        return {"pauseMs": max(0, pause_ms)}


def build_handler(limiter: SharedRateLimiter):
    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, status: int, payload: dict[str, object]) -> None:
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/health":
                self._write_json(200, {"ok": True})
                return
            if parsed.path == "/acquire":
                stream = query.get("stream", ["graph"])[0]
                self._write_json(200, limiter.acquire(stream))
                return
            if parsed.path == "/pause":
                try:
                    pause_ms = int(query.get("ms", ["0"])[0])
                except ValueError:
                    self._write_json(400, {"error": "invalid pause"})
                    return
                self._write_json(200, limiter.pause(pause_ms))
                return
            self._write_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Shared Site Seven request limiter.")
    parser.add_argument("--interval-ms", type=int, default=2500)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    if args.interval_ms < 1000:
        raise SystemExit("--interval-ms must be at least 1000")

    limiter = SharedRateLimiter(args.interval_ms)
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        build_handler(limiter),
    )
    args.ready_file.parent.mkdir(parents=True, exist_ok=True)
    args.ready_file.write_text(
        json.dumps(
            {
                "url": f"http://127.0.0.1:{server.server_address[1]}",
                "intervalMs": args.interval_ms,
            },
            ensure_ascii=True,
        ),
        encoding="utf-8",
    )
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
