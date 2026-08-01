/*
 * Copyright 2026 Red Hat, Inc. and/or its affiliates
 * and other contributors as indicated by the @author tags.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */
package org.keycloak.testsuite.authentication;

import java.security.SecureRandom;
import java.util.Map;

import jakarta.ws.rs.core.MultivaluedMap;
import jakarta.ws.rs.core.Response;

import org.keycloak.authentication.AuthenticationFlowContext;
import org.keycloak.authentication.AuthenticationFlowError;
import org.keycloak.authentication.Authenticator;
import org.keycloak.email.EmailException;
import org.keycloak.email.EmailSenderProvider;
import org.keycloak.forms.login.LoginFormsProvider;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.sessions.AuthenticationSessionModel;

/**
 * Disposable email-code authenticator used to exercise the external OIDC4AC SPI.
 *
 * <p>The realm SMTP settings are used deliberately: the lab points them at
 * smtp4dev, while a deployment can point the same provider at a normal SMTP
 * relay. The code is kept only in the authentication-session notes and is
 * never placed in a token or an authentication-method property.</p>
 */
public final class OIDC4ACEmailAuthenticator implements Authenticator {

    private static final SecureRandom RANDOM = new SecureRandom();
    private static final int CODE_LENGTH = 6;
    private static final long CODE_LIFESPAN_MILLIS = 5 * 60 * 1000L;
    private static final String CODE_NOTE = "oidc4ac.email.code";
    private static final String ISSUED_AT_NOTE = "oidc4ac.email.issued-at";
    private static final String CODE_SENT_MESSAGE = "oidc4acEmailCodeSent";
    private static final String INVALID_CODE_MESSAGE = "oidc4acInvalidEmailCode";
    private static final String SEND_ERROR_MESSAGE = "oidc4acEmailSendError";

    @Override
    public void authenticate(AuthenticationFlowContext context) {
        try {
            issueCodeIfNeeded(context);
            context.challenge(codeForm(context, null));
        } catch (EmailException e) {
            context.failureChallenge(AuthenticationFlowError.INTERNAL_ERROR,
                    context.form().setError(SEND_ERROR_MESSAGE).createErrorPage(Response.Status.INTERNAL_SERVER_ERROR));
        }
    }

    @Override
    public void action(AuthenticationFlowContext context) {
        AuthenticationSessionModel authenticationSession = context.getAuthenticationSession();
        String expected = getSessionNote(authenticationSession, CODE_NOTE);
        String issuedAt = getSessionNote(authenticationSession, ISSUED_AT_NOTE);
        MultivaluedMap<String, String> formData = context.getHttpRequest().getDecodedFormParameters();
        String submitted = formData.getFirst("otp");

        if (expected == null || isExpired(issuedAt)) {
            removeSessionNote(authenticationSession, CODE_NOTE);
            removeSessionNote(authenticationSession, ISSUED_AT_NOTE);
            try {
                issueCodeIfNeeded(context);
                context.challenge(codeForm(context, INVALID_CODE_MESSAGE));
            } catch (EmailException e) {
                context.failureChallenge(AuthenticationFlowError.INTERNAL_ERROR,
                        context.form().setError(SEND_ERROR_MESSAGE)
                                .createErrorPage(Response.Status.INTERNAL_SERVER_ERROR));
            }
            return;
        }

        if (expected.equals(submitted)) {
            removeSessionNote(authenticationSession, CODE_NOTE);
            removeSessionNote(authenticationSession, ISSUED_AT_NOTE);
            context.success();
            return;
        }

        context.failureChallenge(AuthenticationFlowError.INVALID_CREDENTIALS,
                codeForm(context, INVALID_CODE_MESSAGE));
    }

    private void issueCodeIfNeeded(AuthenticationFlowContext context) throws EmailException {
        AuthenticationSessionModel authenticationSession = context.getAuthenticationSession();
        String existing = getSessionNote(authenticationSession, CODE_NOTE);
        if (existing != null && !isExpired(getSessionNote(authenticationSession, ISSUED_AT_NOTE))) {
            return;
        }

        UserModel user = context.getUser();
        String email = user == null ? null : user.getEmail();
        if (email == null || email.isBlank()) {
            throw new EmailException("The user does not have an email address");
        }
        Map<String, String> smtpConfig = context.getRealm().getSmtpConfig();
        if (smtpConfig == null || smtpConfig.isEmpty()) {
            throw new EmailException("The realm has no SMTP configuration");
        }

        String code = String.format("%0" + CODE_LENGTH + "d", RANDOM.nextInt(1_000_000));
        context.getSession().getProvider(EmailSenderProvider.class).send(
                smtpConfig,
                user,
                "OIDC4AC verification code",
                "Your OIDC4AC verification code is: " + code + "\n\nThis code expires in five minutes.",
                "<p>Your OIDC4AC verification code is <strong>" + code
                        + "</strong>.</p><p>This code expires in five minutes.</p>");
        setSessionNote(authenticationSession, CODE_NOTE, code);
        setSessionNote(authenticationSession, ISSUED_AT_NOTE, Long.toString(System.currentTimeMillis()));
    }

    private String getSessionNote(AuthenticationSessionModel session, String name) {
        String authNote = session.getAuthNote(name);
        return authNote != null ? authNote : session.getClientNote(name);
    }

    private void setSessionNote(AuthenticationSessionModel session, String name, String value) {
        session.setAuthNote(name, value);
        // The OIDC4AC planner may fork the authentication session while a
        // factor is challenged. Client notes are copied into that fork, so
        // retain the transient code there as well. It is removed on every
        // terminal path and is never included in a token claim.
        session.setClientNote(name, value);
    }

    private void removeSessionNote(AuthenticationSessionModel session, String name) {
        session.removeAuthNote(name);
        session.removeClientNote(name);
    }

    private Response codeForm(AuthenticationFlowContext context, String error) {
        LoginFormsProvider form = context.form();
        if (error != null) {
            form.setError(error);
        } else {
            form.setInfo(CODE_SENT_MESSAGE);
        }
        return form.createLoginTotp();
    }

    private boolean isExpired(String issuedAt) {
        if (issuedAt == null) {
            return true;
        }
        try {
            return System.currentTimeMillis() - Long.parseLong(issuedAt) > CODE_LIFESPAN_MILLIS;
        } catch (NumberFormatException e) {
            return true;
        }
    }

    @Override
    public boolean requiresUser() {
        return true;
    }

    @Override
    public boolean configuredFor(KeycloakSession session, RealmModel realm, UserModel user) {
        return true;
    }

    @Override
    public void setRequiredActions(KeycloakSession session, RealmModel realm, UserModel user) {
    }

    @Override
    public void close() {
    }
}
