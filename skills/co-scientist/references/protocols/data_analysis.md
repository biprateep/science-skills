# Data Analysis Protocol

Read this when the hypothesis is to be tested against **data** — either the
user's **real dataset** (CSV / Parquet / FITS / HDF5 / …) or **synthetic** data.
This is the empirical counterpart to the Math Derivation Protocol: the goal is a
**reproducible, honestly-quantified** answer, not a plot that "looks right".
Delegate to the Computation subagent (see `references/subagents.md`).

## 1. Ingest

- Take the data path + format from the user. Never invent data values.
- Load it; record shape, columns, dtypes.
- If the user has no data and the test is illustrative, generate **synthetic**
  data from a stated generative model (logged seed) and label results as
  synthetic.

## 2. EDA & Data-Quality Checkpoint

Before any test, produce a data-quality checkpoint:

- Shape, dtypes, units, value ranges.
- Missingness (counts / fractions per field) and how it is handled.
- Outliers / anomalies / duplicates; distributional summary.
- Provenance and any preprocessing applied (with the exact script).

## 3. State the Test Before Running It (avoid p-hacking)

Tie the statistical procedure to the hypothesis **up front**:

- The estimator or test and **why** it fits (assumptions: independence,
  distributional form, variance structure).
- The metric, the effect of interest, and the decision threshold (α) **chosen
  before** looking at results.
- Pre-register multiple-comparison handling if several tests are run
  (Bonferroni / FDR), and state the train/validation split if modeling.

## 4. Run Reproducibly

- One self-contained script in `scripts/`, with a **logged seed** and recorded
  environment (see `checkpointing.md` → Reproducibility).
- Save intermediate artifacts; record the exact command in the manifest.

## 5. Report Effect, Not Just Significance

- Report the **effect size with an uncertainty interval** (CI / bootstrap /
  posterior), not a bare p-value.
- State assumptions checked and any that failed (append to the ledger).
- Distinguish **correlation from causation** explicitly; note confounders.
- If the result **contradicts** the hypothesis, that is a finding — carry it to
  Phase 8 (Outcome decision), do not bury it.

## Self-check before returning

1. Is the data provenance and quality documented?
2. Was the test (and α, and multiple-comparison handling) fixed before results?
3. Is the run reproducible (seed + env + command + script)?
4. Is an effect size **with uncertainty** reported?
5. Are failed assumptions and confounders stated, and the result tagged with a
   confidence level?
