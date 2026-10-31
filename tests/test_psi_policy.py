"""PSI vNext authorization contracts: fail-closed, durable and auditable."""
import hashlib
import sqlite3
import time

import pytest
from psi_runtime import PSIPolicy

KEY = b"\x11" * 32
OTHER = b"\x12" * 32


def test_exact_scope_subject_resource_and_quota(tmp_path):
    with PSIPolicy(tmp_path / "psi.db", KEY) as psi:
        token = psi.issue(subject="buddy-v12", action="task.execute",
                          resource="sandbox:alpha", max_uses=2)
        assert not psi.authorize(token, subject="buddy-v12", action="task.execute",
                                 resource="sandbox:beta")
        assert not psi.authorize(token, subject="other", action="task.execute",
                                 resource="sandbox:alpha")
        assert not psi.authorize(token, subject="buddy-v12", action="tool.shell",
                                 resource="sandbox:alpha")
        assert psi.authorize(token, subject="buddy-v12", action="task.execute",
                             resource="sandbox:alpha")
        assert psi.authorize(token, subject="buddy-v12", action="task.execute",
                             resource="sandbox:alpha")
        assert not psi.authorize(token, subject="buddy-v12", action="task.execute",
                                 resource="sandbox:alpha")
        assert psi.audit()["ok"]


def test_revocation_and_persistent_recovery(tmp_path):
    path = tmp_path / "psi.db"
    with PSIPolicy(path, KEY) as psi:
        token = psi.issue(subject="worker-1", action="memory.read",
                          resource="task-99", max_uses=4)
        gid = token.split(".")[0]
    with PSIPolicy(path, KEY) as psi:
        assert psi.authorize(token, subject="worker-1", action="memory.read",
                             resource="task-99")
        assert psi.revoke(gid)
        assert not psi.authorize(token, subject="worker-1", action="memory.read",
                                 resource="task-99")
        assert not psi.revoke(gid)
        assert psi.audit()["ok"]


def test_expired_and_bad_credentials_rejected(tmp_path):
    with PSIPolicy(tmp_path / "psi.db", KEY) as psi:
        token = psi.issue(subject="agent-1", action="data.read",
                          resource="report-123", duration_seconds=1)
        assert not psi.authorize(token[:-1] + ("a" if token[-1] != "a" else "b"),
                                 subject="agent-1", action="data.read",
                                 resource="report-123")
        with PSIPolicy(tmp_path / "other.db", OTHER) as stranger:
            assert not stranger.authorize(token, subject="agent-1",
                                          action="data.read", resource="report-123")
        psi.db.execute("UPDATE grants SET expires_at=? WHERE grant_id=?",
                       (time.time() - 1, token.split(".")[0]))
        assert not psi.authorize(token, subject="agent-1", action="data.read",
                                 resource="report-123")
        assert psi.audit()["ok"]


def test_invalid_authority_or_claims_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        PSIPolicy(tmp_path / "short.db", b"123")
    with PSIPolicy(tmp_path / "psi.db", KEY) as psi:
        for action in ("tool.*", "admin / all", "", "A"):
            with pytest.raises(ValueError):
                psi.issue(subject="agent", action=action, resource="sandbox")
        with pytest.raises(ValueError):
            psi.issue(subject="agent", action="task.execute", resource="sandbox",
                      duration_seconds=0)


def test_hash_chain_detects_modified_receipt(tmp_path):
    with PSIPolicy(tmp_path / "psi.db", KEY) as psi:
        psi.issue(subject="agent", action="task.execute", resource="sandbox")
        assert psi.audit()["ok"]
        psi.db.execute("UPDATE events SET action='forged' WHERE seq=1")
        assert not psi.audit()["ok"]


def test_same_token_double_use_is_serialized(tmp_path):
    path = tmp_path / "psi.db"
    with PSIPolicy(path, KEY) as owner:
        token = owner.issue(subject="agent", action="task.execute",
                            resource="sandbox", max_uses=1)
    from concurrent.futures import ThreadPoolExecutor
    def use(_):
        with PSIPolicy(path, KEY) as psi:
            return psi.authorize(token, subject="agent", action="task.execute",
                                 resource="sandbox")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(use, range(2)))
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1
