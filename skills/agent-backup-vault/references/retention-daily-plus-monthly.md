# Retention: rolling dailies + month-end archives

Pattern for scheduled jobs that upload via `agent_backup.py` with a fixed `--label`, then prune with `search` + `rm` (no index rewrite in CLI today).

## Policy template

| Window | Rule |
|--------|------|
| Recent | Keep all backups with `backup_id` date ≥ today − N days (UTC, first 8 chars of id). |
| Older | Delete unless date is last day of calendar month. |
| Month-ends | Group by `(year, month)`; keep latest id per month; retain only the M most recent months. |

Example in production: label `ssm-vault-daily`, N=30, M=12 — see `agent-ssm` → `references/ssm-webdav-daily-backup.md`.

## Implementation notes

- Parse date: `datetime.strptime(backup_id[:8], "%Y%m%d").date()`.
- Month-end: `d.day == calendar.monthrange(d.year, d.month)[1]`.
- List candidates: `python3 .../agent_backup.py search <label> --limit 5000`.
- Delete: `python3 .../agent_backup.py rm <full_backup_id>` (object only; index line may remain — acceptable for this user's setup).
- Run prune **after** successful `put` so a failed upload does not delete the last good copy.

## Sub2API contrast

`sub2api_webdav_backup.py` uses simple **count** retention (`KEEP` last N uploads). Use count when calendar rules are not required.