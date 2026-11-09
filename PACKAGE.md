# RecallOps

RecallOps is an experimental incident-response assistant. It records incident
symptoms, resolutions and outcomes, then retrieves resolved precedents for the
same service with evidence and provenance for an operator to review. It never
executes remediation.

The application includes a FastAPI API and a bundled operator console. Local
development uses SQLite and deterministic embeddings without cloud credentials.
CockroachDB, Amazon Bedrock and Managed MCP integrations are available through
configuration, but their live operation must be verified separately.

## Build and install locally

Python 3.11 or newer is required. From a checkout of the
[source repository](https://github.com/DattaDhebe/recallops):

```sh
python -m pip install "build>=1,<2" "twine>=6,<7"
python -m build
python -m twine check --strict dist/*
```

Install the resulting wheel into a separate virtual environment. For the current
development version, the installation command is:

```sh
python -m pip install /path/to/dist/recallops-0.1.0-py3-none-any.whl
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for the console or `/docs` for the API. The import
namespace is currently `app`; use a dedicated environment to avoid conflicts with
unrelated packages using that name. Set `API_KEY` before exposing incident
endpoints outside local development.

These instructions build and install a local artifact. They do not imply that a
package has been published to PyPI or that a cloud deployment is available.

## Distribution checks

CI builds a source distribution and then builds its wheel, checks the package
metadata, installs the wheel into a clean environment, and runs the installed
application outside the source checkout. The smoke test checks the bundled
console, local health and readiness endpoints, and the incident-resolution-recall
workflow. The regular test suite also runs on Python 3.11 and 3.12.

To repeat the installed-wheel smoke test, use the Python interpreter from the
environment where the wheel was installed:

```sh
/path/to/clean-venv/bin/python -I /path/to/checkout/scripts/smoke_installed_package.py
```

The test creates a temporary SQLite database and forces local integration
settings. It does not contact the cloud integrations or publish artifacts.

See the [project README](https://github.com/DattaDhebe/recallops#readme) for API
examples, safeguards and integration status. Report problems through
[GitHub Issues](https://github.com/DattaDhebe/recallops/issues).

Licensed under the MIT License.
