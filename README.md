# RecallOps

![RecallOps project cover](assets/devpost-cover.png)

RecallOps is an incident-response assistant that turns operator-recorded incident history into durable, auditable memory. It stores symptoms, infrastructure context, resolutions, outcomes, embeddings, timestamps, and provenance; retrieves only relevant resolved precedents for the same service; and presents the evidence for a human to review before acting.

This project is being built for the **CockroachDB x AWS Hackathon: Build with Agentic Memory**.

> **Submission-safe status:** The local workflow and integration code are implemented and tested. CockroachDB Cloud, Bedrock, Managed MCP, and AWS hosting still require account credentials and live smoke tests before they can be described as deployed. This repository does not claim a public cloud deployment that has not been verified.

## Why this architecture matters

Incident assistants are only useful when an operator can see why a recommendation was made and what happened the last time. RecallOps makes that evidence boundary explicit: each incident, resolution, and outcome is stored as durable memory; recall is limited to resolved incidents for the same service; the response carries IDs, provenance, relevance, and uncertainty; and a human approval gate remains between the recommendation and any operational action. RecallOps never executes remediation.

## What is implemented

RecallOps currently includes:

- a FastAPI API and a same-origin HTML/CSS/JavaScript operator console;
- atomic creation of an incident and its symptom memory;
- atomic resolution of an incident together with separate resolution and outcome memories;
- structured provenance for every memory, including embedding provider, model, dimensions, source incident ID, metadata, and timestamp;
- same-service retrieval restricted to resolved incidents with a recorded resolution;
- a configurable minimum relevance threshold (`0.15` by default) and a maximum of five recalled incidents;
- a CockroachDB `VECTOR(512)` storage and cosine-search path with a service-prefixed distributed vector index;
- optional Amazon Bedrock integration using Titan Text Embeddings V2 and Nova Lite;
- a narrow CockroachDB Cloud Managed MCP client that allowlists only `select_query` for a bounded incident-memory audit;
- competition-mode startup gates that reject local fallbacks or missing integration credentials;
- structured request logs and an `X-Request-ID` trace on every response;
- an offline SQLite and deterministic-embedding mode for development and automated tests.

RecallOps recommends evidence to investigate. It does not execute infrastructure changes.

## Integration status

| Capability | Repository status | What is still required |
| --- | --- | --- |
| Local SQLite workflow | Implemented and covered by automated tests | No cloud credentials |
| CockroachDB Distributed Vector Indexing | Schema, bootstrap, index, and query path implemented | Run and record an end-to-end test against CockroachDB Cloud |
| Amazon Bedrock | Titan embedding and Nova reasoning clients implemented | AWS credentials, model access, and a live smoke test |
| CockroachDB Cloud Managed MCP | Read-only `select_query` audit is integrated into the top recalled recommendation and covered by contract/API tests | Cluster-scoped read-only credentials and a live execution |
| AWS hosting | Non-root Docker image, CI, and an undeployed ECS Fargate task/IAM template | Render the template, deploy to AWS, expose public HTTPS, and keep it available for judging |
| Architecture evidence | Source SVG, PNG, and one-page PDF are regenerated from the same reviewed design | Upload the same artifact revision to Devpost after the final deployment check |

There is currently no claimed public deployment. Do not describe ECS, Fargate, an Application Load Balancer, Secrets Manager, or a public demo as live until those resources have actually been created and verified.

## Memory loop

```mermaid
flowchart LR
    O["Operator console<br/>service • symptoms • infrastructure<br/>resolution • outcome"] --> A["RecallOps agent<br/>FastAPI orchestration"]
    A --> W["Atomic memory write<br/>incident + evidence commit"]
    W --> D["Durable agent memory<br/>CockroachDB VECTOR(512)<br/>incidents • memory events • ANN"]
    D --> R["Resolved-only recall<br/>same service • thresholded"]
    R --> G["Grounded response<br/>evidence IDs + uncertainty"]
    D --> Q["Managed MCP<br/>read-only select_query audit"]
    Q --> G
    A --> B["Amazon Bedrock when enabled<br/>Titan embeddings • Nova Lite"]
    B --> W
    B --> G
    G --> H["Human approval gate<br/>operator approval required<br/>no automatic remediation"]
    G --> P["Visible proof in every response<br/>relevance • terms • outcome<br/>memory/source IDs • timestamps • MCP status"]
```

The production path uses CockroachDB Cloud's `VECTOR(512)` memory and Bedrock when enabled. Local development swaps in SQLite and deterministic embeddings without changing the API workflow. When Managed MCP is enabled, `/investigate` automatically reads back the top recalled incident's durable memory trail through an allowlisted, bounded `select_query`; the response and browser console expose the per-request tool trace and audit receipt.

The diagram is maintained as source SVG, a 16:9 PNG, and a one-page PDF so the same reviewed design can be used in the repository, demo, and Devpost submission.

See [ARCHITECTURE.md](ARCHITECTURE.md) for transaction boundaries, retrieval rules, provenance, safety controls, and failure behavior.

![RecallOps architecture diagram](assets/architecture.svg)

## Judge-facing proof path

The shortest reproducible demo is:

1. Record a prior incident with service, symptoms, and infrastructure context.
2. Resolve it with a concrete resolution and observed outcome.
3. Record a new incident for the same service with similar symptoms.
4. Investigate and show that recall is resolved-only, same-service, thresholded, and capped at five results.
5. Show the grounded response, source/memory IDs, provenance, request trace, and (when configured) the Managed MCP audit receipt.
6. Have the operator review the recommendation; there is no automatic remediation path.

This sequence demonstrates the complete memory loop rather than only a static architecture claim.

## Requirements

- Python 3.11 or newer
- Docker Desktop only if using the local CockroachDB Compose stack
- AWS credentials and Bedrock model access only if `USE_BEDROCK=true`
- CockroachDB Cloud credentials only for the live Cloud paths
- The official MCP Python SDK, installed with the application dependencies

## Local quick start

From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
python -m uvicorn app.main:app --reload
```

Open:

- operator console: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`
- runtime configuration summary: `http://127.0.0.1:8000/system`
- process health: `http://127.0.0.1:8000/health`
- database readiness: `http://127.0.0.1:8000/ready`

The default `.env.example` uses SQLite, local deterministic embeddings, and a local retrieval summary. It does not contact CockroachDB Cloud, Bedrock, or Managed MCP.

## Exact local API demo

Keep the API running, then use a second PowerShell terminal:

```powershell
$recallOpsBase = "http://127.0.0.1:8000"
$requestHeaders = @{}
# If API_KEY is configured, uncomment the next line:
# $requestHeaders["X-API-Key"] = "replace-with-your-api-key"

$priorIncident = Invoke-RestMethod -Method Post -Uri "$recallOpsBase/incidents" -Headers $requestHeaders -ContentType "application/json" -Body (@{
    title = "Checkout latency spike"
    service = "payments"
    symptoms = "Checkout requests time out after database connections become saturated."
    infrastructure = @{ region = "us-east-1"; runtime = "demo" }
} | ConvertTo-Json -Depth 5)

Invoke-RestMethod -Method Post -Uri "$recallOpsBase/incidents/$($priorIncident.id)/resolve" -Headers $requestHeaders -ContentType "application/json" -Body (@{
    resolution = "Raised the connection pool limit gradually and restarted one worker at a time."
    outcome = "Error rate and p95 latency returned to baseline."
    notes = "Observed the saturation dashboard for 30 minutes."
} | ConvertTo-Json -Depth 5)

$currentIncident = Invoke-RestMethod -Method Post -Uri "$recallOpsBase/incidents" -Headers $requestHeaders -ContentType "application/json" -Body (@{
    title = "Payment checkout slowdown"
    service = "payments"
    symptoms = "Database connections are saturated and checkout latency is increasing."
    infrastructure = @{ region = "us-east-1"; runtime = "demo" }
} | ConvertTo-Json -Depth 5)

$recommendation = Invoke-RestMethod -Method Post -Uri "$recallOpsBase/incidents/$($currentIncident.id)/investigate" -Headers $requestHeaders
$recommendation | ConvertTo-Json -Depth 10

Invoke-RestMethod -Method Get -Uri "$recallOpsBase/incidents/$($priorIncident.id)/memory" -Headers $requestHeaders | ConvertTo-Json -Depth 10
Invoke-RestMethod -Method Get -Uri "$recallOpsBase/system" | ConvertTo-Json -Depth 10
```

The recommendation should reference only the resolved prior incident, include its recorded outcome and provenance-rich evidence, and report a relevance at or above `MINIMUM_RELEVANCE`.

## Tests

```powershell
python -m pytest -q
```

The API tests use an isolated temporary SQLite database. MCP contract tests validate UUID and limit bounds, fixed read-only SQL construction, tool allowlisting, schema adaptation, cluster-scoped headers, and secret redaction without contacting the managed service.

The suite covers the API workflow, readiness, request tracing, validation, transaction rollback, resolved-only recall, Bedrock evidence propagation, MCP safety, and the integrated MCP audit receipt. Vector tests check dimension and numeric-value validation with SQLite and PostgreSQL dialects; the PostgreSQL checks do not replace a live CockroachDB integration test.

Embeddings must contain exactly 512 finite real numbers. Invalid dimensions, NaN, infinity, booleans, and numeric strings are rejected before storage on both database paths. If a provider returns an invalid vector, the incident or resolution transaction rolls back. Reading malformed embeddings from an older database also raises a validation error; repair or regenerate the affected embeddings before using them for recall. Null embeddings remain supported for legacy records.

## Local CockroachDB vector stack

```powershell
docker compose up --build
```

This local-only stack binds ports to loopback, starts a single insecure CockroachDB node, enables vector indexing, creates `incident_memories.embedding VECTOR(512)`, builds `incident_memory_embedding_idx` on `(service, embedding vector_cosine_ops)`, and exposes the API at `http://127.0.0.1:8000`. The CockroachDB Admin UI is at `http://127.0.0.1:8080`.

This Compose environment is for development. It is not CockroachDB Cloud and is not an AWS deployment.

## CockroachDB Cloud and Bedrock configuration

Use a TLS CockroachDB Cloud connection string and retain `sslmode=verify-full`:

```dotenv
DATABASE_URL=postgresql://user:password@cluster-host:26257/defaultdb?sslmode=verify-full
REQUIRE_COCKROACHDB=true
COMPETITION_MODE=true
MINIMUM_RELEVANCE=0.15
USE_BEDROCK=true
AWS_REGION=us-east-1
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
API_KEY=replace-with-a-long-random-value
```

`REQUIRE_COCKROACHDB=true` makes startup fail if the configured database is SQLite or is not identified as CockroachDB. `COMPETITION_MODE=true` additionally refuses to start unless CockroachDB is required, Bedrock and Managed MCP are enabled, and an application API key is configured. The CockroachDB bootstrap also checks that distributed vector indexing is enabled.

Bedrock uses the standard boto3 credential chain. A live runtime needs `bedrock:InvokeModel` permission for the selected Titan and Nova models. Never place AWS keys or database passwords in the repository or container image.

## Managed MCP audit

The second CockroachDB tool is implemented in `app/mcp_client.py`. It accepts only a canonical incident UUID, builds one fixed `SELECT` over `incident_memories`, caps results at 100 rows, excludes the embedding column, adapts to the server-advertised `select_query` schema, rejects non-allowlisted tools, uses an HTTPS endpoint, supports cluster scoping, applies a timeout, and redacts credential-shaped output.

The official MCP SDK is installed with RecallOps but imported lazily so local development remains isolated from the managed service. Configure the live audit before starting the API:

```powershell
$env:COCKROACH_MCP_API_KEY = "replace-with-read-only-service-account-secret"
$env:COCKROACH_MCP_CLUSTER_ID = "replace-with-cluster-id"
$env:COCKROACH_MCP_DATABASE = "defaultdb"
$env:USE_COCKROACH_MCP = "true"
```

With a real CockroachDB Cloud cluster and valid read-only credentials, investigate a new incident through the API or console. RecallOps automatically audits the top recommendation. A direct smoke test is also available when diagnosing credentials:

```powershell
@'
import asyncio
import os

from app.mcp_client import CockroachDBMCPClient, result_as_json

async def main() -> None:
    client = CockroachDBMCPClient(
        api_key=os.environ["COCKROACH_MCP_API_KEY"],
        cluster_id=os.environ.get("COCKROACH_MCP_CLUSTER_ID"),
        database=os.environ.get("COCKROACH_MCP_DATABASE", "defaultdb"),
    )
    result = await client.audit_incident_memories(os.environ["INCIDENT_ID"])
    print(result_as_json(result))

asyncio.run(main())
'@ | python -
```

Set `INCIDENT_ID` only for that direct diagnostic. Live verification still requires credentials; the competition video should show the integrated audit receipt from the same CockroachDB Cloud cluster used by the public demo.

## API workflow and safeguards

1. `POST /incidents` atomically stores an incident and its symptom memory.
2. `POST /incidents/{id}/resolve` atomically updates the incident and appends separate resolution and outcome memories.
3. `POST /incidents/{id}/investigate` retrieves only same-service, resolved precedents that meet `MINIMUM_RELEVANCE`.
4. When `USE_COCKROACH_MCP=true`, the agent audits the top recalled incident through Managed MCP `select_query` and exposes the result plus a per-request tool trace.
5. The response includes source incident IDs, relevance, matched terms, the recorded resolution and outcome, and complete memory evidence with provenance.
6. If relevant matches exist and `USE_BEDROCK=true`, Nova Lite summarizes that evidence with explicit untrusted-data and non-execution guardrails. Otherwise RecallOps returns a deterministic local summary.
7. The operator reviews the grounded recommendation. The application has no remediation endpoint and does not execute infrastructure changes.
8. `GET /incidents/{id}/memory` exposes the stored evidence trail.

Set `API_KEY` to protect every incident read, write, resolution, and investigation route; clients then send it in `X-API-Key`. Health, readiness, system status, and the static operator console remain public for load-balancer checks and judging visibility.

`/health` is a liveness check. `/ready` verifies a database query. `/system` reports selected configuration and the detected backend; configuration alone does not prove that Bedrock or Managed MCP credentials work. The investigation tool trace proves that those calls ran for a request. Every response includes `X-Request-ID`, and the server emits a bounded JSON request-completion or request-failure log without request bodies, query strings, or credentials.

## AWS deployment path (not yet claimed as live)

The image can be published to Amazon ECR and run as a stateless ECS Fargate service behind HTTPS. [`infra/aws`](infra/aws) contains an explicit undeployed task-definition template, a least-privilege Bedrock policy, secret-injection guidance, and a production checklist.

Those templates are not evidence that AWS resources exist. Add ECS/Fargate, ALB, ECR, Secrets Manager, or IAM to Devpost only after the actual deployed architecture is available and tested.

## Submission materials

- [SUBMISSION.md](SUBMISSION.md) - Devpost-ready fields, truthful status language, required URLs, video script, and final checklist.
- [ARCHITECTURE.md](ARCHITECTURE.md) - detailed memory lifecycle, retrieval constraints, MCP safety, and deployment boundaries.
- [LICENSE](LICENSE) - MIT license.
- [Devpost cover](assets/devpost-cover.png) - generated 16:9 project gallery asset.
- [Architecture source SVG](assets/architecture.svg) - editable source for the reviewed design.
- [Architecture graphic](assets/architecture.png) - exact 16:9 tool and memory-flow diagram for web/gallery use.
- [Architecture PDF](output/pdf/recallops-architecture.pdf) - visually verified one-page Devpost upload artifact.
