"""Adapters translate one ecosystem into the probe protocol."""

__all__ = ["InspectAdapter"]


def __getattr__(name: str):
    if name == "InspectAdapter":
        from .inspect_ai_adapter import InspectAdapter

        return InspectAdapter
    raise AttributeError(name)
