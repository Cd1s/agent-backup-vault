# agent-backup-vault

One boring rule for agents: if something needs a backup, put it in WebDAV, not on the machine being changed.

This repo ships a tiny stdlib-only WebDAV backup CLI plus an agent skill. It is meant for config snapshots, database dumps, automation files, and small/medium operational backups.

## Install

```bash
python3 skills/agent-backup-vault/scripts/agent_backup.py init \
  --url 'https://dav.example.com/dav' \
  --user 'you@example.com'
# password is prompted and stored in ~/.config/agent-backup-vault/config.json mode 600
```

## Use

```bash
# upload file or directory; directories become .tar.gz
python3 skills/agent-backup-vault/scripts/agent_backup.py put /path/to/file --label before-edit

# search remote backup index
python3 skills/agent-backup-vault/scripts/agent_backup.py search nginx

# download by backup id
python3 skills/agent-backup-vault/scripts/agent_backup.py get 20260629T054500Z-host-before-edit-file.conf

# verify WebDAV login
python3 skills/agent-backup-vault/scripts/agent_backup.py check
```

Backups are content-addressed with a SHA-256 recorded in `index.jsonl`. Uploads use timestamped immutable names, so normal agent work should not overwrite prior backups.

## Multiple disks / multiple WebDAV targets

Use profiles:

```bash
python3 skills/agent-backup-vault/scripts/agent_backup.py init --profile home-mac --url 'https://mac.example/dav' --user user
python3 skills/agent-backup-vault/scripts/agent_backup.py put ./db.sql --profile home-mac
```

For heavy jobs, keep this as the storage primitive. Add an MCP only when agents need interactive browse/restore inside a client UI; it can shell out to this CLI instead of reimplementing WebDAV.

## Skill

Install/copy `skills/agent-backup-vault/` into an agent runtime skill directory. For Hermes local use:

```bash
cp -a skills/agent-backup-vault ~/.hermes/skills/general/
```
