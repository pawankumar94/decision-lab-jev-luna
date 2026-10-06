# Data

Routing data is a subset of **Banking77** by PolyAI: 13,083 real banking customer-service queries labelled with 77 intents.
Source: https://github.com/PolyAI-LDN/task-specific-datasets/tree/master/banking_data. Licence: CC BY 4.0 (`LICENSE` in this folder).
Paper: Casanueva, Temčinas, Gerz, Henderson and Vulić, *Efficient Intent Detection with Dual Sentence Encoders*, 2020 ([arXiv:2003.04807](https://arxiv.org/abs/2003.04807)).

| File | What it is |
|---|---|
| `train.csv`, `test.csv` | The official Banking77 splits, unmodified. |
| `categories.json` | The 12 intents used here, chosen before any model call because they are easy to confuse. |
| `fit.json` | 1,510 official-train messages used to train the Naive Bayes and TF-IDF baselines. |
| `dev.json` | 120 official-train messages (10 per intent) used only to choose confidence thresholds. |
| `test.json` | 240 official-test messages (20 per intent), sampled with seed 20261006. |
| `challenge.json` | 36 author-written diagnostic cases (missing information, two intents, out of scope, instructions inside the message). Not human-adjudicated. |

`src/prepare.py` builds the JSON files from the CSVs. `manifest.json` in the repo root holds their SHA-256 fingerprints, and every script refuses to run if they change.
