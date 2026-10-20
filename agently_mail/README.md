# Agent Mail

通过本机 agently-cli 查询、读取、搜索和按确认流程发送邮件；支持新邮件 QQ 私聊通知。

## 怎么用

- 触发词：`agently_mail`
- 类型：`direct`
- 别名：`agently_mail`、`邮件`、`邮箱`、`收件箱`、`最近邮件`、`查邮件`、`读邮件`、`发邮件`、`回邮件`、`转发邮件`、`测试邮件通知`、`邮件通知测试`
- 示例：`最近邮件`

## 权限

可用：本地桌面、QQ 远程、QQ 主人。
不可用：QQ 他人、群聊未 @。

## 可配置项

- `model_queue`：邮件意图模型（按顺序尝试）。从主程序模型中选择推理/工具用途模型。留空时跟随 gatekeeper 任务路由。
- `cli_path`：agently-cli 路径。默认使用全局 npm 安装的 Agent Mail CLI。
- `default_limit`：默认邮件数量。列出最近邮件时默认返回多少封。
- `max_body_chars`：正文最大展示字符。读取邮件正文时最多展示多少字符。
- `request_timeout_sec`：CLI 超时秒数。每次调用 agently-cli 最多等待多久。
- `intent_timeout_sec`：草稿生成超时秒数。自然语言发信/回信时，等待模型生成邮件草稿的最长时间。
- `enable_notifications`：启用新邮件通知。开启后会在收到新邮件时主动推送到 QQ 私聊。
- `notification_check_interval_sec`：通知检查间隔(秒)。后台轮询收件箱的间隔。间隔太短会频繁拉起 CLI。
- `notification_target_sessions`：通知推送目标会话。填 session_id，例如 private:123456。
- `notification_character_name`：通知角色。新邮件摘要用哪个角色的口吻来说。下拉选项来自角色库，避免手输名字。
- `notification_poll_limit`：轮询检查数量。每次后台轮询最多检查多少封最近邮件。
- `notification_body_chars`：通知正文图片字数。推送正文图片时最多展示多少字符。
- `seen_state_path`：已读通知状态文件。记录已通知过的邮件 ID，避免重启后重复推送。
