"""Establishes the worst-case SSO session for the warm-SSO benchmark.

Run this file inside the laboratory's browser test image (see
run-benchmark.sh). It completes, in the browser, the authorization that
requests every advertised method with every advertised metadata member and
property, so that the SSO session contains pwd, otp, pop, and email executions.
It then writes the request and the Keycloak cookies of that session, which the
HTTP benchmark runner loads to measure warm-SSO cycles of the same request.
Factor collection therefore happens once, outside the measured cycles.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

import run
from browser_flow import authorize, open_browser, worst_case

OUTPUT = Path(os.environ.get("OIDC4AC_SEED_OUTPUT", "/tmp/oidc4ac-seed-session.json"))


def main() -> int:
    with sync_playwright() as playwright:
        browser, page, discovery = open_browser(playwright)
        request_claims = worst_case(discovery)
        authorize(page, request_claims)
        executed = set(run.detail_map(run.json_section(page, "Verified ID Token")))
        expected = set(discovery["amr_identifiers_supported"])
        run.check(executed == expected, f"Executions were {sorted(executed)}, expected {sorted(expected)}.")
        # Cookies ignore ports, so the test client's cookie shares the
        # localhost domain; Keycloak scopes its cookies to the realm path.
        cookies = [cookie for cookie in page.context.cookies() if cookie["path"].startswith("/realms/")]
        browser.close()
    OUTPUT.write_text(json.dumps({"request_claims": request_claims, "cookies": cookies}, indent=1) + "\n",
                      encoding="utf-8")
    print(f"seeded {sorted(executed)} with {len(cookies)} Keycloak cookies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
