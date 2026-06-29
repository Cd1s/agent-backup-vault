---
name: agent-backup-vault
description: |
  当 agent 在改文件、配置、数据库、自动化任务、远程服务器前需要备份时使用。默认备份到远程 WebDAV，不把必要备份留在本机或被操作服务器；支持搜索、恢复和多 WebDAV profile。
---

# Agent Backup Vault

改配置、服务、数据库、自动化任务、远程服务器前，如果需要备份，先放 WebDAV 备份库。

## 规则

不要把必要备份只留在本机或正在操作的远程机器上。先上传备份，再改东西。

默认按 Ponytail：能不备份就不备份；真正有回滚价值才备份。不要为了“看起来安全”备份缓存、构建产物、包下载目录、可重建文件。

## 最常用

```bash
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put /path/to/file --label before-change
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py search keyword
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py get BACKUP_ID --output ./restore-target
```

## 远程 SSH 备份

```bash
ssh host 'tar -C /etc -czf - nginx' | python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put - --name host-etc-nginx.tar.gz --label before-nginx-edit
```

## 数据库备份

```bash
ssh host 'pg_dump "$DATABASE_URL"' | python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put - --name host-db.sql --label before-migration
```

## 多 WebDAV 磁盘

默认 profile 已够用。第二块盘再加：

```bash
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py init --profile home-mac --url URL --user USER
python3 ~/.hermes/skills/general/agent-backup-vault/scripts/agent_backup.py put FILE --profile home-mac
```

## 省 token 用法

- 不要把备份内容贴进聊天。
- 只回备份 `id`、大小、sha256 前 12 位、搜索关键词。
- 需要确认时运行 `search` 或 `get`，不要展开远程文件全文。
- 目录会自动打成 `.tar.gz`，比逐文件列目录省 token 也省空间。
- 如果只是 Git 已跟踪文件，优先用 `git diff`/commit，不额外备份整份仓库。

## 安全

- 每次上传记录到远程 `index.jsonl`：`id`、`sha256`、大小、源名、UTC 时间、WebDAV 路径。
- 删除源文件前先 `search` 确认备份存在。
- 密钥/数据库建议先加密再传；HTTPS 只保护传输，WebDAV 服务端保存原始字节。

## 暂不做

MCP 先不加。只有需要客户端里点选浏览/恢复、或自动多目标 fanout 时再做；MCP 应调用这个 CLI，不重写 WebDAV。
