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

## Restore

```bash
agent_backup.py search nginx
agent_backup.py get BACKUP_ID --output ./restore
```

Directories restore as the uploaded `.tar.gz`; inspect before extracting.
