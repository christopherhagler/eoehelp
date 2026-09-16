"""Scope-bound data access.

Layer one of the three-layer patient isolation described in
docs/adr/0002-patient-data-isolation.md. Repositories are constructed with a
patient id taken from the verified access token, and every statement they issue
carries it. Routers never build a query and never see a session.

The point is structural rather than defensive: because a repository cannot be
constructed without a scope, there is no code path in which a filter can be
forgotten. That is what removes the IDOR bug class instead of guarding against it.
"""
