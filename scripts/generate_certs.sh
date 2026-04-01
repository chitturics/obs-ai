#!/bin/bash
# =====================================================================
# GENERATE SELF-SIGNED TLS CERTIFICATES FOR DEVELOPMENT
# =====================================================================
# For production, use Let's Encrypt or your organization's CA

set -euo pipefail

CERT_DIR="$(dirname "$0")/../certs"
mkdir -p "$CERT_DIR"

echo "Generating self-signed TLS certificate for development..."

# Generate private key
openssl genrsa -out "$CERT_DIR/privkey.pem" 4096

# Generate certificate signing request
openssl req -new -key "$CERT_DIR/privkey.pem" \
    -out "$CERT_DIR/cert.csr" \
    -subj "/C=US/ST=State/L=City/O=ObsAI Services/OU=IT/CN=localhost"

# Generate self-signed certificate (valid for 365 days)
openssl x509 -req -days 365 \
    -in "$CERT_DIR/cert.csr" \
    -signkey "$CERT_DIR/privkey.pem" \
    -out "$CERT_DIR/fullchain.pem" \
    -extfile <(echo "subjectAltName=DNS:localhost,DNS:*.localhost,IP:127.0.0.1")

# Create chain file (same as fullchain for self-signed)
cp "$CERT_DIR/fullchain.pem" "$CERT_DIR/chain.pem"

# Set permissions
chmod 600 "$CERT_DIR/privkey.pem"
chmod 644 "$CERT_DIR/fullchain.pem" "$CERT_DIR/chain.pem"

echo "✓ Certificates generated in $CERT_DIR"
echo "  - Private key: privkey.pem"
echo "  - Certificate: fullchain.pem"
echo "  - Chain: chain.pem"
echo ""
echo "⚠️  This is a self-signed certificate for DEVELOPMENT ONLY"
echo "   For production, use Let's Encrypt or your organization's CA"
