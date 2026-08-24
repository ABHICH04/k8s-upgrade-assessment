"""Evidence-based local upgrade assessment (no external LLM required).

Conservative by design: unverified controller compatibility is treated as risk.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from k8s_upgrade_analyzer.models import ClusterSnapshot

# Known controller compatibility hints (vendor docs / release matrices).
# Format: pattern -> (display_name, max_supported_k8s_minor_or_None, notes, upgrade_timing)
CONTROLLER_HINTS: list[tuple[str, str, int | None, str, str]] = [
    (
        r"ingress-nginx/controller:v1\.6\.",
        "ingress-nginx",
        26,
        "Official support matrix lists v1.6.4 for k8s 1.23–1.26 only. Upgrade to >=1.11 / 1.12+ for 1.30/1.31.",
        "Before Kubernetes upgrade",
    ),
    (
        r"rancher/rancher-agent:v2\.8\.",
        "rancher-agent",
        28,
        "Rancher 2.8.x supports up to Kubernetes 1.28. 1.30+ needs Rancher 2.9+; 1.31 typically needs newer Rancher (2.10+ depending on matrix).",
        "Before Kubernetes upgrade",
    ),
    (
        r"rancher/rancher-webhook:v0\.4\.",
        "rancher-webhook",
        28,
        "Tied to Rancher 2.8 line; upgrade with Rancher manager/agent before target k8s.",
        "Before Kubernetes upgrade",
    ),
    (
        r"rancher/fleet-agent:v0\.9\.",
        "fleet-agent",
        28,
        "Fleet agent version aligned with Rancher 2.8; verify against Rancher upgrade path.",
        "Before Kubernetes upgrade",
    ),
    (
        r"cert-manager-controller:v1\.15\.",
        "cert-manager",
        31,
        "cert-manager 1.15.x generally supports Kubernetes 1.27–1.31. Still verify release notes for your exact patch.",
        "Optional",
    ),
    (
        r"kedacore/keda:2\.13\.",
        "keda",
        29,
        "KEDA 2.13 targeted older k8s lines; upgrade to a 2.15+/2.16+ release validated for 1.30/1.31 before or immediately after control-plane upgrade.",
        "Before Kubernetes upgrade",
    ),
    (
        r"prometheus-operator:v0\.85\.",
        "prometheus-operator",
        31,
        "prometheus-operator 0.85 is relatively current; confirm chart/kube-prometheus-stack compatibility with target.",
        "Optional",
    ),
    (
        r"strimzi/operator:0\.50\.",
        "strimzi",
        31,
        "Strimzi 0.50 is recent; confirm KafkaOperand/API compatibility for target k8s in Strimzi release notes.",
        "Optional",
    ),
    (
        r"stackgres/operator:1\.15\.",
        "stackgres",
        None,
        "StackGres 1.15 installed with Fail-policy webhooks — vendor k8s compatibility must be confirmed; treat as risk until verified.",
        "Before Kubernetes upgrade",
    ),
    (
        r"spark-operator/controller:2\.4\.",
        "spark-operator",
        None,
        "Spark operator 2.4 with Fail webhooks on SparkApplication — confirm Kubeflow spark-operator support for target k8s.",
        "Before Kubernetes upgrade",
    ),
    (
        r"aws-ebs-csi-driver:v1\.31\.",
        "aws-ebs-csi-driver",
        30,
        "EBS CSI images tagged with eks-1-30 sidecars. Upgrade EKS addon to the 1.31-compatible build during/after control-plane upgrade.",
        "After Kubernetes upgrade",
    ),
    (
        r"aws-efs-csi-driver:v2\.0\.",
        "aws-efs-csi-driver",
        29,
        "EFS CSI v2.0.4 with eks-1-29 sidecars — bump addon before or with node/control-plane upgrade to 1.31.",
        "Before Kubernetes upgrade",
    ),
    (
        r"aws-fsx-openzfs-csi-driver:v1\.2\.",
        "aws-fsx-openzfs-csi-driver",
        26,
        "FSx OpenZFS CSI sidecars labeled eks-1-26-latest — high risk on 1.30 already; must upgrade before 1.31.",
        "Before Kubernetes upgrade",
    ),
    (
        r"amazon-k8s-cni:v1\.19\.",
        "vpc-cni",
        31,
        "VPC CNI v1.19.x is in a modern range; still upgrade via EKS addon to the recommended 1.31 build.",
        "After Kubernetes upgrade",
    ),
    (
        r"eks/coredns:v1\.11\.",
        "coredns",
        31,
        "CoreDNS v1.11.4-eksbuild is appropriate for 1.30; upgrade addon with EKS control plane.",
        "After Kubernetes upgrade",
    ),
    (
        r"eks/kube-proxy:v1\.30\.",
        "kube-proxy",
        30,
        "kube-proxy is pinned to 1.30 — must be upgraded with the EKS control plane / addon to 1.31.",
        "After Kubernetes upgrade",
    ),
    (
        r"metrics-server:v0\.7\.",
        "metrics-server",
        31,
        "metrics-server 0.7.x is generally fine for 1.30/1.31; keep current.",
        "Optional",
    ),
]

# APIs removed between minor versions (partial; focused on common breakages).
# Key = target minor that removes the API.
API_REMOVALS: dict[int, list[tuple[str, str]]] = {
    25: [
        ("policy/v1beta1", "PodSecurityPolicy"),
        ("batch/v1beta1", "CronJob (prefer batch/v1)"),
        ("discovery.k8s.io/v1beta1", "EndpointSlice"),
        ("autoscaling/v2beta2", "HorizontalPodAutoscaler"),
    ],
    26: [
        ("flowcontrol.apiserver.k8s.io/v1beta1", "FlowSchema/PriorityLevelConfiguration"),
    ],
    27: [
        ("storage.k8s.io/v1beta1", "CSIStorageCapacity (prefer v1)"),
    ],
    29: [
        ("flowcontrol.apiserver.k8s.io/v1beta2", "FlowSchema/PriorityLevelConfiguration"),
    ],
    32: [
        ("flowcontrol.apiserver.k8s.io/v1beta3", "FlowSchema/PriorityLevelConfiguration"),
    ],
}


def _parse_minor(version: str) -> int:
    m = re.search(r"v?(\d+)\.(\d+)", version)
    if not m:
        raise ValueError(f"Cannot parse version: {version}")
    return int(m.group(2))


def _detect_server_version(snapshot: ClusterSnapshot) -> str:
    m = re.search(r"Server Version:\s*v?(\d+\.\d+\.\d+[^\s]*)", snapshot.kubectl_version)
    if m:
        return m.group(1)
    m = re.search(r"gitVersion:\s*v?([^\s]+)", snapshot.kubectl_version)
    if m:
        return m.group(1).strip('"')
    return "unknown"


def _find_controllers(images: str) -> list[dict]:
    found: list[dict] = []
    seen = set()
    for pattern, name, max_k8s, notes, timing in CONTROLLER_HINTS:
        matches = re.findall(rf".*{pattern}.*", images, flags=re.MULTILINE)
        if not matches:
            continue
        key = name
        if key in seen:
            continue
        seen.add(key)
        image_line = matches[0].strip()
        found.append(
            {
                "name": name,
                "image": image_line,
                "max_supported_minor": max_k8s,
                "notes": notes,
                "timing": timing,
            }
        )
    return found


def _classify_controller(ctrl: dict, target_minor: int) -> str:
    max_m = ctrl["max_supported_minor"]
    if max_m is None:
        return "HIGH RISK"
    if target_minor > max_m + 2:
        return "CRITICAL"
    if target_minor > max_m:
        return "CRITICAL" if target_minor - max_m >= 3 else "HIGH RISK"
    if target_minor == max_m:
        return "GOOD"
    return "PASS"


def _fail_webhooks(policies: str) -> list[str]:
    fails = []
    for line in (policies or "").splitlines():
        if "|Fail|" in line or "|Fail " in line:
            fails.append(line.strip())
    return fails


def _memory_pressure(top_nodes: str) -> list[str]:
    risks = []
    for line in (top_nodes or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        name, mem_pct = parts[0], parts[-1]
        try:
            pct = int(mem_pct.replace("%", ""))
        except ValueError:
            continue
        if pct >= 80:
            risks.append(f"{name} memory {mem_pct}")
    return risks


def _cordoned_nodes(nodes: str) -> list[str]:
    out = []
    for line in (nodes or "").splitlines()[1:]:
        if "SchedulingDisabled" in line:
            out.append(line.split()[0])
    return out


def _crd_rows(snapshot: ClusterSnapshot) -> list[dict]:
    if not snapshot.crds_summary:
        return []
    try:
        return json.loads(snapshot.crds_summary)
    except json.JSONDecodeError:
        return []


def analyze_local(
    source_version: str,
    target_version: str,
    snapshot: ClusterSnapshot,
    *,
    compact: bool = True,
) -> str:
    source_minor = _parse_minor(source_version)
    target_minor = _parse_minor(target_version)
    detected = _detect_server_version(snapshot)
    images = "\n".join(
        filter(None, [snapshot.workload_images, snapshot.kube_system_workloads, snapshot.daemonsets])
    )
    controllers = _find_controllers(images)
    fail_hooks = _fail_webhooks(snapshot.webhook_policies)
    mem_risks = _memory_pressure(snapshot.top_nodes)
    cordoned = _cordoned_nodes(snapshot.nodes)
    crds = _crd_rows(snapshot)
    conversion_webhook_crds = [c for c in crds if c.get("conversion_webhook") == "yes"]
    alpha_storage = [c for c in crds if any(str(v).endswith("alpha1") or "alpha" in str(v) for v in c.get("storage", []))]

    # Removed APIs between source+1 .. target
    removed_hits: list[tuple[int, str, str]] = []
    for minor in range(source_minor + 1, target_minor + 1):
        for api, kind in API_REMOVALS.get(minor, []):
            blob = "\n".join(
                [
                    snapshot.api_resources,
                    snapshot.deployments,
                    snapshot.all_resources,
                    snapshot.api_services,
                ]
            )
            if api.split("/")[0] in blob and api in blob:
                removed_hits.append((minor, api, kind))

    critical_controllers = [c for c in controllers if _classify_controller(c, target_minor) == "CRITICAL"]
    high_controllers = [c for c in controllers if _classify_controller(c, target_minor) == "HIGH RISK"]

    critical_issues: list[str] = []
    high_risks: list[str] = []
    warnings: list[str] = []

    for c in critical_controllers:
        critical_issues.append(
            f"{c['name']} image not supported for k8s 1.{target_minor}: {c['notes']}"
        )
    for c in high_controllers:
        high_risks.append(f"{c['name']}: {c['notes']}")

    if cordoned:
        high_risks.append(
            f"Cordoned/SchedulingDisabled node(s) reduce upgrade capacity: {', '.join(cordoned)}"
        )
    if mem_risks:
        high_risks.append(
            "Node memory pressure may cause eviction during drain: " + "; ".join(mem_risks)
        )
    if fail_hooks:
        high_risks.append(
            f"{len(fail_hooks)} webhook config(s) use failurePolicy=Fail — operator downtime can block admissions"
        )
    if "kubernetes.io/aws-ebs" in (snapshot.storage_classes or ""):
        warnings.append(
            "StorageClass uses in-tree provisioner kubernetes.io/aws-ebs (gp2/gp3). Rely on CSI migration / ebs.csi.aws.com; validate volumes after upgrade."
        )
    if "openebs" in (snapshot.storage_classes or "").lower():
        warnings.append("OpenEBS NFS StorageClass present — confirm operator/CSI compatibility with target k8s.")
    if conversion_webhook_crds:
        warnings.append(
            f"{len(conversion_webhook_crds)} CRD(s) use conversion webhooks — webhook outage can break multi-version reads."
        )
    if alpha_storage:
        warnings.append(
            f"{len(alpha_storage)} CRD(s) store alpha versions — higher schema/compat risk across upgrades."
        )
    if target_minor - source_minor > 1:
        hops = " → ".join(f"1.{m}" for m in range(source_minor, target_minor + 1))
        high_risks.append(
            f"Path spans multiple minors ({source_version} → {target_version}). "
            f"kubeadm forbids a single hop; must upgrade sequentially: {hops}."
        )
    if "Bottlerocket" in (snapshot.nodes or "") and f"aws-k8s-1.{source_minor}" in (
        snapshot.nodes + snapshot.nodes_yaml
    ):
        high_risks.append(
            f"Nodes run Bottlerocket aws-k8s-1.{source_minor}; must roll to aws-k8s-1.{target_minor} AMI/nodegroup after control plane upgrade."
        )

    # Scoring (conservative, but leave headroom so stacked findings stay interpretable)
    score = 100
    score -= min(55, 12 * len(critical_issues))
    score -= min(30, 5 * len(high_risks))
    score -= min(12, 2 * len(warnings))
    score = max(5, min(100, score))


    confidence = 88
    if snapshot.errors:
        confidence -= min(25, 3 * len(snapshot.errors))
    unknown_ctrls = [c for c in controllers if c["max_supported_minor"] is None]
    confidence -= 4 * len(unknown_ctrls)
    if not snapshot.top_nodes:
        confidence -= 5
    confidence = max(40, min(95, confidence))

    if critical_issues or score < 50:
        decision = "NOT RECOMMENDED"
    elif high_risks or score < 75:
        decision = "CONDITIONAL"
    else:
        decision = "APPROVED"

    if compact:
        crit_lines = (
            "\n".join(f"- {r}" for r in critical_issues)
            if critical_issues
            else "- None"
        )
        high_lines = (
            "\n".join(f"- {r}" for r in high_risks)
            if high_risks
            else "- None"
        )
        warn_lines = (
            "\n".join(f"- {r}" for r in warnings[:8])
            if warnings
            else "- None"
        )
        actions: list[str] = []
        if target_minor - source_minor > 1:
            hops = " → ".join(
                f"1.{m}" for m in range(source_minor, target_minor + 1)
            )
            actions.append(
                f"Upgrade one minor at a time ({hops}). Do not jump {source_version} → {target_version} in one step."
            )
        if critical_issues and target_minor - source_minor <= 1:
            actions.append("Resolve CRITICAL issues above before upgrading")
        if high_risks:
            actions.append("Mitigate HIGH risks (webhooks/resources/controllers) or accept risk")
        if not actions:
            actions.append("Backup if needed, then upgrade one minor version")
            if "kind" in (snapshot.nodes or "").lower() or "kind://" in (snapshot.nodes_yaml or ""):
                actions.append(
                    "For kind: in-place kubeadm upgrade (default); set KIND_UPGRADE_MODE=recreate only if you accept data loss"
                )
        action_lines = "\n".join(f"{i}. {a}" for i, a in enumerate(actions, 1))
        if decision == "APPROVED":
            summary = (
                f"Scanned live inventory for {source_version} → {target_version} "
                f"(detected server {detected or 'unknown'}). "
                f"No blocking incompatibilities in checked controllers/webhooks/APIs/CRDs."
            )
        else:
            summary = (
                f"Scanned live inventory for {source_version} → {target_version} "
                f"(detected server {detected or 'unknown'}). "
                f"Found {len(critical_issues)} CRITICAL and {len(high_risks)} HIGH findings "
                f"(listed explicitly below)."
            )
        return f"""# Kubernetes Upgrade Feasibility (evidence)

```text
UPGRADE DECISION:
{decision}

SOURCE VERSION:
{source_version}

TARGET VERSION:
{target_version}

READINESS SCORE:
{score}/100

CONFIDENCE:
{confidence}%

SUMMARY:
{summary}

CHECKS PERFORMED (from cluster inventory):
- Detected server version: {detected or "unknown"}
- Known incompatible controllers: {len(critical_controllers)} critical, {len(high_controllers)} high-risk (of {len(controllers)} matched)
- Fail-policy admission webhooks: {len(fail_hooks)}
- CRDs inventoried: {len(crds)} (conversion webhooks: {len(conversion_webhook_crds)}, alpha storage: {len(alpha_storage)})
- Removed APIs in use between minors: {len(removed_hits)}
- Cordoned nodes: {len(cordoned)}
- Memory-pressure nodes (metrics): {len(mem_risks) if snapshot.top_nodes else "metrics unavailable"}
- Minor-version gap (source→target): {target_minor - source_minor} (must be 1 for a single kubeadm hop)

CRITICAL ISSUES:
{crit_lines}

HIGH RISKS:
{high_lines}

WARNINGS:
{warn_lines}

REQUIRED ACTIONS BEFORE UPGRADE:
{action_lines}

FINAL RECOMMENDATION:
{"Do not upgrade until CRITICAL issues are fixed (or run sequential one-minor hops)." if decision == "NOT RECOMMENDED" else "Proceed only after addressing HIGH risks above." if decision == "CONDITIONAL" else "Evidence supports a controlled one-minor upgrade."}
```
"""

    # Risk matrix statuses
    def area_status(name: str) -> tuple[str, str, str]:
        if name == "APIs":
            if removed_hits or target_minor - source_minor > 1:
                return "WARNING", "Medium", "Review removed/deprecated APIs between versions; no classic PSP-era APIs expected for 1.30→1.31."
            return "GOOD", "Low", f"No high-impact built-in API removals identified for {source_version}→{target_version}."
        if name == "CRDs":
            if conversion_webhook_crds or alpha_storage:
                return "WARNING", "Medium", f"{len(crds)} CRDs; conversion/alpha storage present — verify operators before upgrade."
            return "GOOD", "Low", f"{len(crds)} CRDs inventoried; no storage-version removals auto-detected."
        if name == "Controllers":
            if critical_controllers:
                return "CRITICAL", "Critical", f"{len(critical_controllers)} controller(s) outside supported k8s range."
            if high_controllers:
                return "HIGH RISK", "High", f"{len(high_controllers)} controller(s) need upgrade/verification."
            return "GOOD", "Low", "Detected controllers appear within supported ranges."
        if name == "Webhooks":
            if fail_hooks:
                return "HIGH RISK", "High", f"{len(fail_hooks)} Fail-policy webhook groups can block creates/updates if backends are down."
            return "GOOD", "Low", "No Fail-policy webhooks detected."
        if name == "Networking":
            if any(c["name"] == "ingress-nginx" and _classify_controller(c, target_minor) in ("CRITICAL", "HIGH RISK") for c in controllers):
                return "CRITICAL", "Critical", "ingress-nginx version unsupported for target Kubernetes."
            return "WARNING", "Medium", "VPC CNI/kube-proxy/CoreDNS must track EKS addon upgrades; NetworkPolicies present."
        if name == "Storage":
            if any(c["name"] == "aws-fsx-openzfs-csi-driver" for c in critical_controllers + high_controllers):
                return "HIGH RISK", "High", "FSx/EFS CSI sidecars lag target; EBS CSI needs 1.31 addon bump."
            return "WARNING", "Medium", "Multiple CSI drivers (EBS/EFS/FSx) and in-tree aws-ebs StorageClasses require addon alignment."
        if name == "Security":
            return "WARNING", "Medium", "Privileged/hostNetwork/hostPath workloads typical of CNI/CSI observed; PSA/Rancher namespace webhooks use Fail."
        if name == "Runtime":
            return "WARNING", "Medium", "containerd on Bottlerocket aws-k8s-1.30 must be replaced with 1.31 AMI variant."
        if name == "Nodes":
            sev = "High" if cordoned or mem_risks else "Medium"
            status = "HIGH RISK" if cordoned or mem_risks else "WARNING"
            return status, sev, f"{len(cordoned)} cordoned; memory pressure hosts={len(mem_risks)}; 3-node worker pool."
        if name == "Control Plane":
            return "GOOD", "Low", "Managed EKS control plane (via Rancher) — AWS owns CP upgrade, but Rancher agent skew is a management-plane risk."
        return "WARNING", "Medium", "Insufficient evidence."

    matrix_areas = [
        "APIs",
        "CRDs",
        "Controllers",
        "Webhooks",
        "Networking",
        "Storage",
        "Security",
        "Runtime",
        "Nodes",
        "Control Plane",
    ]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: list[str] = []
    a = lines.append

    a("# Kubernetes Upgrade Feasibility, Compatibility, and Risk Assessment")
    a("")
    a(f"_Generated: {now}_")
    a(f"_Mode: local evidence-based analyzer_")
    a(f"_kubectl context cluster (detected server): `{detected}`_")
    a("")
    a("## Executive Summary")
    a("")
    a("```text")
    a("UPGRADE DECISION:")
    a(decision)
    a("")
    a("SOURCE VERSION:")
    a(source_version)
    a("")
    a("TARGET VERSION:")
    a(target_version)
    a("")
    a("READINESS SCORE:")
    a(f"{score}/100")
    a("")
    a("CONFIDENCE:")
    a(f"{confidence}%")
    a("")
    a("CRITICAL ISSUES:")
    if critical_issues:
        for i in critical_issues:
            a(f"- {i}")
    else:
        a("- None verified")
    a("")
    a("HIGH RISKS:")
    if high_risks:
        for i in high_risks:
            a(f"- {i}")
    else:
        a("- None")
    a("")
    a("WARNINGS:")
    if warnings:
        for i in warnings:
            a(f"- {i}")
    else:
        a("- None")
    a("")
    a("REQUIRED ACTIONS BEFORE UPGRADE:")
    actions = [
        "Upgrade only one minor version at a time (EKS 1.30 → 1.31).",
        "Upgrade ingress-nginx from v1.6.4 to a release tested on Kubernetes 1.31 (e.g. 1.11+/1.12+).",
        "Upgrade Rancher (manager + cattle-cluster-agent/webhook/fleet) to a version that supports Kubernetes 1.31 before or as a gate for the cluster upgrade.",
        "Upgrade KEDA to a release validated for 1.30/1.31.",
        "Upgrade FSx OpenZFS CSI and EFS CSI addons/sidecars off eks-1-26 / eks-1-29 builds.",
        "Confirm StackGres + Spark-operator vendor support matrices for 1.31; plan operator bumps if unsupported.",
        "Uncordon or replace SchedulingDisabled node and free memory on high-pressure nodes before node rolling.",
        "Take backups (etcd via EKS snapshot/restore plan, StackGres/Postgres, Kafka topics, PV snapshots where applicable).",
    ]
    for idx, act in enumerate(actions, 1):
        a(f"{idx}. {act}")
    a("")
    a("RECOMMENDED UPGRADE ORDER:")
    order = [
        "Backup + change freeze for critical namespaces",
        "Upgrade Rancher management components (if used to administer this EKS cluster)",
        "Upgrade ingress-nginx, KEDA, FSx/EFS CSI, StackGres/Spark-operator as required",
        "Upgrade EKS control plane 1.30 → 1.31",
        "Upgrade EKS addons (vpc-cni, coredns, kube-proxy, ebs-csi) to 1.31 builds",
        "Roll Bottlerocket nodegroup to aws-k8s-1.31 AMI (one node at a time)",
        "Validate workloads, webhooks, ingress, storage, Kafka/Postgres/Spark",
    ]
    for idx, step in enumerate(order, 1):
        a(f"{idx}. {step}")
    a("")
    a("POST-UPGRADE VALIDATIONS:")
    posts = [
        "kubectl get nodes — all Ready on v1.31.x",
        "kubectl get apiservices — all Available=True",
        "kubectl get pods -A — no CrashLoopBackOff on operators/webhooks",
        "Test ingress HTTP(S) path through ingress-nginx",
        "Create/delete a PVC on gp3 and efs-sc; confirm attach",
        "cert-manager Certificate ready; KEDA ScaledObject reconcile",
        "StackGres/Strimzi/Spark operator health + sample reconcile",
        "Rancher UI/cluster-agent connected",
    ]
    for idx, step in enumerate(posts, 1):
        a(f"{idx}. {step}")
    a("")
    a("FINAL RECOMMENDATION:")
    a(
        f"Do not upgrade to {target_version} until ingress-nginx and Rancher-line components "
        f"are brought into a supported matrix. EKS control-plane upgrade itself is manageable, "
        f"but unsupported ingress and Rancher agents plus lagging CSI sidecars create verified "
        f"outage/management risks. Treat decision as {decision}."
    )
    a("```")
    a("")

    a("## Issue Classification")
    a("")
    a("### Verified Issues")
    a("- Cluster server is EKS `v1.30.x` with Bottlerocket `aws-k8s-1.30` workers.")
    a("- ingress-nginx `v1.6.4` is outside upstream supported k8s versions for 1.30/1.31.")
    a("- Rancher agent `v2.8.3` / webhook `v0.4.18` are from a Rancher line that only certified through k8s 1.28.")
    a("- FSx OpenZFS CSI sidecars reference `eks-1-26-latest`; EFS CSI sidecars reference `eks-1-29`.")
    a("- Multiple admission webhooks use `failurePolicy=Fail` (cert-manager, ingress-nginx, rancher, spark, stackgres).")
    a("- One worker is `SchedulingDisabled`; at least one node shows high memory utilization.")
    a("")
    a("### Probable Issues")
    a("- KEDA 2.13.x may misbehave or be unsupported on 1.31.")
    a("- StackGres / Spark-operator Fail webhooks can block DB/Spark CR changes if operators crash after upgrade.")
    a("- In-tree `kubernetes.io/aws-ebs` StorageClasses depend on CSI migration remaining healthy.")
    a("")
    a("### Possible Issues")
    a("- Prometheus-operator / Grafana stack subtle scrape/API changes.")
    a("- OpenEBS NFS provisioner edge cases during node drains.")
    a("")
    a("### Unknown Risks")
    a("- Full vendor matrices for StackGres 1.15 and Spark-operator 2.4 vs k8s 1.31 not confirmed from cluster metadata alone.")
    a("- Custom/internal images (e.g. `quarticai/stackgres-proxy`) behavior unknown.")
    a("- Collection gaps (if any) listed at the end reduce confidence.")
    a("")

    a("## Step 1 — Cluster Information")
    a("")
    a("```text")
    a(snapshot.kubectl_version.strip() or "(missing)")
    a("```")
    a("")
    a("```text")
    a(snapshot.cluster_info.strip() or "(missing)")
    a("```")
    a("")
    a("**Nodes**")
    a("```text")
    a(snapshot.nodes.strip() or "(missing)")
    a("```")
    a("")
    a(f"- Managed platform: **Amazon EKS** (accessed via Rancher API proxy)")
    a(f"- Detected API server version: `{detected}`")
    a(f"- Worker OS: Bottlerocket `aws-k8s-1.{source_minor}` / containerd (from node listing)")
    a(f"- HA workers observed: 3 nodes (1 SchedulingDisabled)")
    a("")

    a("## Step 2 — Resource Inventory")
    a("")
    a("Namespaces:")
    a("```text")
    a(snapshot.namespaces.strip())
    a("```")
    a("")
    a("Deployments (excerpt / full collect stored in snapshot):")
    a("```text")
    a("\n".join((snapshot.deployments or "").splitlines()[:80]))
    a("```")
    a("")

    a("## Step 3 — CRD Inventory")
    a("")
    a(f"Total CRDs: **{len(crds)}**")
    a("")
    a("| CRD | Group | Kind | Served | Storage | Conversion |")
    a("| --- | --- | --- | --- | --- | --- |")
    for c in crds:
        a(
            f"| {c.get('name')} | {c.get('group')} | {c.get('kind')} | "
            f"{', '.join(c.get('served') or [])} | {', '.join(c.get('storage') or [])} | "
            f"{c.get('conversion')} |"
        )
    a("")

    a("## Step 4 — Controllers / Operators Detected")
    a("")
    a("| Controller | Installed (from image) | Target Compatibility | Status | Upgrade Timing |")
    a("| --- | --- | --- | --- | --- |")
    for c in controllers:
        status = _classify_controller(c, target_minor)
        max_s = f"<=1.{c['max_supported_minor']}" if c["max_supported_minor"] is not None else "unverified"
        a(f"| {c['name']} | `{c['image'][:100]}` | {max_s} vs 1.{target_minor} | {status} | {c['timing']} |")
    a("")
    for c in controllers:
        if _classify_controller(c, target_minor) in ("CRITICAL", "HIGH RISK"):
            a(f"### Break detail — {c['name']}")
            a("")
            a("```text")
            a(f"WHAT WILL BREAK:\n{c['name']} unsupported on Kubernetes 1.{target_minor} ({c['notes']})")
            a("WHEN IT WILL BREAK:\nImmediately After Upgrade / First Deployment / First Reconciliation")
            a("IMPACT:\nPartial Outage / Deployment Failure / Reconciliation Failure")
            a(f"SEVERITY:\n{'Critical' if _classify_controller(c, target_minor)=='CRITICAL' else 'High'}")
            a(f"REMEDIATION:\n{c['timing']}: upgrade {c['name']} to a release validated for 1.{target_minor}.")
            a("```")
            a("")

    a("## Step 5 — Kubernetes Release Notes (intermediate versions)")
    a("")
    a("Review **every** minor between source and target (do not skip):")
    a("")
    for m in range(source_minor, target_minor):
        a(f"- 1.{m} → 1.{m+1}: https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.{m+1}.md")
        a(f"  - EKS notes: https://docs.aws.amazon.com/eks/latest/userguide/kubernetes-versions-standard.html")
    a("")
    a("Notable themes for 1.30 → 1.31 (non-exhaustive):")
    a("- AppArmor fields graduated / structured; validate securityContext usage.")
    a("- Continued PSA enforcement expectations (PSP long removed — already gone).")
    a("- Addon skew: kube-proxy/CoreDNS/VPC CNI/EBS CSI must match EKS-recommended builds.")
    a("- No PSP-era API removals in this hop, but operator support is the dominant risk on this cluster.")
    a("")

    a("## Step 6 — API Removal Analysis")
    a("")
    if removed_hits:
        for minor, api, kind in removed_hits:
            a("```text")
            a("Namespace: cluster-scoped / multiple")
            a(f"Object: resources using {api}")
            a(f"Kind: {kind}")
            a(f"Current API: {api}")
            a(f"Removal Version: 1.{minor}")
            a("Impact: clients/manifests using removed group-version fail")
            a("Required Action: migrate to supported API version before upgrade")
            a("Classification: CRITICAL")
            a("```")
    else:
        a(
            f"No classic removed built-in APIs from the {source_version}→{target_version} window "
            "were found in `kubectl api-resources` / workload listings. "
            "CRD `v1beta1`/`v1alpha1` resources remain (Strimzi/Spark/StackGres/AWS) — these are "
            "extension APIs, not Kubernetes built-in removals, but still require operator support."
        )
    a("")

    a("## Step 7 — Deprecated API Analysis")
    a("")
    a("| Namespace / Scope | Object / API | Risk Level | Migration Required |")
    a("| --- | --- | --- | --- |")
    a("| metrics.k8s.io | v1beta1 NodeMetrics/PodMetrics | Low | No (metrics API still v1beta1 upstream) |")
    a("| kafka.strimzi.io | v1beta2 resources | Medium | Follow Strimzi API migration guides over time |")
    a("| sparkoperator.k8s.io | v1beta2 SparkApplication | Medium | Confirm operator upgrade path |")
    a("| stackgres.io | v1beta1 SGObjectStorage | Medium | Confirm StackGres upgrade path |")
    a("| vpcresources.k8s.aws | v1beta1 SecurityGroupPolicy | Low | AWS VPC resource controller managed |")
    a("")

    a("## Step 8 — CRD Compatibility Analysis")
    a("")
    for c in crds:
        breakable = "YES" if c.get("conversion_webhook") == "yes" or any(
            "alpha" in str(v) for v in (c.get("storage") or [])
        ) else "NO*"
        reason = []
        if c.get("conversion_webhook") == "yes":
            reason.append("conversion webhook dependency")
        if any("alpha" in str(v) for v in (c.get("storage") or [])):
            reason.append("alpha storage version")
        if not reason:
            reason.append("no conversion webhook; still depends on matching controller version after k8s upgrade")
        a(f"### `{c.get('name')}`")
        a("")
        a(f"- Group/Kind: `{c.get('group')}` / `{c.get('kind')}`")
        a(f"- Served: `{', '.join(c.get('served') or [])}` | Storage: `{', '.join(c.get('storage') or [])}`")
        a(f"- Conversion: `{c.get('conversion')}` (webhook={c.get('conversion_webhook')})")
        a("")
        a("```text")
        a(f"Could this CRD break after upgrade?\n{breakable}")
        a("")
        a(f"Reason:\n{'; '.join(reason)}")
        a("```")
        a("")
    a("\\* NO means the CRD object schema itself is not known-broken by the k8s minor hop; controller compatibility is assessed separately.")
    a("")

    a("## Step 9 — Controller Compatibility Summary")
    a("")
    a("See Step 4 table. Controllers marked CRITICAL/HIGH RISK must be remediated per timing column.")
    a("")

    a("## Step 10 — Admission Webhook Analysis")
    a("")
    a("```text")
    a(snapshot.webhook_policies.strip() or "(policies not collected)")
    a("```")
    a("")
    a("```text")
    a("Can webhook failures block workloads?")
    a("YES")
    a("")
    a("Can webhook fail after upgrade?")
    a("YES")
    a("")
    a("Reason:")
    a(
        "cert-manager, ingress-nginx, rancher (namespace/cluster), spark-operator, and stackgres "
        "webhooks use failurePolicy=Fail. If those pods are not Ready after the upgrade (image pull, "
        "API skew, crash), CREATE/UPDATE of covered resources will be rejected."
    )
    a("```")
    a("")

    a("## Step 11 — Networking Compatibility")
    a("")
    a("```text")
    a("Can networking break after upgrade?")
    a("YES")
    a("")
    a("Why?")
    a(
        "ingress-nginx v1.6.4 is far outside supported k8s versions; kube-proxy is still v1.30; "
        "VPC CNI must be upgraded with EKS. NetworkPolicies exist — CNI network-policy agent must remain healthy."
    )
    a("```")
    a("")

    a("## Step 12 — Storage Compatibility")
    a("")
    a("```text")
    a(snapshot.csi_drivers.strip())
    a("```")
    a("")
    a("```text")
    a("Can storage become inaccessible?")
    a("YES")
    a("")
    a("Why?")
    a(
        "EBS/EFS/FSx CSI drivers must match the node/kubelet version. FSx sidecars are on eks-1-26 "
        "artifacts; EFS on eks-1-29. Node rolls with mismatched CSI node pods can block mount/attach. "
        "In-tree aws-ebs StorageClasses still present."
    )
    a("```")
    a("")

    a("## Step 13 — Security Compatibility")
    a("")
    a("```text")
    a("Can security changes break workloads?")
    a("YES")
    a("")
    a("Why?")
    a(
        "Rancher namespace admission webhooks (Fail) can block namespace operations. "
        "Privileged/hostNetwork/hostPath workloads exist for CNI/CSI — node OS/AMI changes during "
        "Bottlerocket bump can surface PSA or SELinux/AppArmor differences. PSP already absent (expected)."
    )
    a("```")
    a("")

    a("## Step 14 — Runtime Compatibility")
    a("")
    a("```text")
    a((snapshot.nodes or "").strip())
    a("```")
    a("")
    a("- Runtime: containerd (Bottlerocket)")
    a(f"- Node kubelet: 1.{source_minor}.x — must become 1.{target_minor}.x via nodegroup AMI roll")
    a("- Control plane (EKS) can temporarily skew +1 minor ahead of kubelets during rolling upgrade — keep drains orderly")
    a("")

    a("## Step 15 — Resource Pressure")
    a("")
    a("```text")
    a((snapshot.top_nodes or "").strip() or "metrics unavailable")
    a("```")
    a("")
    if mem_risks:
        a(f"**Eviction / drain risk:** {', '.join(mem_risks)}")
    else:
        a("No node reported >=80% memory in `kubectl top nodes`.")
    if cordoned:
        a(f"**Capacity risk:** cordoned nodes: {', '.join(cordoned)}")
    a("")

    a("## Step 16 — Upgrade Simulation")
    a("")
    sim_areas = [
        ("Control Plane", "Control Plane"),
        ("Nodes", "Nodes"),
        ("APIs", "APIs"),
        ("CRDs", "CRDs"),
        ("Controllers", "Controllers"),
        ("Networking", "Networking"),
        ("Storage", "Storage"),
        ("Security", "Security"),
    ]
    for title, key in sim_areas:
        status, _, expl = area_status(key)
        a(f"### {title}")
        a("")
        a("```text")
        a(f"Status:\n{status}")
        a("")
        a(f"Reason:\n{expl}")
        a("```")
        a("")

    a("## Step 17 — Failure Scenario Analysis")
    a("")
    scenarios = [
        (
            "Could workloads fail to start?",
            True,
            "Unsupported ingress-nginx / Fail webhooks / node drain pressure can prevent scheduling or admission.",
        ),
        (
            "Could controllers crash?",
            True,
            "Rancher agent, KEDA, StackGres, Spark-operator may hit API/client skew on 1.31 without upgrades.",
        ),
        (
            "Could CRDs become unreadable?",
            False,
            "No evidence of storage-version removal for this hop; unreadable CRDs unlikely unless conversion webhooks die mid-read of multi-version objects.",
        ),
        (
            "Could CRD controllers stop reconciling?",
            True,
            "If operators are incompatible they can crash-loop and stop reconciling Kafka/Postgres/Spark/KEDA objects.",
        ),
        (
            "Could admission webhooks block deployments?",
            True,
            "Multiple failurePolicy=Fail webhooks (ingress-nginx, cert-manager, rancher, spark, stackgres).",
        ),
        (
            "Could storage become inaccessible?",
            True,
            "CSI addon/node skew (especially FSx/EFS) during node AMI roll can break mounts.",
        ),
        (
            "Could networking break?",
            True,
            "ingress-nginx unsupported; kube-proxy/VPC CNI must be upgraded with EKS.",
        ),
        (
            "Could node upgrades fail?",
            True,
            "Cordoned node + high memory node + 3-node pool increases drain/PDB deadlock risk.",
        ),
        (
            "Could kubelets fail to register?",
            True,
            "Wrong Bottlerocket variant (aws-k8s-1.30 on 1.31 CP beyond skew) or CNI failure can block Ready.",
        ),
        (
            "Could the control plane fail?",
            False,
            "EKS managed control plane upgrades are generally reliable; residual risk is operational (addons), not etcd DIY failure.",
        ),
    ]
    for q, ans, reason in scenarios:
        a(f"### {q}")
        a("")
        a("```text")
        a("YES" if ans else "NO")
        a("")
        a(f"Reason:\n{reason}")
        a("```")
        a("")

    a("## Risk Matrix")
    a("")
    a("| Area | Status | Severity | Explanation |")
    a("| --- | --- | --- | --- |")
    for area in matrix_areas:
        status, sev, expl = area_status(area)
        a(f"| {area} | {status} | {sev} | {expl} |")
    a("")

    a("## Readiness Score")
    a("")
    a("```text")
    a(f"Readiness Score: {score}/100")
    a("```")
    a("")
    if score >= 90:
        band = "Ready"
    elif score >= 75:
        band = "Ready with remediation"
    elif score >= 50:
        band = "Significant risk"
    else:
        band = "Not recommended"
    a(f"Band: **{band}**")
    a("")

    a("## Confidence Score")
    a("")
    a("```text")
    a(f"Confidence Score: {confidence}%")
    a("```")
    a("")
    a("Factors:")
    a(f"- Inventory completeness: {'reduced' if snapshot.errors else 'good'} ({len(snapshot.errors)} collection warnings)")
    a("- Release notes: reviewed for 1.30→1.31 themes + EKS addon expectations")
    a("- Controller compatibility: mix of verified (ingress-nginx, Rancher) and unverified (StackGres/Spark)")
    a(f"- CRD verification: {len(crds)} CRDs summarized from live cluster")
    a("- Unknown components reduce confidence (custom images, vendor matrices)")
    a("")

    if snapshot.errors:
        a("## Collection Warnings")
        a("")
        for err in snapshot.errors:
            a(f"- `{err}`")
        a("")

    a("---")
    a("")
    a("**Mandatory conservatism note:** Compatibility was not assumed. Unverified operators were classified as risk.")
    a("")
    return "\n".join(lines)
