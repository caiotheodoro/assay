#!/usr/bin/env python3
"""Write every number, table and figure the paper shows, from committed artifacts.

`paper/assay.tex` contains no result-derived number typed by hand. Each one is a
macro defined in `paper/generated/numbers.tex`, and each table or figure is a file
in `paper/generated/` that the paper `\\input`s. This script is the only writer of
that directory, and `tests/test_paper.py` fails if the directory differs from what
this script produces from the current `results/` (`--check` does the same).

Sources, all committed: `results/*.json`, the cost profiles under
`src/assay/costs/profiles/`, and two prose documents that carry counts no artifact
carries (`docs/RETRACTIONS.md`, `docs/RED-TEAM.md`).

Usage:
    python scripts/export_paper_tables.py            # write paper/generated/
    python scripts/export_paper_tables.py --check    # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = ROOT / "paper" / "generated"

ARM_MACRO = {
    "assay": "Assay",
    "assay+auditor": "AssayAuditor",
    "flag_everything": "FlagEverything",
    "flag_nothing": "FlagNothing",
    "check_env": "CheckEnv",
    "always_modal_defect": "AlwaysModal",
    "direct_prompt": "DirectPrompt",
    "stratified_random": "StratRandom",
    "agent_with_tools": "AgentTools",
}
ARM_TEX = {
    "assay": r"\textsc{Assay}",
    "assay+auditor": r"\textsc{Assay}+auditor (one draw)",
    "flag_everything": r"\texttt{flag\_everything}",
    "flag_nothing": r"\texttt{flag\_nothing}",
    "check_env": r"\texttt{check\_env}",
    "always_modal_defect": r"\texttt{always\_modal\_defect}",
    "direct_prompt": r"\texttt{direct\_prompt}",
    "stratified_random": r"\texttt{stratified\_random}",
    "agent_with_tools": r"\texttt{agent\_with\_tools}",
}
ARM_ORDER = [
    "assay+auditor", "assay", "flag_everything", "always_modal_defect", "direct_prompt",
    "agent_with_tools", "stratified_random", "check_env", "flag_nothing",
]
PROFILES = ["research-run", "production-training", "benchmark-publication", "flat"]
SPLIT_TEX = {
    "all": "all published",
    "external-envs": "genuinely external",
    "third-party-format": "our content, third-party format",
    "in-process-fixtures": "in-process fixtures",
    "self-authored": "self-authored",
    "no-harbor": "no Docker (no-harbor)",
}
WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
         7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}

_macros: dict[str, str] = {}


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text())


def put(name: str, value) -> None:
    if name in _macros:
        raise SystemExit(f"duplicate macro {name}")
    _macros[name] = re.sub(r"^-(?=\d)", r"\\ensuremath{-}", str(value))


def f1(x: float) -> str:
    return f"{x:.1f}"


def f3(x: float) -> str:
    return f"{x:.3f}"


def f0(x: float) -> str:
    return f"{x:,.0f}".replace(",", "{,}")


def ci(c) -> str:
    return f"[{c[0]:.0f}, {c[1]:.0f}]"


def tex_escape(s: str) -> str:
    s = s.replace("\\", "").replace("`", "")
    for a, b in [("τ²", r"$\tau^2$"), ("τ", r"$\tau$"), ("→", r"$\to$"), ("—", ";"), ("–", "--"),
                 ("--", "-{}-"), ("“", "``"), ("”", "''"), ("’", "'"), ("≥", r"$\geq$")]:
        s = s.replace(a, b)
    s = s.replace("**", "")
    s = re.sub(r'"([^"]*)"', r"``\1''", s)
    s = re.sub(r"\s+;", ";", s)
    out, i = [], 0
    for ch in s:
        if ch in "&%#_":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def macros_from_results() -> None:
    import yaml
    fr = load("full_run.json")
    iv = load("intervals.json")
    cs = load("corpus_splits.json")
    arms = fr["arms"]

    put("nEnv", fr["corpus_size"])
    put("nPlanted", fr["total_planted_defects"])
    put("nResamples", f0(iv["resamples"]))
    put("bootSeed", iv["seed"])
    put("nClasses", 16)  # asserted equal to the DefectClass enum in tests/test_paper.py

    # ---- arms, research-run ------------------------------------------------
    for arm, tag in ARM_MACRO.items():
        a, b = arms[arm], iv["arms"][arm]
        put(f"loss{tag}", f1(a["expected_loss"]))
        put(f"loLoss{tag}", f"{b['expected_loss']['ci95'][0]:.0f}")
        put(f"hiLoss{tag}", f"{b['expected_loss']['ci95'][1]:.0f}")
        put(f"rec{tag}", f3(a["recall"]))
        put(f"prec{tag}", f3(a["precision"]))
        put(f"spur{tag}", a["n_spurious"])
        put(f"miss{tag}", a["n_missed"])
    sv = iv["arms"]["assay"]["loss_saved_vs"]
    for arm in ("flag_everything", "flag_nothing", "check_env", "direct_prompt", "agent_with_tools",
                "stratified_random", "always_modal_defect"):
        tag = ARM_MACRO[arm]
        put(f"saved{tag}", f1(sv[arm]["point"]))
        put(f"loSaved{tag}", f"{sv[arm]['ci95'][0]:.0f}")
        put(f"hiSaved{tag}", f"{sv[arm]['ci95'][1]:.0f}")
        put(f"sep{tag}", "separated" if sv[arm]["separated"] else "not separated")
    put("nUnchecked", arms["assay"]["n_unchecked"])
    put("recChecked", f3(arms["assay"]["recall_on_checkable"]))
    put("nTP", fr["total_planted_defects"] - arms["assay"]["n_missed"] - arms["assay"]["n_unchecked"])
    put("nSpurAssay", arms["assay"]["n_spurious"])
    # the two LLM arms against the random policy and each other, from the arms table
    put("lossGapLLMvsRandom", f1(arms["stratified_random"]["expected_loss"] - arms["direct_prompt"]["expected_loss"]))
    cn = iv["arms"]["check_env"]["loss_saved_vs"]["flag_nothing"]
    put("savedCheckEnvVsNothing", f1(cn["point"]))
    put("loSavedCheckEnvVsNothing", f"{cn['ci95'][0]:.0f}")
    put("hiSavedCheckEnvVsNothing", f"{cn['ci95'][1]:.0f}")
    put("pctCheckEnvVsNothing", f"{100 * cn['point'] / arms['flag_nothing']['expected_loss']:.2f}")
    dp = iv["arms"]["direct_prompt"]["loss_saved_vs"]["stratified_random"]
    put("savedDPvsRandom", f1(dp["point"]))
    put("loSavedDPvsRandom", f"{dp['ci95'][0]:.0f}")
    put("hiSavedDPvsRandom", f"{dp['ci95'][1]:.0f}")
    aw = iv["arms"]["stratified_random"]["loss_saved_vs"]["agent_with_tools"]
    put("savedRandomVsAT", f1(aw["point"]))
    put("loSavedRandomVsAT", f"{aw['ci95'][0]:.0f}")
    put("hiSavedRandomVsAT", f"{aw['ci95'][1]:.0f}")

    # ---- profiles & post hoc prevalence-aware floors ------------------------
    pf = load("prevalence_floor.json")
    pf_all = pf["splits"]["all"]["profiles"]
    pf_ext = pf["splits"]["external-envs"]["profiles"]
    prof_rows = []
    for p in PROFILES:
        d = load(f"intervals-{p}.json")
        a, fe = d["arms"]["assay"], d["arms"]["flag_everything"]
        au = d["arms"]["assay+auditor"]
        sv = a["loss_saved_vs"]["flag_everything"]
        pfp = pf_all[p]
        fp_arm = pfp["arms"]["flag_present"]
        pv_arm = pfp["arms"]["prevalence_floor"]
        loo_arm = pfp["arms"]["prevalence_floor_loo"]
        sv_fp = pfp["assay_saved_vs"]["flag_present"]
        sv_pv = pfp["assay_saved_vs"]["prevalence_floor"]
        sv_loo = pfp["assay_saved_vs"]["prevalence_floor_loo"]
        tag = {"research-run": "Research", "production-training": "Prod",
               "benchmark-publication": "Bench", "flat": "Flat"}[p]
        put(f"profAssay{tag}", f1(a["expected_loss"]["point"]))
        put(f"profFloor{tag}", f1(fe["expected_loss"]["point"]))
        put(f"profSaved{tag}", f1(sv["point"]))
        put(f"profLoSaved{tag}", f"{sv['ci95'][0]:.0f}")
        put(f"profHiSaved{tag}", f"{sv['ci95'][1]:.0f}")
        put(f"lossRestricted{tag}", f1(fp_arm["expected_loss"]))
        put(f"savedRestricted{tag}", f1(sv_fp["point"]))
        put(f"loSavedRestricted{tag}", f"{sv_fp['ci95'][0]:.0f}")
        put(f"hiSavedRestricted{tag}", f"{sv_fp['ci95'][1]:.0f}")
        put(f"lossPrev{tag}", f1(pv_arm["expected_loss"]))
        put(f"savedPrev{tag}", f1(sv_pv["point"]))
        put(f"loSavedPrev{tag}", f"{sv_pv['ci95'][0]:.0f}")
        put(f"hiSavedPrev{tag}", f"{sv_pv['ci95'][1]:.0f}")
        put(f"sepPrev{tag}", "separated" if sv_pv["separated"] else "not separated")
        put(f"lossPrevLoo{tag}", f1(loo_arm["expected_loss"]))
        put(f"savedPrevLoo{tag}", f1(sv_loo["point"]))
        put(f"loSavedPrevLoo{tag}", f"{sv_loo['ci95'][0]:.0f}")
        put(f"hiSavedPrevLoo{tag}", f"{sv_loo['ci95'][1]:.0f}")
        put(f"prevFlaggedN{tag}", pfp["prevalence_floor_n_flagged_classes"])
        prof_rows.append((p, a["expected_loss"], fe["expected_loss"], fp_arm, pv_arm, sv_fp, sv_pv))

    # Shortcut aliases for the primary research-run restricted-floor CI
    sv_res_main = pf_all["research-run"]["assay_saved_vs"]["flag_present"]
    put("loSavedRestricted", f"{sv_res_main['ci95'][0]:.0f}")
    put("hiSavedRestricted", f"{sv_res_main['ci95'][1]:.0f}")
    put("sepRestricted", "separated" if sv_res_main["separated"] else "not separated")

    # External split post hoc prevalence-aware floor macros (research-run)
    pfe_r = pf_ext["research-run"]
    put("extPrevPresentClasses", pfe_r["n_present_classes"])
    put("extLossPrev", f1(pfe_r["arms"]["prevalence_floor"]["expected_loss"]))
    put("extSavedPrev", f1(pfe_r["assay_saved_vs"]["prevalence_floor"]["point"]))
    put("extLoSavedPrev", f"{pfe_r['assay_saved_vs']['prevalence_floor']['ci95'][0]:.0f}")
    put("extHiSavedPrev", f"{pfe_r['assay_saved_vs']['prevalence_floor']['ci95'][1]:.0f}")
    put("extLossPrevLoo", f1(pfe_r["arms"]["prevalence_floor_loo"]["expected_loss"]))
    put("extSavedPrevLoo", f1(pfe_r["assay_saved_vs"]["prevalence_floor_loo"]["point"]))
    put("extLoSavedPrevLoo", f"{pfe_r['assay_saved_vs']['prevalence_floor_loo']['ci95'][0]:.0f}")
    put("extHiSavedPrevLoo", f"{pfe_r['assay_saved_vs']['prevalence_floor_loo']['ci95'][1]:.0f}")

    rows = [
        r"\begin{tabular}{@{}lrrrrll@{}}", r"\toprule",
        r"profile & \textsc{Assay} & \texttt{flag\_all} & restr.$^\dagger$ & prev.$^\dagger$ & saved vs.\ restr.\ [95\% CI] & saved vs.\ prev.\ [95\% CI] \\",
        r"\midrule",
    ]
    for p, a, fe, fp_arm, pv_arm, sv_fp, sv_pv in prof_rows:
        f_fp = "" if sv_fp["separated"] else r"\,$^\circ$"
        f_pv = "" if sv_pv["separated"] else r"\,$^\circ$"
        rows.append(
            f"\\texttt{{{p}}} & {f1(a['point'])} & {f1(fe['point'])} & "
            f"{f1(fp_arm['expected_loss'])} & {f1(pv_arm['expected_loss'])} & "
            f"{f1(sv_fp['point'])} {ci(sv_fp['ci95'])}{f_fp} & "
            f"{f1(sv_pv['point'])} {ci(sv_pv['ci95'])}{f_pv} \\\\"
        )
    rows += [r"\bottomrule", r"\end{tabular}"]
    write("tab_profiles.tex", "\n".join(rows))

    # ---- arms table (including post hoc restricted & prevalence floors) -----
    pf_res = pf_all["research-run"]["arms"]
    rows = [
        r"\begin{tabular}{@{}lrrrr@{}}", r"\toprule",
        r"arm & expected loss & 95\% CI & recall & precision \\", r"\midrule",
    ]
    for arm in ("assay+auditor", "assay"):
        a, b = arms[arm], iv["arms"][arm]
        rows.append(f"{ARM_TEX[arm]} & {f1(a['expected_loss'])} & {ci(b['expected_loss']['ci95'])} & "
                    f"{f3(a['recall'])} & {f3(a['precision'])} \\\\")
    rows.append(r"\midrule")
    for pkey, plabel in (
        ("prevalence_floor", r"\texttt{prevalence\_floor}$^\dagger$ (in-sample)"),
        ("flag_present", r"\texttt{flag\_present}$^\dagger$ (restricted floor)"),
        ("prevalence_floor_loo", r"\texttt{prevalence\_floor\_loo}$^\dagger$ (LOO)"),
    ):
        a = pf_res[pkey]
        rows.append(f"{plabel} & {f1(a['expected_loss'])} & {ci(a['ci95'])} & "
                    f"{f3(a['recall'])} & {f3(a['precision'])} \\\\")
    for arm in ARM_ORDER[2:]:
        a, b = arms[arm], iv["arms"][arm]
        rows.append(f"{ARM_TEX[arm]} & {f1(a['expected_loss'])} & {ci(b['expected_loss']['ci95'])} & "
                    f"{f3(a['recall'])} & {f3(a['precision'])} \\\\")
    rows += [r"\bottomrule", r"\end{tabular}"]
    write("tab_arms.tex", "\n".join(rows))

    # ---- provenance and splits ---------------------------------------------
    prov = cs["provenance"]
    n_by = {}
    for v in prov.values():
        key = (v["env_author"], v["label_source"])
        n_by[key] = n_by.get(key, 0) + 1
    n_ext = sum(1 for v in prov.values() if v["env_author"] == "external")
    n_ext_derived = n_by.get(("external", "externally_derived"), 0)
    n_ext_hand = n_by.get(("external", "hand_triaged"), 0)
    put("nAuthored", sum(1 for v in prov.values() if v["env_author"] == "authored_here"))
    put("nThirdFormat", sum(1 for v in prov.values() if v["env_author"] == "third_party_format"))
    put("nExternal", n_ext)
    put("nExtDerived", n_ext_derived)
    put("nExtHand", n_ext_hand)
    put("nSelfAuthored", len(prov) - n_ext)
    put("nFixtures", sum(1 for k in prov if k.startswith("fixture/")))
    assert len(prov) == fr["corpus_size"], "provenance and full_run disagree on corpus size"
    ext_planted = cs["splits"]["external-envs"]["n_planted"]
    put("nExtPlanted", ext_planted)
    put("nPlantedHere", fr["total_planted_defects"] - ext_planted)
    put("nPlantedExtDerived", sum(len(fr["per_env"][k]["planted"]) for k, v in prov.items()
                                  if v["label_source"] == "externally_derived"))
    put("nPlantedHand", sum(len(fr["per_env"][k]["planted"]) for k, v in prov.items()
                            if v["label_source"] == "hand_triaged"))

    split_rows = [
        r"\begin{tabular}{@{}lrrrrl@{}}", r"\toprule",
        r"split (\texttt{research-run}) & envs & planted & \textsc{Assay} & \texttt{flag\_everything} & saved [95\% CI] \\",
        r"\midrule",
    ]
    for name in ("all", "self-authored", "in-process-fixtures", "third-party-format", "external-envs"):
        s = cs["splits"][name]
        r = s["profiles"]["research-run"]
        sv = s["paired_vs_flag_everything"]["assay"]["loss_saved_vs"]["flag_everything"]
        flag = "" if sv["separated"] else r" \emph{not separated}"
        split_rows.append(
            f"{SPLIT_TEX[name]} & {s['n_environments']} & {s['n_planted']} & {f1(r['assay']['expected_loss'])} & "
            f"{f1(r['flag_everything']['expected_loss'])} & {f1(sv['point'])} [{sv['ci95'][0]:.0f}, {sv['ci95'][1]:.0f}]{flag} \\\\")
    split_rows += [r"\bottomrule", r"\end{tabular}"]
    write("tab_splits.tex", "\n".join(split_rows))

    ext = cs["splits"]["external-envs"]
    er = ext["profiles"]["research-run"]
    esv = ext["paired_vs_flag_everything"]["assay"]["loss_saved_vs"]["flag_everything"]
    put("extLossAssay", f1(er["assay"]["expected_loss"]))
    put("extLossFloor", f1(er["flag_everything"]["expected_loss"]))
    put("extSaved", f1(esv["point"]))
    put("extLoSaved", f"{esv['ci95'][0]:.0f}")
    put("extHiSaved", f"{esv['ci95'][1]:.0f}")
    put("extPrec", f3(er["assay"]["precision"]))
    put("extRec", f3(er["assay"]["recall"]))
    put("extSpur", er["assay"]["n_spurious"])
    put("extMiss", er["assay"]["n_missed"])
    put("extUnchecked", er["assay"]["n_unchecked"])
    put("extRecChecked", f3(er["assay"]["recall_on_checkable"]))
    put("extLossAuditor", f1(er["assay+auditor"]["expected_loss"]))
    put("extLossCheckEnv", f1(er["check_env"]["expected_loss"]))
    put("extLossNothing", f1(er["flag_nothing"]["expected_loss"]))
    ext_rows = [
        r"\begin{tabular}{@{}lrrrl@{}}", r"\toprule",
        r"profile (external split) & \textsc{Assay} & \texttt{flag\_everything} & saved & 95\% CI \\", r"\midrule",
    ]
    for p in PROFILES:
        r = ext["profiles"][p]
        a, fe = r["assay"]["expected_loss"], r["flag_everything"]["expected_loss"]
        sv = ext["paired_vs_flag_everything"]
        # per-profile intervals for the split exist only for research-run; the others are points
        ext_rows.append(f"\\texttt{{{p}}} & {f1(a)} & {f1(fe)} & {f1(fe - a)} & "
                        f"{'point only' if p != 'research-run' else ci([esv['ci95'][0], esv['ci95'][1]])} \\\\")
    ext_rows += [r"\bottomrule", r"\end{tabular}"]
    write("tab_external_profiles.tex", "\n".join(ext_rows))
    ep = ext["profiles"]
    put("extProdAssay", f1(ep["production-training"]["assay"]["expected_loss"]))
    put("extProdFloor", f1(ep["production-training"]["flag_everything"]["expected_loss"]))
    put("extProdDelta", f1(ep["production-training"]["assay"]["expected_loss"] - ep["production-training"]["flag_everything"]["expected_loss"]))
    put("extBenchAssay", f1(ep["benchmark-publication"]["assay"]["expected_loss"]))
    put("extBenchFloor", f1(ep["benchmark-publication"]["flag_everything"]["expected_loss"]))
    put("extFlatAssay", f1(ep["flat"]["assay"]["expected_loss"]))
    put("extFlatFloor", f1(ep["flat"]["flag_everything"]["expected_loss"]))
    sa = cs["splits"]["self-authored"]
    put("selfLossAssay", f1(sa["profiles"]["research-run"]["assay"]["expected_loss"]))
    put("selfLossFloor", f1(sa["profiles"]["research-run"]["flag_everything"]["expected_loss"]))
    put("selfN", sa["n_environments"])
    tp = cs["splits"]["third-party-format"]
    put("tpfLossAssay", f1(tp["profiles"]["research-run"]["assay"]["expected_loss"]))
    put("tpfLossFloor", f1(tp["profiles"]["research-run"]["flag_everything"]["expected_loss"]))
    put("tpfN", tp["n_environments"])
    nh = cs["splits"]["no-harbor"]
    put("noHarborN", nh["n_environments"])

    # ---- the floor, cell by cell -------------------------------------------
    n_env, n_cls = fr["corpus_size"], 16
    planted_classes = set()
    for e in fr["per_env"].values():
        planted_classes |= set(e["planted"])
    absent = n_cls - len(planted_classes)
    assert {"EXCESSIVE_PERMISSIONS", "EVALUATOR_RCE", "DIFFICULTY_SATURATED", "DIFFICULTY_IMPOSSIBLE"} == (
        {c for c in __import__("assay.types", fromlist=["DefectClass"]).DefectClass.__members__} - planted_classes
    ), "the four classes the paper names as planted nowhere are not the ones planted nowhere"
    put("nClassesAbsent", absent)
    put("nClassesPresent", len(planted_classes))
    cells = {"absent": [0, 0], "clean": [0, 0], "dirty": [0, 0]}  # [floor false alarms, assay false alarms]
    clean_envs = 0
    for eid, e in fr["per_env"].items():
        planted = set(e["planted"])
        spur = set(e["spurious"])
        if not planted:
            clean_envs += 1
        n_unplanted_cells = n_cls - len(planted)
        n_absent_here = absent
        n_present_unplanted = n_unplanted_cells - n_absent_here
        cells["absent"][0] += n_absent_here
        key = "clean" if not planted else "dirty"
        cells[key][0] += n_present_unplanted
        for c in spur:
            if c in planted_classes:
                cells[key][1] += 1
            else:
                cells["absent"][1] += 1
    floor_total = sum(c[0] for c in cells.values())
    assert floor_total == arms["flag_everything"]["expected_loss"] == arms["flag_everything"]["n_spurious"]
    put("nCleanEnv", clean_envs)
    put("floorAbsent", cells["absent"][0])
    put("floorClean", cells["clean"][0])
    put("floorDirty", cells["dirty"][0])
    put("assayAbsentFA", cells["absent"][1])
    put("assayCleanFA", cells["clean"][1])
    put("assayDirtyFA", cells["dirty"][1])
    put("pctFloorAbsent", f"{100 * cells['absent'][0] / floor_total:.1f}")
    put("pctFloorClean", f"{100 * cells['clean'][0] / floor_total:.1f}")
    restricted_floor = floor_total - cells["absent"][0]
    put("floorRestricted", f1(restricted_floor))
    put("savedRestricted", f1(restricted_floor - arms["assay"]["expected_loss"]))
    put("floorPerEnvClean", n_cls)
    fe_cost = arms["flag_everything"]["expected_loss"]
    assay_miss_cost = arms["assay"]["expected_loss"] - arms["assay"]["n_spurious"] * 1.0
    put("assayMissCost", f1(assay_miss_cost))
    write("fig_floor.tex", floor_figure(cells, assay_miss_cost))

    # ---- cost sensitivity and cost anchors ---------------------------------
    cs_ = load("cost_sensitivity.json")
    prod = yaml.safe_load((ROOT / "src/assay/costs/profiles/production-training.yaml").read_text())
    put("prodRatio", f"{prod['miss']['CRITICAL'] / prod['false_alarm']:.0f}")
    na = (ROOT / "docs/PRE-REGISTRATION-NOANSWER.md").read_text()
    m = re.search(r"\| \*\*agent saves, on the headline\*\* \| [\d.]+ \| \*\*([\d.]+)\*\* \|", na)
    assert m, "the no-answer registration no longer carries its predicted gate saving"
    put("predGateSaving", m.group(1))
    put("critShipped", f"{cs_['shipped_value']:.0f}")
    put("critCross", f"{cs_['exact_crossover_critical_cost']:.0f}")
    put("critCrossRatio", f"{cs_['exact_crossover_critical_cost'] / cs_['shipped_value']:.1f}")
    put("critErrPct", f"{100 * (cs_['exact_crossover_critical_cost'] / cs_['shipped_value'] - 1):.0f}")
    cu = load("cost_unit.json")
    put("costFloorLo", f"{cu['floor']['range_engineer_hours'][0]:.2f}")
    put("costFloorHi", f"{cu['floor']['range_engineer_hours'][1]:.2f}")
    put("costCeilLo", f"{cu['ceiling']['range_engineer_hours'][0]:.1f}")
    put("costCeilHi", f"{cu['ceiling']['range_engineer_hours'][1]:.1f}")
    assert cu["crossover_is_above_the_ceiling"] is True
    gpu = sorted({r["gpu_hours"] for r in cu["floor"]["rows"]})
    eng = sorted({r["engineer_usd_per_hour"] for r in cu["floor"]["rows"]})
    mins = sorted({r["minutes_per_sample"] for r in cu["ceiling"]["rows"]})
    put("costGpuLo", f"{gpu[0]:.0f}")
    put("costGpuHi", f"{gpu[-1]:.0f}")
    put("costSpot", f"{cu['floor']['spot_usd_per_hour']:.2f}")
    put("costEngLo", f"{eng[0]:.0f}")
    put("costEngHi", f"{eng[-1]:.0f}")
    put("costMinLo", f"{mins[0]:.0f}")
    put("costMinHi", f"{mins[-1]:.0f}")
    put("costSamples", f"{cu['ceiling']['rows'][0]['samples']:,}".replace(",", "{,}"))
    # per-split crossover: Assay's only priced miss is one HIGH defect (C/3), so loss = spurious + C/3
    ext_r = cs["splits"]["external-envs"]["profiles"]["research-run"]
    assert ext_r["assay"]["n_missed"] + ext_r["assay"]["n_unchecked"] == 1
    assert abs(ext_r["assay"]["expected_loss"] - ext_r["assay"]["n_spurious"] - 40.0) < 1e-9
    put("extCross", f"{3 * (ext_r['flag_everything']['expected_loss'] - ext_r['assay']['n_spurious']):.0f}")
    put("highCross", f"{arms['flag_everything']['expected_loss'] - arms['assay']['n_spurious']:.0f}")
    write("fig_cost.tex", cost_figure(cs_))

    # ---- cost profiles table -------------------------------------------------
    rows = [r"\begin{tabular}{@{}lrrrrr@{}}", r"\toprule",
            r"profile & miss CRITICAL & miss HIGH & miss MEDIUM & miss LOW & false alarm \\", r"\midrule"]
    for p in PROFILES:
        y = yaml.safe_load((ROOT / "src/assay/costs/profiles" / f"{p}.yaml").read_text())
        m = y["miss"]
        rows.append(f"\\texttt{{{p}}} & {m['CRITICAL']} & {m['HIGH']} & {m['MEDIUM']} & {m['LOW']} & {y['false_alarm']} \\\\")
    rows += [r"\bottomrule", r"\end{tabular}"]
    write("tab_costprofiles.tex", "\n".join(rows))

    # ---- tau2 and the external recall measurements --------------------------
    t2 = load("tau2_recall.json")
    c, x = t2["combined"], t2["combined_excluding_advisory_probe"]
    put("tauTasks", c["significance"]["n_tasks"])
    put("tauPos", c["significance"]["n_positives"])
    put("tauBase", f3(c["significance"]["base_rate"]))
    put("tauAllTP", c["confusion"]["tp"])
    put("tauAllFlag", c["significance"]["n_flagged"])
    put("tauAllRec", f3(c["rates"]["recall"]))
    put("tauAllPrec", f3(c["rates"]["precision"]))
    put("tauAllP", f3(c["significance"]["p_one_sided"]))
    put("tauAllExpTP", f"{c['significance']['expected_tp_if_flagged_at_random']:.2f}")
    put("tauNarTP", x["confusion"]["tp"])
    put("tauNarFlag", x["significance"]["n_flagged"])
    put("tauNarRec", f3(x["rates"]["recall"]))
    put("tauNarPrec", f3(x["rates"]["precision"]))
    put("tauNarP", f3(x["significance"]["p_one_sided"]))
    put("tauNarExpTP", f"{x['significance']['expected_tp_if_flagged_at_random']:.2f}")
    put("tauFloorPrec", f3(t2["trivial_floor"]["rates"]["precision"]))
    cat = t2["combined_recall_by_category"]
    crow = [r"\begin{tabular}{@{}lrrr@{}}", r"\toprule",
            r"upstream category & positives & detected & recall \\", r"\midrule"]
    for k, v in cat.items():
        crow.append(f"{k.replace('_', ' ')} & {v['n_positives']} & {v['n_detected']} & {f3(v['recall'])} \\\\")
    crow += [r"\bottomrule", r"\end{tabular}"]
    write("tab_tau2_categories.tex", "\n".join(crow))
    put("tauDbPos", cat["database_accuracy"]["n_positives"])
    put("tauEvalAmbPos", cat["evaluation_ambiguity"]["n_positives"])
    put("tauEvalAmbDet", cat["evaluation_ambiguity"]["n_detected"])

    sab = load("sab_benchguard/assay__original_result.json")
    rec = sab["their_report"]["recall"]["aligned"]
    put("sabGold", rec["total"])
    put("sabDetected", rec["count"])
    put("sabFindings", sab["findings_submitted"]["total"])
    assert sab["findings_submitted"]["total"] == 0

    rc = load("real_check_env.json")
    put("realCheckPlanted", rc["planted_defects"])
    put("realCheckDetected", rc["detected_by_real_checkers"])

    # ---- the agent: gate reliability, semantic gate, challenger -------------
    gr = load("gate_reliability.json")
    sv = gr["auditor_arm"]["saved_vs_deterministic"]
    put("gateRuns", gr["n_runs"])
    put("gateMeanSaved", f1(sv["mean"]))
    put("gateMedianSaved", f1(sv["median"]))
    put("gateMaxSaved", f1(sv["max"]))
    put("gateWorstSaved", f1(sv["min"]).lstrip("-"))
    put("gateWorstLoss", f1(gr["auditor_arm"]["expected_loss"]["max"]))
    put("gateBestLoss", f1(gr["auditor_arm"]["expected_loss"]["min"]))
    put("gateDetLoss", f1(gr["deterministic_arm"]["expected_loss"]))
    assert gr["deterministic_arm"]["identical_every_run"] is True
    put("gateBadRuns", gr["false_override_rate"]["runs_with_a_false_override"])
    put("gateGoodRuns", gr["n_runs"] - gr["false_override_rate"]["runs_with_a_false_override"])
    smin = min(v for v in sv["values"] if v > 0)
    put("gateGoodMin", f1(smin))
    put("gateGoodMax", f1(sv["max"]))
    write("fig_gate.tex", gate_figure(sv["values"]))
    put("gateRunValues", ", ".join(f"{v:.1f}".replace("-", "\\ensuremath{-}") for v in sv["values"]))
    fo = load("false_override_rate.json")
    put("foTrials", fo["trials"])
    put("foFalse", fo["false_overrides"])
    put("foUpper", f"{100 * fo['upper_95']:.1f}")
    sg = load("semantic_gate.json")["backends"]["claude-cli:sonnet"]
    put("sgPosRuns", sg["positive_runs"])
    put("sgTPRuns", sg["true_positive_runs"])
    put("sgNegRuns", sg["negative_runs"])
    put("sgFPRuns", sg["false_positive_runs"])
    put("sgNPos", sg["n_positive"])
    put("sgNNeg", sg["n_negative"])
    put("sgFPPct", f"{100 * sg['false_positive_runs'] / sg['negative_runs']:.1f}")

    fof = load("floor_of_the_field.json")["rows"][0]
    put("fofDetected", fof["n_detected"])
    put("fofPos", fof["n_positives"])
    put("fofTasks", fof["n_tasks"])
    put("fofThreshold", fof["stops_clearing_the_floor_at_or_above"])
    assert "BenchGuard" in fof["claim"] and "Opus" in fof["claim"]
    ch = load("challenger_reliability.json")
    put("chHits", ch["hits"])
    put("chK", ch["k"])
    sf = load("scripted_floor.json")
    put("scriptedSeconds", f1(sf["measured"]["seconds"]))
    put("scriptedAttempts", sf["measured"]["attempts"])
    ab = load("challenger_ablation.json")
    byname = {a["challenger"]: a for a in ab["arms"]}
    put("ablScriptedThenSec", f1(byname["scripted"]["seconds"]))
    pq = [a for a in ab["arms"] if a["challenger"].startswith("prompted:qwen")][0]
    put("ablQwenSec", f1(pq["seconds"]))
    put("ablQwenAttempts", pq["attempts"])
    put("ablClaudeSec", f1(sf["against"]["claude-cli:sonnet, the run that originally found it"]["seconds"]))
    ap = load("agentic_profile.json")
    put("agMissEnvs", len(ap["per_environment_miss_rate"]))
    put("agK", ap["k"])
    put("agSlice", len(ap["never_missed"]) + len(ap["per_environment_miss_rate"]))
    put("agDetLossThen", f1(ap["deterministic_arm"]["loss"]["research-run"]))
    gd = load("train_holdout_dedup.json")["holdout_prompt_exposure"]
    put("grpoRows", gd["colliding_train_rows"])
    put("grpoTotalRows", gd["total_train_rows"])
    put("grpoPct", f"{100 * gd['fraction_of_training_rows']:.0f}")
    la = load("label_agreement.json")["agreement"]
    put("kappaVal", f3(la["cohen_kappa"]))
    put("kappaEnvs", la["n_environments"])
    put("kappaAgree", f"{100 * la['percent_agreement']:.0f}")

    # ---- counts that live in prose documents --------------------------------
    ret = (ROOT / "docs/RETRACTIONS.md").read_text()
    n_ret = len(re.findall(r"^## \d+\. ", ret, flags=re.M))
    put("nRetractions", n_ret)
    rt = (ROOT / "docs/RED-TEAM.md").read_text()
    summary = rt.split("## Summary", 1)[1].split("\n---", 1)[0]
    rows = []
    for m in re.finditer(r"^\| (\d+) \| (.*?) \| \*\*(\w+)([^*]*)\*\*(.*?) \|$", summary, flags=re.M):
        n, claim, verdict, tail, rest = m.groups()
        why = (tail + rest).strip().lstrip("—").strip()
        rows.append((n, claim, verdict, None, why))
    counts: dict[str, int] = {}
    for _, _, verdict, *_ in rows:
        counts[verdict] = counts.get(verdict, 0) + 1
    put("rtClaims", len(rows))
    put("rtBroken", counts.get("BROKEN", 0))
    put("rtPartial", counts.get("PARTIAL", 0))
    put("rtWeak", counts.get("WEAK", 0))
    put("rtSurvives", counts.get("SURVIVES", 0))
    broken_rows = [r for r in rows if r[2] == "BROKEN"]
    assert len(broken_rows) == counts["BROKEN"]
    rt_rows = [r"\begin{tabular}{@{}rp{0.52\linewidth}p{0.34\linewidth}@{}}", r"\toprule",
               r"\# & claim as published & what the red team found \\", r"\midrule"]
    for n, claim, verdict, _, why in rows:
        if verdict != "BROKEN":
            continue
        rt_rows.append(f"{n} & {tex_escape(claim)} & {tex_escape(why or '')} \\\\")
    rt_rows += [r"\bottomrule", r"\end{tabular}"]
    write("tab_redteam.tex", "\n".join(rt_rows))
    put("nRedTeamFoundAfter", n_ret - counts.get("BROKEN", 0))

    # ---- corpus composition table (from provenance + full_run) --------------
    from collections import Counter, defaultdict

    from assay.probes import all_probes
    from assay.types import DEFAULT_SEVERITY, DefectClass

    author_label = {
        "authored_here": "authored here",
        "third_party_format": "third-party format",
        "external": "genuinely external",
    }
    author_order = {"authored_here": 0, "third_party_format": 1, "external": 2}
    source_label = {
        "planted_here": "planted here",
        "hand_triaged": "hand-triaged",
        "externally_derived": "externally derived",
    }
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for eid, p in sorted(prov.items()):
        groups[(p["env_author"], p["label_source"], eid.split("/", 1)[0])].append(eid)

    corp_rows = [
        r"\begin{tabular}{@{}lllrrrr@{}}", r"\toprule",
        r"provenance & label source & ecosystem & envs & clean & planted & spurious \\",
        r"\midrule",
    ]
    tot_e = tot_c = tot_p = tot_s = 0
    for (auth, lsrc, eco), eids in sorted(
        groups.items(), key=lambda kv: (author_order[kv[0][0]], kv[0][1], kv[0][2])
    ):
        n_e = len(eids)
        n_c = sum(1 for e in eids if not fr["per_env"][e]["planted"])
        n_p = sum(len(fr["per_env"][e]["planted"]) for e in eids)
        n_s = sum(len(fr["per_env"][e]["spurious"]) for e in eids)
        tot_e += n_e
        tot_c += n_c
        tot_p += n_p
        tot_s += n_s
        corp_rows.append(
            f"{author_label[auth]} & {source_label[lsrc]} & \\texttt{{{tex_escape(eco)}}} & "
            f"{n_e} & {n_c} & {n_p} & {n_s} \\\\"
        )
    assert (tot_e, tot_p, tot_s) == (fr["corpus_size"], fr["total_planted_defects"], arms["assay"]["n_spurious"])
    corp_rows += [
        r"\midrule",
        f"\\textbf{{total}} & & & \\textbf{{{tot_e}}} & \\textbf{{{tot_c}}} & \\textbf{{{tot_p}}} & \\textbf{{{tot_s}}} \\\\",
        r"\bottomrule", r"\end{tabular}",
    ]
    write("tab_corpus.tex", "\n".join(corp_rows))

    # ---- 16 defect classes table (from types, probes, and full_run) ---------
    class_to_fam: dict[DefectClass, str] = {}
    for pr in all_probes():
        for d in pr.detects:
            class_to_fam[d] = pr.family
    fam_tex = {
        "verifier_integrity": "Verifier integrity",
        "trivial_floor": "Trivial floor",
        "separability": "Separability",
        "contamination": "Contamination",
        "shortcut_leakage": "Shortcut leakage",
        "spec_verifier_match": r"Spec$\leftrightarrow$verifier",
        "determinism": "Determinism",
        "difficulty_band": "Difficulty band",
        "reward_hackability": "Reward hackability",
        "sandbox_permissions": "Sandbox permissions",
        "evaluator_code_execution": "Evaluator RCE",
    }
    planted_c: Counter[str] = Counter()
    caught_c: Counter[str] = Counter()
    unchk_c: Counter[str] = Counter()
    spur_c: Counter[str] = Counter()
    for row in fr["per_env"].values():
        p_set = set(row["planted"])
        d_set = set(row["assay_detected"])
        u_set = set(row["unchecked"])
        for x in p_set:
            planted_c[x] += 1
        for x in p_set & d_set:
            caught_c[x] += 1
        for x in u_set:
            unchk_c[x] += 1
        for x in d_set - p_set:
            spur_c[x] += 1

    cls_rows = [
        r"\begin{tabular}{@{}lllrrrr@{}}", r"\toprule",
        r"probe family & defect class & severity & planted & caught & unchk. & spur. \\",
        r"\midrule",
    ]
    for d in DefectClass:
        v = d.value
        cls_rows.append(
            f"{fam_tex[class_to_fam[d]]} & \\texttt{{{tex_escape(v)}}} & "
            f"{DEFAULT_SEVERITY[d].value} & {planted_c[v]} & {caught_c[v]} & "
            f"{unchk_c[v]} & {spur_c[v]} \\\\"
        )
    cls_rows += [
        r"\midrule",
        f"\\textbf{{total ({len(fam_tex)} families)}} & \\textbf{{{len(DefectClass)} classes}} & & "
        f"\\textbf{{{sum(planted_c.values())}}} & \\textbf{{{sum(caught_c.values())}}} & "
        f"\\textbf{{{sum(unchk_c.values())}}} & \\textbf{{{sum(spur_c.values())}}} \\\\",
        r"\bottomrule", r"\end{tabular}",
    ]
    write("tab_classes.tex", "\n".join(cls_rows))

    # ---- pre-registrations outcomes & deviations table (Appendix A) ---------
    for reg_file in (
        "docs/PRE-REGISTRATION.md",
        "docs/PRE-REGISTRATION-TAU2.md",
        "docs/PRE-REGISTRATION-NOANSWER.md",
        "docs/PRE-REGISTRATION-STEREOSET.md",
    ):
        assert (ROOT / reg_file).exists(), f"missing frozen registration {reg_file}"
    reg_rows = [
        r"\begin{tabular}{@{}p{0.19\linewidth}p{0.20\linewidth}p{0.26\linewidth}p{0.28\linewidth}@{}}",
        r"\toprule",
        r"registration & expansion & deterministic predictions & falsification / deviations \\",
        r"\midrule",
        r"1.\ External tasks (\texttt{PRE-REGISTRATION}) & +2 external (\texttt{paws}, \texttt{boolq}; $n=24 \to 26$) & "
        r"All held (\assay{} 280.0, floor 316.0, margin 36.0; \texttt{boolq} \texttt{NOT\_APPLICABLE}). & "
        r"Reproducibility criterion fired: \texttt{harbor/broken-gold} flaked \texttt{NONDETERMINISM} in 1 of 6 full runs under load. \\",
        r"\addlinespace[3pt]",
        r"2.\ $\tau^2$-bench (\texttt{...-TAU2}) & +2 external ($\tau^2$ retail, airline; $n=26 \to 28$; 14$\to$16 classes) & "
        r"All deterministic corpus predictions held (\assay{} 43.0, floor 394.0, 3 spurious). & "
        r"One arithmetic error in external floor prediction (81.0 vs.\ 89.0); LLM vs.\ random order flipped (criterion fired). \\",
        r"\addlinespace[3pt]",
        r"3.\ No-answer set (\texttt{...-NOANSWER}) & +4 no-answer (1 external \texttt{personality\_BFI}, 3 authored; $n=28 \to 32$) & "
        r"Deterministic arm held (\assay{} 56.0, floor 458.0, 16 spurious). & "
        r"Gate criterion 1 fired on repeated runs (false override on \texttt{tau2/airline}); name-filter ceiling claim retracted (\#21). \\",
        r"\addlinespace[3pt]",
        r"4.\ StereoSet (\texttt{...-STEREOSET}) & +1 external no-answer (\texttt{stereoset}; $n=32 \to 33$) & "
        r"All held (\assay{} 57.0, floor 474.0, 17 spurious; gate withheld \texttt{GOLD\_FAILS}). & "
        r"All four criteria passed on registration run; gate later declined \texttt{stereoset} in 2 of 7 reliability runs. \\",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    write("tab_registrations.tex", "\n".join(reg_rows))


# ---- figures (pgfplots) ------------------------------------------------------


def arms_figure(fr: dict, iv: dict) -> str:
    names = list(reversed(ARM_ORDER))
    key = lambda a: a.replace("_", "").replace("+", "plus")
    sym = ",".join(key(a) for a in names)
    labels = ",".join("{" + ARM_TEX[a].replace("\\textsc{Assay}+auditor (one draw)", "\\textsc{Assay}+auditor") + "}" for a in names)
    lines = [
        r"\begin{tikzpicture}",
        r"\begin{axis}[xbar, xmode=log, width=0.72\linewidth, height=6.4cm, xmin=0.8, xmax=8000,",
        f"  symbolic y coords={{{sym}}}, ytick=data, yticklabels={{{labels}}}, yticklabel style={{font=\\footnotesize}},",
        r"  xlabel={expected loss, \texttt{research-run} (log scale; bars are points, whiskers 95\% CI)},",
        r"  bar width=6pt, xmajorgrids, enlarge y limits=0.07]",
    ]
    lines.append(r"\addplot[fill=black!35, draw=black!70] coordinates {" +
                 " ".join(f"({max(fr['arms'][a]['expected_loss'], 0.5):.1f},{key(a)})" for a in names) + "};")
    for a in names:
        lo, hi = iv["arms"][a]["expected_loss"]["ci95"]
        lines.append(f"\\draw[black, line width=0.6pt] (axis cs:{max(lo, 0.8):.1f},{key(a)}) -- (axis cs:{hi:.1f},{key(a)});")
    lines += [r"\end{axis}", r"\end{tikzpicture}"]
    return "\n".join(lines)


def floor_figure(cells: dict, assay_miss: float) -> str:
    absent, clean, dirty = cells["absent"], cells["clean"], cells["dirty"]
    a_fa = sum(c[1] for c in cells.values())
    return "\n".join([
        r"\begin{tikzpicture}",
        r"\begin{axis}[xbar stacked, width=0.8\linewidth, height=4.2cm, xmin=0, xmax=520,",
        r"  ytick={0,1}, ymin=-0.7, ymax=1.7,",
        r"  yticklabels={\textsc{Assay},\texttt{flag\_everything}}, yticklabel style={font=\footnotesize},",
        r"  xlabel={expected loss, \texttt{research-run}}, bar width=11pt, xmajorgrids,",
        r"  legend style={at={(0.5,1.08)}, anchor=south, font=\scriptsize, legend columns=2, draw=none},",
        r"  legend cell align=left]",
        f"\\addplot[fill=black!75] coordinates {{({absent[0]},1) ({absent[1]},0)}};",
        f"\\addplot[fill=black!45] coordinates {{({clean[0]},1) ({clean[1]},0)}};",
        f"\\addplot[fill=black!18] coordinates {{({dirty[0]},1) ({dirty[1]},0)}};",
        f"\\addplot[fill=white, draw=black] coordinates {{(0,1) ({assay_miss:.0f},0)}};",
        r"\legend{false alarms on classes planted nowhere, false alarms on environments with no planted defect, "
        r"false alarms on environments with defects, cost of the one unchecked defect}",
        r"\end{axis}",
        r"\end{tikzpicture}",
    ])


def cost_figure(cs_: dict) -> str:
    rows = cs_["rows"]
    def line(arm: str, style: str) -> str:
        pts = " ".join(f"({r['critical_miss_cost']},{r['loss'][arm]})" for r in rows)
        return f"\\addplot[{style}] coordinates {{{pts}}};"
    cross = cs_["exact_crossover_critical_cost"]
    return "\n".join([
        r"\begin{tikzpicture}",
        r"\begin{axis}[xmode=log, width=0.92\linewidth, height=5.4cm, xlabel={cost of a missed CRITICAL defect (shipped profile: "
        + f"{cs_['shipped_value']:.0f})" + r"},",
        r"  ylabel={expected loss}, ymin=0, xmajorgrids, ymajorgrids, legend pos=north west, legend style={font=\scriptsize}]",
        line("flag_everything", "thick, dashed"),
        line("assay", "thick, mark=*, mark size=1.4pt"),
        line("assay+auditor", "thick, dotted, mark=square*, mark size=1.2pt"),
        f"\\draw[black!60] (axis cs:{cross:.0f},0) -- (axis cs:{cross:.0f},{max(r['loss']['flag_everything'] for r in rows):.0f});",
        r"\legend{\texttt{flag\_everything}, \textsc{Assay}, \textsc{Assay}+auditor (one draw)}",
        r"\end{axis}",
        r"\end{tikzpicture}",
    ])


def gate_figure(values: list[float]) -> str:
    pts = " ".join(f"({i + 1},{v})" for i, v in enumerate(values))
    return "\n".join([
        r"\begin{tikzpicture}",
        r"\begin{axis}[ybar, width=0.8\linewidth, height=4.6cm, xlabel={run (identical corpus, identical code)},",
        r"  ylabel={loss saved vs.\ \textsc{Assay}}, xtick={1,...,7}, ymajorgrids, bar width=14pt, enlarge x limits=0.1]",
        r"\addplot[fill=black!45] coordinates {" + pts + "};",
        r"\draw[black] (axis cs:0.4,0) -- (axis cs:7.6,0);",
        r"\end{axis}",
        r"\end{tikzpicture}",
    ])


def write(name: str, text: str) -> None:
    text = re.sub(r"(?<=[\[ ])-(?=\d)", "$-$", text)
    _files[name] = text.rstrip("\n") + "\n"


_files: dict[str, str] = {}


def build() -> dict[str, str]:
    _macros.clear()
    _files.clear()
    macros_from_results()
    fr, iv = load("full_run.json"), load("intervals.json")
    _files["fig_arms.tex"] = arms_figure(fr, iv) + "\n"
    body = ["% GENERATED by scripts/export_paper_tables.py from results/*.json. Do not edit.",
            "% Every result-derived number in paper/assay.tex is one of these macros."]
    for k in sorted(_macros):
        body.append(f"\\newcommand{{\\{k}}}{{{_macros[k]}}}")
    _files["numbers.tex"] = "\n".join(body) + "\n"
    return dict(_files)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files = build()
    if args.check:
        stale = [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != t]
        extra = [p.name for p in OUT.glob("*.tex") if p.name not in files] if OUT.exists() else []
        if stale or extra:
            print(f"paper/generated is stale: {stale + extra}; run scripts/export_paper_tables.py", file=sys.stderr)
            return 1
        print("paper/generated is up to date")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("*.tex"):
        p.unlink()
    for n, t in files.items():
        (OUT / n).write_text(t)
    print(f"wrote {len(files)} files, {len(_macros)} macros to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
