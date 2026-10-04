# Large-file WebDAV upload notes

## Why small CLI fails on multi-GB objects

Older versions of `agent_backup.py` did `payload.read_bytes()` before the PUT, doubling peak RAM and
OOM-ing on ~1–1.5GB zips. Current versions stream the file from disk (and `get` streams to disk), so
memory is no longer the limit; the remaining limits are disk space for the temporary tar/stdin copy and
the 100 MB request-body cap on Cloudflare-proxied endpoints.

## Prefer small recoverables for Hermes update

Before `hermes update --backup`, upload labeled small artifacts instead of relying on the multi-GB export zip:

| Label example | Content |
|---|---|
| `before-hermes-update-config` | `~/.hermes/config.yaml` |
| `before-hermes-update-source-diff` | dirty tree patch |
| `before-hermes-update-source-untracked` | small tar of untracked needed files |
| `before-hermes-update-status` | version/git status text |

Inspect a fat zip composition with `zipfile` + size-by-top-prefix before deciding it is worth keeping (often dominated by `state.db`, `webui`, `state-snapshots`, `sessions`).

## If a large upload is still required

1. Stream sha256 (1MiB chunks), do not `Path.read_bytes()`.
2. Stream PUT with `curl --data-binary @file` and long `--max-time`.
3. Append `index.jsonl` only after HTTP 200/201/204.
4. On kill/timeout: leave local file, report failure, do not delete until a successful remote id exists **or** user accepts incremental-only recovery.

## After successful remote backup

Delete local multi-GB zip to free disk; leave a short README in `~/.hermes/backups/` pointing at WebDAV labels / backup ids.
