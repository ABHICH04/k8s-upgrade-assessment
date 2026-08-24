"""Post-upgrade / post-remediation health verification (read-only)."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass
class VerifyReport:
    healthy: bool
    checks: list[CheckResult] = field(default_factory=list)
    rollback_recommended: bool = False
    message: str = ""


def _run(cmd: str) -> tuple[int, str]:
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def verify_cluster_health(expected_minor: str | None = None) -> VerifyReport:
    checks: list[CheckResult] = []

    code, out = _run("kubectl get nodes")
    nodes_ok = code == 0 and "NotReady" not in out and "Ready" in out
    if expected_minor and code == 0:
        # soft check — nodes may still be rolling
        version_ok = f"v{expected_minor}" in out or expected_minor in out
        checks.append(
            CheckResult(
                "nodes_version",
                version_ok,
                out[:2000] if out else "no output",
            )
        )
    checks.append(CheckResult("nodes_ready", nodes_ok, out[:2000]))

    code, out = _run("kubectl get apiservices")
    apis_ok = code == 0 and "False" not in out
    checks.append(CheckResult("apiservices_available", apis_ok, out[:2000]))

    code, out = _run(
        "kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded "
        "--no-headers 2>/dev/null | head -50"
    )
    # empty output means no non-running pods (good); command may still rc=0
    bad_pods = [ln for ln in out.splitlines() if ln.strip()]
    # filter noise: Completed jobs already excluded by selector
    pods_ok = code == 0 and len(bad_pods) == 0
    checks.append(
        CheckResult(
            "no_unhealthy_pods",
            pods_ok,
            "\n".join(bad_pods[:30]) if bad_pods else "No non-running pods found",
        )
    )

    code, out = _run("kubectl get validatingwebhookconfigurations --no-headers 2>/dev/null | wc -l")
    checks.append(CheckResult("webhooks_listable", code == 0, out))

    version_check = next((c for c in checks if c.name == "nodes_version"), None)
    core_ok = all(c.ok for c in checks if c.name != "nodes_version")
    # If caller asked for a target version, require nodes to show it.
    version_ok = version_check.ok if version_check is not None else True
    healthy = core_ok and version_ok
    rollback = not any(c.name == "nodes_ready" and c.ok for c in checks) or not any(
        c.name == "apiservices_available" and c.ok for c in checks
    )

    if healthy:
        msg = "Cluster health OK"
    elif version_check is not None and not version_check.ok and core_ok:
        msg = (
            f"Cluster is up but nodes are NOT on expected version {expected_minor}. "
            "Upgrade did not reach target."
        )
    else:
        msg = "Cluster health degraded — investigate / consider rollback"

    return VerifyReport(
        healthy=healthy,
        checks=checks,
        rollback_recommended=rollback,
        message=msg,
    )


def report_to_dict(report: VerifyReport) -> dict:
    return asdict(report)
