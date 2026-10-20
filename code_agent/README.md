<!-- MANUAL README -->

# 代码代理

把「分析这段代码 / 改这个项目」交给本机已经装好的 Codex CLI 或 Claude Code。她自己不动手改仓库，只负责把任务交出去。

## 怎么用

- `让 Codex 分析这个项目为什么启动失败`
- `用 Claude Code 修改 README`
- `code_agent analyze ||| codex_cli ||| . ||| 检查报错`

真正改文件必须经过确认，不会悄悄落盘。

## 权限

- 本地可用
- QQ 仅主人；群聊需要 @
- 其他人不可用

## 要准备的环境（不是填网页 API Key）

本机先装好其中一个：

- Codex CLI（默认）
- Claude Code

然后打开 **插件管理 → 代码代理**：

| 项 | 填什么 |
| --- | --- |
| 默认代理 | `codex_cli` 或 Claude Code。没说用哪个时走这个 |
| 默认工作目录 | 自然语言没写路径时用哪个文件夹，默认当前项目 `.` |
| 超时 | 单次执行秒数，默认 300 |

Codex / Claude 自己的登录和 Key 在它们的 CLI 里完成，不写在这个插件里。
