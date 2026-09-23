# AWS infrastructure, in two tiers

**Status:** Draft, for the user to read before anything is created · 2026-09-23

> **Nothing in this plan has been built, and nothing should be built from it
> until you have read it and said so.** There is no "start now" step. The first
> action in the runbook is a decision, not an `apply`.

## Goal

**Tier 0** — the cheapest arrangement that runs *this* application, as *this*
artifact, on AWS, holding *your own* EoE record and nobody else's, with backups
that have actually been restored. Measured cost: **$39/month in month 1 and
$62/month once the twelve-month free tier ends**, if your account is on the old
free tier; **$62/month from day one** if it is on the credit-based plan AWS
introduced for newer accounts. Both numbers are itemised below from the AWS
price list, queried today.

**Tier 1** — the posture required before anyone else's data is in it: two
accounts under an Organization, Multi-AZ RDS, compute in private subnets behind
CloudFront and WAF, a promoted-by-digest production release with a human gate.
Measured at **$256/month** across both accounts, which tests the product plan's
$250–300 claim and finds it sound.

The section *Tier 1: what changes* says which of those differences is a resize
and which is a rebuild, because the rebuilds are the decisions tier 0 has to get
right on the first `apply`.

## Clinical basis

No instrument, threshold, or patient-facing wording changes. Four infrastructure
properties have direct clinical or patient consequence, and each is designed
for explicitly below:

- **The audit trail must name the person, not the network.** `audit_log.ip_address`
  and the rate limiter both read `request.client.host`. Measured today against the
  running stack (see *What was verified*), every audit row records `10.89.0.8` —
  the container network's gateway — not the client. Behind an ALB that becomes the
  balancer's address, and "who looked at my record" stops being answerable.
- **Magic-link email is the only way into the product, so deliverability is
  uptime.** A link in a spam folder is a patient locked out of their own health
  record, and it fails silently. SPF, DKIM, DMARC, a custom MAIL FROM domain,
  and bounce/complaint alarms are therefore in tier 0, not deferred.
- **The backup is the record.** This is one person's multi-year EoE history.
  A restore that has never been performed is not a backup, and a restore that
  produces rows whose encrypted notes no longer decrypt is not a restore. The
  drill below decrypts a note.
- **Row-level security has never run against a live application.** It does now:
  the whole API was driven end to end as `app_runtime` during this design and it
  works. Tier 0 is where that becomes a deployed fact rather than a test fixture.

Nothing here is pending clinical confirmation.

## Scope

**In scope**

- Tier 0: one AWS account, Terraform, VPC, ALB, ECS Fargate, RDS PostgreSQL,
  ElastiCache, ECR, Secrets Manager, KMS, S3 (state, audit archive, logical
  dumps), Route 53, ACM, SES, CloudWatch, CloudTrail, Budgets.
- Tier 1: the second account, the Organization, Multi-AZ, private subnets and
  NAT, CloudFront, WAF, GuardDuty, the promote-with-approval release path.
- The DNS cutover from Squarespace, with the record export that has to happen
  first.
- GitHub OIDC, the publish/deploy/promote workflows, where migrations run in
  that sequence, and how a bad release is reverted.
- The `ENVIRONMENT` assertion as a CI check on the rendered task definition.
- The S3 Object Lock archive for `audit_log`.
- Four application changes this design depends on, each named with its file.

**Out of scope**

- SOC 2, the penetration test, entity formation, insurance. Not infrastructure.
- Error tracking (Sentry) and its BAA. Adjacent, and its own decision.
- Any DR beyond single-region: tier 1 is one region with cross-region backup
  copies, not a warm standby. Multi-region is not justified at this size and
  would roughly double the bill.
- Container image hardening beyond what ADR 0006 already asserts.
- A CSP header. `apps/web/nginx/security-headers.conf` has none today; that is
  an application change and belongs in its own feature.

## What was verified, and what is inferred

Everything in this section was run today against the stack in this repository or
queried from the AWS public price list. The distinction matters because the
claims a plan makes about *the system as it is* get acted on without being
rechecked.

### Verified by running it

**1. The application runs end to end as `app_runtime`.** This is the most
consequential finding in the plan, and it contradicts what
`docs/plans/2026-09-19-build-system-and-deploy-path.md` predicted.

A second API container was started against the development database with
`DATABASE_URL=postgresql+asyncpg://app_runtime:…@postgres:5432/eoehelp` — the
role that owns no tables — and driven with curl:

| Path | Result as `app_runtime` |
|---|---|
| Startup, incl. `verify_published_revisions` reading `legal_documents` | ok |
| `POST /auth/magic-link`, `POST /auth/magic-link/verify` | 202, 200 |
| `POST /me/onboarding` (inserts `patients`, `consents`, `research_consent_scopes`) | **201** |
| `GET`/`PATCH /me/profile` | 200 |
| `PUT`/`GET /me/symptoms/{date}` incl. an encrypted note | 200 |
| `POST`/`GET /me/foods`, `/me/foods/recent`, `/me/foods/ingredients` | 201, 200 |
| `POST /me/medications`, `/me/medications/today`, `/adherence` | 201, 200 |
| `POST /me/endoscopies` with a biopsy and a dilation | **201** |
| `GET /me/insights/food-patterns`, `/me/symptoms/burden` | 200 |
| `DELETE /me` (account deletion) | **204** |

The build plan expected onboarding to fail, on the reasoning that the `patients`
policy has no explicit `WITH CHECK` so `USING` governs INSERT and sign-up has no
scope yet. The first half is true — confirmed from `pg_policies`, every policy is
`FOR ALL` with a `qual` and a null `with_check`, so `qual` governs INSERT. The
second half is no longer true: `identity/onboarding_service.py` mints the patient
id *before* the insert and calls `apply_rls_scope` with it, with a comment saying
exactly why. The gap was closed by a later commit than the one the build plan was
written against.

**Consequence: tier 0 should not wait for the stage-4 spike. Tier 0 *is* the
spike, in the environment where it matters.** The service connects as
`app_runtime` from the first deploy, migrations run as a separate task under the
owner, and a post-deploy gate proves both (below).

**2. The row-level security catalogue, read from `pg_class` and `pg_policies`,
not from the migrations.** Twelve tables have `relrowsecurity = true`:
`patients`, `consents`, `research_consent_scopes`, `symptom_entries`,
`medications`, `medication_doses`, `custom_ingredients`, `food_log_items`,
`food_log_item_ingredients`, `endoscopies`, `biopsies`, `dilations`. Each has
one `patient_isolation` policy, `FOR ALL`, `qual` =
`patient_id = NULLIF(current_setting('app.current_patient_id', true), '')::uuid`
(`patients` uses `id`). No table has `relforcerowsecurity`, which is correct and
irrelevant while the app never connects as the owner.

Four tables have no RLS and hold identity or system data: `users`,
`magic_link_tokens`, `refresh_tokens`, `audit_log`. That is ADR 0002's design —
they are not patient-scoped by `patient_id` — but it means `app_runtime` can read
every row of `users` if a query ever forgets its filter. Not this plan's to fix;
recorded so the tier-1 review has it.

**3. `app_runtime` cannot migrate.** `information_schema.table_privileges` shows
no grant of any kind to `app_runtime` on `alembic_version`. The deploy contract's
split — migrations as a separate task under the owner, service as `app_runtime` —
is enforced by the database, not by convention. Good.

**4. `FORWARDED_ALLOW_IPS` behaviour, measured, not read.** With no
`FORWARDED_ALLOW_IPS`, a request carrying `X-Forwarded-For: 203.0.113.77` through
the container network produced an audit row with `ip_address = 10.89.0.8` — the
hop. Restarting the same container with `FORWARDED_ALLOW_IPS=10.89.0.0/24`
produced `ip_address = 203.0.113.77`. So: **CIDR notation works**, and the value
is compared against the *peer* address.

Reading `uvicorn.middleware.proxy_headers` (0.53.0, from inside the image) gives
the part that matters for tier 1. `_TrustedHosts.get_trusted_client_address`
walks `X-Forwarded-For` **right to left and returns the first host that is not
trusted**. Two consequences:

- With an ALB directly in front, `FORWARDED_ALLOW_IPS` = the subnet CIDRs is
  correct *and* spoof-resistant: a client that sends its own `X-Forwarded-For`
  gets it appended to, not replaced, so the rightmost entry is still the real
  client.
- **Adding CloudFront in front of that ALB silently breaks it.** The peer is
  still the ALB, so the header is read; but the rightmost entry becomes a
  CloudFront edge address, which is not in the trusted set, so every audit row
  would record CloudFront. The tier-1 design below handles this.

**5. The rate limiter shares one bucket per hop.** During the probe runs, the
magic-link limit (`5/15 minutes`) tripped across *different* synthetic accounts,
because every request arrived from `10.89.0.8`. This is the same defect as (4),
observed from the other side, and it is why `FORWARDED_ALLOW_IPS` is a tier-0
requirement rather than a tier-1 refinement.

**6. Image sizes**, for ECR cost: API runtime 366 MB uncompressed, web runtime
593 MB uncompressed (`podman images`). Budgeted below at ~1.5 GB of compressed
ECR storage for a five-deep retention of both.

### Verified by querying the AWS price list

Fetched today from `pricing.us-east-1.amazonaws.com/offers/v1.0/aws/…`, region
`us-east-2`. These are list prices, not a quote:

| Item | Price |
|---|---|
| Application Load Balancer | $0.0225/hr; LCU $0.008/LCU-hr |
| Public IPv4 address (in-use or idle) | $0.005/hr = **$3.65/month each** |
| Fargate **ARM64** | $0.03238/vCPU-hr, $0.00356/GB-hr |
| Fargate x86 (for comparison) | $0.04048/vCPU-hr, $0.004445/GB-hr |
| RDS PostgreSQL db.t4g.micro | Single-AZ $0.016/hr, Multi-AZ $0.032/hr |
| RDS PostgreSQL db.t4g.small | Single-AZ $0.032/hr, Multi-AZ $0.065/hr |
| RDS gp3 storage | Single-AZ $0.115/GB-mo, Multi-AZ $0.23/GB-mo |
| RDS backup beyond the free allocation | $0.095/GB-mo |
| ElastiCache cache.t4g.micro | Redis $0.016/hr, **Valkey $0.0128/hr** |
| NAT gateway | $0.045/hr + $0.045/GB processed |
| VPC interface endpoint | $0.01/hr per endpoint per AZ ($7.30/month) |
| Secrets Manager | $0.40/secret/month + $0.05/10k API calls |
| KMS | **$1.00 per customer-managed key *version* per month** + $0.03/10k requests |
| Route 53 | $0.50/hosted zone/month; $0.40/M queries; **alias queries to AWS resources free** |
| ECR storage | $0.10/GB-month |

Two of these changed the design. **Valkey is 20% cheaper than Redis on the same
node class** and is wire-compatible, so ElastiCache runs Valkey. And KMS bills
per key *version*, so enabling automatic annual rotation on a CMK adds $1/month
every year — worth knowing before turning it on for four keys.

### Inferred, not verified — check these before spending

- **Which free-tier model your account is on.** AWS changed the free tier for
  accounts created after roughly mid-2025: instead of twelve months of
  service-specific allowances, new accounts get a signup credit plus a "Free
  plan" that can *suspend resources when the credit is exhausted*. I could not
  confirm the current terms (the documentation page is JavaScript-rendered and
  returned no text). **This is the single most important thing to check before
  putting real data anywhere**, because on the new model the failure mode is not
  a larger bill, it is suspension. Billing console → Free Tier, and Billing →
  Account plan. Both cost models are priced below. If the account is on a Free
  plan, upgrade it to a Paid plan *before* the first real symptom entry.
- Whether ElastiCache's free-tier allowance covers Valkey as well as Redis on
  `cache.t4g.micro`. If not, tier 0 month 1 is $9.34 higher than stated.
- Whether ALB public IPv4 addresses are billed (I have priced them as billed;
  if not, subtract $7.30/month from every total).
- **Which services are HIPAA-eligible under the current AWS BAA.** Every service
  in this plan is on the list as far as I know, but the list is the authority and
  it changes. Read it in AWS Artifact alongside the BAA itself. Two services this
  plan *rejects* partly on eligibility grounds — App Runner and Lightsail — should
  be checked rather than taken from me.
- App Runner's architecture support. I believe it is x86-only, which is decisive
  here; confirm from its documentation before dismissing it on that ground.

## Tier 0

One AWS account. One region. One availability zone doing work, two with subnets
because an ALB requires it. Real PHI — yours.

```
Squarespace (registrar only)
  └── NS → Route 53 hosted zone  eoehelp.org
        ├── A  ALIAS  eoehelp.org      → ALB
        ├── A  ALIAS  www.eoehelp.org  → ALB (redirect rule → apex)
        ├── CAA, SES DKIM x3, MAIL FROM MX+SPF, DMARC
        └── ACM cert (DNS-validated) on the ALB

        ALB :443 (ACM)  ── /api/v1/*  → target group api  → task :8000
                        └─ default    → target group web  → task :8080
                             │
             ECS Fargate service, 1 task, ARM64, public subnet, no NAT
               ├── container `web`  nginx, the promoted image digest
               └── container `api`  uvicorn, the promoted image digest
                     ├── RDS PostgreSQL db.t4g.micro, single-AZ, CMK-encrypted
                     ├── ElastiCache Valkey cache.t4g.micro
                     ├── Secrets Manager (one JSON secret + the RDS managed one)
                     ├── SES (SMTP, STARTTLS :587)
                     └── CloudWatch Logs

        S3: terraform state · audit archive (Object Lock) · logical dumps
        ECR: eoehelp-api, eoehelp-web — immutable tags, scan on push
```

### 1. The host: why ECS Fargate and not the cheaper options

The brief asked for this to be argued rather than inherited from the product
plan. It was, and the product plan's answer survives — but for a different
reason than the product plan gives.

| Option | Monthly (tier 0 shape) | Why not |
|---|---|---|
| **ECS Fargate + ALB** | **$62 list / $39 with free tier** | Chosen. |
| App Runner | ~$25–40 | **x86-only.** ADR 0005 and 0006 make ARM64 end-to-end a property CI asserts, and ADR 0006 makes "production runs the digest that passed the tests" the point of the whole build. An x86 host means a second image built from the same source but never tested — exactly the artifact-provenance weakness ADR 0006 exists to remove. Also cannot reach a private RDS without a VPC connector, and its HIPAA eligibility needs checking. |
| Lightsail containers | ~$10–17 | x86-only, same problem. And I do not believe Lightsail is HIPAA-eligible, which ends it for real PHI regardless of price. |
| One EC2 instance (t4g.small) running the same images under podman | **~$18** | The genuinely cheaper answer, and it deserves a straight comparison rather than a dismissal. See below. |
| API Gateway HTTP API + VPC Link + Cloud Map, no load balancer | ~$45 | Removes the ALB's $24, adds three moving parts, a 10 MB response limit that the M3 PDF report could approach, and a completely different edge from tier 1 — so tier 1 becomes an edge rebuild. Rejected on ADR 0004's "deliberately boring" rule. |
| A Fargate task with a public IP and a Route 53 record updated by a Lambda on task state change | ~$20 | Clever, fragile, and no ACM: TLS would have to terminate in the container with a certificate you renew. Rejected. |

**The EC2 comparison, honestly.** A t4g.small ($12.26) + 30 GB gp3 ($2.40) + one
public IPv4 ($3.65) is about **$18/month**, runs the same arm64 images under the
same compose file the build plan already produces, and would work. What it costs
instead:

- You operate Postgres. No automated backups, no point-in-time recovery, no
  snapshot restore — you build that with `pg_dump` or pgBackRest to S3 and you
  own every part of it. The product plan calls daily backups plus PITR
  "non-negotiable for health data", and RDS gives both as a checkbox.
- One EBS volume, one AZ, no failover, and a `terraform destroy` or an instance
  replacement takes the database with it unless you got the volume lifecycle
  exactly right.
- TLS: no ACM. Let's Encrypt in a container, with renewal, or an ALB anyway.
- And the one that decides it: **tier 1 is then a rebuild, not a resize.** Every
  deploy mechanism — task definitions, the migration task, the service update,
  the digest pinning, the rollback — would be written twice, once for systemd or
  compose on a box and once for ECS. The whole value of tier 0 is that it is the
  real thing in miniature.

So the argument for Fargate is not that it is cheap. It is that **$44/month buys
managed backups with PITR, free auto-renewing TLS, and a tier-1 upgrade path that
is a series of resizes.** If that trade is not worth it to you, the EC2 path is
legitimate and I will design it instead — but say so before the first `apply`,
because switching later is the rebuild.

**Both containers run in one task.** The web container is the promoted image, not
a set of files uploaded to S3. This matters: `apps/web/Dockerfile` carries a
comment saying the build artifact goes to S3 behind CloudFront in AWS, and if it
did, ADR 0006's "production runs the digest that passed the tests" would be only
half true — the SPA would be files extracted from an image rather than the image.
Tier 0 serves the container. Tier 1 keeps serving the container and puts
CloudFront in front of the ALB for caching, so the property holds at both tiers.

**The ALB routes; the containers do not.** `/api/v1/*` → the api target group,
everything else → the web target group. That is exactly what
`infra/local-edge/edge.conf` does in the build plan's `just up-prod`, so local
parity is preserved. A consequence worth stating: the API also serves `/docs` and
`/openapi.json` at the root, outside `/api/v1`, and **with this rule they are
unreachable in every deployed environment** — the SPA's `try_files` fallback
answers them with `index.html`. That is the right outcome (the contract is
committed in `packages/openapi/schema.json` anyway) and it removes the "staging
publishes the full API surface" question entirely.

**Task size:** 0.25 vCPU, 1 GB, ARM64. That is $8.51/month and is ample for one
user. It is a one-line change to 0.5 vCPU when the M3 WeasyPrint report lands
(PDF rendering is CPU-heavy and will be the first thing that feels slow).

**Health checks:** ALB target group health check `GET /healthz` on both targets —
`apps/api/src/eoehelp_api/health.py` deliberately keeps `/healthz` off the
database so a brief Postgres blip does not cycle healthy containers. Declare
`healthCheck` explicitly in the task definition for both containers; ECS does not
use the image's `HEALTHCHECK` instruction. `/readyz` is hit once by the
post-deploy smoke check, not by the balancer.

### 2. Network: no NAT gateway, and what that costs

**Tier 0 puts the Fargate task in a public subnet with `assignPublicIp: ENABLED`
and no NAT gateway.** A NAT gateway is $32.85/month before a byte moves — more
than half the tier-0 bill. The alternative, private subnets with VPC interface
endpoints, is worse: ECR API, ECR DKR, Secrets Manager, CloudWatch Logs and STS
are five endpoints at $7.30 each = $36.50/month, and outbound calls to Open Food
Facts and USDA FoodData Central would still have nowhere to go.

What is given up:

- The task's ENI has a routable public IPv4 address ($3.65/month). Inbound is
  closed by security group: the api and web ports accept traffic only from the
  ALB's security group, and nothing else is open. The address is reachable in the
  sense that packets can arrive; the security group drops them.
- "PHI-processing compute in a public subnet" is a finding at any serious review,
  and it is the single clearest difference between tier 0 and tier 1.
- RDS and ElastiCache stay in the same subnets with `publicly_accessible = false`
  and security groups that accept only the task's security group. They have no
  public address and no route from the internet.

Ad-hoc database access uses **ECS Exec** (`aws ecs execute-command`) into the
running task — no bastion host, no SSH key, and every session is logged to
CloudWatch. Enable `enableExecuteCommand` on the service and give the task role
the three SSM actions.

**VPC layout, sized so tier 1 does not need a new VPC:** `10.20.0.0/16`, two AZs,
four subnets created at tier 0 even though two sit empty —
`10.20.0.0/24` and `10.20.1.0/24` public, `10.20.10.0/24` and `10.20.11.0/24`
private. A subnet cannot change AZ or CIDR later, so they are created now and
tier 1 moves the service into the private pair with a `network_configuration`
change. An S3 gateway endpoint is free; create it at tier 0.

### 3. The four collisions between this codebase and tier 0

Tier 0 must run as `ENVIRONMENT=staging`, because
`identity/documents.enforce_review_status` refuses to start in production while
any of the three onboarding documents is an unreviewed draft — and all three are
(`documents.py` lines 144, 157, 170: `ReviewStatus.DRAFT`). That string then
turns off four other things that have nothing to do with legal review.

`ENVIRONMENT` is currently the axis for five separate questions. It should be
two. The recommended application change — small, and a prerequisite for tier 0 —
is to split them:

| Control | Where | Gated on today | Should be gated on |
|---|---|---|---|
| Refuse unreviewed legal drafts | `identity/documents.py:369` | `== "production"` | unchanged |
| Hide `/docs` | `main.py:84` | `is_production` | unchanged (and the ALB makes it moot) |
| Refuse dev JWT secret, dev field key, dev USDA key, missing Redis, `debug` | `config.py:136` | `is_production` | **`!= "local"`** |
| Send HSTS | `main.py:152` | `is_production` | **`!= "local"`** |
| Refuse to write synthetic data | `synthetic/writer.py:67` | `is_production`, and staging behind a flag | see below |

**Collision 1 — secrets are not enforced in staging. Design the check.**

Three layers, each catching a different failure:

1. **Wiring, in CI.** A new script, `scripts/verify-taskdef.sh`, runs against the
   task definition JSON that Terraform renders (`terraform show -json`, or a
   `local_file` the plan writes) and fails if:
   - `ENVIRONMENT` is not exactly the value that environment's Terraform
     variable declares (`staging` for tier 0, `production` for tier 1's prod
     account) — the assertion the build plan asked for, as a check rather than
     a note;
   - any of `JWT_SECRET`, `FIELD_ENCRYPTION_KEY`, `SMTP_PASSWORD`,
     `USDA_FDC_API_KEY`, or a `DATABASE_URL` containing a password appears in
     `containerDefinitions[].environment` rather than `.secrets`;
   - `REDIS_URL` is unset, or `DEBUG` is true;
   - either image reference is a tag rather than `@sha256:`;
   - `cpuArchitecture` is not `ARM64`;
   - `FORWARDED_ALLOW_IPS` is unset.
   This runs in the same CI job that runs `terraform plan`, and it is a required
   check on the branch.

2. **Value, from outside, after every deploy.** CI mints a JWT signed with
   `DEV_JWT_SECRET` — the value is public, it is in `config.py` — for a random
   patient id, and calls `GET /api/v1/me/profile` with it. **A 401 is the pass.
   Anything else fails the deploy and rolls back.** This proves the deployed
   signing key is not the repository's, from the outside, without reading the
   secret. It is the check that the `ENVIRONMENT` string cannot give you.

3. **Value, at boot, for the keys an external check cannot see.** Widen
   `config.enforce_production_safety` to run whenever `environment != "local"`,
   and rename it `enforce_deployed_safety` to say what it now means. The
   field-encryption key is compared by equality against `DEV_FIELD_ENCRYPTION_KEY`,
   so a dev key means the task will not start — which is the strongest available
   proof of that value. This also makes `REDIS_URL` mandatory in tier 0, which is
   correct, and makes `DEBUG=false` mandatory.

   Known consequences for the implementer: `apps/api/tests/core/test_config.py`
   and `apps/api/tests/synthetic/test_synthetic.py` construct
   `Settings(environment="staging")` directly — that path is unaffected, since the
   guard is called from `get_settings()`, but any test that goes through
   `get_settings()` with a non-local environment will need real values. The build
   plan's `infra/local-prod.env` already generates real keys via `just secrets`,
   so `just up-prod` and CI's prod-shaped stack keep passing.

**Collision 2 — RLS has never run against a live application.**

It has now. See *What was verified*: the whole surface works as `app_runtime`,
including the onboarding insert the build plan expected to fail. **Tier 0 should
not wait for the stage-4 spike; tier 0 is the better place to prove it**, because
a laptop probe proves the policies bind and a deployed service proves the
credentials, the pooling, the grants, and the migration/runtime role split all
hold together.

Make it a gate rather than a hope. After each deploy, a one-off ECS task using
the **runtime image digest** and the **service's** `DATABASE_URL` secret runs:

```
SELECT current_user;                                   -- must not be the owner
SELECT count(*) FROM patients;                         -- must be 0: no scope set
SELECT count(*) FROM symptom_entries;                  -- must be 0
SELECT has_table_privilege('app_runtime','alembic_version','SELECT');  -- must be false
```

Any row that comes back from the first two means RLS is not binding, and the
deploy fails. This is the deployed equivalent of
`tests/db/test_patient_isolation.py`, and it is cheap: one task, a few seconds.

**Collision 3 — `FORWARDED_ALLOW_IPS`.**

Tier 0's edge is the ALB, whose nodes hold private addresses in the subnets they
are attached to. **The value is the two public subnet CIDRs:
`FORWARDED_ALLOW_IPS=10.20.0.0/24,10.20.1.0/24`.** CIDR notation is supported
(measured). Do not use `*`: with `always_trust`, uvicorn takes the *leftmost*
`X-Forwarded-For` entry, which is entirely client-controlled, and both the audit
trail and the rate limiter become spoofable.

Do not set it to the ALB's security group or DNS name; uvicorn compares the peer
IP address.

A CI assertion belongs with this: `scripts/smoke.sh` already checks, per the
build plan, that `X-Forwarded-For` is honoured through the edge and ignored when
sent directly to the API. The post-deploy smoke should do the same against the
real ALB — request a magic link with an `X-Forwarded-For` the ALB will append to,
then assert via an ECS Exec query that the newest `audit_log` row's `ip_address`
is the client's address and not a `10.20.*` one.

**Collision 4 — the synthetic data seeder is one flag away.** `synthetic/writer.py`
refuses `production` outright and allows `staging` with `allow_staging=True`.
Tier 0 is `staging` and holds real data, so the guard that exists is the wrong
one. Two mitigations, both cheap: **no seeder task definition exists in the tier-0
account** (so there is nothing to run), and the recommended application follow-up
is a `ALLOW_SYNTHETIC_DATA` setting defaulting to false, so the permission is a
deliberate environment variable rather than a CLI argument. Until that lands, the
rule is written into the runbook: **never run `just seed` against tier 0.**

### 4. The database, and backups that have been restored

**RDS PostgreSQL 16, `db.t4g.micro`, single-AZ, 20 GB gp3, `storage_encrypted =
true` with a customer-managed KMS key.**

Three settings are creation-time only and cannot be changed later without
rebuilding the instance from a snapshot. They are the reason tier 0's first
`apply` matters:

- `storage_encrypted` and `kms_key_id`. An unencrypted RDS instance cannot be
  encrypted in place, and the key cannot be swapped in place. Snapshot → copy
  with a new key → restore is the only path, and it is an outage.
- The DB subnet group's AZs.
- `character_set`/collation, via the parameter group and the `initdb` locale.
  The build plan already established that `postgres:16-alpine` (musl) orders text
  differently from glibc; RDS is glibc `en_US.UTF-8`, which is what the build
  plan's pinned `postgres:16.15-bookworm` local image now matches.

Settings that protect the record from the likeliest way it disappears, which is
not hardware:

```hcl
deletion_protection      = true
skip_final_snapshot      = false
final_snapshot_identifier = "eoehelp-final-${timestamp-ish}"
backup_retention_period  = 7        # tier 0; 35 at tier 1
backup_window            = "07:00-08:00"   # UTC, off-peak for a US user
maintenance_window       = "sun:08:00-sun:09:00"
auto_minor_version_upgrade = true
max_allocated_storage    = 100      # storage autoscaling, capped
performance_insights_enabled = false  # free tier is 7 days, but skip at tier 0
lifecycle { prevent_destroy = true }
```

`manage_master_user_password = true` so the master credential is created and
rotated by RDS in a Secrets Manager secret, and **never enters Terraform state**.
The `app_runtime` password is created outside Terraform (see *Secrets*).

`performance_insights` off and `enabled_cloudwatch_logs_exports = ["postgresql"]`
on, with a 30-day log group retention.

**Three backup layers, and a restore that is actually performed.**

1. **Automated backups with point-in-time recovery**, 7 days at tier 0. RPO is
   5 minutes. Backup storage up to the allocated size is free, so 20 GB of
   retention costs nothing.
2. **A weekly logical dump**, so there is a copy readable without AWS. An
   EventBridge Scheduler rule runs a one-off ECS task on the runtime image
   (`pg_dump -Fc` as the owner) writing to
   `s3://eoehelp-<acct>-backups/pgdump/YYYY-MM-DD.dump`, SSE-KMS, versioned,
   lifecycle to Glacier Instant Retrieval after 30 days and expiry at 365. The
   dump contains PHI, and the encrypted columns stay ciphertext — which is the
   point of the next item.
3. **The key that decrypts the notes.** `FIELD_ENCRYPTION_KEY` lives in Secrets
   Manager and nowhere else. **A restore without it produces rows whose notes are
   permanently unreadable.** Secrets Manager's recovery window is set to the
   maximum 30 days, the secret is replicated to a second region, and the key is
   also held offline by you, written down, before the first note is written. Say
   that out loud in the runbook, because it is the failure that a row-count check
   on a restore will not catch.

**The restore drill, performed in week 1 and quarterly after** (runbook step R):

1. `aws rds restore-db-instance-to-point-in-time` to a new identifier, a time
   about an hour old, same subnet group and security group. Start a stopwatch.
2. Run a one-off ECS task on the current runtime image digest with
   `DATABASE_URL` pointed at the restored instance, executing:
   - row counts for `patients`, `symptom_entries`, `food_log_items`,
     `medications`, `endoscopies`, `consents`, `audit_log`;
   - `max(entry_date)` from `symptom_entries` — compare against what you know
     you logged;
   - **decrypt one `notes_encrypted` value** using the live
     `FIELD_ENCRYPTION_KEY`, and assert it is readable text. This is the step
     that proves the restore is a restore.
3. Stop the stopwatch. Record the elapsed time against the stated RTO of 4 hours
   in `docs/runbooks/database-restore.md`, with the date.
4. **Delete the restored instance.** A forgotten restore is the top unattended
   cost risk in this whole design — a second db.t4g.micro is $11.68/month plus
   storage, quietly. The budget alarm is the backstop; the runbook step is the
   control.

### 5. Secrets

One Secrets Manager secret holding the application's secrets as JSON, plus the
RDS-managed master secret. ECS reads individual JSON keys with the
`arn:…:secret:name:jsonkey::` form, so one secret serves all of them at
$0.40/month rather than $2.00.

```
eoehelp/staging/app  →  {
  "JWT_SECRET": "...",            # 32+ bytes
  "FIELD_ENCRYPTION_KEY": "...",  # 32 bytes, urlsafe base64
  "USDA_FDC_API_KEY": "...",      # a real key from api.data.gov, not DEMO_KEY
  "SMTP_PASSWORD": "...",         # SES SMTP credential
  "DB_PASSWORD": "..."            # app_runtime's password
}
eoehelp/staging/rds-master        # created and rotated by RDS
```

**Terraform creates the secret but never its value.** The resource carries a
placeholder and `lifecycle { ignore_changes = [secret_string] }`; the real values
are written once from your machine with `aws secretsmanager put-secret-value`.
The reason is blunt: Terraform state is a plaintext copy of everything it
manages, and `random_password` is no better — it lands in state too. This keeps
the field-encryption key, whose loss is unrecoverable ciphertext, out of a file
that gets copied around. `recovery_window_in_days = 30`, and replicate the secret
to a second region.

Rotation runbook, written now and exercised once: `JWT_SECRET` can be rotated
freely (it invalidates access tokens; refresh tokens are DB-backed and survive).
`FIELD_ENCRYPTION_KEY` **cannot** be rotated without a re-encryption pass over
every `*_encrypted` column, which does not exist yet — so treat it as permanent
until that feature is built, and say so in `docs/runbooks/key-rotation.md`.

### 6. DNS, ACM, CAA — the cutover

Squarespace stays the registrar. Only the nameservers move.

**The export is load-bearing and comes first.** Squarespace's nameserver connect
strips existing records. Before anything:

1. In Squarespace DNS settings, record **every** existing record — type, name,
   value, TTL, priority — into `docs/runbooks/dns-before-cutover.md`, and take a
   screenshot. Pay particular attention to MX and any `TXT` SPF record: if any
   mail reaches this domain today, missing one breaks it at cutover and the
   symptom is silence.
2. Create the Route 53 hosted zone and recreate every record from that list in it,
   *before* switching nameservers.

Then, in this order:

3. **Request the ACM certificate in the ALB's region** for `eoehelp.org` and
   `www.eoehelp.org`, DNS validation. ACM emits CNAME validation records. **Add
   those CNAMEs at Squarespace**, not only in Route 53, so the certificate
   validates *before* the nameserver switch and TLS is ready the moment traffic
   moves. Add them in Route 53 too, so renewal keeps working afterwards.
4. Build everything else. Verify the stack through the ALB's own
   `*.elb.amazonaws.com` name over HTTPS (it will present the wrong certificate;
   use `curl --resolve` against the ALB with the real hostname to test the
   listener rules properly).
5. **Switch nameservers at Squarespace** to the four Route 53 NS values. **This is
   the hard-to-reverse step.** `.org` delegation TTL is typically 48 hours, so a
   mistake takes up to two days to fully undo even after you correct it. Do it on
   a day you can watch it.
6. Verify: `dig +trace eoehelp.org`, `dig NS eoehelp.org @a.gtld-servers.net`,
   `dig MX eoehelp.org`, and send a test email to the domain if it receives any.
7. **Add the CAA record after the certificate is issued**, and include every
   value ACM may use, or renewal breaks:
   `0 issue "amazon.com"`, `0 issue "amazontrust.com"`, `0 issue "awstrust.com"`,
   `0 issue "amazonaws.com"`, plus `0 iodef "mailto:security@eoehelp.org"`.
8. Redirect `www` to the apex with an ALB listener rule (301), so there is one
   canonical host.

**HSTS is its own hard-to-reverse decision.** `main.py` sends
`max-age=31536000; includeSubDomains; preload` — but only in production, so tier 0
sends none at all today. Two changes: move the header to `environment != "local"`
(browsers ignore HSTS over plain HTTP, so this is safe locally), and **drop
`preload` until you have decided**. Submitting to the preload list is effectively
irreversible for months, and `includeSubDomains` with a one-year max-age commits
every future subdomain — including any you might point back at Squarespace — to
HTTPS. Start with `max-age=86400` for a week, then raise it.

Also add `TrustedHostMiddleware` with the deployed hostnames, and an ALB listener
rule that only forwards requests whose `Host` matches. `main.py` already sets
`redirect_slashes=False` as the interim fix for the host-header open redirect the
2026-09-21 security review demonstrated, with a comment saying the complete fix
"belongs with the deploy plan". This is that plan; both halves go in.

### 7. SES, and why the sandbox is enough at tier 0

**Tier 0 does not need SES production access.** The sandbox allows 200 messages
per 24 hours to *verified* addresses — and at tier 0 the only recipient is you.
Verify your own address, verify the domain, and send.

Request production access anyway, at tier 0, for two reasons: approval takes about
a day and you do not want to discover that on launch day, and the request is
stronger from a sender with a working configuration and a clean reputation than
from an empty account. If it is refused, tier 0 still works.

Configuration, all of it in tier 0:

- **Domain identity** with Easy DKIM (three CNAMEs in Route 53).
- **A custom MAIL FROM domain**, `mail.eoehelp.org`, with its MX and SPF records.
  Without it the envelope sender is an Amazon domain, SPF does not align, and
  DMARC passes on DKIM alone. With it, both align.
- **SPF** on the apex: `v=spf1 include:amazonses.com ~all` — merged with anything
  the export in step 1 turned up. One TXT record, not two; multiple SPF records
  is a permanent fail.
- **DMARC** at `_dmarc.eoehelp.org`: `v=DMARC1; p=none; rua=mailto:…; pct=100`.
  Monitor the aggregate reports for two weeks, then `p=quarantine`, then
  `p=reject`. Do not start at `p=reject` — the first misconfiguration silently
  destroys sign-in for everyone.
- **A configuration set** with an SNS event destination for `bounce`, `complaint`,
  `delivery`, `reject`, `renderingFailure`, and CloudWatch alarms at bounce rate
  > 5% and complaint rate > 0.1%. SES suspends sending at 10% and 0.5%, and
  suspension means nobody can sign in.
- **A daily canary.** An EventBridge rule triggers a one-off task that requests a
  magic link for a dedicated mailbox and asserts a `delivery` event arrives within
  five minutes. Magic-link failure is the outage that looks like a product
  problem, and it is invisible until someone complains.

**One thing that sits oddly with "no long-lived keys": SES SMTP credentials *are*
a long-lived IAM credential**, derived from an access key. The application uses
`aiosmtplib` (`identity/email.py`), so tier 0 stores the SMTP password in Secrets
Manager with a documented rotation. The better answer — and a recommended
follow-up before tier 1 — is to switch `EmailSender` to the SES v2 API under the
task role, which removes the credential entirely. That is a contained application
change to one file.

`SMTP_HOST=email-smtp.<region>.amazonaws.com`, `SMTP_PORT=587`,
`SMTP_USE_TLS=true` (aiosmtplib's `start_tls`, which is STARTTLS — correct for
587).

### 8. The audit archive, and why its bucket is created at tier 0

`audit_log` is the answer to "did someone read my record", and `app_runtime` holds
only `INSERT` and `SELECT` on it (verified). A second copy outside the database's
blast radius is the product plan's requirement.

**Create the bucket at tier 0 with `object_lock_enabled = true`, even though the
export job can land later.** Object Lock can only be enabled at bucket creation
in the normal path; retrofitting it is the awkward part, and the bucket costs
nothing empty.

- **GOVERNANCE mode, one-year default retention**, not COMPLIANCE. COMPLIANCE
  cannot be shortened or overridden by anyone including the account root for the
  whole retention period, and a mistake — the wrong retention, an accidental
  multi-terabyte write — is then unfixable and billable for a year. GOVERNANCE
  gives the same protection against ordinary deletion while leaving a documented
  escape hatch, and the escape hatch is closed by denying
  `s3:BypassGovernanceRetention` in the bucket policy to everything except a
  break-glass role.
- Versioning on (required by Object Lock), block-public-access on, SSE-KMS.
- The exporting task's role gets `s3:PutObject` and `s3:PutObjectRetention` only:
  no `DeleteObject`, no `BypassGovernanceRetention`.
- The job: an EventBridge Scheduler rule, daily, running a one-off ECS task on
  the runtime image that reads `audit_log` rows newer than the last watermark
  (stored as an S3 object, not in the database) and writes NDJSON to
  `s3://eoehelp-<acct>-audit-archive/audit/dt=YYYY-MM-DD/part-<ts>.ndjson`.
- **It contains `ip_address` and `user_agent`, which are PHI-adjacent, and field
  names and counts but never values** — the audit-metadata policy already
  guarantees that shape. Treat the bucket as PHI: SSE-KMS, no public access, in
  scope for the BAA.

### 9. Observability, alarms, and what can run up a bill unattended

Logs go to CloudWatch with a 30-day retention on every log group (tier 0) —
`observability.py` already emits JSON when `DEBUG=false`, and already keeps PHI
and resolved paths out. First 5 GB of ingestion is always free; this will be well
under it.

Alarms, all with an SNS topic to your email:

| Alarm | Threshold | Why |
|---|---|---|
| ALB target 5xx | > 5 in 5 min | the app is failing |
| ALB unhealthy host count | ≥ 1 for 5 min | the task is not serving |
| ECS service running count | < 1 for 5 min | nothing is running |
| RDS free storage | < 4 GB | the slow way a database dies |
| RDS CPU credit balance | < 60 | t4g burst exhaustion |
| RDS free memory | < 100 MB | db.t4g.micro is 1 GB |
| SES bounce rate | > 5% | SES suspends at 10% and nobody can sign in |
| SES complaint rate | > 0.1% | SES suspends at 0.5% |
| Magic-link canary failure | any | sign-in is broken |
| Certificate days to expiry | < 21 | ACM auto-renews, but DNS validation can silently break |

**Budget alarms and the things that run up a bill while you are not looking:**

- An AWS Budget at **$75/month actual** with alerts at 50%, 80%, 100%, and a
  second **forecasted** budget at 100%. Two budgets are free per account.
- **Cost Anomaly Detection** with a monitor on the whole account and a $10
  threshold. It is free and it catches the shape of the problem — a step change —
  rather than the total.
- The specific unattended risks here, in order of likelihood:
  1. **A restored RDS instance left running after a drill.** $12–24/month, silent.
     The runbook's last step deletes it; the budget alarm catches the miss.
  2. **A NAT gateway added without thinking at tier 1.** $33/month plus $0.045/GB,
     and the data charge is the part that grows.
  3. **CloudWatch Logs with no retention set.** The default is "never expire".
     Every log group gets an explicit retention in Terraform.
  4. **ECR with no lifecycle policy.** Two ~500 MB images per push, forever.
     Policy: expire untagged after 7 days, keep the last 5 `candidate-*`.
  5. **RDS storage autoscaling with no ceiling.** `max_allocated_storage = 100`.
  6. **CloudTrail data events.** Management events on one trail are free; S3 and
     Lambda data events are billed per event and can be enormous. Do not enable
     them at tier 0.
  7. **VPC flow logs to CloudWatch.** Off at tier 0. At tier 1, to S3 with a
     30-day lifecycle.
  8. **GuardDuty after its 30-day trial.** ~$4/month here; tier 1 keeps it, tier 0
     does not enable it.

### 10. Tier 0 cost, itemised

us-east-2, list prices queried today, 730 hours.

| Line | $/month |
|---|---|
| ALB (hours) | 16.43 |
| ALB (LCU, near-idle) | 0.29 |
| Public IPv4 × 3 (ALB in 2 AZs, 1 task) | 10.95 |
| Fargate ARM64, 0.25 vCPU / 1 GB | 8.51 |
| RDS db.t4g.micro, Single-AZ | 11.68 |
| RDS gp3, 20 GB | 2.30 |
| RDS backups (≤ allocated size) | 0.00 |
| ElastiCache Valkey, cache.t4g.micro | 9.34 |
| Route 53 hosted zone (alias queries free) | 0.50 |
| Secrets Manager, 2 secrets | 0.80 |
| KMS, 1 customer-managed key version | 1.00 |
| ECR, ~1.5 GB with a 5-deep lifecycle | 0.15 |
| S3 — state, audit archive, dumps, ~2 GB | 0.05 |
| CloudWatch Logs (< 5 GB, always-free) | 0.00 |
| CloudTrail, one management trail | 0.00 |
| ACM, IGW, egress under 100 GB | 0.00 |
| SES, ~100 messages | 0.01 |
| **Total at list price** | **$62.01** |

**Month 1, if the account is on the old twelve-month free tier** (750 hours of
db.t4g.micro + 20 GB storage + 20 GB backup; 750 hours of cache.t4g.micro; 500 MB
ECR): subtract **$23.42** → **$38.59/month**.

**Month 13:** the free-tier allowances stop. The bill goes to **$62.01/month**.

**What breaks at month 12: nothing.** On the old free tier, AWS does not stop
anything when the twelve months end; the allowances simply stop being applied and
the invoice grows by $23. That is the honest answer, and it is a relief rather
than a cliff.

**How you would know, in three ways:** the forecasted budget alarm fires in month
11 or 12 as the forecast steps up; AWS's own free-tier usage alerts (enable them
in Billing preferences) warn as you approach 85% and 100% of an allowance; and a
calendar reminder for month 11 in `docs/runbooks/` to re-read this table. Set all
three — the first two are free and the third is the one that actually gets read.

**If the account is on the newer credit-based plan, the shape is different and
worse.** There are no 750-hour allowances, so the bill is $62/month from day one,
drawn against the signup credit. A $100–200 credit lasts two or three months, and
on a "Free plan" account **exhausting it can suspend resources** rather than
generate an invoice. Suspension with real health data in an RDS instance is not
an acceptable failure mode. **Check the account plan in the Billing console
before the first real entry, and move to a Paid plan if it is not already one.**

Reducing it further, if the numbers matter: dropping ElastiCache saves $9.34
(costs you cross-restart rate-limit state, which is harmless at one user but
means `enforce_deployed_safety` cannot require `REDIS_URL`); a one-year Compute
Savings Plan covering the Fargate task saves roughly 20% of $8.51; and the EC2
alternative in section 1 is about $18. None of these is worth doing first.

### 11. The BAA at tier 0: yes

The question was whether there is any reason not to accept it when only the
operator's own data is present. There is not.

- It is free and self-serve in AWS Artifact, takes minutes, and obligates you to
  nothing. It binds AWS.
- It does not make you a covered entity or a business associate. ADR 0001's
  posture — patient-owned record, no doctor accounts — is untouched.
- The data in tier 0 *is* PHI: a named individual's diagnosis, symptoms,
  medications, and biopsy results. That it is your own does not change what it is,
  and the point of tier 0 is to run the real thing.
- Accepting it now removes the only remaining "migration moment" the product plan
  worried about.

Two things it obliges the *design* to do, which is why it is not merely
paperwork: PHI may only be placed in HIPAA-eligible services (so the eligibility
list is a design constraint, and App Runner/Lightsail need checking before use),
and encryption, private access, and CloudTrail remain your responsibility. ADR
0004's "eligible is not compliant" line is the right one.

Accept it in the tier-0 account. At tier 1, accept it at the Organization
management account so both members are covered — Artifact supports organisation-
wide acceptance, and re-accepting per account afterwards is avoidable friction.

## Tier 1: what changes, what is a resize, what is a rebuild

Tier 1 is the launch-gate posture: two accounts, Multi-AZ, private subnets,
CloudFront and WAF, promotion with a human gate.

**Which account becomes production?** The recommendation is the one that will
surprise you: **tier 0's account becomes production, and the new account becomes
staging.** Tier 0's account holds real data in a CMK-encrypted RDS instance that
cannot be re-encrypted in place; moving that data to a new account means sharing
an encrypted snapshot, sharing the CMK, restoring, and re-pointing — a real
operation with a real failure mode, performed on the only copy of your history.
Building a *staging* account from scratch and seeding it with synthetic data is
trivial by comparison. An existing standalone account can be invited into a new
Organization, so nothing about the account needs rebuilding.

That inverts the natural instinct and it is worth stating plainly, because it
raises the stakes on tier 0's first `apply`: **the tier-0 account is the
production account, so everything tier 0 creates that cannot be changed in place
must be created correctly the first time.**

### Resizes — one Terraform variable or one `apply`

| Change | How |
|---|---|
| RDS Single-AZ → Multi-AZ | `multi_az = true`; a failover, minutes |
| RDS db.t4g.micro → db.t4g.small | instance class change, one restart |
| RDS backups 7 → 35 days | attribute |
| Fargate 1 task → 2, 0.25 → 0.5 vCPU | attributes; a rolling deployment |
| Compute public subnets → private subnets + NAT | `network_configuration` subnets + a NAT gateway + route table; a rolling deployment |
| ElastiCache single node → replication group with a replica | attribute; a failover |
| Add CloudFront in front of the ALB | new distribution + a Route 53 alias change; **and see the `FORWARDED_ALLOW_IPS` note below** |
| Add WAF | a web ACL association |
| Add GuardDuty, Config, flow logs | new resources |
| `ENVIRONMENT=staging` → `production` | a variable — **but only once the legal documents are attorney-reviewed**, because `enforce_review_status` will otherwise refuse to boot. That refusal is the control working; it is also the single most likely tier-1 deploy failure, so read it here rather than discovering it at 2am |

### Rebuilds — cannot be changed in place

| Thing | Why | What tier 0 must therefore do |
|---|---|---|
| RDS encryption and its KMS key | cannot be added or changed in place; snapshot-copy-restore only | create encrypted with a CMK at tier 0 |
| S3 Object Lock on the audit archive | bucket-creation only in the normal path | create the bucket at tier 0, empty |
| Subnet CIDRs and AZ placement | immutable | create four subnets across two AZs at tier 0 |
| VPC CIDR | only extendable by secondary blocks | pick `10.20.0.0/16` at tier 0 |
| The account that holds the data | cross-account RDS moves are snapshot-share-and-restore | make tier 0's account the production one |
| Region | everything | decide at tier 0 (see open questions) |
| The edge, if tier 0 had chosen EC2 or API Gateway | different deploy mechanism entirely | this is the argument for ECS at tier 0 |

### The CloudFront trap, stated once more because it is subtle

Adding CloudFront in front of the ALB makes `FORWARDED_ALLOW_IPS = subnet CIDRs`
**wrong**, silently: uvicorn walks `X-Forwarded-For` right to left and returns the
first untrusted host, which becomes a CloudFront edge address. Every audit row
would then record CloudFront, and every request would share a rate-limit bucket —
the exact defect tier 0 fixed.

Tier 1 therefore does two things together:

1. `FORWARDED_ALLOW_IPS` = the subnet CIDRs **plus** CloudFront's address ranges,
   from Terraform's `data "aws_ip_ranges" { services = ["cloudfront"] }` so a
   re-apply picks up changes.
2. Restrict the ALB's security group to the AWS-managed prefix list
   `com.amazonaws.global.cloudfront.origin-facing`. Without this, trusting
   CloudFront's ranges would let anyone put their own distribution in front of
   your ALB and spoof a client address — and it also closes the more ordinary
   hole of bypassing CloudFront and WAF by calling the ALB directly.

Neither is optional; they only work as a pair.

### Tier 1 cost, itemised

**Production account**

| Line | $/month |
|---|---|
| ALB (hours + LCU) | 16.73 |
| Public IPv4 (ALB, 2 AZ) | 7.30 |
| NAT gateway (1) + ~10 GB processed | 33.30 |
| Fargate ARM64, 2 × 0.5 vCPU / 1 GB | 28.84 |
| RDS db.t4g.small, Multi-AZ | 47.45 |
| RDS gp3, 50 GB, Multi-AZ | 11.50 |
| ElastiCache Valkey, 2 × cache.t4g.micro | 18.69 |
| CloudFront (under the always-free 1 TB / 10M requests) | 0.00 |
| AWS WAF (1 web ACL, 6 rules, request volume) | 11.60 |
| Route 53 (zone + queries) | 0.70 |
| Secrets Manager (5 secrets, split for rotation granularity) | 2.00 |
| KMS (4 customer-managed key versions) | 4.00 |
| CloudWatch (logs, ~15 alarms) | 3.00 |
| CloudTrail + its S3 storage | 0.50 |
| GuardDuty | 4.00 |
| S3 (audit archive, report PDFs, backups) | 2.00 |
| SES | 1.00 |
| ECR | 0.30 |
| **Production subtotal** | **$192.90** |

**Staging account** (synthetic data only, so no NAT, no Multi-AZ, no WAF)

| Line | $/month |
|---|---|
| ALB + LCU | 16.53 |
| Public IPv4 (ALB 2, task 1) | 10.95 |
| Fargate ARM64, 0.25 vCPU / 1 GB | 8.51 |
| RDS db.t4g.micro Single-AZ + 20 GB | 13.98 |
| ElastiCache Valkey cache.t4g.micro | 9.34 |
| Route 53 delegated subzone | 0.50 |
| Secrets Manager (2) | 0.80 |
| KMS (1) | 1.00 |
| CloudWatch + S3 + ECR | 1.50 |
| **Staging subtotal** | **$63.11** |

**Tier 1 total: $256/month.**

ADR 0004 and the product plan estimate $250–300. **The claim holds**, and the
itemisation shows where it lives: NAT ($33), the two ALBs ($52 with their public
addresses), and Multi-AZ RDS ($59) are 56% of it. Two honest observations:

- The product plan's line-item guesses were close in total but wrong in
  distribution — it put RDS Multi-AZ at ~$70 (actual $59 for db.t4g.small) and
  omitted public IPv4 charges entirely ($18 across both accounts), which did not
  exist when that plan was written.
- The single largest lever is staging: switching it off when not in use, or
  running it only during active development, saves $63/month. An ECS service
  scaled to zero and an RDS instance stopped (RDS can be stopped for 7 days at a
  time) makes staging roughly $25/month. Worth doing, not worth automating.

## Terraform layout, and the state bootstrap problem

```
infra/terraform/
  bootstrap/            # run once, per account; see below
    main.tf  versions.tf
  modules/
    network/            # VPC, subnets, route tables, SGs, S3 gateway endpoint
    data/               # RDS, ElastiCache, subnet groups, parameter groups
    secrets/            # Secrets Manager shells (values never in state)
    compute/            # ECR, task definitions, ECS cluster/service, ALB, TGs
    dns/                # Route 53 records, ACM, CAA
    email/              # SES identity, DKIM, MAIL FROM, config set, alarms
    audit_archive/      # Object Lock bucket, exporter schedule + task
    observability/      # log groups, alarms, SNS, budgets, anomaly monitor
    ci_oidc/            # GitHub OIDC provider + roles
  envs/
    staging/            # tier 0 lives here; tier 1 keeps it for the new account
      main.tf terraform.tfvars backend.tf
    production/         # tier 1 only
```

`required_version = "~> 1.13"`, `hashicorp/aws ~> 6.0`, `.terraform.lock.hcl`
committed. One provider, one region per root, `default_tags` applying
`Project=eoehelp`, `Environment`, `ManagedBy=terraform` to everything so an
untagged resource is visibly hand-made.

**The state bootstrap chicken and egg.** Terraform needs an S3 bucket to store
state; the bucket has to exist before the backend can be configured. The
resolution:

1. `infra/terraform/bootstrap/` has a **local backend** and creates exactly three
   things: the state bucket (versioned, SSE-KMS with its own CMK, block public
   access, `prevent_destroy`), that CMK, and the GitHub OIDC provider and roles.
2. Run `terraform apply` once from your machine with admin credentials.
3. Add the `backend "s3"` block to `bootstrap/` pointing at the bucket it just
   created, and run `terraform init -migrate-state`. Bootstrap now stores its own
   state in the bucket it manages. The local `terraform.tfstate` is deleted and
   **never committed** — `.gitignore` gets `*.tfstate*` and `.terraform/`.
4. Every other root uses that bucket with a distinct `key`.

**Use S3 native state locking** (`use_lockfile = true`, Terraform 1.11+) rather
than a DynamoDB table: one fewer resource, one fewer thing to pay for and forget.

**State contains secrets.** Even with the `ignore_changes` discipline above, state
holds ARNs, endpoints, and anything a provider returns. The bucket is SSE-KMS with
a key policy limited to the Terraform roles, versioned so a corrupt apply is
recoverable, and never public. Nobody gets `s3:GetObject` on it except the
bootstrap admin and the CI plan/apply roles.

**Not a skeleton.** The build plan refused to commit a Terraform root that could
not `plan`, and it was right. This plan's Terraform is written when the account
exists and `plan` runs against it — not before.

## CI/CD: OIDC, publish, deploy, promote, migrate, revert

### GitHub OIDC, no long-lived keys

The bootstrap root creates `aws_iam_openid_connect_provider` for
`token.actions.githubusercontent.com` and two roles per account:

| Role | Trust condition on `sub` | Permissions |
|---|---|---|
| `gha-plan` | `repo:<owner>/eoehelp:pull_request` | read-only + `terraform plan` |
| `gha-deploy` | tier 0: `repo:<owner>/eoehelp:ref:refs/heads/development`<br>tier 1 prod: `repo:<owner>/eoehelp:environment:production` | ECR push, ECS register/update, RunTask, PassRole, `terraform apply` |

Two conditions, both required: `aud = sts.amazonaws.com` and an **exact** `sub`.
A `repo:<owner>/*` wildcard is the classic hole — any workflow in any branch of
any repo you own could then assume the role. Tier 1's production role trusts an
`environment:production` subject, and the GitHub Environment carries a required
reviewer, which is where the human gate actually lives.

### The release path

**Tier 0** (one account, `development` is the only branch that deploys):

1. `publish.yml`, on push to `development`. Builds `runtime` and `web-runtime`
   with buildah on `ubuntu-24.04-arm`, runs `scripts/verify-image.sh`, pushes to
   ECR as `candidate-<sha>`, reads the digests back with `skopeo inspect`, writes
   them to `digests.json` and the job summary. This is the build plan's existing
   workflow with `vars.REGISTRY` pointed at ECR and `GITHUB_TOKEN` login replaced
   by OIDC + `aws ecr get-login-password` — the change the build plan promised
   would be two variables and a login step.
2. `deploy.yml`, triggered by `publish.yml` succeeding. In order:
   a. Render the task definitions with `@sha256:` digests.
   b. **`scripts/verify-taskdef.sh`** — the `ENVIRONMENT` and secrets-wiring
      assertions from section 3. Fails closed.
   c. Register the task definitions.
   d. **Run the migration task** — the same image digest, the **owner**
      `DATABASE_URL`, command `alembic upgrade head`, `awsvpc` in the same
      subnets. Wait for exit code 0. **If it fails, stop: the service is not
      updated.**
   e. `aws ecs update-service --task-definition <new arn>`, with the deployment
      circuit breaker enabled and `rollback = true`.
   f. `aws ecs wait services-stable`.
   g. **Post-deploy gates**, all of which must pass or the deploy is rolled back:
      - `GET /healthz` and `GET /readyz` → 200
      - a JWT signed with `DEV_JWT_SECRET` → **401**
      - the RLS one-off task: `current_user` ≠ owner, unscoped
        `count(*) FROM patients` = 0, no privilege on `alembic_version`
      - `scripts/smoke.sh` against `https://eoehelp.org`: magic-link sign-in, a
        symptom entry written and read back, and the `X-Forwarded-For` assertion
        from section 3.

**Tier 1** adds `promote.yml`: `workflow_dispatch` with the two digests, gated by
the GitHub `production` environment's required reviewer, doing
`skopeo copy --all` from the staging ECR digest to the production ECR, re-reading
the destination digest and failing on a mismatch — then the identical sequence
from (a) in the production account. Production is never built, only promoted.

### Reverting a bad release

**The application is easy; the schema is not, and the plan has to say so.**

- **App-only regression:** re-register nothing — the previous task definition
  revision already exists and already pins the previous digest.
  `aws ecs update-service --task-definition <previous revision arn>` and wait.
  Two to three minutes. This is the whole procedure, and it is why task
  definitions pin digests rather than tags.
- **A migration made it bad:** a task-definition rollback does *not* undo it. The
  previous image will run against the new schema. There are two paths, and
  neither is fast: roll *forward* with a corrective migration, or restore the
  database to a point-in-time before the migration and accept losing every write
  since. For a one-user tier 0 the second is tolerable; at tier 1 it is not.
- **The discipline that makes the first path work**, and which must be written
  into the migration review: **every migration must leave the schema compatible
  with the immediately preceding image.** Expand first (add nullable columns, add
  tables), deploy, then contract in a later release. CI already runs
  `upgrade/downgrade/upgrade`, which proves a migration is reversible in
  isolation — a different and weaker property than "the old code still works
  against the new schema". Name that difference in the ADR so nobody mistakes the
  green check for the guarantee.

## Where the build plan's deploy contract is wrong or insufficient

`docs/plans/2026-09-19-build-system-and-deploy-path.md` hands this plan a deploy
contract to consume. Most of it is right and is used verbatim: ports 8000 and
8080, `GET /healthz` on both, `cpuArchitecture: ARM64`, `@sha256:` image
references, ECR tag immutability and scan-on-push, the environment variable list,
which variables come from Secrets Manager, and migrations as a separate task
under the owner role while the service runs as `app_runtime`.

Seven places where it is wrong or not enough:

1. **The `app_runtime` spike's expected outcome is out of date.** The plan says
   the spike will probably fail because `patients` has no `WITH CHECK` and sign-up
   has no scope. The first half is still true; the second is not —
   `onboarding_service.complete` sets the scope before the insert. Measured: the
   whole API works as `app_runtime`. The "revert to the owner URL" branch should
   not be taken, and `compose.prod.yaml` should ship pointed at `app_runtime`.

2. **`FORWARDED_ALLOW_IPS` is described as "the private subnet CIDRs".** That is
   right for an ALB and wrong for anything in front of it. The contract should say
   *every hop between the client and uvicorn*, because uvicorn walks the header
   right to left and stops at the first untrusted address — so adding CloudFront
   at tier 1 silently breaks the audit trail unless CloudFront's ranges are added
   too. Also: never `*`, which makes the leftmost, fully client-controlled entry
   authoritative.

3. **`ENVIRONMENT` is the wrong axis for the secret check.** The contract asks CI
   to assert `ENVIRONMENT=production` on the production task definition. Necessary,
   and adopted here — but it does nothing for tier 0, which *must* be `staging`
   and therefore gets no secret enforcement at all. The contract needs a second
   assertion that is independent of the string, and the application needs
   `enforce_production_safety` to key on "deployed" rather than "production".

4. **The contract says nothing about the web artifact**, while
   `apps/web/Dockerfile` says the build goes to S3 behind CloudFront. Those are
   different deployments with different provenance properties. The contract must
   state which, because ADR 0006's guarantee depends on it. This plan runs the
   container at both tiers.

5. **The migration task's failure semantics are unstated.** "Migrations run as a
   separate task before the service updates" does not say that a non-zero exit
   must abort the deploy, nor that a task-definition rollback cannot undo a
   migration. Both belong in the contract.

6. **Health checks need to be declared in the task definition.** ECS does not use
   a Dockerfile `HEALTHCHECK`. The contract names the endpoints but not where the
   check is configured, and the difference is a service that never reports
   unhealthy.

7. **`SMTP_PASSWORD` from Secrets Manager is listed without noting that an SES
   SMTP credential is a long-lived IAM credential**, which sits awkwardly beside
   the same document's "GitHub OIDC, no long-lived keys". Either say it is an
   accepted exception with a rotation runbook, or move to the SES v2 API under
   the task role.

Two smaller additions for the contract: `alembic_version` carries no grant to
`app_runtime` (verified from `information_schema`), which is what makes the role
split enforced rather than conventional; and `/docs` and `/openapi.json` sit
outside `/api/v1`, so an ALB that routes only `/api/v1/*` to the API makes them
unreachable in every deployed environment — which should be a stated decision,
not a surprise.

## Application changes this plan depends on

Small, contained, and each one is a prerequisite rather than a nice-to-have.
They belong to the implementer of *this* plan, not to a later feature.

| Change | File | Why |
|---|---|---|
| `enforce_production_safety` → `enforce_deployed_safety`, guarded on `environment != "local"` | `config.py:131–160` | the only thing that refuses a dev field-encryption key in tier 0 |
| HSTS on `environment != "local"`, and drop `preload` for now | `main.py:152` | tier 0 currently sends no HSTS at all |
| `TrustedHostMiddleware` with the deployed hostnames | `main.py` | the complete fix for the host-header redirect the 2026-09-21 review demonstrated; `redirect_slashes=False` was the interim |
| `ALLOW_SYNTHETIC_DATA` setting, default false, checked by `assert_writable` | `config.py`, `synthetic/writer.py:67` | tier 0 is `staging`, where the seeder is one flag away from writing invented entries into a real record |

Recommended but not required before tier 0: move `EmailSender` from SMTP to the
SES v2 API under the task role (`identity/email.py`), which deletes the last
long-lived credential.

## Security and privacy

- **Patient data.** No new table, column, endpoint, or query. RLS, grants, the
  repository pattern, and `/me` routing are untouched. `tests/test_architecture.py`
  and `tests/db/test_patient_isolation.py` need no change and must stay green.
  What changes is that the `app_runtime` path becomes the deployed path and is
  asserted after every deploy.
- **What improves.** `audit_log.ip_address` becomes the patient's address rather
  than a network hop, and the rate limiter gets a per-client bucket — both
  measured broken today. The dev JWT secret becomes provably absent from a
  deployed environment. RLS binds in production for the first time.
- **PHI boundaries.** PHI exists in RDS (encrypted at rest with a CMK, private,
  no public address), in the S3 logical dumps (SSE-KMS, versioned, blocked from
  public access), in the S3 audit archive (`ip_address` and `user_agent` only —
  field names and counts, never values, per the audit-metadata policy), and in
  transit over TLS. Free text stays application-layer AES-GCM encrypted with a key
  that lives only in Secrets Manager.
- **Logs never carry PHI.** `observability.py` already logs route templates rather
  than resolved paths, field names rather than values, and uvicorn runs with
  `--no-access-log`. CloudWatch is inside the BAA boundary regardless.
- **New third parties: none that receive patient data.** ECR, S3, RDS,
  ElastiCache, SES and CloudWatch are all AWS, under the BAA. GitHub Actions
  receives no patient data — it holds image layers of a public repository's source
  and deploy metadata. Route 53 and ACM see DNS and certificates, not data. This
  is deliberate, and it is why the plan refuses Cloudflare's proxy (ADR 0004) and
  keeps error tracking out of scope until its BAA question is answered.
- **Credentials.** Zero long-lived AWS keys: GitHub authenticates by OIDC, the
  tasks use IAM roles, the RDS master password is RDS-managed. The one long-lived
  credential in the design is the SES SMTP password, named above with its
  rotation runbook and its replacement.
- **Least privilege.** The task execution role reads only the two secrets and
  writes only its log group. The task role gets SES send, S3 put on the audit
  archive prefix, and the three SSM actions for ECS Exec — nothing else. The
  audit-archive writer holds no `DeleteObject` and no
  `BypassGovernanceRetention`.
- **This change is squarely in the security-review and devops-review categories**
  of the feature workflow: database grants, public endpoints, outbound calls, CI
  permissions, headers, and infrastructure. Both reviews apply. The database
  reviewer applies to the RDS parameter group, the role split, and the backup
  configuration. The legal reviewer does not: no patient-facing wording changes,
  and no claim in the published documents becomes stale — but confirm that
  reading, because AWS becomes a named subprocessor in any subprocessor register
  the privacy policy points at.

## Testing: what proves each claim

| Claim | Proof |
|---|---|
| The deployed artifact is the tested digest | `scripts/verify-taskdef.sh` fails on any tag-based image reference; `promote.yml` re-reads the destination digest and fails on mismatch |
| The deployed environment does not use the repository's JWT secret | post-deploy gate: a token signed with `DEV_JWT_SECRET` gets 401 |
| The deployed environment does not use the dev field key | the task refuses to start (`enforce_deployed_safety`), so a green deploy is the proof |
| RLS binds to the running application | post-deploy one-off task: `current_user` ≠ owner, unscoped `count(*) FROM patients` = 0 |
| The service cannot migrate | the same task asserts no privilege on `alembic_version` |
| The audit trail records the patient, not the balancer | post-deploy: a request with a known `X-Forwarded-For` produces an `audit_log` row whose `ip_address` is the client's, not `10.20.*` |
| Rate limits are per client | two requests from different source addresses do not share a bucket (exercised by the smoke test's two synthetic clients) |
| Migrations run before the service updates | `deploy.yml` fails the job on a non-zero migration exit and does not reach `update-service`; exercised deliberately once with a broken migration on a throwaway branch |
| A bad release can be reverted | perform it once, deliberately, in the runbook: deploy a known-good revision, then roll back to the previous one and time it |
| Backups restore | the week-1 restore drill, including decrypting a note, timed and recorded |
| Magic-link email is delivered | SES `delivery` event within five minutes, daily canary, and the launch-gate manual test across Gmail, Outlook, iCloud and one hospital mail system |
| The Object Lock archive cannot be deleted by the writer | attempt `DeleteObject` with the writer role and assert AccessDenied |
| `ENVIRONMENT` is what the environment says | `scripts/verify-taskdef.sh`, as a required CI check |

Existing suites that must stay green unchanged: the full API suite,
`tests/db/test_patient_isolation.py`, `tests/test_architecture.py`, the Angular
unit tests, and the OpenAPI drift check. The only test files this plan expects to
touch are `tests/core/test_config.py` (the renamed guard) and possibly
`tests/synthetic/test_synthetic.py` (the new `ALLOW_SYNTHETIC_DATA` setting).

## Runbook

**Irreversible or hard to reverse** is marked ⚠. Nothing before step 1 costs
anything.

### Phase A — decide, before creating anything

0. Read this plan. Answer the open questions below. **Stop here if you are not
   spending money yet.**
1. Check the AWS account's billing plan and free-tier model (Billing → Free tier,
   Billing → Account plan). If it is a "Free plan" with credits, **upgrade to a
   Paid plan before any real data exists** — credit exhaustion can suspend
   resources.
2. Enable free-tier usage alerts and set the $75 budget + anomaly monitor
   *before* the first resource, so the alarms predate the spend.
3. ⚠ **Accept the HIPAA BAA in AWS Artifact**, and read the HIPAA-eligible
   services list alongside it. (Reversible on paper; treat it as a decision.)
4. Enable MFA on the root user, create an admin IAM Identity Center user, and
   stop using root. Set the account alias and the billing contacts.

### Phase B — bootstrap

5. `infra/terraform/bootstrap`: state bucket + its CMK + the GitHub OIDC provider
   and roles. `terraform apply` locally, then add the backend and
   `terraform init -migrate-state`. ⚠ `prevent_destroy` on the bucket and key.
6. Store the GitHub repository variables: `AWS_REGION`, `AWS_ACCOUNT_ID`,
   `REGISTRY`, `REGISTRY_NAMESPACE`, `DEPLOY_ROLE_ARN`.

### Phase C — the record's home, before the domain moves

7. `modules/network`, `modules/data`: VPC, four subnets, security groups, the S3
   gateway endpoint, ⚠ the RDS CMK, ⚠ the RDS instance created **encrypted**,
   ElastiCache Valkey.
8. `modules/secrets`: the secret shells. Write the real values once with
   `aws secretsmanager put-secret-value`. ⚠ **Write `FIELD_ENCRYPTION_KEY` down
   offline before anything is encrypted with it.**
9. ⚠ `modules/audit_archive`: the Object Lock bucket, created empty. Object Lock
   cannot be added later.
10. ECR repositories with immutable tags, scan-on-push, and the 5-deep lifecycle
    policy. Push the first images from `publish.yml`.
11. `modules/compute`: cluster, task definitions, service, ALB, target groups.
    The ALB has an HTTP listener only at this stage.
12. Run the migration task by hand once. Then `deploy.yml` end to end, including
    every post-deploy gate. **This is the first moment RLS runs in a deployed
    application; do not skip the gate.**
13. Smoke-test through the ALB's own DNS name using `curl --resolve` so the host
    rules are exercised.

### Phase D — the domain

14. ⚠ **Export every Squarespace DNS record** into
    `docs/runbooks/dns-before-cutover.md`, with a screenshot. Nothing else in
    this phase is safe until this is done.
15. Create the Route 53 hosted zone; recreate every exported record in it.
16. Request the ACM certificate; add its validation CNAMEs **at Squarespace** and
    in Route 53; wait for `ISSUED`. Attach the HTTPS listener and the HTTP→HTTPS
    redirect.
17. Add the SES domain identity, DKIM CNAMEs, MAIL FROM records, SPF, and DMARC
    at `p=none` — in Route 53, which is not yet authoritative, so they take effect
    at cutover.
18. ⚠ **Switch the nameservers at Squarespace.** Up to 48 hours to fully undo.
    Do it when you can watch it. Verify with `dig +trace`, confirm MX still
    resolves, send a test message to any address on the domain.
19. Add the CAA records, after the certificate is issued, with all four Amazon
    values.
20. Verify your own address in SES, request production access, and send a magic
    link to yourself end to end.

### Phase E — the data, and proving you can get it back

21. Create your account through the real site. Complete onboarding. Enter a week
    of real history.
22. **Run the restore drill (section 4), including decrypting a note. Record the
    elapsed time.** ⚠ Delete the restored instance when finished.
23. Turn on the weekly logical dump and the daily audit-archive export. Confirm
    the first object lands and that the writer role cannot delete it.
24. Set the month-11 calendar reminder to re-read the cost table.
25. Deliberately roll back one deploy and time it. Deliberately fail one
    migration on a throwaway branch and confirm the service is not updated.

### Phase F — tier 1, when the launch gate needs it

26. Create the Organization from the tier-0 account; accept the BAA at the
    management account; invite a new account to be **staging**.
27. Resize production per the table: Multi-AZ, private subnets + NAT, two tasks,
    CloudFront + WAF + the origin-facing prefix list + the `FORWARDED_ALLOW_IPS`
    change (together, never separately), GuardDuty, 35-day backups, cross-region
    snapshot copies.
28. ⚠ Flip `ENVIRONMENT` to `production` — **only after the legal documents are
    attorney-reviewed**, or the task will refuse to start. That refusal is the
    control working.

## Open questions

Each has a recommended default. None of them is decided by this plan.

1. **Do you want tier 0 at all, at ~$39–62/month?** Nothing here creates a
   resource until you say so. **Default: yes, at tier 0 only, after checking the
   account's billing plan.** The alternative — keep using `just up-prod` locally
   and start at tier 1 when there are other patients — costs nothing and gives up
   the chance to find the deploy-shaped problems on one user's data.
2. **Fargate at ~$62/month, or one EC2 instance at ~$18?** **Default: Fargate**,
   for managed backups with PITR, free auto-renewing TLS, and a tier 1 that is a
   series of resizes. The $44/month difference is real and the EC2 path is
   legitimate; it just has to be chosen before the first `apply`, because
   switching later is the rebuild.
3. **Region.** **Default: `us-east-2` (Ohio)** — the same price as `us-east-1` and
   less entangled with the control-plane incidents `us-east-1` has historically
   had. If you would rather be physically closer to the West Coast, `us-west-2`
   is the same price again. This is a rebuild if changed later.
4. **Does tier 0's account become production at tier 1?** **Default: yes**, so
   your real history never has to move between accounts, and the new account
   becomes staging. It raises the stakes on tier 0's creation-time settings, which
   is why they are listed explicitly.
5. **ElastiCache at tier 0, or drop it and save $9.34/month after the free
   tier?** **Default: keep it.** It is free for the first twelve months, it makes
   tier 0 behave like tier 1, and it lets `enforce_deployed_safety` require
   `REDIS_URL` — which is one of the three checks that make up for `ENVIRONMENT`
   being `staging`.
6. **GOVERNANCE or COMPLIANCE mode on the audit archive?** **Default: GOVERNANCE
   with a one-year retention**, plus an explicit deny on
   `s3:BypassGovernanceRetention`. COMPLIANCE cannot be undone by anyone,
   including you, and a mistake becomes a year of unavoidable storage. If an
   auditor later requires COMPLIANCE, it can be set on new objects.
7. **HSTS `preload`?** **Default: no, not yet.** Start at `max-age=86400`, raise
   it after a week of clean HTTPS, and decide about the preload list separately —
   removal from it takes months.
8. **SES SMTP credentials now, or move to the SES v2 API first?** **Default: SMTP
   at tier 0** with the credential in Secrets Manager and a rotation runbook;
   move to the API under the task role before tier 1. It is the last long-lived
   credential in the design.
9. **Does the cost of staging at tier 1 ($63/month) justify keeping it running
   continuously?** **Default: yes while building, stopped otherwise** — RDS can be
   stopped for seven days at a time and the ECS service scaled to zero, which
   takes staging to roughly $25/month.
10. **Who receives the alarm emails, and do you want SMS for the sign-in-broken
    ones?** **Default: your email for everything, no SMS.** Magic-link failure is
    the one where a slow notification is genuinely expensive, so revisit this when
    there are patients other than you.

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect (self-check) | Draft, for the user to read before anything is created | Checked against every item in the architect's standard. **Clinical soundness:** no instrument, threshold or wording changes; the four properties with clinical consequence (audit truthfulness, magic-link deliverability as authentication uptime, restore-with-decryption, RLS binding) are each designed for with a named proof rather than asserted. **Patient isolation:** no new table, route or query; `/me` routing, repositories and RLS untouched; the `app_runtime` path was *driven end to end* rather than reasoned about, and the deployed equivalent of the isolation test is a post-deploy gate. **Privacy and PHI:** PHI locations enumerated (RDS, dumps, audit archive, in transit); no new third party receives patient data; logs keep field names and counts; the audit archive holds `ip_address`/`user_agent` only; Cloudflare and error tracking are both kept out with reasons. **Architecture:** no package moves, no dependency-rule changes, `tests/test_architecture.py` unaffected; the four application changes are each one file and each a prerequisite rather than a refactor. **Data model and migrations:** none added; the constraints that matter here live in the database's creation-time settings (RDS encryption, Object Lock, subnet AZs), which are called out as rebuilds. **API contract:** unchanged; the one deliberate behavioural change is that `/docs` and `/openapi.json` become unreachable in deployed environments, stated as a decision. **Frontend:** unchanged; the SPA is served as the promoted container image at both tiers, which is what keeps ADR 0006's digest guarantee true for the web as well as the API. **Testing:** thirteen claims each with a named proof, including three failure paths exercised deliberately (a failed migration, a rollback, a denied delete against Object Lock). **Scope:** SOC 2, pen test, entity, insurance, error tracking, multi-region and CSP are each excluded by name. **Decisions:** ten open questions with defaults, including the three that are purely the user's (whether to spend at all, Fargate versus EC2, region). **Verified rather than inferred:** the `app_runtime` end-to-end run, the RLS catalogue from `pg_class`/`pg_policies`, the `alembic_version` grant gap, `FORWARDED_ALLOW_IPS` behaviour measured both ways, uvicorn's right-to-left XFF walk read from source in the image, and every major price queried from the AWS price list. **Explicitly not resolved:** which free-tier model the account is on (the AWS documentation page is JavaScript-rendered and returned no text; both cost models are priced and the check is runbook step 1), whether ElastiCache's free tier covers Valkey, whether ALB public IPv4 addresses are billed, and the current HIPAA-eligible services list — each flagged as inferred with the place to check. Also found and reported rather than worked around: seven defects or gaps in the build plan's deploy contract, the largest being that its `app_runtime` spike prediction is out of date and that `ENVIRONMENT` is the wrong axis for the secret-safety check. |
