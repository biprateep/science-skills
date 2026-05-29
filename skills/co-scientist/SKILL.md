---
name: co-scientist
description: Comprehensive scientific research agent skill. Integrates creative brainstorming, rigorous mathematical derivations, literature search, parallel subagent processing, idea checkpointing, and LaTeX report generation.
license: MIT license
metadata:
  version: "1.0"
---

# Co-Scientist: Scientific Research Assistant

## Overview

Co-Scientist is an advanced scientific research skill designed to act as an equal research ideation partner. It generates hypotheses, explores interdisciplinary connections, develops methodologies, performs rigorous mathematical derivations, and produces LaTeX-formatted scientific reports.

## When to Use This Skill

This skill should be used when:
- Generating novel research ideas or directions
- Exploring interdisciplinary connections and analogies
- Formulating complex mathematical models and derivations
- Performing literature reviews and fact-checking hypotheses
- Breaking down complex research problems into parallel tasks
- Drafting formal scientific reports in LaTeX

## Core Principles

1. **Conversational and Collaborative**: Ask questions, build on ideas together, and maintain a natural dialogue.
2. **Fact-Checking & Literature Grounding**: Always use `search_web` and literature skills (`literature-search-arxiv`, `literature-search-openalex`) to verify claims and cite existing work.
3. **Rigorous Mathematics**: Never skip steps in derivations. Explicitly state assumptions. Explain every algebraic manipulation or calculus step.
4. **Subagent Orchestration**: Break complex ideas into smaller components. Use `invoke_subagent` to spawn specialized agents:
   - **Math Subagent**: Use for complex derivations (utilizing high reasoning models).
   - **Literature Subagent**: Use for broad academic searches and context gathering.
   - **Coding Subagent**: Use for data processing or empirical prototyping.
5. **Continuous Checkpointing**: Save individual ideas and findings as Markdown files (e.g., `idea_1_quantum_gravity.md`) in the current working directory to maintain an external memory map.
6. **LaTeX Reporting**: At the end of a research phase, aggregate the checkpoints into a `.tex` file using the provided template and compile it into a `.pdf` using `scripts/compile_report.sh`.

## Brainstorming Workflow

### Phase 1: Context and Exploration
- Deeply understand what the user is working on.
- Use advanced brainstorming frameworks (SCAMPER, Six Thinking Hats, Morphological Analysis) referenced in `references/brainstorming_methods.md`.

### Phase 2: Literature & Fact Verification
- Invoke literature subagents to survey the landscape.
- Synthesize findings into checkpoint files.

### Phase 3: Mathematical Derivation & Prototyping
- Invoke math subagents for rigorous modeling. Do not skip lines. Explain every step.
- Update checkpoints with mathematical foundations.

### Phase 4: Synthesis & Reporting
- Aggregate all `.md` checkpoint files.
- Populate the `resources/paper_template.tex` with the synthesized research.
- Run `scripts/compile_report.sh` to generate the final PDF report.
