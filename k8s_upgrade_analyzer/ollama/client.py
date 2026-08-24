"""Local Ollama assessment — evidence is authoritative; model may only add notes."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from k8s_upgrade_analyzer.claude.client import _truncate
from k8s_upgrade_analyzer.gates import parse_feasibility_report
from k8s_upgrade_analyzer.models import ClusterSnapshot

_DEFAULT_HOST = "http://127.0.0.1:11434"
_DEFAULT_MODEL = "llama3.1:8b"
_PROMPT = Path(__file__).parent.parent.parent / "prompts" / "ollama_assessment_prompt.md"


def _chat(
    *,
    host: str,
    model: str,
    system: str,
    user: str,
    stream: bool = False,
    num_predict: int = 900,
) -> str:
    url = f"{host}/api/chat"
    payload = {
        "model": model,
        "stream": bool(stream),
        "options": {"temperature": 0.0, "num_predict": num_predict},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            if not stream:
                body = json.loads(resp.read().decode("utf-8"))
                return (body.get("message") or {}).get("content", "") or ""

            full: list[str] = []
            for raw_line in resp:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                chunk = json.loads(line)
                content = (chunk.get("message") or {}).get("content") or ""
                if content:
                    print(content, end="", flush=True)
                    full.append(content)
                if chunk.get("done"):
                    break
            print()
            return "".join(full)
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach Ollama at {host}. Is `ollama serve` running?\n"
            f"  ollama pull {model}\n"
            f"Underlying error: {exc}"
        ) from exc


def _load_prompt(
    source_version: str,
    target_version: str,
    snapshot: ClusterSnapshot,
    evidence_report: str,
) -> str:
    template = _PROMPT.read_text()
    return template.format(
        source_version=source_version,
        target_version=target_version,
        evidence_report=_truncate(evidence_report, 12_000),
        kubectl_version=_truncate(snapshot.kubectl_version, 4_000),
        nodes=_truncate(snapshot.nodes, 8_000),
        namespaces=_truncate(snapshot.namespaces, 4_000),
        crds_list=_truncate(snapshot.crds_list, 8_000),
        deployments=_truncate(snapshot.deployments, 12_000),
        validating_webhooks=_truncate(snapshot.validating_webhooks, 8_000),
        mutating_webhooks=_truncate(snapshot.mutating_webhooks, 8_000),
        top_nodes=_truncate(snapshot.top_nodes, 4_000),
        workload_images=_truncate(
            "\n".join(
                filter(
                    None,
                    [
                        snapshot.workload_images,
                        snapshot.kube_system_workloads,
                        snapshot.daemonsets,
                    ],
                )
            ),
            12_000,
        ),
    )


def _strip_decision_blocks(text: str) -> str:
    """Remove structured decision/score blocks so gates cannot parse LLM first."""
    cleaned = re.sub(
        r"(?im)^(?:#{1,3}\s*)?UPGRADE DECISION:.*?(?=^(?:#{1,3}\s*)?(?:SUMMARY|CHECKS|RISKS|REQUIRED|FINAL|---)|\Z)",
        "",
        text,
        flags=re.S,
    )
    for key in (
        "SOURCE VERSION",
        "TARGET VERSION",
        "READINESS SCORE",
        "CONFIDENCE",
    ):
        cleaned = re.sub(rf"(?im)^(?:#+\s*)?{key}:\s*.*\n?", "", cleaned)
    return cleaned.strip()


def analyze(
    source_version: str,
    target_version: str,
    snapshot: ClusterSnapshot,
    model: str | None = None,
    host: str | None = None,
    stream: bool = False,
) -> str:
    """Evidence report is authoritative. Ollama adds notes only (cannot override decision)."""
    from k8s_upgrade_analyzer import analyzer

    host = (host or os.environ.get("OLLAMA_HOST") or _DEFAULT_HOST).rstrip("/")
    model = model or os.environ.get("OLLAMA_MODEL") or _DEFAULT_MODEL

    evidence = analyzer.analyze_local(
        source_version,
        target_version,
        snapshot,
        compact=True,
    )
    evidence_gate = parse_feasibility_report(evidence, "")

    prompt = _load_prompt(source_version, target_version, snapshot, evidence)
    try:
        llm = _chat(
            host=host,
            model=model,
            stream=stream,
            system=(
                "You explain a Kubernetes upgrade evidence report. "
                "You MUST keep the same UPGRADE DECISION as the evidence report. "
                "If evidence says NOT RECOMMENDED (e.g. skipping minor versions), you must not say APPROVED. "
                "Never invent resources. Be concrete and short."
            ),
            user=prompt
            + f"\n\nIMPORTANT: Evidence decision is {evidence_gate.decision.value}. "
            "Your decision MUST match exactly.",
        )
    except RuntimeError as exc:
        return (
            evidence.rstrip()
            + f"\n\n_Note: Ollama failed ({exc}); evidence-only report above is authoritative._\n"
        )

    llm_gate = parse_feasibility_report(llm, "")
    notes = _strip_decision_blocks(llm)
    if not notes:
        notes = "(model produced no extra notes)"

    # Always lead with evidence so Decision/readiness come from the rule engine.
    if llm_gate.decision != evidence_gate.decision:
        return (
            evidence.rstrip()
            + "\n\n---\n\n## AI notes (rejected — contradicted evidence decision)\n\n"
            + f"Evidence decision: **{evidence_gate.decision.value}**. "
            + f"Model said: **{llm_gate.decision.value}** (ignored).\n\n"
            + notes
            + "\n"
        )

    return (
        evidence.rstrip()
        + "\n\n---\n\n## AI notes (non-authoritative)\n\n"
        + notes
        + "\n"
    )
