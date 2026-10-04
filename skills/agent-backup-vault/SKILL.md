---
name: agent-backup-vault
description: |
  当 agent 在改文件、配置、数据库、自动化任务、远程服务器前需要备份时使用。默认备份到远程 WebDAV，不把必要备份留在本机或被操作服务器；支持搜索、恢复和多 WebDAV profile。
---

# Agent Backup Vault

改配置、服务、数据库、自动化任务、远程服务器前，如果需要备份，先放 WebDAV 备份库。

## 规则

不要把必要备份只留在本机或正在操作的远程机器上。先上传备份，再改东西。

## 最常用

装好的机器上有 `agent-backup` 命令（等价于 `python3 <skill>/scripts/agent_backup.py`）：

```bash
agent-backup put /path/to/file-or-dir --label before-change   # 目录自动打成 .tar.gz
agent-backup search keyword
agent-backup get BACKUP_ID --output ./restore-target          # 流式下载并校验 sha256
```

没有 `agent-backup` 命令时，用本 skill 目录下的 `scripts/agent_backup.py`，参数相同。

- `put` 内容和已有备份完全相同（同主机、同文件名、同 sha256）时直接复用旧记录，输出带 `"reused": true`，不再上传。要强制再传一份就加 `--no-dedup`。
- 完整 id 可以不经索引直接 `get`。索引每分钟重建一次，所以刚上传的备份要一分钟左右才能被 `search` 搜到。

## WebDAV 临时不可用时

- 客户端对目录创建、对象上传、索引读写等瞬时 TLS/网络错误统一做有限退避重试；重试耗尽仍按下述规则 fail-closed。
- 先重试一次；如果仍是 5xx/网络错误，不要假装已备份。
- `put` 只有在返回完整结构化记录和 backup `id` 后才算成功。对象 PUT 成功但 `index.jsonl` 追加超时属于部分成功，不能作为可恢复备份报告；网络恢复后重新执行并以返回的 `id` 为准。
- 如果新备份失败，但远端已有一个可能覆盖当前文件的旧备份，计算当前文件 SHA-256，并与该旧备份记录中的完整 SHA-256 比较。只有逐字节 hash 相同才能把旧备份作为本次修改的有效前置备份；仅凭文件名、label 或“配置应该没变”不够。
- 没有可证明相同的远端备份时，做本机临时备份到当前 workspace，输出路径和 sha256，并明确标注“非长期备份”。
- 只做必要的最小安全改动；完成后在结果里提醒远程备份失败，后续需要补传。
- 不要把这个失败写成“备份工具不可用”的长期结论；它通常是服务端/网络瞬态问题。

## 大文件

- 现在的客户端是流式上传和下载，不再把整个文件读进内存，大文件不会因此 OOM。目录打包用 gzip 6 级，比默认 9 级快很多。
- 走公网（Cloudflare 代理）的入口单个请求最大 100MB，客户端遇到超过 95MB 的文件会直接报错。这种情况要在能连 tailnet 的机器上传。
- `put --timeout` 默认 300 秒，是单次网络读写的超时，不是总时长。
- 细节：`references/large-file-upload.md`。

## 远程 SSH 备份

```bash
ssh host 'tar -C /etc -czf - nginx' | agent-backup put - --name host-etc-nginx.tar.gz --label before-nginx-edit
```

经 **sshctl** 时须用 `sshctl run <alias> -s <<'EOF'` 输出 tar 流；勿把裸远程命令当第一个参数（会 `invalid_arguments` 且 `put -` 可能收到空流）。

## 数据库备份

```bash
ssh host 'pg_dump "$DATABASE_URL"' | agent-backup put - --name host-db.sql --label before-migration
```

### 数据库备份验证

对数据库/WebDAV 备份，不要只以“dump 成功/上传成功”作为最终结论。关键业务库在策略变更、首次上线或用户问“能不能恢复”时，做一次 round-trip 验证：上传后用 `agent_backup.py get` 下载同一 `backup_id`，校验 sha256/manifest，再恢复到临时库，对比业务关键表行数，确认被设计排除的日志/历史表为空或符合预期。避免把一次性 `pg_restore` 管道 SIGPIPE/141 误判为备份损坏；必要时先把 dump 文件复制到数据库容器内，再从文件路径执行 restore/list。

## 高风险发布与迁移的终态证据包

完成 GitHub Release、生产部署、迁移或安全修复后，优先制作一个只含白名单 JSON/日志摘要的无凭据小型证据包；上传后必须对同一 backup ID 执行 `get`、SHA-256 round trip 和归档成员检查。凭据扫描应检查敏感结构化键与真实 token/private-key 形态，不要因文档中出现普通单词 `authorization` 或 `token` 就误报。完整流程见 `references/audit-evidence-bundles.md`。

## 多 WebDAV 磁盘 / profile

`~/.config/agent-backup-vault/config.json` 里可以有多个 profile：

- `default`：主备份库。`urls` 依次是 tailnet 地址、公网地址，客户端选第一个连得通的，结果缓存 10 分钟。`index: sidecar` 表示每个备份旁边写一个 `.meta.json`，由服务端合成 `index.jsonl`。`host_label` 是记录里的主机名，用 ssm 别名。
- 其它 profile（例如旧 WebDAV 库）用 `--profile NAME` 指定。主库会异步复制一份到异地库，agent 不用自己往两边各传一次。

新增 profile：

```bash
agent-backup init --profile NAME --url URL [--fallback-url URL2] --user USER [--index sidecar] [--host-label ALIAS]
```

## 省 token 用法

- 不要把备份内容贴进聊天。
- 只回备份 `id`、大小、sha256 前 12 位、搜索关键词。
- 需要确认时运行 `search` 或 `get`，不要展开远程文件全文。
- 目录会自动打成 `.tar.gz`，比逐文件列目录省 token 也省空间。
- 如果只是 Git 已跟踪文件，优先用 `git diff`/commit，不额外备份整份仓库。

## 定时任务保留策略

简单条数保留：上传后 `search <label>`，对最旧超出 `KEEP` 的 id 调用 `rm`。**`rm` 是不可逆对象删除，必须在当次获得明确授权后才执行；不要让常规定时备份自动裁剪。** 删除脚本必须将 WebDAV 403 视为失败（不可把无权/未确认删除记作成功），404 才是可接受的幂等“已不存在”。

日历保留（近 N 天日备 + 最近 M 个月末各一份）：上传成功后按 backup id 日期裁剪，再用 `rm` 删对象。模式见 `references/retention-daily-plus-monthly.md`；SSM vault 实例见 `agent-ssm` → `references/ssm-webdav-daily-backup.md`。

## 并发与安全

- sidecar profile：客户端只写对象和它的 `.meta.json`，从不改写 `index.jsonl`。服务端 cron 每分钟跑一次 `scripts/agent_backup_index.py <root>`，把 sidecar 合进索引（和原有行取并集，原子替换），所以多台机器同时备份也不会丢记录。
- legacy profile（没有 `index: sidecar`）仍是 `index.jsonl` 的 GET→PUT 追加，由本机 `index-append.lock` 串行化。不同机器同时写会互相覆盖，所以多机共用的库应当用 sidecar。只有明确 HTTP 404 才能初始化空索引；索引读取的 5xx、认证或网络失败必须 fail-closed，绝不把它当作空索引覆盖。
- 每条记录含 `id`、`sha256`、大小、源名、UTC 时间、WebDAV 路径、主机名。
- 删除源文件前先 `search` 或 `get` 确认备份存在。
- 密钥/数据库建议先加密再传；HTTPS 只保护传输，WebDAV 服务端保存原始字节。

## 暂不做

MCP 先不加。只有需要客户端里点选浏览/恢复、或自动多目标 fanout 时再做；MCP 应调用这个 CLI，不重写 WebDAV。
