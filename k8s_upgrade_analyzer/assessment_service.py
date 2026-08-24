"""Shared assessment entrypoint used by CLI, Agent, and MCP tools."""

from __future__ import annotations

from pathlib import Path

from k8s_upgrade_analyzer import analyzer, claude, collector, gpt, ollama, reporter
from k8s_upgrade_analyzer.gates import FeasibilityGateResult, load_and_parse_report
from k8s_upgrade_analyzer.models import ClusterSnapshot

_AI_MODES = frozenset({"ollama", "claude", "gpt", "openai"})


def require_ai_mode(mode: str) -> str:
    """Only AI backends are allowed. Local/rule-only mode is rejected."""
    m = (mode or "").strip().lower()
    if m in {"local", "rules", "offline", ""}:
        raise ValueError(
            "No model found. Please connect to a model first.\n"
            "Use one of:\n"
            "  --mode ollama --model llama3.1:8b\n"
            "  --mode claude --model claude-sonnet-4-6\n"
            "  --mode gpt --model gpt-4o-mini\n"
            "(Set OLLAMA_HOST / ANTHROPIC_API_KEY / OPENAI_API_KEY as needed.)"
        )
    if m == "openai":
        m = "gpt"
    if m not in _AI_MODES:
        raise ValueError(
            f"Unsupported mode '{mode}'. Supported AI modes: ollama, claude, gpt.\n"
            "No model found. Please connect to a model first."
        )
    return m


def run_assessment(
    *,
    source: str,
    target: str,
    mode: str = "ollama",
    kubeconfig: str | None = None,
    from_snapshot: str | None = None,
    snapshot_out: str = "snapshots/latest-snapshot.json",
    output_dir: str = "reports",
    api_key: str | None = None,
    model: str | None = None,
    stream: bool = False,
) -> tuple[Path, FeasibilityGateResult, ClusterSnapshot | None]:
    mode = require_ai_mode(mode)
    snapshot: ClusterSnapshot | None = None

    if from_snapshot:
        snapshot = collector.load_snapshot(from_snapshot)
    else:
        snapshot = collector.collect(kubeconfig=kubeconfig)
        collector.save_snapshot(snapshot, snapshot_out)

    if mode == "ollama":
        if not model and not __import__("os").environ.get("OLLAMA_MODEL"):
            # still ok — ollama client has a default, but require explicit model for clarity
            pass
        raw = ollama.analyze(
            source_version=source,
            target_version=target,
            snapshot=snapshot,
            model=model,
            stream=stream,
        )
    elif mode == "claude":
        evidence = analyzer.analyze_local(source, target, snapshot, compact=True)
        try:
            narrative = claude.analyze(
                source_version=source,
                target_version=target,
                snapshot=snapshot,
                api_key=api_key,
                model=model,
                stream=stream,
            )
            raw = (
                evidence.rstrip()
                + "\n\n## Claude notes (non-authoritative)\n\n"
                + narrative.strip()
                + "\n"
            )
        except Exception as exc:
            raise RuntimeError(
                f"Claude model not connected: {exc}\n"
                "Set ANTHROPIC_API_KEY and pass --mode claude --model <model>."
            ) from exc
    elif mode == "gpt":
        raw = gpt.analyze(
            source_version=source,
            target_version=target,
            snapshot=snapshot,
            model=model,
            api_key=api_key,
            stream=stream,
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    report_path = reporter.save(
        raw_analysis=raw,
        source_version=source,
        target_version=target,
        output_dir=output_dir,
        mode=mode,
    )
    gate = load_and_parse_report(report_path)
    return report_path, gate, snapshot


def report_path_for(source: str, target: str, output_dir: str = "reports") -> Path:
    from k8s_upgrade_analyzer.reporter.report_generator import _version_slug

    slug = f"{_version_slug(source)}_to_{_version_slug(target)}"
    return Path(output_dir) / f"cluster-upgrade-feasibility-and-risks_{slug}.md"
