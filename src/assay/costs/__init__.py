"""Cost profiles: what it costs to miss a defect, and to cry wolf.

Severity is a property of the defect. Cost is a property of the caller. Keeping
them apart is what lets the same audit be read by a researcher burning one run
and by someone publishing a benchmark others will cite for years.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..types import Severity

PROFILE_DIR = Path(__file__).parent / "profiles"


@dataclass(frozen=True)
class CostProfile:
    name: str
    description: str
    miss: dict[Severity, float]
    false_alarm: float

    def cost_of_miss(self, severity: Severity) -> float:
        return self.miss[severity]


def load(name: str) -> CostProfile:
    path = PROFILE_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no cost profile named {name!r} in {PROFILE_DIR}")
    raw = yaml.safe_load(path.read_text())
    return CostProfile(
        name=raw["name"],
        description=raw["description"].strip(),
        miss={Severity(k): float(v) for k, v in raw["miss"].items()},
        false_alarm=float(raw["false_alarm"]),
    )


def available() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))


def all_profiles() -> dict[str, CostProfile]:
    return {name: load(name) for name in available()}
