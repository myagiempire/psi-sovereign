"""PSI task agent: bounded delegated execution rather than trust by phrases.

A registered local handler can execute only when PSI grants exact
subject+action+resource permission. This is an integration boundary for
AIOS/HandyMan workers, not a public endpoint or general shell executor.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from .policy import PSIPolicy, stable

TaskHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class TaskEnvelope:
    subject: str
    action: str
    resource: str
    payload: dict[str, Any]


class SovereignTaskAgent:
    def __init__(self, policy: PSIPolicy):
        self.policy = policy
        self._handlers: dict[tuple[str, str], TaskHandler] = {}

    def register_local(self, *, action: str, resource: str,
                       handler: TaskHandler) -> None:
        if not action or not resource or not callable(handler):
            raise ValueError("Explicit action/resource and callable handler required")
        if (action, resource) in self._handlers:
            raise ValueError("Handler already registered; cannot silently override")
        self._handlers[(action, resource)] = handler

    def execute(self, grant_token: str, task: TaskEnvelope) -> dict[str, Any]:
        if not isinstance(task.payload, dict):
            raise TypeError("Task payload must be a JSON object")
        encoded = stable(task.payload)
        if len(encoded.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Payload exceeds 1 MiB")
        handler = self._handlers.get((task.action, task.resource))
        if handler is None:
            raise PermissionError("No handler for requested exact capability")
        if not self.policy.authorize(grant_token, subject=task.subject,
                                     action=task.action, resource=task.resource):
            raise PermissionError("PSI grant denied, expired, revoked or exhausted")
        result = handler(task.payload)
        if not isinstance(result, dict):
            raise TypeError("Handler must return JSON object")
        return {
            "status": "done",
            "subject": task.subject, "action": task.action,
            "resource": task.resource,
            "payload_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "result": result,
            "result_sha256": hashlib.sha256(stable(result).encode("utf-8")).hexdigest(),
            "psi_audit": self.policy.audit(),
        }
