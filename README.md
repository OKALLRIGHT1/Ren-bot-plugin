# Ren-bot 插件仓库

这是 [Ren-bot](https://github.com/OKALLRIGHT1/Ren-bot) 的可选插件仓库。

Ren-bot 是一套跑在本机的 Live2D 助手，可以桌面聊天，也可以通过 QQ 远程对话。主程序自己带着搜索、记忆、工作区这类核心能力；表情包、点歌、日报、骰子等可选功能从本仓库安装。

- 主程序：https://github.com/OKALLRIGHT1/Ren-bot
- 本仓库：https://github.com/OKALLRIGHT1/Ren-bot-plugin

## 插件长什么样

每个插件一个文件夹，至少包含：

- `config.json`：名称、触发词、权限
- `plugin.py`：插件入口

根目录的 `index.json` 是市场清单。主程序读取这份清单后，按插件下载并安装到本机。
