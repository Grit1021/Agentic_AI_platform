<h1 align="center">Reliable agentic AI platform for biological pathway inference of disease-associated genes</h1>

<p align="center">
  <em>A disease-context-aware agentic system that combines LLM reasoning with formal enrichment testing,
  biological ranking, feedback-guided refinement, and structured interpretation.</em>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="LLM" src="https://img.shields.io/badge/LLM-GPT--5.1-4A6FA5">
  <img alt="Enrichment" src="https://img.shields.io/badge/Enrichment-g%3AProfiler-5B9B7A">
  <img alt="Evidence" src="https://img.shields.io/badge/Evidence-PubMed%2FEntrez-C88A3C">
</p>

<p align="center">
  <b>🌐 Demo homepage:</b> <a href="https://tigerai.bio/pathway/">tigerai.bio/pathway/</a>
</p>

<p align="center">
  <img src="assets/figure1.png" alt="Framework overview: agentic pathway inference from disease-associated genes" width="100%">
</p>

<p align="center"><sub><b>Overview.</b> A human-expert-designed orchestrator connects four functional stages—pathway hypothesis generation, statistical validation, biological ranking, and structured interpretation—with a feedback-guided second generation pass.</sub></p>

---

## Overview

Pathway analysis turns disease-associated gene lists into mechanistic hypotheses, but conventional enrichment output often requires substantial manual interpretation. LLMs can generate fluent pathway narratives directly, yet plausible wording does not guarantee enrichment support. This platform treats every LLM-proposed pathway as a hypothesis that must pass explicit statistical and biological verification before it is reported.

Given a **disease** and a **gene list**, a human-expert-designed orchestrator runs a fixed, auditable workflow:

1. **Hypothesis generation** proposes ten candidates per database across GO:BP, GO:MF, GO:CC, KEGG, and Reactome, reasoning forward from the input genes and their documented pathway memberships.
2. **Statistical validation** matches each candidate to a database term and applies formal g:Profiler enrichment with multiple-testing correction; only terms with FDR-adjusted *P* < 0.05 are retained.
3. **Biological ranking** evaluates validated pathways independently within each database using five evidence components: pathway description, disease pathology, intersection genes, enrichment strength, and live PubMed literature.
4. **Feedback-guided refinement** summarizes validated and invalidated hypotheses with a keep–expand–avoid strategy, then launches one refined generation pass in the same disease–gene-list context.
5. **Structured interpretation** reports the selection rationale, driver genes and dominant functions, pathway-level tissue/cell context, mechanistic themes, and disease-relevance strength. Context assignments are interpretive outputs—not additional evidence of enrichment or cell abundance—and indirect support is flagged.

The interpretation stage itself calls no external tool. The user-facing implementation can separately attach provenance-preserving PubMed evidence to pathway-level context when matching disease, cell/tissue labels, and intersection genes are available.

The final-check benchmark contains **567 disease–gene-list pairs across 24 complex diseases**. Among database-matched terms, the disease-macro mean statistical-validation pass rate increased from **28.9% under the initial prompt to 39.8% under the refined prompt**. Statistical testing remains necessary after refinement because many new hypotheses still fail enrichment.

---

## The agent workflow

| Agent | Role | Module |
|---|---|---|
| 🤖 **Hypothesis Generation** | Reasons over module genes + disease to propose candidate pathways across five functional sources | [`agents/hypothesis_generation_agent.py`](agents/hypothesis_generation_agent.py) · [`predictor.py`](predictor.py) |
| ✅ **Statistical Validation** | Runs the formal enrichment test and writes the matched / FDR&nbsp;p&lt;0.05 / nominal validation contract | [`agents/statistical_validation_agent.py`](agents/statistical_validation_agent.py) |
| 🔁 **Feedback** | Converts validated and invalidated hypotheses into a keep–expand–avoid prompt for the second generation pass | [`agents/feedback_agent.py`](agents/feedback_agent.py) · [`prompts/feedback.py`](prompts/feedback.py) |
| 📊 **Biological Ranking** | Ranks validated pathways within each category by synthesizing five evidence sources | [`agents/biological_ranking_agent.py`](agents/biological_ranking_agent.py) |
| 🧩 **Interpretation** | Adds post-validation, pathway-level cell/tissue context to every supported pathway and detailed driver-gene / mechanistic interpretation to highlighted pathways | [`website/web_app/cell_context.py`](website/web_app/cell_context.py) · [`predictor.py`](predictor.py) · [`backend/reasoning_parser.py`](backend/reasoning_parser.py) |

The [`PipelineOrchestrator`](orchestrator.py) fixes the stage order, tool calls, feedback loop, and stopping rule: initial pass → validation and ranking → feedback-guided refined pass → aggregation and structured interpretation. These decisions are specified by human domain experts rather than planned autonomously by the LLM.

---

## Installation

```bash
git clone https://github.com/Grit1021/Agentic_AI_platform.git
cd Agentic_AI_platform
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # pandas, numpy, biopython, gprofiler-official, openai, matplotlib, ...
```

Set the required environment variables:

```bash
export OPENAI_API_KEY="sk-..."          # required: generation, feedback, ranking, interpretation
export ENTREZ_EMAIL="name@example.com"  # recommended: PubMed / Entrez access
```

`OPENAI_API_KEY` powers all LLM stages. `ENTREZ_EMAIL` is recommended so PubMed evidence retrieval runs without throttling. The default model (`gpt-5.1`) is configurable in [`llm_client.py`](llm_client.py); LLM responses are disk-cached under `~/.cache/pathway_analysis/`.

---

## Quickstart

Run commands from the directory that contains this package.

```bash
# Full analysis for Alzheimer's disease
python -m refined.orchestrator --disease AD --tag full_run

# Fast smoke test (a couple of modules only)
python -m refined.orchestrator --disease AD --test --tag test_run

# Disable optional memory-bank storage
python -m refined.orchestrator --disease AD --test --no-memory --tag no_memory
```

`--disease` accepts an abbreviation (e.g. `AD`, `PD`, `MS`, `T2D`) **or** a full disease name. Disease metadata (MeSH ID, description, keywords) is resolved automatically from NCBI/MeSH — no hardcoding required.

<details>
<summary><b>24-disease benchmark (as reported in the paper)</b></summary>

Spanning neurodegenerative, cardiovascular, autoimmune, metabolic, infectious, oncological, respiratory, renal, and dermatological conditions:

`AD, PD, ALS, PSP, MDD, MS, RA, AIT, SLE, PS, IBD, CD, COPD, AST, CAD, AF, HF, HTN, T2D, CKD, OSA, TB, CRC, HCC`

Any other disease can be analyzed by passing its name or abbreviation — metadata is resolved from NCBI/MeSH.
</details>

---

## Input data

The workflow reads network-expansion module files:

```
Network_expansion/outputs/disease_pair_expansion/{MESH_ID}_modules.csv
```

| Column | Required | Meaning |
|---|---|---|
| `node` | ✅ | Gene symbol |
| `cluster_walktrap` | ✅ | Module ID (rows with `-1` are excluded) |
| `passes_all_filters` | optional | If present, only passing genes are used |

---

## Outputs

Each run writes to `iterative_feedback_{DISEASE}/{DISEASE}_aggregated_{TIMESTAMP}_{TAG}/`:

- `phase1_module_collection/Module_{id}_filtered_pathways.csv` — per-module validated pathways
- iter1 statistical-validation contract: `*_gpt_matched_all.csv`, `*_gpt_matched_fdr_p005.csv`, `*_gpt_matched_nominal_p005.csv`
- per-module Phase 2 iteration outputs and `*_reasoning.md` audit traces
- `final_aggregated_pathways.csv` — ranked, validated pathways across all modules
- `final_module_metadata.json`
- `summary_iterative/summary_pathway_ranking.txt`
- post-validation pathway-level `cell_context`, provenance, and label/gene-mapped PubMed evidence in website/API result records
- validation / category plots ([`visualization.py`](visualization.py))
- optional memory-bank storage artifacts (when enabled; retrieval was not used in the primary benchmark)

---

## Repository layout

```text
.
├── orchestrator.py        # command-line entry point & pipeline coordinator
├── config.py              # disease configuration (MeSH/NCBI lookup, abbreviations)
├── framework.py           # iterative framework wired to the Feedback agent
├── predictor.py           # hypothesis generation + reasoning-audit traces
├── llm_client.py          # LLM client + disk cache
├── report.py              # summary report generation
├── visualization.py       # validation & category plots
├── agents/                # four stage agents plus the feedback agent
├── prompts/               # prompt templates (generation, feedback, reasoning audit)
├── tools/                 # PubMed, ranking, g:Profiler cache utilities
├── backend/               # bundled runtime modules (multi-agent analysis, optional memory storage)
├── website/web_app/       # Interactive app, including pathway-level cell-context mapping
├── docs/                  # GitHub Pages demo homepage (index.html)
└── assets/                # Framework overview (PNG/PDF)
```

---

## Reproducibility

Full runs call external services—OpenAI, NCBI/MeSH, PubMed/Entrez, and g:Profiler. Reproducing the manuscript results requires the same input gene lists, disease labels, GPT-5.1 configuration, prompt templates, database versions, and archived outputs. The primary benchmark stored validated pathways in the memory bank but did not retrieve them during generation; retrieval was evaluated only in the dedicated 69-pair cold-start transfer experiment. Disk caching of LLM responses (`~/.cache/pathway_analysis/`) reduces repeated calls.

---

## Citation

```bibtex
@misc{li2026reliable_agentic_ai,
  title  = {Reliable agentic AI platform for biological pathway inference of disease-associated genes},
  author = {Li, Yuxin and Yang, Yilin and Shu, Juan and Zhang, Zichen and Li, Bingxuan and Fan, Zirui and Zhao, Bingxin},
  year   = {2026},
  url    = {https://github.com/Grit1021/Agentic_AI_platform}
}
```

Publication metadata will be added when the manuscript is publicly available. Questions and issues are welcome via the repository issue tracker.
