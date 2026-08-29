"""Run-configuration capture, per hf-publication-specs.md 11.2.

The requirement is not "record what you can". It is that every results row
carries the fields, and the failure mode this guards against is a config that
looks complete because the fields a backend would not report were dropped
instead of nulled.
"""

from __future__ import annotations

import json

import pytest

from assay.llm import ClaudeCLIClient, OllamaClient
from assay.runconfig import (
    RunConfig,
    client_config,
    digest_text,
    prompt_version,
    unavailable,
)

#: 11.2's list. `top_p` and `max_tokens` are here even though one backend will
#: not report them -- that is the point of the null-with-reason rule.
REQUIRED_11_2 = {
    "temperature",
    "top_p",
    "max_tokens",
    "thinking_mode",
    "model_revision",
}


def test_unavailable_is_a_null_with_a_reason():
    field = unavailable("the backend does not expose it")
    assert field["value"] is None
    assert field["unavailable"]


def test_ollama_config_carries_every_11_2_field():
    cfg = client_config(OllamaClient("qwen3:8b"))
    assert REQUIRED_11_2 <= set(cfg)
    assert cfg["backend"] == "ollama"
    assert cfg["temperature"] == 0.8
    assert cfg["max_tokens"] == 400
    assert cfg["thinking_mode"] is False


def test_ollama_reports_top_p_as_absent_rather_than_inventing_one():
    """`OllamaClient` never sends top_p, so the server default applied and the
    client cannot know what it was. Writing 1.0 here would be a guess presented
    as a measurement."""
    cfg = client_config(OllamaClient("qwen3:8b"))
    assert cfg["top_p"]["value"] is None
    assert "does not send top_p" in cfg["top_p"]["unavailable"]


def test_claude_cli_reports_all_sampling_fields_as_absent():
    """`claude -p` exposes no sampling controls. Every one of them has to come
    back null with a reason -- not omitted, which would read as 'not
    applicable', and not defaulted, which would read as 'measured'."""
    cfg = client_config(ClaudeCLIClient())
    assert REQUIRED_11_2 <= set(cfg)
    for name in ("temperature", "top_p", "max_tokens", "thinking_mode"):
        assert cfg[name]["value"] is None, name
        assert cfg[name]["unavailable"], name


def test_an_unknown_backend_says_so_instead_of_returning_an_empty_config():
    class Homegrown:
        name = "homegrown"

    cfg = client_config(Homegrown())
    assert "no run-config extractor" in cfg["unavailable"]


def test_prompt_version_is_a_digest_of_the_prompt_text():
    """A hand-kept version number goes stale silently the first time a prompt is
    edited without bumping it, and a stale version asserts two runs were
    comparable when they were not."""
    a = prompt_version("system A", "system B")
    b = prompt_version("system A", "system B")
    c = prompt_version("system A", "system B!")
    assert a == b
    assert a["digest"] != c["digest"]


def test_digest_is_order_and_boundary_sensitive():
    """Concatenating without a separator would make ("ab","c") and ("a","bc")
    the same prompt version."""
    assert digest_text("ab", "c") != digest_text("a", "bc")
    assert digest_text("a", "b") != digest_text("b", "a")


def test_runconfig_serialises_the_whole_11_2_row():
    payload = RunConfig(
        harness="scripts/challenger_ablation.py",
        task="harbor/self-graded",
        samples_per_task=1,
        aggregation="max exploit gap across attempts",
        arms={"scripted": {"backend": "none"}},
        prompt=prompt_version("x"),
    ).to_dict()
    for key in (
        "eval_date",
        "samples_per_task",
        "aggregation_rule",
        "prompt_version",
        "assay_revision",
        "arms",
    ):
        assert key in payload, key
    json.dumps(payload)  # must be serialisable next to the numbers


def test_runconfig_states_its_own_absent_field_policy():
    """So a reader of the JSON knows a null means 'asked and was refused'
    rather than 'nobody looked'."""
    payload = RunConfig("h", "t", 1, "agg").to_dict()
    assert "null WITH a reason" in payload["absent_fields_policy"]


@pytest.mark.parametrize("path", ["results/challenger_ablation_runconfig.json"])
def test_the_recaptured_ablation_carries_a_run_config(path):
    from pathlib import Path

    target = Path(__file__).resolve().parents[1] / path
    if not target.exists():
        pytest.skip(f"{path} not generated on this machine (needs Docker and a model)")
    body = json.loads(target.read_text())
    assert body["run_config"]["spec"] == "hf-publication-specs.md 11.2"
    for arm in body["arms"]:
        assert "run_config" in arm, arm["challenger"]
