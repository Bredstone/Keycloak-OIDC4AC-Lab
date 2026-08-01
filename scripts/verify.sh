#!/usr/bin/env bash
#
# Copyright 2026 Red Hat, Inc. and/or its affiliates
# and other contributors as indicated by the @author tags.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

ISSUER="${OIDC4AC_LAB_ISSUER:-http://keycloak.localhost:8080/realms/oidc4ac}"
DISCOVERY=$(curl --fail --silent --show-error "$ISSUER/.well-known/openid-configuration")

jq --exit-status '
  .amr_details_request_supported == true and
  (.claims_supported | index("amr_details")) and
  (.amr_identifiers_supported | sort == ["email", "otp", "pop", "pwd"]) and
  (.email_metadata_supported | sort == ["assurance_level", "channel", "trust_framework"]) and
  (.email_verification_method_values_supported == ["code"]) and
  (.otp_properties_supported | sort == ["otp_algorithm", "otp_delivery_method", "otp_format", "otp_length", "otp_time_to_live"]) and
  (.otp_algorithm_values_supported | sort == ["HOTP", "TOTP"]) and
  (.otp_delivery_method_values_supported == ["app"]) and
  (.otp_format_values_supported == ["numeric"]) and
  (.pwd_properties_supported | index("pwd_derivation_algorithm") and index("pwd_iterations")) and
  (has("pwd_derivation_algorithm_values_supported") | not)
' <<<"$DISCOVERY" >/dev/null

CLIENT_URL="${OIDC4AC_LAB_CLIENT_URL:-http://client.localhost:5000}"
curl --fail --silent --show-error "$CLIENT_URL/healthz" | jq --exit-status '.status == "ok"' >/dev/null
curl --fail --silent --show-error "$CLIENT_URL/otp-code" \
    | jq --exit-status '(.code | test("^[0-9]{6}$")) and (.remaining >= 1 and .remaining <= 30)' >/dev/null
curl --fail --silent --show-error "$CLIENT_URL/discovery" \
    | jq --exit-status '.methods.email.metadata.assurance_level and .methods.otp.metadata.location and .methods.pwd.properties.pwd_iterations' >/dev/null
echo "OIDC4AC discovery and test-client readiness checks passed."
