<!-- MANUAL README -->

# Agent Mail

通过本机 `agently-cli` 查信、读信、搜索；写信/回复会先出草稿再确认。也可以把新邮件推到 QQ 私聊。

## 怎么用

- `最近邮件`、`查邮件`
- `读邮件`（按她列出的编号）
- `发邮件` / `回邮件` / `转发邮件`（会先给草稿）
- `测试邮件通知`

## 权限

- 本地可用
- QQ 仅主人
- 其他人不可用

## 要准备的环境

1. 本机安装 [agently-cli](https://www.npmjs.com/package/agently-cli)，并在 CLI 里登录你的邮箱。
2. 打开 **插件管理 → Agent Mail**：

| 项 | 填什么 |
| --- | --- |
| agently-cli 路径 | 默认是当前 Windows 用户的 npm 全局命令，例如 `C:\Users\<你>\AppData\Roaming\npm\agently-cli.cmd`。换电脑必改 |
| 启用新邮件通知 | 默认开 |
| 通知推送目标会话 | `private:QQ号`。默认值是作者自己的号码，请改成你的 |
| 通知角色 | 用哪个角色的口吻念摘要 |

邮箱密码/OAuth 在 agently-cli 自己的登录流程里，不要写进这个插件。

路径还是别人的、或通知会话还是示例 QQ 号时，查信和推送都会对不上。
