"""What a results row has to record about the run that produced it.

`hf-publication-specs.md` 11.2: every results row records temperature, top_p,
max_tokens, samples per task and aggregation rule, prompt version, thinking
mode, eval date, and model revision -- emitted by the harness rather than
written by hand.

`results/challenger_ablation.json` recorded none of them, and the README's
found/missed claims come from those runs. So a reader could not tell whether
the `qwen3:8b` arm missed because the model is weak or because it was sampled
at a temperature that made it repeat itself, which is exactly the ambiguity the
requirement exists to remove.

Two rules this module holds to, both of which cost something:

**A field that cannot be obtained is `None` WITH a reason, never omitted and
never guessed.** `claude -p` exposes no sampling controls and no model snapshot
date, so those come back null with the reason attached. A run config that
quietly drops the fields a backend will not tell it is worse than no run config:
it looks complete.

**The prompt version is a digest of the actual prompt text, not a hand-kept
number.** Hand-kept version numbers go stale the first time someone edits a
string without remembering to bump them, and a stale prompt version is worse
than none because it asserts two different runs were comparable.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[2]


def digest_text(*parts: str) -> str:
    """Stable content digest. Short because it identifies, it does not secure."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def unavailable(reason: str) -> dict[str, Any]:
    """The shape every absent field takes: null, plus why."""
    return {"value": None, "unavailable": reason}


def eval_date() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_revision() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(_REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return unavailable(f"git not usable: {exc}")
    if proc.returncode != 0:
        return unavailable(f"git rev-parse failed: {proc.stderr.strip()[:120]}")
    sha = proc.stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(_REPO), "status", "--porcelain"],
        capture_output=True, text=True, timeout=30,
    ).stdout.strip()
    return {"commit": sha, "dirty": bool(dirty)}


def ollama_model_revision(model: str, host: str) -> dict[str, Any]:
    """Ollama's own digest for the pulled weights.

    A tag is not a revision: `qwen3:8b` moves when upstream repushes it, and two
    runs a month apart under the same tag are not the same model. The digest is
    the only thing here that pins the weights.
    """
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=30) as resp:
            tags = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return unavailable(f"ollama tags unreachable at {host}: {exc}")
    for entry in tags.get("models", []):
        if entry.get("name") == model:
            details = entry.get("details", {})
            return {
                "digest": entry.get("digest"),
                "modified_at": entry.get("modified_at"),
                "size_bytes": entry.get("size"),
                "parameter_size": details.get("parameter_size"),
                "quantization_level": details.get("quantization_level"),
                "family": details.get("family"),
            }
    return unavailable(f"model {model!r} is not in the local ollama tag list")


def claude_cli_revision() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return unavailable(f"claude CLI not usable: {exc}")
    if proc.returncode != 0:
        return unavailable("claude --version returned nonzero")
    return {
        "cli_version": proc.stdout.strip(),
        "model_snapshot": None,
        "model_snapshot_unavailable": (
            "`claude -p` takes a model ALIAS and reports no snapshot date, so the "
            "exact weights behind 'sonnet' on this run cannot be recovered from the "
            "CLI. Two runs of this arm weeks apart are not guaranteed to be the "
            "same model, and nothing here can tell you whether they were."
        ),
    }


def client_config(client: Any) -> dict[str, Any]:
    """Sampling configuration of one model backend, as far as it will say."""
    name = getattr(client, "name", type(client).__name__)
    kind = type(client).__name__
    if kind == "OllamaClient":
        return {
            "client": name,
            "backend": "ollama",
            "model_tag": client.model,
            "model_revision": ollama_model_revision(client.model, client.host),
            "temperature": client.temperature,
            "top_p": unavailable(
                "OllamaClient does not send top_p, so the server's own default "
                "applies and the client cannot report which value that was"
            ),
            "top_k": unavailable("not sent by OllamaClient; server default applies"),
            "max_tokens": client.num_predict,
            "thinking_mode": bool(client.think),
            "request_timeout_s": client.timeout,
        }
    if kind == "ClaudeCLIClient":
        no_control = (
            "`claude -p` exposes no sampling controls, so this run used whatever "
            "the CLI defaults to and the value is not observable from here"
        )
        return {
            "client": name,
            "backend": "claude-cli",
            "model_tag": client.model,
            "model_revision": claude_cli_revision(),
            "temperature": unavailable(no_control),
            "top_p": unavailable(no_control),
            "top_k": unavailable(no_control),
            "max_tokens": unavailable(no_control),
            "thinking_mode": unavailable(
                "not selectable through `claude -p`; the CLI decides"
            ),
            "request_timeout_s": client.timeout,
        }
    return {
        "client": name,
        "backend": kind,
        "unavailable": (
            f"no run-config extractor for {kind}; add one rather than letting this "
            "arm publish a row with no configuration"
        ),
    }


def prompt_version(*sources: str) -> dict[str, str]:
    """Digest the prompt text itself, so the version cannot go stale."""
    return {"digest": digest_text(*sources), "n_sources": str(len(sources))}


@dataclass
class RunConfig:
    """One results row's provenance. Serialise it next to the numbers."""

    harness: str
    task: str
    samples_per_task: int
    aggregation: str
    arms: dict[str, dict[str, Any]] = field(default_factory=dict)
    prompt: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec": "hf-publication-specs.md 11.2",
            "harness": self.harness,
            "task": self.task,
            "eval_date": eval_date(),
            "samples_per_task": self.samples_per_task,
            "aggregation_rule": self.aggregation,
            "prompt_version": self.prompt,
            "assay_revision": git_revision(),
            "arms": self.arms,
            **self.extra,
            "absent_fields_policy": (
                "Every field a backend will not report is null WITH a reason rather "
                "than omitted. A run config that silently drops what it could not "
                "obtain reads as complete and is not."
            ),
        }


def docker_image_revision(image: str) -> dict[str, Any]:
    """The image DIGEST, not just its tag.

    `alpine:3.20` is a moving target; the sandbox a Harbor run executed in is
    pinned by digest or it is not pinned at all. Two ablations months apart
    under the same tag can differ in shell, coreutils and permissions -- all
    things an attacker's exploits are made of.
    """
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return unavailable(f"docker not usable: {exc}")
    if proc.returncode != 0:
        return unavailable(
            f"docker image inspect {image} failed: {proc.stderr.strip()[:120]}"
        )
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return unavailable(f"docker returned unparseable JSON: {exc}")
    return {
        "tag": image,
        "id": info.get("Id"),
        "repo_digests": info.get("RepoDigests") or [],
        "created": info.get("Created"),
        "architecture": info.get("Architecture"),
        "os": info.get("Os"),
    }
