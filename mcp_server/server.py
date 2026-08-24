#!/usr/bin/env python3
"""MCP server for Kubernetes upgrade execution (guardrailed).

Tools:
  - assess_upgrade_feasibility
  - get_feasibility_report
  - request_upgrade_approval
  - remediate_from_report
  - upgrade_cluster          (HARD-GATED by report decision)
  - verify_cluster_health

Policy:
  If report decision is NOT RECOMMENDED, upgrade_cluster ALWAYS refuses —
  even when the human confirms.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer

from k8s_upgrade_analyzer.assessment_service import report_path_for, run_assessment
from k8s_upgrade_analyzer.gates import load_and_parse_report
from k8s_upgrade_analyzer.remediate import (
    build_remediation_plan,
    execute_remediation_plan,
    plan_to_dict,
    save_plan,
)
from k8s_upgrade_analyzer.upgrade import request_approval, result_to_dict, run_upgrade, save_result
from k8s_upgrade_analyzer.verify import report_to_dict
from k8s_upgrade_analyzer.verify import verify_cluster_health as run_health_checks

mcp = MCPServer(
    name="k8s-upgrade-mcp",
    instructions=(
        "Kubernetes upgrade MCP with hard feasibility gates. "
        "Always assess first. Never call upgrade_cluster when the report "
        "decision is NOT RECOMMENDED — the tool will refuse even with human confirmation. "
        "Default dry_run=true for remediation and upgrade."
    ),
)


@mcp.tool()
def assess_upgrade_feasibility(
    source: str,
    target: str,
    mode: str = "ollama",
    model: str = "llama3.1:8b",
    output_dir: str = "reports",
) -> str:
    """Collect cluster state and generate a feasibility report (AI model required)."""
    report_path, gate, _ = run_assessment(
        source=source,
        target=target,
        mode=mode,
        model=model,
        output_dir=output_dir,
    )
    return json.dumps(
        {
            "report_path": str(report_path),
            "decision": gate.decision.value,
            "readiness_score": gate.readiness_score,
            "confidence": gate.confidence,
            "critical_issues": gate.critical_issues,
            "required_actions": gate.required_actions,
            "upgrade_allowed": gate.upgrade_allowed,
            "refusal_reason": gate.refusal_reason,
        },
        indent=2,
    )


@mcp.tool()
def get_feasibility_report(source: str, target: str, output_dir: str = "reports") -> str:
    """Read and parse an existing feasibility report for source→target."""
    path = report_path_for(source, target, output_dir)
    gate = load_and_parse_report(path)
    text = path.read_text() if path.exists() else ""
    return json.dumps(
        {
            "report_path": str(path),
            "exists": path.exists(),
            "decision": gate.decision.value,
            "readiness_score": gate.readiness_score,
            "confidence": gate.confidence,
            "critical_issues": gate.critical_issues,
            "required_actions": gate.required_actions,
            "upgrade_allowed": gate.upgrade_allowed,
            "refusal_reason": gate.refusal_reason,
            "report_excerpt": text[:6000],
        },
        indent=2,
    )


@mcp.tool()
def request_upgrade_approval(source: str, target: str, output_dir: str = "reports") -> str:
    """Human-in-the-loop gate. Returns confirmation_token only when approval is possible.

    If the report is NOT RECOMMENDED, approval_available=false and upgrade stays blocked.
    """
    path = report_path_for(source, target, output_dir)
    return json.dumps(request_approval(source, target, str(path)), indent=2)


@mcp.tool()
def remediate_from_report(
    source: str,
    target: str,
    output_dir: str = "reports",
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> str:
    """Build/execute remediations from the feasibility report (APIs, CRDs, controllers, CSI).

    Defaults to dry_run=true. Live changes need confirmation_token + K8S_UPGRADE_ALLOW_MUTATIONS=1.
    """
    path = report_path_for(source, target, output_dir)
    if not path.exists():
        return json.dumps(
            {"error": f"No report at {path}. Run assess_upgrade_feasibility first."},
            indent=2,
        )

    plan = build_remediation_plan(str(path), source, target)
    plan = execute_remediation_plan(
        plan,
        dry_run=dry_run,
        confirmation_token=confirmation_token,
    )
    out = ROOT / "plans" / f"remediation_{source.replace('.', '_')}_to_{target.replace('.', '_')}.json"
    save_plan(plan, out)
    payload = plan_to_dict(plan)
    payload["plan_path"] = str(out)
    return json.dumps(payload, indent=2)


@mcp.tool()
def upgrade_cluster(
    source: str,
    target: str,
    confirmation_token: str,
    output_dir: str = "reports",
    dry_run: bool = True,
    remediations_verified: bool = False,
    allow_conditional: bool = False,
    user_accepted_resource_risk: bool = False,
    platform: str | None = None,
) -> str:
    """Execute or dry-run the cluster upgrade for kind/kops/eks/kubeadm/etc.

    HARD GATE: NOT RECOMMENDED refuses unless findings are resource-pressure-only AND
    user_accepted_resource_risk=true (explicit human acceptance).
    platform: optional override (kind|kops|eks|gke|aks|kubeadm|generic). Auto-detected if omitted.
    """
    path = report_path_for(source, target, output_dir)
    result = run_upgrade(
        source=source,
        target=target,
        report_path=str(path),
        confirmation_token=confirmation_token,
        dry_run=dry_run,
        remediations_verified=remediations_verified,
        allow_conditional=allow_conditional,
        user_accepted_resource_risk=user_accepted_resource_risk,
        platform_override=platform,
    )
    out = ROOT / "plans" / f"upgrade_{source.replace('.', '_')}_to_{target.replace('.', '_')}.json"
    save_result(result, out)
    payload = result_to_dict(result)
    payload["result_path"] = str(out)
    return json.dumps(payload, indent=2)


@mcp.tool()
def verify_cluster_health(expected_version: str | None = None) -> str:
    """Read-only health checks after remediation/upgrade. Advises rollback if unhealthy."""
    report = run_health_checks(expected_minor=expected_version)
    return json.dumps(report_to_dict(report), indent=2)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
