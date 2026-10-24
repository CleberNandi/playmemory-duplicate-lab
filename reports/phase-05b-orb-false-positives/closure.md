# Phase 05B closure — 2026-10-23

> Update 2026-10-24: [raw-evidence-audit.md](raw-evidence-audit.md) records receipt,
> hash verification, JSON comparison and inspection of all six diagnostic PNGs.
> Statements below about unavailable raw artifacts describe the original closure.

**Decision: PASS WITH RESERVATIONS.** The two false confirmations are identified
and their supplied measurements are preserved. Evidence consolidation is complete.
This does not certify capture identity or qualify ORB for retention decisions.

An initial GitHub HTTP 403 blocked publication. After the user granted access,
creation of the investigation branch succeeded. This report is the closure record
prepared for publication as one documentation-only commit on that branch.

## Git provenance and scope

- Repository: `CleberNandi/playmemory-duplicate-lab`.
- Verified production base: `96b214475dc56fa4e828f9c0bf9eb3b3b6db3a3f`.
- Verified experimental reference: `b9bf4a10bbef4aac14a5945ce9bd0f7dfeecb627`.
- The investigation branch was absent remotely during the initial audit.
- Consolidation branch: `investigation/orb-mutual-false-positives`, created from
  the verified production base. The inaccessible workstation branch is not
  asserted to have the same history; no workstation work was overwritten.
- Only this report directory is added. Experimental code is referenced at its
  frozen commit, without integration into production. No corpus was available
  or modified; no thresholds, retention rules or application code changed.

## Imported evidence and integrity

Source package: `playmemories-phase-05b-evidence.tar.gz` (5,096 bytes).
SHA-256: `315346df0aa249980148ee5b537b89cebaa8bdec5bc69d1b95bf6cddf1b86f36`.
Archive inspection found exactly two regular files, no links, absolute paths,
parent traversal or special entries; extraction used the Python data filter.
These hashes identify received bytes, not an independently signed source.

`measurements.json` is preserved byte-for-byte from the package, SHA-256:
`5f0e426a817ad02a77ae0abf180c2d50bd1c709183634f60c3fb85dbdbe657be`.
The imported README is retained with a pointer to this closure record.

The supplied JSON contains paths, four image hashes, matching parameters,
direct and reciprocal counts, direct and mutual-only homographies, coverage
and reprojection diagnostics for these pairs:

| Query | Candidate | Ground-truth class | Direct / mutual matches | Direct / mutual-only inliers |
|---|---|---|---|---|
| `strong/214902.jpg` | `original/202600.jpg` | FP | 41 / 23 | 28 / 19 |
| `strong/214902.jpg` | `original/207800.jpg` | FP | 38 / 18 | 24 / 16 |
| `strong/214902.jpg` | `original/214900.jpg` | TP | 124 / 87 | 108 / 84 |

All three mutual-only homographies were reported plausible. Visual observations
in the imported report are prior investigator observations, not images inspected
again in this consolidation. Shared depicted content is strongly supported by
that record, but exact region provenance remains a hypothesis.

## Executed validation

- Clean initial checkout at the verified production base; remote branch list
  and experimental history/tree inspected. No existing report was replaced.
- JSON parsed; count bounds, inlier ratios, symmetric-error arithmetic and
  finite 3-by-3 matrices checked successfully.
- All four recorded image hashes match `source_integrity.before` in
  `reports/experiment-04-geometric-verification/experiment-04.json` at the
  experimental commit. This verifies agreement between records, not image bytes.
- Verification configuration exactly matches that report's selected configuration.
- Original query row confirms 285 candidates, 3 mutual confirmations and the
  expected original accepted. Aggregate evaluation records 2 false-positive
  pairs across 151 positive queries; the targeted three-pair record is not a
  replacement for that full evaluation.
- `uv run pytest -q`: exit 0, 70 tests passed on the production-base code.
- `uv run ruff check .`: exit 0, all checks passed.
- Runtime for these checks: CPython 3.13.16, project dependencies from `uv.lock`.
  These tests do not execute the frozen experimental ORB code or reproduce its
  reported OpenCV 5.0.0 environment.
- Final staged `git diff --check` and documentation-only scope review passed.

## Reservations and reproduction boundaries

The raw `orb-mutual-confirmations.json`, `geometry-comparison.json` and six
direct/mutual PNGs from the workstation were not present in the imported package.
They were neither reconstructed nor published. Source photographs, the complete
285-file database and the standalone diagnostic generation script are absent.
The README gives procedural reproduction guidance against the frozen experimental
code; it is not a self-contained executable reproduction package. Exact reruns
also require the original corpus, dependency versions and runtime settings.

Consequently, no fresh ORB evaluation, pixel inspection, independent verification
of source file bytes, or full-corpus mitigation benchmark was performed here.
Raw diagnostic metrics cannot be independently corroborated beyond internal
consistency and the original report's hashes, configuration and aggregate counts.

`confirms_mutual()` uses reciprocal match count plus `confirms_current()`;
`analyze_pair()` fits geometry to forward ratio matches. Code inspection confirms
this distinction. Plausibility is a separate diagnostic, not an additional
plausibility gate in `confirms_mutual()`. Inlier bounding-box coverage also differs
from all-match coverage used by `confirms_current()`; low inlier coverage alone
does not contradict a mutual acceptance. Mutual-only RANSAC did not resolve
the two reported false confirmations.

Binary equality, visual similarity, partial correspondence, capture identity
and human retention choice remain separate concepts. Geometric consistency
does not establish capture identity. Increasing coverage or inlier thresholds
from these two examples risks overfitting and loss of genuine cropped matches.

## Next phase recommendation

Prepare a separately approved evaluation protocol distinguishing partial visual
correspondence from capture identity, with genuine crops and identity-disjoint
calibration/evaluation sets. Preserve raw diagnostics privately for later audit.
Do not tune thresholds or implement that next phase as part of 05B.
