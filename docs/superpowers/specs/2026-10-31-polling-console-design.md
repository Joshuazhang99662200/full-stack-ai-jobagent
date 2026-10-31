# Polling console design

Approved direction: the user accepted a lightweight React console, reusable public components and shared host queries, and requested implementation followed by Hallmark audit.

## Responsibilities

Existing Python schemas remain the only domain type authority. The console projection reads complete candidate-scoped pipeline job/meta/history and portable HarnessRun state without mutation. Additional append-only host activity observations identify actual execution stages; they never authorize or prove delivery or approval. CLI, loopback HTTP and MCP read the same projection.

React renders two views: current/historical execution lanes and recorded job business states. Run phases, activity observations and nine-state pipeline facts remain separate. Full field disclosure includes exact JD/draft content as escaped text and provenance/artifact references. Missing observations render honestly, stale activity loses its running indication, and unvisited states are not inferred from enum order.

## Interface and privacy

The public component consumes a snapshot prop; a standalone app loads same-origin read endpoints. Synthetic demonstration is explicit, never an error fallback. Query definitions expose JSON Schema with original domain models. No credentials or raw arbitrary file download are exposed. Data endpoints are GET-only, bound to loopback with Host and Origin validation. Static serving is limited to the explicit built app directory. No browser/platform API is called by the console.

Activity writes are a separate explicit CLI action, bound to an existing owned run with aware chronology, identity checks, immutable event IDs and concurrent-write exclusion. Querying never migrates databases, acknowledges events or changes leases. Completed/failed runs cannot be reactivated through observations.

## Known source limitations

Old worker completion events cannot reconstruct stage starts. Old global patrol and outreach approval records lack reliable candidate/run ownership in all cases. Unsupported associations are source diagnostics, not silently empty success. Backend observation recording and host adoption must be distinguished from actual platform acceptance.

## Acceptance

Candidate separation, byte-preserving read-only behavior, full exact text and faithful history are tested. HTTP method/origin/host/traversal boundaries are tested. React interaction tests cover run/job selection, nine states, exact field access, source failure and empty/loading states, and narrow/wide layouts. Production and library builds must pass. Four repository gates remain mandatory. Hallmark app-scope static/render sweep and independent finish review precede delivery.
