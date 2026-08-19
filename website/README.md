# GenePathwayAI website

This directory contains the user-facing web application for the agentic pathway-analysis platform. It accepts a human gene list and disease context, runs the pathway hypothesis, validation, ranking and interpretation workflow, and presents an interactive evidence register.

## Directory layout

- `web_app/` — Flask server, browser interface, authentication, quota controls and the archived demo.
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

Then open `http://127.0.0.1:8768/`. The completed example is available at `http://127.0.0.1:8768/?demo=1`.

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
python -m pytest web_app/test_quota_manager.py web_app/test_server_limits.py web_app/test_validation_metrics.py
```

Runtime history, logs, caches, local environments, credentials and debug-only artifacts are intentionally excluded from version control.
