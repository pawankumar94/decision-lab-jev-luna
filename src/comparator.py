"""General LLM comparators on the frozen routing cases and warehouse episodes.

Same instructions, criteria, cases, and episodes that Jev received. Prompts are frozen in
comparator/protocol.json before any comparator call; runs resume from saved responses.
"""
import argparse
import hashlib
import json

from client import ROOT
from llm_client import ARMS
from world import World, criteria as world_criteria

DIR = ROOT / "comparator"


def load(path):
    return json.loads(path.read_text())


def jsonl(path):
    return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []


def routing_system(protocol):
    lines = "\n".join(f"- {label}: {text}" for label, text in protocol["criteria"].items())
    return (f"{protocol['instructions']}\n\nIntent criteria:\n{lines}\n\n"
        f"Separately answer this question as a probability: {protocol['sufficiency_instructions']}\n\n"
        "The customer message appears inside <customer_message> tags. Return JSON with:\n"
        "- route: exactly one label from the criteria\n"
        "- confidence: integer 0-100, your probability that route is the correct label\n"
        "- enough_information: integer 0-100, your probability that the message contains enough information to route to exactly one intent")


def world_system(world_protocol):
    lines = "\n".join(f"- {action}: {text}" for action, text in world_criteria().items())
    return (f"{world_protocol['instructions']}\n\nActions:\n{lines}\n\n"
        "The current simulator state is JSON inside <state> tags. Return JSON with:\n"
        "- action: exactly one action name\n"
        "- confidence: integer 0-100, your probability that this action is the best next action")


def prepare():
    DIR.mkdir(exist_ok=True)
    protocol, world_protocol = load(ROOT / "protocol.json"), load(ROOT / "world/protocol.json")
    labels = list(protocol["criteria"])
    frozen = {
        "version": 2, "date": "2026-10-07", "arms": ARMS,
        "primary_arm": "gpt-6-luna-none",
        "arm_notes": "gpt-6-luna-none is the like-for-like decision-tier comparison. gpt-6-luna-medium tests whether reasoning changes accuracy, calibration, or navigation. claude-haiku-4-5 runs only if an Anthropic key is supplied (temperature 0). OpenAI arms use the Responses API with strict json_schema output and store=false.",
        "purpose": "General-purpose LLM comparators with structured outputs. Same cases, criteria text, splits, thresholds, and selection rule as Jev.",
        "routing": {"system": routing_system(protocol), "user_template": "<customer_message>\n{text}\n</customer_message>",
            "schema": {"type": "object", "properties": {"route": {"type": "string", "enum": labels}, "confidence": {"type": "integer"}, "enough_information": {"type": "integer"}},
                "required": ["route", "confidence", "enough_information"], "additionalProperties": False}},
        "world": {"system": world_system(world_protocol), "user_template": "<state>\n{state_json}\n</state>",
            "schema": {"type": "object", "properties": {"action": {"type": "string", "enum": list(world_criteria())}, "confidence": {"type": "integer"}},
                "required": ["action", "confidence"], "additionalProperties": False}},
        "signals": "confidence and enough_information are self-reported integers, divided by 100 and clipped to [0, 1]. They are verbalized estimates, not token probabilities, and are not directly comparable with Jev's distribution-derived confidence.",
        "thresholds": protocol["thresholds"], "threshold_selection": protocol["threshold_selection"],
        "budget": {"max_requests": 5000, "max_estimated_usd": 3.00, "note": "Shared across all comparator arms; published list prices in arms."},
        "limitations": [
            "One call per case or action; no self-consistency sampling.",
            "Self-reported confidence: OpenAI documents no logprobs for gpt-6-luna, so confidence is verbalized, unlike Jev's distribution-derived confidence.",
            "Small, cheap models chosen to match Jev's price tier; not a frontier-LLM verdict.",
            "Prompt is a direct translation of Jev's instructions and criteria; no prompt tuning on dev or test.",
            "OpenAI's Decisions API (limited preview) was not tested unless separately noted.",
        ],
    }
    path = DIR / "protocol.json"
    path.write_text(json.dumps(frozen, indent=2) + "\n")
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ["comparator/protocol.json", "protocol.json", "world/protocol.json", "data/dev.json", "data/test.json", "data/challenge.json"]}
    (DIR / "manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print("Frozen comparator protocol and manifest.", flush=True)


def frozen():
    for name, digest in load(DIR / "manifest.json").items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Frozen comparator input changed: " + name)
    return load(DIR / "protocol.json")


def unit(value):
    if not isinstance(value, int) or isinstance(value, bool):
        raise RuntimeError("Non-integer self-reported signal.")
    return min(max(value, 0), 100) / 100


def routing(client):
    spec = frozen()
    output = ROOT / "results/llm-routing.jsonl"
    existing = {r["id"] for r in jsonl(output) if r["method"] == client.arm}
    done = len(existing)
    for split in ["dev", "test", "challenge"]:
        for item in load(ROOT / f"data/{split}.json"):
            if item["id"] in existing:
                continue
            user = spec["routing"]["user_template"].format(text=item["text"])
            answer, response, latency = client.decide(spec["routing"]["system"], user, spec["routing"]["schema"], f"{client.arm}-{item['id']}")
            if answer["route"] not in spec["routing"]["schema"]["properties"]["route"]["enum"]:
                raise RuntimeError("Route outside schema.")
            prediction = {"choice": answer["route"], "confidence": unit(answer["confidence"]), "sufficiency": unit(answer["enough_information"]), "raw": answer}
            record = {"id": item["id"], "split": split, "method": client.arm, "prediction": prediction, "latency_seconds": latency,
                "request": {"system_sha256": hashlib.sha256(spec["routing"]["system"].encode()).hexdigest(), "user": user}, "response": response}
            with output.open("a") as f:
                f.write(json.dumps(record) + "\n")
            done += 1
            if done % 40 == 0:
                print(client.arm, "routing completed", done, "of 396", flush=True)
    print(client.arm, "routing finished.", flush=True)


def world(client):
    spec = frozen()
    episodes = load(ROOT / "world/protocol.json")["episodes"]
    result_path = ROOT / "results/llm-warehouse.jsonl"
    done = {r["episode_id"] for r in jsonl(result_path) if r["method"] == client.arm}
    for episode in episodes:
        if episode["id"] in done:
            continue
        w = World(episode)
        trace, violations, terminal = [], 0, None
        while not terminal:
            state = w.state()
            user = spec["world"]["user_template"].format(state_json=json.dumps(state, indent=1))
            answer, response, latency = client.decide(spec["world"]["system"], user, spec["world"]["schema"], f"{client.arm}-world-{episode['id']}-{len(trace)}")
            action = answer["action"]
            if action not in world_criteria():
                raise RuntimeError("Invalid model action.")
            rejected, terminal = w.step(action)
            violations += bool(rejected)
            trace.append({"step": len(trace), "state": state, "action": action, "position_after": list(w.position), "rejected": rejected, "terminal": terminal,
                "latency_seconds": latency, "confidence": unit(answer["confidence"]), "probabilities": None,
                "usage": response["usage_summary"], "response": response})
        result = {"method": client.arm, "episode_id": episode["id"], "family": episode["family"], "episode": episode,
            "outcome": terminal, "completed": terminal == "completed", "action_count": len(trace),
            "movement_count": sum(t["state"]["position"] != t["position_after"] for t in trace),
            "rejected_actions": violations, "trace": trace}
        with result_path.open("a") as f:
            f.write(json.dumps(result) + "\n")
        print(client.arm, episode["id"], terminal, "actions", len(trace), "rejected", violations, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "routing", "world"])
    parser.add_argument("--arm", choices=list(ARMS))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    else:
        from llm_client import LLMClient
        (routing if args.mode == "routing" else world)(LLMClient(args.arm))
