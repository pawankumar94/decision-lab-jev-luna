"""Recompute evidence from raw responses; no model calls or headline tuning."""
import collections
import csv
import hashlib
import json
import math
import statistics
from client import ROOT, RATE
from llm_client import ARMS, ledger_usd


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def wilson(k, n):
    if not n:
        return None
    z = 1.959963984540054
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [center - half, center + half]


def quantile(values, p):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * p
    a = int(pos)
    b = min(a + 1, len(values) - 1)
    return values[a] + (values[b] - values[a]) * (pos - a)


def scored(rows, truth, gate=None, threshold=0):
    accepted = [r for r in rows if r["prediction"]["choice"] != "needs_review" and (gate is None or r["prediction"].get(gate, 0) >= threshold)]
    good = sum(r["prediction"]["choice"] == truth[r["id"]]["label"] for r in accepted)
    errors = len(accepted) - good
    return {"total": len(rows), "accepted": len(accepted), "correct_accepted": good, "errors_accepted": errors,
        "coverage": len(accepted) / len(rows) if rows else None,
        "accepted_accuracy": good / len(accepted) if accepted else None,
        "accepted_error_rate": errors / len(accepted) if accepted else None,
        "accepted_error_wilson95": wilson(errors, len(accepted)),
        "correct_automatic_fraction": good / len(rows) if rows else None}


def paired_test(rows_a, rows_b, truth):
    a = {r["id"]: r["prediction"]["choice"] == truth[r["id"]]["label"] for r in rows_a}
    b = {r["id"]: r["prediction"]["choice"] == truth[r["id"]]["label"] for r in rows_b}
    ids = set(a) & set(b)
    a_only = sum(a[i] and not b[i] for i in ids)
    b_only = sum(b[i] and not a[i] for i in ids)
    n = a_only + b_only
    p = min(1, 2 * sum(math.comb(n, i) for i in range(min(a_only, b_only) + 1)) / (2 ** n)) if n else 1
    return {"paired_n": len(ids), "a_only_correct": a_only, "b_only_correct": b_only, "mcnemar_exact_two_sided_p": p,
        "note": "Exploratory comparison on preselected subset; unadjusted for multiple comparisons."}


def llm_usd(arm, usage):
    rate_in, rate_out = ARMS[arm]["usd_per_million"]
    return (usage["input_tokens"] * rate_in + usage["output_tokens"] * rate_out) / 1e6


def gate_outcome(rows, gold, threshold):
    """Hybrid gate: automate wait/reroute only at or above threshold; everything else goes to a human."""
    automated = [r for r in rows if r["prediction"]["choice"] != "escalate" and r["prediction"]["confidence"] >= threshold]
    errors = [r for r in automated if r["prediction"]["choice"] != gold[r["id"]]]
    automatable = sum(gold[r["id"]] != "escalate" for r in rows)
    return {"n": len(rows), "automated": len(automated), "automated_coverage": len(automated) / len(rows) if rows else None,
        "automatable_cases": automatable, "automated_share_of_automatable": len(automated) / automatable if automatable else None,
        "automated_errors": len(errors), "automated_error_rate": len(errors) / len(automated) if automated else None,
        "automated_error_wilson95": wilson(len(errors), len(automated)),
        "safety_misses": sum(gold[r["id"]] == "escalate" for r in errors),
        "to_human": len(rows) - len(automated),
        "unnecessary_to_human": sum(gold[r["id"]] != "escalate" for r in rows if r not in automated)}


def incidents():
    protocol = json.loads((ROOT / "incidents/protocol.json").read_text())
    cases = json.loads((ROOT / "incidents/cases.json").read_text())
    gold = {c["id"]: c["label"] for c in cases}
    text = {c["id"]: c["text"] for c in cases}
    rows = json.loads((ROOT / "results/incidents-local.json").read_text()) + read_jsonl(ROOT / "results/jev-incidents.jsonl") + read_jsonl(ROOT / "results/llm-incidents.jsonl")
    out = {"labels": {split: {label: sum(c["split"] == split and c["label"] == label for c in cases) for label in protocol["criteria"]} for split in ["dev", "test", "messy"]}, "methods": {}}
    for method in sorted({r["method"] for r in rows}):
        mine = [r for r in rows if r["method"] == method]
        by_split = {split: [r for r in mine if r["split"] == split] for split in ["dev", "test", "messy"]}
        summary = {}
        for split, group in by_split.items():
            good = sum(r["prediction"]["choice"] == gold[r["id"]] for r in group)
            confusion = collections.Counter(f"{gold[r['id']]}->{r['prediction']['choice']}" for r in group)
            summary[split] = {"n": len(group), "correct": good, "accuracy": good / len(group) if group else None, "accuracy_wilson95": wilson(good, len(group)),
                "confusion": dict(sorted(confusion.items())), "ungated": gate_outcome(group, gold, 0)}
        thresholds = protocol["thresholds"] if method not in ("keyword_rules", "always_escalate") else [0]
        development = [{"threshold": t, **gate_outcome(by_split["dev"], gold, t)} for t in thresholds]
        eligible = [d for d in development if d["automated"] >= 15 and d["automated_error_rate"] <= .05]
        selected = max(eligible, key=lambda d: (d["automated_coverage"], -d["threshold"]))["threshold"] if eligible else None
        summary["gate"] = {"dev_curve": development, "selected_threshold": selected,
            "selection_status": "dev selected" if selected is not None else "no threshold met the declared dev rule",
            "test_curve": [{"threshold": t, **gate_outcome(by_split["test"], gold, t)} for t in thresholds],
            "messy_curve": [{"threshold": t, **gate_outcome(by_split["messy"], gold, t)} for t in thresholds],
            "selected_test": gate_outcome(by_split["test"], gold, selected) if selected is not None else None,
            "selected_messy": gate_outcome(by_split["messy"], gold, selected) if selected is not None else None}
        summary["messy_errors"] = [{"id": r["id"], "text": text[r["id"]], "gold": gold[r["id"]], "choice": r["prediction"]["choice"], "confidence": r["prediction"]["confidence"]}
            for r in by_split["messy"] if r["prediction"]["choice"] != gold[r["id"]]]
        latencies = [r["latency_seconds"] for r in mine if "latency_seconds" in r]
        summary["median_latency_seconds"] = statistics.median(latencies) if latencies else None
        summary["p95_latency_seconds"] = quantile(latencies, .95)
        out["methods"][method] = summary
    return out


def main():
    protocol = json.loads((ROOT / "protocol.json").read_text())
    truth = {}
    for split in ["dev", "test", "challenge"]:
        for row in json.loads((ROOT / "data" / f"{split}.json").read_text()):
            truth[row["id"]] = row
    local = json.loads((ROOT / "results/local.json").read_text())
    jev = read_jsonl(ROOT / "results/jev-routing.jsonl")
    llm = read_jsonl(ROOT / "results/llm-routing.jsonl")
    all_rows = local + jev + llm
    methods = sorted({r["method"] for r in all_rows})
    report = {"date": "2026-10-06", "routing": {}, "warehouse": {}, "limits": protocol["limitations"]}
    for method in methods:
        rows = [r for r in all_rows if r["method"] == method]
        test = [r for r in rows if r["split"] == "test"]
        dev = [r for r in rows if r["split"] == "dev"]
        challenge = [r for r in rows if r["split"] == "challenge"]
        correct = sum(r["prediction"]["choice"] == truth[r["id"]]["label"] for r in test)
        summary = {"test_n": len(test), "test_correct": correct, "test_accuracy": correct / len(test) if test else None,
            "test_accuracy_wilson95": wilson(correct, len(test)), "median_latency_seconds": statistics.median(r["latency_seconds"] for r in test) if test else None,
            "p95_latency_seconds": quantile([r["latency_seconds"] for r in test], 0.95),
            "ungated": scored(test, truth), "gates": {}, "challenge": {}}
        gates = ["confidence", "top_probability", "sufficiency"] if method.startswith("jev") else ["confidence", "sufficiency"] if method in ARMS else ["score"]
        for gate in gates:
            thresholds = protocol["thresholds"] if gate != "score" or method != "tfidf_nearest_neighbor" else [0, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, .99]
            development = [{"threshold": t, **scored(dev, truth, gate, t)} for t in thresholds]
            eligible = [r for r in development if r["accepted"] >= 30 and r["accepted_error_rate"] <= .05]
            selected = max(eligible, key=lambda r: (r["coverage"], -r["threshold"]))["threshold"] if eligible else None
            test_curve = [{"threshold": t, **scored(test, truth, gate, t)} for t in thresholds]
            summary["gates"][gate] = {"dev_curve": development, "test_curve": test_curve, "selected_threshold": selected,
                "selected_test": scored(test, truth, gate, selected) if selected is not None else None,
                "selection_status": "dev selected" if selected is not None else "no threshold met declared dev rule; no policy recommended"}
        for group in sorted({truth[r["id"]]["group"] for r in challenge}):
            cases = [r for r in challenge if truth[r["id"]]["group"] == group]
            ncorrect = sum(r["prediction"]["choice"] == truth[r["id"]]["label"] for r in cases)
            review_correct = sum(r["prediction"]["choice"] == "needs_review" for r in cases if truth[r["id"]]["label"] == "needs_review")
            summary["challenge"][group] = {"n": len(cases), "exact_label_correct": ncorrect, "review_choice_correct": review_correct}
        if (method.startswith("jev") or method in ARMS) and test:
            # Jev: returned top probability. LLM arms: self-reported confidence. Different signals; same binning.
            signal = "top_probability" if method.startswith("jev") else "confidence"
            summary["calibration_signal"] = signal
            probability_bins = []
            for low in [0, .5, .6, .7, .8, .9]:
                high = .5 if low == 0 else min(1, round(low + .1, 3))
                cases = [r for r in test if low <= r["prediction"][signal] and (r["prediction"][signal] < high or high == 1)]
                if cases:
                    avg = statistics.mean(r["prediction"][signal] for r in cases)
                    acc = sum(r["prediction"]["choice"] == truth[r["id"]]["label"] for r in cases) / len(cases)
                    probability_bins.append({"low": low, "high": high, "n": len(cases), "mean_top_probability": avg, "observed_accuracy": acc})
            summary["probability_bins"] = probability_bins
            summary["ece_selected_bins"] = sum(abs(r["mean_top_probability"] - r["observed_accuracy"]) * r["n"] / len(test) for r in probability_bins)
            strip = lambda pred: {k: v for k, v in pred.items() if k != "raw"}
            summary["high_probability_errors"] = [{"id": r["id"], "text": truth[r["id"]]["text"], "gold": truth[r["id"]]["label"], **strip(r["prediction"])} for r in test if r["prediction"]["choice"] != truth[r["id"]]["label"] and r["prediction"][signal] >= .9]
            summary["challenge_cases"] = [{"id": r["id"], "text": truth[r["id"]]["text"], "gold": truth[r["id"]]["label"], "group": truth[r["id"]]["group"], **strip(r["prediction"])} for r in challenge]
            summary["estimated_test_api_usd"] = sum(r["response"]["usage"]["input_tokens"] for r in test) * RATE if method.startswith("jev") else sum(llm_usd(method, r["response"]["usage_summary"]) for r in test)
        report["routing"][method] = summary
    if len(jev) == 396:
        report["paired_comparisons"] = {method: paired_test([r for r in jev if r["split"] == "test"], [r for r in all_rows if r["split"] == "test" and r["method"] == method], truth) for method in methods if not method.startswith("jev")}
    episodes = read_jsonl(ROOT / "results/warehouse.jsonl") + read_jsonl(ROOT / "results/llm-warehouse.jsonl")
    for method in sorted({r["method"] for r in episodes}):
        rows = [r for r in episodes if r["method"] == method]
        good = [r for r in rows if r["completed"]]
        families = {}
        for family in sorted({r["family"] for r in rows}):
            group = [r for r in rows if r["family"] == family]
            families[family] = {"n": len(group), "completed": sum(r["completed"] for r in group)}
        latencies = [t["latency_seconds"] for r in rows for t in r["trace"] if t["usage"]]
        reference = {r["episode_id"]: r for r in episodes if r["method"] == "breadth_first_search_replanning"}
        report["warehouse"][method] = {"n": len(rows), "completed": len(good), "completion_fraction": len(good) / len(rows), "uncertainty_note": "Descriptive counts only: the 12 episodes are rotations of four authored families, not an independent random sample.",
            "rejected_action_attempts": sum(r["rejected_actions"] for r in rows), "executed_forbidden_moves": 0,
            "false_completion_episodes": sum(r["outcome"] == "false_completion" for r in rows), "total_actions": sum(r["action_count"] for r in rows),
            "median_action_latency_seconds": statistics.median(latencies) if latencies else None,
            "p95_action_latency_seconds": quantile(latencies, .95), "families": families,
            "successful_action_excess_vs_replanner": [{"episode_id": r["episode_id"], "extra_actions": r["action_count"] - reference[r["episode_id"]]["action_count"]} for r in good],
            "estimated_api_usd": sum(t["usage"]["input_tokens"] for r in rows for t in r["trace"] if t["usage"]) * RATE if method.startswith("jev") else sum(llm_usd(method, t["usage"]) for r in rows for t in r["trace"] if t["usage"]) if method in ARMS else 0,
            "reasoning_tokens": sum(t["usage"].get("reasoning_tokens", 0) for r in rows for t in r["trace"] if t["usage"])}
    ledger = read_jsonl(ROOT / "results/api-ledger.jsonl")
    report["api_accounting"] = {"attempted_requests": len(ledger), "successful_requests": sum(r["status"] == 200 for r in ledger),
        "input_tokens": sum(r.get("input_tokens", 0) for r in ledger), "estimated_api_usd": sum(r.get("input_tokens", 0) for r in ledger) * RATE,
        "unconfirmed_attempts": sum(r["status"] != 200 for r in ledger), "note": "Estimate from recorded input tokens and TypeSafe's published $0.042/M input price; not a billing receipt."}
    report["incidents"] = incidents()
    llm_ledger = read_jsonl(ROOT / "results/llm-ledger.jsonl")
    report["llm_accounting"] = {arm: {"requests": sum(r["arm"] == arm for r in llm_ledger), "input_tokens": sum(r["input_tokens"] for r in llm_ledger if r["arm"] == arm),
        "output_tokens": sum(r["output_tokens"] for r in llm_ledger if r["arm"] == arm), "reasoning_tokens": sum(r.get("reasoning_tokens", 0) for r in llm_ledger if r["arm"] == arm),
        "estimated_usd": ledger_usd([r for r in llm_ledger if r["arm"] == arm]), "unfinished": sum(not r["finished"] for r in llm_ledger if r["arm"] == arm)}
        for arm in sorted({r["arm"] for r in llm_ledger})}
    report["llm_accounting_note"] = "Estimated from recorded usage and published list prices; includes smoke-test calls; not a billing receipt. OpenAI's Decisions API returned 403 (not enabled) and was not used."
    report["complete"] = len(jev) == 396 and sum(r["method"] == "jev-1.13.0" for r in episodes) == 12
    report["evidence_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "results").glob("*.jsonl")}
    (ROOT / "results/summary.json").write_text(json.dumps(report, indent=2) + "\n")
    with (ROOT / "results/routing-predictions.csv").open("w") as f:
        writer = csv.DictWriter(f, fieldnames=["method", "split", "id", "gold", "predicted", "correct", "confidence", "top_probability", "sufficiency", "latency_seconds"])
        writer.writeheader()
        for r in all_rows:
            prediction = r["prediction"]
            writer.writerow({"method": r["method"], "split": r["split"], "id": r["id"], "gold": truth[r["id"]]["label"], "predicted": prediction["choice"], "correct": prediction["choice"] == truth[r["id"]]["label"], "confidence": prediction.get("confidence"), "top_probability": prediction.get("top_probability"), "sufficiency": prediction.get("sufficiency"), "latency_seconds": r["latency_seconds"]})
    print(json.dumps({"complete": report["complete"], "routing": {m: {"correct": s["test_correct"], "n": s["test_n"], "gates": {g: v["selected_threshold"] for g, v in s["gates"].items()}} for m, s in report["routing"].items()}, "warehouse": report["warehouse"], "api": report["api_accounting"]}, indent=2))


if __name__ == "__main__":
    main()
