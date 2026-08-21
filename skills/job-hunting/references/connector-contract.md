# Connector contract

Use `JobDiscoverySource` for sourcing and intelligence. It exposes only `search`,
`fetch_job`, and `get_recruiter`, returning `SourceJobRecord` and `RecruiterInfo` contracts.
The bundled `MockJobSource` reads synthetic fixture JSON and intentionally has no application
or platform-control methods.

Keep delivery capabilities in a separate connector boundary. A later delivery-capable
`JobSource` may add package inspection and submission, with independent authorization and
approval gates. Job Intelligence must not import or call that delivery surface.

Connector adapters translate platform state into domain contracts and never leak DOM or
browser types into core modules. Preserve source IDs, canonical URLs, observation timestamps,
and the full JD so deduplication can retain an auditable provenance set.

For future platform connectors, return `USER_INTERVENTION_REQUIRED` for login, CAPTCHA,
verification, risk control, and platform changes. Do not bypass, evade, or automatically retry
those states. Real browser delivery remains sequential.
