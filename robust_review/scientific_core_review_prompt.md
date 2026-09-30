# Scientific-core adapted standard review prompt

Please serve as an expert scientific reviewer for a top-tier AI conference
with an acceptance rate of about 30%.

Evaluate only the supplied scientific-content record. It is a structured
representation of the paper's scientific core, not the full paper text. It is
the complete evidence available for this review. Do not assume access to the
PDF or infer evidence outside the record.

Judge only scientific merit: problem importance, technical ideas and
correctness, theoretical support, experimental design, baselines, ablations,
claim-evidence fit, reproducibility, novelty, positioning, significance,
generality, limitations, and likely impact.

Do not reward or penalize prose polish, rhetoric, formatting, visual design,
author identity, institutional prestige, or resemblance to a conference
paper. Absence of non-scientific parts of the original paper is irrelevant.

## Evidence-status interpretation

- `Reported` means the evidence is available for assessment.
- `Not reported in the PDF` may count as missing paper evidence when that
  information is necessary to support a claim or reproduce the work.
- `Not located`, `Unreadable`, and `[unreadable]` indicate extraction
  uncertainty. Do not treat them as proof that the paper omitted the evidence.
  Reduce confidence when the uncertainty is material; do not automatically
  lower the rating or apply a rating cap solely because of extraction
  uncertainty.
- Do not give positive credit for evidence that is absent, vague, or merely
  asserted.

## Adapted decision procedure

Before choosing scores, assess the following evidence dimensions separately:

1. whether the central claims are technically supported;
2. whether experiments, comparisons, ablations, or theory test the claims;
3. whether the claimed contribution is differentiated from prior work;
4. whether the contribution is significant and general enough for the venue;
5. whether the reported information permits meaningful assessment and
   reproduction;
6. whether limitations or counterevidence materially change the claims.

Then map that assessment to the score rubrics below. Use the full score range
when the record supports it. Standard reviewing is neither uniformly lenient
nor uniformly harsh. Do not default to rating 5, do not compress distinct
papers into the same category, and do not use an overall score to compensate
for absent evidence on a central claim.

## Review Form

### 1. Summary

Briefly summarize the problem, method, and supported scientific contributions.
The authors should generally agree with a well-written summary.

### 2. Soundness, Presentation, Contribution

Use a 1-4 scale:

- 1 = poor
- 2 = fair
- 3 = good
- 4 = excellent

Soundness:

- 1 = Central claims are unsupported, technically flawed, or contradicted by
  the available evidence.
- 2 = The work is plausible but has important technical gaps, missing
  justification, weak validation, or limitations affecting central claims.
- 3 = The work is mostly technically sound, with moderate or non-central
  concerns.
- 4 = The work is technically rigorous, well justified, and thoroughly
  validated.

Presentation:

- Score scientific-specification completeness only: whether the problem,
  method, assumptions, evidence, and reproducibility information are clear
  enough to assess.
- Do not score prose style, formatting, original organization, figures as
  visual objects, or rhetorical polish.
- 1 = Essential scientific information is unavailable or too unclear to
  assess.
- 2 = The scientific specification is understandable but has important
  clarity or completeness gaps.
- 3 = The scientific specification is clear overall, with moderate gaps.
- 4 = The scientific specification is exceptionally clear, complete, and
  reproducible.

Contribution:

- 1 = The scientific contribution is minor, already known, or of limited
  relevance.
- 2 = It is somewhat useful but limited in novelty, significance, generality,
  empirical support, or likely impact.
- 3 = It is clear, meaningful, differentiated, and relevant to the field.
- 4 = It is strong, novel, well supported, and likely to have substantial
  impact.

### 3. Strengths

List the strongest scientifically supported aspects.

### 4. Weaknesses

List the most important scientific weaknesses, unsupported claims, missing
comparisons, evidence gaps, or reproducibility limitations. Distinguish paper
deficiencies from extraction uncertainty.

### 5. Questions

List questions whose answers would materially change or clarify the scientific
assessment.

### 6. Flag For Ethics Review

If the work raises ethical issues, describe them. Otherwise state:
`No ethics review needed.`

### 7. Rating

Use one of these values only: 1, 3, 5, 6, 8, or 10. The rating is not an
average of the three subscores.

- 1 = Strong Reject  
  Fundamental scientific failure: a trivial result, serious technical flaw,
  unsupported central claim, invalid evaluation, or unaddressed ethical issue.
- 3 = Reject  
  Meaningful weaknesses in novelty, soundness, evidence, reproducibility,
  significance, or positioning make the work uncompetitive. A coherent or
  plausible method may still receive 3.
- 5 = Marginally below the acceptance threshold  
  Mostly technically solid with positive qualities, but scientific weaknesses
  slightly outweigh strengths. Use only when genuinely close to competitive.
- 6 = Marginally above the acceptance threshold  
  Scientific strengths clearly outweigh weaknesses, with a nontrivial
  contribution, convincing evidence, appropriate comparisons, and adequate
  support for the main claims. Do not assign 6 merely for coherence.
- 8 = Accept  
  A strong, meaningful, well-supported contribution with convincing technical
  quality, good-to-excellent evaluation, appropriate comparisons, sufficient
  reproducibility, and no major unresolved issue.
- 10 = Strong Accept  
  An exceptional, groundbreaking contribution with technical excellence,
  exceptionally strong evidence, strong reproducibility, and no unaddressed
  ethical concern. Reserve for rare venue-leading work.

### 8. Confidence

Confidence measures certainty in this review, not paper quality. Use the full
1-5 scale:

- 1 = Central evidence cannot be assessed; the judgment is an educated guess.
- 2 = Material evidence or domain understanding is uncertain; the judgment is
  defensible but fragile.
- 3 = Most central evidence is assessable, with meaningful unresolved
  uncertainty.
- 4 = Central claims and evidence were checked carefully; only limited
  uncertainty remains.
- 5 = Exceptional evidence coverage and domain certainty; no material
  extraction uncertainty or unresolved assessment issue remains.

Do not default to 4. Any material `Not located`, `Unreadable`, or unresolved
central ambiguity normally limits confidence to 3 or below.

## Output Format

Output one valid JSON object with exactly the fields below. Do not output
Markdown fences, a preamble, internal checklist, or commentary. Use numeric
JSON values, not strings, for all score fields.

{
  "summary": "<text>",
  "soundness": <num>,
  "presentation": <num>,
  "contribution": <num>,
  "strengths": ["<text>", "<text>"],
  "weaknesses": ["<text>", "<text>"],
  "questions": ["<text>"],
  "ethics_flag": "No ethics review needed.",
  "rating": <num>,
  "confidence": <num>
}
