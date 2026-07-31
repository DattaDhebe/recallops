# RecallOps Devpost submission draft

This file contains paste-ready fields plus explicit status notes. Replace every bracketed placeholder and complete every live-verification item before submitting. The repository implements the local workflow and cloud integration code paths, but this draft does not claim that a public AWS deployment, CockroachDB Cloud connection, Bedrock request, or Managed MCP request is already live.

## Project name

**RecallOps**

## Tagline / elevator pitch

RecallOps turns recorded incident outcomes into durable, provenance-rich memory and surfaces relevant resolved precedents before an operator acts.

## Inspiration

During an outage, the most useful clue is often buried in an old incident timeline or remembered by one engineer. Traditional runbooks can become stale, while a generic assistant may treat a proposed fix as if it actually worked. We wanted operational memory that keeps symptoms, attempted resolutions, and operator-recorded outcomes distinct, traceable, and useful during the next incident.

## What it does

RecallOps lets an operator record an incident with its service, symptoms, and infrastructure context. Creating an incident atomically stores the incident and its symptom memory. Resolving it atomically records the state change plus separate resolution and outcome memories, so a partial embedding failure cannot leave the history in a misleading state.

When a new incident is investigated, RecallOps searches only prior incidents for the same service that are resolved, have a recorded resolution, and meet a configurable relevance threshold. It returns source incident IDs, similarity, matched terms, the recorded resolution and outcome, and the complete memory evidence with provenance. With Amazon Bedrock enabled, Nova Lite explains which precedent is safest to investigate first using the retrieved evidence. The assistant never claims it executed a remediation.

When Managed MCP is enabled, RecallOps independently reads back the top recalled incident's memory trail through CockroachDB Cloud Managed MCP. It can call only `select_query` with a fixed, bounded read-only query. The API response and browser console show whether that per-request audit completed, failed, or was skipped, alongside the other tools used by the agent.

## How we built it

- **FastAPI, Pydantic, and SQLAlchemy** provide the typed API, validation, transactions, and operator workflow.
- **CockroachDB Distributed Vector Indexing** stores 512-dimensional memory embeddings and uses a service-prefixed cosine index for semantic recall.
- **CockroachDB Cloud Managed MCP** is represented by a cluster-scoped, read-only client that allowlists only `select_query`, validates incident UUIDs, caps rows, adapts to the advertised tool schema, disables redirects, applies timeouts, and redacts secrets.
- **Amazon Titan Text Embeddings V2** produces normalized 512-dimensional embeddings when Bedrock is enabled.
- **Amazon Nova Lite** uses the Bedrock Converse API to summarize the retrieved resolution, outcome, and provenance while preserving uncertainty.
- **SQLite and a deterministic local embedder** provide a credential-free development and test mode with the same resolved-only and threshold behavior.
- **Docker** packages the API, while Docker Compose provides a loopback-only single-node CockroachDB development stack.

The CockroachDB Cloud, Bedrock, Managed MCP, and public AWS hosting paths still require live credentials and end-to-end verification. No ECS/Fargate or public URL claim should be added unless that deployment is actually running.

## CockroachDB tools used

### 1. Distributed Vector Indexing

The CockroachDB code path defines `incident_memories.embedding` as `VECTOR(512)` and creates `incident_memory_embedding_idx` on `(service, embedding vector_cosine_ops)`. Investigation filters by service, excludes the current incident, restricts candidates to resolved incidents with a recorded resolution, applies `MINIMUM_RELEVANCE` (`0.15` by default), and ranks symptom memories using cosine distance. Full symptom, resolution, and outcome memories are then attached as provenance-rich evidence.

**Status:** implemented in source and represented in the local CockroachDB Compose path. A live CockroachDB Cloud run must be completed and shown before submission.

### 2. CockroachDB Cloud Managed MCP Server

`CockroachDBMCPClient` performs a bounded audit of one recalled incident through Managed MCP `select_query`. The client owns the SQL; users cannot supply arbitrary statements. It validates the UUID, limits results to at most 100 rows, excludes vectors from the audit response, rejects write tools before invocation, supports cluster scoping, and redacts credential-shaped values from normalized output.

**Status:** the client is integrated into `/investigate`, rendered in the UI, and covered by contract and application tests. A real CockroachDB Cloud cluster and cluster-scoped read-only credentials are still required for live verification.

Select **Distributed Vector Indexing** and **MCP Server** in Devpost only after both have been exercised against the live competition environment.

## AWS services used

### Amazon Bedrock

The source integrates two Bedrock model paths:

- `amazon.titan-embed-text-v2:0` for normalized 512-dimensional embeddings;
- `amazon.nova-lite-v1:0` through Converse for grounded, uncertainty-aware recommendations.

**Status:** implemented in source and covered by mocked/contract behavior, but live AWS credentials, model access, and an end-to-end Bedrock smoke test are still required.

Do not list Amazon ECS, Fargate, ECR, ALB, Secrets Manager, or a specific IAM runtime role as used until those resources exist and power the public demo. A Dockerfile or deployment plan is not proof of deployment.

## Challenges

The hardest design problem was preserving the difference between a resolution someone tried and the outcome they later observed. RecallOps stores them as separate memory events, includes both in recommendation evidence, and retrieves only resolved precedents above a relevance threshold. We also made each state transition atomic so an embedding failure cannot commit only half of the story.

The Managed MCP audit required a second safety boundary. Instead of accepting arbitrary SQL, the client creates one bounded query from a validated UUID, allowlists one read-only tool, adapts cautiously to the server schema, and fails closed when the contract is unfamiliar.

## Accomplishments

- A working local remember -> resolve -> recall -> reason loop.
- Atomic incident, resolution, and memory writes with rollback tests.
- Resolved-only, same-service retrieval with a configurable threshold.
- Recommendation payloads containing recorded outcomes and complete source provenance.
- A concrete CockroachDB vector schema, distributed index, and cosine-query path.
- A defensive Managed MCP `select_query` audit client with contract tests.
- A per-investigation tool trace and Managed MCP audit receipt in the API and operator console.
- 34 passing tests covering readiness, request tracing, production gates, atomicity, evidence propagation, MCP safety, and the integrated audit flow.
- Optional Titan embedding and Nova reasoning clients.
- A human-approval boundary: RecallOps recommends but never mutates infrastructure.

These are source and local-test accomplishments. They are not a claim of production traffic or a completed public deployment.

## What we learned

Useful agent memory needs more than semantic similarity. Event type, source ID, service scope, status, timestamp, embedding provenance, and the difference between a resolution and its outcome all affect whether a precedent is safe to surface. We also learned that a configuration flag is not integration evidence: CockroachDB Cloud, Bedrock, and Managed MCP must each be demonstrated with a real request.

## What's next

First, connect the implemented paths to one live competition environment: CockroachDB Cloud over TLS, Amazon Bedrock with least-privilege credentials, the Managed MCP audit using a read-only service account, and a public HTTPS deployment on AWS. Then add live integration tests and retain redacted deployment evidence for the video.

After submission readiness, the next product steps are tenant-scoped RBAC, dependency readiness probes, evaluation traces, Bedrock Guardrails, CloudWatch ingestion, multi-region locality, and approval-gated execution for carefully bounded remediations.

## Built with

Python, FastAPI, Pydantic, SQLAlchemy, CockroachDB, CockroachDB Distributed Vector Indexing, CockroachDB Cloud Managed MCP Server, Amazon Bedrock, Amazon Titan Text Embeddings V2, Amazon Nova Lite, boto3, Docker, SQLite, HTML, CSS, and JavaScript.

## Try it out

Current local instructions:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
python -m pytest -q
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. Create the prefilled incident, save its resolution and outcome, select **Create similar incident**, and then select **Recall related incidents**. The default configuration uses SQLite and local deterministic embeddings; it does not prove the cloud integrations.

For exact API and Managed MCP commands, use the root `README.md`.

## Required links

- Public source repository: `[ADD PUBLIC GITHUB REPOSITORY URL]`
- Functional public AWS demo: `[ADD PUBLIC HTTPS AWS DEMO URL]`
- Public YouTube or Vimeo video under three minutes: `[ADD PUBLIC VIDEO URL]`
- Public MIT license: `[ADD PUBLIC REPOSITORY URL]/blob/main/LICENSE`

Do not replace a required URL with localhost, a private dashboard, a screenshot, or a repository-only deployment plan.

## Suggested gallery assets

- Project cover: `assets/devpost-cover.png`
- Operator-console screenshot: `[ADD IMAGE]`
- Architecture diagram showing both CockroachDB tools and Bedrock: `assets/architecture.png` and `output/pdf/recallops-architecture.pdf`
- CockroachDB vector-memory evidence screenshot: `[ADD IMAGE]`
- Managed MCP `select_query` audit screenshot with secrets removed: `[ADD IMAGE]`

## Additional information fields

- **Project license:** MIT.
- **CockroachDB tools:** Distributed Vector Indexing and MCP Server, after live verification.
- **AWS service:** Amazon Bedrock, after live verification. Add hosting services only if actually deployed.
- **Data statement:** demo incident text is operator-provided synthetic data; no external dataset is required by the current project.
- **Execution boundary:** the system recommends investigation steps and does not execute remediation.
- **Current deployment status:** local/source implementation; public cloud verification pending.

The entrant must personally complete team membership, country/residency, age, employment, originality/new-work, rules acceptance, privacy, tax, and other eligibility attestations. Do not infer or automate those answers.

## Demo video script (target 2:50)

Record this only after the public deployment, CockroachDB Cloud vector path, Bedrock calls, and Managed MCP call have all succeeded. Remove any step that cannot be shown truthfully.

**0:00-0:15 - Problem and promise.** Show the RecallOps operator console. Explain that incident timelines often lose the distinction between what was tried and what operators observed.

**0:15-0:35 - Architecture.** Show the architecture graphic. Name the two CockroachDB tools: Distributed Vector Indexing for recall and Managed MCP `select_query` for read-only evidence audit. Name Amazon Bedrock for Titan embeddings and Nova reasoning.

**0:35-1:05 - Remember atomically.** On the public app, create the checkout incident and resolve it. Show the CockroachDB Cloud rows for the incident plus separate `symptoms`, `resolution`, and `outcome` memories. Point out source IDs, timestamps, and embedding provenance.

**1:05-1:30 - Explain the safety filters.** Briefly show that only same-service, resolved incidents above the relevance threshold can be returned. Mention that create and resolve each commit once and roll back on embedding failure.

**1:30-2:00 - Recall and reason.** Create the similar incident and investigate it. Show the source incident ID, relevance, recorded outcome, full evidence, and the Nova-generated uncertainty-aware recommendation. State that no remediation was executed.

**2:00-2:25 - Audit through Managed MCP.** In the same investigation result, show the completed Managed MCP `select_query` receipt and tool trace. Show that its source incident matches the top recommendation. Keep credentials and connection strings off screen.

**2:25-2:50 - Proof and close.** Show the public URL, `/system`, the public repository and MIT license, and the passing test summary. Clarify that `/system` reports configuration while the requests just shown are the live integration proof.

## Final submission checklist

### Product and integration

- [x] Local incident memory loop implemented.
- [x] Atomic write and rollback behavior implemented and tested.
- [x] Resolved-only retrieval and relevance threshold implemented.
- [x] Outcome and provenance included in recommendation evidence.
- [x] Distributed Vector Indexing code path implemented.
- [x] Managed MCP read-only audit client and contract tests implemented.
- [x] Bedrock embedding and reasoning code paths implemented.
- [ ] CockroachDB Cloud TLS connection verified with the final application.
- [ ] Distributed vector index and retrieval visibly verified on CockroachDB Cloud.
- [ ] Bedrock Titan and Nova requests verified with the final AWS runtime credentials.
- [ ] Managed MCP `select_query` verified with a cluster-scoped read-only service account.
- [x] MCP audit exposed through the application and displayed as part of the agent workflow.
- [ ] Public HTTPS application deployed on AWS and tested end to end.

### Submission assets

- [ ] Public source repository URL added.
- [ ] Root MIT license visible in the public repository.
- [ ] Public AWS demo URL added and available for the full judging period.
- [ ] Public YouTube/Vimeo video is under three minutes.
- [ ] Video visibly proves vector retrieval, Bedrock reasoning, and the MCP audit.
- [ ] Generated cover, architecture image, UI screenshot, and memory/audit evidence uploaded.
- [ ] Devpost project name changed from any earlier draft name to RecallOps.
- [ ] Devpost text matches the final deployed behavior and services.
- [ ] Every placeholder removed.
- [ ] Entrant completed all personal and legal attestations.

Do not submit while a mandatory live-integration, URL, video, or eligibility item remains unchecked.
