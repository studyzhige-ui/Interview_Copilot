# Refresh current state at mutation and erasure boundaries

A row lock orders concurrent writers but does not by itself replace an object
already loaded in a SQLAlchemy Session identity map. The affected mutation
queries now request `populate_existing()` along with their existing locks;
workspace invalidation refreshes the workspace after the existing user lock.
The transaction boundaries, lock order and authorization filters are unchanged.

The batch covers global/conversation/debrief guidance, Memory controls and
lifecycle/promotion, Artifact archival/edit boundaries, Profile candidate
resolution, Opportunity/NextAction transitions, Offer confirmation and pending
Automation triggers. Scalar identity-only queries are intentionally unchanged.
Memory source suppression refreshes evidence and extraction observations before
clearing dependent text, indexes and leases.

Behavioral regressions deliberately retain a cached object while a Core update
changes the underlying stored values. They verify that newer guidance cannot be
cleared, disabled contribution cannot be re-enabled with an old version, deleted
Memory cannot be revived, a newly acquired workspace lease and private index are
actually invalidated, archived artifacts/closed opportunities reject new work,
and Offer terms require confirmation against their current token. The relevant
existing domain regressions remain in place. SQLite reproduces identity-map
semantics, not PostgreSQL locking; PostgreSQL concurrency tests remain required.

SQLAlchemy 2.0's Query documentation explicitly recommends populate_existing
with with_for_update when an identity may already be loaded:
https://docs.sqlalchemy.org/en/20/orm/queryguide/query.html#sqlalchemy.orm.Query.with_for_update
