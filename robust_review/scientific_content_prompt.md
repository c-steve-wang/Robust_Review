# Task: extract a self-contained scientific content record from a paper PDF

Read the complete paper PDF, including appendices and supplementary material
contained in the file, and produce one rigorous, self-contained Markdown
record of its scientific content.

This is an evidence-preserving extraction task, not a peer review, acceptance
recommendation, manuscript rewrite, or related-work survey. Extract what the
paper reports without evaluating its quality, importance, novelty, clarity, or
persuasiveness. Do not omit scientific information merely to make the record
shorter.

## Evidence and attribution rules

- Preserve the problem formulation, inputs and outputs, notation, objectives,
  algorithms, components, training and inference procedures, assumptions,
  derivations, and formal results that materially define or support the method.
- Preserve exact reported numbers, units, uncertainty, metric direction,
  comparison conditions, and negative or mixed findings. Do not estimate
  numerical values from plot geometry.
- Attribute interpretations and claims to the paper. For example, write
  `The authors attribute this difference to ...` rather than presenting that
  explanation as an independently established fact.
- Include section, equation, theorem, table, figure, or appendix identifiers as
  evidence anchors when available. Do not include PDF page numbers.
- Do not infer strengths, weaknesses, novelty, scientific importance, causal
  conclusions, limitations, or missing information beyond what the PDF states.
- Do not use evaluative adjectives unless they are part of an attributed claim
  or have a precise quantitative basis.
- Do not manufacture citations, experiments, implementation details, or
  numerical values.

## Required organization

Use exactly the following five level-two sections, with the headings written
exactly as shown. Do not add a descriptive title, executive summary,
contribution list, experimental map, separate conclusion,
scientific-positioning section, evidence-reference index, notes on
interpretation, or any other section before, between, or after them.

## Problem and setting

Record the research problem, task definition, inputs and outputs, setting,
motivation needed to understand the problem, and the paper's stated research
questions or claims. Keep author claims explicitly attributed.

## Method and assumptions

Record the complete method and its technical foundations: notation, objectives,
model or system components, algorithms, training and inference, assumptions,
and method-critical derivations. For every theorem, proposition, lemma,
corollary, or formal guarantee that materially supports the method, state its
conditions, scope, result, and the proof logic available in the PDF.

## Experiments and reported results

Create one level-three subsection for each distinct experiment or coherent
experiment family. In each subsection, keep together:

- the stated question or purpose;
- datasets, sample sizes, splits, models, baselines, changed and controlled
  variables, metrics, and protocol;
- all material quantitative and qualitative results, including uncertainty,
  ablations, sensitivity and robustness studies, efficiency or scaling
  results, diagnostics, failure analyses, and negative or mixed findings;
- the interpretation stated by the authors, clearly attributed.

Represent every reported result needed to understand the paper's scientific
claims and comparisons.

### Complete extraction of reported tables

Extract every table in the main paper and appendix that contains scientific,
methodological, empirical, dataset, ablation, hyperparameter, complexity, or
reproducibility information. Reproduce each such table as a Markdown table
inside the relevant experiment or method subsection. Table extraction is
completeness-first and is not a place to shorten the record.

For every extracted table:

- include its table number and caption or a faithful descriptive caption;
- preserve every scientifically meaningful row, column, cell, header level,
  row group, column group, unit, metric direction, uncertainty value, range,
  footnote marker, missing-value marker, and table note;
- preserve the mapping between each value and its row and column conditions;
- retain author-provided emphasis such as bold or underline only when it
  encodes a defined meaning, and state that meaning in the table note;
- do not replace the table with selected values, prose, a bullet list, a range,
  an average, a summary, or only the best-performing entries;
- do not omit cells because they appear repetitive or less important;
- if a table is too wide or has multi-level headers, split it into clearly
  labeled Markdown sub-tables while preserving all cells and their original
  grouping and order;
- if a cell cannot be read reliably, write `[unreadable]` in that cell rather
  than guessing or dropping it.

Do not repeat all table values in surrounding prose. Use prose only for setup,
qualifications, figure-only evidence, and explicit author interpretations that
are not already contained in the table. State each non-table scientific fact
once. If a figure contains unique evidence, describe that evidence in the
relevant experiment subsection without inventing values.

## Reproducibility information

Record reported datasets and versions, preprocessing, splits, sample sizes,
architectures, objectives, optimization details, hyperparameters, stopping and
model-selection rules, seeds and repeats, inference settings, baselines, metric
definitions and directions, software, and hardware. Avoid repeating details
already recorded with a particular experiment; cross-reference that subsection
instead.

For a reproducibility field that is relevant but absent or uncertain, use only
one of these neutral statuses:

- `Reported`: the PDF provides the information;
- `Not reported in the PDF`: the PDF does not provide it;
- `Not located`: the information may be present but cannot be reliably found;
- `Not applicable`: the field does not apply to this work.

Do not call absent information critical, important, problematic, or a
weakness. Do not create a checklist of irrelevant fields.

## Author-stated limitations

Include only limitations, boundary conditions, failure modes, or future-work
needs that the authors explicitly state or directly demonstrate. Attribute
them to the authors or to the specific reported evidence. If none are stated,
write `No explicit author-stated limitations were located in the PDF.` Do not
add inferred criticisms. This must be the final section of the record. End the
record when this section is complete; do not append references to evidence,
notes on interpretation, extraction notes, conclusions, or other commentary.

## Writing rules

- Use neutral, dense, precise technical language and consistent terminology.
- Preserve qualifications and distinguish reported facts from attributed
  explanations.
- Include an interpretation only when the paper explicitly states it, place it
  beside the relevant evidence, and attribute it to the authors. Never add a
  model-generated interpretation or a separate interpretation summary.
- Avoid repeating a fact across overview, detail, table, figure, and conclusion
  formats. Removing repetition must never remove distinct conditions, values,
  qualifications, or evidence.
- Resolve notation into readable Markdown where possible while retaining the
  formulas and proof dependencies needed for scientific completeness.
- Do not include author names, affiliations, acknowledgements, paper IDs,
  arXiv IDs, filenames, repository names, or other source-identifying tokens.
- Do not discuss the extraction process, the prompt, or PDF parsing.
- Output only the finished Markdown scientific content record, without a code
  fence, preamble, TODO list, or commentary.
