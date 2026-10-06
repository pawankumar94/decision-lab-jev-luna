"""Pinned TypeSafe API client; credentials live only in process memory."""
import getpass
import hashlib
import json
import os
import pathlib
import subprocess
import time
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent  # repository root
RATE = 0.042 / 1_000_000


def key_from_prompt():
    value = os.environ.get("TYPESAFE_API_KEY") or getpass.getpass("Temporary TypeSafe key (hidden): ")
    if not value or any(c in value for c in "\r\n\x00"):
        raise SystemExit("Invalid credential input; no request made.")
    return value


class JevClient:
    def __init__(self, key, max_requests=1500, max_usd=0.10):
        self.key = key
        self.ledger = ROOT / "results" / "api-ledger.jsonl"
        self.ledger.parent.mkdir(exist_ok=True)
        self.max_requests, self.max_usd = max_requests, max_usd
        self.records = [json.loads(s) for s in self.ledger.read_text().splitlines()] if self.ledger.exists() else []

    def decide(self, payload, request_id):
        # Do not put credentials in arguments, files, raw results, or exception text.
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        conservative_tokens = len(raw.encode("utf-8")) + 2048
        consumed = sum(r.get("input_tokens", r.get("reserved_tokens", 0)) for r in self.records)
        if len(self.records) >= self.max_requests or (consumed + conservative_tokens) * RATE > self.max_usd:
            raise RuntimeError("Predeclared request or estimated cost budget reached.")
        last_error = None
        for attempt in range(3):
            # curl config is piped over stdin. Neither key nor request are in argv.
            def quote(s):
                return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'
            config = '\n'.join([
                'url = "https://api.typesafe.ai/v1/systemone"',
                'request = "POST"',
                'header = ' + quote('Authorization: Bearer ' + self.key),
                'header = "Content-Type: application/json"',
                'data = ' + quote(raw),
            ])
            started = time.perf_counter()
            process = subprocess.run(
                ["curl", "--silent", "--show-error", "--max-time", "40", "--connect-timeout", "15", "--config", "-", "--write-out", "\n%{http_code}"],
                input=config, text=True, capture_output=True, timeout=45,
            )
            elapsed = time.perf_counter() - started
            body, _, status_text = process.stdout.rpartition("\n")
            status = int(status_text) if status_text.isdigit() else 0
            response = None
            try:
                response = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                pass
            record = {
                "request_id": request_id, "attempt": attempt,
                "at_utc": datetime.now(timezone.utc).isoformat(),
                "status": status, "client_latency_seconds": elapsed,
                "request_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            }
            if status == 200 and isinstance(response, dict) and "usage" in response:
                record["input_tokens"] = response["usage"]["input_tokens"]
                record["output_tokens"] = response["usage"].get("output_tokens", 0)
            else:
                record["reserved_tokens"] = conservative_tokens
            with self.ledger.open("a") as f:
                f.write(json.dumps(record) + "\n")
            self.records.append(record)
            if process.returncode == 0 and status == 200:
                if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
                    raise RuntimeError("Unexpected response schema.")
                if response.get("model") != payload["model"]:
                    raise RuntimeError("Pinned model version mismatch.")
                return response, elapsed
            last_error = f"API HTTP {status}; transport exit {process.returncode}"
            if status not in (429, 529, 0) or attempt == 2:
                raise RuntimeError(last_error)
            time.sleep(2 ** attempt)
        raise RuntimeError(last_error)

