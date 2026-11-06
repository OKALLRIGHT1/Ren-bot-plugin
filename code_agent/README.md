<!-- MANUAL README -->

# 代码代理 0.2.0

基于原 code_agent 扩展：把分析和修改交给本机 Codex、DeepSeek Harness 或 Claude Code。
提交立即返回任务编号，后台运行；普通聊天和桌面停止按钮不会取消这些任务。
结果回到最初发起的桌面或 QQ 会话，并可通过任务编号查询。

## 怎么用

```text
让 Codex 分析这个项目为什么启动失败
让 DeepSeek Harness 检查这个项目
code_agent analyze ||| codex_cli ||| C:\projects\demo ||| 检查报错
code_agent modify ||| deepseek_harness ||| C:\projects\demo ||| 修复报错并运行测试
code_agent list
code_agent status ||| 任务ID
code_agent cancel ||| 任务ID
code_agent resume ||| 任务ID ||| 按刚才的结论继续修复
code_agent retry_delivery ||| 任务ID
```

`analyze` 使用 CLI 的只读权限；`modify` 使用工作目录写权限，并沿用主程序 ActionGate 确认。
`resume` 也经过确认，沿用原代理、工作目录、权限和准确的外部会话 ID，绝不使用 `--last`。
尚未建立外部会话的任务不能继续，需要重新提交。

`status` 显示排队、执行、取消、完成、失败、中断状态及最近事件；不虚构完成百分比。
同一工作目录串行执行，不同目录默认最多同时运行两个任务。最多接受 32 个在途任务。
“完成”表示 CLI 正常退出且报告成功完成，不等于项目的所有验收项自动通过，请查看任务结果。

## 安装与 CLI 配置

从插件市场安装/更新 `code_agent`，或把整个文件夹复制到主程序 `plugins/code_agent`。
后台运行代码随插件分发，不要求替换主程序的 `modules/code_agent`。
使用 Python 3.10+；建议与主程序一样使用 Python 3.11。

- **Codex**：先安装 CLI 并完成 `codex login`。插件执行 `codex ... exec --json -`，继续时使用 `exec resume --json <ID> -`。
- **DeepSeek Harness**：安装提供 `dsh headless --json`、`--session-id`、`--permission-mode` 和 `--approval-policy` 的版本。可先用 `dsh headless --help` 检查。
  当前官方 headless 默认不读取 GUI 保存的登录，需在 DSH 的环境或配置中准备凭据；GUI 登录本身不代表 headless 可用。
  插件不创建、存储或输出 API Key。`dsh_home` 可指定已有 DSH 配置/会话目录。
- **Claude Code**：保留支持，使用 stream-json 输出与准确的 `--resume` 会话。

每种代理可以配置一个可执行文件路径；留空从 PATH 查找。
旧的 `codex exec {prompt_stdin}` / `claude -p {prompt_stdin}` 模板仍接受，但插件统一管理实际运行参数，
不接受任意 shell 命令或绕过权限的模板参数。提示词通过 stdin 传递，不拼接 shell 命令。
默认单次超时 1800 秒，可设置 1–86400 秒。
CLI 需要额外批准的操作在无人值守模式下应拒绝或失败，插件不会自动放宽到完全访问。

接口依据：[Codex 非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)、
[DSH headless 协议](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/headless/README.md)。
旧版本缺少这些参数时会明确失败，不退回无进度或不受约束的执行方式。

## 会话、取消与恢复

- 本地和主人 QQ 私聊共用任务访问范围，但完成通知仍回最初的发起渠道；不会跟随当前活跃聊天。
- 群聊任务范围独立，其他 QQ 用户不能查询、取消或继续主人的任务。启动仍受主程序的群聊高风险权限限制。
- `cancel`、超时和正常插件停用会等待进程树清理；取消不会撤销代理已写入的文件。
- 原子保存任务记录到主程序数据目录 `code_agent/tasks.json`，支持 `SUZU_DATA_DIR` 或插件 `state_path` 覆盖。
  不保存在插件安装目录，升级不会丢失。保留最近 200 条已结束任务，每条保留最近 30 个进度事件。
- 重启后未结束的任务标记“已中断”，不会自动再次执行。外部 CLI 的会话文件也必须保留才能继续。
- 回传失败单独记录，可用 `retry_delivery` 重发，任务本身不会重跑。
  旧版主程序文本发送接口不返回投递结果时只能标记“已提交发送”；更新主程序的网关返回值修复后可确认失败。
  网络响应丢失时人工重发仍可能产生重复通知，插件不声称网络端恰好一次投递。

任务原文和结果保存在本机任务存档；输出在展示和持久化前做常见凭据脱敏，不保存完整工具参数或思考内容。
结果最多保留 24000 字符，聊天回传最多展示其中 12000 字符；代码变更以实际工作目录为准。

## 测试

插件仓库 `tests/test_code_agent_jobs.py`、`tests/test_code_agent_runtime.py` 覆盖会话、后台生命周期、恢复、
发送失败、权限参数、结构化事件及真实子进程树取消。测试不调用模型、不读取真实登录、不扣费。
运行方法见仓库根 README。
