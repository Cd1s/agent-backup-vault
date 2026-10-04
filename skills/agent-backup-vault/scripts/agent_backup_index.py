#!/usr/bin/env python3
"""Rebuild <root>/index.jsonl from per-backup *.meta.json sidecars (union with existing rows).

Clients write the object plus a one-line sidecar; this keeps the index append-only
without client-side read-modify-write races. Runs from cron every minute.
"""
import json, os, sys, tempfile
root = sys.argv[1] if len(sys.argv) > 1 else '/srv/agent-backups/agent-backups'
index = os.path.join(root, 'index.jsonl')
rows, seen = [], set()
def add(line):
    try:
        r = json.loads(line)
    except ValueError:
        return
    if isinstance(r, dict) and r.get('id') and r['id'] not in seen:
        seen.add(r['id']); rows.append(r)
try:
    with open(index, encoding='utf-8') as f:
        for line in f: add(line)
except FileNotFoundError:
    pass
before = len(rows)
for d, _, files in os.walk(root):
    for n in files:
        if n.endswith('.meta.json'):
            try:
                with open(os.path.join(d, n), encoding='utf-8') as f: add(f.read())
            except OSError:
                pass
# Sidecar-written rows whose object was deleted (`rm`) drop out; legacy/imported rows are kept as-is.
base = os.path.dirname(root.rstrip('/'))
kept = [r for r in rows if r.get('index') != 'sidecar' or os.path.exists(os.path.join(base, r.get('path', '')))]
if len(kept) == len(rows) == before and os.path.exists(index):
    sys.exit(0)
rows = kept
rows.sort(key=lambda r: (r.get('time_utc', ''), r['id']))
fd, tmp = tempfile.mkstemp(dir=root, prefix='.index.')
with os.fdopen(fd, 'w', encoding='utf-8') as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + '\n')
os.chmod(tmp, 0o640); os.replace(tmp, index)
