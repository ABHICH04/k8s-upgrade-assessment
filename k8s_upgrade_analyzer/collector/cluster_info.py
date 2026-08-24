"""Read-only Kubernetes cluster inventory collector.

Safety: every command is a kubectl get/version/top/api-resources/cluster-info
read. No create/apply/patch/delete/scale/drain/cordon is ever executed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from k8s_upgrade_analyzer.models import ClusterSnapshot

# Hard blocklist — refuse any non-read verbs if somehow passed in.
_FORBIDDEN = re.compile(
    r"\b(apply|create|delete|patch|replace|edit|scale|drain|cordon|uncordon|"
    r"taint|label|annotate|exec|attach|cp|run|set|rollout|certificate|"
    r"approve|deny|debug)\b",
    re.IGNORECASE,
)

_MAX_FIELD_CHARS = 400_000  # keep Claude/local prompts manageable


def _run(
    cmd: str,
    kubeconfig: str | None = None,
    *,
    truncate: bool = True,
    max_chars: int = _MAX_FIELD_CHARS,
) -> tuple[str, str | None]:
    if _FORBIDDEN.search(cmd):
        return "", f"Blocked non-read command: {cmd}"

    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    out = result.stdout or ""
    err = result.stderr.strip() if result.returncode != 0 else None
    if truncate and len(out) > max_chars:
        out = out[:max_chars] + f"\n\n...[truncated {len(out) - max_chars} chars]..."
    return out, err


def _summarize_crds(crds_json: str) -> str:
    try:
        data = json.loads(crds_json)
    except json.JSONDecodeError:
        return "(unable to parse CRD JSON)"

    rows = []
    for item in data.get("items", []):
        meta = item.get("metadata", {})
        spec = item.get("spec", {})
        versions = spec.get("versions", [])
        served = [v.get("name") for v in versions if v.get("served")]
        storage = [v.get("name") for v in versions if v.get("storage")]
        conversion = (spec.get("conversion") or {}).get("strategy", "None")
        webhook = "yes" if (spec.get("conversion") or {}).get("webhook") else "no"
        rows.append(
            {
                "name": meta.get("name"),
                "group": spec.get("group"),
                "kind": (spec.get("names") or {}).get("kind"),
                "served": served,
                "storage": storage,
                "conversion": conversion,
                "conversion_webhook": webhook,
            }
        )
    return json.dumps(rows, indent=2)


def collect(kubeconfig: str | None = None) -> ClusterSnapshot:
    """Collect a full read-only inventory of the current kubectl context."""
    snapshot = ClusterSnapshot()
    errors: list[str] = []

    steps: list[tuple[str, str]] = [
        ("kubectl_version", "kubectl version"),
        ("cluster_info", "kubectl cluster-info"),
        ("nodes", "kubectl get nodes -o wide"),
        ("namespaces", "kubectl get ns"),
        ("api_resources", "kubectl api-resources"),
        ("api_services", "kubectl get apiservices"),
        ("all_resources", "kubectl get all -A"),
        ("deployments", "kubectl get deploy -A -o wide"),
        ("statefulsets", "kubectl get sts -A -o wide"),
        ("daemonsets", "kubectl get ds -A -o wide"),
        ("jobs", "kubectl get jobs -A"),
        ("cronjobs", "kubectl get cronjobs -A"),
        ("crds_list", "kubectl get crd"),
        ("validating_webhooks", "kubectl get validatingwebhookconfigurations -o yaml"),
        ("mutating_webhooks", "kubectl get mutatingwebhookconfigurations -o yaml"),
        (
            "webhook_policies",
            "kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations "
            "-o jsonpath='{range .items[*]}{.kind}/{.metadata.name}{\"\\t\"}"
            "{range .webhooks[*]}{.name}{\"|\"}{.failurePolicy}{\"|\"}{.sideEffects}{\" \"}"
            "{end}{\"\\n\"}{end}'",
        ),
        ("nodes_yaml", "kubectl get nodes -o yaml"),
        ("top_nodes", "kubectl top nodes"),
        ("top_pods", "kubectl top pods -A"),
        ("storage_classes", "kubectl get sc -o yaml"),
        ("csi_drivers", "kubectl get csidrivers -o wide"),
        ("persistent_volumes", "kubectl get pv"),
        ("persistent_volume_claims", "kubectl get pvc -A"),
        ("ingresses", "kubectl get ingress -A"),
        ("network_policies", "kubectl get networkpolicy -A"),
        (
            "workload_images",
            "kubectl get deploy,ds,sts -A -o jsonpath="
            "'{range .items[*]}{.metadata.namespace}{\"\\t\"}{.metadata.name}{\"\\t\"}"
            "{range .spec.template.spec.containers[*]}{.image}{\" \"}{end}{\"\\n\"}{end}'",
        ),
        (
            "kube_system_workloads",
            "kubectl get deploy,ds -n kube-system -o jsonpath="
            "'{range .items[*]}{.kind}/{.metadata.name}{\"\\t\"}"
            "{range .spec.template.spec.containers[*]}{.image}{\" \"}{end}{\"\\n\"}{end}'",
        ),
    ]

    for field, cmd in steps:
        output, err = _run(cmd, kubeconfig)
        setattr(snapshot, field, output)
        if err:
            errors.append(f"{cmd}: {err}")

    # CRD JSON → compact summary (must NOT truncate before parse; full YAML is tens of MB)
    crds_json, err = _run("kubectl get crd -o json", kubeconfig, truncate=False)
    if err:
        errors.append(f"kubectl get crd -o json: {err}")
    snapshot.crds_summary = _summarize_crds(crds_json)
    # Keep a truncated YAML for AI prompts; prefer summary for local analysis
    crds_yaml, err = _run(
        "kubectl get crd -o yaml", kubeconfig, truncate=True, max_chars=120_000
    )
    if err:
        errors.append(f"kubectl get crd -o yaml: {err}")
    snapshot.crds_yaml = crds_yaml

    snapshot.errors = errors
    return snapshot


def save_snapshot(snapshot: ClusterSnapshot, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": snapshot.model_dump(),
    }
    out.write_text(json.dumps(payload, indent=2))
    return out


def load_snapshot(path: str | Path) -> ClusterSnapshot:
    data = json.loads(Path(path).read_text())
    raw = data.get("snapshot", data)
    return ClusterSnapshot.model_validate(raw)
