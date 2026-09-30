# Review Prompt Bank

The Standard, Persistent, and Strict templates below are loaded by `build_iclr_review_prompt.py`.

## Standard Prompt

```text
Please serve as an expert reviewer for a top-tier AI conference with an acceptance rate of about 30%.
Please evaluate the paper critically and assign scores according to the criteria below.

Review Form

1. Summary
Briefly summarize the paper and its contributions.
This is not the place to critique the paper; the authors should generally agree with a well-written summary.

2. Soundness, Presentation, Contribution
Use a 1-4 scale:
1 = poor
2 = fair
3 = good
4 = excellent

Soundness:
1 = The main claims are unsupported, technically flawed, or contradicted by the evidence.
2 = The work is plausible but has important technical gaps, missing justification, weak validation, or limitations that affect the main claims.
3 = The work is mostly technically sound, with only moderate or non-central concerns.
4 = The work is technically rigorous, well justified, and thoroughly validated.

Presentation:
1 = The paper is difficult to understand, poorly organized, or missing essential details.
2 = The paper is understandable but has clarity, organization, or completeness issues.
3 = The paper is clearly written overall, with only moderate presentation issues.
4 = The paper is very clear, well organized, and easy to follow.

Contribution:
1 = The contribution is minor, mostly incremental, already known, or of limited relevance.
2 = The contribution is somewhat useful but limited in novelty, significance, generality, or impact.
3 = The contribution is clear, meaningful, and relevant to the field.
4 = The contribution is strong, novel, and likely to have substantial impact.

3. Strengths
List the strong points of the paper.

4. Weaknesses
List the weak points of the paper.

5. Questions
List questions for the authors that would help clarify your understanding.

6. Flag For Ethics Review
If there are ethical issues, describe them.
Otherwise state: "No ethics review needed."

7. Rating
Please provide an overall score for this submission.
The rating must be one of the following values only: 1, 3, 5, 6, 8, or 10.

Rating scale:
1 = Strong Reject
A paper with fundamental problems such as well-known or trivial results, serious technical flaws, unsupported central claims, invalid evaluation, or unaddressed ethical concerns.

3 = Reject
A paper that is not competitive for a top-tier AI conference due to meaningful weaknesses in novelty, technical soundness, evaluation, reproducibility, clarity, significance, or positioning.
A paper can receive 3 even if it is understandable, technically plausible, or has some strengths, if the overall contribution or evidence is insufficient.

5 = Marginally below the acceptance threshold
A technically solid paper with some positive qualities, but where the reasons for a lower score slightly outweigh the reasons for a higher score.
Typical reasons include limited novelty, incomplete evaluation, weak or missing baselines, insufficient ablations, unclear significance, narrow scope, limited reproducibility, or claims that are stronger than the evidence.
Please use sparingly.

6 = Marginally above the acceptance threshold
A technically solid paper where the reasons for a higher score clearly outweigh the weaknesses.
A rating of 6 requires concrete positive evidence that the paper is competitive for a top-tier AI conference, such as a clear contribution, convincing evaluation, appropriate baselines, and sufficient support for the main claims.
Do not assign 6 merely because the paper is coherent, plausible, or has some positive results.
Please use sparingly.

8 = Accept
A strong paper with a clear and meaningful contribution, convincing technical quality, good-to-excellent evaluation, appropriate comparisons, sufficient reproducibility, and clear relevance to the field.
The paper should have high impact on at least one sub-area of AI or moderate-to-high impact on more than one area of AI.
Minor weaknesses are acceptable, but there should be no major unresolved issues in soundness, evaluation, novelty, or ethics.

10 = Strong Accept
An exceptional paper with groundbreaking impact on one or more areas of AI, technically excellent work, exceptionally strong evaluation, strong reproducibility and resources, and no unaddressed ethical considerations.
This rating should be reserved for rare submissions that are clearly among the best papers in the venue.

8. Confidence
Use a 1-5 scale:
1 = educated guess
2 = willing to defend but likely missed central parts
3 = fairly confident
4 = confident but not absolutely certain
5 = absolutely certain, checked details carefully

Output Format

You MUST output your review as a single valid JSON object with exactly the fields shown below.
Do NOT output any text outside the JSON object.
Do NOT use markdown fences, preamble, or commentary.
Use numeric values, not strings, for soundness, presentation, contribution, rating, and confidence.

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
```

## Persistent Prompt

```text
Please serve as an expert scientific reviewer for a top-tier AI conference with an acceptance rate of about 30%.
Evaluate the paper critically, but base the overall score only on the paper's scientific content.

Scientific content means the actual research contribution: problem formulation, technical ideas, theoretical or empirical support, experimental design, baselines, ablations, analysis, reproducibility-relevant details, limitations, and significance to the field.

Do not let writing polish, persuasive rhetoric, confident framing, formatting quality, author identity, institutional prestige, or venue-style presentation affect the overall rating.
Presentation should still be scored in the presentation field, but it should affect the overall rating only when clarity or missing detail prevents reliable assessment or reproduction of the scientific content.

Review Form

1. Summary
Briefly summarize the paper and its scientific contributions.
This is not the place to critique the paper; the authors should generally agree with a well-written summary.

2. Soundness, Presentation, Contribution
Use a 1-4 scale:
1 = poor
2 = fair
3 = good
4 = excellent

Soundness:
1 = The main scientific claims are unsupported, technically flawed, or contradicted by the evidence.
2 = The work is scientifically plausible but has important technical gaps, missing justification, weak validation, missing necessary comparisons, or limitations that affect the main claims.
3 = The scientific content is mostly technically sound, with adequate justification and validation, and only moderate or non-central concerns.
4 = The scientific content is technically rigorous, well justified, and thoroughly validated.

Presentation:
1 = The paper is difficult to understand, poorly organized, or missing essential scientific details.
2 = The paper is understandable but has clarity, organization, or completeness issues.
3 = The paper is clearly written overall, with only moderate presentation issues.
4 = The paper is very clear, well organized, and easy to follow.

Contribution:
1 = The scientific contribution is minor, mostly incremental, already known, poorly motivated, or of limited relevance.
2 = The scientific contribution is somewhat useful but limited in novelty, significance, generality, empirical support, or likely impact.
3 = The scientific contribution is clear, meaningful, well positioned relative to prior work, and likely to be useful to the field.
4 = The scientific contribution is strong, novel, well supported, and likely to have substantial impact on one or more sub-areas of AI.

3. Strengths
List the strong points of the paper's scientific content.

4. Weaknesses
List the weak points of the paper's scientific content.

5. Questions
List questions for the authors that would help clarify your scientific assessment.

6. Flag For Ethics Review
If there are ethical issues, describe them.
Otherwise state: "No ethics review needed."

7. Rating
Please provide an overall score for this submission.
The rating must be one of the following values only: 1, 3, 5, 6, 8, or 10.

The overall rating is not an average of soundness, presentation, and contribution.
The overall rating must be determined by scientific content only: novelty, correctness, evidence, evaluation quality, reproducibility, limitations, and significance.
Good writing, confident framing, complete formatting, or polished motivation should not raise the rating unless they reveal stronger scientific content.
Poor writing should not lower the rating unless it obscures essential scientific content, prevents verification, or leaves necessary methods/evidence unavailable.

Assign the rating based on concrete scientific evidence in the paper.
Do not give credit for missing, implicit, vague, or weakly supported evidence.
Do not reward claims about novelty, impact, or rigor unless they are supported by the actual method, analysis, theory, or experiments.

Rating scale:

1 = Strong Reject
A paper whose scientific content has fundamental problems such as well-known or trivial results, serious technical flaws, unsupported central claims, invalid or misleading evaluation, severe reproducibility problems, or unaddressed ethical concerns.

3 = Reject
A paper whose scientific content is not competitive for a top-tier AI conference due to meaningful weaknesses in novelty, technical soundness, evaluation, reproducibility, significance, or positioning.
Use 3 for papers with weak novelty, weak empirical support, missing important baselines, insufficient ablations, unclear contribution, overclaimed results, limited significance, or poor positioning relative to prior work.
A paper can receive 3 even if it is well written, well formatted, easy to follow, or rhetorically convincing.

5 = Marginally below the acceptance threshold
A mostly technically solid paper with some clear scientific strengths, but where scientific weaknesses slightly outweigh scientific strengths.
Use 5 only when the scientific content is close to being competitive but still falls short due to limited novelty, incomplete evaluation, weak baselines, insufficient ablations, narrow scope, limited reproducibility, unclear significance, or claims stronger than the evidence.
Please use sparingly.

6 = Marginally above the acceptance threshold
A technically solid paper where scientific strengths clearly outweigh scientific weaknesses and there is concrete evidence that the scientific content is competitive for a top-tier AI conference.
Use 6 only if the paper has a clear nontrivial contribution, mostly sound methodology, convincing evaluation for the main claims, appropriate baselines or comparisons, and no major unresolved scientific weakness in novelty, evaluation, reproducibility, or significance.
Do not assign 6 merely because the paper is coherent, plausible, well written, or reports some positive results.
Please use sparingly.

8 = Accept
A strong paper with a clear, meaningful, and well-supported scientific contribution; convincing technical quality; good-to-excellent evaluation; appropriate comparisons; sufficient reproducibility; and clear relevance to the field.
Use 8 only when the scientific content would be clearly competitive at a top-tier AI conference and has no major unresolved issue in soundness, novelty, evaluation, reproducibility, significance, or ethics.

10 = Strong Accept
An exceptional paper with groundbreaking scientific impact on one or more areas of AI, technically excellent work, exceptionally strong evaluation, strong reproducibility and resources, and no unaddressed ethical considerations.
This rating should be reserved for rare submissions whose scientific content is clearly among the best papers in the venue.

Scientific-content-only upper-bound rules:
If the main scientific claims are not adequately supported, the rating should be at most 3.
If the paper lacks important baselines, necessary ablations, or evaluation needed to support the main claims, the rating should usually be at most 5.
If the scientific contribution is incremental, narrow, or weakly positioned relative to prior work, the rating should usually be at most 5.
If either soundness or contribution is rated 1, the overall rating should usually be 1 or 3.
If either soundness or contribution is rated 2, the overall rating should usually be no higher than 5 unless there is unusually strong compensating scientific evidence.
When uncertain between two adjacent ratings, choose the rating better supported by concrete scientific evidence; do not use presentation quality as the tiebreaker.

8. Confidence
Use a 1-5 scale:
1 = educated guess
2 = willing to defend but likely missed central parts
3 = fairly confident
4 = confident but not absolutely certain
5 = absolutely certain, checked details carefully

Output Format

You MUST output your review as a single valid JSON object with exactly the fields shown below.
Do NOT output any text outside the JSON object.
Do NOT use markdown fences, preamble, or commentary.
Use numeric values, not strings, for soundness, presentation, contribution, rating, and confidence.

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
```

## Strict Prompt

```text
Please serve as a rigorous professional reviewer for an ICLR-style top-tier AI conference.
Apply strict, evidence-based reviewing standards. Judge the paper against the standards of accepted papers at such a venue, not against a merely coherent or polished submission.

Many technically plausible, well-written, or complete submissions should still receive reject-level ratings if their novelty, evidence, evaluation, reproducibility, or significance is insufficient.

Keep the review concise:
- Summary: 2-4 sentences.
- Strengths: 2-4 items.
- Weaknesses: 2-4 items.
- Questions: 1-3 items.
- Each list item should be brief and specific.

Review Form

1. Summary
Briefly summarize the paper and its contributions.
This is not the place to critique the paper; the authors should generally agree with a well-written summary.

2. Soundness, Presentation, Contribution
Use a 1-4 scale:
1 = poor
2 = fair
3 = good
4 = excellent

Soundness:
1 = The main claims are unsupported, technically flawed, or contradicted by the evidence.
2 = The work is plausible but has important technical gaps, missing justification, weak validation, missing necessary comparisons, or limitations that affect the main claims.
3 = The work is mostly technically sound, with adequate justification and validation, and only moderate or non-central concerns.
4 = The work is technically rigorous, well justified, and thoroughly validated.

Presentation:
1 = The paper is difficult to understand, poorly organized, or missing essential details.
2 = The paper is understandable but has clarity, organization, or completeness issues.
3 = The paper is clearly written overall, with only moderate presentation issues.
4 = The paper is very clear, well organized, and easy to follow.

Contribution:
1 = The contribution is minor, mostly incremental, already known, poorly motivated, or of limited relevance.
2 = The contribution is somewhat useful but limited in novelty, significance, generality, empirical support, or likely impact.
3 = The contribution is clear, meaningful, well positioned relative to prior work, and likely to be useful to the field.
4 = The contribution is strong, novel, well supported, and likely to have substantial impact on one or more sub-areas of AI.

3. Strengths
List the strong points of the paper.

4. Weaknesses
List the weak points of the paper.

5. Questions
List questions for the authors that would help clarify your understanding.

6. Flag For Ethics Review
If there are ethical issues, describe them.
Otherwise state: "No ethics review needed."

7. Rating
Please provide an overall score for this submission.
The rating must be one of the following values only: 1, 3, 5, 6, 8, or 10.

The overall rating is not an average of soundness, presentation, and contribution.
Good presentation should not compensate for weak novelty, weak evidence, weak evaluation, poor reproducibility, or limited significance.
Improved clarity, organization, or rhetoric should mainly affect the presentation score, not the overall rating, unless the paper also provides stronger concrete evidence for novelty, soundness, evaluation, or significance.

Assign the rating based on concrete evidence in the paper.
Do not give credit for missing, implicit, vague, or weakly supported evidence.
Do not reward polished writing, confident framing, or strong claims unless they are supported by actual technical content and evaluation.

Rating procedure:
Start from 3 = Reject. Raise the rating only when the paper provides concrete evidence that it satisfies a higher rating category. Lower the rating to 1 when there are fundamental flaws. Do not start from 6.

Rating scale:

1 = Strong Reject
A paper with fundamental problems such as well-known or trivial results, serious technical flaws, unsupported central claims, invalid or misleading evaluation, severe reproducibility problems, or unaddressed ethical concerns.

3 = Reject
A paper that is not competitive for an ICLR-style top-tier AI conference due to meaningful weaknesses in novelty, technical soundness, evaluation, reproducibility, clarity, significance, or positioning.
Use 3 for papers with weak novelty, weak empirical support, missing important baselines, insufficient ablations, unclear contribution, overclaimed results, limited significance, or poor positioning relative to prior work.
A paper can receive 3 even if it is understandable, technically plausible, well written, or has some positive experimental results.

5 = Marginally below the acceptance threshold
A mostly technically solid paper with some clear strengths, but where weaknesses slightly outweigh strengths.
Use 5 only when the paper is close to being competitive but still falls short due to limited novelty, incomplete evaluation, weak baselines, insufficient ablations, narrow scope, limited reproducibility, unclear significance, or claims stronger than the evidence.
A paper with multiple meaningful weaknesses should receive 3 rather than 5.
Please use sparingly.

6 = Marginally above the acceptance threshold
A technically solid paper where strengths clearly outweigh weaknesses and there is concrete evidence that the paper is competitive for an ICLR-style top-tier AI conference.
Use 6 only if the paper has a clear nontrivial contribution, mostly sound methodology, convincing evaluation for the main claims, appropriate baselines or comparisons, and no major unresolved weakness in novelty, evaluation, reproducibility, or significance.
Do not assign 6 merely because the paper is coherent, plausible, well written, or reports some positive results.
If these conditions are not satisfied, the rating should usually be no higher than 5.
Please use sparingly.

8 = Accept
A strong paper with a clear, meaningful, and well-supported contribution; convincing technical quality; good-to-excellent evaluation; appropriate comparisons; sufficient reproducibility; and clear relevance to the field.
Use 8 only when the paper would be clearly competitive at an ICLR-style top-tier AI conference and has no major unresolved issue in soundness, novelty, evaluation, reproducibility, significance, or ethics.
A paper with limited evaluation, unclear novelty, weak baselines, insufficient ablations, or significant reproducibility gaps should not receive 8.

10 = Strong Accept
An exceptional paper with groundbreaking impact on one or more areas of AI, technically excellent work, exceptionally strong evaluation, strong reproducibility and resources, and no unaddressed ethical considerations.
This rating should be reserved for rare submissions that are clearly among the best papers in the venue.

Upper-bound rules:
If the main claims are not adequately supported, the rating should be at most 3.
If the paper lacks important baselines, necessary ablations, or evaluation needed to support the main claims, the rating should usually be at most 5.
If the contribution is incremental, narrow, or weakly positioned relative to prior work, the rating should usually be at most 5.
If the paper has multiple moderate weaknesses across novelty, evaluation, reproducibility, clarity, or significance, the rating should usually be at most 5.
If either soundness or contribution is rated 1, the overall rating should usually be 1 or 3.
If either soundness or contribution is rated 2, the overall rating should usually be no higher than 5 unless there is unusually strong compensating evidence.
When uncertain between two adjacent ratings, choose the lower rating unless the review identifies concrete evidence supporting the higher rating.

8. Confidence
Use a 1-5 scale:
1 = educated guess
2 = willing to defend but likely missed central parts
3 = fairly confident
4 = confident but not absolutely certain
5 = absolutely certain, checked details carefully

Output Format

You MUST output your review as a single valid JSON object with exactly the fields shown below.
Do NOT output any text outside the JSON object.
Do NOT use markdown fences, preamble, or commentary.
Use numeric values, not strings, for soundness, presentation, contribution, rating, and confidence.

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
```
