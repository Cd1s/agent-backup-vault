---
name: agent-backup-vault
description: |
  Use when an agent needs to back up files, configs, dumps, automation state, or remote-server data before making changes. Enforces remote WebDAV backups instead of local or same-server backup folders, with searchable index and restore commands.
---

# Agent Backup Vault

Before risky edits, upgrades, migrations, daemon changes, database work, or automation changes: back up to the configured WebDAV vault.

## Rule

Do **not** leave required backups only on the local machine or on the remote SSH host being changed. Use this vault first, then make the change.

## Fast path

```bash
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put /path/to/thing --label before-change
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py search keyword
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py get BACKUP_ID --output ./restore-target
```

Remote SSH file:

```bash
ssh host 'tar -C /etc -czf - nginx' | python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put - --name host-etc-nginx.tar.gz --label before-nginx-edit
```

Database dump:

```bash
ssh host 'pg_dump "$DATABASE_URL"' | python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put - --name host-db.sql --label before-migration
```

## Profiles

Default profile is enough until a second WebDAV disk exists. For another disk:

```bash
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py init --profile home-mac --url URL --user USER
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put FILE --profile home-mac
```

## Safety checks

- After every upload, the CLI records `id`, `sha256`, size, source name, UTC time, and WebDAV path in remote `index.jsonl`.
- Verify with `search` before deleting any source.
- For secrets, prefer already-encrypted dumps; WebDAV transport is HTTPS, but the server stores bytes as given.

## When not enough

Use this CLI for storage. Add an MCP later only if agents need UI-native browse/restore or scheduled multi-target fanout; the MCP should call this CLI, not replace it.
