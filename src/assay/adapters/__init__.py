"""Adapters translate one ecosystem into the probe protocol."""

__all__ = ["InspectAdapter", "HarborAdapter"]


def __getattr__(name: str):
    if name == "InspectAdapter":
        from .inspect_ai_adapter import InspectAdapter

        return InspectAdapter
    if name == "HarborAdapter":
        from .harbor import HarborAdapter

        return HarborAdapter
    raise AttributeError(name)
