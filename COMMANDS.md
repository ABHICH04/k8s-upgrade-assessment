# Demo Commands — AGNTCon / MCPCon Japan

One-page runbook for the talk: **assess → gate → remediate → (optional) dry-run upgrade → verify**.

Default safety: **no live cluster mutation** unless you explicitly enable it.

---

## 0) One-time setup

```bash
cd k8s-upgrade-assessment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# Always keep mutations off during demos unless you intend to change a cluster
export K8S_UPGRADE_ALLOW_MUTATIONS=0
```

Optional Claude assessment later:

```bash
cp .env.example .env
# edit .env → set ANTHROPIC_API_KEY
```

---

## Talk flow (what the audience should see)

```text
1. Agent generates ONE short feasibility report
2. Asks yes/no to upgrade
3. No  → save report, exit
4. Yes → dry-run plan (default) OR live upgrade with --execute-upgrade
5. Verify health
```

No confirmation tokens. No second assessment loop.

---

## Demo A — Staging EKS (your current cluster)

### A1. Point kubectl

```bash
kubectl config use-context latest-staging-eks-cluster
kubectl get nodes -o wide
kubectl version
```

### A2. Run the Agent (finishes; does not stay running)

```bash
source .venv/bin/activate
export K8S_UPGRADE_ALLOW_MUTATIONS=0

k8s-upgrade-agent --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b
```

**What happens**
- AI assessment (ollama/claude/gpt required — `--mode ollama --model llama3.1:8b` is rejected)
- Writes ONE short report
- Prompts **yes/no** for upgrade
- Answer **no** → saves report and exits
- Answer **yes** + `--execute-upgrade` → in-place upgrade, then verifies nodes and prints **UPGRADED SUCCESSFULLY** if healthy

### A3. Show the report decision (talk slide / terminal)

```bash
rg -n "UPGRADE DECISION|READINESS SCORE|CRITICAL ISSUES|REQUIRED ACTIONS" \
  reports/cluster-upgrade-feasibility-and-risks_1_30_to_1_31.md | head -40
```

### A4. Assessment-only (if you don't want the full agent loop)

```bash
k8s-upgrade-analyzer --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b
```

### A5. Show hard gate: human says yes, MCP still refuses

```bash
python - <<'PY'
from k8s_upgrade_analyzer.upgrade import run_upgrade, make_approval_token
from k8s_upgrade_analyzer.gates import make_approval_token as tok
path = "reports/cluster-upgrade-feasibility-and-risks_1_30_to_1_31.md"
# even with a token, NOT RECOMMENDED must refuse
from k8s_upgrade_analyzer.gates import make_approval_token
token = make_approval_token("1.30", "1.31", path)
r = run_upgrade(
    source="1.30",
    target="1.31",
    report_path=path,
    confirmation_token=token,
    dry_run=True,
)
print("allowed:", r.allowed)
print("platform:", r.platform)
print(r.message)
PY
```

Expected: `allowed: False` + `NOT RECOMMENDED` refusal message.

### A6. Show remediation plan from report

```bash
python - <<'PY'
from k8s_upgrade_analyzer.remediate import build_remediation_plan, execute_remediation_plan, save_plan
plan = build_remediation_plan(
    "reports/cluster-upgrade-feasibility-and-risks_1_30_to_1_31.md",
    "1.30",
    "1.31",
)
plan = execute_remediation_plan(plan, dry_run=True)
save_plan(plan, "plans/remediation_1_30_to_1_31.json")
print(plan.summary)
for s in plan.steps[:8]:
    print(f"- [{s.category}] {s.title}")
PY

less plans/remediation_1_30_to_1_31.json
```

### A7. MCP server for Cursor demo (long-running)

In a **separate terminal** (or rely on `.cursor/mcp.json`):

```bash
source .venv/bin/activate
export K8S_UPGRADE_ALLOW_MUTATIONS=0
python -m mcp_server.server
```

**What this does**
- Starts MCP stdio server and **keeps running**
- Does **not** upgrade anything by itself
- Waits for Cursor / an MCP client to call tools

In Cursor chat (with MCP connected), ask:

```text
Use k8s-upgrade MCP tools:
1) get_feasibility_report source=1.30 target=1.31
2) request_upgrade_approval source=1.30 target=1.31
3) upgrade_cluster with any token, dry_run=true
Show that it refuses because NOT RECOMMENDED.
```

Stop MCP with `Ctrl+C` when done.

---

## Demo B — kind cluster (safe laptop demo)

### B1. Create kind cluster (example)

```bash
kind create cluster --name upgrade-demo --image kindest/node:v1.30.0
kubectl config use-context kind-upgrade-demo
kubectl get nodes
```

### B2. Force platform = kind (optional; usually auto-detected)

```bash
export K8S_PLATFORM=kind
export KIND_CLUSTER_NAME=upgrade-demo
export CLUSTER_NAME=upgrade-demo
export K8S_UPGRADE_ALLOW_MUTATIONS=0
```

### B3. Assess once → yes/no (AI model required)

```bash
source .venv/bin/activate
ollama serve
ollama pull llama3.1:8b

# Live in-place kind upgrade (keeps pods/PVCs). Answer yes at the prompt.
k8s-upgrade-agent --source 1.30 --target 1.32 \
  --mode ollama --model llama3.1:8b --execute-upgrade
```

`--mode ollama --model llama3.1:8b` is **not supported** (error: connect a model first).  
Also supported: `--mode claude --model …` / `--mode gpt --model …`.

Report path:

```text
reports/cluster-upgrade-feasibility-and-risks_1_30_to_1_31.md
```

### B4. Non-interactive yes (CI / scripting)

```bash
k8s-upgrade-agent --source 1.30 --target 1.32 \
  --mode ollama --model llama3.1:8b --execute-upgrade --yes
```

Check upgrade result:

```bash
cat plans/upgrade_1_30_to_1_32.json
kubectl get nodes
```

### B5. Live kind upgrade (ONLY if you really want to mutate the demo cluster)

```bash
export K8S_UPGRADE_ALLOW_MUTATIONS=1
# Still prefer dry-run first, then execute carefully.
# kind upgrade in this project is often delete+recreate — data loss expected.
```

Cleanup:

```bash
kind delete cluster --name upgrade-demo
```

---

## Demo C — kops cluster

```bash
export K8S_PLATFORM=kops
export KOPS_CLUSTER_NAME=my.example.com
export KOPS_STATE_STORE=s3://my-kops-state
export CLUSTER_NAME=my.example.com
export K8S_UPGRADE_ALLOW_MUTATIONS=0

kubectl config use-context <your-kops-context>
k8s-upgrade-agent --source 1.28 --target 1.29 --mode ollama --model llama3.1:8b
```

Upgrade plan will contain `kops edit/update/rolling-update/validate` (dry-run by default).

---

## Command cheat sheet

| Command | Keeps running? | Upgrades cluster? | When to use |
| --- | --- | --- | --- |
| `k8s-upgrade-analyzer --source X --target Y --mode ollama --model llama3.1:8b` | No | No | Report only |
| `k8s-upgrade-agent --source X --target Y --mode ollama --model llama3.1:8b` | No | No (default) | Full agent loop + gates |
| `python -m mcp_server.server` | **Yes** | No by itself | Expose MCP tools to Cursor |
| MCP tool `upgrade_cluster(..., dry_run=true)` | n/a | No | Show planned commands |
| MCP tool `upgrade_cluster(..., dry_run=false)` + `K8S_UPGRADE_ALLOW_MUTATIONS=1` + valid token + APPROVED report | n/a | **Yes (dangerous)** | Only after talk guardrails are clear |

---

## Recommended 5-minute live demo script

1. `kubectl config current-context` → show staging/kind  
2. `k8s-upgrade-agent --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b`  
3. Open report → highlight `UPGRADE DECISION: NOT RECOMMENDED`  
4. Run hard-gate Python snippet → `allowed: False`  
5. Show `plans/remediation_*.json` → “agent planned fixes first”  
6. Start MCP / call from Cursor → same refuse behavior  
7. Closing line: *“We let the agent plan; we do not let it ignore the feasibility report.”*

---

## Safety checklist before any live upgrade

- [ ] You read the one short report
- [ ] You answered **yes** intentionally at the prompt
- [ ] You have backups (kind = full data loss on recreate)
- [ ] You know the platform (`kind` / `kops` / `eks` / …)
- [ ] Prefer dry-run (no `--execute-upgrade`) once before live

---

## Live upgrade on local kind (simple)

> Default kind path is **in-place kubeadm** (preserves etcd/workloads).  
> Only `KIND_UPGRADE_MODE=recreate` deletes the cluster (data loss).

### 0) Prerequisites

```bash
kind create cluster --name upgrade-demo --image kindest/node:v1.30.0
kubectl config use-context kind-upgrade-demo

cd k8s-upgrade-assessment
source .venv/bin/activate
pip install -e .
```

### 1) One report → yes/no → upgrade

```bash
export CLUSTER_NAME=upgrade-demo

# Recommended (short, evidence-based):
k8s-upgrade-agent --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b --execute-upgrade
# answer yes

# Or Ollama narrative (still one report + yes/no):
# ollama serve && ollama pull llama3.2
k8s-upgrade-agent --source 1.30 --target 1.31 --mode ollama --model llama3.2 --execute-upgrade
```

Dry-run only (no cluster change):

```bash
k8s-upgrade-agent --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b
# answer yes → writes plans/upgrade_*.json with kind commands, does not delete cluster
```

### 2) What live kind upgrade runs (default in-place)

```bash
bash scripts/kind_inplace_upgrade.sh upgrade-demo 1.31.0
kubectl get nodes -o wide
```

### Recreate fallback (DATA LOSS)

```bash
export KIND_UPGRADE_MODE=recreate
# or manually:
kind delete cluster --name upgrade-demo
kind create cluster --name upgrade-demo --image kindest/node:v1.31.0
```
