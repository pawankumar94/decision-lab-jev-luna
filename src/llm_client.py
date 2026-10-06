"""General-purpose LLM comparator clients. Credentials come only from the environment and stay in process memory.

Each arm is one provider, model, and setting. All arms share one ledger and one predeclared budget.
"""
import json
import os
import time
from datetime import datetime, timezone

from client import ROOT

ARMS = {
    "gpt-6-luna-none": {"provider": "openai", "model": "gpt-6-luna", "effort": "none", "max_tokens": 512, "usd_per_million": (0.10, 0.50)},
    "gpt-6-luna-medium": {"provider": "openai", "model": "gpt-6-luna", "effort": "medium", "max_tokens": 8000, "usd_per_million": (0.10, 0.50)},
    "claude-haiku-4-5": {"provider": "anthropic", "model": "claude-haiku-4-5", "effort": None, "max_tokens": 256, "usd_per_million": (1.00, 5.00)},
}
KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
LEDGER = ROOT / "results" / "llm-ledger.jsonl"


def available_arms():
    return [arm for arm, spec in ARMS.items() if os.environ.get(KEY_ENV[spec["provider"]])]


def ledger_usd(records):
    return sum((r["input_tokens"] * ARMS[r["arm"]]["usd_per_million"][0] + r["output_tokens"] * ARMS[r["arm"]]["usd_per_million"][1]) / 1e6 for r in records)


class LLMClient:
    def __init__(self, arm, max_requests=5000, max_usd=3.00):
        self.arm, self.spec = arm, ARMS[arm]
        if not os.environ.get(KEY_ENV[self.spec["provider"]]):
            raise SystemExit(f"{KEY_ENV[self.spec['provider']]} is not set; no request made.")
        if self.spec["provider"] == "openai":
            import openai
            self.client = openai.OpenAI(max_retries=4)
        else:
            import anthropic
            self.client = anthropic.Anthropic(max_retries=4)
        LEDGER.parent.mkdir(exist_ok=True)
        self.max_requests, self.max_usd = max_requests, max_usd

    def _records(self):
        return [json.loads(s) for s in LEDGER.read_text().splitlines()] if LEDGER.exists() else []

    def decide(self, system, user, schema, request_id):
        """One structured-output call. Returns (parsed JSON, raw response dict, client latency seconds)."""
        records = self._records()
        if len(records) >= self.max_requests or ledger_usd(records) > self.max_usd:
            raise RuntimeError("Predeclared comparator request or cost budget reached.")
        started = time.perf_counter()
        if self.spec["provider"] == "openai":
            response = self.client.responses.create(
                model=self.spec["model"], instructions=system, input=user, reasoning={"effort": self.spec["effort"]},
                text={"format": {"type": "json_schema", "name": "decision", "schema": schema, "strict": True}},
                max_output_tokens=self.spec["max_tokens"], store=False,
            )
            elapsed = time.perf_counter() - started
            details = response.usage.output_tokens_details
            usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
                "reasoning_tokens": getattr(details, "reasoning_tokens", 0) or 0}
            finished, model_version, provider_id = response.status == "completed", response.model, response.id
            texts = [c.text for item in response.output if item.type == "message" and getattr(item, "phase", None) in (None, "final_answer")
                for c in item.content if c.type == "output_text"]
            text = texts[-1] if texts else None
        else:
            response = self.client.messages.create(
                model=self.spec["model"], max_tokens=self.spec["max_tokens"], temperature=0, system=system,
                messages=[{"role": "user", "content": user}], output_config={"format": {"type": "json_schema", "schema": schema}},
            )
            elapsed = time.perf_counter() - started
            usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens, "reasoning_tokens": 0}
            finished, model_version, provider_id = response.stop_reason == "end_turn", response.model, response._request_id
            text = next((b.text for b in response.content if b.type == "text"), None)
        record = {"arm": self.arm, "request_id": request_id, "at_utc": datetime.now(timezone.utc).isoformat(), "model": model_version,
            "client_latency_seconds": elapsed, **usage, "provider_request_id": provider_id, "finished": finished}
        with LEDGER.open("a") as f:
            f.write(json.dumps(record) + "\n")
        if not finished or text is None:
            raise RuntimeError(f"{self.arm} did not finish cleanly for {request_id}.")
        raw = response.to_dict()
        raw["usage_summary"] = usage
        return json.loads(text), raw, elapsed
