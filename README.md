# Ren-bot 插件仓库

这是 Ren-bot / live2d-llm 的可选插件来源。主程序以后只从这里的清单发现、下载可选插件。

当前仓库是源码目录，还不是安装包。每个插件一个文件夹，里面保持 `config.json` 和 `plugin.py`。`index.json` 是市场清单，先列出名称、版本和目录。单个插件的版本 zip 和 sha256 还没发。

## 没有放进来的核心插件

这些插件跟主程序绑在一起，继续留在主仓库：

- search
- web_reader
- memory_tools
- workspace_ops
- user_files

`plugins/plugin_utils.py` 也留在主程序里。

技能运行时（`skill_runtime`）和 MCP 工具桥（`mcp_tools`）不进这个仓库。MCP 从一开始就没上传。

## 这份副本清掉的本机信息

上传前清掉了本机路径、QQ 会话号和点歌音频缓存。你电脑上的 `live2d-llm/plugins` 没有改动。

- 邮件插件的命令路径改成 `agently-cli`，通知会话留空
- 日报的定时推送目标留空
- 本地知识库去掉绝对路径
- 本地音乐目录留空
- 不包含 `qq_music/data/cache` 里已下载的歌曲

装到别人机器上之后，这些项要在插件设置里重新填。
