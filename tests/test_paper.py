"""Tie `paper/assay.tex` to the artifacts it reports, and the PDF to the source.

Three failures this guards, each a thing that happened in a sibling repository or
in this one:

* a number typed into the prose that drifts from `results/` (the repository's
  whole subject is that drift);
* a build that stays green while the PDF is wrong -- doubled backslashes once ate
  an abstract and a result in a sibling paper and nothing failed;
* a document that says one thing while the committed intervals say another.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
TEX = PAPER / "assay.tex"


def _exporter():
    spec = importlib.util.spec_from_file_location("export_paper_tables", ROOT / "scripts/export_paper_tables.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _macros() -> dict[str, str]:
    text = (PAPER / "generated/numbers.tex").read_text()
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}", text))


def _body() -> str:
    """The prose between \\begin{document} and the bibliography, comments removed."""
    text = TEX.read_text()
    text = re.sub(r"(?<!\\)%.*", "", text)
    return text.split(r"\begin{document}", 1)[1].split(r"\bibliographystyle", 1)[0]


def test_generated_files_are_what_the_exporter_writes_from_the_current_results():
    files = _exporter().build()
    stale = [n for n, t in files.items() if not (PAPER / "generated" / n).exists()
             or (PAPER / "generated" / n).read_text() != t]
    extra = [p.name for p in (PAPER / "generated").glob("*.tex") if p.name not in files]
    assert not stale and not extra, (
        f"paper/generated is stale ({stale + extra}); run `python scripts/export_paper_tables.py`"
    )


# Digits that may appear in the prose because they are not results of this
# repository: a cited source's own figure, a date, a count of things defined in
# the text itself. Anything else must be a macro from generated/numbers.tex.
ALLOWED_LITERALS = {
    # cited sources' own figures, each checked against the abstract it comes from
    "93", "1,699",                          # SWE-bench Verified annotation (OpenAI 2024; the anchor in results/cost_unit.json)
    "12",                                   # BenchGuard's author-confirmed ScienceAgentBench issues (arXiv 2604.24955)
    "168", "25.7",                          # ABA (arXiv 2605.26079)
    "219",                                  # BenchJack flaws (arXiv 2605.12673)
    "22.4", "49", "28.5",                   # arXiv 2606.16062, v2 and v1
    "445",                                  # construct-validity review (arXiv 2511.04703)
    "5.45", "8.49", "15.3", "10.7", "150",  # arXiv 2610.01491 and 2607.28367
    # the earlier revision the two outside reviews read
    "28",
    # a bare 2 or 3 left over from \tau^2 and C/3 in the strip above; a result is never one of these
    "2", "3",
    "1.0",            # 'scored 1.0' quotes a retracted claim verbatim (retraction 11)
    "122", "124",     # changelog slice numbers, names of files in docs/changelog/
    "8",              # the 8 in 'qwen3:8b', an 8-billion-parameter model
}


def test_no_result_number_is_typed_into_the_prose():
    body = _body()
    body = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", body)               # ISO dates
    body = body.replace("\\$", " USD ")                           # escaped dollar signs are not math delimiters
    body = re.sub(r"\$[^$]*\$", " ", body)                       # math
    body = re.sub(r"\\(cite[tp]?|ref|label|url|input|bibliography\w*)\{[^}]*\}", " ", body)
    body = re.sub(r"\\newcommand.*", " ", body)
    body = re.sub(r"\\[A-Za-z]+(\{\})?", " ", body)              # macros such as \lossAssay{}
    body = re.sub(r"\bV[1-8]\b", " ", body)                      # BenchJack class names
    body = body.replace("Apache-2.0", " ").replace("CC BY 4.0", " ")  # licence names
    body = re.sub(r"95\\%", " ", body)                           # the confidence level
    body = re.sub(r"\b[Ss]ection~?\s*\d+", " ", body)
    found = re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])", body)
    stray = sorted({f.rstrip(",") for f in found} - ALLOWED_LITERALS)
    assert not stray, (
        f"digits typed into the prose that are not macros and not on the allow-list: {stray}. "
        "A result number must come from generated/numbers.tex."
    )


def test_every_macro_the_prose_uses_is_defined():
    body = _body()
    used = set(re.findall(r"\\([A-Za-z]+)\{\}", body))
    defined = set(_macros())
    local = {"assay", "fe"}  # defined in the preamble
    missing = {u for u in used - defined - local if u[0].islower() and any(c.isupper() for c in u)}
    assert not missing, f"macros used in the prose but not generated: {sorted(missing)}"


def test_the_class_and_probe_family_counts_are_the_code_s():
    from assay.types import DefectClass

    macros = _macros()
    assert int(macros["nClasses"]) == len(DefectClass)
    families = {int(m) for m in re.findall(r"# family (\d+)", (ROOT / "src/assay/types.py").read_text())}
    assert max(families) == 11 == len(families), families
    assert "Eleven probe families" in _body()


def test_the_registrations_precede_the_code_they_register():
    """The paper says each registration was committed before the code it covers."""
    if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"],
                      capture_output=True, text=True).stdout.strip() != "false":
        pytest.skip("shallow clone: the registration order needs full history")

    def first_commit(path: str) -> str:
        out = subprocess.run(["git", "-C", str(ROOT), "log", "--reverse", "--format=%H", "--", path],
                             capture_output=True, text=True).stdout.split()
        assert out, f"{path} has no history"
        return out[0]

    pairs = [
        ("docs/PRE-REGISTRATION.md", "src/assay/_inspect_evals_corpus.py"),
        ("docs/PRE-REGISTRATION-TAU2.md", "src/assay/_tau2_corpus.py"),
        ("docs/PRE-REGISTRATION-NOANSWER.md", "src/assay/_noanswer_corpus.py"),
        ("docs/PRE-REGISTRATION-STEREOSET.md", "src/assay/_inspect_evals_corpus.py"),
    ]
    for reg, code in pairs:
        r = first_commit(reg)
        c = first_commit(code)
        if reg.endswith("STEREOSET.md"):
            # stereoset joined an existing module: compare against the commit that names it
            c = subprocess.run(["git", "-C", str(ROOT), "log", "--reverse", "--format=%H", "-S", "stereoset", "--", code],
                               capture_output=True, text=True).stdout.split()[0]
        ancestor = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", r, c]).returncode == 0
        assert ancestor and r != c, f"{reg} must be committed before {code}"


def _pdf_text() -> str:
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext not installed: the rendered-PDF check needs poppler")
    pdf = PAPER / "assay.pdf"
    assert pdf.exists(), "paper/assay.pdf is not committed"
    return subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True).stdout


def test_the_rendered_pdf_has_no_garbled_citation_and_all_its_floats():
    text = _pdf_text()
    assert "[?]" not in text and "??" not in text, "unresolved reference or citation in the PDF"
    for n in range(1, 5):
        assert f"Figure {n}:" in text, f"Figure {n} is missing from the PDF"
    for n in range(1, 8):
        assert f"Table {n}:" in text, f"Table {n} is missing from the PDF"
    assert "Abstract" in text
    pages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(
        ["pdfinfo", str(PAPER / "assay.pdf")], capture_output=True, text=True).stdout).group(1)) \
        if shutil.which("pdfinfo") else 12
    assert 8 <= pages <= 16, f"{pages} pages"


def test_every_number_in_the_abstract_and_headline_survives_into_the_pdf():
    """The doubled-backslash failure: the build stayed green and a result vanished."""
    flat = re.sub(r"\s+", " ", _pdf_text().replace("\u2212", "-").replace("\ufb01", "fi"))
    m = _macros()
    abstract = flat.split("Abstract", 1)[1].split("1 The question", 1)[0]
    for name in ["nEnv", "nPlanted", "lossAssay", "lossFlagEverything", "savedFlagEverything", "extSaved",
                 "precAssay", "gateMeanSaved", "tauAllRec", "tauAllP", "rtBroken", "nRetractions", "pctFloorAbsent",
                 "nSelfAuthored", "nExternal", "nClasses"]:
        value = m[name].replace(r"\ensuremath{-}", "-").replace("{,}", ",")
        assert value in abstract, f"{name}={value} is not in the rendered abstract"
    for name in ["savedRestricted", "critCross", "critErrPct", "gateWorstSaved", "tauNarP", "extProdDelta"]:
        value = m[name].replace(r"\ensuremath{-}", "-").replace("{,}", ",")
        assert value in flat, f"{name}={value} is missing from the rendered paper"


def test_the_committed_pdf_is_the_one_the_source_builds():
    """Skipped where tectonic is absent; the abstract check above still runs from the committed PDF."""
    if shutil.which("tectonic") is None:
        pytest.skip("tectonic not installed: cannot rebuild the PDF to compare")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "paper"
        shutil.copytree(PAPER, work, ignore=shutil.ignore_patterns("*.pdf", "*.aux", "*.log", "*.out", "*.blg"))
        r = subprocess.run(["tectonic", "assay.tex"], cwd=work, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-800:]
        fresh = subprocess.run(["pdftotext", str(work / "assay.pdf"), "-"], capture_output=True, text=True).stdout
    committed = _pdf_text()
    norm = lambda s: re.sub(r"\s+", " ", s)
    assert norm(fresh) == norm(committed), "paper/assay.pdf is not what paper/assay.tex builds; rebuild and commit it"


# ---- documents that must agree with the artifacts -----------------------------------------


def _md_rows(text: str, start: str, stop: str) -> list[list[str]]:
    block = text.split(start, 1)[1].split(stop, 1)[0]
    rows = []
    for line in block.splitlines():
        if line.startswith("|") and not line.startswith("|---"):
            rows.append([c.strip().strip("*").strip() for c in line.strip().strip("|").split("|")])
    return rows


def test_the_results_document_tables_are_the_committed_intervals():
    """Four rows of the per-arm table and every paired and per-profile row had drifted."""
    doc = (ROOT / "docs/RESULTS.md").read_text()
    iv = json.loads((ROOT / "results/intervals.json").read_text())["arms"]
    names = {"assay+auditor": "assay+auditor", "assay": "assay", "flag_everything": "flag_everything",
             "always_modal_defect": "always_modal_defect", "direct_prompt": "direct_prompt",
             "stratified_random": "stratified_random", "agent_with_tools": "agent_with_tools",
             "check_env": "check_env", "flag_nothing": "flag_nothing"}
    seen = set()
    for row in _md_rows(doc, "## Every arm, on one corpus", "**Every arm is measured"):
        label = re.sub(r"\(.*?\)|, one draw|`|\*", "", row[0]).strip()
        if label not in names:
            continue
        a = iv[names[label]]
        lo, hi = a["expected_loss"]["ci95"]
        assert row[1] == f"{a['expected_loss']['point']:.1f}", (label, row)
        assert row[2] == f"[{lo:.0f}, {hi:.0f}]", (label, row)
        assert row[3] == f"{a['recall']['point']:.3f}", (label, row)
        assert row[4] == f"{a['precision']['point']:.3f}", (label, row)
        seen.add(label)
    assert seen == set(names), f"rows missing from the per-arm table: {set(names) - seen}"

    sv = iv["assay"]["loss_saved_vs"]
    for row in _md_rows(doc, "## What holds, and what does not", "### The two trivial"):
        m = re.match(r"assay vs `(\w+)`", row[0])
        if m:
            d = sv[m.group(1)]
            assert row[1] == f"{d['point']:.1f}" and row[2] == f"[{d['ci95'][0]:.0f}, {d['ci95'][1]:.0f}]", row

    for row in _md_rows(doc, "| profile | assay | assay+auditor", "**Assay now wins all four"):
        m = re.match(r"`([\w-]+)`", row[0])
        if m:
            d = json.loads((ROOT / f"results/intervals-{m.group(1)}.json").read_text())["arms"]
            s = d["assay"]["loss_saved_vs"]["flag_everything"]
            assert row[1] == f"{d['assay']['expected_loss']['point']:.1f}", row
            assert row[3] == f"{d['flag_everything']['expected_loss']['point']:.1f}", row
            assert row[4] == f"{s['point']:.1f}", row
            assert f"[{s['ci95'][0]:.0f}, {s['ci95'][1]:.0f}]" in row[5], row


def test_the_provenance_counts_in_the_documents_are_the_registry_s():
    cs = json.loads((ROOT / "results/corpus_splits.json").read_text())
    n_ext = cs["n_external"]
    assert n_ext == 8
    doc = (ROOT / "docs/RESULTS.md").read_text()
    assert "| **genuinely external** | **8** |" in doc, "RESULTS.md provenance table is stale"
    assert "| authored here | 15 |" in doc
    assert "**25 planted here, 5 hand-triaged, 3 derived" in doc
    agents = (ROOT / "AGENTS.md").read_text()
    assert "only **3 of those 8**" in agents


def test_retired_figures_do_not_return():
    """Strings that were true once, were corrected in this release, and must not be restated as current."""
    retired = {
        "AGENTS.md": ["precision is 0.9464**", "3 of those\n  6"],
        "docs/FOR_AGENTS.md": ["precision is 0.9464", "1173.0h", "878%", "77.0 of the 351.0", "3 of those 7",
                               "43.0 [0, 125] vs 394.0"],
        "docs/RESULTS.md": ["2411.0", "2693.0", "542.0 on [46, 808]", "28.5% of 49"],
        "README.md": ["28.5% of 49"],
    }
    for path, strings in retired.items():
        text = (ROOT / path).read_text()
        for s in strings:
            assert s not in text, f"{path} restates a retired figure: {s!r}"


def test_the_deposit_metadata_cites_what_the_paper_cites_and_carries_its_abstract_numbers():
    z = json.loads((ROOT / ".zenodo.json").read_text())
    bib = (PAPER / "refs.bib").read_text()
    eprints = set(re.findall(r"eprint\s*=\s*\{([\d.]+)\}", bib))
    cited = {r["identifier"].removeprefix("arXiv:") for r in z["related_identifiers"] if r["scheme"] == "arxiv"}
    assert eprints == cited, f"refs.bib and .zenodo.json disagree on the arXiv works: {eprints ^ cited}"
    m = _macros()
    for name in ["lossAssay", "lossFlagEverything", "savedFlagEverything", "savedRestricted", "extSaved",
                 "precAssay", "gateMeanSaved", "tauAllP", "rtBroken", "nRetractions"]:
        value = m[name].replace(r"\ensuremath{-}", "-")
        assert value in z["description"], f"{name}={value} is not in the deposit description"
    assert "Not peer reviewed" in z["description"]
    title = re.search(r"\\title\{(.*?)\}\s*\\author", TEX.read_text(), flags=re.S).group(1)
    plain = re.sub(r"\s+", " ", title.replace("\\\\", " "))
    assert z["title"] == plain, (z["title"], plain)
    assert z["title"] in (ROOT / "CITATION.cff").read_text()
