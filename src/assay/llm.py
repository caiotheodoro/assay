"""Minimal model clients.

Deliberately dependency-free and small. Assay's scoring never calls a model --
every oracle is a program -- so the only thing that needs one is the prompted
Challenger, which proposes attacks that are then judged by deterministic code.
A weak or unavailable model therefore degrades the Challenger, never the
verdict.

Ollama is the default because it runs locally with no API key, which keeps the
reproduction path intact: `ollama pull qwen3:1.7b` and the whole comparison
reruns offline.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class LLMUnavailable(RuntimeError):
    """No model backend is reachable. Callers degrade; they do not guess."""


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


@dataclass
class OllamaClient:
    """Local model over Ollama's HTTP API."""

    model: str = "qwen3:1.7b"
    host: str = "http://localhost:11434"
    temperature: float = 0.8
    timeout: int = 180

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as resp:
                tags = json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return False
        return any(m.get("name") == self.model for m in tags.get("models", []))

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": user,
                "system": system,
                "stream": False,
                "options": {"temperature": self.temperature},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read()).get("response", "")
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(f"{self.name}: {exc}") from exc


@dataclass
class ClaudeCLIClient:
    """Headless Claude Code, for when a stronger model is wanted.

    Not the default: it needs the CLI installed and authenticated, which the
    reproduction guide cannot assume.
    """

    model: str = "sonnet"
    timeout: int = 240

    @property
    def name(self) -> str:
        return f"claude-cli:{self.model}"

    def available(self) -> bool:
        try:
            return (
                subprocess.run(
                    ["claude", "--version"], capture_output=True, timeout=15
                ).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError):
            return False

    def complete(self, system: str, user: str) -> str:
        try:
            proc = subprocess.run(
                ["claude", "-p", "--model", self.model, "--append-system-prompt", system],
                input=user,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise LLMUnavailable(f"{self.name}: {exc}") from exc
        if proc.returncode != 0:
            raise LLMUnavailable(f"{self.name}: exit {proc.returncode}: {proc.stderr[:200]}")
        return proc.stdout


def default_client() -> LLMClient:
    """First backend that is actually reachable, or raise."""
    for client in (OllamaClient("qwen3:8b"), OllamaClient("qwen3:1.7b"), ClaudeCLIClient()):
        if client.available():
            return client
    raise LLMUnavailable(
        "no model backend reachable; try `ollama pull qwen3:1.7b` or install the claude CLI"
    )
