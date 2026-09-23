# AWS infrastructure, in two tiers

**Status:** Draft, revised for the user's decisions of 2026-09-23 · 2026-09-23

> **Nothing in this plan has been built, and nothing should be built from it
> until you have read this revision.** There is no "start now" step. The first
> action in the runbook is still checking the account's billing plan, and on this
> path that check matters more than it did, because there is no managed snapshot
> to restore from if a credit-based Free plan suspends the instance.

## Goal

**Tier 0** — the cheapest arrangement that runs *this* application, as *this*
artifact, on AWS, holding *your own* EoE record and nobody else's, with backups
that have actually been restored.

Per the user's decision (review log row 2), tier 0 is **one EC2 instance running
the promoted image digests**, not ECS Fargate. Measured from the AWS price list
queried today: **$20.42/month in month 1 and $22.87/month from month 13** — very
nearly flat, because this shape barely touches the free tier and therefore has no
month-12 cliff at all.

Because the same decision makes tier 0's account the eventual **production**
account, the PostgreSQL instance on this box is the permanent home of your real
EoE history. There is no RDS, so there is no managed snapshot and no managed
point-in-time recovery. **Backup and restore is therefore the centre of this
design, and it is section 2, not an appendix.** The mechanism is pgBackRest with
continuous WAL archiving to S3, giving a derived RPO of 60 seconds, plus two
independent fallbacks, and a restore that is performed as a numbered step during
setup and quarterly afterwards.

**Tier 1** — the posture required before anyone else's data is in it: two
accounts under an Organization, Multi-AZ RDS, compute in private subnets behind
CloudFront and WAF, promotion with a human gate. Still **$256/month**, which
tests ADR 0004's $250–300 claim and finds it sound. On this path reaching it is a
**rebuild**, not a resize; section 9 sizes that deferred bill honestly.

## Clinical basis

No instrument, threshold, or patient-facing wording changes. Five infrastructure
properties have direct clinical or patient consequence, and each is designed for
explicitly below:

- **The backup is the record.** This is one person's multi-year EoE history on one
  EBS volume in one availability zone. A restore that has never been performed is
  not a backup; a restore that produces rows whose encrypted notes no longer
  decrypt is not a restore; and a restore that comes back without the
  `app_runtime` role is worse than no restore, because the obvious "fix" is to
  connect as the table owner, which silently disables every row-level-security
  policy. The drill in section 2 checks all three.
- **The audit trail must name the person, not the network.** `audit_log.ip_address`
  and the rate limiter both read `request.client.host`. Measured today against the
  running stack, every audit row records `10.89.0.8` — the container network's
  gateway — not the client. Behind any edge that becomes the edge's address, and
  "who looked at my record" stops being answerable.
- **Magic-link email is the only way into the product, so deliverability is
  uptime.** A link in a spam folder is a patient locked out of their own health
  record, and it fails silently.
- **On this path, so is the TLS certificate.** There is no ACM. A Let's Encrypt
  renewal that fails is not a warning banner — browsers refuse the site, the SPA
  never loads, and every magic link points at a URL that errors. It is a total
  lockout from one's own health record, and it is the single most likely
  self-inflicted outage in this design.
- **Row-level security has never run against a live application.** It does now:
  the whole API was driven end to end as `app_runtime` during this design and it
  works. Tier 0 is where that becomes a deployed fact rather than a test fixture.

Nothing here is pending clinical confirmation.

## Scope

**In scope**

- Tier 0 on one EC2 instance in `us-east-2`: Terraform, VPC, the instance and its
  separate data volume, podman running the promoted digests, a Caddy edge with
  Let's Encrypt, PostgreSQL and Valkey as containers, pgBackRest to S3, ECR,
  Secrets Manager, KMS, S3 (state, backup repository, logical dumps, audit
  archive), Route 53, SES, CloudWatch, CloudTrail, Budgets.
- Tier 1: the second account, the Organization, and — stated plainly — the
  rebuild that reaching it now requires.
- The DNS cutover from Squarespace, with the record export that has to happen
  first.
- GitHub OIDC, publish/deploy workflows, how a promoted digest reaches the
  instance, where migrations run, and how a bad release is reverted.
- The `ENVIRONMENT` assertion as a CI-and-deploy check rather than a note.
- The S3 Object Lock archive for `audit_log`.
- Five application or repository changes this design depends on, each named with
  its file.

**Out of scope**

- SOC 2, the penetration test, entity formation, insurance.
- Error tracking (Sentry) and its BAA.
- Any form of high availability. This is one instance in one availability zone.
  An AZ failure is an outage lasting as long as a restore takes, and that is an
  accepted consequence of the cost decision, not an oversight.
- Multi-region anything beyond backup copies.
- A CSP header (`apps/web/nginx/security-headers.conf` has none); an application
  change with its own feature.

## What was verified, and what is inferred

Everything in this section was run today against the stack in this repository or
queried from the AWS public price list. **None of it depends on the compute
choice, so all of it survives the revision.**

### Verified by running it

**1. The application runs end to end as `app_runtime`.** A second API container
was started against the development database with
`DATABASE_URL=postgresql+asyncpg://app_runtime:…@postgres:5432/eoehelp` — the role
that owns no tables — and driven with curl:

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

`docs/plans/2026-09-19-build-system-and-deploy-path.md` predicted this would fail.
Its reasoning was half right — `pg_policies` confirms every policy is `FOR ALL`
with a `qual` and a null `with_check`, so `qual` governs INSERT — but
`identity/onboarding_service.py` now mints the patient id and calls
`apply_rls_scope` with it *before* the insert, with a comment saying exactly why.
The gap was closed by a later commit than the one that plan was written against.

**Consequence: tier 0 should not wait for the stage-4 spike. Tier 0 is the spike,
in the environment where it matters.**

**2. The row-level security catalogue, read from `pg_class` and `pg_policies`,
not from the migrations.** Twelve tables have `relrowsecurity = true`:
`patients`, `consents`, `research_consent_scopes`, `symptom_entries`,
`medications`, `medication_doses`, `custom_ingredients`, `food_log_items`,
`food_log_item_ingredients`, `endoscopies`, `biopsies`, `dilations`. Each has one
`patient_isolation` policy, `FOR ALL`, `qual` =
`patient_id = NULLIF(current_setting('app.current_patient_id', true), '')::uuid`
(`patients` uses `id`). Four tables have no RLS and hold identity or system data:
`users`, `magic_link_tokens`, `refresh_tokens`, `audit_log`. That is ADR 0002's
design, but it means `app_runtime` can read every row of `users` if a query ever
forgets its filter — recorded so the tier-1 review has it.

**3. `app_runtime` cannot migrate.** `information_schema.table_privileges` shows
no grant of any kind to `app_runtime` on `alembic_version`. The deploy contract's
split — migrations under the owner, service as `app_runtime` — is enforced by the
database, not by convention.

**4. `FORWARDED_ALLOW_IPS` behaviour, measured.** With no `FORWARDED_ALLOW_IPS`,
a request carrying `X-Forwarded-For: 203.0.113.77` through the container network
produced an audit row with `ip_address = 10.89.0.8` — the hop. Restarting the same
container with `FORWARDED_ALLOW_IPS=10.89.0.0/24` produced
`ip_address = 203.0.113.77`. **CIDR notation works, and the value is compared
against the *peer* address.** This measurement was taken through a container
bridge network, which is precisely the shape tier 0 now has.

Reading `uvicorn.middleware.proxy_headers` (0.53.0, from inside the image),
`_TrustedHosts.get_trusted_client_address` **walks `X-Forwarded-For` right to left
and returns the first host that is not trusted.** Two consequences, one for each
tier, in section 4 and section 9.

**5. The rate limiter shares one bucket per hop.** During the probe runs the
magic-link limit (`5/15 minutes`) tripped across *different* synthetic accounts,
because every request arrived from `10.89.0.8`. The same defect as (4), from the
other side.

**6. Image sizes**, for ECR and root-volume sizing: API runtime 366 MB, web
runtime 593 MB, both uncompressed (`podman images`).

### Verified by querying the AWS price list

Fetched today from `pricing.us-east-1.amazonaws.com/offers/v1.0/aws/…`, region
`us-east-2`. List prices, not a quote.

| Item | Price |
|---|---|
| EC2 `t4g.micro` / `t4g.small` / `t4g.medium`, Linux, shared | $0.0084 / **$0.0168** / $0.0336 per hour |
| EBS gp3 | **$0.08/GB-month** (3,000 IOPS and 125 MB/s included) |
| EBS snapshot storage | $0.05/GB-month; archive tier $0.0125/GB-month |
| Public IPv4 address (in use or idle) | $0.005/hr = **$3.65/month each** |
| Secrets Manager | $0.40/secret/month + $0.05/10k API calls |
| KMS | **$1.00 per customer-managed key *version* per month** + $0.03/10k requests |
| Route 53 | $0.50/hosted zone/month; $0.40/M queries; alias queries to AWS resources free |
| ECR storage | $0.10/GB-month |
| — *retained for the rejected alternative and for tier 1* | |
| Application Load Balancer | $0.0225/hr; LCU $0.008/LCU-hr |
| Fargate ARM64 / x86 | $0.03238 / $0.04048 per vCPU-hr; $0.00356 / $0.004445 per GB-hr |
| RDS PostgreSQL `db.t4g.micro` / `db.t4g.small` | Single-AZ $0.016 / $0.032 per hr; Multi-AZ $0.032 / $0.065 |
| RDS gp3 storage | Single-AZ $0.115/GB-mo; Multi-AZ $0.23/GB-mo |
| ElastiCache `cache.t4g.micro` | Redis $0.016/hr; **Valkey $0.0128/hr** |
| NAT gateway | $0.045/hr + $0.045/GB |
| VPC interface endpoint | $0.01/hr per endpoint per AZ |

Two of these shaped decisions even on this path: **KMS bills per key *version***,
so enabling annual rotation adds $1/month every year — relevant because one of
the three unrecoverable secrets is a KMS key; and Valkey is 20% cheaper than
Redis, which is now moot at tier 0 (Valkey runs as a container, free) but decides
tier 1.

### Inferred, not verified — check these before spending

- **Which free-tier model your account is on.** AWS changed the free tier for
  accounts created after roughly mid-2025: instead of twelve months of
  service-specific allowances, newer accounts get a signup credit plus a "Free
  plan" that can *suspend resources when the credit is exhausted*. The
  documentation page is JavaScript-rendered and returned no text, so I could not
  confirm current terms. **On this path a suspension is worse than a larger bill:
  there is no managed snapshot to restore from, and the only copy of your history
  is an EBS volume attached to a suspended instance.** Billing → Free tier, and
  Billing → Account plan. If it is a Free plan, move to a Paid plan before the
  first real symptom entry.
- Whether `t4g.small` carries any free-tier allowance. The classic twelve-month
  tier covers `t2.micro`/`t3.micro` (x86), and AWS's separate `t4g.small` free
  trial ran to the end of 2025. I have priced this path assuming **no instance
  free tier**, which is the conservative assumption; if a trial applies, month 1
  is $12.26 cheaper.
- Whether CloudWatch's always-free allowance is still 10 custom metrics, 10
  alarms, 1M API requests and 5 GB of log ingestion. The cost table assumes it is;
  if not, add roughly $3/month.
- **Which services are HIPAA-eligible under the current AWS BAA.** EC2, EBS, S3,
  KMS, Secrets Manager, ECR, Route 53, SES, CloudWatch, CloudTrail and Systems
  Manager should all be on it; the list is the authority and it changes. Read it
  in AWS Artifact alongside the BAA.
- Whether the `t4g.small`'s 2 GiB is comfortable with PostgreSQL, Valkey, uvicorn,
  nginx and Caddy resident. My judgement is yes for one user with the tuning in
  section 2; the upgrade to `t4g.medium` is a stop/start and $12.27/month more.

## Tier 0

One AWS account. One region, `us-east-2`. One availability zone. One instance.
Real PHI — yours.

```
Squarespace (registrar only)
  └── NS → Route 53 hosted zone  eoehelp.org
        ├── A  eoehelp.org      → Elastic IP
        ├── A  www.eoehelp.org  → Elastic IP
        └── CAA, SES DKIM x3, MAIL FROM MX+SPF, DMARC

EC2 t4g.small (arm64, Amazon Linux 2023), public subnet, Elastic IP
 SG in: 80, 443 from 0.0.0.0/0 only.  No port 22, no key pair.  Access by SSM.
 IMDSv2 required, hop limit 2, containers firewalled off except one (section 6)

  root volume gp3 20 GB      OS, podman image store — disposable
  data volume gp3 20 GB      /var/lib/eoehelp  — SEPARATE RESOURCE, prevent_destroy
                              ├── pgdata/      PostgreSQL data directory
                              ├── caddy/       ACME account + certificates
                              └── valkey/      (nothing durable)

  podman + compose, one systemd unit, network eoehelp_edge = 10.90.0.0/24
    caddy    :80 :443 published — Let's Encrypt, /api/v1/* → api, else → web
    web      :8080  the promoted eoehelp-web digest       (no host port)
    api      :8000  the promoted eoehelp-api digest       (no host port)
    postgres :5432  eoehelp-postgres digest = upstream + pgbackrest (no host port)
    valkey   :6379                                         (no host port)
    migrate         one-shot, the api digest, owner role, runs before api

S3   pgbackrest repo (AES-256 + SSE-KMS) · weekly pg_dump · audit archive
     (Object Lock) · terraform state
ECR  eoehelp-api · eoehelp-web · eoehelp-postgres — immutable tags, scan on push
```

### 1. The host: the decision, and the alternative it rejected

**Decision (user, 2026-09-23): one EC2 instance.** The comparison that produced
it is kept here rather than deleted, because it is the reasoning a future reader
will want.

| Option | Monthly | Verdict |
|---|---|---|
| **One EC2 `t4g.small` running the promoted images** | **$22.87** | **Chosen.** Cheapest thing that is still the real artifact. |
| ECS Fargate + ALB | $62.01 ($38.59 in month 1) | Rejected by the user on cost. What it bought: RDS with automated backups and point-in-time recovery operated by AWS, free auto-renewing ACM certificates, and a tier 1 that is a series of resizes rather than a rebuild. The user read those consequences and accepted them for a saving of roughly $193 in year one and $470 in year two. |
| App Runner | ~$25–40 | x86-only, which breaks ADR 0005/0006's ARM64-end-to-end and means production would run an image that was never the one tested. Also needs a VPC connector to reach a private database, and its HIPAA eligibility needs checking. |
| Lightsail containers | ~$10–17 | x86-only, and I do not believe it is HIPAA-eligible, which ends it for real PHI regardless of price. |
| API Gateway + VPC Link + Cloud Map | ~$45 | Three extra moving parts, a 10 MB response ceiling the M3 PDF report could approach, and a completely different edge from tier 1. |

**One correction to the number the decision was made on.** The "~$18/month" in
the first draft was bare compute — instance, one volume, one address. The complete
design, with a second volume, backups, snapshots, secrets, a KMS key and alarms,
is **$22.87/month**. The saving against Fargate at month 13 is therefore **$39/month,
not $44**. The decision is unaffected; the number should be right.

**Amazon Linux 2023, arm64.** The SSM agent is preinstalled, so there is no SSH
port, no key pair and no long-lived credential for access; AWS patches the AMI;
`dnf` carries podman. Ubuntu 24.04 would also work and ships a newer podman;
nothing in this design needs one.

**podman with the compose provider, not Docker and not hand-written units.** The
orchestration file is `compose.prod.yaml` — the same file `just up-prod` runs
locally — plus a small `compose.deploy.yaml` override that publishes 80/443 on the
edge, sets `restart: unless-stopped`, binds the data volume paths, drops Mailhog,
and adds Caddy. That is the strongest parity claim available: the thing that runs
in production is orchestrated by the file a developer runs on their laptop, with
a visible diff between them. One systemd unit, `eoehelp.service`
(`Type=oneshot`, `RemainAfterExit=yes`, `ExecStart=compose up -d --wait`,
`ExecStop=compose down`), gives boot ordering, restart, and journald logging.

*Considered and rejected:* **Quadlet systemd units**. Native, no compose provider
to install, and genuinely tidy — but it is a second orchestration definition
maintained in parallel with `compose.prod.yaml`, and the migrate-then-api ordering
that compose expresses as `condition: service_completed_successfully` becomes
hand-written `After=`/`Requires=`. If the compose provider proves troublesome on
AL2023, Quadlet is the fallback and nothing else in this plan changes.

**Both application containers run the promoted digests**, and the SPA is served by
the web container rather than from S3. `apps/web/Dockerfile` carries a comment
saying the build artifact goes to S3 behind CloudFront in AWS; if it did, ADR
0006's "production runs the digest that passed the tests" would be only half true,
because the SPA would be files extracted from an image rather than the image.

**Sizing.** `t4g.small`, 2 vCPU burstable, 2 GiB. Memory budget: PostgreSQL
`shared_buffers=256MB` plus work memory, uvicorn ~200 MB, nginx and Caddy ~30 MB
each, Valkey `maxmemory=64mb`, leaving headroom for the host. A **2 GiB swapfile**
on the root volume, so memory pressure degrades throughput instead of letting the
OOM killer choose which process dies — and it must not be allowed to choose
PostgreSQL. Container memory limits on `api` and `web` so a leak there cannot
starve the database. Upgrade triggers, named now so the decision is not made under
pressure: the M3 WeasyPrint report landing, or PostgreSQL's buffer cache hit ratio
falling below ~95%. The upgrade is a stop, an instance-type change, and a start,
with the data volume attached throughout.

### 2. The record, and getting it back — the centre of this design

There is no RDS here. The database is a container writing to an EBS volume, and
the user's real EoE history is what is in it. Everything in this section exists
because that sentence is true.

#### 2.1 Where the data lives, and the volume trap

**The data volume is a separate Terraform resource, not a block device on the
instance.** This is the difference between an instance replacement being routine
and being a catastrophe:

```hcl
resource "aws_ebs_volume" "data" {
  availability_zone = var.az
  size              = 20
  type              = "gp3"
  encrypted         = true
  kms_key_id        = aws_kms_key.main.arn   # creation-time only; see below
  lifecycle { prevent_destroy = true }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.app.id
  skip_destroy = true      # detach by hand, never as part of a destroy
}
```

What that buys, and what it does not:

- **Instance replacement** (an AMI change, a user-data change with
  `user_data_replace_on_change`, a forced taint) destroys the instance and its
  root volume, then reattaches the data volume to the new one. The database
  survives. Without `skip_destroy`, Terraform detaches *and* can order the
  operations in a way that leaves the volume orphaned mid-apply.
- **Instance resize** (`instance_type`) is an in-place update in Terraform — stop,
  change, start — and the volume never detaches.
- **`terraform destroy` does not destroy the volume: it refuses to run at all.**
  `prevent_destroy` makes the plan error out and abort the whole destroy. That is
  the intended behaviour and it is worth understanding rather than being surprised
  by: the escape hatch is to remove the `lifecycle` block deliberately, in a
  commit, which is a thing a person has to mean.
- **It does not protect against:** an availability-zone failure (the volume lives
  in one AZ and cannot be attached from another), a volume failure, an accidental
  `mkfs`, `DROP TABLE`, or a bad migration. Those are what section 2.2 is for.

**Two creation-time-only settings**, which is why the first `apply` matters even
on a path with no RDS:

- `encrypted` and `kms_key_id`. An unencrypted EBS volume cannot be encrypted in
  place, and the key cannot be swapped; the path is snapshot, copy with a new key,
  restore, reattach. Create it encrypted with a customer-managed key.
- The availability zone. A volume cannot move AZ except through a snapshot.

**The `mkfs` footgun, named because it is how this kind of setup loses data.**
The user-data script that prepares the volume on first boot must refuse to format
a device that already carries a filesystem:

```sh
if ! blkid /dev/nvme1n1 >/dev/null 2>&1; then
    mkfs.ext4 -L eoehelp-data /dev/nvme1n1
fi
```

Mount by **label or UUID** in `/etc/fstab` with `nofail`, never by device name —
NVMe device names are not stable across instance types. And `user_data` must be
treated as first-boot-only: never put anything in it that would be harmful to run
again, because a replacement runs it again.

**PostgreSQL configuration** for 2 GiB and for backups, in a mounted
`postgresql.conf` fragment rather than command-line flags so it is reviewable:

```
shared_buffers = 256MB
effective_cache_size = 768MB
work_mem = 8MB
maintenance_work_mem = 64MB
max_connections = 30            # app pool 5 + overflow 10, migrate 1, backup 2
random_page_cost = 1.1          # gp3
wal_level = replica
archive_mode = on
archive_command = 'pgbackrest --stanza=eoehelp archive-push %p'
archive_timeout = 60            # this is what sets the RPO
checkpoint_completion_target = 0.9
log_min_duration_statement = 1000
```

`max_connections = 30` is deliberate and tight: on 2 GiB, a connection storm is a
more likely outage than a slow query. The application's pool
(`database_pool_size=5`, `database_max_overflow=10`) is already well inside it.

The `app_runtime` role and its grants come from
`infra/postgres/init/01-extensions.sql` — the same file local development and CI
use, which is the parity the build plan established. That file hardcodes the
password `app_runtime_local_only`, which must not be the deployed password. The
deploy script therefore runs, idempotently, on every deploy:

```
ALTER ROLE app_runtime PASSWORD :'pw';   -- value from Secrets Manager
```

which also gives password rotation for free, and leaves the shared init file
untouched.

#### 2.2 The backup mechanism: pgBackRest, and why not `pg_dump`

**Decision: pgBackRest is the backup. A weekly `pg_dump` is the escape hatch.
Daily EBS snapshots are the convenience.** Three layers, each with one job.

**Why pgBackRest rather than `pg_dump` on a timer.** `pg_dump` is simpler and its
output is portable, and if it were the only mechanism the RPO would be the dump
interval — lose up to a day of entries, or run hourly full dumps of a growing
database. pgBackRest adds the thing that decides it: **continuous WAL archiving**,
which is what point-in-time recovery is made of. With `archive_timeout = 60`,
every write reaches S3 within about a minute of being made. On a path with no RDS
PITR and one copy of a person's health history, the gap between "up to 24 hours"
and "up to 60 seconds" is the entire argument. pgBackRest also brings retention
management, `verify`, and repository-level encryption, each of which would
otherwise be a script to write and a script to get wrong.

**Configuration** (`/etc/pgbackrest/pgbackrest.conf`, mounted into the postgres
container):

```ini
[global]
repo1-type=s3
repo1-s3-bucket=eoehelp-<acct>-backups
repo1-s3-region=us-east-2
repo1-s3-key-type=auto            # the instance role; see section 6
repo1-path=/pgbackrest
repo1-cipher-type=aes-256-cbc     # passphrase in Secrets Manager
repo1-cipher-pass=<from secrets>
repo1-retention-full=4            # four weekly fulls ≈ 28 days
repo1-retention-diff=14
compress-type=zst
process-max=2
start-fast=y
log-level-console=info
log-level-file=detail

[eoehelp]
pg1-path=/var/lib/postgresql/data
```

**Schedule**, as host systemd timers calling `podman exec postgres pgbackrest …`:

| When | What |
|---|---|
| continuous | `archive-push`, driven by PostgreSQL's `archive_command` |
| Sunday 07:00 UTC | `backup --type=full` |
| daily 07:00 UTC | `backup --type=diff` |
| daily 07:30 UTC | `verify`, then publish `BackupAgeHours` to CloudWatch |
| Sunday 08:00 UTC | `pg_dump -Fc` **and** `pg_dumpall --roles-only` to S3 |

**pgBackRest needs a container that contains it.** PostgreSQL's `archive_command`
runs inside the database's own process tree, so the binary has to be in the
database image. Tier 0 therefore adds a third image: `infra/postgres/Dockerfile`,
four lines, `FROM` the same upstream digest that `infra/images.env` pins, plus
`apt-get install pgbackrest`. It is built, verified and pushed by the same
pipeline as the other two, and CI asserts with `skopeo inspect` that its base
digest equals the pin. Local development and CI keep using the plain upstream
image — they have no backups to take — so the only difference between the
databases is one package, and that difference is asserted rather than assumed.

*Considered and rejected:* running PostgreSQL on the host from AL2023's `dnf`
package, which would make pgBackRest a host package and remove the image
entirely. Rejected because the local, CI and production databases would then be
different builds of PostgreSQL with potentially different locale behaviour — the
exact class of silent difference the build plan's collation work was about — and
because the database's upgrade path would become `dnf` rather than a pinned
digest.

**The encryption story, stated in full, because three different keys are
involved and losing any one of them loses something different:**

| Layer | Protected by | If the key is lost |
|---|---|---|
| The live database on disk | EBS encryption, customer-managed KMS key | The volume is unreadable. Restore from S3. |
| The pgBackRest repository in S3 | **pgBackRest AES-256-CBC with a passphrase**, *and* S3 SSE-KMS with the same CMK | The backups are unreadable. There is no recovery. |
| The weekly `pg_dump` in S3 | S3 SSE-KMS | The dump is unreadable. |
| Free-text clinical columns (`notes_encrypted`, `prescriber_note_encrypted`, …) | Application-layer AES-GCM with `FIELD_ENCRYPTION_KEY` | **Every note in every backup is permanently unreadable.** The rows restore; the words do not. |

The repository passphrase means a leaked S3 object is ciphertext under a key AWS
never held, which is the point of doing it in addition to SSE-KMS rather than
instead of it.

**Three secrets whose loss is unrecoverable, and they go in one offline record,
written down, before the first real note is entered:**

1. `FIELD_ENCRYPTION_KEY`
2. the pgBackRest repository passphrase
3. the KMS customer-managed key (its deletion is a scheduled, 7-to-30-day,
   irreversible operation — and scheduling it makes every backup and the volume
   unreadable at the end of the window)

All three live in Secrets Manager with `recovery_window_in_days = 30` and
replication to a second region. That is defence in depth, not a substitute for
the paper copy, because the failure this guards against includes losing access to
the account.

**RPO and RTO, derived from the mechanism rather than chosen:**

- **RPO = 60 seconds.** `archive_timeout = 60` forces a WAL segment switch, and
  therefore an `archive-push` to S3, at least once a minute whenever there has
  been any write. Worst case is the writes in the current unarchived segment plus
  the push latency. For a product where a patient logs once a day, the realistic
  loss is zero entries.
- **RPO = 0 for instance replacement**, because the volume detaches and reattaches
  rather than being restored.
- **RTO: to be set by the first drill, not asserted here.** The components are a
  replacement instance from the same AMI (~3 minutes), `pgbackrest restore` of a
  few gigabytes (~5 minutes), recovery replay, and `compose up` pulling from ECR
  (~2 minutes). A target of **2 hours** leaves ample room, and the drill replaces
  the estimate with a measured number. An availability-zone failure costs the same
  RTO plus the time to notice.
- Storage cost of all this: a few gigabytes. `archive_timeout=60` sounds expensive
  until you note that pgBackRest compresses a nearly-empty 16 MB WAL segment with
  zstd to a few kilobytes. Budgeted below at $0.30/month for S3 in total.

**The third layer, for completeness:** an EBS Data Lifecycle Manager policy taking
a daily snapshot of the data volume, seven retained, with a weekly copy to
`us-west-2`. A snapshot of a running database is crash-consistent rather than
backup-consistent — PostgreSQL recovers from it exactly as it would from a power
cut, which for a single volume is sound but is not a substitute for WAL
archiving. It exists because "the volume is gone" is then a two-click recovery
that needs no PostgreSQL knowledge at all, and because it costs about $1.20/month.

#### 2.3 The restore drill — performed, not planned

**Runbook step R, performed once during setup within a week of the first real
data, and quarterly thereafter.** The product plan's line is that an untested
backup is not a backup; on this path it is the only safety net there is.

1. Launch a second `t4g.small` from the same AMI in the same subnet, with the
   instance profile. Start a stopwatch. *(A separate instance rather than a second
   data directory on the live box, because the point is to test the whole path,
   including that the AMI, the role, and the S3 access all still work.)*
2. `pgbackrest --stanza=eoehelp --type=time --target='<one hour ago>' --delta restore`
   into an empty data directory, then start PostgreSQL and wait for
   `pg_is_in_recovery()` to return false.
3. Run the verification container — **the current runtime image digest**, so the
   test exercises the code that will read the restored data — against it, checking
   all five of:
   - **row counts** for `patients`, `symptom_entries`, `food_log_items`,
     `medications`, `endoscopies`, `consents`, `audit_log`;
   - **`max(entry_date)` from `symptom_entries`**, compared against what you know
     you logged;
   - **one `notes_encrypted` value decrypted** with the live
     `FIELD_ENCRYPTION_KEY`, asserted to be readable text. This is the step that
     proves the restore is a restore and not a pile of ciphertext;
   - **`SELECT current_user` as `app_runtime`**, proving the role survived — and
     an unscoped `SELECT count(*) FROM patients` returning **0**, proving the
     policies survived. A restore that silently loses either is the dangerous
     case, because the obvious workaround is to connect as the owner, which
     disables every policy in ADR 0002's second layer;
   - **`alembic current`** matching the head the application expects.
4. Stop the stopwatch. **Write the elapsed time, the date, and anything that
   surprised you into `docs/runbooks/database-restore.md`.** An undocumented drill
   is an anecdote.
5. ⚠ **Terminate the test instance and delete its volumes.** A forgotten restore
   instance is the top unattended cost in this design; the budget alarm is the
   backstop, this step is the control.

**The trap the drill is designed to catch**, stated so it is not discovered
during a real restore: `pg_dump` of a database does **not** include cluster-level
roles. Restoring the weekly escape-hatch dump into a fresh cluster produces a
database with the right tables, the right policies and the right grants — and no
`app_runtime` role to hold them. That is why the weekly job runs `pg_dumpall
--roles-only` alongside `pg_dump -Fc`, and why the drill asserts on
`current_user` rather than just on row counts. pgBackRest restores the whole
cluster and does not have this problem; the escape hatch does.

### 3. TLS without ACM

**Caddy as the edge, with automatic Let's Encrypt certificates.**

Caddy is chosen over nginx-plus-certbot for one reason that matters more here
than anywhere else in the design: **the failure mode.** With certbot the classic
failure is not that renewal fails but that renewal succeeds and the reload never
happens, so the server keeps presenting the old certificate until it expires —
silently, for up to 30 days, with nothing on fire. Caddy renews in-process at
two-thirds of the certificate lifetime, retries continuously, uses the new
certificate immediately, and logs each attempt. Its configuration for this job is
about fifteen lines and includes the path split the ALB would have done:

```
eoehelp.org, www.eoehelp.org {
    encode zstd gzip
    handle /api/v1/* {
        reverse_proxy api:8000 {
            header_up X-Forwarded-For {remote_host}   # replace, never append
        }
    }
    handle {
        reverse_proxy web:8080
    }
    header Strict-Transport-Security "max-age=86400"
    log { output stdout   format json }
}
```

**Two operational facts that are load-bearing:**

- **The ACME account and the certificates live in Caddy's data directory, and that
  directory must be on the persistent data volume** (`/var/lib/eoehelp/caddy`),
  not in an anonymous container volume. If it is lost, every deploy re-issues, and
  Let's Encrypt's duplicate-certificate limit is five per exact name set per week
  — so the fifth redeploy in a week locks you out of getting a certificate at all,
  for days.
- **Port 80 must stay open to the world permanently**, not only during issuance,
  because the HTTP-01 challenge uses it at every renewal. Caddy also uses it for
  the HTTPS redirect.

**What fails when renewal fails, and how you find out before a patient does.**
The consequence is total: browsers refuse the site, the SPA never loads, and every
magic link — the only authentication path — points at a URL that errors. Three
controls:

1. A systemd timer on the host checks the served certificate's remaining days with
   `openssl s_client` and publishes `CertificateDaysRemaining` to CloudWatch.
   **Alarm below 21 days.** With a 90-day certificate renewed at 60, a value below
   21 means renewal has been failing for over a week.
2. The magic-link canary (section 5) fails when TLS fails, because it fetches over
   HTTPS. It is the end-to-end check.
3. An EventBridge-scheduled Lambda does an HTTPS `GET /healthz` every five
   minutes and alarms on a TLS error or a non-200 — free at this volume, and the
   only thing that notices when the whole instance is gone rather than merely
   unhealthy.

**HSTS becomes a hazard rather than a nicety on this path, which strengthens a
recommendation the first draft already made.** With a long `max-age`, a failed
renewal is not a clickable-through warning — it is a browser that refuses, with no
override, for the remaining lifetime of the policy. So: **`max-age=86400` (one
day) to start, no `includeSubDomains`, and emphatically no `preload`.** Raise it
only after several clean automatic renewals, and treat preload-list submission as
a separate decision, because removal from that list takes months.

Note also that the API's own HSTS middleware only fires when `is_production`
(`main.py:152`), so tier 0 as `staging` sends none. That is one of the
`ENVIRONMENT` splits in section 4; here Caddy sets the header for every response
regardless, which is the belt to the application's braces.

*Considered:* DNS-01 validation via Route 53, which would renew without needing
port 80 or the site being reachable. It needs a Caddy build with the Route 53
module, i.e. an image we build and maintain. Noted as the upgrade if HTTP-01 ever
proves flaky; not worth a fourth custom image today.

### 4. The four collisions between this codebase and tier 0

Tier 0 must run as `ENVIRONMENT=staging`, because
`identity/documents.enforce_review_status` refuses to start in production while
any of the three onboarding documents is an unreviewed draft — and all three are
(`documents.py` lines 144, 157, 170). That one string then governs four other
things that have nothing to do with legal review.

`ENVIRONMENT` is currently the axis for five separate questions. It should be
two:

| Control | Where | Gated on today | Should be gated on |
|---|---|---|---|
| Refuse unreviewed legal drafts | `identity/documents.py:369` | `== "production"` | unchanged |
| Hide `/docs` | `main.py:84` | `is_production` | unchanged |
| Refuse dev JWT secret, dev field key, dev USDA key, missing Redis, `debug` | `config.py:136` | `is_production` | **`!= "local"`** |
| Send HSTS | `main.py:152` | `is_production` | **`!= "local"`** |
| Refuse to write synthetic data | `synthetic/writer.py:67` | `is_production`, staging behind a flag | see collision 4 |

**Collision 1 — secrets are not enforced in `staging`. The check, in three
layers**, unchanged in substance from the Fargate draft and adapted to where
things now run:

1. **Wiring, before the stack starts.** `scripts/verify-deploy-env.sh` runs on the
   instance as the first step of every deploy, against the rendered environment
   file and the resolved compose configuration (`compose config`), and fails
   closed if:
   - `ENVIRONMENT` is not exactly the value this environment declares (`staging`
     at tier 0, `production` at tier 1) — the assertion the build plan asked for,
     as a check rather than a note;
   - `JWT_SECRET`, `FIELD_ENCRYPTION_KEY`, `SMTP_PASSWORD`, `USDA_FDC_API_KEY`,
     the pgBackRest passphrase, or a password-bearing `DATABASE_URL` appear
     anywhere except the Secrets-Manager-materialised file at `/etc/eoehelp/app.env`
     (mode 0600, root-owned);
   - `REDIS_URL` is unset, or `DEBUG` is true;
   - either application image is referenced by tag rather than `@sha256:`;
   - the image architecture is not `arm64` (`skopeo inspect`);
   - `FORWARDED_ALLOW_IPS` is not exactly the declared network CIDR;
   - the `api`, `web`, `postgres` or `valkey` services publish **any** host port;
   - the `api` service's `DATABASE_URL` contains the owner username.

   The same script runs in CI against the committed compose files and a fixture
   env file, so most of these fail on a pull request rather than on the box.

2. **Value, from outside, after every deploy.** CI mints a JWT signed with
   `DEV_JWT_SECRET` — the value is public, it is in `config.py` — for a random
   patient id, and calls `GET /api/v1/me/profile` over HTTPS at the real hostname.
   **A 401 is the pass. Anything else fails the deploy and triggers a rollback.**
   This proves the deployed signing key is not the repository's, from outside,
   without reading the secret.

3. **Value, at boot, for the key no external check can see.** Widen
   `config.enforce_production_safety` to run whenever `environment != "local"`, and
   rename it `enforce_deployed_safety`. The field-encryption key is compared by
   equality against `DEV_FIELD_ENCRYPTION_KEY`, so a dev key means the container
   will not start — which is the strongest available proof of that value, and it
   is why a green deploy is itself evidence. It also makes `REDIS_URL` and
   `DEBUG=false` mandatory in tier 0, both of which are correct.

   For the implementer: `apps/api/tests/core/test_config.py` and
   `apps/api/tests/synthetic/test_synthetic.py` construct
   `Settings(environment="staging")` directly, which is unaffected because the
   guard is called from `get_settings()`; but any test reaching `get_settings()`
   with a non-local environment will need real values. The build plan's
   `infra/local-prod.env` already generates real keys via `just secrets`, so
   `just up-prod` and CI's prod-shaped stack keep passing.

**Collision 2 — RLS has never run against a live application.** It has now; see
*What was verified*. Tier 0 runs the service as `app_runtime` from the first
deploy, with migrations as a separate one-shot container under the owner, and
makes it a gate rather than a hope. After each deploy, a one-off container using
the **runtime image digest** and the **service's** `DATABASE_URL` runs:

```sql
SELECT current_user;                                    -- must not be the owner
SELECT count(*) FROM patients;                          -- must be 0: no scope set
SELECT count(*) FROM symptom_entries;                   -- must be 0
SELECT has_table_privilege('app_runtime','alembic_version','SELECT');  -- false
```

Any row from the first two means RLS is not binding, and the deploy fails. This is
the deployed equivalent of `tests/db/test_patient_isolation.py`, and the restore
drill runs the same four checks against the restored copy.

**Collision 3 — `FORWARDED_ALLOW_IPS`, for an edge that is now a container on the
same box.** uvicorn sees the **Caddy container's** address on the compose bridge
network. So:

- **Pin the network** in `compose.deploy.yaml` rather than letting podman allocate
  one, so the value is a constant and not a discovery:

  ```yaml
  networks:
    edge:
      ipam:
        config: [{ subnet: 10.90.0.0/24 }]
  ```

- **`FORWARDED_ALLOW_IPS=10.90.0.0/24`.** Measured working in exactly this shape
  today (the probe ran through a podman bridge on `10.89.0.0/24`).
- **Never `*`.** With `always_trust`, uvicorn takes the *leftmost*
  `X-Forwarded-For` entry, which is entirely client-controlled, and both the audit
  trail and the rate limiter become spoofable.
- The spoofing path is closed twice over here, which is better than the ALB case:
  Caddy is configured with `header_up X-Forwarded-For {remote_host}`, which
  **replaces** rather than appends, so there is only ever one entry and it is the
  real peer; and the `api` container publishes no host port, so the only peer
  uvicorn can ever see is Caddy.
- The assertion: the post-deploy smoke test sends a request with a bogus
  `X-Forwarded-For` and then reads the newest `audit_log` row, asserting its
  `ip_address` is the runner's real address and not `10.90.*` and not the bogus
  value.

**Collision 4 — the synthetic seeder is one flag away.** `synthetic/writer.py`
refuses `production` outright and permits `staging` with `allow_staging=True`.
Tier 0 *is* `staging` and holds real data, so the guard that exists is the wrong
one, and on this path there is no separate account boundary to fall back on. Two
mitigations: the deployed environment file never contains anything that would let
the seeder run, and the recommended application follow-up is an
`ALLOW_SYNTHETIC_DATA` setting defaulting to false so the permission is a
deliberate environment variable rather than a command-line argument. Until then
the rule goes in the runbook in capitals: **never run `just seed` against tier 0.**

### 5. Secrets, SES, DNS and the audit archive

**Secrets.** One Secrets Manager secret holding the application's secrets as JSON,
at $0.40/month:

```
eoehelp/staging/app  →  {
  "JWT_SECRET": "...",              # 32+ bytes
  "FIELD_ENCRYPTION_KEY": "...",    # 32 bytes urlsafe base64  ⚠ unrecoverable
  "USDA_FDC_API_KEY": "...",        # a real key from api.data.gov, not DEMO_KEY
  "SMTP_PASSWORD": "...",           # SES SMTP credential
  "DB_OWNER_PASSWORD": "...",
  "DB_APP_RUNTIME_PASSWORD": "...",
  "PGBACKREST_CIPHER_PASS": "..."   # ⚠ unrecoverable
}
```

**Terraform creates the secret but never its value** — a placeholder plus
`lifecycle { ignore_changes = [secret_string] }`, with the real values written
once from your machine with `aws secretsmanager put-secret-value`. Terraform state
is a plaintext copy of everything it manages, and `random_password` lands in state
too. The deploy script materialises `/etc/eoehelp/app.env` from the secret at
0600, root-owned, on every deploy; it is never committed and never in an image.

Rotation, written now: `JWT_SECRET` rotates freely (it invalidates access tokens;
refresh tokens are DB-backed and survive). The two database passwords rotate with
an `ALTER ROLE` and a restart. **`FIELD_ENCRYPTION_KEY` cannot be rotated** without
a re-encryption pass over every `*_encrypted` column, which does not exist — treat
it as permanent and say so in `docs/runbooks/key-rotation.md`. The pgBackRest
passphrase cannot be rotated without starting a new repository, so rotating it
means keeping the old one until the old backups age out.

**SES.** Unchanged from the Fargate draft, because it does not touch compute.

- **Tier 0 does not need SES production access.** The sandbox allows 200 messages
  per 24 hours to *verified* addresses, and at tier 0 the only recipient is you.
  Request production access anyway — it takes about a day and the request is
  stronger from a working, low-bounce sender — but tier 0 works without it.
- Domain identity with Easy DKIM (three CNAMEs); **a custom MAIL FROM domain**
  `mail.eoehelp.org` with its MX and SPF records, so SPF aligns for DMARC rather
  than passing on DKIM alone; one SPF TXT record on the apex merging
  `include:amazonses.com` with anything the DNS export turns up (two SPF records
  is a permanent fail); DMARC at `p=none` with `rua`, moving to `p=quarantine`
  after two weeks of clean reports and then `p=reject`.
- A configuration set with an SNS event destination for `bounce`, `complaint`,
  `delivery`, `reject` and `renderingFailure`, and alarms at bounce > 5% and
  complaint > 0.1% — SES suspends at 10% and 0.5%, and suspension means nobody can
  sign in.
- **A daily magic-link canary**: a host timer requests a link for a dedicated
  mailbox and asserts a `delivery` event within five minutes. It also fails when
  TLS fails, which makes it the cheapest end-to-end check in the design.
- `SMTP_HOST=email-smtp.us-east-2.amazonaws.com`, `SMTP_PORT=587`,
  `SMTP_USE_TLS=true` (aiosmtplib's `start_tls`, i.e. STARTTLS — correct for 587).
- **SES SMTP credentials are a long-lived IAM credential**, which sits oddly beside
  "GitHub OIDC, no long-lived keys". Tier 0 accepts it with the credential in
  Secrets Manager and a rotation runbook. On this path the fix is easier than it
  was on Fargate — the instance has a role — so moving `EmailSender` to the SES v2
  API is a contained change to `identity/email.py` and is the recommended
  follow-up.

**DNS.** Unchanged except that the target is an Elastic IP rather than an ALB
alias, and that there is no ACM.

- **Use an Elastic IP, not the auto-assigned public address.** An instance
  replacement then keeps the same address and DNS needs no change, which removes a
  propagation delay from the middle of every recovery. It costs the same $3.65/month
  either way.
- Apex and `www` are plain `A` records to that address. (There is no
  apex-CNAME problem to solve, which is the one way this path is simpler.)
- **Export every Squarespace DNS record first** — Squarespace's nameserver connect
  strips existing records, and a missing MX or SPF breaks mail silently. Section
  *Runbook, phase D* has the ordering.
- **CAA after the certificate issues**, and for Let's Encrypt rather than Amazon:
  `0 issue "letsencrypt.org"` plus `0 iodef "mailto:security@eoehelp.org"`. **This
  is a real difference from the Fargate draft** — a CAA record naming only Amazon
  would block Let's Encrypt from ever issuing, and the symptom would be a renewal
  that fails silently until the certificate expires. If tier 1 later moves to ACM,
  the CAA record must gain the Amazon values *before* the first ACM request.
- `TrustedHostMiddleware` with the deployed hostnames goes in alongside; `main.py`
  already carries `redirect_slashes=False` as the interim fix for the host-header
  open redirect the 2026-09-21 security review demonstrated, with a comment saying
  the complete fix belongs with the deploy plan. This is that plan. Caddy's
  `handle` blocks are matched per site, so a request with a foreign `Host` never
  reaches the application in the first place — but the middleware is the half that
  survives an edge change.

**The audit archive.** `audit_log` is the answer to "did someone read my record",
and `app_runtime` holds only `INSERT` and `SELECT` on it (verified).

**Create the bucket at tier 0 with `object_lock_enabled = true`**, even though the
export job could land later: Object Lock can only be enabled at bucket creation
in the normal path, and the bucket costs nothing empty. **GOVERNANCE mode with a
one-year default retention**, per the user's decision — COMPLIANCE cannot be
shortened or overridden by anyone including the account root, so a mistake becomes
a year of unavoidable, unfixable storage. `s3:BypassGovernanceRetention` is denied
in the bucket policy to everything except a documented break-glass role.
Versioning on, public access blocked, SSE-KMS.

The exporter is a host systemd timer, daily, running a short-lived container that
connects **as `app_runtime`** (least privilege, and it proves the grant) and
streams NDJSON:

```
COPY (SELECT row_to_json(a) FROM audit_log a WHERE id > :watermark ORDER BY id)
  TO STDOUT
```

piped to `aws s3 cp` with `--object-lock-retain-until-date`. The watermark is an
S3 object, not a database row, so a database restore cannot rewind it into
re-exporting. The exporter's role gets `s3:PutObject` and `s3:PutObjectRetention`
and nothing else — no `DeleteObject`, no bypass — and the setup runbook proves it
by attempting a delete and asserting AccessDenied.

The archive contains `ip_address` and `user_agent`, which are PHI-adjacent, and
field names and counts but never values, per the audit-metadata policy. Treat the
bucket as PHI.

### 6. Access, identity and the metadata-service exception

**No SSH.** No key pair, no port 22, no bastion. Interactive access is AWS Systems
Manager Session Manager, which needs only the instance profile and outbound HTTPS,
and which logs every session to CloudWatch. This removes the last long-lived
credential that a single-instance design would otherwise want.

**Security group.** Inbound: TCP 80 and 443 from `0.0.0.0/0`, nothing else.
Outbound: all, for ECR, S3, Secrets Manager, SSM, SES, and the Open Food Facts and
USDA lookups the application makes. There is no NAT gateway on this path because
there is nothing in a private subnet.

**IMDSv2 required** (`http_tokens = "required"`). The hop limit needs thought
rather than a default, and this is the one genuinely fiddly piece of the design:

- With `http_put_response_hop_limit = 1`, containers on a bridge network cannot
  reach `169.254.169.254` at all, so **no container can assume the instance role**.
  That is exactly what you want for the `api` container, which is the one
  processing untrusted input and where a server-side request forgery would
  otherwise hand over the instance's credentials.
- But **pgBackRest runs inside the postgres container and needs S3 credentials**,
  continuously, because `archive_command` is a PostgreSQL child process. Static
  keys would be a long-lived credential, which is the thing this design has
  otherwise eliminated.
- **Resolution: hop limit 2, plus an nftables rule on the host that allows
  `169.254.169.254` only from the postgres container's pinned address on the
  `10.90.0.0/24` network and drops it from every other address on that network.**
  Three rules, declarative, applied by a systemd unit at boot and asserted by the
  setup runbook (`podman exec api curl -m 2 http://169.254.169.254/latest/api/token`
  must time out; the same from `postgres` must succeed).

**Instance role**, minimal: `AmazonSSMManagedInstanceCore`; `ecr:GetAuthorizationToken`
plus pull on the three repositories; `secretsmanager:GetSecretValue` on the one
secret; `kms:Decrypt` on the one key; `s3:GetObject/PutObject/DeleteObject/ListBucket`
scoped to the backup bucket prefix (pgBackRest needs delete for expiry) and
`s3:PutObject`/`PutObjectRetention` on the audit-archive prefix; `ses:SendRawEmail`;
`cloudwatch:PutMetricData`. Nothing else.

**Patching.** `dnf-automatic` applies security updates nightly. Reboots happen
only when a package requires one and only inside the declared window (Sunday
08:00 UTC); `eoehelp.service` brings the stack back at boot, and a post-boot
timer publishes a heartbeat metric so a failure to come back is alarmed rather
than noticed. A ~60-second outage in a weekly window is the right trade against
an unpatched kernel on an internet-facing box.

**Auto-recovery.** A CloudWatch alarm on `StatusCheckFailed_System` with the
`arn:aws:automate:us-east-2:ec2:recover` action, which migrates the instance to
healthy hardware keeping the same volumes and Elastic IP. Free, and it covers the
most common infrastructure failure without any decision from you.

### 7. Deploy: how a promoted digest reaches this instance

ADR 0006's rule holds unchanged: build once, test that image, run *that digest*.

1. **`publish.yml`**, on push to `development`. buildah builds `runtime`,
   `web-runtime` and the new `postgres` image on `ubuntu-24.04-arm`,
   `scripts/verify-image.sh` asserts manifest, arm64, non-root and no test
   tooling, then pushes to **ECR** as `candidate-<sha>`, reads the digests back
   with `skopeo inspect`, and writes `digests.json`. This is the build plan's
   existing workflow with `vars.REGISTRY` pointed at ECR and the `GITHUB_TOKEN`
   login replaced by OIDC plus `aws ecr get-login-password` — the change that plan
   promised would be two variables and a login step.

2. **`deploy.yml`**, on `publish.yml` succeeding. It assumes the OIDC role, writes
   the digests to **SSM Parameter Store** (`/eoehelp/staging/api_digest`,
   `/web_digest`, `/postgres_digest`), and then invokes
   `aws ssm send-command` to run `/opt/eoehelp/deploy.sh` on the instance.

   SSM rather than SSH: no inbound port, no key in GitHub secrets, no long-lived
   credential, and the command's output and exit code come back to the runner so
   the workflow can fail. Parameter Store rather than only passing arguments,
   because the instance's boot script reads the same parameters and therefore
   comes back on the right version after a reboot or a replacement.

3. **`/opt/eoehelp/deploy.sh`**, on the instance, in order:
   a. read the three digests from Parameter Store;
   b. `aws ecr get-login-password | podman login`, then
      `podman pull <repo>@sha256:<digest>` for each — **by digest, never by tag**;
   c. materialise `/etc/eoehelp/app.env` from Secrets Manager (0600, root);
   d. **`scripts/verify-deploy-env.sh`** — the assertions in collision 1. Fails
      closed, before anything is restarted;
   e. `ALTER ROLE app_runtime PASSWORD` from the secret, idempotent;
   f. **run migrations as a separate one-shot container under the owner role**:
      `podman run --rm --network eoehelp_edge -e DATABASE_URL=<owner url>
      <api-digest> alembic upgrade head`. **A non-zero exit aborts the deploy and
      leaves the running service untouched**;
   g. `compose -f compose.prod.yaml -f compose.deploy.yaml up -d --wait`;
   h. record the previously running digests in `/etc/eoehelp/previous.env`.

4. **Post-deploy gates**, all required, run partly from the GitHub runner (the
   HTTP-shaped ones, so they traverse the real DNS name and the real certificate)
   and partly on the instance via SSM (the ones needing database access):
   - `GET https://eoehelp.org/healthz` and `/readyz` → 200;
   - a JWT signed with `DEV_JWT_SECRET` → **401**;
   - the RLS proof from collision 2;
   - `scripts/smoke.sh https://eoehelp.org` — magic-link sign-in, a symptom entry
     written and read back, and the `X-Forwarded-For` assertion.

   Any failure triggers the rollback below and fails the workflow.

5. **Reverting a bad release.** `deploy.sh --rollback` reads
   `/etc/eoehelp/previous.env` and repeats step 3 with those digests. The images
   are still in the local store, so there is no pull — **this is faster than the
   ECS equivalent, typically under a minute**, and it is one of the few places
   this path is genuinely better.

   **The migration caveat is unchanged and more acute than it was on Fargate.** A
   digest rollback does not undo a migration; the old image will run against the
   new schema. There are two paths: roll forward with a corrective migration, or
   restore the database to a point in time before it. On this path the second is
   pgBackRest PITR, which is the *only* fallback there is — which means the
   discipline matters more, not less:

   > **Every migration must leave the schema compatible with the immediately
   > preceding image.** Expand first (add nullable columns, add tables), deploy,
   > contract in a later release. CI already runs `upgrade/downgrade/upgrade`,
   > which proves a migration is reversible *in isolation* — a different and
   > weaker property than "the previous code still works against the new schema".
   > Write that difference into the ADR so nobody mistakes the green check for the
   > guarantee.

6. **Image garbage collection.** A weekly timer runs `podman image prune` keeping
   the last three digests of each image. Without it the 20 GB root volume fills,
   and a full root volume stops podman, journald and the backup timers — the
   database survives on its own volume but nothing else does. Alarm on root volume
   usage above 80%.

### 8. Tier 0 cost

`us-east-2`, list prices queried today, 730 hours.

| Line | $/month |
|---|---|
| EC2 `t4g.small`, on demand | 12.26 |
| EBS gp3, root, 20 GB | 1.60 |
| EBS gp3, data, 20 GB | 1.60 |
| Elastic IP (in use) | 3.65 |
| EBS snapshots — 7 daily incrementals + a weekly copy to `us-west-2` | 1.20 |
| S3 — pgBackRest repository, WAL, weekly dumps, audit archive, state | 0.30 |
| Route 53 hosted zone | 0.50 |
| Secrets Manager, 1 secret | 0.40 |
| KMS, 1 customer-managed key version | 1.00 |
| ECR, ~1.5 GB with a 3-deep lifecycle | 0.15 |
| CloudWatch — 6 custom metrics and 12 alarms, against a 10/10 always-free allowance | 0.20 |
| CloudTrail, one management trail | 0.00 |
| Lambda HTTPS canary (free tier) | 0.00 |
| SES, ~100 messages | 0.01 |
| Data transfer out, under 100 GB | 0.00 |
| Let's Encrypt | 0.00 |
| **Total at list price** | **$22.87** |

**Month 1**, if the old twelve-month free tier applies (30 GB of EBS, 500 MB of
ECR): subtract **$2.45** → **$20.42**.

**Month 13:** **$22.87**.

**What breaks at month 12: nothing, and on this path there is barely a step at
all.** The twelve-month allowances that matter here amount to $2.45/month,
because `t4g.small` is not in the free tier and there is no RDS or ElastiCache
allowance to lose. That is a genuine advantage of the decision: the bill is
essentially flat from day one, and there is no cliff to plan for.

**How you would know anyway**, since the discipline is worth keeping: a forecasted
AWS Budget at $40/month with alerts at 50/80/100%, free-tier usage alerts enabled
in Billing preferences, and a month-11 calendar reminder in
`docs/runbooks/` to re-read this table.

**If the account is on the newer credit-based plan**, the $22.87 is drawn against
the signup credit, which lasts several months — and then, on a "Free plan",
**exhausting it can suspend resources rather than generate an invoice.** On this
path a suspended instance means an EBS volume you cannot reach holding the only
live copy of your health record. The backups in S3 survive, which is precisely why
they exist, but this is still the worst available failure. **Check Billing →
Account plan before the first real entry and move to a Paid plan if it is not
already one.** It is runbook step 1 for that reason.

**Comparison over time**, so the decision's shape is visible:

| | Month 1 | Month 13 | Year 1 total | Year 2 total |
|---|---|---|---|---|
| EC2 (chosen) | $20.42 | $22.87 | ~$270 | ~$274 |
| ECS Fargate (rejected) | $38.59 | $62.01 | ~$463 | ~$744 |
| **Saving** | $18.17 | $39.14 | **~$193** | **~$470** |

**What can run up a bill unattended**, in order of likelihood on this path:

1. **A restore-drill instance and its volumes left running.** ~$15/month, silent.
   Runbook step R5 deletes it; the budget alarm catches the miss.
2. **EBS snapshots with no expiry.** The DLM policy retains seven and copies one a
   week; without a retention rule they accumulate at $0.05/GB-month forever.
3. **CloudWatch custom metrics.** They are $0.30 each beyond the free ten, and the
   CloudWatch agent will happily publish dozens if configured with a default
   template. Publish exactly the six named in section 10.
4. **CloudWatch Logs with no retention.** The default is "never expire"; every log
   group gets an explicit retention in Terraform.
5. **ECR with no lifecycle policy.** Three ~500 MB images per push, forever.
6. **CloudTrail data events.** Management events on one trail are free; S3 and
   Lambda data events are billed per event and can be enormous. Not enabled.
7. **WAL archiving with compression disabled.** `compress-type=zst` turns a mostly
   empty 16 MB segment into kilobytes; without it, `archive_timeout=60` could
   write ~700 GB/month.

### 9. Tier 1 from here: the deferred bill, sized

Tier 1 is the launch-gate posture — two accounts under an Organization, Multi-AZ
RDS, private subnets, CloudFront and WAF, promotion with a human gate. Its running
cost is unchanged at **$256/month** (itemised below). What the EC2 decision
changed is what it takes to *get* there, and the user should see that number now
rather than while standing in it.

**Which account becomes production?** Tier 0's, per the user's decision. An
existing standalone account can be invited into a new Organization, so the account
itself needs no rebuilding, and your real history never moves between accounts.

**What has to be built that tier 0 does not build**, because on this path almost
none of it is a resize:

| Work | Nature |
|---|---|
| ECS cluster, task definitions, service, ALB, target groups, deployment circuit breaker | built from nothing; the SSM/`deploy.sh` mechanism is discarded |
| **Migrating the database from the instance into RDS** | a rehearsed operation on the only copy of the record — `pg_dump`/`pg_restore` with a planned outage, or logical replication with a cutover |
| RDS: instance, parameter group, subnet group, CMK, automated backups | new; and pgBackRest is retired in favour of RDS PITR, so the existing repository becomes a historical archive to keep or consciously discard |
| ElastiCache instead of the Valkey container | new; and `REDIS_URL` moves from a container name to an endpoint |
| ACM instead of Let's Encrypt | new; **and the CAA record must gain the Amazon values before the first ACM request**, or issuance fails |
| Secrets delivery: env-file materialisation → ECS `secrets` with `valueFrom` | rewritten |
| The three post-deploy gates | rewritten against ECS RunTask instead of SSM |
| `FORWARDED_ALLOW_IPS` | changes from the container CIDR to the subnet CIDRs, plus CloudFront's ranges (see below) |
| The edge | Caddy is replaced by ALB and CloudFront; routing, TLS and headers all move |
| Monitoring | host-agent metrics → ECS, RDS and ALB metrics; every alarm re-pointed |
| CloudFront, WAF, GuardDuty, private subnets, NAT, the second account | new either way |

**Sizing it honestly: two to three focused weeks**, versus two to three days of
resizes from the Fargate path, **plus a rehearsed database migration with a
planned outage, performed against a live database holding a year of real
history** — which is exactly the situation ADR 0004 argued to avoid when it wrote
that standing up infrastructure "later, against a live app with real patient data
and a cutover to plan, is not [straightforward]".

**The mitigation, which is a real design obligation and not a consolation.** The
rebuild is now certain, so tier 0 must keep the seams where tier 1 will cut. This
is ADR 0004's portability discipline, applied to this path:

- PostgreSQL stays vanilla — `pgcrypto` and `citext` only, which is already true.
  No extension that RDS does not offer, ever.
- The application only ever learns about its dependencies through `DATABASE_URL`
  and `REDIS_URL`, so swapping in RDS and ElastiCache endpoints is a value change.
- **Secrets come from Secrets Manager even at tier 0**, materialised into a file
  rather than stored in one. The source of truth does not move at tier 1; only the
  delivery does.
- **Images always come from ECR by digest**, so the registry does not move.
- The edge always performs the same `/api/v1/*` split and sets the same forwarded
  headers, so the application's view of the world does not move.
- **Nothing may depend on the box**: no report PDFs on the local filesystem (S3
  from the day M3 lands), no host cron doing application work (the same container
  images, invoked by timers), no Python installed on the host, no data in a
  container's writable layer.

Violating one of these is what turns a two-to-three-week rebuild into a project.

**Tier 1 running cost**, unchanged from the first draft and retained so the number
is not lost. Production: ALB $16.73, ALB public IPv4 $7.30, NAT $33.30, Fargate
2 × 0.5 vCPU/1 GB ARM $28.84, RDS `db.t4g.small` Multi-AZ $47.45, RDS gp3 50 GB
Multi-AZ $11.50, ElastiCache Valkey × 2 $18.69, CloudFront $0, WAF $11.60,
Route 53 $0.70, Secrets Manager $2.00, KMS $4.00, CloudWatch $3.00, CloudTrail
$0.50, GuardDuty $4.00, S3 $2.00, SES $1.00, ECR $0.30 — **$192.90**. Staging:
ALB $16.53, public IPv4 $10.95, Fargate $8.51, RDS Single-AZ + storage $13.98,
ElastiCache $9.34, Route 53 $0.50, Secrets $0.80, KMS $1.00, CloudWatch/S3/ECR
$1.50 — **$63.11**. **Total $256/month**, which tests ADR 0004's $250–300 claim
and finds it sound; NAT, the two ALBs and Multi-AZ RDS are 56% of it.

**The CloudFront trap, which tier 1 must handle as a pair, not separately.**
uvicorn walks `X-Forwarded-For` right to left and returns the first untrusted host
(read from source, section *What was verified*). Putting CloudFront in front of an
ALB makes the rightmost entry a CloudFront edge address, so every audit row would
record CloudFront and every request would share a rate-limit bucket. Tier 1 must
therefore (1) set `FORWARDED_ALLOW_IPS` to the subnet CIDRs **plus** CloudFront's
ranges, from Terraform's `data "aws_ip_ranges" { services = ["cloudfront"] }` so a
re-apply tracks changes, and (2) restrict the ALB's security group to the managed
prefix list `com.amazonaws.global.cloudfront.origin-facing` — without which
trusting CloudFront's ranges would let anyone put their own distribution in front
of your ALB and spoof a client address. Neither works without the other.

**Flipping `ENVIRONMENT` to `production`** is a variable change — **but only once
the legal documents are attorney-reviewed**, or `enforce_review_status` refuses to
boot. That refusal is the control working, and it is the most likely tier-1 deploy
failure, so it is written here rather than discovered at 2am.

## Terraform layout, and the state bootstrap problem

```
infra/terraform/
  bootstrap/            # run once; local state, then migrated into its own bucket
  modules/
    network/            # VPC, subnets, route table, security group, IGW
    instance/           # AMI, instance, instance profile, EIP, data volume,
                        # DLM snapshot policy, auto-recovery alarm
    secrets/            # Secrets Manager shells — values never in state
    storage/            # ECR, backup bucket, audit-archive bucket (Object Lock)
    dns/                # Route 53 records, CAA
    email/              # SES identity, DKIM, MAIL FROM, config set, alarms
    observability/      # log groups, alarms, SNS, budgets, anomaly monitor, canary
    ci_oidc/            # GitHub OIDC provider + roles
  envs/
    staging/            # tier 0 lives here; becomes production at tier 1
```

`required_version = "~> 1.13"`, `hashicorp/aws ~> 6.0`, `.terraform.lock.hcl`
committed, `default_tags` applying `Project`, `Environment` and
`ManagedBy=terraform` so an untagged resource is visibly hand-made.

**The bootstrap chicken and egg.** Terraform needs an S3 bucket for state, and the
bucket must exist before the backend can be configured:

1. `infra/terraform/bootstrap/` uses a **local backend** and creates exactly three
   things: the state bucket (versioned, SSE-KMS with its own key, public access
   blocked, `prevent_destroy`), that key, and the GitHub OIDC provider and roles.
2. `terraform apply` once, from your machine, with admin credentials.
3. Add the `backend "s3"` block pointing at the bucket it just created and run
   `terraform init -migrate-state`. Bootstrap now stores its own state in the
   bucket it manages. The local `terraform.tfstate` is deleted and **never
   committed** — `.gitignore` gains `*.tfstate*` and `.terraform/`.
4. Every other root uses that bucket with a distinct `key`.

**Use S3 native state locking** (`use_lockfile = true`, Terraform 1.11+) rather
than a DynamoDB table: one fewer resource to pay for and forget.

**State holds secrets** — ARNs, endpoints, and anything a provider returns, plus
anything created with `random_*`. The bucket is SSE-KMS with a key policy limited
to the bootstrap admin and the CI roles, versioned so a corrupt apply is
recoverable, and never public.

**No skeleton.** The build plan refused to commit Terraform that could not `plan`,
and it was right. This plan's Terraform is written when the account exists.

**GitHub OIDC**, two roles, each with **two** trust conditions — `aud =
sts.amazonaws.com` and an **exact** `sub`. A `repo:<owner>/*` wildcard is the
classic hole: any workflow in any branch of any repository you own could then
assume the role.

| Role | `sub` condition | Permissions |
|---|---|---|
| `gha-plan` | `repo:<owner>/eoehelp:pull_request` | read-only, `terraform plan` |
| `gha-deploy` | `repo:<owner>/eoehelp:ref:refs/heads/development` | ECR push, `ssm:SendCommand` on the one instance, `ssm:PutParameter` on `/eoehelp/*`, `terraform apply` |

At tier 1 the production deploy role trusts `…:environment:production`, and the
GitHub Environment's required reviewer is where the human gate lives.

## Application and repository changes this plan depends on

Small, contained, and each a prerequisite rather than a nice-to-have. They belong
to the implementer of *this* plan.

| Change | File | Why |
|---|---|---|
| `enforce_production_safety` → `enforce_deployed_safety`, guarded on `environment != "local"` | `config.py:131–160` | the only thing that refuses a dev field-encryption key in a tier 0 that must run as `staging` |
| HSTS on `environment != "local"`, and drop `preload`; start at `max-age=86400` | `main.py:152` | tier 0 sends no HSTS today, and a long max-age plus a failed Let's Encrypt renewal is an unclickable-through lockout |
| `TrustedHostMiddleware` with the deployed hostnames | `main.py` | the complete fix for the host-header redirect; `redirect_slashes=False` was the interim |
| `ALLOW_SYNTHETIC_DATA` setting, default false, checked by `assert_writable` | `config.py`, `synthetic/writer.py:67` | tier 0 is `staging`, where the seeder is one flag from writing invented entries into a real record |
| `infra/postgres/Dockerfile` — the pinned upstream digest plus `pgbackrest`, built and published as a third image | new | `archive_command` runs inside the database's process tree, so the binary must be in the image |
| `compose.deploy.yaml` — the deployment override, with the pinned `10.90.0.0/24` network | new, next to `compose.prod.yaml` | one orchestration definition shared with `just up-prod`, with a visible diff |

**A recommendation for the build plan, which is being implemented right now and
whose stage 4 has not landed.** That plan's local edge is nginx
(`infra/local-edge/edge.conf`). If it became **Caddy** instead, with the same
Caddyfile that section 3 deploys and `auto_https off` locally, the edge would be
one file at both tiers rather than two configurations that have to be kept
equivalent by hand. It is a smaller change now than later. If stage 4 has already
shipped nginx, production still uses Caddy and the parity is by configuration
rather than by file — say so in the ADR, and the renewal-failure risk in section 3
is the reason the production side does not simply match it.

## Security and privacy

- **Patient data.** No new table, column, endpoint or query. RLS, grants, the
  repository pattern and `/me` routing are untouched;
  `tests/test_architecture.py` and `tests/db/test_patient_isolation.py` need no
  change and must stay green. What changes is that the `app_runtime` path becomes
  the deployed path and is asserted after every deploy and after every restore.
- **What improves.** `audit_log.ip_address` becomes the patient's address rather
  than a network hop, and the rate limiter gets a per-client bucket — both measured
  broken today. The dev JWT secret becomes provably absent from a deployed
  environment. RLS binds in production for the first time.
- **PHI boundaries.** PHI exists on the encrypted EBS data volume, in the
  pgBackRest repository in S3 (doubly encrypted), in the weekly dump in S3, in the
  audit archive (`ip_address` and `user_agent` only), and in transit over TLS.
  Free text stays application-layer AES-GCM encrypted with a key that lives only
  in Secrets Manager and on paper.
- **Logs never carry PHI.** `observability.py` already logs route templates rather
  than resolved paths and field names rather than values, and uvicorn runs with
  `--no-access-log`. Caddy's access log records method, path and status; **its
  configuration must not enable request or response body logging**, and the path
  it records can contain a share-link token once M3 lands — so revisit the edge
  log format when share links ship.
- **New third parties.** All AWS, under the BAA, except one: **Let's Encrypt**,
  which is new on this path and did not appear in the Fargate design. It receives
  the domain name and the fact that a certificate was requested — no patient data,
  no PHI, and it is a certificate authority rather than a data processor. It does
  not need a BAA, but it is a subprocessor-adjacent fact that belongs in any
  vendor register the privacy policy points at, so **flag this for the legal
  reviewer** alongside AWS.
- **Credentials.** No SSH key, no GitHub-stored AWS key, no bastion. The one
  long-lived credential is the SES SMTP password, named with its rotation runbook
  and its replacement.
- **Least privilege.** The instance role is enumerated in section 6. The
  audit-archive writer holds no `DeleteObject` and no bypass. Containers cannot
  reach the instance metadata service except the database container, by an
  explicit and asserted firewall rule.
- **Review routing.** This change is squarely in the **security-review** and
  **devops-review** categories (database grants, public endpoints, outbound calls,
  CI permissions, headers, infrastructure, container privileges), and the
  **database reviewer** applies to the PostgreSQL configuration, the role split,
  and the whole of section 2. The **legal reviewer** applies narrowly: no
  patient-facing wording changes, but AWS and Let's Encrypt become named parties
  in any subprocessor register, and the privacy policy's claims about retention
  and logging should be re-read against the audit archive's one-year Object Lock.

## Testing: what proves each claim

| Claim | Proof |
|---|---|
| The deployed artifact is the tested digest | `verify-deploy-env.sh` fails on any tag-based reference; the deploy pulls by digest and the running digest is asserted after `compose up` |
| The deployed environment does not use the repository's JWT secret | post-deploy: a token signed with `DEV_JWT_SECRET` gets **401** |
| The deployed environment does not use the dev field key | the container refuses to start (`enforce_deployed_safety`), so a green deploy is the proof |
| RLS binds to the running application | post-deploy one-off container: `current_user` ≠ owner, unscoped `count(*) FROM patients` = 0 |
| The service cannot migrate | the same container asserts no privilege on `alembic_version` |
| The audit trail records the patient, not the edge | post-deploy: a request with a bogus `X-Forwarded-For` produces an `audit_log` row whose `ip_address` is the runner's real address, neither `10.90.*` nor the bogus value |
| Migrations run before the service updates | `deploy.sh` aborts on a non-zero migration exit; exercised once deliberately with a broken migration on a throwaway branch |
| A bad release can be reverted | performed once during setup: deploy, then `deploy.sh --rollback`, and time it |
| **Backups restore** | the week-1 drill (section 2.3), all five checks, timed and written down; repeated quarterly |
| The restored database still isolates patients | the drill's `current_user` and unscoped-count checks |
| Encrypted notes survive a restore | the drill decrypts one |
| The backup is not silently failing | `BackupAgeHours` alarm above 26 hours, and an alarm on any increase in `pg_stat_archiver.failed_count` |
| TLS will not expire unnoticed | `CertificateDaysRemaining` alarm below 21, plus the five-minute HTTPS canary |
| Containers cannot assume the instance role | `podman exec api curl -m 2 http://169.254.169.254/...` times out; the same from `postgres` succeeds |
| The audit archive cannot be deleted by its writer | attempt `DeleteObject` with the writer role and assert AccessDenied |
| `ENVIRONMENT` is what the environment declares | `verify-deploy-env.sh`, in CI against the committed files and on the box before every start |

Existing suites that must stay green unchanged: the full API suite,
`tests/db/test_patient_isolation.py`, `tests/test_architecture.py`, the Angular
unit tests, and the OpenAPI drift check. The only test files this plan expects to
touch are `tests/core/test_config.py` (the renamed guard) and
`tests/synthetic/test_synthetic.py` (the new setting).

## Runbook

**Irreversible or hard to reverse** is marked ⚠. Nothing before step 3 costs
anything.

### Phase A — decide, before creating anything

0. Read this revision. Answer the open questions. **Stop here if you are not
   spending money yet.**
1. **Check Billing → Free tier and Billing → Account plan.** If it is a
   credit-based Free plan, move to a Paid plan **before** any real data exists.
   On this path a suspension puts the only live copy of your record behind an
   instance you cannot start.
2. Enable free-tier usage alerts; create the $40 budget and the cost-anomaly
   monitor **before** the first resource, so the alarms predate the spend.
3. ⚠ **Accept the HIPAA BAA in AWS Artifact**, and read the HIPAA-eligible
   services list alongside it.
4. Enable MFA on the root user, create an IAM Identity Center admin, stop using
   root, set the account alias and billing contacts.

### Phase B — bootstrap

5. `infra/terraform/bootstrap`: state bucket, its KMS key, the GitHub OIDC
   provider and the two roles. Apply locally, then migrate state into the bucket.
   ⚠ `prevent_destroy` on the bucket and key.
6. Set the GitHub repository variables: `AWS_REGION`, `AWS_ACCOUNT_ID`,
   `REGISTRY`, `REGISTRY_NAMESPACE`, `DEPLOY_ROLE_ARN`, `INSTANCE_ID`.

### Phase C — the record's home, before the domain moves

7. `modules/network` and `modules/storage`: VPC, one public subnet per AZ, the
   security group (80 and 443 only), ECR with immutable tags and lifecycle, the
   backup bucket, ⚠ **the audit-archive bucket created with Object Lock enabled**
   (it cannot be added later).
8. `modules/secrets`: the secret shell. Write the real values once with
   `aws secretsmanager put-secret-value`. ⚠ **Write `FIELD_ENCRYPTION_KEY`, the
   pgBackRest passphrase and the KMS key id on paper, offline, now** — before
   anything is encrypted with them.
9. `modules/instance`: ⚠ the KMS key; ⚠ **the data volume, created encrypted, as
   a separate resource with `prevent_destroy`**; the instance; the Elastic IP; the
   instance profile; the DLM snapshot policy; the auto-recovery alarm.
10. First boot: confirm the volume was formatted **once** and mounts by label;
    confirm SSM Session Manager works and that there is no port 22; confirm IMDS
    is reachable from the `postgres` container and not from `api`.
11. Push the first images from `publish.yml` (three of them now, including
    `eoehelp-postgres`). Run `deploy.yml`. Watch every post-deploy gate pass —
    **this is the first moment RLS runs in a deployed application; do not skip
    it.**
12. `pgbackrest stanza-create`, then a first `--type=full` backup, then
    `pgbackrest verify`. Confirm objects appear in S3 and that they are encrypted.

### Phase D — the domain ⚠

13. ⚠ **Export every Squarespace DNS record** into
    `docs/runbooks/dns-before-cutover.md`, with a screenshot. Nothing else in this
    phase is safe until this is done. Pay particular attention to MX and any SPF
    TXT record.
14. Create the Route 53 hosted zone; recreate every exported record in it; add the
    apex and `www` A records to the Elastic IP; add the SES DKIM, MAIL FROM, SPF
    and DMARC records (they take effect at cutover).
15. ⚠ **Switch the nameservers at Squarespace.** `.org` delegation TTLs are
    typically 48 hours, so a mistake takes up to two days to fully undo even after
    you correct it. Do it on a day you can watch it.
16. Verify: `dig +trace eoehelp.org`, `dig NS eoehelp.org @a.gtld-servers.net`,
    `dig MX eoehelp.org`; send a test message to any address on the domain.
17. Let Caddy obtain the certificate (it will, within seconds of DNS resolving).
    Confirm HTTPS, then ⚠ **add the CAA records — `letsencrypt.org`, not
    `amazon.com`.** A CAA record naming only Amazon would block every future
    renewal, silently, until the certificate expires.
18. Verify your own address in SES, request production access, and send yourself a
    magic link end to end.

### Phase E — the data, and proving you can get it back

19. Create your account through the real site. Complete onboarding. Enter a week
    of real history.
20. **Perform the restore drill, section 2.3, all five checks. Record the elapsed
    time in `docs/runbooks/database-restore.md`.** ⚠ Delete the drill instance and
    its volumes when finished.
21. Confirm the weekly `pg_dump` + `pg_dumpall --roles-only` lands, and the daily
    audit-archive export lands; attempt a delete with the writer role and confirm
    AccessDenied.
22. Confirm every alarm by forcing it once: fill a disk, stop a backup timer,
    point the cert check at an expired host.
23. Deliberately roll back one deploy and time it. Deliberately fail one migration
    on a throwaway branch and confirm the running service is untouched.
24. Set the quarterly restore-drill reminder and the month-11 cost-review
    reminder.

### Phase F — tier 1, when the launch gate needs it

25. Read section 9 again before starting; it is a project, not an afternoon.
26. Create the Organization from this account; accept the BAA at the management
    account; invite a new account to be **staging**.
27. Build the ECS/RDS/ALB/CloudFront stack alongside the running instance, seed it,
    and rehearse the database migration at least twice against a restored copy
    before doing it for real.
28. ⚠ Add the Amazon CAA values **before** the first ACM certificate request.
29. ⚠ Flip `ENVIRONMENT` to `production` — only after the legal documents are
    attorney-reviewed.

## Open questions

Decisions 1–4 are made (review log row 2) and are not repeated here. Decisions
5–10 stand, with the two adjustments the EC2 path forces, noted below. These are
the questions the revision newly creates.

1. **Should the build plan's stage-4 local edge become Caddy rather than nginx?**
   It would make the edge one configuration at both tiers instead of two kept
   equivalent by hand, and stage 4 has not landed. **Default: yes, switch it** —
   and if that is too disruptive to an in-flight change, production still uses
   Caddy and the ADR records why the two differ.
2. **`t4g.small` (2 GiB, $12.26) or `t4g.medium` (4 GiB, $24.53)?**
   **Default: `t4g.small`**, with the named upgrade triggers in section 1. The
   upgrade is a stop, a type change and a start, with the data volume attached
   throughout — about five minutes of downtime and no data risk.
3. **A one-year Compute Savings Plan or Reserved Instance for the instance?**
   It would save roughly 30–40% of $12.26, about $4/month. **Default: no** — tier 1
   replaces this instance with Fargate, and a one-year commitment would be
   stranded. This is a small, concrete cost of the rebuild being certain.
4. **PostgreSQL as a container with a derived image, or on the host from `dnf`?**
   **Default: the container**, so local, CI and production run the same PostgreSQL
   build with the same locale — the property the build plan's collation work
   established. The host alternative is simpler for backups and avoids the IMDS
   exception; it is the fallback if the derived image proves awkward.
5. **How much of the restore drill should be automated?** A fully scripted drill
   runs more often; a manual one is read and understood. **Default: scripted
   setup and verification, manual invocation**, quarterly, with the results
   written by hand — because the purpose is partly to keep the operator fluent in
   a procedure they will one day run under stress.
6. **Does the daily audit-archive export start at tier 0, or only the bucket?**
   The bucket must exist now; the exporter is ~20 lines. **Default: both now** —
   it is cheap, and the export is the only copy of the audit trail outside the
   database's blast radius.

**Two adjustments to decisions 5–10 that the EC2 path forces**, offered for
confirmation rather than re-decision:

- **Decision 5 (keep ElastiCache)** becomes **keep Valkey, as a container on the
  box**. The substance holds — `REDIS_URL` is set, so `enforce_deployed_safety` can
  require it and the rate limiter behaves as it will in production — and the cost
  drops from $9.34/month to zero. ElastiCache returns at tier 1.
- **Decision 10 (alarms by email, no SMS)** holds, but the alarm *set* is larger
  than it would have been: on this path no managed service raises alarms on your
  behalf, so the twelve alarms in section 10 are all yours to configure and all
  yours to notice. The backup-age and certificate-expiry alarms are the two whose
  silence is most expensive.

## Review log

| Round | Reviewer | Verdict | What changed |
|---|---|---|---|
| 1 | architect (self-check) | Draft ready for the user | Checked against every item in the architect's standard. **Clinical soundness:** no instrument, threshold or wording changes; the four properties with clinical consequence (audit truthfulness, magic-link deliverability as authentication uptime, restore-with-decryption, RLS binding) each designed for with a named proof. **Patient isolation:** no new table, route or query; the `app_runtime` path was driven end to end rather than reasoned about, and the deployed equivalent of the isolation test is a post-deploy gate. **Privacy and PHI:** PHI locations enumerated; no new third party receives patient data; Cloudflare and error tracking kept out with reasons. **Architecture:** no package moves; the application changes are one file each. **Data model:** none added; the constraints that matter are creation-time infrastructure settings, called out as rebuilds. **API contract:** unchanged. **Frontend:** unchanged; the SPA ships as the promoted container image, which keeps ADR 0006's guarantee true for the web as well as the API. **Testing:** thirteen claims each with a named proof, three failure paths exercised deliberately. **Scope:** SOC 2, pen test, entity, insurance, error tracking, multi-region and CSP excluded by name. **Decisions:** ten open questions with defaults. **Verified rather than inferred:** the `app_runtime` end-to-end run, the RLS catalogue from `pg_class`/`pg_policies`, the `alembic_version` grant gap, `FORWARDED_ALLOW_IPS` measured both ways, uvicorn's right-to-left XFF walk read from source, and every major price queried from the AWS price list. **Not resolved:** which free-tier model the account is on, ElastiCache free-tier Valkey eligibility, whether ALB public IPv4 is billed, and the current HIPAA-eligible services list. Also reported rather than worked around: seven defects in the build plan's deploy contract. |
| 2 | user | Decisions on the open questions | 2026-09-23. **1. Yes to tier 0**, at one account, after checking the billing plan. **2. One EC2 instance (~$18/month), not Fargate** — against this plan's recommendation, on cost. The consequences the plan names are accepted: self-operated Postgres backups with no PITR or snapshot restore, one volume in one AZ, TLS without ACM, and a tier 1 that is a rebuild of the deploy mechanism rather than a series of resizes. Because of decision 4, the database this instance carries is the one holding real health data permanently, so backup and restore become the centre of the design rather than a line item. **3. `us-east-2` (Ohio).** **4. Yes — tier 0's account becomes production at tier 1**, and the new account becomes staging, so real data never moves between accounts. **5–10: the defaults**, unless the EC2 revision makes one of them incoherent: ElastiCache kept, Object Lock GOVERNANCE at one year with bypass denied, HSTS without `preload` at `max-age=86400`, SES SMTP now with the v2 API before tier 1, tier-1 staging stopped when not building, and alarms by email with no SMS. |
| 3 | architect (revision) | Revised for the EC2 path; ready for the user to read | 2026-09-23. **Rewritten around decisions 2 and 4.** Tier 0 is now one `t4g.small` on Amazon Linux 2023 running the promoted digests under podman with the compose provider, a Caddy edge with Let's Encrypt, and PostgreSQL and Valkey as containers. **Backup and restore moved to section 2, ahead of everything else**, with a chosen mechanism and its reasoning (pgBackRest with continuous WAL archiving, over `pg_dump` on a timer, because PITR is the only safety net on this path), a full encryption story across four layers and three unrecoverable secrets, **RPO 60 seconds derived from `archive_timeout`** rather than asserted, an RTO the first drill is required to *set* rather than claim, and a five-check restore drill as numbered runbook steps for setup and quarterly repetition. The drill's fourth check — `current_user` and an unscoped `count(*)` — exists because a restore that loses the `app_runtime` role invites connecting as the owner, which silently disables every ADR 0002 policy; and the `pg_dumpall --roles-only` companion exists for the same reason. **The volume lifecycle is stated as the trap it is**: the data volume is a separate resource with `prevent_destroy` and `skip_destroy`, instance replacement reattaches, `terraform destroy` refuses to run at all, and the `mkfs`-on-every-boot footgun is named with the guard. **TLS without ACM** is designed with Caddy rather than nginx-plus-certbot specifically for the failure mode (a certbot renewal that succeeds while the reload never happens is silent for up to 30 days), with the certificate directory pinned to the persistent volume against Let's Encrypt's five-duplicates-per-week limit, port 80 permanently open for HTTP-01, three independent expiry detections, and **HSTS at `max-age=86400` with no `preload` restated as a hazard control rather than caution**. A new and easily-missed consequence is called out: **the CAA record must name `letsencrypt.org`, not `amazon.com`** — the value the Fargate draft specified would have blocked every renewal — and the Amazon values must be added back before tier 1's first ACM request. **`FORWARDED_ALLOW_IPS` is named for this shape**: `10.90.0.0/24`, a *pinned* compose network rather than a podman-allocated one, with Caddy configured to replace rather than append the header and no host ports on the application containers, which closes spoofing twice over; the measurement that established the behaviour was taken through exactly this kind of bridge network. **The deploy mechanism** is GitHub OIDC → SSM Run Command → `deploy.sh`, with digests also in Parameter Store so a reboot returns to the right version, migrations as a one-shot container under the owner that aborts the deploy on failure, the same four post-deploy gates, and a rollback from locally-cached images that is faster than the ECS equivalent — with the expand/contract migration discipline restated as *more* load-bearing, not less, because PITR is now the only fallback. **The three secret-safety checks are kept intact**, re-pointed at `verify-deploy-env.sh` on the box and in CI, and extended with four assertions this shape needs (no host ports, no owner credentials in the `api` service, arm64, exact network CIDR). **Tier 1 is sized as the deferred bill**: unchanged at $256/month to run, but two to three focused weeks to build plus a rehearsed database migration against a live record, versus two to three days of resizes from the rejected path — with a portability discipline written as a design obligation so that estimate stays bounded. **Costs re-derived from the price list**, including a correction the user should see: the "~$18/month" the decision was made on was bare compute; the complete design is **$22.87/month**, so the saving against Fargate is $39/month rather than $44 — about $193 in year one and $470 in year two. This path barely touches the free tier, so month 1 and month 13 differ by only $2.45 and there is **no month-12 cliff at all**, which is a real advantage of the decision. **New in this revision:** a third published image (`infra/postgres/Dockerfile` = the pinned upstream digest plus `pgbackrest`, because `archive_command` runs inside the database's process tree), an IMDS hop-limit design with an nftables exception so only the database container can reach the instance role, an Elastic IP so replacement does not move DNS, EC2 auto-recovery, and **Let's Encrypt named as a new third party for the legal reviewer** — it receives no patient data but belongs in a vendor register. **Kept from round 1 unchanged, because none of it depends on compute:** every verified measurement, the RLS catalogue, the `alembic_version` grant gap, the XFF findings, the four `ENVIRONMENT` collisions, and the seven deploy-contract defects (of which #6, ECS ignoring a Dockerfile `HEALTHCHECK`, is restated for compose — where the image's `HEALTHCHECK` *is* used and `compose up --wait` depends on it, so it becomes load-bearing here and re-emerges as a defect at tier 1). **Decisions 5 and 10 adjusted rather than re-decided**, per the coordinator's instruction to say if the path made one incoherent: ElastiCache becomes a Valkey container (same substance, $9.34/month cheaper), and the alarm set grows because nothing managed raises alarms on your behalf. **Still unresolved:** the account's free-tier model (runbook step 1), whether `t4g.small` carries any allowance, whether CloudWatch's 10-metric/10-alarm always-free tier still holds, the HIPAA-eligible services list, and whether 2 GiB is comfortable in practice — each flagged with the place to check and a priced fallback. |
| 4 | user | The six new questions, all defaults | 2026-09-23. **Caddy at both tiers**, so the build plan's stage-4 local edge changes from nginx to Caddy and there is one edge configuration rather than two kept equivalent by hand — recorded against that plan too. `t4g.small`, with the named triggers deciding any move to `t4g.medium` rather than a judgement made under pressure. **No Savings Plan**, accepting that this is a small concrete cost of the tier-1 rebuild being certain. Postgres as a container from the pinned digest plus pgBackRest. Partial drill automation. The audit exporter starts now, because the bucket's Object Lock is creation-time only. Also noted from the revision: the figure the compute decision was made on (~$18) was bare compute; the complete design is **$22.87/month**, so the saving against Fargate is **$39/month rather than $44** — which does not change the decision, and this path's near-total independence from the free tier means there is no month-12 cliff. |
