"""Subprocess adapter evolved from Ren-bot's modules/code_agent runner.

No model API or credentials are owned by this module. Prompts go over stdin;
the installed CLI owns its authentication, sandbox and persisted sessions.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class CodeAgentRequest:
    provider: str
    prompt: str
    cwd: str
    command_template: str
    timeout_sec: int
    allow_write: bool
    allow_exec: bool
    task_id: str
    session_id: str = ""
    dsh_home: str = ""


@dataclass(frozen=True)
class CodeAgentResult:
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_sec: float
    command_preview: str
    session_id: str = ""


def discover_agent_command(provider: str) -> str:
    names = {"codex_cli": "codex", "deepseek_harness": "dsh", "claude_code": "claude"}
    name = names.get(provider)
    if not name:
        return ""
    path = shutil.which(name)
    return f'"{path}"' if path else ""


def build_argv(request: CodeAgentRequest) -> list[str]:
    if not request.allow_exec:
        raise PermissionError("代码代理需要执行许可")
    if not request.prompt.strip():
        raise ValueError("任务内容不能为空")
    if len(request.prompt.encode("utf-8")) > 32768:
        raise ValueError("任务指令过长，请限制在 32 KiB 内")
    if request.session_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", request.session_id):
        raise ValueError("外部会话 ID 无效，拒绝将其传给命令行")
    if not Path(request.cwd).is_dir():
        raise ValueError("工作目录不存在")
    parts = shlex.split(request.command_template, posix=os.name != "nt")
    if not parts:
        raise ValueError("未找到代理命令")
    # Legacy templates consisted of executable + exec/-p + prompt placeholder.
    # Only the executable is configurable; this adapter owns all policy flags.
    if any(p not in {"exec", "-p", "{prompt_stdin}", "{prompt}"} for p in parts[1:]):
        raise ValueError("请配置可执行文件路径；运行参数由插件统一管理")
    executable = parts[0].strip('"')
    if any(c in executable for c in "\r\n|&;<>`$"):
        raise ValueError("可执行文件路径包含不支持的字符")
    mode = "workspace-write" if request.allow_write else "read-only"
    if request.provider == "codex_cli":
        argv = [executable, "--sandbox", mode, "--ask-for-approval", "never", "exec"]
        if request.session_id:
            argv += ["resume", "--json", request.session_id]
        else:
            argv += ["--json"]
        return argv + ["-"]
    if request.provider == "deepseek_harness":
        argv = [executable, "headless", "--json", "--permission-mode", mode,
                "--approval-policy", "never"]
        if request.session_id:
            argv += ["--session-id", request.session_id]
        return argv + ["-"]
    if request.provider == "claude_code":
        argv = [executable, "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "acceptEdits" if request.allow_write else "plan"]
        if request.session_id:
            argv += ["--resume", request.session_id]
        return argv
    raise ValueError(f"不支持的代理: {request.provider}")


class EventDecoder:
    def __init__(self, provider: str, callback: Callable[[dict], None]):
        self.provider = provider
        self.callback = callback
        self.session_id = ""
        self.answer = ""
        self.completed = False
        self.failed = False

    def feed(self, raw: bytes) -> None:
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return  # CLI diagnostics are not a successful result.
        if not isinstance(event, dict):
            return
        kind = event.get("type", "")
        if self.provider == "codex_cli":
            if kind == "thread.started":
                self.session_id = str(event.get("thread_id") or "")
            item = event.get("item") or {}
            if kind == "item.completed" and item.get("type") == "agent_message":
                self.answer = str(item.get("text") or "")[-24000:]
            self.completed |= kind == "turn.completed"
            self.failed |= kind in {"turn.failed", "error"}
            detail = item.get("type", "")
        elif self.provider == "deepseek_harness":
            if kind in {"session", "final"}:
                self.session_id = str(event.get("sessionId") or self.session_id)
            if kind == "final":
                self.answer = str(event.get("text") or "")[-24000:]
                self.completed = (event.get("reason") or {}).get("kind") == "completed"
                self.failed |= not self.completed
            self.failed |= kind == "error"
            detail = str(event.get("status") or event.get("name") or "")
        else:
            self.session_id = str(event.get("session_id") or self.session_id)
            if kind == "result":
                self.answer = str(event.get("result") or "")[-24000:]
                self.completed = not bool(event.get("is_error"))
                self.failed |= not self.completed
            detail = str(event.get("subtype") or "")
        # Progress intentionally excludes reasoning, tool arguments and commands.
        self.callback({"type": str(kind)[:100], "detail": str(detail)[:200],
                       "session_id": self.session_id})


class WindowsProcessJob:
    """Kill descendants when the worker ends, even if its parent already exited."""
    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", w.DWORD), ("minimum_ws", ctypes.c_size_t),
                        ("maximum_ws", ctypes.c_size_t), ("active_limit", w.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class Counters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", Counters), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.api.OpenProcess.restype = w.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        process = None
        try:
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = self.api.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
            if not process or not self.api.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise
        finally:
            if process:
                self.api.CloseHandle(process)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


async def terminate_process_tree(proc) -> None:
    if os.name == "nt":
        if proc.returncode is None:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(proc.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await killer.wait()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await proc.wait()


async def run_code_agent(request: CodeAgentRequest, on_event=lambda event: None) -> CodeAgentResult:
    argv = build_argv(request)
    started = time.monotonic()
    env = dict(os.environ)
    if request.dsh_home and request.provider == "deepseek_harness":
        env["DSH_HOME"] = str(Path(request.dsh_home).expanduser().resolve())
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(Path(request.cwd).resolve()), env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, **kwargs,
    )
    job = None
    if os.name == "nt":
        try:
            job = WindowsProcessJob(proc.pid)
        except OSError:
            await terminate_process_tree(proc)
            raise RuntimeError("无法建立 Windows 子进程清理范围，任务未继续执行")
    decoder = EventDecoder(request.provider, on_event)
    stderr = ""

    async def read_events():
        # read() avoids StreamReader's 64 KiB readline limit; bound malformed lines.
        pending = b""
        limit = 2 * 1024 * 1024
        dropping = False
        while chunk := await proc.stdout.read(16384):
            for part in chunk.splitlines(keepends=True):
                if not dropping:
                    pending += part
                    if len(pending) > limit:
                        pending = b""
                        dropping = True
                if part.endswith(b"\n"):
                    if not dropping:
                        decoder.feed(pending)
                    else:
                        decoder.failed = True
                    pending, dropping = b"", False
        if pending:
            decoder.feed(pending)

    async def read_errors():
        nonlocal stderr
        while chunk := await proc.stderr.read(8192):
            stderr = (stderr + chunk.decode("utf-8", errors="replace"))[-12000:]

    async def communicate():
        try:
            proc.stdin.write(request.prompt.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdin.close()
        await asyncio.gather(read_events(), read_errors(), proc.wait())

    io_task = asyncio.create_task(communicate())
    try:
        await asyncio.wait_for(asyncio.shield(io_task), timeout=max(1, request.timeout_sec))
    except BaseException:
        # Keep stream readers alive until the process exits, otherwise full pipes
        # can deadlock cleanup. Cancellation only finishes after child cleanup.
        if job is not None:
            job.close()
        cleanup = asyncio.create_task(terminate_process_tree(proc))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
        finally:
            io_task.cancel()
            await asyncio.gather(io_task, return_exceptions=True)
        raise
    finally:
        if job is not None:
            job.close()
    ok = proc.returncode == 0 and decoder.completed and not decoder.failed
    if not ok and not stderr:
        stderr = "代理未报告成功完成；请查看 CLI 配置或任务进度。"
    return CodeAgentResult(ok, decoder.answer, stderr, proc.returncode,
                           time.monotonic() - started, Path(argv[0]).name,
                           decoder.session_id)
