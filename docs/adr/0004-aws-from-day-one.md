# ADR 0004 — AWS from day one, with the domain kept at Squarespace

**Status:** Accepted · 2026-09-15

## Context

The usual advice for an unvalidated product is to start on a managed platform and
migrate later. That advice assumes the migration trigger is scale. Here it is
compliance, and the economics are inverted.

## Decision

**Run on AWS from the first deployment, and accept the HIPAA BAA in AWS Artifact
before any production infrastructure exists.**

AWS signs its BAA at **no charge**, self-serve, covering RDS, Fargate, S3,
CloudFront, Route 53, SES, and KMS. The managed alternatives charge for the same
capability — Fly.io $99/month as an add-on, Render only on its $499/month tier —
so the PaaS saving holds only until a BAA is needed, which is precisely when the
product is succeeding. Signing it costs nothing, obligates nothing, changes no
relationship (see ADR 0001), and removes the migration moment entirely.

**Architecture, deliberately boring** — operable by one person:

```
Route 53 → CloudFront → S3 (Angular build)
Route 53 → ALB → ECS Fargate (FastAPI, private subnets)
                  ├── RDS PostgreSQL (Multi-AZ, KMS-encrypted)
                  ├── ElastiCache Redis
                  └── S3 (report PDFs; separate bucket with Object Lock for audit)
AWS WAF · Secrets Manager · CloudWatch · CloudTrail · SES
```

All in Terraform, separate AWS accounts for staging and production.

**No Cloudflare proxy in front.** It is the reflexive choice for WAF and DDoS,
but proxying means Cloudflare terminates TLS and handles PHI, making it a
subprocessor requiring its own BAA — Enterprise tier only. CloudFront plus AWS
WAF is already covered.

**SES for magic-link email**, for the same reason: a login link tied to a known
patient address should not go to an uncovered vendor.

**DNS:** Squarespace remains the registrar; only the nameservers move to Route 53.
Export every existing DNS record first — Squarespace's nameserver connect strips
existing CNAME and some A records, which breaks any email on the domain at
cutover. Route 53 ALIAS records resolve the apex-CNAME problem natively.

## Consequences

- One to two extra weeks of setup in M0, and a real ops learning curve.
- Roughly $250–300/month across staging and production, versus ~$40 for a
  single-instance PaaS. Multi-AZ and a real staging environment are most of that
  difference and are not optional for health data.
- No migration is ever required for compliance reasons.
- Eligible is not compliant: the BAA is the beginning of the work. Encryption
  with customer-managed keys, private subnets, no public buckets, and CloudTrail
  are all still on us.

## Alternatives rejected

**Render or Fly.io with a portability discipline.** Genuinely faster to ship, and
the right call if the priority were validating the product before the compliance
question arrives. Viable only while the app stays portable — plain containers,
vanilla Postgres, S3-compatible storage, no proprietary platform primitives —
and one convenient platform service turns the later migration into a project.
