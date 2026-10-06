"""Local text baselines and real Jev calls against frozen cases."""
import argparse
import collections
import hashlib
import json
import math
import pathlib
import re
import time
from client import JevClient, ROOT, key_from_prompt


def load(name):
    return json.loads((ROOT / name).read_text())


def verify_manifest():
    for name, digest in load("manifest.json").items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Frozen protocol/data changed: " + name)


def tokens(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return words + [a + "_" + b for a, b in zip(words, words[1:])]


class NaiveBayes:
    def __init__(self, fit):
        self.counts = collections.defaultdict(collections.Counter)
        self.docs = collections.Counter()
        vocab = set()
        for item in fit:
            ts = tokens(item["text"])
            self.counts[item["label"]].update(ts)
            self.docs[item["label"]] += 1
            vocab.update(ts)
        self.labels = sorted(self.docs)
        self.vocab = vocab
        self.denoms = {label: sum(self.counts[label].values()) + len(vocab) for label in self.labels}
        self.total = len(fit)

    def predict(self, text):
        counts = collections.Counter(t for t in tokens(text) if t in self.vocab)
        logs = {label: math.log(self.docs[label] / self.total) + sum(n * math.log((self.counts[label][t] + 1) / self.denoms[label]) for t, n in counts.items()) for label in self.labels}
        peak = max(logs.values())
        probabilities = {label: math.exp(v - peak) for label, v in logs.items()}
        total = sum(probabilities.values())
        probabilities = {label: v / total for label, v in probabilities.items()}
        label = max(probabilities, key=probabilities.get)
        return {"choice": label, "top_probability": probabilities[label], "probabilities": probabilities, "score": probabilities[label]}


class NearestNeighbor:
    def __init__(self, fit):
        df = collections.Counter()
        for item in fit:
            df.update(set(tokens(item["text"])))
        self.idf = {t: math.log((1 + len(fit)) / (1 + n)) + 1 for t, n in df.items()}
        self.docs = [(self.vector(item["text"]), item["label"]) for item in fit]

    def vector(self, text):
        counts = collections.Counter(tokens(text))
        v = {t: (1 + math.log(n)) * self.idf[t] for t, n in counts.items() if t in self.idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        return {t: x / norm for t, x in v.items()}

    def predict(self, text):
        query = self.vector(text)
        scored = [(sum(v * doc.get(t, 0) for t, v in query.items()), label) for doc, label in self.docs]
        score, label = max(scored, key=lambda x: x[0])
        return {"choice": label, "score": score, "score_kind": "cosine similarity, not probability"}


def local():
    verify_manifest()
    fit = load("data/fit.json")
    outputs = []
    for name, model in [("multinomial_naive_bayes", NaiveBayes(fit)), ("tfidf_nearest_neighbor", NearestNeighbor(fit))]:
        for split in ["dev", "test", "challenge"]:
            for item in load(f"data/{split}.json"):
                t = time.perf_counter()
                prediction = model.predict(item["text"])
                outputs.append({"id": item["id"], "split": split, "method": name, "prediction": prediction, "latency_seconds": time.perf_counter() - t})
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results/local.json").write_text(json.dumps(outputs, indent=2) + "\n")
    for name in ["multinomial_naive_bayes", "tfidf_nearest_neighbor"]:
        rows = [r for r in outputs if r["method"] == name and r["split"] == "test"]
        truth = {r["id"]: r["label"] for r in load("data/test.json")}
        good = sum(truth[r["id"]] == r["prediction"]["choice"] for r in rows)
        print(name, "correct", good, "of", len(rows), flush=True)


def live(client):
    verify_manifest()
    protocol = load("protocol.json")
    output = ROOT / "results/jev-routing.jsonl"
    existing = {json.loads(s)["id"] for s in output.read_text().splitlines()} if output.exists() else set()
    done = 0
    for split in ["dev", "test", "challenge"]:
        for item in load(f"data/{split}.json"):
            if item["id"] in existing:
                continue
            payload = {"model": protocol["model"], "state": {"customer_message": item["text"]}, "questions": {
                "route": {"type": "choice", "instructions": protocol["instructions"], "criteria": protocol["criteria"]},
                "sufficient": {"type": "noul", "instructions": {"question": protocol["sufficiency_instructions"], "intent_criteria": {k: v for k, v in protocol["criteria"].items() if k != "needs_review"}}},
            }}
            response, latency = client.decide(payload, item["id"])
            answer = response["answers"]["route"]
            probs = answer["probabilities"]
            if set(probs) != set(protocol["criteria"]) or answer["choice"] not in probs or abs(sum(probs.values()) - 1) > 0.01:
                raise RuntimeError("Invalid choice/probability schema.")
            if not all(isinstance(x, (int, float)) and math.isfinite(x) and 0 <= x <= 1 for x in probs.values()):
                raise RuntimeError("Invalid probability values.")
            prediction = {"choice": answer["choice"], "confidence": answer["confidence"], "top_probability": max(probs.values()), "probabilities": probs, "sufficiency": response["answers"]["sufficient"]["noul"]}
            if not 0 <= prediction["sufficiency"] <= 1:
                raise RuntimeError("Invalid sufficiency value.")
            record = {"id": item["id"], "split": split, "method": "jev-1.13.0", "prediction": prediction, "latency_seconds": latency, "request": payload, "response": response}
            with output.open("a") as f:
                f.write(json.dumps(record) + "\n")
            done += 1
            if done % 20 == 0:
                print("Jev routing completed", done + len(existing), "of 396", flush=True)
    print("Jev routing finished; raw responses saved.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["local", "live"])
    args = parser.parse_args()
    if args.mode == "local":
        local()
    else:
        live(JevClient(key_from_prompt()))
