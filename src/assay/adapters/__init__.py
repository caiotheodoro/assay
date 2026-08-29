"""Adapters translate one ecosystem into the probe protocol."""

__all__ = ["InspectAdapter", "HarborAdapter", "OpenEnvAdapter", "SpecAdapter"]


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
    raise AttributeError(name)
