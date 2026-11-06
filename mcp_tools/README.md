<!-- MANUAL README -->

# MCP 工具桥 0.1.0

可独立安装的 MCP 客户端插件。协议实现、服务器发现、连接清理和 Python `mcp` 依赖均归本插件管理。
主程序不再需要启动内置 MCP 服务；代码代理插件通过 CLI 工作，也不依赖本插件。

## 怎么用

从插件市场安装 `mcp_tools`，然后在**主程序使用的 Python 环境**安装可选依赖：

```text
python -m pip install -r plugins/mcp_tools/requirements.txt
```

打开插件管理 → MCP 工具桥，配置 `servers` 数组，例如：

```json
[
  {"name": "demo", "transport": "stdio", "command": "python", "args": ["C:/tools/server.py"], "timeout_sec": 20},
  {"name": "local_http", "transport": "streamable_http", "url": "http://127.0.0.1:8000/mcp", "enabled": false}
]
```

按需设置 `allowed_server_names: ["demo"]`，或更细地设置 `allowed_tool_names: ["mcp.demo.read"]`。
服务器名中的特殊字符会被桥接层转换为下划线；允许列表使用列出的工具名里的服务器 slug。
默认拒绝调用全部工具；仅配置服务器不会自动授予工具调用权限。

```text
[CMD: mcp_tools | list_tools]
[CMD: mcp_tools | server_status]
[CMD: mcp_tools | call_tool ||| mcp.demo.read ||| {"path":"README.md"}]
```

只允许本地使用，QQ 包括主人也不开放。`list_tools` 会刷新发现结果；
模型工具 schema 只读取缓存，不会在构造提示词时启动服务器或阻塞界面。
服务器配置中的 `env` / `headers` 可用于显式传递必要配置；stdio 子进程默认不继承主程序的 API Key。

## 从主程序迁移

旧的主程序 MCP 桥接实现已迁入这里的 `bridge.py`，包含初始化失败、取消、超时的资源清理修复。
配套主程序补丁保留旧导入路径的转发层，便于已有扩展升级；它不包含第二份协议实现。
插件也可在尚未更新转发层的旧主程序上工作，因为它只导入自己的桥接代码。

原有服务器与允许列表设置请保留在本插件配置中；不会自动复制其他插件的私有配置或凭据。
卸载/停用会取消正在执行的调用并等待连接关闭，不留下常驻 MCP 连接。
同步 `configure_remote_servers` 仅作为旧扩展兼容 API；本插件使用异步发现接口。

## 测试

仓库测试覆盖 stdio、HTTP 初始化/调用/列举工具取消、真实超时语义、部分初始化失败、
退出异常、允许列表、禁用 QQ、异步发现和插件停用。MCP 传输使用模拟资源，不连接实际服务。
