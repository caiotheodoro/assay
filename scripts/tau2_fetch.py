"""Download the two pinned tau2-bench snapshots this measurement is scored on.

Neither snapshot is committed. tau2-bench is MIT and tau2-bench-verified is
Apache-2.0, so redistribution would be permitted -- but the rule this repo has
followed for inspect_evals, OpenEnv and ScienceAgentBench is that a verdict
about someone else's benchmark ships and a copy of it does not, and there is no
reason to make an exception for the one benchmark that happens to be permissive.
The cache directory is gitignored; this script is what makes the run
reproducible.

    uv run --extra tau2 python scripts/tau2_fetch.py

Downloads a ~53 MB source tarball and keeps the part the audit needs: the
`tau2` package (so the probes drive the real environment and the real
deterministic evaluators, not a reimplementation of them) and the retail and
airline data. Then the verified fork's task files and FIXES.md.
"""

from __future__ import annotations

import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assay.tau2_truth import (  # noqa: E402
    BASE_REPO,
    BASE_REV,
    DOMAINS,
    VERIFIED_REPO,
    VERIFIED_REV,
    cache_dir,
    tau2_source_root,
    verified_dir,
)

RAW = "https://raw.githubusercontent.com/{repo}/{rev}/{path}"
TARBALL = "https://codeload.github.com/{repo}/tar.gz/{rev}"


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as resp:  # noqa: S310
        return resp.read()


def _wanted(name: str) -> bool:
    """The package, and only the two domains this measurement scores.

    tau2-bench also ships telecom, whose task file alone is 14 MB. Unpacking it
    would triple the cache for data no probe here reads.
    """
    parts = name.split("/")[1:]  # drop the tarball's top-level directory
    if parts[:2] == ["src", "tau2"]:
        return True
    if parts[:3] == ["data", "tau2", "domains"] and len(parts) > 3:
        return parts[3] in DOMAINS
    return False


def _unpack_source(out: Path) -> None:
    url = TARBALL.format(repo=BASE_REPO, rev=BASE_REV)
    print(f"  fetching {url}")
    blob = _fetch(url)
    print(f"  {len(blob):,} bytes")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if _wanted(m.name)]
        for member in members:
            member.name = member.name.split("/", 1)[1]
            tar.extract(member, out, filter="data")
    print(f"  extracted {len(members)} paths into {out}")


def main() -> int:
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    print(f"cache: {cache}")

    print(f"{BASE_REPO}@{BASE_REV[:10]}  (pre-fix task set + runnable environment)")
    _unpack_source(tau2_source_root())

    print(f"{VERIFIED_REPO}@{VERIFIED_REV[:10]}  (post-fix task set + FIXES.md)")
    ver = verified_dir()
    ver.mkdir(parents=True, exist_ok=True)
    for domain in DOMAINS:
        blob = _fetch(
            RAW.format(
                repo=VERIFIED_REPO,
                rev=VERIFIED_REV,
                path=f"data/tau2/domains/{domain}/tasks.json",
            )
        )
        (ver / f"{domain}-tasks.json").write_bytes(blob)
        print(f"  {domain}-tasks.json {len(blob):>10,} bytes")
    blob = _fetch(RAW.format(repo=VERIFIED_REPO, rev=VERIFIED_REV, path="FIXES.md"))
    (ver / "FIXES.md").write_bytes(blob)
    print(f"  FIXES.md {len(blob):>16,} bytes")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
