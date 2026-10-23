#!/bin/sh
# Create the dev collector CA and the ingest server certificate (for infra/nginx/ingest-mtls.conf).
#
#   infra/pki/make-ca.sh                       # writes infra/pki/out/{ca,ingest-server}.{crt,key}
#   FORCE=1 infra/pki/make-ca.sh               # replace an existing CA (invalidates every collector cert)
#
# Without a local openssl:
#   MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh -v "$PWD/infra/pki:/pki" alpine/openssl /pki/make-ca.sh
#
# Environment:
#   PKI_OUT            output directory              (default: <this dir>/out)
#   PKI_CA_DAYS        CA validity in days            (default: 3650)
#   PKI_SERVER_DAYS    server cert validity in days   (default: 825)
#   PKI_SERVER_DNS     server cert DNS names          (default: "ingest-mtls localhost")
#
# DEV ONLY. In production the client CA lives in the company PKI / a secrets manager, the ingest server
# certificate comes from the company or a public CA, and private keys never sit in a working tree.
set -eu

# Git Bash (MSYS) would otherwise rewrite "/O=..." subjects into Windows paths; file paths still convert.
export MSYS2_ARG_CONV_EXCL="/O="

here=$(cd "$(dirname "$0")" && pwd)
out=${PKI_OUT:-$here/out}
ca_days=${PKI_CA_DAYS:-3650}
server_days=${PKI_SERVER_DAYS:-825}
server_dns=${PKI_SERVER_DNS:-"ingest-mtls localhost"}

command -v openssl >/dev/null 2>&1 || { echo "openssl not found (see the docker command in this file)" >&2; exit 1; }
mkdir -p "$out"
umask 077

if [ -f "$out/ca.key" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "CA already exists in $out (set FORCE=1 to replace it)."
else
  openssl req -x509 -new -nodes -sha256 \
    -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
    -keyout "$out/ca.key" -out "$out/ca.crt" -days "$ca_days" \
    -subj "/O=Jade GCC (dev)/OU=Collectors/CN=Jade GCC Dev Collector CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash"
  chmod 600 "$out/ca.key"
  chmod 644 "$out/ca.crt"
  echo "Created CA: $out/ca.crt"
fi

# Ingest server certificate (nginx). SANs: every name in PKI_SERVER_DNS plus 127.0.0.1.
san=""
for name in $server_dns; do san="${san:+$san,}DNS:$name"; done
san="$san,IP:127.0.0.1"

ext=$(mktemp)
csr=$(mktemp)
trap 'rm -f "$ext" "$csr"' EXIT
cat >"$ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$san
authorityKeyIdentifier=keyid
subjectKeyIdentifier=hash
EOF

first_dns=${server_dns%% *}
openssl req -new -nodes -sha256 -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
  -keyout "$out/ingest-server.key" -out "$csr" \
  -subj "/O=Jade GCC (dev)/CN=$first_dns"
openssl x509 -req -sha256 -in "$csr" -CA "$out/ca.crt" -CAkey "$out/ca.key" -CAcreateserial \
  -days "$server_days" -extfile "$ext" -out "$out/ingest-server.crt"
# Dev only: readable by the nginx and collector containers whatever uid they run as.
chmod 644 "$out/ingest-server.key" "$out/ingest-server.crt"

echo "Created ingest server certificate: $out/ingest-server.crt ($san)"
echo "Next: infra/pki/make-collector-cert.sh <collector-name>"
