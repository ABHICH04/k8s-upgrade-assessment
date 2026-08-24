"""Detect Kubernetes distribution so upgrade plans are not EKS-only.

Supports:
  - kind
  - kops
  - eks
  - gke / aks (basic detection)
  - kubeadm / generic self-managed
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Literal

Platform = Literal["kind", "kops", "eks", "gke", "aks", "kubeadm", "generic"]


@dataclass
class PlatformInfo:
    platform: Platform
    cluster_name: str | None = None
    context: str | None = None
    evidence: list[str] | None = None
    override: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _run(cmd: str) -> str:
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return str(exc)


def detect_platform(explicit: str | None = None) -> PlatformInfo:
    """Detect platform from env override, kubectl context, nodes, and provider IDs."""
    override = (explicit or os.environ.get("K8S_PLATFORM") or "").strip().lower()
    if override in {"kind", "kops", "eks", "gke", "aks", "kubeadm", "generic"}:
        return PlatformInfo(
            platform=override,  # type: ignore[arg-type]
            cluster_name=os.environ.get("CLUSTER_NAME")
            or os.environ.get("EKS_CLUSTER_NAME")
            or os.environ.get("KOPS_CLUSTER_NAME"),
            evidence=[f"override via K8S_PLATFORM/explicit={override}"],
            override=True,
        )

    evidence: list[str] = []
    context = _run("kubectl config current-context").strip().splitlines()
    ctx = context[0] if context else ""
    if ctx:
        evidence.append(f"context={ctx}")

    nodes = _run("kubectl get nodes -o json")
    provider_ids = ""
    labels = ""
    try:
        data = json.loads(nodes)
        for item in data.get("items", []):
            spec = item.get("spec", {})
            meta = item.get("metadata", {})
            provider_ids += " " + str(spec.get("providerID", ""))
            labels += " " + " ".join(f"{k}={v}" for k, v in (meta.get("labels") or {}).items())
    except json.JSONDecodeError:
        evidence.append("nodes json unavailable")

    # kind
    if "kind://" in provider_ids or re.search(r"\bkind-", ctx) or "kind.x-k8s.io" in labels:
        name = None
        m = re.search(r"kind-(.+)$", ctx)
        if m:
            name = m.group(1)
        name = os.environ.get("KIND_CLUSTER_NAME") or name or "kind"
        evidence.append("detected kind providerID/context")
        return PlatformInfo(platform="kind", cluster_name=name, context=ctx, evidence=evidence)

    # eks
    if (
        "aws:///" in provider_ids
        or "eks.amazonaws.com" in labels
        or "-eks-" in nodes
        or "eksctl" in ctx
        or os.environ.get("EKS_CLUSTER_NAME")
    ):
        evidence.append("detected AWS/EKS signals")
        return PlatformInfo(
            platform="eks",
            cluster_name=os.environ.get("EKS_CLUSTER_NAME") or os.environ.get("CLUSTER_NAME"),
            context=ctx,
            evidence=evidence,
        )

    # kops
    if (
        "kops.k8s.io" in labels
        or "kops" in ctx.lower()
        or os.environ.get("KOPS_CLUSTER_NAME")
        or "node-role.kubernetes.io/master" in labels
        and "kops" in nodes.lower()
    ):
        evidence.append("detected kops signals")
        return PlatformInfo(
            platform="kops",
            cluster_name=os.environ.get("KOPS_CLUSTER_NAME") or os.environ.get("CLUSTER_NAME"),
            context=ctx,
            evidence=evidence,
        )

    # gke
    if "gce://" in provider_ids or "cloud.google.com/gke" in labels or "gke_" in ctx:
        evidence.append("detected GKE signals")
        return PlatformInfo(
            platform="gke",
            cluster_name=os.environ.get("CLUSTER_NAME"),
            context=ctx,
            evidence=evidence,
        )

    # aks
    if "azure://" in provider_ids or "kubernetes.azure.com" in labels or "aks" in ctx.lower():
        evidence.append("detected AKS signals")
        return PlatformInfo(
            platform="aks",
            cluster_name=os.environ.get("CLUSTER_NAME"),
            context=ctx,
            evidence=evidence,
        )

    # kubeadm heuristic
    if "node-role.kubernetes.io/control-plane" in labels or "node-role.kubernetes.io/master" in labels:
        evidence.append("detected kubeadm/control-plane roles")
        return PlatformInfo(
            platform="kubeadm",
            cluster_name=os.environ.get("CLUSTER_NAME"),
            context=ctx,
            evidence=evidence,
        )

    evidence.append("fallback generic")
    return PlatformInfo(
        platform="generic",
        cluster_name=os.environ.get("CLUSTER_NAME"),
        context=ctx,
        evidence=evidence,
    )
