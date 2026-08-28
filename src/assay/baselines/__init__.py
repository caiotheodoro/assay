from .structural import StructuralCheckArm  # noqa: F401

__all__ = ["StructuralCheckArm", "DirectPromptArm", "ToolAgentArm"]


def __getattr__(name: str):
    if name in {"DirectPromptArm", "ToolAgentArm"}:
        from . import llm

        return getattr(llm, name)
    raise AttributeError(name)
