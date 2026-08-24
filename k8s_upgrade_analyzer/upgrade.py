"""Cluster upgrade executor with hard feasibility + human-approval gates.

Platform-aware: kind | kops | eks | gke | aks | kubeadm | generic

MCP must call this only after:
1. Feasibility report exists and is parsed
2. Decision is APPROVED (or CONDITIONAL with remediations_verified)
3. Human confirmation token is valid
4. dry_run=False AND K8S_UPGRADE_ALLOW_MUTATIONS=1 for live changes

If the report says NOT RECOMMENDED, this module ALWAYS refuses —
even when the human confirms.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from k8s_upgrade_analyzer.gates import (
    UpgradeDecision,
    evaluate_upgrade_gate,
    is_resource_pressure_only,
    load_and_parse_report,
    make_approval_token,
    mutations_enabled,
    verify_approval_token,
)
from k8s_upgrade_analyzer.platform import PlatformInfo, detect_platform


@dataclass
class UpgradeStep:
    id: str
    title: str
    command: str
    status: str = "planned"
    output: str = ""


@dataclass
class UpgradeResult:
    allowed: bool
    dry_run: bool
    decision: str
    report_path: str
    message: str
    platform: str = "generic"
    cluster_name: str | None = None
    approval_token_required: str = ""
    steps: list[UpgradeStep] = field(default_factory=list)


def build_upgrade_plan(source: str, target: str, platform: PlatformInfo | None = None) -> list[UpgradeStep]:
    info = platform or detect_platform()
    name = info.cluster_name or os.environ.get("CLUSTER_NAME") or "<SET_CLUSTER_NAME>"

    if info.platform == "kind":
        image_ver = _normalize_k8s_image_version(target)
        # ALWAYS default to in-place kubeadm (keeps pods/PVCs/etcd).
        # Recreate is double-gated and off by default — never wipe by accident.
        mode = (os.environ.get("KIND_UPGRADE_MODE") or "inplace").strip().lower()
        allow_recreate = os.environ.get("KIND_ALLOW_RECREATE", "").strip() == "1"
        script = Path(__file__).resolve().parent.parent / "scripts" / "kind_inplace_upgrade.sh"
        if mode in {"recreate", "delete", "replace"}:
            if not allow_recreate:
                return [
                    UpgradeStep(
                        id="up-01",
                        title=(
                            "REFUSED recreate: would destroy pods/PVCs. "
                            "Using in-place kubeadm instead. "
                            "(Only set KIND_UPGRADE_MODE=recreate AND KIND_ALLOW_RECREATE=1 to wipe.)"
                        ),
                        command=f"bash {script} {name} {image_ver}",
                    ),
                    UpgradeStep(
                        id="up-02",
                        title="Verify nodes Ready on target version",
                        command="kubectl get nodes -o wide",
                    ),
                ]
            return [
                UpgradeStep(
                    id="up-01",
                    title="Delete existing kind cluster (DATA LOSS — explicit recreate allowed)",
                    command=f"kind delete cluster --name {name}",
                ),
                UpgradeStep(
                    id="up-02",
                    title="Create kind cluster at target Kubernetes version",
                    command=f"kind create cluster --name {name} --image kindest/node:v{image_ver}",
                ),
                UpgradeStep(
                    id="up-03",
                    title="Verify nodes Ready on target version",
                    command="kubectl get nodes -o wide",
                ),
            ]
        return [
            UpgradeStep(
                id="up-01",
                title="In-place kind upgrade via kubeadm (preserves pods/PVCs/etcd)",
                command=f"bash {script} {name} {image_ver}",
            ),
            UpgradeStep(
                id="up-02",
                title="Verify nodes Ready on target version",
                command="kubectl get nodes -o wide",
            ),
        ]

    if info.platform == "kops":
        state = os.environ.get("KOPS_STATE_STORE", "s3://<KOPS_STATE_STORE>")
        return [
            UpgradeStep(
                id="up-01",
                title="Edit cluster Kubernetes version",
                command=(
                    f"export KOPS_STATE_STORE={state}\n"
                    f"kops edit cluster {name}  # set kubernetesVersion: {target}"
                ),
            ),
            UpgradeStep(
                id="up-02",
                title="Update cluster (control plane + rolling nodes)",
                command=f"kops update cluster {name} --yes",
            ),
            UpgradeStep(
                id="up-03",
                title="Rolling-update instance groups",
                command=f"kops rolling-update cluster {name} --yes",
            ),
            UpgradeStep(
                id="up-04",
                title="Validate cluster",
                command=f"kops validate cluster {name}",
            ),
            UpgradeStep(
                id="up-05",
                title="Verify nodes Ready on target version",
                command="kubectl get nodes -o wide",
            ),
        ]

    if info.platform == "eks":
        region = os.environ.get("AWS_REGION", "ap-south-1")
        return [
            UpgradeStep(
                id="up-01",
                title="Update EKS control plane",
                command=(
                    f"aws eks update-cluster-version --name {name} "
                    f"--kubernetes-version {target} --region {region}"
                ),
            ),
            UpgradeStep(
                id="up-02",
                title="Wait for control plane active",
                command=f"aws eks wait cluster-active --name {name} --region {region}",
            ),
            UpgradeStep(
                id="up-03",
                title="Upgrade managed addons",
                command=(
                    f"# aws eks update-addon --cluster-name {name} --addon-name vpc-cni "
                    f"--resolve-conflicts OVERWRITE --region {region}"
                ),
            ),
            UpgradeStep(
                id="up-04",
                title="Roll nodegroup to target version",
                command=(
                    f"aws eks update-nodegroup-version --cluster-name {name} "
                    f"--nodegroup-name <NODEGROUP> --region {region}"
                ),
            ),
            UpgradeStep(
                id="up-05",
                title="Verify nodes Ready on target version",
                command="kubectl get nodes -o wide",
            ),
        ]

    if info.platform == "gke":
        project = os.environ.get("GCP_PROJECT", "<GCP_PROJECT>")
        zone = os.environ.get("GCP_ZONE", "<GCP_ZONE>")
        return [
            UpgradeStep(
                id="up-01",
                title="Upgrade GKE cluster/control plane",
                command=(
                    f"gcloud container clusters upgrade {name} --cluster-version={target} "
                    f"--project={project} --zone={zone} --master"
                ),
            ),
            UpgradeStep(
                id="up-02",
                title="Upgrade GKE node pools",
                command=(
                    f"gcloud container clusters upgrade {name} --cluster-version={target} "
                    f"--project={project} --zone={zone}"
                ),
            ),
            UpgradeStep(
                id="up-03",
                title="Verify nodes Ready on target version",
                command="kubectl get nodes -o wide",
            ),
        ]

    if info.platform == "aks":
        rg = os.environ.get("AZURE_RESOURCE_GROUP", "<RESOURCE_GROUP>")
        return [
            UpgradeStep(
                id="up-01",
                title="Upgrade AKS cluster",
                command=f"az aks upgrade --resource-group {rg} --name {name} --kubernetes-version {target}",
            ),
            UpgradeStep(
                id="up-02",
                title="Verify nodes Ready on target version",
                command="kubectl get nodes -o wide",
            ),
        ]

    # kubeadm / generic self-managed
    return [
        UpgradeStep(
            id="up-01",
            title="Drain / backup before control-plane upgrade",
            command="# take etcd snapshot / Velero backup; cordon carefully",
        ),
        UpgradeStep(
            id="up-02",
            title="Upgrade kubeadm control plane to target",
            command=(
                f"sudo kubeadm upgrade plan {target}\n"
                f"sudo kubeadm upgrade apply v{target}"
            ),
        ),
        UpgradeStep(
            id="up-03",
            title="Upgrade kubelet/kubectl on control-plane nodes",
            command=(
                f"# distro package upgrade to kubelet/kubectl {target}, then:\n"
                "sudo systemctl daemon-reload && sudo systemctl restart kubelet"
            ),
        ),
        UpgradeStep(
            id="up-04",
            title="Roll worker nodes (drain → upgrade kubelet → uncordon)",
            command=(
                "kubectl drain <node> --ignore-daemonsets --delete-emptydir-data\n"
                f"# upgrade kubelet to {target} on the node\n"
                "kubectl uncordon <node>"
            ),
        ),
        UpgradeStep(
            id="up-05",
            title="Verify nodes Ready on target version",
            command="kubectl get nodes -o wide",
        ),
    ]


def request_approval(source: str, target: str, report_path: str) -> dict:
    report_text = Path(report_path).read_text() if Path(report_path).exists() else ""
    gate = load_and_parse_report(report_path)
    gate = evaluate_upgrade_gate(gate, remediations_verified=False, report_text=report_text)
    platform = detect_platform()
    resource_only = is_resource_pressure_only(gate, report_text)

    token = make_approval_token(source, target, report_path)
    base = {
        "platform": platform.platform,
        "cluster_name": platform.cluster_name,
        "platform_evidence": platform.evidence,
        "resource_pressure_only": resource_only,
    }

    if gate.decision == UpgradeDecision.NOT_RECOMMENDED:
        if resource_only:
            return {
                **base,
                "approval_available": True,
                "decision": gate.decision.value,
                "message": (
                    "Decision is NOT RECOMMENDED, but findings appear limited to "
                    "CPU/memory/resource pressure. Interactive yes can proceed at your risk."
                ),
                "confirmation_token": token,
                "human_prompt": (
                    "Resource-pressure-only risk detected. "
                    f"In the agent CLI, answer yes to proceed. Token: {token}"
                ),
            }
        return {
            **base,
            "approval_available": False,
            "decision": gate.decision.value,
            "message": gate.refusal_reason,
            "confirmation_token": None,
            "human_prompt": (
                "Upgrade is blocked by feasibility report (NOT RECOMMENDED). "
                "Confirming will NOT unlock MCP upgrade. Fix issues and re-assess."
            ),
        }

    if not gate.upgrade_allowed and gate.decision == UpgradeDecision.CONDITIONAL:
        return {
            **base,
            "approval_available": True if resource_only else False,
            "decision": gate.decision.value,
            "message": gate.refusal_reason,
            "confirmation_token": token,
            "human_prompt": (
                "Report is CONDITIONAL"
                + (" (resource pressure only)." if resource_only else ".")
                + " Answer yes in the interactive agent prompt to proceed, "
                f"or pass --confirmation-token {token}"
            ),
        }

    return {
        **base,
        "approval_available": True,
        "decision": gate.decision.value,
        "message": "Human must explicitly confirm by passing confirmation_token to upgrade_cluster.",
        "confirmation_token": token,
        "human_prompt": (
            f"Detected platform={platform.platform}. "
            f"Pass this confirmation token to proceed with upgrade {source}→{target}: {token}"
        ),
    }


def _run_streaming(cmd: str, timeout: int = 1800) -> tuple[int, str]:
    """Run a shell command, printing stdout/stderr line-by-line as debug logs."""
    import time

    proc = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines: list[str] = []
    start = time.time()
    assert proc.stdout is not None
    try:
        while True:
            if timeout and (time.time() - start) > timeout:
                proc.kill()
                msg = f"\n[timeout] command exceeded {timeout}s\n"
                print(msg, end="", flush=True)
                lines.append(msg)
                return 124, "".join(lines)
            line = proc.stdout.readline()
            if line:
                print(line, end="", flush=True)
                lines.append(line)
                continue
            if proc.poll() is not None:
                # Drain remainder
                rest = proc.stdout.read()
                if rest:
                    print(rest, end="", flush=True)
                    lines.append(rest)
                break
            time.sleep(0.05)
    except Exception as exc:  # noqa: BLE001
        proc.kill()
        msg = f"\n[stream error] {exc}\n"
        print(msg, end="", flush=True)
        lines.append(msg)
        return 1, "".join(lines)
    return int(proc.returncode or 0), "".join(lines)


def _is_placeholder(cmd: str) -> bool:
    markers = ("<", "SET_CLUSTER", "SET_EKS", "RESOURCE_GROUP", "GCP_PROJECT", "GCP_ZONE", "KOPS_STATE_STORE")
    first = cmd.strip().splitlines()[0] if cmd.strip() else ""
    if first.startswith("#"):
        return True
    return any(m in cmd for m in markers)


def _normalize_k8s_image_version(version: str) -> str:
    """kindest/node tags need a patch, e.g. 1.31 -> 1.31.0."""
    v = version.lstrip("v").strip()
    parts = v.split(".")
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return f"{parts[0]}.{parts[1]}.0"
    return v


def run_upgrade(
    *,
    source: str,
    target: str,
    report_path: str,
    confirmation_token: str | None = None,
    dry_run: bool = True,
    remediations_verified: bool = False,
    allow_conditional: bool = False,
    user_accepted_resource_risk: bool = False,
    platform_override: str | None = None,
    skip_token_check: bool = False,
    force_user_approved: bool = False,
) -> UpgradeResult:
    platform = detect_platform(platform_override)

    if not Path(report_path).exists():
        return UpgradeResult(
            allowed=False,
            dry_run=dry_run,
            decision="UNKNOWN",
            report_path=report_path,
            message=f"REFUSED: feasibility report missing at {report_path}",
            platform=platform.platform,
            cluster_name=platform.cluster_name,
        )

    report_text = Path(report_path).read_text()
    gate = load_and_parse_report(report_path)

    if force_user_approved:
        # Interactive agent yes/no is the only approval needed.
        gate.upgrade_allowed = True
        gate.refusal_reason = "ALLOWED: user confirmed interactively."
    else:
        gate = evaluate_upgrade_gate(
            gate,
            remediations_verified=remediations_verified,
            allow_conditional=allow_conditional,
            user_accepted_resource_risk=user_accepted_resource_risk,
            report_text=report_text,
        )

        if gate.decision == UpgradeDecision.NOT_RECOMMENDED and not gate.upgrade_allowed:
            return UpgradeResult(
                allowed=False,
                dry_run=dry_run,
                decision=gate.decision.value,
                report_path=report_path,
                message=gate.refusal_reason,
                platform=platform.platform,
                cluster_name=platform.cluster_name,
                approval_token_required="",
                steps=[],
            )

        if not gate.upgrade_allowed:
            return UpgradeResult(
                allowed=False,
                dry_run=dry_run,
                decision=gate.decision.value,
                report_path=report_path,
                message=gate.refusal_reason,
                platform=platform.platform,
                cluster_name=platform.cluster_name,
                approval_token_required="",
                steps=build_upgrade_plan(source, target, platform),
            )

        if not skip_token_check:
            ok, msg = verify_approval_token(
                confirmation_token,
                source=source,
                target=target,
                report_path=report_path,
            )
            if not ok:
                return UpgradeResult(
                    allowed=False,
                    dry_run=dry_run,
                    decision=gate.decision.value,
                    report_path=report_path,
                    message=msg,
                    platform=platform.platform,
                    cluster_name=platform.cluster_name,
                    approval_token_required=make_approval_token(source, target, report_path),
                    steps=build_upgrade_plan(source, target, platform),
                )

    steps = build_upgrade_plan(source, target, platform)

    if dry_run:
        for step in steps:
            step.status = "dry-run"
            step.output = (
                f"Platform={platform.platform}. Command prepared only; not executed (dry_run=true)."
            )
        return UpgradeResult(
            allowed=True,
            dry_run=True,
            decision=gate.decision.value,
            report_path=report_path,
            message=(
                f"Upgrade ALLOWED for platform={platform.platform}. "
                "dry_run=true so no cluster changes were made. "
                "Re-run with --execute-upgrade and answer yes for live execution."
            ),
            platform=platform.platform,
            cluster_name=platform.cluster_name,
            steps=steps,
        )

    # Interactive yes + --execute-upgrade is enough; env var still works for MCP.
    if not force_user_approved and not mutations_enabled():
        for step in steps:
            step.status = "blocked"
            step.output = "K8S_UPGRADE_ALLOW_MUTATIONS!=1"
        return UpgradeResult(
            allowed=False,
            dry_run=False,
            decision=gate.decision.value,
            report_path=report_path,
            message="REFUSED: live mutations disabled. Export K8S_UPGRADE_ALLOW_MUTATIONS=1.",
            platform=platform.platform,
            cluster_name=platform.cluster_name,
            steps=steps,
        )

    for step in steps:
        cmd = step.command.strip()
        if _is_placeholder(cmd):
            step.status = "skipped"
            step.output = "Placeholder/manual step — fill cluster values / run carefully by hand."
            continue
        # Stream logs live so the CLI does not look stuck during long kubeadm hops.
        timeout = 1800 if "kind_inplace_upgrade.sh" in cmd or "kubeadm upgrade" in cmd else 600
        print(f"\n----- LIVE LOG: {step.id} {step.title} -----", flush=True)
        print(f"$ {cmd}", flush=True)
        rc, output = _run_streaming(cmd, timeout=timeout)
        print(f"----- END LOG: {step.id} (exit={rc}) -----\n", flush=True)
        step.status = "executed" if rc == 0 else "failed"
        step.output = output[-12000:]
        if rc != 0:
            break

    failed = any(s.status == "failed" for s in steps)
    return UpgradeResult(
        allowed=True,
        dry_run=False,
        decision=gate.decision.value,
        report_path=report_path,
        message="Upgrade execution finished with failures." if failed else "Upgrade execution finished.",
        platform=platform.platform,
        cluster_name=platform.cluster_name,
        steps=steps,
    )


def result_to_dict(result: UpgradeResult) -> dict:
    return asdict(result)


def save_result(result: UpgradeResult, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result_to_dict(result), indent=2))
    return out
