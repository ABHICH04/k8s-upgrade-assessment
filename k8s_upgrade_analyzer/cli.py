import sys

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

console = Console()


@click.command()
@click.option("--source", required=True, help="Current Kubernetes version, e.g. 1.30")
@click.option("--target", required=True, help="Target Kubernetes version, e.g. 1.31")
@click.option(
    "--kubeconfig",
    default=None,
    envvar="KUBECONFIG",
    help="Path to kubeconfig (defaults to KUBECONFIG env or ~/.kube/config)",
)
@click.option(
    "--mode",
    required=True,
    help="AI backend: ollama | claude | gpt (local is not supported)",
)
@click.option(
    "--model",
    required=True,
    help="Model id (e.g. llama3.1:8b, claude-sonnet-4-6, gpt-4o-mini)",
)
@click.option(
    "--api-key",
    default=None,
    help="API key for claude/gpt (or ANTHROPIC_API_KEY / OPENAI_API_KEY)",
)
@click.option(
    "--output-dir",
    default="reports",
    show_default=True,
    help="Directory to save the assessment report",
)
@click.option(
    "--snapshot-out",
    default="snapshots/latest-snapshot.json",
    show_default=True,
    help="Where to save the collected cluster snapshot JSON",
)
@click.option(
    "--from-snapshot",
    default=None,
    help="Skip kubectl and analyze an existing snapshot JSON instead",
)
@click.option(
    "--no-stream",
    is_flag=True,
    default=False,
    help="Disable streaming model output",
)
def main(
    source: str,
    target: str,
    kubeconfig: str | None,
    mode: str,
    model: str,
    api_key: str | None,
    output_dir: str,
    snapshot_out: str,
    from_snapshot: str | None,
    no_stream: bool,
) -> None:
    """Kubernetes upgrade feasibility assessment (AI model required)."""
    from k8s_upgrade_analyzer.assessment_service import require_ai_mode, run_assessment

    try:
        mode = require_ai_mode(mode)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(2)

    if not model or not str(model).strip():
        console.print(
            "[red]No model found. Please connect to a model first.[/red]\n"
            "Example: --mode ollama --model llama3.1:8b"
        )
        sys.exit(2)

    console.print(
        Panel.fit(
            f"[bold]K8s Upgrade Analyzer[/bold]\n"
            f"[dim]{source}[/dim] → [green]{target}[/green]\n"
            f"mode=[cyan]{mode}[/cyan] model=[cyan]{model}[/cyan]",
            border_style="blue",
        )
    )

    try:
        report_path, gate, _ = run_assessment(
            source=source,
            target=target,
            mode=mode,
            model=model,
            api_key=api_key,
            kubeconfig=kubeconfig,
            from_snapshot=from_snapshot,
            snapshot_out=snapshot_out,
            output_dir=output_dir,
            stream=not no_stream,
        )
    except Exception as exc:
        console.print(f"[red]Assessment failed:[/red] {exc}")
        sys.exit(1)

    console.print(
        f"\n[bold]Decision:[/bold] {gate.decision.value}  "
        f"readiness={gate.readiness_score} confidence={gate.confidence}"
    )
    console.print(f"[green]Report saved:[/green] {report_path}")


if __name__ == "__main__":
    main()
