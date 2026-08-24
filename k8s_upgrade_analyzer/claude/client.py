import os
from pathlib import Path

import anthropic

from k8s_upgrade_analyzer.models import ClusterSnapshot

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "system_prompt.md"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 16000


def _truncate(value: str, limit: int = 80_000) -> str:
    if not value:
        return "(not available)"
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n\n...[truncated {len(value) - limit} chars]..."


def _load_prompt(
    source_version: str,
    target_version: str,
    snapshot: ClusterSnapshot,
) -> str:
    template = _PROMPT_PATH.read_text()
    # Prefer compact CRD summary over full YAML for the model context window
    crd_detail = snapshot.crds_summary or snapshot.crds_yaml
    return template.format(
        source_version=source_version,
        target_version=target_version,
        kubectl_version=_truncate(snapshot.kubectl_version, 8_000),
        cluster_info=_truncate(snapshot.cluster_info, 8_000),
        nodes=_truncate(snapshot.nodes, 20_000),
        namespaces=_truncate(snapshot.namespaces, 8_000),
        api_resources=_truncate(snapshot.api_resources, 40_000),
        api_services=_truncate(snapshot.api_services, 20_000),
        all_resources=_truncate(snapshot.all_resources, 60_000),
        deployments=_truncate(snapshot.deployments, 40_000),
        statefulsets=_truncate(snapshot.statefulsets, 20_000),
        daemonsets=_truncate(snapshot.daemonsets, 20_000),
        jobs=_truncate(snapshot.jobs, 10_000),
        cronjobs=_truncate(snapshot.cronjobs, 10_000),
        crds_list=_truncate(snapshot.crds_list, 40_000),
        crds_yaml=_truncate(crd_detail, 80_000),
        validating_webhooks=_truncate(snapshot.validating_webhooks, 40_000),
        mutating_webhooks=_truncate(snapshot.mutating_webhooks, 40_000),
        nodes_yaml=_truncate(snapshot.nodes_yaml, 40_000),
        top_nodes=_truncate(snapshot.top_nodes, 10_000),
        top_pods=_truncate(snapshot.top_pods, 20_000),
        collection_errors="\n".join(snapshot.errors) if snapshot.errors else "None",
    )


def analyze(
    source_version: str,
    target_version: str,
    snapshot: ClusterSnapshot,
    api_key: str | None = None,
    model: str | None = None,
    stream: bool = True,
) -> str:
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. "
            "Set it in your environment, pass --api-key, or use --mode local."
        )

    model = model or os.environ.get("CLAUDE_MODEL", _DEFAULT_MODEL)
    prompt = _load_prompt(source_version, target_version, snapshot)
    client = anthropic.Anthropic(api_key=api_key)

    if stream:
        full_text = ""
        with client.messages.stream(
            model=model,
            max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        ) as s:
            for text in s.text_stream:
                print(text, end="", flush=True)
                full_text += text
        print()
        return full_text

    message = client.messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
