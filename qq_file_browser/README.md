# QQ文件浏览

在 QQ 中安全浏览 /bot 虚拟目录并发送文件（零拷贝）。

## 怎么用

- 触发词：`qq文件`
- 类型：`direct`
- 别名：`/文件`、`/ls`、`/dir`、`/cd`、`/get`、`/pwd`、`/help`、`[文件]`
- 示例：`/文件 /ls`

## 权限

可用：QQ 远程、QQ 主人。
不可用：本地桌面、QQ 他人、群聊未 @。

## 可配置项

- `extra_mounts`：额外挂载目录。格式为 别名|本地路径，例如 qqsave|D:\QQDownloads。保存后可在 QQ 里用 /cd /qqsave 进入。
- `inbox_mount`：接收文件目录。QQ 发给机器人的文件会保存到这个虚拟目录，默认 /bot/inbox。
