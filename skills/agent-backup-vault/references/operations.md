# Operations

## What belongs here

- `/etc` service configs before edits
- systemd unit/timer files before replacement
- automation scripts before deployment
- database dumps before migrations
- app config/data snapshots before upgrades

## What does not belong here

- huge media archives
- package caches
- unencrypted private keys unless explicitly required
- backups that already live in a proper external backup system

## Naming

Use `--label before-THING` so search works later:

```bash
agent_backup.py put /etc/nginx --label before-nginx-reload
agent_backup.py put dump.sql --label before-user-table-migration
```

## Remote SSH backup

```bash
ssh host 'tar -C /etc -czf - nginx' | python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put - --name host-etc-nginx.tar.gz --label before-nginx-edit
```

With **ssm/sshctl**: use `sshctl run <alias> -s <<'EOF' … EOF` for the remote tar stream, not a bare quoted remote command as the first argument after the alias (that yields `invalid_arguments` and can pipe an empty stdin into `put -`). Example:

```bash
sshctl run <alias> -s <<'EOF' | python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put - --name remote.tar.gz --label before-change
tar -czf - -C /opt/sub2api file1 file2
EOF
```

Verify the printed backup `size` is non-zero before treating the upload as durable.

## Restore

```bash
agent_backup.py search nginx
agent_backup.py get BACKUP_ID --output ./restore
```

Directories restore as the uploaded `.tar.gz`; inspect before extracting.
