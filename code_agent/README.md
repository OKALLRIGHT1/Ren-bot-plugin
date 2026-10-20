# 代码代理

把代码项目分析或修改任务委托给本机 Codex CLI / Claude Code。修改模式必须确认。

## 怎么用

- 触发词：`code_agent`
- 类型：`direct`
- 别名：`code_agent`、`codex`、`Codex`、`claude code`、`Claude Code`、`cc`
- 示例：`analyze ||| codex_cli ||| . ||| 检查项目为什么启动失败`

## 权限

可用：本地桌面、QQ 远程、QQ 主人。
不可用：QQ 他人、群聊未 @。

## 可配置项

- `default_provider`：default_provider。未明确指定 Codex/Claude 时使用的外部代码代理。
- `default_cwd`：default_cwd。自然语言未包含路径时使用的工作目录。
- `timeout_sec`：timeout_sec。外部代码代理单次执行超时秒数。
