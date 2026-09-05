# GenePathwayAI website

This directory contains the user-facing web application for the agentic pathway-analysis platform. It accepts a human gene list and disease context, runs the pathway hypothesis, validation, ranking and interpretation workflow, and presents an interactive evidence register.

## Directory layout

- `web_app/` — Flask server, componentized browser interface, authentication, admin quota controls and archived examples.
- `web_app/components/` — shared header, workflow, input, runtime, results, history, documentation, tour and footer fragments.
- `web_app/examples/` — downloadable HGNC, Ensembl and mixed-identifier input examples.
- `gene_pathway_tool/` — pathway analysis clients and pipeline adapters.
- `demo_sources/` — source records used to reproduce the bundled Alzheimer’s disease example.
- `.ebextensions/`, `Procfile` and `.ebignore` — AWS Elastic Beanstalk deployment configuration.
- `DEPLOY_AWS.md` — deployment and authentication instructions.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd web_app
AUTH_ENABLED=false python server.py
```

Then open `http://127.0.0.1:5000/`. The completed Alzheimer’s disease example is available at `http://127.0.0.1:5000/?demo=1&example=AD`.

## Configuration

Copy `web_app/.env.template` to a local `.env` file and provide the required environment variables. Do not commit `.env` files, API keys, Cognito client secrets or Flask secret keys.

The production deployment currently expects:

- OpenAI credentials for model-backed analysis;
- an NCBI Entrez contact email for PubMed access;
- Amazon Cognito settings for authenticated access;
- optional DynamoDB settings for persistent daily quotas.

See `DEPLOY_AWS.md` for the complete AWS setup.

## Validation

```bash
python validate_demo_output.py
cd web_app
python -m unittest test_server_limits.py
python -m unittest test_quota_manager.py
python -m unittest test_validation_metrics.py
python -m unittest test_admin_dashboard.py
python -m unittest test_external_evidence.py
python -m unittest test_open_targets_gene_import.py
cd ..
python -m unittest test_archive_lock.py test_backfill_narrative_clusters.py
```

Runtime history, logs, caches, local environments, credentials and debug-only artifacts are intentionally excluded from version control.
