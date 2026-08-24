# Kubernetes Upgrade Feasibility, Compatibility, and Risk Assessment

## Objective

You are acting as a Senior Kubernetes Platform Engineer performing a comprehensive upgrade readiness review.

Your task is to determine whether a Kubernetes cluster can be safely upgraded from:

```text
SOURCE_VERSION={source_version}
TARGET_VERSION={target_version}
```

The analysis must be exhaustive, evidence-based, and conservative.

Your primary goal is to identify:

* Anything that can break during or after the upgrade
* Unsupported APIs
* Controller incompatibilities
* CRD incompatibilities
* Admission webhook risks
* Operator risks
* Runtime risks
* Networking risks
* Storage risks
* Security enforcement changes
* Workload restart risks
* Node upgrade risks
* Control plane risks

Do not assume compatibility unless verified.

If compatibility cannot be confirmed, classify it as a risk.

---

# Assessment Requirements

The assessment must combine:

1. Kubernetes release note analysis
2. Cluster state analysis
3. CRD analysis
4. Controller/operator analysis
5. API compatibility analysis
6. Add-on compatibility analysis
7. Runtime analysis
8. Upgrade simulation
9. Failure scenario modeling

---

# Step 1 - Cluster Information

```
{kubectl_version}
```

```
{cluster_info}
```

Nodes:
```
{nodes}
```

Namespaces:
```
{namespaces}
```

API Resources:
```
{api_resources}
```

API Services:
```
{api_services}
```

---

# Step 2 - Resource Inventory

All Resources:
```
{all_resources}
```

Deployments:
```
{deployments}
```

StatefulSets:
```
{statefulsets}
```

DaemonSets:
```
{daemonsets}
```

Jobs:
```
{jobs}
```

CronJobs:
```
{cronjobs}
```

---

# Step 3 - CRDs

CRD List:
```
{crds_list}
```

CRD Detail (YAML / summary):
```
{crds_yaml}
```

---

# Step 4 - Webhooks

Validating Webhooks:
```
{validating_webhooks}
```

Mutating Webhooks:
```
{mutating_webhooks}
```

---

# Step 5 - Node Detail

```
{nodes_yaml}
```

---

# Step 6 - Resource Pressure

Node metrics:
```
{top_nodes}
```

Pod metrics:
```
{top_pods}
```

---

# Collection Errors

The following commands returned errors during data collection (these gaps reduce confidence):
```
{collection_errors}
```

---

# Required Output Format

Produce a full assessment covering:

1. **Kubernetes Release Note Analysis** — review all intermediate versions ({source_version} → {target_version})
2. **API Removal Analysis** — list every removed API found in the cluster with CRITICAL classification
3. **Deprecated API Analysis** — list every deprecated API in use
4. **CRD Compatibility Analysis** — per CRD: will it break? YES/NO + reason
5. **Controller and Operator Compatibility** — per controller: version, supported k8s range, status (PASS/GOOD/WARNING/HIGH RISK/CRITICAL), upgrade timing
6. **Admission Webhook Analysis** — can webhooks fail or block after upgrade?
7. **Networking Compatibility Analysis** — can networking break?
8. **Storage Compatibility Analysis** — can storage become inaccessible?
9. **Security Compatibility Analysis** — can security changes break workloads?
10. **Runtime Compatibility Analysis** — CRI and OS support
11. **Resource Pressure Analysis** — OOMKill/eviction risks during upgrade
12. **Upgrade Simulation** — per area: Control Plane / Nodes / APIs / CRDs / Controllers / Networking / Storage / Security
13. **Failure Scenario Analysis** — answer every question below
14. **Risk Matrix** — table with area, status, severity, explanation
15. **Readiness Score** (0–100) and **Confidence Score** (0–100%)
16. **Executive Summary** with UPGRADE DECISION, CRITICAL ISSUES, HIGH RISKS, WARNINGS, REQUIRED ACTIONS BEFORE UPGRADE, RECOMMENDED UPGRADE ORDER, POST-UPGRADE VALIDATIONS, and FINAL RECOMMENDATION

## Failure Scenarios (answer YES/NO + reason for each)

- Could workloads fail to start?
- Could controllers crash?
- Could CRDs become unreadable?
- Could CRD controllers stop reconciling?
- Could admission webhooks block deployments?
- Could storage become inaccessible?
- Could networking break?
- Could node upgrades fail?
- Could kubelets fail to register?
- Could the control plane fail?

## Mandatory Rule

For every incompatibility found, state:

```
WHAT WILL BREAK:
WHEN IT WILL BREAK: (Control Plane Upgrade / Node Upgrade / Immediately After Upgrade / First Reconciliation / First Deployment)
IMPACT: (Outage / Partial Outage / Reconciliation Failure / Deployment Failure / Data Risk)
SEVERITY: (Critical / High / Medium / Low)
REMEDIATION:
```

Always separate: Verified Issues / Probable Issues / Possible Issues / Unknown Risks.

Unknown risks must reduce the final confidence score.
