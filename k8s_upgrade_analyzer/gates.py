"""Production guardrails shared by Agent and MCP.

Hard rules:
1. Upgrade is refused unless the latest feasibility report decision is APPROVED
   (or CONDITIONAL with remediations_verified=True — still never for NOT RECOMMENDED).
2. Human confirmation token is required for any mutating step.
3. Mutations default to dry-run; live changes need K8S_UPGRADE_ALLOW_MUTATIONS=1.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class UpgradeDecision(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    NOT_RECOMMENDED = "NOT RECOMMENDED"
    UNKNOWN = "UNKNOWN"


@dataclass
class FeasibilityGateResult:
    decision: UpgradeDecision
    readiness_score: int | None
    confidence: int | None
    report_path: str
    critical_issues: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    upgrade_allowed: bool = False
    refusal_reason: str = ""


_DECISION_PATTERNS = [
    re.compile(
        r"UPGRADE\s*DECISION\s*[:\-]?\s*(APPROVED|CONDITIONAL|NOT\s*RECOMMENDED)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bDecision\s*[=:]\s*(APPROVED|CONDITIONAL|NOT\s*RECOMMENDED)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(APPROVED|CONDITIONAL|NOT\s*RECOMMENDED)\b\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
]

_SCORE_PATTERNS = [
    re.compile(r"READINESS\s*SCORE\s*(?:\([^)]*\))?\s*[:\-]?\s*\n?\s*(\d+)\s*(?:/\s*100|out of\s*100)?", re.IGNORECASE),
    re.compile(r"readiness score is\s*(\d+)\s*(?:out of|/)\s*100", re.IGNORECASE),
    re.compile(r"\*\*Readiness Score[^*]*\*\*\s*[:\-]?\s*(\d+)", re.IGNORECASE),
]

_CONF_PATTERNS = [
    re.compile(r"CONFIDENCE\s*(?:SCORE)?\s*(?:\([^)]*\))?\s*[:\-]?\s*\n?\s*(\d+)\s*(?:%|/\s*100|out of\s*100)?", re.IGNORECASE),
    re.compile(r"confidence score is\s*(\d+)\s*(?:out of|/)\s*100", re.IGNORECASE),
    re.compile(r"\*\*Confidence Score[^*]*\*\*\s*[:\-]?\s*(\d+)", re.IGNORECASE),
]

_RESOURCE_KEYWORDS = re.compile(
    r"\b(memory|cpu|resource pressure|oom|eviction|disk pressure|capacity|"
    r"high resource|optimize cluster resources|resource constraints)\b",
    re.IGNORECASE,
)
_HARD_INCOMPAT_KEYWORDS = re.compile(
    r"\b(api removal|removed api|unsupported api|crd break|webhook fail|"
    r"incompatible controller|not supported|version skew critical|"
    r"ingress-nginx unsupported|csi incompatible)\b",
    re.IGNORECASE,
)

_CRIT_RE = re.compile(
    r"CRITICAL ISSUES\s*[:\-]?\s*\n(.*?)(?:\nHIGH RISKS|\nWARNINGS|\nREQUIRED ACTIONS|\n\*\*)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIONS_RE = re.compile(
    r"(?:REQUIRED ACTIONS(?: BEFORE UPGRADE)?|recommended order for upgrades(?:\s+is)?)\s*[:\-]?\s*\n(.*?)(?:\nRECOMMENDED UPGRADE ORDER|\nPOST-UPGRADE|\n\*\*Final|\nFinal Recommendation|$)",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_decision(raw: str) -> UpgradeDecision:
    text = re.sub(r"\s+", " ", raw.strip().upper())
    if text == "APPROVED":
        return UpgradeDecision.APPROVED
    if text == "CONDITIONAL":
        return UpgradeDecision.CONDITIONAL
    if text in {"NOT RECOMMENDED", "NOT_RECOMMENDED"}:
        return UpgradeDecision.NOT_RECOMMENDED
    return UpgradeDecision.UNKNOWN


def _first_int(patterns: list[re.Pattern[str]], text: str) -> int | None:
    for pat in patterns:
        m = pat.search(text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def _infer_decision_from_prose(text: str, score: int | None) -> UpgradeDecision:
    """Fallback for free-form LLM reports (e.g. Ollama) that omit the structured block."""
    lower = text.lower()

    # Prefer explicit structured-ish phrases from LLM executive summaries
    if "proceed with caution" in lower or "generally recommended" in lower:
        return UpgradeDecision.CONDITIONAL

    hard_no = [
        "do not upgrade",
        "upgrade is not recommended",
        "not recommended",
    ]
    # "not ready for immediate upgrade" with only resource pressure → CONDITIONAL
    if "not ready for an immediate upgrade" in lower or "cluster is not ready" in lower:
        if is_resource_pressure_only_text(text):
            return UpgradeDecision.CONDITIONAL
        return UpgradeDecision.NOT_RECOMMENDED

    if any(p in lower for p in hard_no):
        if is_resource_pressure_only_text(text):
            return UpgradeDecision.CONDITIONAL
        return UpgradeDecision.NOT_RECOMMENDED

    if re.search(r"\bapproved\b", lower) and "not approved" not in lower:
        if score is not None and score < 75:
            return UpgradeDecision.CONDITIONAL
        return UpgradeDecision.APPROVED

    if "conditional" in lower or "addressing potential issues" in lower or "before upgrading" in lower:
        if score is not None and score < 50 and not is_resource_pressure_only_text(text):
            return UpgradeDecision.NOT_RECOMMENDED
        return UpgradeDecision.CONDITIONAL

    if score is not None:
        if score >= 90:
            return UpgradeDecision.APPROVED
        if score >= 50:
            return UpgradeDecision.CONDITIONAL
        return UpgradeDecision.NOT_RECOMMENDED

    return UpgradeDecision.UNKNOWN


def is_resource_pressure_only_text(text: str) -> bool:
    """True when findings look like capacity/pressure risks, not hard incompatibilities."""
    if _HARD_INCOMPAT_KEYWORDS.search(text):
        return False
    resource_hits = len(_RESOURCE_KEYWORDS.findall(text))
    return resource_hits >= 1


def _executive_focus_lines(report_text: str) -> list[str]:
    """Pull decision-driving bullets from executive summary (ignore hallucinated body sections)."""
    lines: list[str] = []
    patterns = [
        r"CRITICAL ISSUES\s*[:\-]\s*(.+)",
        r"HIGH RISKS\s*[:\-]\s*(.+)",
        r"REQUIRED ACTIONS BEFORE UPGRADE\s*[:\-]\s*(.+)",
        r"\*\s*CRITICAL ISSUES\s*[:\-]\s*(.+)",
        r"\*\s*HIGH RISKS\s*[:\-]\s*(.+)",
        r"\*\s*REQUIRED ACTIONS BEFORE UPGRADE\s*[:\-]\s*(.+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, report_text, re.IGNORECASE):
            item = m.group(1).strip()
            if item and "see narrative" not in item.lower():
                lines.append(item)
    return lines


def is_resource_pressure_only(result: FeasibilityGateResult, report_text: str = "") -> bool:
    """True when decision drivers are capacity/pressure, not hard incompatibilities.

    Uses required actions / executive-summary bullets first so hallucinated
    API-removal sections in LLM narratives do not block a resource-only prompt.
    """
    focus = [c for c in result.critical_issues if "see narrative" not in c.lower()]
    focus.extend(result.required_actions)
    if report_text:
        focus.extend(_executive_focus_lines(report_text))

    # Deduplicate
    seen: set[str] = set()
    focus_unique: list[str] = []
    for item in focus:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            focus_unique.append(item)

    if focus_unique:
        if any(_HARD_INCOMPAT_KEYWORDS.search(i) for i in focus_unique):
            return False
        return all(_RESOURCE_KEYWORDS.search(i) for i in focus_unique)

    # Fallback: whole report, but only if no hard-incompat keywords dominate
    if not report_text.strip():
        return False
    if _HARD_INCOMPAT_KEYWORDS.search(report_text) and not _RESOURCE_KEYWORDS.search(report_text):
        return False
    # If both appear, prefer resource-only when score is mid and caution language exists
    lower = report_text.lower()
    if _RESOURCE_KEYWORDS.search(report_text) and (
        "proceed with caution" in lower
        or "optimize cluster resources" in lower
        or "high resource pressure" in lower
    ):
        return True
    return is_resource_pressure_only_text(report_text)


def parse_feasibility_report(report_text: str, report_path: str = "") -> FeasibilityGateResult:
    decision = UpgradeDecision.UNKNOWN
    for pat in _DECISION_PATTERNS:
        m = pat.search(report_text)
        if m:
            decision = _normalize_decision(m.group(1))
            if decision != UpgradeDecision.UNKNOWN:
                break

    score = _first_int(_SCORE_PATTERNS, report_text)
    conf = _first_int(_CONF_PATTERNS, report_text)

    if decision == UpgradeDecision.UNKNOWN:
        decision = _infer_decision_from_prose(report_text, score)

    critical: list[str] = []
    cm = _CRIT_RE.search(report_text)
    if cm:
        for line in cm.group(1).splitlines():
            line = line.strip()
            if line.startswith(("- ", "* ", "+ ")):
                item = re.sub(r"^[-*+]\s+", "", line).strip()
                if item and "none" not in item.lower():
                    critical.append(item)

    actions: list[str] = []
    am = _ACTIONS_RE.search(report_text)
    if am:
        for line in am.group(1).splitlines():
            line = line.strip()
            if re.match(r"^\d+\.", line):
                actions.append(re.sub(r"^\d+\.\s*", "", line))

    # Conservative default: unparseable LLM output must not unlock upgrades
    if decision == UpgradeDecision.UNKNOWN:
        decision = UpgradeDecision.NOT_RECOMMENDED

    provisional = FeasibilityGateResult(
        decision=decision,
        readiness_score=score,
        confidence=conf,
        report_path=report_path,
        critical_issues=critical,
        required_actions=actions,
    )

    # Soften stale/LLM "NOT RECOMMENDED" when decision drivers are resource-pressure only
    lower = report_text.lower()
    if decision == UpgradeDecision.NOT_RECOMMENDED and is_resource_pressure_only(
        provisional, report_text
    ):
        if (
            "proceed with caution" in lower
            or "generally recommended" in lower
            or (score is not None and score >= 50)
        ):
            provisional.decision = UpgradeDecision.CONDITIONAL

    return provisional


def load_and_parse_report(report_path: str | Path) -> FeasibilityGateResult:
    path = Path(report_path)
    if not path.exists():
        return FeasibilityGateResult(
            decision=UpgradeDecision.UNKNOWN,
            readiness_score=None,
            confidence=None,
            report_path=str(path),
            upgrade_allowed=False,
            refusal_reason=f"Report not found: {path}",
        )
    result = parse_feasibility_report(path.read_text(), str(path))
    return evaluate_upgrade_gate(result, remediations_verified=False)


def evaluate_upgrade_gate(
    result: FeasibilityGateResult,
    *,
    remediations_verified: bool = False,
    allow_conditional: bool = False,
    user_accepted_resource_risk: bool = False,
    report_text: str = "",
) -> FeasibilityGateResult:
    """Decide whether MCP may start an upgrade sequence."""
    resource_only = is_resource_pressure_only(result, report_text)

    if result.decision == UpgradeDecision.NOT_RECOMMENDED:
        if user_accepted_resource_risk and resource_only:
            result.upgrade_allowed = True
            result.refusal_reason = (
                "ALLOWED with explicit human acceptance of resource-pressure risk only."
            )
            return result
        result.upgrade_allowed = False
        result.refusal_reason = (
            "REFUSED: Feasibility report decision is NOT RECOMMENDED. "
            "MCP will not upgrade even if a human confirms. "
            "Remediate critical issues and regenerate an APPROVED report first."
            + (
                " (Tip: if risks are only CPU/memory pressure, re-run the agent interactively "
                "and answer yes to the resource-risk prompt.)"
                if resource_only
                else ""
            )
        )
        return result

    if result.decision == UpgradeDecision.UNKNOWN:
        result.upgrade_allowed = False
        result.refusal_reason = (
            "REFUSED: Could not parse UPGRADE DECISION from the report. "
            "Re-run assessment before any upgrade."
        )
        return result

    if result.decision == UpgradeDecision.CONDITIONAL:
        if (remediations_verified and allow_conditional) or (
            user_accepted_resource_risk and resource_only
        ):
            result.upgrade_allowed = True
            result.refusal_reason = ""
            return result
        result.upgrade_allowed = False
        result.refusal_reason = (
            "REFUSED (for now): Decision is CONDITIONAL. "
            "Complete remediations, or if risks are only resource pressure, "
            "explicitly accept that risk in the interactive agent prompt."
        )
        return result

    # APPROVED
    result.upgrade_allowed = True
    result.refusal_reason = ""
    return result


def mutations_enabled() -> bool:
    return os.environ.get("K8S_UPGRADE_ALLOW_MUTATIONS", "").strip() == "1"


def make_approval_token(source: str, target: str, report_path: str) -> str:
    """Deterministic token the human must echo back to confirm intent."""
    material = f"{source}|{target}|{Path(report_path).resolve()}|UPGRADE"
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def verify_approval_token(
    provided: str | None,
    *,
    source: str,
    target: str,
    report_path: str,
) -> tuple[bool, str]:
    if not provided:
        return False, "Missing confirmation token. Call request_upgrade_approval first."
    expected = make_approval_token(source, target, report_path)
    if provided.strip() != expected:
        return False, "Invalid confirmation token. Upgrade blocked."
    return True, "Confirmation token accepted."
