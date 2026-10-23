// SHA-256 fingerprint of the verified client certificate, for infra/nginx/ingest-mtls.conf.
//
// nginx's built-in $ssl_client_fingerprint is SHA-1. This computes SHA-256 over the certificate's DER bytes
// (the same value `openssl x509 -noout -fingerprint -sha256` prints, as lowercase hex without colons), which
// is what infra/pki/make-collector-cert.sh prints and what is stored in collectors.cert_fingerprint.
import crypto from 'crypto';

function sha256(r) {
    var pem = r.variables.ssl_client_raw_cert;
    if (!pem || r.variables.ssl_client_verify !== 'SUCCESS') {
        return '';
    }
    var b64 = pem
        .replace(/-----BEGIN CERTIFICATE-----/, '')
        .replace(/-----END CERTIFICATE-----/, '')
        .replace(/\s+/g, '');
    var der = Buffer.from(b64, 'base64');
    return crypto.createHash('sha256').update(der).digest('hex');
}

export default { sha256 };
