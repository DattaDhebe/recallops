# AWS ECS Fargate delivery template

These files are deployment templates, not evidence of a deployment. They keep
the AWS path reproducible while leaving account-specific identifiers and
credentials as explicit placeholders.

## Intended shape

An Application Load Balancer sends HTTP traffic to one or more private-subnet
ECS Fargate tasks on port `8000`. The tasks run the repository's container as
the image user `recallops`, use a read-only root filesystem, call Amazon
Bedrock through the task role, connect to CockroachDB Cloud, and use the
CockroachDB Cloud Managed MCP endpoint over HTTPS. CloudWatch receives the
container logs.

The task definition enables all production integration gates:

- `COMPETITION_MODE=true`
- `USE_BEDROCK=true`
- `REQUIRE_COCKROACHDB=true`
- `USE_COCKROACH_MCP=true`

It deliberately supplies `DATABASE_URL`, `API_KEY`,
`COCKROACH_MCP_API_KEY`, and `COCKROACH_MCP_CLUSTER_ID` through the ECS
`secrets` mechanism. Do not move them into plaintext `environment` entries,
image layers, source control, CI logs, or Devpost content.

## Placeholders to render

Create a rendered copy of `task-definition.json`; keep the committed template
unchanged. Replace every angle-bracket value:

| Placeholder | Expected value |
| --- | --- |
| `<AWS_ACCOUNT_ID>` | AWS account containing the ECR repository |
| `<AWS_REGION>` | One region used by ECS, logs, secrets, and Bedrock |
| `<IMMUTABLE_IMAGE_TAG>` | A commit SHA or image digest-backed tag, not `latest` |
| `<ECS_TASK_EXECUTION_ROLE_ARN>` | ECS execution role ARN |
| `<ECS_TASK_ROLE_ARN>` | Application task role ARN |
| `<DATABASE_URL_SECRET_ARN>` | Secrets Manager ARN containing only the CockroachDB connection URL |
| `<API_KEY_SECRET_ARN>` | Secrets Manager ARN containing only the application API key |
| `<COCKROACH_MCP_API_KEY_SECRET_ARN>` | Secrets Manager ARN containing only the MCP service-account API key |
| `<COCKROACH_MCP_CLUSTER_ID_PARAMETER_ARN>` | SSM SecureString parameter ARN containing only the cluster ID |
| `<COCKROACH_DATABASE_NAME>` | CockroachDB database name, for example `defaultdb` |
| `<HTTPS_APPLICATION_ORIGIN>` | Exact HTTPS browser origin allowed by CORS |
| `<CLOUDWATCH_LOG_GROUP>` | Pre-created log group, for example `/ecs/recallops` |

Use one plaintext value per Secrets Manager secret or SSM SecureString
parameter. If an existing secret is JSON, use the documented ECS
`valueFrom` JSON-key ARN suffix instead of passing the entire JSON object as an
environment variable.

## IAM boundaries

Keep the two ECS roles separate:

1. The **task execution role** pulls the ECR image, writes CloudWatch logs,
   and reads exactly the three secret ARNs and one SSM parameter ARN referenced
   by the task definition. Start with
   `AmazonECSTaskExecutionRolePolicy`, then add a small inline policy scoped to
   those four resources for `secretsmanager:GetSecretValue` and
   `ssm:GetParameters`. Add `kms:Decrypt` only for a customer-managed KMS key,
   scoped to that key.
2. The **task role** is the application's AWS identity. Attach the rendered
   `bedrock-policy.json`. It grants only `bedrock:InvokeModel` on the exact
   Nova reasoning model and Titan embedding model configured in the task.

The application currently makes non-streaming Bedrock calls, so this template
does not grant `bedrock:InvokeModelWithResponseStream`. If model IDs or the AWS
region change, update both task environment values and the policy ARNs. If a
cross-region inference profile is selected, replace the resources with the
exact inference-profile and destination foundation-model ARNs required by
Bedrock; do not broaden them to `*`.

The CockroachDB database user and MCP service account should independently be
read-only and limited to the application cluster/database. The application's
MCP client also allowlists only `select_query`; IAM and database permissions
remain necessary defense in depth.

## Readiness gate

Both the ECS container health check and the load balancer target group should
probe `GET /ready`. Do not register the service or record a demo until the
built image returns HTTP `200` there only when startup and required database
checks have succeeded. The health command uses Python's standard library, so
it does not assume `curl` is installed in the slim image.

Suggested target-group settings are a 30-second interval, 5-second timeout,
three healthy/unhealthy thresholds, and a 60-second ECS health-check grace
period. Enable the ECS deployment circuit breaker with rollback.

## Network and secret posture

- Run tasks in private subnets with `assignPublicIp=DISABLED`.
- Permit inbound port `8000` only from the load balancer security group.
- Terminate public TLS at the load balancer with an ACM certificate. Redirect
  port 80 to 443 rather than forwarding plaintext traffic.
- Restrict task egress to DNS plus the CockroachDB SQL endpoint/port and HTTPS
  destinations needed for Bedrock, Managed MCP, logs, ECR, and secrets. VPC
  endpoints can keep AWS service traffic private.
- Set secret rotation and CloudWatch log retention deliberately. Never print
  SQL connection URLs, authorization headers, or raw MCP responses.
- Protect the public demo against unbounded use with the application API key,
  load-balancer/WAF rate limits, and conservative ECS desired count.

## Registration outline

This is an operator checklist, not a claim that these commands have run:

1. Build the image for `linux/amd64`, scan it, push it to ECR, and retain its
   digest.
2. Create the log group, secrets/parameter, IAM roles, VPC networking, target
   group, HTTPS listener, and ECS cluster.
3. Render the placeholders into files outside source control.
4. Validate and register the rendered task definition:

   ```bash
   python -m json.tool infra/aws/task-definition.rendered.json
   aws ecs register-task-definition \
     --cli-input-json file://infra/aws/task-definition.rendered.json
   ```

5. Create or update an ECS Fargate service with private subnets, the task
   security group, load-balancer target group, health-check grace period, and
   deployment circuit breaker/rollback enabled.
6. Verify `/ready`, `/health`, a complete incident memory round trip,
   CockroachDB vector retrieval, the read-only MCP audit, and a Bedrock-backed
   investigation before publishing the demo URL.
7. Keep the service functional through the competition judging window, while
   configuring AWS Budgets and alarms to prevent an unexpected bill.
