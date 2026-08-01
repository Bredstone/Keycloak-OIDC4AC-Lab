/*
 * Copyright 2026 Red Hat, Inc. and/or its affiliates
 * and other contributors as indicated by the @author tags.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */
package org.keycloak.testsuite.authentication;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

import org.keycloak.Config;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.protocol.oidc4ac.spi.AuthenticationMethodCapability;
import org.keycloak.protocol.oidc4ac.spi.AuthenticationMethodDetails;
import org.keycloak.protocol.oidc4ac.spi.AuthenticationMethodDetailsContext;
import org.keycloak.protocol.oidc4ac.spi.AuthenticationMethodDetailsProvider;
import org.keycloak.protocol.oidc4ac.spi.AuthenticationMethodDetailsProviderFactory;

/** External-provider example proving custom identifiers and properties flow into tokens. */
public final class OIDC4ACEmailAuthenticationMethodDetailsProviderFactory
        implements AuthenticationMethodDetailsProviderFactory {

    public static final String PROVIDER_ID = "oidc4ac-test-email-details";

    @Override
    public AuthenticationMethodDetailsProvider create(KeycloakSession session) {
        return new Provider();
    }

    @Override
    public String getId() {
        return PROVIDER_ID;
    }

    @Override
    public void init(Config.Scope config) {
    }

    @Override
    public void postInit(KeycloakSessionFactory factory) {
    }

    @Override
    public void close() {
    }

    private static final class Provider implements AuthenticationMethodDetailsProvider {

        @Override
        public List<AuthenticationMethodCapability> getCapabilities() {
            return List.of(new AuthenticationMethodCapability("email", Set.of("email_verification_method"),
                    Set.of("channel", "trust_framework", "assurance_level"),
                    Map.of("email_verification_method", Set.of("code"))));
        }

        @Override
        public boolean supports(AuthenticationMethodDetailsContext context) {
            return OIDC4ACEmailAuthenticatorFactory.PROVIDER_ID.equals(context.authenticatorProviderId());
        }

        @Override
        public Optional<AuthenticationMethodDetails> describeSuccessfulExecution(AuthenticationMethodDetailsContext context) {
            return Optional.of(new AuthenticationMethodDetails("email", context.executionTime(), Map.of(
                    "channel", "email",
                    "trust_framework", "urn:example:oidc4ac:email",
                    "assurance_level", "aal2"),
                    Optional.of(Map.of("email_verification_method", "code"))));
        }

        @Override
        public void close() {
        }
    }
}
