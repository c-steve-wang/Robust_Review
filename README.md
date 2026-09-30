# RobustReview: Benchmarking Rhetorical Robustness in AI Peer Review

This repository contains the benchmark data layout and evaluation code for **RobustReview**, a controlled full-manuscript benchmark for measuring whether AI reviewers remain stable under content-preserving rhetorical rewrites while continuing to distinguish among scientifically different papers. It also contains **SciCore**, a dual-branch review method that combines a full-manuscript review with a review of a structured scientific-content record.

The project accompanies the paper:

**A Missing Piece for Trustworthy AI Reviewers: From Benchmarking Rhetorical Robustness to SciCore Review**  
Chenguang Wang*, Ming Li*, Chengrui Fan, Jianpeng Chen, Han Chen, Tianyi Zhou, Dawei Zhou

## Contents

- [Overview](#overview)
- [Key Findings](#key-findings)
- [Setup](#setup)
- [Repository Layout](#repository-layout)
- [Data Organization](#data-organization)
- [Review Pipeline](#review-pipeline)
- [Evaluation from Review Results](#evaluation-from-review-results)
- [Output Files](#output-files)
- [Citation](#citation)

## Overview

RobustReview evaluates rhetorical robustness through matched paper families. Each family contains an original manuscript and rhetorical variants designed to preserve its reported scientific content. Comparisons within a family measure rewrite-induced score changes, while comparisons across families test whether stability is retained without collapsing distinctions among papers.

The released benchmark data contains:

- 38 ICLR 2026 source papers;
- 10 rhetorical rewrite conditions;
- two independently generated rewrites per condition;
- 38 original manuscripts and 760 rewritten manuscripts;
- human review scores for soundness, presentation, contribution, overall assessment, and confidence.

The 10 conditions cover novelty stance, scope framing, evidence framing, contribution salience, technical register, linguistic complexity, a compound rewrite, two recursive rewrite settings, and a reviewer-guided rewrite. Each condition has one GPT-5.5 rewrite and one Claude Opus 4.8 rewrite.

The full dataset used in the paper cannot currently be released in full because redistribution rights for some source papers have not been secured.

The released families are unevenly distributed across six human-score intervals (6, 9, 10, 2, 8, and 3 papers from lowest to highest). Results computed with this repository describe these 38 families. The PDFs are under `papers/`; paper sources and licenses are documented in [data/DATA_LICENSES.md](data/DATA_LICENSES.md).

## Key Findings

The accompanying paper reports:

- Low rewrite-induced score drift does not by itself establish robustness; a reviewer can appear stable because its scores collapse across papers.
- No evaluated reviewer configuration is consistently robust across rhetorical conditions, model backbones, and review protocols.
- Human alignment and rhetorical robustness are distinct evaluation targets and can rank reviewer configurations differently.
- SciCore achieves a leading joint stability-discrimination profile in the primary comparison while retaining competitive human alignment.
- Combining the manuscript and science-core branches preserves manuscript-level assessment while reducing dependence on rhetorical realization.

## Setup

The review scripts require Python 3.10 or later.

After cloning the repository, create an environment and install the Python requirements:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set the API key for the provider you plan to use:

```bash
export OPENAI_API_KEY=...
export OPENROUTER_API_KEY=...
```

Only the corresponding key is required for a given run. The runtime uses only Python's standard library.

Code is licensed under [MIT](LICENSE). Data has separate per-paper terms; see [data/DATA_LICENSES.md](data/DATA_LICENSES.md).

## Repository Layout

```text
.
├── README.md
├── requirements.txt
├── data/
│   ├── meta.json
│   ├── released_paper_ids.json
│   ├── paper_licenses.json
│   ├── dataset_manifest.json
│   ├── ATTRIBUTION.md
│   └── DATA_LICENSES.md
├── papers/
│   ├── 1/
│   │   ├── original.pdf
│   │   └── rewrites/
│   │       ├── condition_01.pdf
│   │       ├── condition_02.pdf
│   │       └── ...
│   ├── 2/
│   └── ...
├── baseline_review/
│   ├── build_iclr_review_prompt.py
│   ├── review_pdf_scores_openai.py
│   ├── review_prompt_bank.md
│   └── run_baseline_review.py
├── robust_review/
│   ├── fuse_reviews.py
│   ├── run_robust_review.py
│   ├── scientific_content_prompt.md
│   └── scientific_core_review_prompt.md
└── utility/
    └── evaluate_review_results.py
```

## Data Organization

### Metadata

`data/meta.json` contains one record for each of the 38 publicly released source papers. Every record includes:

- a numeric benchmark `paper_id` from 1 to 38;
- the versioned arXiv identifier;
- arXiv abstract, PDF, and LaTeX source URLs;
- the corresponding OpenReview forum URL;
- title, venue, and decision metadata;
- individual human review scores;
- paper-level mean human scores.

The file also contains a `rewrite_conditions` table that maps each `condition_XX.pdf` filename to its rhetorical condition and rewrite producer.

### PDF files

The released PDFs follow this layout:

```text
papers/<paper_id>/
├── original.pdf
└── rewrites/
    ├── condition_01.pdf
    ├── condition_02.pdf
    ├── ...
    └── condition_20.pdf
```

The included PDFs use paper IDs `1` through `38`. Each directory contains one original manuscript and 20 rewrites.

## Review Pipeline

### Example 1: Quick baseline review

Review one original manuscript with GLM-5.2 and the paper's `high` reasoning setting:

```bash
python3 baseline_review/run_baseline_review.py \
  --provider openrouter --model z-ai/glm-5.2 --reasoning-effort high \
  --template standard --pdf-dir papers --pdf-glob '*/original.pdf' \
  --limit 1 --output-dir results/quick_check
```

This checks the API workflow; it does not produce a complete evaluation panel.

### Example 2: Complete baseline and SciCore evaluation

Run this from the repository root using the included PDFs under `papers/`. It scores all 21 versions of each of the 38 available papers, fuses SciCore's Strict manuscript and science-core ratings with equal weights, and evaluates both methods.

```bash
set -euo pipefail
provider=openai
model=gpt-5.5
reasoning=()
run_dir=results/gpt55_release

python3 utility/verify_dataset.py --papers-dir papers

for template in standard strict; do
  python3 baseline_review/run_baseline_review.py \
    --provider "$provider" --model "$model" "${reasoning[@]}" \
    --template "$template" --pdf-dir papers --pdf-glob '**/*.pdf' --limit 0 \
    --output-dir "$run_dir/$template"
done

python3 robust_review/run_robust_review.py \
  --provider "$provider" --model "$model" "${reasoning[@]}" \
  --pdf-dir papers --pdf-glob '**/*.pdf' --limit 0 \
  --output-dir "$run_dir/science_core"

python3 robust_review/fuse_reviews.py \
  --strict-reviews "$run_dir/strict/reviews.jsonl" \
  --science-core-dir "$run_dir/science_core" \
  --output "$run_dir/scicore_fused.jsonl" --require-complete

python3 utility/evaluate_review_results.py \
  "$run_dir/standard/reviews.jsonl" \
  --paper-id-file data/released_paper_ids.json --require-complete \
  --output-dir "$run_dir/evaluation/standard"

python3 utility/evaluate_review_results.py \
  "$run_dir/scicore_fused.jsonl" \
  --paper-id-file data/released_paper_ids.json --require-complete \
  --output-dir "$run_dir/evaluation/scicore"
```

For the paper's OpenRouter models, set `provider=openrouter`, choose `model=z-ai/glm-5.2`, `moonshotai/kimi-k2.6`, or `openai/gpt-oss-120b`, and set `reasoning=(--reasoning-effort high)`. Use a separate `run_dir` for each configuration. OpenAI runs leave reasoning at the provider default.

## Evaluation from Review Results

`utility/evaluate_review_results.py` computes the seven benchmark metrics directly from completed review results. It reads the saved ratings and `data/meta.json`; it does not call an API or inspect the PDFs.

The script accepts one or more result files or directories. It reads baseline scores from `model_rating`, science-core scores from `review.rating`, and fused SciCore scores from `robust_review_rating`. The score field is detected automatically, or it can be selected with `--rating-field`.

Each evaluated configuration uses the original score and 20 matched rewrite scores. The default metadata selects the 38 released papers; use `--paper-id-file data/released_paper_ids.json` to declare this paper set explicitly, or repeat `--paper-id` for a smaller experiment. Evaluation now requires a complete score panel by default and reports an error if a selected paper has a missing or failed score. The complete example above passes `--require-complete` explicitly.

Use `--allow-incomplete` only for exploratory analysis. In this mode, MAD, Drift SD, and rewrite mean squared drift pool all observed original–rewrite pairs. SPR uses the variance across distinct original papers with at least one valid pair, counting each original once, divided by that variance plus the pooled mean squared drift. ICC and discriminability use complete paper blocks only. These metrics can describe different paper sets and must be labeled as incomplete-panel estimates. Missing counts remain in the output; metrics without enough observations are `null`, not zero. ICC is also `null` when its denominator is zero, matching the paper's undefined case.

SciCore saves the same configuration information on successful and failed attempts. Older failed records without a configuration fingerprint can also be evaluated as missing cells; known configuration conflicts still cause an error. An interrupted attempt in either review branch does not hide an earlier completed success for the same PDF and configuration; a completed failed rerun still supersedes it. Rerun the same scoring command without `--force` to reuse successful caches and retry failed work. Evaluation can also proceed directly using the available scores.

The reported metrics are:

- `mad`: mean absolute original-to-rewrite score change, lower is better;
- `drift_sd`: population standard deviation of all signed original-to-rewrite score changes, including variation of condition means, lower is better;
- `icc_a1`: two-way mixed-effects, absolute-agreement, single-measure ICC across the original and rewrites, higher is better;
- `spr`: original-paper score variance divided by that variance plus mean squared rewrite drift, reported on the 0–1 scale, higher is better;
- `discriminability`: probability that a within-paper presentation pair is closer in score than a between-paper pair, with ties worth one half, higher is better;
- `human_mae`: mean absolute error between original-paper ratings and mean human overall-assessment scores, lower is better;
- `human_spearman`: Spearman correlation between original-paper ratings and mean human overall-assessment scores, higher is better.

`human_spearman` is `null` in JSON (blank in CSV) when fewer than two paired original scores are available, or when the model or human scores are constant. `human_spearman_undefined_reason` records the cause and is `null` when the correlation is defined. A mathematically defined zero correlation remains `0`.

Drift SD uses population normalization (`ddof=0`). Complete panels give every paper/variant pair equal weight.

## Output Files

Typical baseline outputs include:

- review records: `results/baseline_review/<provider>/<model>/<template>/reviews.jsonl`
- score table: `results/baseline_review/<provider>/<model>/<template>/summary.csv`
- aggregate error metrics: `results/baseline_review/<provider>/<model>/<template>/metrics.json`

Typical science-core outputs include:

- extracted records: `results/scicore_branch/**/scientific_content.md`
- extraction metadata: `results/scicore_branch/**/scientific_content.meta.json`
- science-core reviews: `results/scicore_branch/**/reviews/science_core.json`
- fused reviews: `results/scicore_fused.jsonl`

Metric evaluation produces:

- aggregate metrics and provenance: `results/evaluation/<run>/metrics.json`
- one-row metric table: `results/evaluation/<run>/metrics.csv`
- original and rewrite score matrix: `results/evaluation/<run>/paper_scores.csv`

## Citation

If you use this repository, please cite:

```bibtex
@misc{wang2026robustreview,
  title = {A Missing Piece for Trustworthy AI Reviewers: From Benchmarking Rhetorical Robustness to SciCore Review},
  author = {Wang, Chenguang and Li, Ming and Fan, Chengrui and Chen, Jianpeng and Chen, Han and Zhou, Tianyi and Zhou, Dawei},
  year = {2026}
}
```
