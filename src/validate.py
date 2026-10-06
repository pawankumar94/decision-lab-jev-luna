"""Independently check evidence integrity, metric counts, and simulator replays."""
import collections
import hashlib
import json
import pathlib
import re
from client import ROOT
from world import World, DIRS


def jsonl(p):return [json.loads(s) for s in p.read_text().splitlines()]


def main():
    for directory in [ROOT, ROOT / "world"]:
        manifest = json.loads((directory / "manifest.json").read_text())
        for file, digest in manifest.items():
            assert hashlib.sha256((directory / file).read_bytes()).hexdigest() == digest, file
    datasets={split: json.loads((ROOT / "data" / (split+".json")).read_text()) for split in ["fit","dev","test","challenge"]}
    norm=lambda row: ' '.join(row["text"].lower().split())
    for a,b in [("fit","dev"),("fit","test"),("dev","test")]:
        assert not ({norm(r) for r in datasets[a]} & {norm(r) for r in datasets[b]}), "Exact text leakage"
    routing=jsonl(ROOT / "results/jev-routing.jsonl")
    assert len(routing)==396 and len({r['id'] for r in routing})==396
    for row in routing:
        response=row['response'];pred=row['prediction'];answer=response['answers']['route']
        assert response['model']=='jev-1.13.0'
        assert pred['choice']==answer['choice']
        assert abs(sum(answer['probabilities'].values())-1)<.01
        assert answer['probabilities'][answer['choice']]+.011 >= max(answer['probabilities'].values())
        n=len(answer['probabilities']);formula=(max(answer['probabilities'].values())-1/n)/(1-1/n)
        # Returned probabilities/confidence are rounded; allow corresponding rounding.
        assert abs(formula-answer['confidence'])<.03
    truth={r['id']:r['label'] for r in datasets['test']}
    test=[r for r in routing if r['split']=='test']
    assert len(test)==240
    good=sum(r['prediction']['choice']==truth[r['id']] for r in test)
    summary=json.loads((ROOT/'results/summary.json').read_text())
    assert good==summary['routing']['jev-1.13.0']['test_correct']
    chosen=summary['routing']['jev-1.13.0']['gates']['confidence']['selected_threshold']
    accepted=[r for r in test if r['prediction']['choice']!='needs_review' and r['prediction']['confidence']>=chosen]
    assert len(accepted)==202
    assert sum(r['prediction']['choice']!=truth[r['id']] for r in accepted)==2
    records=jsonl(ROOT/'results/warehouse.jsonl')
    assert len(records)==36 and len({(r['method'],r['episode_id']) for r in records})==36
    for r in records:
        w=World(r['episode']);terminal=None
        for t in r['trace']:
            assert w.state()==t['state'], r['episode_id']
            violation,terminal=w.step(t['action'])
            assert list(w.position)==t['position_after']
            assert violation==t['rejected'] and terminal==t['terminal']
        assert terminal==r['outcome']
        assert (terminal=='completed')==r['completed']
        assert sum(t['rejected'] is not None for t in r['trace'])==r['rejected_actions']
    calls=jsonl(ROOT/'results/api-ledger.jsonl')
    expected_tokens=sum(r['response']['usage']['input_tokens'] for r in routing)
    expected_tokens+=sum(t['usage']['input_tokens'] for r in records for t in r['trace'] if t['usage'])
    # The original pilot's 522 calls come first in the shared Jev ledger; incident calls (Test 2) follow.
    pilot=calls[:522]
    assert expected_tokens==sum(r['input_tokens'] for r in pilot)==544407
    assert all(r['status']==200 for r in calls)
    incident_rows=jsonl(ROOT/'results/jev-incidents.jsonl')
    assert len(calls)==522+len(incident_rows)
    assert sum(r['input_tokens'] for r in calls[522:])==sum(r['response']['usage']['input_tokens'] for r in incident_rows)
    comparison_checks(datasets, summary)
    # Fail without printing file contents if a credential-shaped value is present.
    for p in ROOT.rglob('*'):
        if {'.venv', 'node_modules', 'renders', '.git'} & set(p.parts): continue
        if p.is_file() and p.suffix in ['.json','.jsonl','.csv','.md','.py','.js','.html','.svg','.log','.sh','.txt']:
            data=p.read_bytes()
            assert not re.search(b'api'+b'key_'+rb'[0-9a-f]{32}_[0-9a-f]{64}',data), 'Credential-shaped content found in '+str(p)
            assert not re.search(rb'(?<![A-Za-z0-9_-])sk-(proj-)?[A-Za-z0-9_-]{40,200}(?![A-Za-z0-9_-])',data), 'OpenAI-key-shaped content found in '+str(p)
            assert not re.search(rb'(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{40,200}(?![A-Za-z0-9_-])',data), 'Anthropic-key-shaped content found in '+str(p)
    print('PASS: frozen manifests, split isolation, raw metrics, confidence formula, 36 simulator traces, 522 Jev pilot calls, token accounting, comparator and incident evidence, and credential scan.')


def comparison_checks(datasets, summary):
    from llm_client import ARMS
    for directory in [ROOT / 'comparator', ROOT / 'incidents']:
        for name, digest in json.loads((directory / 'manifest.json').read_text()).items():
            base = ROOT if directory.name == 'comparator' else directory
            assert hashlib.sha256((base / name).read_bytes()).hexdigest() == digest, name
    arms = ['gpt-6-luna-none', 'gpt-6-luna-medium']
    truth = {r['id']: r['label'] for s in ['dev', 'test', 'challenge'] for r in datasets[s]}
    routing = jsonl(ROOT / 'results/llm-routing.jsonl')
    for arm in arms:
        rows = [r for r in routing if r['method'] == arm]
        assert len(rows) == 396 and len({r['id'] for r in rows}) == 396, arm
        for r in rows:
            text = [c['text'] for o in r['response']['output'] if o['type'] == 'message' for c in o['content'] if c['type'] == 'output_text'][-1]
            raw = json.loads(text)
            assert raw == r['prediction']['raw'] and raw['route'] == r['prediction']['choice']
            assert r['response']['model'] == ARMS[arm]['model'] and r['response']['status'] == 'completed'
        test = [r for r in rows if r['split'] == 'test']
        assert sum(r['prediction']['choice'] == truth[r['id']] for r in test) == summary['routing'][arm]['test_correct']
    cases = {c['id']: c for c in json.loads((ROOT / 'incidents/cases.json').read_text())}
    assert len(cases) == 240
    incidents = jsonl(ROOT / 'results/jev-incidents.jsonl') + jsonl(ROOT / 'results/llm-incidents.jsonl')
    for method in ['jev-1.13.0'] + arms:
        rows = [r for r in incidents if r['method'] == method]
        assert len(rows) == 240 and {r['id'] for r in rows} == set(cases), method
        good = sum(r['prediction']['choice'] == cases[r['id']]['label'] for r in rows if r['split'] == 'messy')
        assert good == summary['incidents']['methods'][method]['messy']['correct'], method
    for r in incidents:
        if r['method'] == 'jev-1.13.0':
            assert r['response']['model'] == 'jev-1.13.0' and r['response']['answers']['decision']['choice'] == r['prediction']['choice']
    episodes = jsonl(ROOT / 'results/llm-warehouse.jsonl')
    for arm in arms:
        assert len([r for r in episodes if r['method'] == arm]) == 12, arm
    for r in episodes:
        w = World(r['episode']); terminal = None
        for t in r['trace']:
            assert w.state() == t['state'], r['episode_id']
            violation, terminal = w.step(t['action'])
            assert list(w.position) == t['position_after'] and violation == t['rejected'] and terminal == t['terminal']
        assert terminal == r['outcome'] and (terminal == 'completed') == r['completed']
    ledger = jsonl(ROOT / 'results/llm-ledger.jsonl')
    assert all(x['finished'] for x in ledger)
    used = {}
    for r in routing + [x for x in incidents if x['method'] in arms]:
        u = r['response']['usage_summary']; used[r['method']] = used.get(r['method'], 0) + u['input_tokens']
    for r in episodes:
        used[r['method']] += sum(t['usage']['input_tokens'] for t in r['trace'])
    for arm in arms:
        recorded = [x for x in ledger if x['arm'] == arm and not x['request_id'].startswith('smoke-')]
        assert sum(x['input_tokens'] for x in recorded) == used[arm], arm
        assert len(recorded) == 396 + 240 + sum(len(r['trace']) for r in episodes if r['method'] == arm), arm
    jev_inc = [x for x in jsonl(ROOT / 'results/api-ledger.jsonl')]
    assert all(x['status'] == 200 for x in jev_inc)


if __name__=='__main__':main()
