# Architecture

`feishu-task-cli` is an Agent-native boundary around Feishu Task mutations. Its core pipeline is:

```text
intent → Plan → Review + Policy → guarded executor → Feishu write → readback → Receipt → Markdown
```

A Plan is not an executed Task. Planning resolves the real authenticated context and, for an
existing Task, captures the observed state and precondition fingerprint. Execution revalidates
artifact hashes, expiry, review facts, policy, actual AuthContext, and the latest Task state before
claiming and consuming a Plan.

## Layers and ownership

- `artifacts`: strict versioned models, canonical serialization, integrity hashes, and schemas.
- `application`: planning, declared Agent review, policy validation, execution, reconciliation.
- `auth`: explicit configuration, user OAuth, keyring storage, and AuthContext fingerprints.
- `feishu`: the restricted HTTP client and Task API adapter.
- `journal`: atomic single-consumption records and an OS lock for one local host.
- `presentation`: stable next-action mapping and sanitized Markdown for users.
- `cli`: non-interactive Agent I/O, typed exit codes, and safe atomic output files.

The JSON artifacts are the machine interface. Diagnostic text is sent separately and is not an
API. Task content and remote error text are untrusted data; rendering escapes Markdown/HTML,
removes unsafe controls, limits length, and prevents business text from becoming instructions.

## Trust boundaries

The journal guarantees replay exclusion only on a single host. It is not a distributed lock and
does not promise remote exactly-once execution. Once a mutating request may have reached Feishu,
the CLI never retries it blindly. An ambiguous result becomes `unknown`; recovery is read-only
investigation and the same Plan remains consumed.

Reviewer IDs and executor IDs are declared identity metadata. Equality produces the explicit
`declared_self_reviewed` relationship. Different values produce `declared_independently_reviewed`,
but the CLI does not cryptographically authenticate Agent identity. A stricter Policy can require
different declared IDs and action-specific checked facts.

The authentication boundary accepts only the official Feishu API origin. Secrets come from
explicit environment variables, an explicit mode-`0600` config, or the OS keyring. There are no
default profiles and no implicit account, tenant, Tasklist, assignee, or Task selection.

Interactive OAuth uses one pre-registered canonical loopback URI. The stable default is
`http://127.0.0.1:8765/callback`; an explicit `FEISHU_OAUTH_REDIRECT_URI` may select another
non-zero port or the exact IPv6 loopback form. Validation and listener binding happen before the
browser or OAuth network exchange, and the authorization and exchange requests use the identical
configured string.

## Verification boundary

`verified` requires a successful mutation followed by a readback whose normalized required fields
match the Plan. `partial` preserves mismatches and omissions. `unknown` preserves ambiguity.
Receipts include safe fingerprints and metadata, not credentials. Public tests use mocked,
synthetic responses and provide no live-tenant validation.
