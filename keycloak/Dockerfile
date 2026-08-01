FROM eclipse-temurin:21-jre-jammy

ENV KEYCLOAK_HOME=/opt/keycloak

COPY .build/keycloak-26.7.0.tar.gz /tmp/keycloak.tar.gz
RUN mkdir -p "${KEYCLOAK_HOME}" \
    && tar -xzf /tmp/keycloak.tar.gz -C "${KEYCLOAK_HOME}" --strip-components=1 \
    && rm /tmp/keycloak.tar.gz \
    && mkdir -p "${KEYCLOAK_HOME}/data/import"

COPY config/realm-import.json ${KEYCLOAK_HOME}/data/import/oidc4ac-realm.json

WORKDIR ${KEYCLOAK_HOME}
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
