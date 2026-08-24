from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    PASS = "PASS"
    GOOD = "GOOD"
    WARNING = "WARNING"
    HIGH_RISK = "HIGH RISK"
    CRITICAL = "CRITICAL"


class UpgradeDecision(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    NOT_RECOMMENDED = "NOT RECOMMENDED"


class AreaAssessment(BaseModel):
    area: str
    status: RiskLevel
    severity: str
    explanation: str


class FailureScenario(BaseModel):
    question: str
    answer: bool
    reason: str


class ClusterSnapshot(BaseModel):
    """Raw data collected from the cluster before analysis (read-only kubectl)."""

    kubectl_version: str = ""
    cluster_info: str = ""
    nodes: str = ""
    namespaces: str = ""
    api_resources: str = ""
    api_services: str = ""
    all_resources: str = ""
    deployments: str = ""
    statefulsets: str = ""
    daemonsets: str = ""
    jobs: str = ""
    cronjobs: str = ""
    crds_list: str = ""
    crds_yaml: str = ""
    crds_summary: str = ""
    validating_webhooks: str = ""
    mutating_webhooks: str = ""
    webhook_policies: str = ""
    nodes_yaml: str = ""
    top_nodes: str = ""
    top_pods: str = ""
    storage_classes: str = ""
    csi_drivers: str = ""
    persistent_volumes: str = ""
    persistent_volume_claims: str = ""
    ingresses: str = ""
    network_policies: str = ""
    workload_images: str = ""
    kube_system_workloads: str = ""
    errors: list[str] = Field(default_factory=list)


class AssessmentRequest(BaseModel):
    source_version: str
    target_version: str
    cluster_snapshot: ClusterSnapshot
    kubeconfig: Optional[str] = None


class AssessmentReport(BaseModel):
    source_version: str
    target_version: str
    decision: UpgradeDecision
    readiness_score: int
    confidence_score: int
    critical_issues: list[str] = Field(default_factory=list)
    high_risks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    upgrade_order: list[str] = Field(default_factory=list)
    post_upgrade_validations: list[str] = Field(default_factory=list)
    risk_matrix: list[AreaAssessment] = Field(default_factory=list)
    failure_scenarios: list[FailureScenario] = Field(default_factory=list)
    raw_analysis: str = ""
    final_recommendation: str = ""
