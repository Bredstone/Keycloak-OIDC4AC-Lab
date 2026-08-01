/*
 * Copyright 2026 Red Hat, Inc. and/or its affiliates
 * and other contributors as indicated by the @author tags.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */
package org.keycloak.testsuite.oidc;

import java.io.IOException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClientBuilder;

import org.keycloak.common.Profile;
import org.keycloak.models.AuthenticationExecutionModel;
import org.keycloak.protocol.oidc.OIDCLoginProtocol;
import org.keycloak.protocol.oidc.representations.OIDCConfigurationRepresentation;
import org.keycloak.representations.IDToken;
import org.keycloak.representations.UserInfo;
import org.keycloak.representations.idm.AuthenticationExecutionInfoRepresentation;
import org.keycloak.representations.idm.AuthenticationFlowRepresentation;
import org.keycloak.representations.idm.AuthenticatorConfigRepresentation;
import org.keycloak.representations.idm.RealmRepresentation;
import org.keycloak.testsuite.authentication.OIDC4ACEmailAuthenticatorFactory;
import org.keycloak.testsuite.arquillian.annotation.EnableFeature;
import org.keycloak.testsuite.pages.AppPage;
import org.keycloak.testsuite.util.oauth.AccessTokenResponse;
import org.keycloak.testsuite.util.oauth.AuthorizationEndpointResponse;
import org.keycloak.testsuite.broker.util.SimpleHttpDefault;
import org.keycloak.util.JsonSerialization;

import org.junit.Before;
import org.junit.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** End-to-end proof that a separately packaged authenticator and details SPI can participate in OIDC4AC. */
@EnableFeature(value = Profile.Feature.OIDC4AC, skipRestart = true)
public class OIDC4ACCustomProviderIntegrationTest extends AbstractOIDCScopeTest {

    private static final String BROWSER_FLOW = "oidc4ac custom-provider browser";
    private static final String FACTOR_FLOW = "oidc4ac custom-provider factors";
    // Flow aliases use Keycloak's reserved-character validation; keep the
    // protocol identifier (email) in the authenticator/provider, not in the
    // alias itself.
    private static final String EMAIL_FLOW = "oidc4ac-email";

    @Override
    public void configureTestRealm(RealmRepresentation testRealm) {
        // The standard test realm provides test-app and test-user.
    }

    @Before
    public void configureCustomProviderFlow() {
        assertTrue(managedRealm.admin().flows().getAuthenticatorProviders().stream()
                .anyMatch(provider -> OIDC4ACEmailAuthenticatorFactory.PROVIDER_ID.equals(provider.get("id"))));
        if (managedRealm.admin().flows().getFlows().stream().anyMatch(flow -> BROWSER_FLOW.equals(flow.getAlias()))) {
            return;
        }

        createFlow(BROWSER_FLOW, true);

        addExecution(BROWSER_FLOW, "auth-username-password-form", AuthenticationExecutionModel.Requirement.REQUIRED);
        AuthenticationExecutionInfoRepresentation planner = addExecution(
                BROWSER_FLOW, "oidc4ac-factor-planner", AuthenticationExecutionModel.Requirement.REQUIRED);

        managedRealm.admin().flows().addExecutionFlow(BROWSER_FLOW,
                Map.of("alias", FACTOR_FLOW, "provider", "basic-flow", "type", "basic-flow"));
        AuthenticationExecutionInfoRepresentation factorSubflow = findSubflow(BROWSER_FLOW, FACTOR_FLOW);
        factorSubflow.setRequirement(AuthenticationExecutionModel.Requirement.REQUIRED.name());
        managedRealm.admin().flows().updateExecutions(BROWSER_FLOW, factorSubflow);

        managedRealm.admin().flows().addExecutionFlow(FACTOR_FLOW,
                Map.of("alias", EMAIL_FLOW, "provider", "basic-flow", "type", "basic-flow"));
        AuthenticationExecutionInfoRepresentation emailSubflow = findSubflow(FACTOR_FLOW, EMAIL_FLOW);
        emailSubflow.setRequirement(AuthenticationExecutionModel.Requirement.ALTERNATIVE.name());
        managedRealm.admin().flows().updateExecutions(FACTOR_FLOW, emailSubflow);

        addExecution(EMAIL_FLOW, "oidc4ac-test-email", AuthenticationExecutionModel.Requirement.REQUIRED);

        AuthenticatorConfigRepresentation config = new AuthenticatorConfigRepresentation();
        config.setAlias("oidc4ac custom-provider planner config");
        config.setConfig(Map.of("factor_flow_alias", FACTOR_FLOW));
        managedRealm.admin().flows().newExecutionConfig(planner.getId(), config);

        RealmRepresentation realm = managedRealm.admin().toRepresentation();
        realm.setBrowserFlow(BROWSER_FLOW);
        managedRealm.admin().update(realm);
    }

    @Test
    public void packagedAuthenticatorAndDetailsProviderAreProjected() throws IOException {
        try (CloseableHttpClient client = HttpClientBuilder.create().build()) {
            OIDCConfigurationRepresentation discovery = SimpleHttpDefault
                    .doGet(getAuthServerRoot().toString() + "realms/test/.well-known/openid-configuration", client)
                    .asJson(OIDCConfigurationRepresentation.class);
            assertTrue(discovery.getClaimsSupported().contains("amr_details"));
            assertTrue(((List<?>) discovery.getOtherClaims().get("amr_identifiers_supported")).contains("email"));
            assertEquals(List.of("assurance_level", "channel", "trust_framework"),
                    discovery.getOtherClaims().get("email_metadata_supported"));
            assertEquals(List.of("code"), discovery.getOtherClaims().get("email_verification_method_values_supported"));
        }

        oauth.client("test-app", "password");
        oauth.scope("openid");
        String claims = JsonSerialization.writeValueAsString(Map.of(
                "id_token", Map.of("amr_details", Map.of("essential", true,
                        "amr_identifier", Map.of("value", "email"),
                        "amr_metadata", Map.of("time", Map.of("essential", true),
                                "trust_framework", Map.of("essential", true),
                                "assurance_level", Map.of("essential", true)),
                        "amr_properties", Map.of("email_verification_method", Map.of("essential", true)))),
                "userinfo", Map.of("amr_details", Map.of("essential", true,
                        "amr_identifier", Map.of("value", "email"),
                        "amr_metadata", Map.of("time", Map.of("essential", true))))));

        oauth.loginForm().param(OIDCLoginProtocol.CLAIMS_PARAM, URLEncoder.encode(claims, StandardCharsets.UTF_8)).open();
        loginPage.assertCurrent();
        loginPage.login("test-user@localhost", "password");
        assertEquals(AppPage.RequestType.AUTH_RESPONSE, appPage.getRequestType());

        AuthorizationEndpointResponse authorizationResponse = oauth.parseLoginResponse();
        assertTrue(authorizationResponse.isSuccess(),
                () -> authorizationResponse.getError() + ": " + authorizationResponse.getErrorDescription());
        AccessTokenResponse response = oauth.client("test-app", "password").doAccessTokenRequest(authorizationResponse.getCode());
        assertEquals(200, response.getStatusCode());

        IDToken idToken = oauth.verifyIDToken(response.getIdToken());
        List<?> details = (List<?>) idToken.getOtherClaims().get("amr_details");
        assertNotNull(details);
        assertTrue(details.stream().anyMatch(detail -> detail.toString().contains("email_verification_method=code")));
        assertTrue(details.stream().anyMatch(detail -> detail.toString().contains("amr_identifier=email")));
        assertTrue(details.stream().anyMatch(detail -> detail.toString().contains("amr_identifier=pwd")));
        assertTrue(details.stream().anyMatch(detail -> detail.toString().contains("trust_framework=urn:example:oidc4ac:email")));
        assertTrue(details.stream().anyMatch(detail -> detail.toString().contains("assurance_level=aal2")));

        UserInfo userInfo = oauth.doUserInfoRequest(response.getAccessToken()).getUserInfo();
        Object userInfoDetails = userInfo.getOtherClaims().get("amr_details");
        assertNotNull(userInfoDetails);
        assertTrue(userInfoDetails.toString().contains("amr_identifier=email"));
        assertTrue(userInfoDetails.toString().contains("amr_identifier=pwd"));
        assertTrue(userInfoDetails.toString().contains("amr_metadata"));
        assertTrue(userInfoDetails.toString().contains("time="));
        assertFalse(userInfoDetails.toString().contains("trust_framework"));
        assertFalse(userInfoDetails.toString().contains("assurance_level"));
        assertTrue(oauth.verifyToken(response.getAccessToken()).getOtherClaims().get("amr_details") == null);
    }

    private void createFlow(String alias, boolean topLevel) {
        AuthenticationFlowRepresentation flow = new AuthenticationFlowRepresentation();
        flow.setAlias(alias);
        flow.setDescription(alias);
        flow.setProviderId("basic-flow");
        flow.setTopLevel(topLevel);
        flow.setBuiltIn(false);
        managedRealm.admin().flows().createFlow(flow).close();
    }

    private AuthenticationExecutionInfoRepresentation addExecution(String flowAlias, String provider,
            AuthenticationExecutionModel.Requirement requirement) {
        managedRealm.admin().flows().addExecution(flowAlias, Map.of("provider", provider));
        AuthenticationExecutionInfoRepresentation execution = managedRealm.admin().flows().getExecutions(flowAlias).stream()
                .filter(candidate -> provider.equals(candidate.getProviderId())).findFirst().orElseThrow();
        execution.setRequirement(requirement.name());
        managedRealm.admin().flows().updateExecutions(flowAlias, execution);
        return execution;
    }

    private AuthenticationExecutionInfoRepresentation findSubflow(String flowAlias, String displayName) {
        return managedRealm.admin().flows().getExecutions(flowAlias).stream()
                .filter(candidate -> candidate.getFlowId() != null && displayName.equals(candidate.getDisplayName()))
                .findFirst().orElseThrow();
    }
}
