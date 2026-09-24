<h1 align="center">Reliable agentic AI platform for biological pathway inference of disease-associated genes</h1>

<p align="center">
  <em>A disease-context-aware agentic system that combines LLM reasoning with formal enrichment testing,
  biological ranking, feedback-guided refinement, and structured interpretation.</em>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
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
| 🤖 **Hypothesis Generation** | Reasons forward from the input gene list and disease to propose ten candidates from each of five annotation sources | [`agents/hypothesis_generation_agent.py`](agents/hypothesis_generation_agent.py) · [`predictor.py`](predictor.py) |
| ✅ **Statistical Validation** | Matches candidates to g:Profiler terms and retains only those with FDR-adjusted&nbsp;*P*&lt;0.05, together with identifiers and intersection genes | [`agents/statistical_validation_agent.py`](agents/statistical_validation_agent.py) |
| 📊 **Biological Ranking** | Ranks validated pathways independently within each database using pathway description, disease pathology, intersection genes, enrichment strength, and PubMed literature | [`agents/biological_ranking_agent.py`](agents/biological_ranking_agent.py) |
| 🔁 **Feedback** | Converts validated and invalidated hypotheses into a keep–expand–avoid prompt for the second generation pass | [`agents/feedback_agent.py`](agents/feedback_agent.py) · [`prompts/feedback.py`](prompts/feedback.py) |
| 🧩 **Interpretation** | Structures validated results into selection rationale, driver genes and functions, tissue/cell context, mechanistic themes, and disease-relevance strength | [`website/web_app/cell_context.py`](website/web_app/cell_context.py) · [`predictor.py`](predictor.py) · [`backend/reasoning_parser.py`](backend/reasoning_parser.py) |

The public platform runs exactly one initial prompt pass and one feedback-guided refined pass. Initial terms that pass FDR correction are retained after deduplication, and new generation fills the remaining database quota. The stage order, tool calls, feedback loop, and stopping rule are specified by human domain experts rather than planned autonomously by the LLM. The deployed two-pass workflow is implemented in [`website/web_app/server.py`](website/web_app/server.py).

---

## Installation

```bash
git clone https://github.com/Grit1021/Agentic_AI_platform.git
cd Agentic_AI_platform
python -m venv .venv && source .venv/bin/activate
pip install -r website/requirements.txt
```

Set the required environment variables:

```bash
export OPENAI_API_KEY="sk-..."          # required: generation, feedback, ranking, interpretation
export ENTREZ_EMAIL="name@example.com"  # recommended: PubMed / Entrez access
```

`OPENAI_API_KEY` powers hypothesis generation, feedback, ranking, and interpretation. `ENTREZ_EMAIL` is recommended for PubMed / Entrez retrieval. GPT-5.1 is the manuscript model and the default in the public platform.

---

## Run the platform locally

Install the web application dependencies and start the service without authentication:

```bash
cd website/web_app
AUTH_ENABLED=false python server.py
```

Open `http://127.0.0.1:5000/`. The interface accepts HGNC symbols or Ensembl Gene IDs together with a disease name. It reports identifier mapping before pathway inference and keeps enrichment statistics separate from biological interpretation.

<details>
<summary><b>24-disease benchmark (as reported in the paper)</b></summary>

Spanning neurodegenerative, neuropsychiatric, cardiovascular, autoimmune, metabolic, infectious, oncological, respiratory, renal, and dermatological conditions:

`AD, PD, ALS, PSP, MDD, MS, RA, AIT, SLE, PS, IBD, CD, COPD, AST, CAD, AF, HF, HTN, T2D, CKD, OSA, TB, CRC, HCC`

The public platform is not limited to these benchmark diseases; it accepts a submitted disease label and resolves disease context through NCBI MeSH.
</details>

---

## Input

The scientific workflow is agnostic to how a gene list was assembled. Each analysis requires:

- a human gene list, submitted as HGNC symbols, Ensembl Gene IDs, or a supported mixture; and
- a disease label that defines the context for generation, ranking, and interpretation.

For the manuscript benchmark, the 567 inputs were significant network-derived gene communities from a previous study. Each retained community contained at least ten genes and was paired with its corresponding disease. These benchmark-specific communities are evaluation inputs, not a requirement of the public platform.

---

## Output

Each completed platform analysis reports:

- submitted, recognized, and unresolved gene identifiers;
- initial and refined hypothesis counts and the number passing FDR-controlled validation;
- a deduplicated set of validated pathways, ranked independently within GO:BP, GO:MF, GO:CC, KEGG, and Reactome;
- matched database identifiers, FDR-adjusted *P*-values, pathway sizes, and input–pathway intersection genes;
- structured biological interpretation covering driver genes and functions, tissue/cell context, mechanistic themes, and disease relevance; and
- pathway definitions, PubMed support, and provenance links where available.

Cell and tissue assignments are multi-label interpretation outputs. They do not measure cell abundance, expression, enrichment strength, or statistical significance, and they are not independent evidence of disease-specific cell-type involvement.

---

## Repository layout

```text
.
├── orchestrator.py        # benchmark-oriented command-line pipeline
├── config.py              # disease configuration (MeSH/NCBI lookup, abbreviations)
├── framework.py           # iterative framework wired to the Feedback agent
├── predictor.py           # hypothesis generation + reasoning-audit traces
├── llm_client.py          # LLM client + disk cache
├── report.py              # summary report generation
├── visualization.py       # validation & category plots
├── agents/                # generation, validation, ranking, and feedback modules
├── prompts/               # prompt templates (generation, feedback, reasoning audit)
├── tools/                 # PubMed, ranking, g:Profiler cache utilities
├── backend/               # bundled runtime modules (multi-agent analysis, optional memory storage)
├── website/web_app/       # Public two-pass app and pathway-level cell-context mapping
├── docs/                  # GitHub Pages demo homepage (index.html)
└── assets/                # Framework overview (PNG/PDF)
```

---

## Reproducibility

Full runs call OpenAI, g:Profiler, NCBI MeSH, and NCBI Entrez / PubMed. Reproducing the manuscript results requires the same 567 input gene lists, disease labels, GPT-5.1 model, prompt templates, and service outputs. Each prompt pass requests ten hypotheses per database; the workflow uses one initial pass and one feedback-guided refined pass. The primary benchmark stored validated pathways in the memory bank but did not retrieve cross-disease history during generation. Retrieval was evaluated only in the dedicated transfer experiment on 69 gene-list pairs from five diseases, using `text-embedding-3-small` for semantic indexing.

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
