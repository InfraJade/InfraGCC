#!/bin/sh
# Issue a client certificate for one collector, signed by the dev CA (run make-ca.sh first).
#
#   infra/pki/make-collector-cert.sh pnq1-col-a
#
# Without a local openssl:
#   MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh -v "$PWD/infra/pki:/pki" alpine/openssl \
#     /pki/make-collector-cert.sh pnq1-col-a
#
# Writes <out>/<name>.key and <out>/<name>.crt and prints the certificate's SHA-256 fingerprint: store it in
# `collectors.cert_fingerprint` (Admin -> Collectors, or the SQL printed below). The ingest API compares
# fingerprints case-insensitively and ignores colons, so either printed form works.
#
# Environment: PKI_OUT (default <this dir>/out), PKI_CLIENT_DAYS (default 825).
# DEV ONLY: see make-ca.sh.
set -eu
export MSYS2_ARG_CONV_EXCL="/O="

name=${1:-}
case "$name" in
  "" | -* | *[!a-z0-9-]*)
    echo "usage: $0 <collector-name>   (lowercase letters, digits and '-', e.g. pnq1-col-a)" >&2
    exit 2
    ;;
esac

here=$(cd "$(dirname "$0")" && pwd)
out=${PKI_OUT:-$here/out}
days=${PKI_CLIENT_DAYS:-825}

command -v openssl >/dev/null 2>&1 || { echo "openssl not found (see the docker command in this file)" >&2; exit 1; }
[ -f "$out/ca.key" ] || { echo "No CA in $out; run make-ca.sh first." >&2; exit 1; }
umask 077

ext=$(mktemp)
csr=$(mktemp)
trap 'rm -f "$ext" "$csr"' EXIT
cat >"$ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=clientAuth
subjectAltName=DNS:$name
authorityKeyIdentifier=keyid
subjectKeyIdentifier=hash
EOF

openssl req -new -nodes -sha256 -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
  -keyout "$out/$name.key" -out "$csr" \
  -subj "/O=Jade GCC (dev)/OU=Collectors/CN=$name"
openssl x509 -req -sha256 -in "$csr" -CA "$out/ca.crt" -CAkey "$out/ca.key" -CAcreateserial \
  -days "$days" -extfile "$ext" -out "$out/$name.crt"
# Dev only: readable by the collector container whatever uid it runs as. In production: 0600, owned by
# the collector's user, or delivered by the secrets manager.
chmod 644 "$out/$name.key" "$out/$name.crt"

colon=$(openssl x509 -in "$out/$name.crt" -noout -fingerprint -sha256 | sed 's/^[^=]*=//')
hex=$(printf '%s' "$colon" | tr -d ':' | tr 'ABCDEF' 'abcdef')

echo "Created $out/$name.crt"
echo "Subject:            $(openssl x509 -in "$out/$name.crt" -noout -subject | sed 's/^subject= *//')"
echo "SHA-256 fingerprint: $hex"
echo "                     ($colon)"
echo
echo "Register it (dev stack):"
echo "  docker compose exec timescaledb psql -U gcc_owner -d gcc -c \\"
echo "    \"UPDATE collectors SET cert_fingerprint = '$hex' WHERE name = '$name';\""
