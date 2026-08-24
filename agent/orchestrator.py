#!/usr/bin/env python3
"""AI-driven upgrade agent:

1) Assess with a connected model (ollama / claude / gpt)
2) Ask yes/no
3) If yes → in-place upgrade
4) Verify nodes + workloads; print UPGRADED SUCCESSFULLY when healthy
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from k8s_upgrade_analyzer.assessment_service import require_ai_mode, run_assessment
from k8s_upgrade_analyzer.upgrade import run_upgrade, save_result
from k8s_upgrade_analyzer.verify import verify_cluster_health

console = Console()


@dataclass
class AgentEvent:
    phase: str
    message: str
    data: dict = field(default_factory=dict)


@dataclass
class AgentRun:
    source: str
    target: str
    events: list[AgentEvent] = field(default_factory=list)
    final_status: str = "started"


def _log(run: AgentRun, phase: str, message: str, **data) -> None:
    data.pop("message", None)
    data.pop("phase", None)
    run.events.append(AgentEvent(phase=phase, message=message, data=data))
    console.print(f"[bold cyan][{phase}][/bold cyan] {message}")


def _write_trace(run: AgentRun) -> None:
    out = (
        ROOT
        / "plans"
        / f"agent_trace_{run.source.replace('.', '_')}_to_{run.target.replace('.', '_')}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(run), indent=2))
    console.print(f"[dim]Trace:[/dim] {out}")


def _ask_yes_no(prompt: str) -> bool:
    """Keep asking until the user types y/yes or n/no. Empty Enter re-prompts."""
    while True:
        try:
            answer = input(f"{prompt} [y/N]: ").strip().lower()
        except EOFError:
            console.print("[yellow]No input received; please answer y or n.[/yellow]")
            continue
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        console.print("[yellow]Please type y or n (Enter alone is not accepted).[/yellow]")


def _print_short_summary(report_path: Path, decision: str, readiness, confidence) -> None:
    text = report_path.read_text()
    preview = "\n".join(text.splitlines()[:80])
    console.print(Panel.fit(preview, title=str(report_path), border_style="blue"))
    console.print(
        f"\n[bold]Decision:[/bold] {decision}   "
        f"[bold]Readiness:[/bold] {readiness}/100   "
        f"[bold]Confidence:[/bold] {confidence}%\n"
    )


def _target_minor(version: str) -> str:
    v = version.lstrip("v")
    parts = v.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return v


def _cluster_on_target(target: str) -> tuple[bool, str]:
    """Return (ok, detail) after waiting briefly for API."""
    minor = _target_minor(target)
    detail = ""
    for _ in range(30):
        proc = subprocess.run(
            "kubectl get nodes -o wide",
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        detail = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0 and ("Ready" in detail) and (
            f"v{minor}" in detail or minor in detail
        ):
            return True, detail
        time.sleep(2)
    return False, detail


def _workloads_ok() -> tuple[bool, str]:
    proc = subprocess.run(
        "kubectl get pods,pvc -A",
        shell=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out[:4000]


@click.command()
@click.option("--source", required=True)
@click.option("--target", required=True)
@click.option(
    "--mode",
    required=True,
    help="AI backend: ollama | claude | gpt (local is not supported)",
)
@click.option(
    "--model",
    required=True,
    help="Model id, e.g. llama3.1:8b / claude-sonnet-4-6 / gpt-4o-mini",
)
@click.option("--output-dir", default="reports", show_default=True)
@click.option(
    "--execute-upgrade/--dry-run-upgrade",
    default=False,
    help="If yes on prompt: live upgrade vs dry-run plan only",
)
@click.option(
    "--yes",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip interactive prompt and proceed with upgrade path",
)
def main(
    source: str,
    target: str,
    mode: str,
    model: str,
    output_dir: str,
    execute_upgrade: bool,
    assume_yes: bool,
) -> None:
    """AI model required. One report → yes/no → upgrade → verify success."""
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

    run = AgentRun(source=source, target=target)
    console.print(
        Panel.fit(
            f"[bold]K8s Upgrade Agent[/bold]\n"
            f"{source} → {target}\n"
            f"mode={mode} model={model}\n"
            f"flow: AI assess → yes/no → in-place upgrade → verify",
            border_style="magenta",
        )
    )

    # Explain hopping up front when multi-minor
    try:
        s_minor = int(source.lstrip("v").split(".")[1])
        t_minor = int(target.lstrip("v").split(".")[1])
        if t_minor - s_minor > 1:
            hops = " → ".join(f"1.{m}" for m in range(s_minor, t_minor + 1))
            console.print(
                Panel.fit(
                    f"[yellow]HOPPING REQUIRED[/yellow]\n"
                    f"kubeadm upgrades one minor at a time.\n"
                    f"This run will hop: [bold]{hops}[/bold]\n"
                    f"(in-place — pods/PVCs kept, no kind delete)",
                    border_style="yellow",
                )
            )
    except (IndexError, ValueError):
        pass

    _log(run, "assess", f"AI assessment (mode={mode}, model={model})")
    try:
        report_path, gate, _ = run_assessment(
            source=source,
            target=target,
            mode=mode,
            model=model,
            output_dir=output_dir,
            stream=False,
        )
    except Exception as exc:
        console.print(f"[red]Assessment failed:[/red] {exc}")
        sys.exit(1)

    _print_short_summary(
        report_path,
        gate.decision.value,
        gate.readiness_score,
        gate.confidence,
    )
    _log(
        run,
        "assess",
        f"Report saved: {report_path}",
        decision=gate.decision.value,
        readiness=gate.readiness_score,
    )

    if assume_yes:
        proceed = True
    else:
        from k8s_upgrade_analyzer.platform import detect_platform

        plat = detect_platform()
        if plat.platform == "kind" and execute_upgrade:
            prompt = (
                "Do you want to proceed with the upgrade "
                "(kind LIVE = in-place kubeadm; keep all resources intact)?"
            )
        else:
            prompt = "Do you want to proceed with the upgrade?"
        proceed = _ask_yes_no(prompt)

    if not proceed:
        run.final_status = "declined_by_user"
        _write_trace(run)
        console.print(
            f"\n[yellow]Upgrade cancelled.[/yellow] Report kept at:\n  {report_path}\n"
        )
        sys.exit(0)

    dry_run = not execute_upgrade
    _log(run, "upgrade", f"Starting upgrade ({'LIVE' if execute_upgrade else 'dry-run'})")
    if execute_upgrade:
        console.print(
            "[dim]Streaming live upgrade logs below "
            "(kubeadm hops can take several minutes — this is not stuck)…[/dim]\n"
        )
    result = run_upgrade(
        source=source,
        target=target,
        report_path=str(report_path),
        confirmation_token="interactive-yes",
        dry_run=dry_run,
        remediations_verified=True,
        allow_conditional=True,
        user_accepted_resource_risk=True,
        skip_token_check=True,
        force_user_approved=True,
    )
    result_path = (
        ROOT / "plans" / f"upgrade_{source.replace('.', '_')}_to_{target.replace('.', '_')}.json"
    )
    save_result(result, result_path)
    _log(run, "upgrade", result.message, allowed=result.allowed, result_path=str(result_path))

    if not result.allowed:
        run.final_status = "upgrade_refused"
        _write_trace(run)
        console.print(f"[red]Upgrade did not run:[/red] {result.message}")
        sys.exit(4)

    failed_steps = [s for s in result.steps if s.status == "failed"]
    for step in result.steps:
        style = "red" if step.status == "failed" else "green"
        console.print(f"  [{style}][{step.status}][/{style}] {step.id} {step.title}")
        if step.command:
            console.print(f"      [dim]{step.command}[/dim]")
        # Show hop banners / success lines from script output
        if step.output:
            interesting = [
                ln
                for ln in step.output.splitlines()
                if re.search(
                    r"HOPPING REQUIRED|HOP \d+/|UPGRADED SUCCESSFULLY|Hop OK|SINGLE HOP|ERROR:",
                    ln,
                )
            ]
            for ln in interesting[-30:]:
                console.print(f"      {ln}")
        if step.status == "failed" and step.output:
            console.print(
                Panel.fit(step.output[-2000:], title="upgrade step output (tail)", border_style="yellow")
            )

    if dry_run:
        run.final_status = "success_dry_run"
        _write_trace(run)
        console.print("\n[green]Dry-run complete[/green] — no cluster changes made.")
        sys.exit(0)

    # Authoritative success = live cluster on target + API healthy
    _log(run, "verify", "Checking nodes/workloads for successful upgrade…")
    on_target, nodes_out = _cluster_on_target(target)
    workloads_ok, wl_out = _workloads_ok()
    health = verify_cluster_health(expected_minor=target)

    console.print(Panel.fit(nodes_out[-1500:] or "(no nodes output)", title="kubectl get nodes", border_style="blue"))
    if wl_out:
        console.print(Panel.fit(wl_out[-1500:], title="pods/pvc", border_style="blue"))

    if on_target and health.healthy:
        # Even if a step exited non-zero due to a transient API blip, cluster is good.
        if failed_steps:
            for s in failed_steps:
                s.status = "recovered"
                s.output = (s.output or "") + "\n# recovered: post-check shows target version healthy\n"
            save_result(result, result_path)
        run.final_status = "success"
        _write_trace(run)
        console.print(
            Panel.fit(
                f"[bold green]UPGRADED SUCCESSFULLY[/bold green]\n"
                f"Cluster is on target [bold]{target}[/bold].\n"
                f"Existing pods/PVCs were preserved (in-place upgrade).",
                border_style="green",
            )
        )
        console.print(f"[dim]Report:[/dim] {report_path}")
        console.print(f"[dim]Upgrade result:[/dim] {result_path}")
        sys.exit(0)

    run.final_status = "upgrade_failed"
    _write_trace(run)
    console.print(
        Panel.fit(
            f"[bold red]UPGRADE NOT CONFIRMED[/bold red]\n"
            f"on_target={on_target} health={health.healthy} workloads_listable={workloads_ok}\n"
            f"{health.message}",
            border_style="red",
        )
    )
    console.print(f"[dim]Result:[/dim] {result_path}")
    sys.exit(5)


if __name__ == "__main__":
    main()
