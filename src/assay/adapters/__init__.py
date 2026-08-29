"""Adapters translate one ecosystem into the probe protocol."""

__all__ = ["InspectAdapter", "HarborAdapter", "OpenEnvAdapter"]


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
    raise AttributeError(name)
