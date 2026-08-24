"""Remediation planner/executor driven by the feasibility report.

MVP behavior:
- Always builds a concrete remediation plan from report required actions / critical issues.
- Defaults to dry-run (prints exact commands; does not mutate the cluster).
- Live execution requires confirmation token + K8S_UPGRADE_ALLOW_MUTATIONS=1.
- Only a small allowlisted set of read/fix helpers may run live in MVP;
  destructive cluster upgrades are never done here (that is upgrade.py).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from k8s_upgrade_analyzer.gates import (
    load_and_parse_report,
    mutations_enabled,
    verify_approval_token,
)


@dataclass
class RemediationStep:
    id: str
    title: str
    category: str  # api | crd | controller | addon | capacity | backup | other
    commands: list[str]
    automatable: bool
    status: str = "planned"  # planned | dry-run | executed | skipped | blocked
    notes: str = ""


@dataclass
class RemediationPlan:
    report_path: str
    source: str
    target: str
    steps: list[RemediationStep] = field(default_factory=list)
    dry_run: bool = True
    summary: str = ""


def _classify(action: str) -> tuple[str, bool, list[str]]:
    a = action.lower()
    target_hint = re.search(r"1\.\d+", action)
    tgt = target_hint.group(0) if target_hint else "TARGET"

    if "ingress-nginx" in a:
        return (
            "controller",
            False,
            [
                "# Upgrade ingress-nginx to a release tested on the target Kubernetes version",
                "helm repo update",
                f"helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx "
                f"--version <chart-compatible-with-{tgt}> -n default --dry-run",
            ],
        )
    if "rancher" in a:
        return (
            "controller",
            False,
            [
                "# Upgrade Rancher manager + cattle-cluster-agent/webhook/fleet to a matrix that supports target k8s",
                "# Perform on the Rancher management plane, then verify agent reconnect",
            ],
        )
    if "keda" in a:
        return (
            "controller",
            False,
            [
                "helm repo add kedacore https://kedacore.github.io/charts",
                "helm upgrade --install keda kedacore/keda -n default --dry-run",
            ],
        )
    if "fsx" in a or "efs" in a or "csi" in a or "ebs" in a:
        return (
            "addon",
            False,
            [
                "# Align CSI addons with EKS target version (example)",
                "aws eks describe-addon-versions --kubernetes-version TARGET --addon-name aws-ebs-csi-driver",
                "aws eks update-addon --cluster-name CLUSTER --addon-name aws-ebs-csi-driver --addon-version <compat> --resolve-conflicts OVERWRITE",
            ],
        )
    if "api" in a or "deprecated" in a:
        return (
            "api",
            True,
            [
                "kubectl api-resources",
                # read-only scan helper
                "kubectl get deploy,sts,ds,cj,ing -A -o json | "
                "python -c \"import json,sys; d=json.load(sys.stdin); "
                "print('objects', len(d.get('items',[])))\"",
            ],
        )
    if "crd" in a:
        return (
            "crd",
            True,
            [
                "kubectl get crd -o custom-columns=NAME:.metadata.name,VERSIONS:.spec.versions[*].name",
            ],
        )
    if "cordon" in a or "memory" in a or "schedulingdisabled" in a or "node" in a:
        return (
            "capacity",
            False,
            [
                "kubectl get nodes -o wide",
                "kubectl top nodes",
                "# Uncordon only after confirming the node is healthy:",
                "# kubectl uncordon <node>",
            ],
        )
    if "backup" in a:
        return (
            "backup",
            False,
            [
                "# Take application + volume backups before upgrade (Velero / CSI snapshots / DB dumps)",
            ],
        )
    return ("other", False, [f"# Manual remediation required: {action}"])


def build_remediation_plan(report_path: str, source: str, target: str) -> RemediationPlan:
    gate = load_and_parse_report(report_path)
    steps: list[RemediationStep] = []

    items = gate.required_actions or []
    items.extend(f"Address critical issue: {c}" for c in gate.critical_issues)

    seen = set()
    for idx, item in enumerate(items, 1):
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        category, automatable, commands = _classify(item)
        # Inject real target into command placeholders
        commands = [c.replace("TARGET", target) for c in commands]
        steps.append(
            RemediationStep(
                id=f"rem-{idx:02d}",
                title=item,
                category=category,
                commands=commands,
                automatable=automatable,
            )
        )

    plan = RemediationPlan(
        report_path=report_path,
        source=source,
        target=target,
        steps=steps,
        summary=(
            f"Built {len(steps)} remediation steps from {report_path}. "
            f"Decision={gate.decision.value}. "
            "MVP auto-executes only read-only/automatable steps when mutations are enabled; "
            "controller/addon upgrades remain human-approved command plans."
        ),
    )
    return plan


def _run_readonly(cmd: str) -> tuple[int, str, str]:
    # Extremely conservative: only allow kubectl get/api-resources/top/version
    allowed = re.compile(r"^\s*kubectl\s+(get|api-resources|top|version|describe)\b")
    if not allowed.search(cmd.split("|")[0]):
        return 1, "", f"Blocked non-allowlisted command in remediation MVP: {cmd}"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    return proc.returncode, proc.stdout, proc.stderr


def execute_remediation_plan(
    plan: RemediationPlan,
    *,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> RemediationPlan:
    plan.dry_run = dry_run

    if not dry_run:
        ok, msg = verify_approval_token(
            confirmation_token,
            source=plan.source,
            target=plan.target,
            report_path=plan.report_path,
        )
        if not ok:
            for step in plan.steps:
                step.status = "blocked"
                step.notes = msg
            plan.summary = msg
            return plan
        if not mutations_enabled():
            for step in plan.steps:
                step.status = "blocked"
                step.notes = "Set K8S_UPGRADE_ALLOW_MUTATIONS=1 to allow live remediation."
            plan.summary = "Mutations disabled by environment guardrail."
            return plan

    for step in plan.steps:
        if dry_run:
            step.status = "dry-run"
            step.notes = "Commands listed only; no cluster mutation performed."
            continue

        if not step.automatable:
            step.status = "skipped"
            step.notes = "Not auto-executable in MVP — run listed commands manually / via GitOps."
            continue

        outputs = []
        for cmd in step.commands:
            if cmd.strip().startswith("#"):
                continue
            code, out, err = _run_readonly(cmd)
            outputs.append(f"$ {cmd}\nrc={code}\n{out}{err}")
            if code != 0:
                step.status = "blocked"
                step.notes = "\n".join(outputs)[-4000:]
                break
        else:
            step.status = "executed"
            step.notes = "\n".join(outputs)[-4000:]

    done = sum(1 for s in plan.steps if s.status in ("executed", "dry-run", "skipped"))
    plan.summary = f"Remediation finished: {done}/{len(plan.steps)} steps processed (dry_run={dry_run})."
    return plan


def plan_to_dict(plan: RemediationPlan) -> dict:
    return asdict(plan)


def save_plan(plan: RemediationPlan, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan_to_dict(plan), indent=2))
    return out
