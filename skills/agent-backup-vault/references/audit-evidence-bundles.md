# 高风险发布终态证据包

适用于 GitHub Release、生产部署、迁移或安全修复完成后的无凭据证据归档。

## 目标

归档足以证明终态的少量结构化证据，而不是复制整个工作区、构建产物或凭据目录。

推荐内容：

- promotion / deployment summary JSON
- post-change canary summary JSON
- exact-HEAD CI / recovery run JSON
- latest / release / tag 的最终 API 快照
- 旧版本或旧资源的不变性快照
- 自动化清单或变更记录

通常不要包含：

- 二进制和完整构建缓存（除非它们本身是唯一证据）
- `.env`、SSH vault、CLI auth 配置、cookies
- token、密码、私钥、连接字符串
- 整个用户配置目录或整个项目工作区

## 凭据扫描

不要只搜索 `token`、`secret`、`authorization` 等普通单词；Release Notes、文档和测试说明经常合法包含这些词，会产生误报。

应组合两类检查：

1. **结构化键检查**：递归检查 JSON/YAML 中的敏感键，如 `password`、`passwd`、`secret`、`token`、`access_token`、`authorization`、`private_key`、`api_key`；值非空即停止。
2. **真实凭据形态检查**：PEM private-key header、GitHub token 前缀、AWS access key、Telegram bot token、JWT 三段式字符串等。

普通说明文本中的“authorization required”不是凭据；敏感键带实际值或匹配真实凭据形态才是阻断项。

## 确定性流程

1. 创建新的临时目录，只复制白名单文件。
2. 对目录执行结构化键 + 凭据形态扫描。
3. 打包为 `.tar.gz`，计算完整 SHA-256。
4. 使用 `agent_backup.py put ... --label <stable-label>` 上传。
5. 只有返回完整 backup `id`、size 和 SHA-256 才算上传成功。
6. 用同一个 backup `id` 执行 `get` 下载到新的临时路径。
7. 重新计算 SHA-256，必须与上传前完全一致。
8. 列出归档成员，确认只有白名单文件且没有意外父目录内容。
9. 最终只报告 backup ID、size、SHA-256 和 label，不展开证据正文。

## 常见陷阱

- 第一个文件路径错误时，`set -e` 会在上传前停止；修正真实路径后重建整个包，不要假设部分包可用。
- `put` 成功但没有 backup ID，不能报告为可恢复备份。
- 只执行 `search` 不能证明对象内容正确；必须对同一 ID 做 `get` + SHA-256 round trip。
- 归档清单检查与 SHA-256 各自解决不同问题：前者验证范围，后者验证字节完整性，两者都要做。
