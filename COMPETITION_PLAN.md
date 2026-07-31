# RecallOps prize plan

Last reviewed: July 31, 2026

Official sources:

- Hackathon overview: https://cockroachdb-ai.devpost.com/
- Official rules: https://cockroachdb-ai.devpost.com/rules
- Schedule: https://cockroachdb-ai.devpost.com/details/dates
- Resources and FAQ: https://cockroachdb-ai.devpost.com/resources
- CockroachDB Cloud MCP: https://www.cockroachlabs.com/docs/cockroachcloud/connect-to-the-cockroachdb-cloud-mcp-server

## Goal and hard deadline

Build and submit a truthful, fully demonstrable, prize-caliber incident-response agent before **August 18, 2026 at 5:00 PM EDT** (**August 19 at 2:30 AM IST**). The project must remain available to judges through September 15, 2026.

The internal target is **August 16** so there is a two-day buffer for Devpost, video, hosting, and account issues.

## Stage One: pass/fail compliance

Every item in this section is mandatory.

- [x] Project was created during the submission period. Local file timestamps begin July 31, 2026.
- [x] Agentic memory use case: incidents, symptoms, resolutions, and outcomes form a persistent operational-memory loop.
- [ ] Production demo uses CockroachDB Cloud as the persistent system of record.
- [ ] Production demo is deployed on AWS and remains available throughout judging.
- [x] CockroachDB tool 1: Distributed Vector Indexing is implemented in the production code path.
- [ ] CockroachDB tool 2: Managed MCP Server is implemented and integrated; it still needs a cluster-scoped read-only service account and live demo proof.
- [x] AWS service code path: Amazon Bedrock supports Titan embeddings and Nova reasoning.
- [ ] At least one AWS service is live and demonstrably powers the deployed project.
- [x] Public open-source repository contains all code, setup instructions, example configuration, and a root MIT license.
- [ ] Free functional demo URL is available to judges until September 15.
- [ ] Public YouTube or Vimeo demo is under three minutes, shows the project working, and visibly shows the CockroachDB memory layer.
- [x] Devpost project story names both CockroachDB tools and Amazon Bedrock with their actual agent roles; the saved Additional Info selections identify the same tools and service.
- [x] Devpost project story names Amazon Bedrock and explains Titan embedding and Nova reasoning roles.
- [ ] All required Devpost fields, eligibility attestations, and personal details are completed by the entrant.

Do not submit while any mandatory item is unchecked.

## Current gaps

| Priority | Gap | Why it matters | Exit condition |
| --- | --- | --- | --- |
| P0 | Managed MCP is integrated but not live-verified | Automatic Stage One failure if the live demo does not prove it | Configure the read-only service account, exercise the integrated audit against CockroachDB Cloud, and show its receipt in the video |
| P0 | No verified AWS deployment | The challenge requires deployment on AWS | Public HTTPS endpoint runs the production configuration and passes an end-to-end smoke test |
| P0 | No live demo or video URLs | Required submission deliverables | Add a public AWS demo URL and a public YouTube/Vimeo video URL to Devpost |
| P0 | No public demo video | Required submission deliverable | Public YouTube/Vimeo video is under 3:00 and shows vector memory plus MCP audit |
| Done | Devpost and product naming diverged | Confusing and weakens credibility | Devpost, repository, UI, and generated assets now use RecallOps |
| Done | Saved Devpost story described a generic planned system | Claims did not match the working product | Project story now describes the implemented incident-response memory loop |
| Done | Incident and memory writes were not atomic | Contradicted readiness claims | One transaction now commits state plus all related memory events, with rollback tests |
| Done | Outcome and provenance were not returned to the reasoner | Weakened memory design | Recommendations now expose structured memory evidence and recorded outcomes |
| P1 | Sponsor cloud paths still lack live integration tests | Core sponsor integrations are not yet externally proven | Contract/API tests pass; a recorded CockroachDB Cloud + MCP + Bedrock smoke test remains |
| P1 | Submission visuals are only partially complete | Judges rely heavily on the gallery and video | Cover and architecture assets exist; capture the deployed UI, vector rows, and MCP receipt |

## Strategy for the five judging criteria

Each criterion is equally weighted. Agentic Memory Design is also the first tie-break criterion.

### 1. Agentic Memory Design

- Keep incident state and append-only evidence in CockroachDB.
- Store symptom, resolution, and outcome memories separately with source IDs, timestamps, and provenance.
- Retrieve only same-service, resolved precedents with a relevance threshold.
- Use the distributed vector index for semantic recall.
- Use Managed MCP `select_query` as a bounded, read-only audit step that verifies the exact recalled evidence against CockroachDB Cloud.
- Make the agent act on memory by changing its recommended investigation path while never claiming remediation was executed.

### 2. Technical Implementation

- Make state and memory writes atomic.
- Scope MCP to one cluster and a read-only service account; allowlist only `select_query`.
- Validate UUIDs, bound queries, limit results, set timeouts, and redact secrets.
- Fail fast when production is not connected to CockroachDB, Bedrock, or MCP.
- Add contract tests for vector SQL, MCP argument construction, failures, and transaction rollback.

### 3. Real-World Impact

- Demonstrate a credible on-call workflow: a prior incident records what was tried and what operators observed; a later incident recalls the safest precedent in seconds.
- Show why generic RAG is insufficient: attempted fixes and observed outcomes remain distinct and auditable.
- Quantify the value in the story and video using clearly labeled demo measurements, not unsupported production statistics.

### 4. Product Readiness

- HTTPS AWS deployment, health/readiness endpoints, API-key protection, request IDs, structured logs, and least-privilege service accounts.
- Clear failure behavior: no fallback to local providers in production and no fabricated answer when Bedrock or MCP is unavailable.
- Reproducible deployment and rollback instructions.
- Keep the judging demo online and test it daily through September 15.

### 5. Creativity and Originality

- Position RecallOps as an evidence ledger for incident response, not a generic chatbot.
- Make the core insight visible: a proposed remediation is not trusted until its observed outcome becomes a separate memory event.
- Show dual-path recall: vector search discovers precedent; MCP verifies exact source evidence through a standard agent tool boundary.

## Delivery schedule

### July 31-August 3: eligibility and memory integrity

- Implement atomic memory writes, structured evidence, resolved-only retrieval, and correct score labeling.
- Add Managed MCP client and tests.
- Fix encoding and naming inconsistencies.
- Expand automated tests.

### August 4-7: live sponsor integrations

- Create CockroachDB Cloud cluster.
- Configure vector schema/index and seed the demo scenario.
- Create a cluster-scoped, read-only MCP service account and verify `select_query`.
- Configure Amazon Bedrock and run a complete production-mode investigation.

### August 8-11: AWS deployment and hardening

- Deploy the container on AWS ECS/Fargate or another clearly documented AWS runtime.
- Configure HTTPS, secrets, task role, health checks, logs, and API key.
- Run fresh-install, concurrency, provider-failure, and end-to-end smoke tests.
- Publish the repository with a visible MIT license.

### August 12-14: judging assets

- Capture the UI, CockroachDB rows/vector index, MCP audit evidence, and `/system` provider status.
- Create a clean architecture diagram and 3:2 project thumbnail.
- Record a 2:30-2:45 demo video with no unlicensed music or third-party footage.

### August 15-16: final submission

- Replace every placeholder and conditional claim with verified facts.
- Complete personal and eligibility fields manually.
- Test every public URL in a signed-out browser.
- Submit by August 16 and retain screenshots of the final confirmation.

## Video proof sequence (target 2:40)

1. **0:00-0:20 — problem and value:** incident knowledge is scattered; RecallOps preserves recorded outcomes.
2. **0:20-0:45 — architecture:** AWS runtime, Bedrock, CockroachDB transactional memory, vector index, and Managed MCP audit.
3. **0:45-1:15 — remember:** create and resolve an incident; show separate symptom, resolution, and outcome rows.
4. **1:15-1:50 — recall:** create a similar incident and show the service-scoped vector result with source ID and relevance.
5. **1:50-2:15 — verify:** show the MCP audit reading the exact source memories through the cluster-scoped read-only connection.
6. **2:15-2:40 — reason and safety:** show Nova's grounded recommendation, provenance, provider status, and the human approval boundary.

## Entrant-only decisions and actions

Codex must not guess or attest to these items:

- individual/team/organization status and team membership;
- country of residence, age/majority, employment/conflict eligibility, or legal attestations;
- whether any pre-existing code or third-party work was incorporated;
- authorization to make a repository public, deploy into an AWS account, incur cloud charges, publish a video, or finally submit the entry.
