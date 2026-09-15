# ADR 0003 — Magic-link authentication; tokens in memory and httpOnly cookies

**Status:** Accepted · 2026-09-15

## Context

Authentication is the highest-value target in a health application. The user
population will reuse passwords, and a credential-stuffing compromise here
discloses a diagnosis, not just an account.

## Decision

**Magic link is the primary and default path.** Requesting a link both registers
and signs in; the first click also verifies the address, since clicking is exactly
what proves inbox possession. An optional argon2id password exists for users on
shared family email, but it is not the primary call to action.

This deletes three vulnerability classes rather than defending them: there is no
password hash to crack, no credential reuse to exploit, and no reset flow to
secure — historically the weakest part of any auth system.

**Token handling:**

- **Access token** — JWT, 15 minutes, held only in an Angular signal in memory.
- **Refresh token** — opaque random value, stored hashed, in an
  `httpOnly; Secure; SameSite=Strict` cookie scoped to the auth routes.

Opaque rather than a second JWT so it can be revoked server-side without a
blocklist. In memory rather than `localStorage` because a persisted token turns
any XSS into full account takeover, while an httpOnly cookie is unreadable to
injected script. `SameSite=Strict` costs nothing here — single first-party
origin — and removes the CSRF exposure the cookie introduces.

**Rotation with reuse detection.** Redeeming a refresh token rotates it. A
rotated token presented again means the cookie leaked, so the entire token
*family* is revoked — including the currently valid one. The legitimate user
re-authenticates; the attacker's copy is dead.

That revocation is committed **out of band**, in its own transaction. The request
raises immediately afterward, and the request transaction's rollback would
otherwise discard the revocation and its audit row — leaving the stolen family
live. This was a real bug caught in testing, and the reason
`_revoke_family_out_of_band` exists rather than the obvious inline version.

**No account enumeration.** The magic-link endpoint returns an identical 202 and
body whether or not the address has an account. On this product, distinguishing
them would disclose who has an EoE diagnosis.

## Consequences

- Email deliverability *is* uptime. A link in a spam folder locks a user out
  completely, so SPF/DKIM/DMARC, domain warming, and bounce alarms are launch
  requirements, and delivery must be verified against real providers including a
  hospital mail system.
- Sign-in requires an inbox round trip, which is slower than a password.
- Passkeys are the natural next step; magic link already captures most of the
  breach-surface reduction, so they are an upgrade rather than a prerequisite.

## Alternatives rejected

**An external identity provider.** Routing patient email ↔ health-data linkage
through a third party adds a vendor to the compliance surface for convenience
not needed at this scale.

**Passwords as primary.** Every argument above, inverted.
