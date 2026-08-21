# Connector contract

Implement the `JobSource` port: independent `search`, `fetch_job`, `get_recruiter`, `preview_application`, and `submit_application` methods. Connectors translate platform state into domain contracts and never leak DOM or browser types into core modules.

Return `USER_INTERVENTION_REQUIRED` for login, CAPTCHA, verification, risk control, and platform changes. Do not bypass, evade, or automatically retry those states. Real browser delivery remains sequential.
