# PSI Sovereign — separate vNext authorization and task-agent prototype

This is an **additive** source-preserving upgrade. Original `main` files `qbrain9_sovereign_core.py`, `supabase_bridge.py` and `supabase_bridge_v2.py` remain unchanged, available for archaeology and interface recovery.

## Recovered baseline

- `main` has **QBrain 9.0 Sovereign Core** with an Infinite Braid Stream, a temporal-regulator prototype, and an in-memory 48D state representation.
- `supabase_bridge.py` is a **broken historical variant**: `import hashiib` instead of `hashlib`, missing dependency handling that launches `pip install` implicitly, and phrase-based `USER_0_BOND` checks. It must not be mistaken for real authorization or a suitable unattended production service.
- `supabase_bridge_v2.py` corrects the import and wraps QBrain9 but still defaults to role/config fallbacks, auto-installs dependency, and treats a phrase as a trust decision. Those are not security guarantees.
- Historical QBrain9 `FlashRAM_48D` stores at most one object per mode and its GB counter is synthetic. It does not implement expandable physical RAM. Historical source kept for comparison; no silent claim upgrade.
- `myagiempire/Mypsi` is a **different, currently empty private repo**, not an alias to this public `psi-sovereign`.

## Implemented on this branch

**`psi_runtime/policy.py`** provides an explicit operator-scoped, local SQLite capability controller. An authorized software component holding a 32+ byte PSI authority key can mint exact grants for a specific `subject + action + resource`, with expiration, usage quota, and revocation. Tasks cannot broaden that grant. Revocation persists across process restart, decisions are transactional, and grant usage has a hash-linked event record.

**`psi_runtime/agent.py`** provides a bounded, pluggable task agent. An agent must hold a valid scoped grant and have a concrete handler registered for the exact action/resource. No arbitrary command executor, remote service, password exchange, or cloud client is included. The library does not make approval mandatory for every step: controllers can issue limited standing grants for ordinary work and reserve escalation for exceptional actions.

### Quick local example (no cloud credentials)

```python
import secrets
from psi_runtime import PSIPolicy, SovereignTaskAgent, TaskEnvelope

with PSIPolicy("local-state/psi.db", secrets.token_bytes(32)) as p:
    token = p.issue(
        subject="buddy-v12", action="task.plan",
        resource="sandbox", duration_seconds=600, max_uses=10
    )
    agent = SovereignTaskAgent(p)
    agent.register_local(
        action="task.plan", resource="sandbox",
        handler=lambda data: {"proposal": f"Plan for {data['goal']}"}
    )
    print(agent.execute(token, TaskEnvelope(
        subject="buddy-v12", action="task.plan", resource="sandbox",
        payload={"goal": "household repair"}
    )))
```

Keep the authority key securely outside source control. For restart to preserve the ability to verify outstanding grants, reload the **same** secured key along with the SQLite state; otherwise intentionally rotate and revoke prior grants. The example generates a new development key and is not a production deployment process.

**Tests:** `pytest tests/test_psi_policy.py tests/test_psi_agent.py` checks revocation, expiration, unauthorized scopes, double-use races, receipt tampering, and agent fail-closed behavior.

## Integration into myAGIempire

The AIOS-HandymanBot `empire_runtime` queue is the execution layer, while PSI will be a separate **policy/authority layer** for sensitive external adapters and delegated long-running workflows. The two remain distinct; no capability should be considered authorized merely because it appears in a registry. Wire them together through narrow Python interfaces under a dedicated branch and prove a denied task does not execute.

**Do not publish or deploy** the historical Supabase bridge as production auth. A production revision needs tenant/installation identity, secure key custody, encrypted-at-rest data and backups, independently anchored audit, HTTPS + appropriate service authentication and rate limits, migration of authorized grants, and revocation propagation to workers. The branch is still experimental/local-only and changes no cloud resources.

Founder direction: the larger system should become cooperative AI infrastructure with meaningful delegated autonomy, not a manual-approval bottleneck. **Abundance · Gratitude · Integrity**, with original variants and credit retained.
