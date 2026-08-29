"""Adapters translate one ecosystem into the probe protocol."""

__all__ = ["InspectAdapter", "HarborAdapter", "OpenEnvAdapter", "SpecAdapter", "Tau2Adapter"]


def __getattr__(name: str):
    if name == "InspectAdapter":
        from .inspect_ai_adapter import InspectAdapter

        return InspectAdapter
    if name == "HarborAdapter":
        from .harbor import HarborAdapter

        return HarborAdapter
    if name == "OpenEnvAdapter":
        from .openenv import OpenEnvAdapter

        return OpenEnvAdapter
    if name == "SpecAdapter":
        from .spec import SpecAdapter

        return SpecAdapter
    if name == "Tau2Adapter":
        # Imported lazily like the rest, and for one extra reason: tau2 lives in
        # a gitignored cache rather than site-packages, so importing it eagerly
        # would make `import assay` fail on a clone that has not fetched it.
        from .tau2 import Tau2Adapter

        return Tau2Adapter
    raise AttributeError(name)
