# Live 567-input benchmark launcher

The deposited historical output archive is the source for exact offline
Figure 2 and pass-rate reconstruction. `run_live_benchmark.py` provides an
entry point for attempting new live analyses on the same 567 gene lists.
It verifies the 24 original module CSVs against `gene_lists_567.csv` and
`source_manifest.csv`, then plans one disease command at a time.

```bash
python scripts/run_live_benchmark.py
python scripts/run_live_benchmark.py --disease AD
```

Both commands are offline dry runs. The complete plan reports 567 inputs in
24 diseases; the AD subset reports 20 inputs. The live pipeline needs a
Python 3.11+ environment with `scripts/live_requirements.txt`, internet
access, an OpenAI API key, and an Entrez contact email:

```bash
python -m pip install -r scripts/live_requirements.txt
export OPENAI_API_KEY="..."
export ENTREZ_EMAIL="name@example.com"
python scripts/run_live_benchmark.py --disease AD --execute
```

`--execute` calls `orchestrator.py` with the bundled `data/source_modules/`
files and writes ignored `iterative_feedback_<disease>/` outputs under this
checkout. It incurs API calls and costs. The launcher can run all 24 diseases
sequentially if `--disease` is omitted. The historical live environment,
external-service responses, model snapshot, and random state were not
archived. Only the offline plan and import path have been smoke tested; a new
live run is expected to differ from the 2026 historical results and is not
offered as an exact reproduction of the paper.

`src/pathway_enrichment_analysis.py` restores a local
`PathwayEnrichmentAnalyzer` implementation used by the bundled benchmark runner. Its
unrelated hard-coded anemia/body-height example entry point was omitted.
This working copy is not identified as an exact as-run code snapshot.
The optional legacy Planning/Reasoning/Query/Writing agent modules and AG2
loader were not found in the local source archive. The bundled backend has
fallbacks, but their full API-backed behavior has not been verified from a
clean checkout. A dry-run plan or import smoke test does not establish a
complete live method reproduction.
