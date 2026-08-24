"""OpenAI / GPT assessment — evidence-first, same contract as Ollama."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from k8s_upgrade_analyzer.gates import parse_feasibility_report
from k8s_upgrade_analyzer.models import ClusterSnapshot
from k8s_upgrade_analyzer.ollama.client import _load_prompt, _strip_decision_blocks

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_BASE = "https://api.openai.com/v1"


def analyze(
    source_version: str,
    target_version: str,
    snapshot: ClusterSnapshot,
    model: str | None = None,
    api_key: str | None = None,
    stream: bool = False,
) -> str:
    from k8s_upgrade_analyzer import analyzer

    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No model connected for GPT. Set OPENAI_API_KEY (and optionally OPENAI_MODEL)."
        )

    model = model or os.environ.get("OPENAI_MODEL") or _DEFAULT_MODEL
    base = (os.environ.get("OPENAI_BASE_URL") or _DEFAULT_BASE).rstrip("/")

    evidence = analyzer.analyze_local(
        source_version, target_version, snapshot, compact=True
    )
    evidence_gate = parse_feasibility_report(evidence, "")
    prompt = _load_prompt(source_version, target_version, snapshot, evidence)

    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You explain a Kubernetes upgrade evidence report. "
                    "Keep the same UPGRADE DECISION as the evidence. Be short and concrete."
                ),
            },
            {
                "role": "user",
                "content": (
                    prompt
                    + f"\n\nIMPORTANT: Evidence decision is {evidence_gate.decision.value}. "
                    "Your decision MUST match exactly."
                ),
            },
        ],
    }

    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        llm = (
            ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        )
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GPT/OpenAI request failed: {exc}") from exc

    llm_gate = parse_feasibility_report(llm, "")
    notes = _strip_decision_blocks(llm) or "(model produced no extra notes)"
    if llm_gate.decision != evidence_gate.decision:
        return (
            evidence.rstrip()
            + "\n\n---\n\n## AI notes (rejected — contradicted evidence decision)\n\n"
            + f"Evidence: **{evidence_gate.decision.value}**. Model: **{llm_gate.decision.value}**.\n\n"
            + notes
            + "\n"
        )
    return evidence.rstrip() + "\n\n---\n\n## AI notes (non-authoritative)\n\n" + notes + "\n"
