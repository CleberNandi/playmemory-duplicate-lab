# Phase 05B — ORB mutual: investigation of false confirmations

> Raw artifacts received and audited on 2026-10-24: see
> [raw-evidence-audit.md](raw-evidence-audit.md). Their previous unavailability
> is resolved; source-corpus and independent-reproduction limits remain.

> Consolidated on 2026-10-23. See [closure.md](closure.md) for the final audit,
> executed validations and remaining reservations. Pending gates below describe
> the imported investigation record, before this consolidation.

**State:** targeted reproduction and diagnostic inspection completed; no production change or authorization of deletion.

## Grounded result

Reference query: `strong/214902.jpg`; expected source capture: `original/214900.jpg`. The evaluation database included 157 originals + 128 held-out distractors (285 candidates). The recorded outcome reproduced the original benchmark count: 1 true confirmation and 2 false confirmations. Exact candidates: `original/202600.jpg` (FP-01) and `original/207800.jpg` (FP-02).

| Pair | Direct matches | Mutual matches | Direct inliers | Mutual among direct inliers | Mutual-only RANSAC inliers | Query inlier bounding-box coverage | Query grid cells | Direct symmetric reprojection error | Plausible mutual homography |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| FP-01 (202600) | 41 | 23 | 28 | 20 | 19 | 2.79% | 3 | 1.1712 px | yes |
| FP-02 (207800) | 38 | 18 | 24 | 16 | 16 | 1.07% | 2 | 0.9939 px | yes |
| TP (214900) | 124 | 87 | 108 | 86 | 84 | 16.67% | 6 | 1.1141 px | yes |

All original direct homographies and all mutual-only diagnostic homographies were marked plausible by the implementation's checks. Re-estimating the homography using only reciprocal matches did **not** reject either false confirmation. The original `confirms_mutual()` requires 8 mutual matches but `confirms_current()` checks geometry estimated from forward ratio matches; this is a semantic mismatch between its label and its geometric basis, not proof of an implementation bug.

## Visual observations, explicitly separated from proof

The user-provided side-by-side diagnostic sheets show the query as a multi-image composition. FP-01 matches occupy a small portion showing architecture; FP-02 matches occupy a small portion showing tiered seating. The TP matches occupy a larger region showing trees. These are observed **partial visual correspondences**. The record does not establish pixel identity, image provenance, or equality of capture. The distinction between visual correspondence and capture identity is essential.

## Interpretation

- **Observed:** strong, geometrically coherent local matches can exist between different Copydays original capture IDs. Forward/backward reprojection error alone fails to discriminate these three cases; FP-02 had a lower symmetric error than the TP.
- **Observed:** mutual-only RANSAC remains numerically plausible for both false confirmations.
- **Hypothesis:** compositing/overlapping scene content permits a small matched region to satisfy local geometric consistency.
- **Not demonstrated:** robust general suppression using a higher spatial coverage or minimum-inlier threshold; any such change needs separate corpus-wide evaluation and calibration/test separation.

The quoted coverage numbers are **axis-aligned bounding rectangle coverage of matched inlier keypoint locations in the query**, not exact image-area overlap or segmentation. Do not interpret them as a percentage of image pixels shared.

## Reproduce locally (no photo changes)

1. Preserve the source image corpus and the frozen experimental ref `b9bf4a1`. Record full SHA-256 of the query and all candidates against `measurements.json`.
2. Use ORB configuration and geometric-verification configuration from `measurements.json`. Environment reported OpenCV 5.0.0, seed 202503; same library version/hardware settings should be recorded for a strict reproduction.
3. Construct evaluation database with all `original/*.jpg` and the held-out 128 `database/*.png` distractors using `_split_distractors()` from the frozen experimental ref. Assert database count equals 285.
4. Extract ORB features with `ORBConfig(nfeatures=1800, fast_threshold=12)` and run `analyze_pair(query, candidate, VerificationConfig())` on all 285 pairs. Record each `confirms_mutual()` decision. Expect 3 accepted: two FP paths and one TP path listed above.
5. For those three pairs, compute the direct homography from forward ratio matches (as original) and the independent diagnostic homography from reciprocal ratio matches (`cv2.findHomography(..., cv2.RANSAC, 4.0)`, calling `cv2.setRNGSeed(202503)` first), then compare inliers and plausibility with `measurements.json`.
6. Keep diagnostic images under an ignored local directory only. The screenshots were deliberately omitted from this public-repo deliverable to avoid redistributing third-party dataset imagery without licensing review.

## Gates, constraints and open items

- Gate SHA integration: PASS (local `main` at `96b2144`; 70 pytest PASS and Ruff PASS reported by operator).
- Targeted reproduction: PASS (3 confirmed, 1 TP and 2 FP); **not** an independent full-dataset reevaluation.
- Pair diagnostics: PASS for 3 pairs, OpenCV 5.0.0.
- Full source hash manifest check: PENDING.
- Human inspection of pixel provenance: PENDING.
- Full holdout benchmark of any future mitigation: NOT RUN.
- Regression tests of new code, final Git diff review and commit: PENDING until done in local checkout.
- Risk: a spatial-coverage constraint may reject genuine crops; avoid calibrating on only these known false positives.
- Never promote ORB to same-capture proof, retention selection, movement, or deletion.

No geometry or threshold modification is recommended for production in 05B. Next phase should design a **separate**, pre-registered comparison of partial-correspondence semantics and genuine cropped-duplicate recall.
