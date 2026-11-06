import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from code_agent.jobs import TaskManager, origin_from_context
from code_agent.plugin import Plugin
from code_agent.runtime import CodeAgentRequest, CodeAgentResult


def request(tmp_path, task_id="one", provider="codex_cli"):
    return CodeAgentRequest(provider, "check", str(tmp_path), "codex", 60, False, True, task_id)


def result(session="session-one", ok=True):
    return CodeAgentResult(ok, "done", "", 0 if ok else 1, 1, "codex", session)


async def finish(manager):
    await asyncio.gather(*list(manager.tasks.values()))
    await asyncio.sleep(0)


async def test_background_progress_cancel_resume_preserves_origin(tmp_path):
    started = asyncio.Event()
    released = asyncio.Event()
    cleanup = asyncio.Event()
    calls, delivered = [], []

    async def runner(req, emit):
        calls.append(req)
        emit({"type": "thread.started", "session_id": "exact-session"})
        emit({"type": "item.started", "detail": "command_execution"})
        started.set()
        try:
            await released.wait()
        finally:
            cleanup.set()
        return result("exact-session")

    async def deliver(job):
        delivered.append(job)
        return True

    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    scope, origin = origin_from_context({"source": "qq_gateway", "channel_meta": {
        "is_owner": True, "user_id": "1", "session_id": "private:1"}})
    job = manager.submit(request(tmp_path), scope, origin)
    origin["channel_meta"]["session_id"] = "private:other"
    assert job["status"] == "queued"
    await asyncio.wait_for(started.wait(), 1)
    assert job["status"] == "running"
    assert job["events"][-1] == "item.started command_execution"
    assert json.loads(manager.path.read_text())["jobs"]["one"]["session_id"] == "exact-session"
    await manager.cancel("one", scope)
    assert cleanup.is_set()
    assert job["status"] == "cancelled"
    released.set()
    manager.resume("one", "owner_shared", "continue")
    await finish(manager)
    assert calls[-1].session_id == "exact-session"
    assert calls[-1].cwd == str(tmp_path)
    assert calls[-1].prompt == "continue"
    assert delivered[-1]["origin"]["channel_meta"]["session_id"] == "private:1"
    assert job["generation"] == 2
    assert job["status"] == "completed"


async def test_cancelling_chat_does_not_cancel_background_job(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    async def runner(req, emit):
        started.set()
        await release.wait()
        return result()
    async def deliver(job): return True
    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    async def chat_turn():
        manager.submit(request(tmp_path), "owner_shared", {"source": "text_input"})
        await asyncio.Event().wait()
    chat = asyncio.create_task(chat_turn())
    await asyncio.wait_for(started.wait(), 1)
    chat.cancel()
    await asyncio.gather(chat, return_exceptions=True)
    assert manager.jobs["one"]["status"] == "running"
    release.set()
    await finish(manager)
    assert manager.jobs["one"]["status"] == "completed"


async def test_scope_isolation_and_owner_shared_policy(tmp_path):
    async def runner(req, emit): return result()
    async def deliver(job): return True
    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    manager.submit(request(tmp_path), "qq:group:1", {"source": "qq_gateway"})
    assert manager.list("qq:group:2") == []
    for scope in ["qq:group:2", "owner_shared"]:
        with pytest.raises(ValueError): manager.get("one", scope)
        with pytest.raises(ValueError): await manager.cancel("one", scope)
        with pytest.raises(ValueError): manager.resume("one", scope, "continue")
    await finish(manager)
    for ctx in [{}, {"source": "qq_gateway", "channel_meta": {"is_owner": True, "session_id": "private:1"}}]:
        assert origin_from_context(ctx)[0] == "owner_shared"
    assert origin_from_context({"source": "qq_gateway", "channel_meta": {
        "is_owner": True, "session_id": "group:1"}})[0] == "qq:group:1"


@pytest.mark.parametrize("ctx", [
    {"source": "qq_gateway"},
    {"source": "qq_gateway", "channel_meta": {"is_owner": True}},
    {"source": "qq_gateway", "channel_meta": {"is_owner": True, "session_id": "private:1", "group_id": "2"}},
])
def test_missing_or_unauthorized_remote_identity_is_rejected(ctx):
    with pytest.raises((PermissionError, ValueError)):
        origin_from_context(ctx)


async def test_same_workspace_serializes_but_different_workspace_runs(tmp_path):
    release = asyncio.Event()
    started = []
    async def runner(req, emit):
        started.append(req.task_id)
        await release.wait()
        return result()
    async def deliver(job): return True
    manager = TaskManager(tmp_path / "state.json", runner, deliver, parallel=2)
    other = tmp_path / "other"
    other.mkdir()
    for req in [request(tmp_path), request(tmp_path, "two"), request(other, "three")]:
        manager.submit(req, "owner_shared", {"source": "text_input"})
    for _ in range(10): await asyncio.sleep(0)
    assert started == ["one", "three"]
    release.set()
    await finish(manager)
    assert started == ["one", "three", "two"]


async def test_restart_marks_incomplete_and_resumes_exact_session(tmp_path):
    started = asyncio.Event()
    calls = []
    async def runner(req, emit):
        emit({"type": "session", "session_id": "saved-dsh-session"})
        started.set()
        await asyncio.Event().wait()
    async def deliver(job): return True
    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    manager.submit(request(tmp_path, provider="deepseek_harness"), "owner_shared", {"source": "text_input"})
    await started.wait()
    await manager.stop()
    async def resumed(req, emit):
        calls.append(req)
        return result(req.session_id)
    restored = TaskManager(manager.path, resumed, deliver)
    assert restored.get("one", "owner_shared")["status"] == "interrupted"
    restored.resume("one", "owner_shared", "continue")
    await finish(restored)
    assert calls[0].session_id == "saved-dsh-session"
    assert calls[0].provider == "deepseek_harness"


async def test_cancel_queued_before_start_and_stop_are_safe(tmp_path):
    calls = []
    async def runner(req, emit): calls.append(req); return result()
    async def deliver(job): return True
    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    manager.submit(request(tmp_path), "owner_shared", {"source": "text_input"})
    await manager.cancel("one", "owner_shared")
    assert calls == []
    assert manager.jobs["one"]["status"] == "cancelled"
    with pytest.raises(ValueError, match="外部会话"):
        manager.resume("one", "owner_shared", "continue")
    await manager.stop()
    assert manager.tasks == {}


async def test_failed_delivery_can_retry_without_rerunning_job(tmp_path):
    runs, sends = [], []
    async def runner(req, emit): runs.append(req); return result()
    async def deliver(job): sends.append(job); return len(sends) > 1
    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    job = manager.submit(request(tmp_path), "owner_shared", {"source": "text_input"})
    await finish(manager)
    assert job["delivery"] == "failed"
    await asyncio.gather(manager.notify(job), manager.notify(job))
    assert job["delivery"] == "sent"
    assert len(runs) == 1
    assert len(sends) == 2


async def test_atomic_save_failure_preserves_old_file(tmp_path, monkeypatch):
    async def runner(req, emit): return result()
    async def deliver(job): return True
    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    manager.save()
    before = manager.path.read_bytes()
    def fail(*args): raise OSError("disk unavailable")
    monkeypatch.setattr("code_agent.jobs.os.replace", fail)
    with pytest.raises(OSError):
        manager.submit(request(tmp_path), "owner_shared", {})
    assert manager.path.read_bytes() == before
    assert not manager.tasks and not manager.jobs
    assert list(tmp_path.glob(".code-agent-*.tmp")) == []


def test_corrupt_state_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("broken")
    with pytest.raises(ValueError): TaskManager(path, None, None)
    assert path.read_text() == "broken"


async def test_plugin_returns_ack_and_delivers_to_immutable_qq_origin(tmp_path):
    release, started = asyncio.Event(), asyncio.Event()
    sent = []
    async def runner(req, emit):
        started.set()
        await release.wait()
        return result()
    async def send(text, ctx): sent.append((text, ctx)); return True
    plugin = Plugin(runner=runner, discoverer=lambda p: "codex")
    plugin.settings = {"state_path": str(tmp_path / "state.json")}
    ctx = {"source": "qq_gateway", "allow_exec": True, "app_root": str(tmp_path),
           "gateway": SimpleNamespace(send_text=send),
           "channel_meta": {"is_owner": True, "session_id": "private:1"}}
    ack = await plugin.run("analyze ||| codex_cli ||| . ||| check", ctx)
    assert "已提交后台任务" in ack
    await started.wait()
    ctx["channel_meta"]["session_id"] = "private:2"
    release.set()
    await finish(plugin._manager)
    assert sent[0][1]["channel_meta"]["session_id"] == "private:1"
    assert "done" in sent[0][0]
    await plugin.stop()


async def test_plugin_local_delivery_and_modify_confirmation(tmp_path):
    calls, sent = [], []
    async def runner(req, emit): calls.append(req); return result()
    async def emit(name, **kwargs): sent.append((name, kwargs))
    plugin = Plugin(runner=runner, discoverer=lambda p: "dsh")
    plugin.settings = {"state_path": str(tmp_path / "state.json")}
    ctx = {"allow_exec": True, "app_root": str(tmp_path),
           "app": SimpleNamespace(get_app=lambda: SimpleNamespace(event_bus=SimpleNamespace(emit=emit)))}
    confirmation = await plugin.run("modify ||| dsh ||| . ||| repair", ctx)
    assert confirmation["__agent_result__"] == "confirmation_required"
    assert calls == []
    ack = await plugin.confirm_agent_action(confirmation["payload"], ctx)
    assert "已提交后台任务" in ack
    await finish(plugin._manager)
    assert calls[0].provider == "deepseek_harness" and calls[0].allow_write
    assert sent[0][0] == "ui.append"
    assert "done" in sent[0][1]["text"]
    job = next(iter(plugin._manager.jobs.values()))
    confirm = await plugin.run(f"resume ||| {job['id']} ||| next", ctx)
    assert confirm["__agent_result__"] == "confirmation_required"
    await plugin.confirm_agent_action(confirm["payload"], ctx)
    await finish(plugin._manager)
    assert calls[-1].session_id == "session-one"
    await plugin.stop()


async def test_plugin_denies_other_qq_and_ungated_exec(tmp_path):
    plugin = Plugin(discoverer=lambda p: "codex")
    plugin.settings = {"state_path": str(tmp_path / "state.json")}
    assert "主人" in await plugin.run("list", {"source": "qq_gateway", "channel_meta": {"session_id": "private:2"}})
    assert "执行许可" in await plugin.run("analyze ||| codex ||| . ||| check", {})
    assert plugin._manager is None


def test_dsh_natural_routing_and_management_gate():
    plugin = Plugin()
    assert plugin.should_handle_direct("让 DeepSeek Harness 检查项目", {}, "dsh")
    assert plugin._parse_request("analyze ||| dsh ||| . ||| x ||| y")[3] == "x ||| y"
    assert plugin.resolve_gated_action("status ||| id") == ""
    assert plugin.resolve_gated_action("cancel ||| id") == ""
    assert plugin.resolve_gated_action("resume ||| id ||| continue") == "system.code_agent"
    assert plugin.format_invocation({"action": "resume", "task_id": "one", "prompt": "next"}) == "resume ||| one ||| next"


async def test_plugin_can_restart_after_stop_without_reexecuting_jobs(tmp_path):
    calls = []
    async def runner(req, emit): calls.append(req); return result()
    plugin = Plugin(runner=runner, discoverer=lambda p: "codex")
    plugin.settings = {"state_path": str(tmp_path / "state.json")}
    await plugin.start({"app_root": str(tmp_path)})
    await plugin.stop()
    await plugin.start({"app_root": str(tmp_path)})
    ack = await plugin.run("analyze ||| codex_cli ||| . ||| check", {"allow_exec": True})
    assert "已提交后台任务" in ack
    await finish(plugin._manager)
    assert len(calls) == 1
    await plugin.stop()


async def test_repeated_cancel_does_not_interrupt_cleanup(tmp_path):
    started, cleanup_started, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def runner(req, emit):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await release_cleanup.wait()
    async def deliver(job): return True
    manager = TaskManager(tmp_path / "state.json", runner, deliver)
    manager.submit(request(tmp_path), "owner_shared", {})
    await started.wait()
    first = asyncio.create_task(manager.cancel("one", "owner_shared"))
    await cleanup_started.wait()
    second = asyncio.create_task(manager.cancel("one", "owner_shared"))
    await asyncio.sleep(0)
    assert not first.done() and not second.done()
    release_cleanup.set()
    await asyncio.gather(first, second)
    assert manager.jobs["one"]["status"] == "cancelled"
