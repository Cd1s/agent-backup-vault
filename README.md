# agent-backup-vault

给 agent 用的远程备份库：需要备份时传到 WebDAV，不放本机或正在操作的服务器。

## 安装

```bash
python3 skills/agent-backup-vault/scripts/agent_backup.py init \
  --url 'https://dav.example.com/dav' \
  --user 'you@example.com'
```

密码会提示输入，保存到 `~/.config/agent-backup-vault/config.json`，权限 `600`。

## 使用

```bash
# 备份文件或目录；目录自动打成 .tar.gz
python3 skills/agent-backup-vault/scripts/agent_backup.py put /path/to/file --label before-edit

# 搜索远程索引
python3 skills/agent-backup-vault/scripts/agent_backup.py search nginx

# 按备份 id 下载
python3 skills/agent-backup-vault/scripts/agent_backup.py get BACKUP_ID --output ./restore

# 检查 WebDAV 登录
python3 skills/agent-backup-vault/scripts/agent_backup.py check
```

## 多 WebDAV / 多磁盘

```bash
python3 skills/agent-backup-vault/scripts/agent_backup.py init --profile home-mac --url 'https://mac.example/dav' --user user
python3 skills/agent-backup-vault/scripts/agent_backup.py put ./db.sql --profile home-mac
```

## 给 Hermes 安装

```bash
cp -a skills/agent-backup-vault ~/.hermes/skills/general/
```

## 省 token

只让 agent 汇报备份 `id`、大小、sha256 前 12 位和搜索关键词；不要展开备份内容。

## 设计取舍

先用 stdlib CLI。MCP 暂不做；需要在客户端 UI 里浏览/恢复或多目标自动 fanout 时再加。
