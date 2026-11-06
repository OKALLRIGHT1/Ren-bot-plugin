import asyncio
import json
import os
import sys
from dataclasses import replace

import pytest
import psutil

from code_agent import runtime
from code_agent.runtime import CodeAgentRequest, EventDecoder, build_argv


def request(tmp_path, provider="codex_cli", **kwargs):
    req = CodeAgentRequest(provider, "dangerous-looking input $(echo nope) & | 中文", str(tmp_path),
                           '"agent path"', 5, False, True, "task")
    return replace(req, **kwargs)


@pytest.mark.parametrize("provider,session_flag", [("codex_cli", "resume"), ("deepseek_harness", "--session-id")])
@pytest.mark.parametrize("write", [False, True])
def test_argv_enforces_permissions_and_exact_resume(tmp_path, provider, session_flag, write):
    req = request(tmp_path, provider, allow_write=write, session_id="exact-id")
    argv = build_argv(req)
    assert argv[0] == "agent path"
    assert session_flag in argv and "exact-id" in argv
    assert ("workspace-write" if write else "read-only") in argv
    assert "never" in argv and "--json" in argv
    assert req.prompt not in argv and "--last" not in argv
    assert argv[-1] == "-"


@pytest.mark.parametrize("changes", [{"allow_exec": False}, {"prompt": ""},
                                     {"command_template": "codex --dangerously-bypass-approvals-and-sandbox"},
                                     {"session_id": "id & echo unsafe"}, {"session_id": "--last"}])
def test_invalid_or_unsafe_request_is_rejected(tmp_path, changes):
    with pytest.raises((ValueError, PermissionError)):
        build_argv(request(tmp_path, **changes))


@pytest.mark.parametrize("provider,events,ok", [
    ("codex_cli", [{"type": "thread.started", "thread_id": "a"},
                   {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
                   {"type": "turn.completed"}], True),
    ("codex_cli", [{"type": "turn.failed"}, {"type": "turn.completed"}], False),
    ("deepseek_harness", [{"type": "session", "sessionId": "a"},
                         {"type": "final", "sessionId": "a", "reason": {"kind": "completed"}, "text": "answer"}], True),
    ("deepseek_harness", [{"type": "final", "reason": {"kind": "aborted"}, "text": "partial"}], False),
    ("deepseek_harness", [{"type": "final", "reason": None, "text": "partial"}], False),
])
def test_decoder_requires_terminal_success(provider, events, ok):
    progress = []
    decoder = EventDecoder(provider, progress.append)
    decoder.feed(b"not-json")
    decoder.feed(b"[]")
    for event in events: decoder.feed(json.dumps(event).encode())
    assert (decoder.completed and not decoder.failed) is ok
    if ok:
        assert decoder.session_id == "a" and decoder.answer == "answer"
    assert len(progress) == len(events)


async def test_real_subprocess_streams_before_exit_and_bounds_large_output(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONUTF8", "0")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    script = tmp_path / "worker.py"
    script.write_text('''import json, sys, time
prompt = sys.stdin.read()
print(json.dumps({"type":"thread.started", "thread_id":"subprocess-session"}), flush=True)
print(json.dumps({"type":"item.completed", "item":{"type":"agent_message", "text":"x"*100000+prompt}}), flush=True)
sys.stderr.write("e"*100000)
sys.stderr.flush()
time.sleep(0.1)
print(json.dumps({"type":"turn.completed"}), flush=True)
''')
    monkeypatch.setattr(runtime, "build_argv", lambda req: [sys.executable, "-u", str(script)])
    event = asyncio.Event()
    def progress(payload): event.set()
    task = asyncio.create_task(runtime.run_code_agent(request(tmp_path), progress))
    await asyncio.wait_for(event.wait(), 2)
    assert not task.done()
    result = await task
    assert result.ok and result.session_id == "subprocess-session"
    assert len(result.stdout) <= 24000 and len(result.stderr) <= 12000
    assert result.stdout.endswith(request(tmp_path).prompt)


async def test_exit_zero_without_success_event_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "build_argv", lambda req: [sys.executable, "-c", "print('{}')"])
    result = await runtime.run_code_agent(request(tmp_path))
    assert not result.ok


@pytest.mark.parametrize("timeout", [False, True])
@pytest.mark.parametrize("parent_exits", [False, True])
async def test_cancel_or_timeout_reaps_child_process_tree(tmp_path, monkeypatch, timeout, parent_exits):
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "worker.py"
    script.write_text('''import subprocess, sys, time, pathlib
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
print('{"type":"thread.started", "thread_id":"cancel-me"}', flush=True)
''' + ("time.sleep(0.1)\n" if parent_exits else "time.sleep(60)\n"))
    monkeypatch.setattr(runtime, "build_argv", lambda req: [sys.executable, "-u", str(script), str(pid_file)])
    started = asyncio.Event()
    task = asyncio.create_task(runtime.run_code_agent(request(tmp_path, timeout_sec=1 if timeout else 30), lambda e: started.set()))
    await asyncio.wait_for(started.wait(), 3)
    child_pid = int(pid_file.read_text())
    try:
        if parent_exits:
            await asyncio.sleep(0.2)
        if not timeout: task.cancel()
        with pytest.raises(asyncio.TimeoutError if timeout else asyncio.CancelledError):
            await asyncio.wait_for(task, 10)
        try:
            child = psutil.Process(child_pid)
            if child.status() != psutil.STATUS_ZOMBIE:
                child.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
    finally:
        if psutil.pid_exists(child_pid):
            try: psutil.Process(child_pid).kill()
            except psutil.NoSuchProcess: pass
