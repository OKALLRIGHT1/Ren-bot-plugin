from __future__ import annotations

import re
import os
import inspect
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .runtime import CodeAgentRequest, build_argv, discover_agent_command, run_code_agent
from .jobs import TaskManager, origin_from_context
from modules.security_redaction import redact_sensitive_text
from services.capability_manager import ToolCapability, ToolCapabilityMatch


class Plugin:
    name = "代码代理"
    type = "direct"
    description = "把代码项目分析或修改任务委托给本机 Codex / DeepSeek Harness / Claude Code，支持后台进度、取消和继续。"
    aliases = ["code_agent", "codex", "Codex", "claude code", "Claude Code", "cc", "dsh", "DeepSeek Harness"]
    allow_natural_language_direct = True
    gated_action = "system.code_agent"
    tool_examples = [
        "让 Codex 分析这个项目为什么启动失败",
        "用 Claude Code 修改 README",
        "code_agent analyze ||| codex_cli ||| . ||| 检查报错",
    ]

    def __init__(
        self,
        *,
        runner: Callable[[CodeAgentRequest], Any] | None = None,
        discoverer: Callable[[str], str] | None = None,
    ) -> None:
        self._runner = runner or run_code_agent
        self._discoverer = discoverer or discover_agent_command
        self.settings: Dict[str, Any] = {}
        self._manager = None
        self._gateway = None
        self._app = None
        self._local_sender = None
        self._conversation_events = None
        self._root = Path.cwd()

    def _capture(self, ctx):
        from services.plugin_ports import resolve_gateway, resolve_app
        self._gateway = resolve_gateway(ctx) or self._gateway
        self._app = resolve_app(ctx) or self._app
        self._local_sender = ctx.get("send_bubble") or self._local_sender
        self._conversation_events = ctx.get("conversation_event_service") or self._conversation_events
        if ctx.get("app_root"):
            self._root = Path(ctx["app_root"])

    async def start(self, ctx=None):
        self._capture(ctx or {})
        if self._manager is not None and self._manager._closing:
            self._manager = None
        self._jobs()

    async def stop(self):
        if self._manager is not None:
            await self._manager.stop()

    def _jobs(self):
        if self._manager is None:
            default = Path(os.environ.get("SUZU_DATA_DIR") or self._root / "data") / "code_agent" / "tasks.json"
            path = Path(self._setting("state_path", "") or default).expanduser()
            if not path.is_absolute():
                path = self._root / path
            self._manager = TaskManager(path, self._run_job, self._deliver,
                                        parallel=self._setting_int("max_parallel", 2))
        return self._manager

    async def _run_job(self, request, on_event):
        # Preserve the existing injectable runner contract for hosts/tests.
        if len(inspect.signature(self._runner).parameters) == 1:
            return await self._runner(request)
        return await self._runner(request, on_event)

    async def _deliver(self, job):
        origin = job["origin"]
        text = self._job_text(job)
        if "channel_meta" in origin:
            if self._gateway is None:
                raise RuntimeError("QQ 网关不可用，可稍后重发结果")
            sent = await self._gateway.send_text(text, origin)
        else:
            app = self._app.get_app() if self._app is not None else None
            if app is not None and getattr(app, "event_bus", None) is not None:
                await app.event_bus.emit("ui.append", role="assistant", text=text)
                sent = True
            elif callable(self._local_sender):
                sent = self._local_sender(text)
                if inspect.isawaitable(sent):
                    sent = await sent
            else:
                raise RuntimeError("桌面输出不可用，可稍后重发结果")
        if sent is not False and not (isinstance(sent, dict) and not sent.get("ok")):
            if self._conversation_events is not None:
                # A history failure must not cause a duplicate network delivery.
                try:
                    self._conversation_events.record_assistant_message(
                        ctx=origin, text=text, metadata={"plugin": "code_agent", "task_id": job["id"]})
                except Exception:
                    pass
        return sent

    def _submit(self, request, ctx):
        scope, origin = origin_from_context(ctx)
        build_argv(request)
        job = self._jobs().submit(request, scope, origin)
        return f"已提交后台任务 {job['id']}（{self._provider_label(request.provider)}）。\n用 code_agent status ||| {job['id']} 查看进度；结果会返回发起会话。"

    def _job_text(self, job):
        labels = {"queued": "排队中", "running": "执行中", "cancelling": "取消中", "completed": "完成",
                  "failed": "失败", "cancelled": "已取消", "interrupted": "已中断"}
        lines = [f"代码代理任务 {job['id']}：{labels.get(job['status'], job['status'])}"]
        lines += job.get("events", [])[-5:]
        if job.get("result"):
            lines.append(job["result"][-12000:])
        if job.get("error"):
            lines.append(job["error"])
        if job.get("delivery") == "failed":
            lines.append("结果回传失败，可用 retry_delivery 重发；任务不会重新执行。")
        return "\n".join(lines)

    def get_tool_schema(self):
        return {"name": "code_agent", "description": self.description,
                "parameters": {"type": "object", "properties": {
                    "action": {"type": "string", "enum": ["analyze", "modify", "list", "status", "cancel", "resume", "retry_delivery"]},
                    "provider": {"type": "string", "enum": ["codex_cli", "deepseek_harness", "claude_code"]},
                    "cwd": {"type": "string"}, "prompt": {"type": "string"}, "task_id": {"type": "string"}},
                    "required": ["action"]}}

    def format_invocation(self, payload):
        action = str(payload.get("action") or "help")
        if action in {"analyze", "modify"}:
            return " ||| ".join([action, str(payload.get("provider") or self._default_provider()),
                                  str(payload.get("cwd") or self._default_cwd()), str(payload.get("prompt") or "")])
        return " ||| ".join([action, str(payload.get("task_id") or ""), str(payload.get("prompt") or "")])

    def resolve_gated_action(self, args: str, ctx: Optional[Dict[str, Any]] = None) -> str:
        action = (args or "").removeprefix("code_agent").strip().split("|||", 1)[0].strip().lower()
        if action in {"", "help", "status", "list", "cancel", "retry_delivery"}:
            return ""  # no gate for status/help
        return "system.code_agent"

    def get_capabilities(self):
        return [
            ToolCapability(
                id="code_agent.codex_task",
                plugin="code_agent",
                trigger_mode="natural",
                match=lambda text, ctx: self._match_agent_task(
                    text, ctx, provider="codex_cli"
                ),
                description="委托 Codex CLI 分析或修改代码项目",
                examples=["让 Codex 分析这个项目为什么启动失败"],
            ),
            ToolCapability(
                id="code_agent.dsh_task", plugin="code_agent", trigger_mode="natural",
                match=lambda text, ctx: self._match_agent_task(text, ctx, provider="deepseek_harness"),
                description="委托 DeepSeek Harness 后台分析或修改项目",
                examples=["让 DeepSeek Harness 检查这个项目"],
            ),
            ToolCapability(
                id="code_agent.claude_task",
                plugin="code_agent",
                trigger_mode="natural",
                match=lambda text, ctx: self._match_agent_task(
                    text, ctx, provider="claude_code"
                ),
                description="委托 Claude Code 分析或修改代码项目",
                examples=["用 Claude Code 修改 README"],
            ),
        ]

    def should_handle_direct(self, text: str, context: Dict[str, Any], key: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        if raw.lower().startswith(("code_agent ", "code_agent\n")):
            return True
        if re.search(
            r"(画图|画画|画一张|绘图|生图|生成图|生成图片|图片生成|发图)",
            raw,
            flags=re.IGNORECASE,
        ):
            return False  # 画图归 qq_draw，不委托代码代理
        provider, _ = self._detect_provider(raw)
        if not provider:
            return False
        return bool(
            re.search(
                r"(分析|检查|查看|看一下|看看|读一下|审查|排查|修复|修改|重构|改一下|处理|接手|帮我)",
                raw,
                flags=re.IGNORECASE,
            )
        )

    def _match_agent_task(
        self,
        text: str,
        ctx: Dict[str, Any],
        *,
        provider: str,
    ) -> Optional[ToolCapabilityMatch]:
        raw = str(text or "").strip()
        if not raw:
            return None
        detected_provider, _ = self._detect_provider(raw)
        if detected_provider != provider:
            return None
        if not self.should_handle_direct(raw, ctx, "code_agent"):
            return None
        action = "modify" if self._looks_like_modify(raw) else "analyze"
        return ToolCapabilityMatch(
            capability_id=(
                "code_agent.claude_task"
                if provider == "claude_code"
                else "code_agent.dsh_task" if provider == "deepseek_harness" else "code_agent.codex_task"
            ),
            plugin="code_agent",
            score=0.9,
            args={"provider": provider, "action": action},
            raw_text=raw,
            reason="code_agent_provider_task",
        )

    async def run(self, args: str, ctx: Dict[str, Any]) -> Any:
        ctx = ctx or {}
        self._capture(ctx)
        try:
            scope, _origin = origin_from_context(ctx)
            control = str(args or "").removeprefix("code_agent").strip().split("|||", 2)
            verb = control[0].strip().lower()
            task_id = control[1].strip() if len(control) > 1 else ""
            if verb in {"list", "status"} and not task_id:
                jobs = self._jobs().list(scope)
                return self._status_text() + "\n" + ("\n".join(self._job_text(j) for j in jobs) or "当前会话没有任务。")
            if verb in {"status", "cancel", "resume", "retry_delivery"}:
                manager = self._jobs()
                job = manager.get(task_id, scope)
                if verb == "cancel":
                    job = await manager.cancel(task_id, scope)
                elif verb == "resume":
                    prompt = control[2].strip() if len(control) > 2 else "继续之前的任务"
                    confirmed = bool(ctx.get("action_confirmed") or ctx.get("gate_confirmed"))
                    if not confirmed:
                        return {"__agent_result__": "confirmation_required", "trigger": "code_agent",
                                "summary": f"继续任务 {task_id}，沿用原工作目录和权限。",
                                "payload": {"mode": "gate_rerun", "args": args}, "expires_in": 300}
                    manager.resume(task_id, scope, prompt)
                    return f"任务 {task_id} 已继续，结果仍返回最初发起会话。"
                elif verb == "retry_delivery":
                    if job["status"] in {"queued", "running", "cancelling"}:
                        return "任务尚未结束。"
                    await manager.notify(job)
                return self._job_text(job)
        except (ValueError, PermissionError, RuntimeError, OSError) as exc:
            return redact_sensitive_text(str(exc))
        action, provider, cwd, prompt = self._parse_request(args)
        if action in {"", "help"}:
            return self._help_text()
        if action == "status":
            return self._status_text()
        if action not in {"analyze", "modify"}:
            return f"不支持的 action: {action}\n\n{self._help_text()}"

        command_template = self._command_template(provider)
        if not command_template:
            return f"未找到 {self._provider_label(provider)} 命令，请先安装或在设置里配置命令模板。"

        gate_confirmed = bool(
            (ctx or {}).get("action_confirmed") or (ctx or {}).get("gate_confirmed")
        )
        request = self._build_request(
            provider=provider,
            cwd=cwd,
            prompt=prompt,
            command_template=command_template,
            action=action,
            ctx=ctx,
            force_exec=gate_confirmed,
        )

        # ActionGate already handles confirmation (local popup or chat “确认”).
        # Keep a plugin-level fallback only when gate was bypassed and action is modify.
        if action == "modify" and not gate_confirmed:
            if not request.allow_exec:
                return self._exec_permission_message()
            return {
                "__agent_result__": "confirmation_required",
                "trigger": "code_agent",
                "summary": (
                    f"将使用 {self._provider_label(provider)} 修改 {request.cwd}。\n"
                    "确认后会启动外部代码代理执行。"
                ),
                "payload": {
                    "provider": provider,
                    "cwd": request.cwd,
                    "prompt": prompt,
                    "command_template": command_template,
                    "timeout_sec": request.timeout_sec,
                    "allow_write": True,
                    "task_id": request.task_id,
                    "mode": "code_agent_run",
                    "action": action,
                },
                "expires_in": 300,
            }

        if not request.allow_exec:
            return self._exec_permission_message()
        try:
            return self._submit(request, ctx)
        except (ValueError, PermissionError, RuntimeError, OSError) as exc:
            return redact_sensitive_text(str(exc))

    async def confirm_agent_action(self, payload: Dict[str, Any], ctx: Dict[str, Any]) -> str:
        self._capture(ctx or {})
        runtime = dict(ctx or {})
        runtime["action_confirmed"] = True
        runtime["gate_confirmed"] = True
        # Prefer gate_rerun args when present
        if str(payload.get("mode") or "") == "gate_rerun" and payload.get("args") is not None:
            result = await self.run(str(payload.get("args") or ""), runtime)
            return str(result)
        provider = str(payload.get("provider") or "codex_cli").strip()
        request = CodeAgentRequest(
            provider=provider,
            prompt=str(payload.get("prompt") or "").strip(),
            cwd=str(payload.get("cwd") or ".").strip(),
            command_template=str(payload.get("command_template") or "").strip(),
            timeout_sec=int(payload.get("timeout_sec") or self._setting_int("timeout_sec", 300)),
            allow_write=bool(payload.get("allow_write", True)),
            # Confirmed path may run without separate code-assistant allow_exec flag
            allow_exec=True,
            task_id=str(payload.get("task_id") or uuid.uuid4().hex[:16]),
            dsh_home=str(self._setting("dsh_home", "") or ""),
        )
        try:
            return self._submit(request, ctx)
        except (ValueError, PermissionError, RuntimeError, OSError) as exc:
            return redact_sensitive_text(str(exc))

    def _parse_request(self, raw: str) -> Tuple[str, str, str, str]:
        text = str(raw or "").strip()
        if text.lower().startswith("code_agent"):
            text = text[len("code_agent") :].strip()
        parts = [p.strip() for p in text.split("|||", 3)]
        action = parts[0].strip().lower() if parts else ""
        if action in {"", "help", "status"}:
            return action, self._default_provider(), self._default_cwd(), ""
        if action in {"analyze", "modify"}:
            provider = self._normalize_provider(parts[1] if len(parts) >= 2 else "")
            cwd = parts[2] if len(parts) >= 3 else self._default_cwd()
            prompt = parts[3] if len(parts) >= 4 else ""
            return action, provider or self._default_provider(), cwd or self._default_cwd(), prompt

        provider, stripped = self._detect_provider(text)
        provider = provider or self._default_provider()
        action = "modify" if self._looks_like_modify(text) else "analyze"
        cwd = self._extract_cwd(text) or self._default_cwd()
        prompt = stripped or text
        return action, provider, cwd, prompt

    def _detect_provider(self, text: str) -> Tuple[str, str]:
        raw = str(text or "")
        lowered = raw.lower()
        if "deepseek harness" in lowered or re.search(r"\bdsh\b", lowered):
            return "deepseek_harness", re.sub(r"deepseek harness|\bdsh\b", "", raw, flags=re.IGNORECASE).strip()
        if "claude code" in lowered:
            return "claude_code", re.sub("claude code", "", raw, flags=re.IGNORECASE).strip()
        if re.search(r"(^|[^\w])cc([^\w]|$)", lowered):
            return "claude_code", re.sub(r"(^|[^\w])cc([^\w]|$)", " ", raw, flags=re.IGNORECASE).strip()
        if "codex" in lowered:
            return "codex_cli", re.sub("codex", "", raw, flags=re.IGNORECASE).strip()
        return "", raw.strip()

    def _looks_like_modify(self, text: str) -> bool:
        return bool(
            re.search(
                r"(修改|修复|重构|改一下|写入|生成|新增|删除|移动|安装|打包)",
                str(text or ""),
                flags=re.IGNORECASE,
            )
        )

    def _extract_cwd(self, text: str) -> str:
        match = re.search(r"([A-Za-z]:\\[^\s，。]+|[./][^\s，。]+)", str(text or ""))
        return match.group(1).strip() if match else ""

    def _normalize_provider(self, provider: str) -> str:
        raw = str(provider or "").strip().lower().replace("-", "_").replace(" ", "_")
        if raw in {"dsh", "deepseek", "deepseek_harness"}:
            return "deepseek_harness"
        if raw in {"codex", "codex_cli"}:
            return "codex_cli"
        if raw in {"claude", "claude_code", "cc"}:
            return "claude_code"
        return raw

    def _build_request(
        self,
        *,
        provider: str,
        cwd: str,
        prompt: str,
        command_template: str,
        action: str,
        ctx: Dict[str, Any],
        force_exec: bool = False,
    ) -> CodeAgentRequest:
        allow_exec = bool(ctx.get("allow_exec", False)) or bool(force_exec)
        return CodeAgentRequest(
            provider=provider,
            prompt=str(prompt or "").strip(),
            cwd=str(Path(self._resolve_cwd(cwd, ctx)).expanduser().resolve()),
            command_template=command_template,
            timeout_sec=max(1, min(86400, self._setting_int("timeout_sec", 1800))),
            allow_write=action == "modify",
            allow_exec=allow_exec,
            task_id=uuid.uuid4().hex[:16],
            dsh_home=str(self._setting("dsh_home", "") or ""),
        )

    def _command_template(self, provider: str) -> str:
        setting_key = f"{provider}_command_template"
        configured = str(self._setting(setting_key, "") or "").strip()
        return configured or self._discoverer(provider)

    def _format_result(self, result: Any) -> str:
        ok = bool(getattr(result, "ok", False))
        status = "完成" if ok else "失败"
        stdout = str(getattr(result, "stdout", "") or "").strip()
        stderr = str(getattr(result, "stderr", "") or "").strip()
        exit_code = getattr(result, "exit_code", "")
        command_preview = str(getattr(result, "command_preview", "") or "").strip()
        lines = [f"代码代理{status} (exit={exit_code})"]
        if command_preview:
            lines.append(f"命令: {command_preview}")
        if stdout:
            lines.append(redact_sensitive_text(stdout))
        if stderr:
            lines.append("stderr:\n" + redact_sensitive_text(stderr))
        return "\n".join(lines)

    def _status_text(self) -> str:
        rows = []
        for provider in ("codex_cli", "deepseek_harness", "claude_code"):
            template = self._command_template(provider)
            rows.append(f"- {self._provider_label(provider)}: {'可用' if template else '未找到'}")
        return "代码代理状态\n" + "\n".join(rows)

    def _help_text(self) -> str:
        return (
            "code_agent 用法：\n"
            "- code_agent list / code_agent status\n"
            "- code_agent status ||| 任务ID\n"
            "- code_agent cancel ||| 任务ID\n"
            "- code_agent resume ||| 任务ID ||| 继续指令\n"
            "- code_agent retry_delivery ||| 任务ID\n"
            "- code_agent analyze ||| deepseek_harness ||| . ||| 检查报错\n"
            "- code_agent analyze ||| codex_cli ||| . ||| 检查启动失败\n"
            "- code_agent modify ||| claude_code ||| . ||| 修改 README\n"
            "自然语言示例：让 Codex 分析这个项目为什么启动失败"
        )

    def _exec_permission_message(self) -> str:
        return (
            "代码代理需要执行许可才能启动外部 Codex/Claude。"
            "请直接说明要分析或修改的项目，确认后再执行。"
        )

    def _provider_label(self, provider: str) -> str:
        if provider == "deepseek_harness":
            return "DeepSeek Harness"
        if provider == "claude_code":
            return "Claude Code"
        return "Codex"

    def _setting(self, key: str, default: Any) -> Any:
        value = (self.settings or {}).get(key, default)
        if isinstance(value, dict):
            return value.get("default", default)
        return value

    def _setting_int(self, key: str, default: int) -> int:
        try:
            return int(self._setting(key, default))
        except (TypeError, ValueError):
            return int(default)

    def _default_provider(self) -> str:
        return self._normalize_provider(str(self._setting("default_provider", "codex_cli"))) or "codex_cli"

    def _default_cwd(self) -> str:
        return str(self._setting("default_cwd", ".") or ".").strip() or "."

    def _resolve_cwd(self, requested: str, ctx: Dict[str, Any]) -> str:
        raw = str(requested or "").strip()
        if raw and raw != ".":
            return raw
        for key in ("code_path", "app_root", "cwd"):
            value = str((ctx or {}).get(key) or "").strip()
            if value:
                return value
        return raw or self._default_cwd()
