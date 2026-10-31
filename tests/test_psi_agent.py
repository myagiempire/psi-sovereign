"""PSI agent execution must obey delegation and never self-grant authority."""
import pytest
from psi_runtime import PSIPolicy, SovereignTaskAgent, TaskEnvelope


def test_agent_blocks_missing_and_wrong_grants(tmp_path):
    with PSIPolicy(tmp_path / "psi.db", bytes(range(32))) as policy:
        agent = SovereignTaskAgent(policy)
        called = []
        agent.register_local(action="task.plan", resource="sandbox-a",
                             handler=lambda p: (called.append(p), {"plan": "ok"})[1])
        envelope = TaskEnvelope("buddy-v12", "task.plan", "sandbox-a", {"goal": "repair"})
        with pytest.raises(PermissionError):
            agent.execute("missing-grant", envelope)
        assert called == []
        token = policy.issue(subject="buddy-v12", action="task.plan",
                             resource="sandbox-a", max_uses=1)
        with pytest.raises(PermissionError):
            agent.execute(token, TaskEnvelope("other-agent", "task.plan",
                                              "sandbox-a", {"goal": "repair"}))
        with pytest.raises(PermissionError):
            agent.execute(token, TaskEnvelope("buddy-v12", "task.plan",
                                              "production", {"goal": "repair"}))
        ok = agent.execute(token, envelope)
        assert ok["status"] == "done"
        assert ok["result"]["plan"] == "ok"
        assert len(called) == 1
        assert ok["psi_audit"]["ok"]
        with pytest.raises(PermissionError):
            agent.execute(token, envelope)
        assert len(called) == 1


def test_agent_prevents_unregistered_actions_even_with_a_grant(tmp_path):
    with PSIPolicy(tmp_path / "psi.db", bytes(range(32))) as policy:
        agent = SovereignTaskAgent(policy)
        token = policy.issue(subject="buddy", action="tool.shell",
                             resource="sandbox", max_uses=1)
        with pytest.raises(PermissionError, match="No handler"):
            agent.execute(token, TaskEnvelope("buddy", "tool.shell",
                                              "sandbox", {"command": "whoami"}))
        # No handler execution and quota remains available; no arbitrary shell.


def test_agent_rejects_override(tmp_path):
    with PSIPolicy(tmp_path / "psi.db", bytes(range(32))) as policy:
        agent = SovereignTaskAgent(policy)
        agent.register_local(action="task.plan", resource="demo",
                             handler=lambda p: {"ok": True})
        with pytest.raises(ValueError, match="already registered"):
            agent.register_local(action="task.plan", resource="demo",
                                 handler=lambda p: {"ok": False})
