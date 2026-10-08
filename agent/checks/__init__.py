"""
agent/checks/__init__.py

Each check function is a pure async function with the signature:

    async def check_*(claim, ...) -> CheckResult

A CheckResult bundles the pass/fail outcome, a score contribution (0-100),
and a dict of evidence that is stored with the attestation for auditability.
"""

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    passed: bool
    score: int          # 0-100 contribution from this check
    evidence: dict = field(default_factory=dict)
    reason: str = ""    # Human-readable reason for failure
