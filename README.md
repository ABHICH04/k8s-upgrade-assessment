# K8s Upgrade Agent + MCP

Agentic planner → executor → verifier loop, with an MCP server that performs **gated** remediation and upgrade. Built for talks like AGNTCon / MCPCon: feasibility first, human approval, refuse unsafe upgrades.

```text
┌──────────────────────────── AGENT ────────────────────────────┐
│  planner → assess → remediate plan → human gate → upgrade     │
│                         → verify → rollback recommendation      │
└─────────────────────────────┬─────────────────────────────────┘
                              │ calls tools
┌─────────────────────────────▼ MCP SERVER ─────────────────────┐
│ assess_upgrade_feasibility                                     │
│ get_feasibility_report                                         │
│ request_upgrade_approval                                       │
│ remediate_from_report     (APIs / CRDs / controllers / CSI)    │
│ upgrade_cluster           (HARD-GATED by report decision)      │
│ verify_cluster_health                                          │
└───────────────────────────────────────────────────────────────┘
```

## Who does what?

| Layer | Responsibility |
| --- | --- |
| **AGENT** (`agent/orchestrator.py`) | Plans the loop, runs assessment, asks for human confirmation, decides next step, stops on NOT RECOMMENDED |
| **MCP** (`mcp_server/server.py`) | Exposes tools. **Enforces hard gates** so upgrade cannot run when the report says not feasible |
| **Analyzer** (`k8s_upgrade_analyzer/`) | Collects cluster inventory + writes feasibility report |

### Hard gate (talk demo moment)

## Safety defaults

- Assessment collection is read-only `kubectl get|version|top|api-resources|cluster-info`
- Agent flow: **one short report → yes/no → upgrade** (no tokens, no re-assess loop)
- Default is dry-run; live needs `--execute-upgrade` + answering **yes**
- kind live upgrade = in-place kubeadm by default (set `KIND_UPGRADE_MODE=recreate` only if you accept wipe)
- Set `EKS_CLUSTER_NAME` / `CLUSTER_NAME` before platform-specific upgrades

## Install

```bash
cd k8s-upgrade-assessment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
kubectl config use-context latest-staging-eks-cluster
```

## 1) Feasibility report (Agent or CLI)

```bash
# CLI (assessment only)
k8s-upgrade-analyzer --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b
# -> reports/cluster-upgrade-feasibility-and-risks_1_30_to_1_31.md

# Agent: one report → yes/no → dry-run upgrade plan
k8s-upgrade-agent --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b

# Live (kind = recreate / DATA LOSS). Answer yes at the prompt.
k8s-upgrade-agent --source 1.30 --target 1.31 --mode ollama --model llama3.1:8b --execute-upgrade
```

## 2) MCP server (Cursor / any MCP client)

Config is in `.cursor/mcp.json`. Or run manually:

```bash
python -m mcp_server.server
```

Prefer the CLI agent for demos. MCP still exposes assess / upgrade / verify tools.

## Outputs

| Path | Description |
| --- | --- |
| `reports/cluster-upgrade-feasibility-and-risks_<src>_to_<tgt>.md` | Feasibility report |
| `plans/remediation_*.json` | Remediation plan from report |
| `plans/upgrade_*.json` | Upgrade dry-run / execution result |
| `plans/agent_trace_*.json` | Agent loop trace for the talk |

## Optional Claude assessment

```bash
cp .env.example .env   # set ANTHROPIC_API_KEY
k8s-upgrade-analyzer --source 1.30 --target 1.31 --mode claude
```

`--mode ollama --model llama3.1:8b` uses **no AI** (Python rules). Claude is only used when you ask for it.

## Project layout

```
agent/                      # AGENTIC loop
mcp_server/                 # MCP tools (guardrailed executor)
k8s_upgrade_analyzer/
  collector/                # read-only inventory
  analyzer/                 # feasibility report
  gates.py                  # APPROVED / CONDITIONAL / NOT RECOMMENDED enforcement
  remediate.py              # fix plan from report
  upgrade.py                # gated upgrade
  verify.py                 # health checks
prompts/system_prompt.md
reports/
plans/
```
