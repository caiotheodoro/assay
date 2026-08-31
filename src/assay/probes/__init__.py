"""Probe registry. Importing this module registers every family."""

from .base import (  # noqa: F401
    FAMILIES_NOT_PLANTED_IN_FIXTURES,
    REGISTRY,
    Probe,
    all_probes,
    families,
    register,
)
from . import verifier  # noqa: F401,E402
from . import policies  # noqa: F401,E402
from . import contamination  # noqa: F401,E402
from . import shortcut  # noqa: F401,E402
from . import specmatch  # noqa: F401,E402
from . import determinism  # noqa: F401,E402
from . import hackability  # noqa: F401,E402
from . import permissions  # noqa: F401,E402
from . import evaluator  # noqa: F401,E402

__all__ = [
    "FAMILIES_NOT_PLANTED_IN_FIXTURES",
    "REGISTRY",
    "Probe",
    "all_probes",
    "families",
    "register",
]
