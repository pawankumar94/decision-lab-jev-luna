"""Build film/data.json from summary.json and saved traces. Every on-screen number comes from here."""
import json
import statistics

from client import ROOT

S = json.loads((ROOT / "results/summary.json").read_text())
COLORS = {"jev-1.13.0": "#ef1760", "gpt-6-luna-none": "#4f63d8", "gpt-6-luna-medium": "#8a3ffc",
    "breadth_first_search_replanning": "#137f79", "manhattan_greedy": "#8a949b", "keyword_rules": "#8a949b",
    "multinomial_naive_bayes": "#a9b1b6", "tfidf_nearest_neighbor": "#c3c9cc", "always_escalate": "#c3c9cc"}
NAMES = {"jev-1.13.0": "Jev", "gpt-6-luna-none": "Luna · no reasoning", "gpt-6-luna-medium": "Luna · reasoning",
    "breadth_first_search_replanning": "BFS planner", "manhattan_greedy": "Greedy rule", "keyword_rules": "Keyword rules",
    "multinomial_naive_bayes": "Naive Bayes", "tfidf_nearest_neighbor": "TF-IDF kNN", "always_escalate": "Always escalate"}
SHORT = {**NAMES, "gpt-6-luna-none": "Luna (none)", "gpt-6-luna-medium": "Luna (medium)"}
MODELS = ["jev-1.13.0", "gpt-6-luna-none", "gpt-6-luna-medium"]
EPISODE = "door_closure-1"


def jsonl(name):
    path = ROOT / "results" / name
    return [json.loads(s) for s in path.read_text().splitlines()] if path.exists() else []


def compact(record):
    return {"episode": record["episode"], "outcome": record["outcome"], "completed": record["completed"],
        "trace": [{"state": {"position": t["state"]["position"], "map": t["state"]["map_rows_y_0_to_6"], "door": t["state"]["door_update_applied"]},
            "after": t["position_after"], "action": t["action"], "confidence": t["confidence"]} for t in record["trace"]]}


def nav():
    records = {(r["method"], r["episode_id"]): r for r in jsonl("warehouse.jsonl") + jsonl("llm-warehouse.jsonl")}
    boards = []
    for key, method, sub, signal in [("jev", "jev-1.13.0", "Decision model · typed choice", "Confidence"),
            ("none", "gpt-6-luna-none", "General LLM · effort none", "Self-reported"),
            ("medium", "gpt-6-luna-medium", "General LLM · effort medium", "Self-reported"),
            ("bfs", "breadth_first_search_replanning", "Plain code · replans each step", "Confidence")]:
        boards.append({"key": key, "name": NAMES[method], "sub": sub, "signal": signal, "color": COLORS[method], "record": compact(records[(method, EPISODE)])})
    fine = ("Recorded replay of saved responses for the closing-aisle world. Models receive the map as text, not images. "
        "Motion is interpolated for readability; it does not reproduce API latency. No physical robot.")
    # Camera on the open side of the closing aisle so looping robots are not hidden behind shelves.
    return {"episode": EPISODE, "boards": boards, "fine": fine, "cam": [-12, 12, 10]}


def navres():
    W = S["warehouse"]
    rows = []
    for method in ["breadth_first_search_replanning", "gpt-6-luna-medium", "jev-1.13.0", "gpt-6-luna-none", "manhattan_greedy"]:
        w = W[method]
        detail = "plain code"
        if method in MODELS:
            lat = w["median_action_latency_seconds"]
            detail = f"{lat:.2f}s per move · ${w['estimated_api_usd'] / w['n'] * 1000:.2f} per 1k worlds"
        rows.append({"name": NAMES[method], "color": COLORS[method], "completed": w["completed"], "n": w["n"], "detail": detail})
    return {"rows": rows}


def gate_label(choice, confidence, gold, threshold):
    if choice == "escalate" or threshold is None or confidence < threshold:
        return "human"
    return "auto" if choice == gold else "wrong"


def hybrid(pick):
    cases = {c["id"]: c for c in json.loads((ROOT / "incidents/cases.json").read_text())}
    rows = {(r["method"], r["id"]): r for r in jsonl("jev-incidents.jsonl") + jsonl("llm-incidents.jsonl") + json.loads((ROOT / "results/incidents-local.json").read_text())}
    visual = {"person_in_lane": "person", "unidentified_object": "crate", "sensor_conflict": "sensor", "spill_cleanup": "spill",
        "fallen_pallet": "crate", "scheduled_maintenance": "crate"}
    out = []
    for case_id in pick:
        c = cases[case_id]
        models = []
        for m in MODELS:
            p = rows[(m, case_id)]["prediction"]
            thr = S["incidents"]["methods"][m]["gate"]["selected_threshold"]
            models.append({"name": SHORT[m], "color": COLORS[m], "choice": p["choice"], "confidence": p["confidence"], "gate": gate_label(p["choice"], p["confidence"], c["label"], thr)})
        rule = rows[("keyword_rules", case_id)]["prediction"]["choice"]
        models.append({"name": "Keyword rules", "color": COLORS["keyword_rules"], "choice": rule, "confidence": None, "gate": gate_label(rule, 1, c["label"], 0)})
        out.append({"id": case_id, "text": c["text"], "gold": c["label"], "behavior": c["label"], "visual": visual[c["hidden"]["kind"]],
            "split_label": "not seen when thresholds were chosen", "models": models})
    return out


def end_stats():
    led = jsonl("api-ledger.jsonl"); llm = jsonl("llm-ledger.jsonl")
    calls = len(led) + len(llm)
    usd = sum(x.get("input_tokens", 0) for x in led) * 0.042 / 1e6 + sum(v["estimated_usd"] for v in S["llm_accounting"].values())
    return [{"value": f"{calls:,}", "label": "real API calls"}, {"value": "3", "label": "small tests"}, {"value": f"${usd:.2f}", "label": "estimated total spend"}]


def build(pick, text):
    R, I = S["routing"], S["incidents"]["methods"]
    routing_rows = [{"name": SHORT[m], "color": COLORS[m], "value": R[m]["test_accuracy"] * 100, "label": f"{R[m]['test_correct']}/240"}
        for m in MODELS + ["multinomial_naive_bayes", "tfidf_nearest_neighbor"]]
    gate_rows = []
    for m in MODELS:
        g = R[m]["gates"]["confidence"]["selected_test"]
        gate_rows.append({"name": SHORT[m], "color": COLORS[m], "value": (g["coverage"] * 100) if g else 0,
            "label": f"{g['accepted']} · {g['errors_accepted']} err" if g else "no gate"})
    messy_rows = [{"name": SHORT[m], "color": COLORS[m], "value": I[m]["messy"]["correct"], "label": f"{I[m]['messy']['correct']}/60"}
        for m in MODELS + ["keyword_rules", "always_escalate"]]
    data = {
        "title": text["title"], "nav": nav(), "navres": {**navres(), **text["navres"]},
        "hybrid": {"incidents": hybrid(pick), "fine": text["hybrid_fine"]},
        "results": {"title": text["results_title"], "fine": text["results_fine"], "panels": [
            {"h": "Routing 240 bank messages", "q": "Correct intent on held-out Banking77 test messages", "rows": routing_rows, "max": 100, "foot": text["foot_routing"]},
            {"h": "Confidence gate", "q": "Messages automated at the threshold chosen on dev; errors among them", "rows": gate_rows, "max": 100, "foot": text["foot_gate"]},
            {"h": "60 hand-written incident notes", "q": "Correct wait / reroute / escalate under the stated policy", "rows": messy_rows, "max": 60, "foot": text["foot_messy"]},
        ]},
        "end": {**text["end"], "stats": end_stats()},
    }
    (ROOT / "film/data.json").write_text(json.dumps(data, indent=1) + "\n")
    return data


if __name__ == "__main__":
    import sys
    spec = json.loads((ROOT / "film/script.json").read_text())
    build(spec["pick"], spec["text"])
    print("film/data.json written")
