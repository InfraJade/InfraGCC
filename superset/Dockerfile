# Jade GCC Superset image: pinned apache/superset 4.1.2 plus the Postgres driver, Authlib (Keycloak SSO) and
# flask-cors, our superset_config.py, the bundle generator/spec and the init script.
#
# One image, four services (see compose.snippet.yaml):
#   superset-init    /app/docker/gcc-superset-init.sh        (one-shot, idempotent, runs on every start)
#   superset         /usr/bin/run-server.sh                  (default CMD, gunicorn on :8088)
#   superset-worker  celery --app=superset.tasks.celery_app:app worker ...
#   superset-beat    celery --app=superset.tasks.celery_app:app beat ...
#
# Build: docker build -t gcc-superset:dev superset

ARG SUPERSET_IMAGE=apache/superset:4.1.2
FROM ${SUPERSET_IMAGE}

USER root

# Superset 4.1.x installs into the system interpreter (/usr/local), not a venv.
RUN pip install --no-cache-dir --disable-pip-version-check \
        "psycopg2-binary==2.9.6" \
        "Authlib==1.3.2" \
        "flask-cors==4.0.2"

COPY --chown=superset:superset pythonpath/ /app/pythonpath/
COPY --chown=superset:superset bundle/ /app/gcc/bundle/
COPY --chown=superset:superset init_superset.py verify_superset.py /app/gcc/
COPY --chown=superset:superset --chmod=0755 docker/gcc-superset-init.sh /app/docker/gcc-superset-init.sh

# Generate the import bundle at build time so a bad spec fails the build, not the first start.
# The ZIP holds no secrets: the database password is masked and supplied at import time.
RUN python /app/gcc/bundle/generate_bundle.py --out /app/gcc/bundle/gcc_bundle.zip \
    && chown superset:superset /app/gcc/bundle/gcc_bundle.zip

USER superset
