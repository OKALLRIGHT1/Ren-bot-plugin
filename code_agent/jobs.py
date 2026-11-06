"""Persistent, conversation-scoped jobs; all mutations belong to one event loop."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path

from modules.security_redaction import redact_sensitive_text
from .runtime import CodeAgentRequest


ACTIVE = {"queued", "running", "cancelling"}


def origin_from_context(ctx: dict) -> tuple[str, dict]:
    source = str(ctx.get("source") or "text_input").strip().lower()
    meta = ctx.get("channel_meta") or {}
    if not isinstance(meta, dict):
        raise ValueError("会话信息无效")
    remote = source in {"qq_gateway", "napcat_qq", "qq_private", "qq_group"} or meta.get("adapter") == "napcat_qq"
    origin = {"source": source}
    if not remote:
        return "owner_shared", origin
    if not meta.get("is_owner"):
        raise PermissionError("代码代理仅允许主人使用")
    session = str(meta.get("session_id") or "").strip()
    group = source == "qq_group" or meta.get("message_type") == "group" or meta.get("group_id") or session.startswith("group:")
    if not session:
        identity = meta.get("group_id") if group else meta.get("user_id")
        if not identity:
            raise ValueError("无法确认发起会话，拒绝启动后台任务")
        session = f"{'group' if group else 'private'}:{identity}"
    if not session.startswith("group:" if group else "private:"):
        raise ValueError("会话标识与消息类型不一致")
    origin["channel_meta"] = {key: copy.deepcopy(meta[key]) for key in (
        "adapter", "user_id", "group_id", "is_owner", "message_type", "sender_name"
    ) if key in meta}
    origin["channel_meta"]["session_id"] = session
    origin["channel_meta"].setdefault("adapter", "napcat_qq")
    return (f"qq:{session}" if group else "owner_shared"), origin


class TaskManager:
    def __init__(self, path, runner, deliver, *, parallel=2):
        self.path = Path(path)
        self.runner = runner
        self.deliver = deliver
        self.jobs = {}
        self.tasks = {}
        self._limit = asyncio.Semaphore(max(1, min(8, int(parallel))))
        self._workspaces = {}
        self._delivery_locks = {}
        self._closing = False
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != 1 or not isinstance(payload.get("jobs"), dict):
                raise ValueError("任务存档格式无效，原文件已保留")
            self.jobs = payload["jobs"]
            for job in self.jobs.values():
                if job["status"] in ACTIVE:
                    job.update(status="interrupted", error="主程序退出时任务未完成，请显式继续。")
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Keep active jobs and the newest 200 terminal records.
        terminal = sorted((j for j in self.jobs.values() if j["status"] not in ACTIVE),
                          key=lambda j: j["updated_at"], reverse=True)
        for job in terminal[200:]:
            if job["id"] not in self.tasks:
                self.jobs.pop(job["id"], None)
        text = json.dumps({"schema": 1, "jobs": self.jobs}, ensure_ascii=False)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".code-agent-", suffix=".tmp", delete=False) as fh:
                tmp = Path(fh.name)
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def get(self, task_id, scope):
        job = self.jobs.get(task_id)
        if job is None or job["scope"] != scope:
            raise ValueError("当前会话没有这个任务")
        return job

    def list(self, scope):
        return sorted((j for j in self.jobs.values() if j["scope"] == scope),
                      key=lambda j: j["updated_at"], reverse=True)[:20]

    def submit(self, request: CodeAgentRequest, scope, origin):
        if self._closing:
            raise RuntimeError("插件正在停止")
        if len(self.tasks) >= 32:
            raise ValueError("后台任务队列已满，请先完成或取消已有任务")
        if request.task_id in self.jobs:
            raise ValueError("任务编号重复")
        now = time.time()
        job = {"id": request.task_id, "scope": scope, "origin": copy.deepcopy(origin),
               "request": asdict(request), "status": "queued", "created_at": now,
               "updated_at": now, "session_id": "", "events": [], "result": "",
               "error": "", "delivery": "pending", "generation": 1}
        self.jobs[job["id"]] = job
        try:
            self.save()
        except Exception:
            self.jobs.pop(job["id"], None)
            raise
        self._launch(job, request)
        return job

    def _launch(self, job, request):
        task = asyncio.create_task(self._execute(job, request), name=f"code-agent:{job['id']}")
        self.tasks[job["id"]] = task

        def done(completed):
            if self.tasks.get(job["id"]) is completed:
                self.tasks.pop(job["id"], None)
            if not completed.cancelled():
                completed.exception()  # execution errors are retained in the job

        task.add_done_callback(done)

    async def _execute(self, job, request):
        workspace = os.path.normcase(str(Path(request.cwd).resolve()))
        lock = self._workspaces.setdefault(workspace, asyncio.Lock())
        last_save = 0.0

        def progress(event):
            nonlocal last_save
            session_id = str(event.get("session_id") or "")
            new_session = session_id and session_id != job["session_id"]
            if new_session:
                job["session_id"] = session_id
            summary = redact_sensitive_text(f"{event.get('type', '')} {event.get('detail', '')}").strip()[:300]
            job["events"] = (job["events"] + [summary])[-30:]
            job["updated_at"] = time.time()
            if new_session or time.monotonic() - last_save >= 1:
                self.save()
                last_save = time.monotonic()

        try:
            # Same workspace is serialized even across different conversations.
            async with lock:
                async with self._limit:
                    job.update(status="running", updated_at=time.time())
                    self.save()
                    result = await self.runner(request, progress)
                    job.update(status="completed" if result.ok else "failed",
                               result=redact_sensitive_text(result.stdout or "")[-24000:],
                               error=redact_sensitive_text(result.stderr or "")[-6000:])
                    job["session_id"] = getattr(result, "session_id", "") or job["session_id"]
        except asyncio.CancelledError:
            job["status"] = "interrupted" if self._closing else "cancelled"
            job["error"] = "主程序停止，任务已中断。" if self._closing else "任务已取消，子进程已清理。"
        except asyncio.TimeoutError:
            job.update(status="failed", error="任务执行超时，子进程已清理。")
        except Exception as exc:
            job.update(status="failed", error=redact_sensitive_text(str(exc))[:6000])
        finally:
            job["updated_at"] = time.time()
            self.save()
        if not self._closing:
            await self.notify(job)

    async def notify(self, job):
        lock = self._delivery_locks.setdefault(job["id"], asyncio.Lock())
        async with lock:
            await self._notify_locked(job)

    async def _notify_locked(self, job):
        if job["delivery"] in {"sent", "submitted"}:
            return
        try:
            result = await asyncio.wait_for(self.deliver(copy.deepcopy(job)), timeout=20)
            if result is False or isinstance(result, dict) and not result.get("ok"):
                raise RuntimeError("发起会话投递失败")
            job["delivery"] = "submitted" if result is None else "sent"
            job.pop("delivery_error", None)
        except Exception as exc:
            job["delivery"] = "failed"
            job["delivery_error"] = redact_sensitive_text(str(exc))[:500]
        self.save()

    async def cancel(self, task_id, scope):
        job = self.get(task_id, scope)
        task = self.tasks.get(task_id)
        if task is None or job["status"] not in ACTIVE:
            return job
        if job["status"] != "cancelling":
            job.update(status="cancelling", updated_at=time.time())
            self.save()
            task.cancel()
        await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        if job["status"] == "cancelling":  # task was cancelled before first execution
            job.update(status="cancelled", error="任务在启动前取消。", updated_at=time.time())
            self.save()
            await self.notify(job)
        return job

    def resume(self, task_id, scope, prompt):
        job = self.get(task_id, scope)
        if self._closing or task_id in self.tasks or job["status"] in ACTIVE:
            raise ValueError("任务仍在运行或清理，请稍后继续")
        if len(self.tasks) >= 32:
            raise ValueError("后台任务队列已满")
        if not job["session_id"]:
            raise ValueError("任务尚未建立外部会话，请重新提交；不会猜测或恢复其他会话")
        if not prompt.strip():
            raise ValueError("请提供继续执行的指令")
        request = replace(CodeAgentRequest(**job["request"]), prompt=prompt,
                          session_id=job["session_id"], allow_exec=True)
        old = copy.deepcopy(job)
        job.update(status="queued", result="", error="", delivery="pending",
                   events=[], updated_at=time.time(), generation=job["generation"] + 1)
        try:
            self.save()
        except Exception:
            job.clear()
            job.update(old)
            raise
        self._launch(job, request)
        return job

    async def stop(self):
        self._closing = True
        tasks = list(self.tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for job in self.jobs.values():
            if job["status"] in ACTIVE:
                job.update(status="interrupted", error="主程序停止，请显式继续。")
        self.save()
