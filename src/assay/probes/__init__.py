"""Probe registry. Importing this module registers every family."""

from .base import REGISTRY, Probe, all_probes, families, register  # noqa: F401
from . import verifier  # noqa: F401,E402
from . import policies  # noqa: F401,E402
from . import contamination  # noqa: F401,E402
from . import shortcut  # noqa: F401,E402
from . import specmatch  # noqa: F401,E402
from . import determinism  # noqa: F401,E402
from . import hackability  # noqa: F401,E402

__all__ = ["REGISTRY", "Probe", "all_probes", "families", "register"]
