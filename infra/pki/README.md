# Dev PKI for collector mutual TLS

**Dev only.** These scripts make a throwaway CA so the prod-style mTLS path (DECISIONS.md D8) can be run on a
laptop. Everything they write goes to `infra/pki/out/`, which is gitignored. In staging and production the
client CA belongs to the company PKI, the ingest server certificate comes from the company or a public CA, and
keys are held by the secrets manager (cloud side) and the collector VM (on-prem), with `0600` permissions.

| Script | Writes | Notes |
|---|---|---|
| `make-ca.sh` | `ca.crt`, `ca.key`, `ingest-server.crt`, `ingest-server.key` | EC P-256 keys. The CA is kept if it already exists (`FORCE=1` replaces it, which invalidates every collector certificate). The server certificate is reissued on every run, with SANs `ingest-mtls`, `localhost`, `127.0.0.1` (`PKI_SERVER_DNS` changes the names). |
| `make-collector-cert.sh <name>` | `<name>.crt`, `<name>.key` | Client certificate (`extendedKeyUsage=clientAuth`, `CN=<name>`). Prints the SHA-256 fingerprint and the SQL to register it. |

Both are POSIX `sh` + `openssl` (1.1.1 or 3.x). Environment: `PKI_OUT` (output directory), `PKI_CA_DAYS`
(3650), `PKI_SERVER_DAYS` (825), `PKI_CLIENT_DAYS` (825).

## Run

From the repo root, with a local `openssl` (Linux, macOS, Git Bash):

```sh
sh infra/pki/make-ca.sh
for c in pnq1-col-a pnq1-col-b hyd1-col-a; do sh infra/pki/make-collector-cert.sh "$c"; done
```

Without `openssl`, in a container (the `MSYS_NO_PATHCONV=1` prefix is only needed in Git Bash):

```sh
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh -v "$PWD/infra/pki:/pki" alpine/openssl /pki/make-ca.sh
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh -v "$PWD/infra/pki:/pki" alpine/openssl \
  /pki/make-collector-cert.sh pnq1-col-a
```

## Fingerprints

The ingest API identifies a collector by the **SHA-256 fingerprint of its certificate (DER)**, stored in
`collectors.cert_fingerprint`. `make-collector-cert.sh` prints it as lowercase hex
(`b0c7a0e6…f84b`) and in OpenSSL's colon form; the API ignores case and colons, so either works. nginx
computes the same value with njs (`infra/nginx/cert_fingerprint.js`) and forwards it as
`X-Client-Cert-Fingerprint`. (nginx's built-in `$ssl_client_fingerprint` is SHA-1 and is not used.)

To check a certificate by hand:

```sh
openssl x509 -in infra/pki/out/pnq1-col-a.crt -noout -fingerprint -sha256
```

Register it in Admin → Collectors, or with SQL:

```sh
docker compose exec timescaledb psql -U gcc_owner -d gcc \
  -c "UPDATE collectors SET cert_fingerprint = '<hex>' WHERE name = 'pnq1-col-a';"
```

With the overlay below, the one-shot `mtls-register` service does this for the three dev collectors.

## Use with the local stack

```sh
docker compose -f compose.yaml -f infra/compose.mtls.yaml up -d
```

`infra/compose.mtls.yaml` adds `ingest-mtls` (nginx on host port 8443, config `infra/nginx/ingest-mtls.conf`),
switches the ingest API to `INGEST_AUTH_MODE=mtls`, trusts identity headers only from the proxy's fixed address,
and points the collectors at `https://ingest-mtls:8443` with their own certificate.

Test by hand from the host:

```sh
curl --cacert infra/pki/out/ca.crt --cert infra/pki/out/pnq1-col-a.crt --key infra/pki/out/pnq1-col-a.key \
  https://localhost:8443/ingest/v1/config
```

## Rotation and revocation (production notes)

- Each collector has one fingerprint. Rotate one collector of a pair at a time: issue the new certificate,
  update the fingerprint and restart that collector together. Requests in the few seconds between the two get 401;
  if it takes longer, the partner collector covers the servers (D9).
- To revoke immediately: clear `collectors.cert_fingerprint` or disable the collector (the API answers 401), and
  publish a CRL to nginx (`ssl_crl`).
