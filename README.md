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

## 代码代理与 MCP

- [代码代理 0.2.0](code_agent/README.md)：Codex / DeepSeek Harness 后台任务、进度、取消、继续、原会话回传。
- [MCP 工具桥 0.1.0](mcp_tools/README.md)：独立的可选 MCP 客户端，协议实现和依赖随插件安装。

两者可以分别安装。代码代理不依赖 MCP；MCP 默认仅本地使用，并要求配置工具允许列表。
主程序旧版本也可安装这两个插件；配套主程序补丁用于移除重复 MCP 实现及向插件返回 QQ 发送结果。

## 开发与测试

测试依赖主程序的公共插件接口。准备 Ren-bot 源码并指定 `REN_BOT_ROOT`，无需安装它的全部 GUI/语音依赖：

```powershell
python -m pip install -r requirements-test.txt
$env:REN_BOT_ROOT = "C:\projects\Ren-bot"
python -m pytest -q
```

Linux/macOS 使用 `REN_BOT_ROOT=/path/to/Ren-bot python -m pytest -q`。
回归测试不调用真实模型、QQ 或 MCP 服务；进程取消测试会启动本地 Python 测试子进程。
CI 在 Windows 和 Linux 上运行同一组测试。
