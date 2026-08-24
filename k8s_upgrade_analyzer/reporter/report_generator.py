import re
from datetime import datetime, timezone
from pathlib import Path


def _version_slug(version: str) -> str:
    """Turn a user version string into a safe filename fragment.

    Examples:
      1.30      -> 1_30
      1.20.3    -> 1_20_3
      v1.31     -> 1_31
    """
    cleaned = version.strip().lstrip("vV")
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", cleaned)
    return cleaned.strip("_")


def save(
    raw_analysis: str,
    source_version: str,
    target_version: str,
    output_dir: str = "reports",
    mode: str = "local",
) -> Path:
    """Write one report named from the CLI --source / --target values."""
    slug = f"{_version_slug(source_version)}_to_{_version_slug(target_version)}"
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    report_path = out / f"cluster-upgrade-feasibility-and-risks_{slug}.md"
    header = (
        f"<!-- generated_at={datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"mode={mode} source={source_version} target={target_version} -->\n"
    )
    report_path.write_text(header + raw_analysis)
    return report_path
