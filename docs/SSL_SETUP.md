# SSL/TLS Certificate Setup

## Certificate Placement

ObsAI uses nginx as the SSL termination point. Place your certificates in the `app_certs` podman volume.

### Step 1: Find the volume path
```bash
# Get the volume mount path
CERT_PATH=$(podman volume inspect app_certs --format '{{.Mountpoint}}')
echo "Certificate path: $CERT_PATH"
```

### Step 2: Copy your certificates
```bash
# Copy your production certificates
sudo cp /path/to/your/cert.pem $CERT_PATH/cert.pem
sudo cp /path/to/your/key.pem $CERT_PATH/key.pem

# Optional: CA chain (for intermediate certificates)
sudo cp /path/to/your/ca-chain.pem $CERT_PATH/ca-chain.pem

# Set permissions
sudo chmod 644 $CERT_PATH/cert.pem
sudo chmod 600 $CERT_PATH/key.pem
sudo chmod 644 $CERT_PATH/ca-chain.pem
```

### Step 3: Alternative — use podman unshare
```bash
# For rootless podman on WSL2
podman unshare cp /path/to/your/cert.pem $(podman volume inspect app_certs --format '{{.Mountpoint}}')/cert.pem
podman unshare cp /path/to/your/key.pem $(podman volume inspect app_certs --format '{{.Mountpoint}}')/key.pem
podman unshare chmod 600 $(podman volume inspect app_certs --format '{{.Mountpoint}}')/key.pem
```

### Step 4: Enable SSL in nginx
Edit `containers/nginx/nginx.conf.template`:
1. Uncomment the HTTPS server block
2. Set `NGINX_SSL_PORT` (default 8443)
3. Add cert volume mount to nginx container

Or use environment variables in `start_all.sh`:
```bash
export SSL_ENABLED=true
export GATEWAY_SSL_PORT=8443
```

### Step 5: Restart
```bash
bash docker_files/start_all.sh --no-ingest
```

## Self-Signed Certificate (Development)

For development/testing, ObsAI auto-generates self-signed certificates:
```bash
# Auto-generated during start_all.sh if no certs exist
# Located at: app_certs volume
# Valid for: 365 days
# Subject: CN=localhost
```

## Certificate Verification
```bash
# Check certificate details
openssl x509 -in $CERT_PATH/cert.pem -noout -subject -dates -issuer

# Verify cert matches key
openssl x509 -noout -modulus -in $CERT_PATH/cert.pem | md5sum
openssl rsa -noout -modulus -in $CERT_PATH/key.pem | md5sum
# Both should match

# Test SSL connection
curl -v https://localhost:8443/ --cacert $CERT_PATH/ca-chain.pem
```

## Certificate Files

| File | Purpose | Required |
|------|---------|----------|
| `cert.pem` | Server certificate (PEM format) | Yes |
| `key.pem` | Private key (PEM format, unencrypted) | Yes |
| `ca-chain.pem` | CA chain / intermediate certs | Optional (for production) |

## Production Checklist

- [ ] Use certificates from a trusted CA (Let's Encrypt, DigiCert, etc.)
- [ ] Certificate covers your domain name (not localhost)
- [ ] Private key is NOT password-protected (nginx can't prompt)
- [ ] Certificate chain includes intermediates
- [ ] TLS 1.2+ only (configured in nginx)
- [ ] Strong cipher suite (HIGH:!aNULL:!MD5:!RC4)
- [ ] HSTS header enabled (already configured in nginx)
- [ ] Certificate expiry monitoring set up
- [ ] Redirect HTTP → HTTPS enabled

## Admin API — SSL Status
```bash
# Check SSL status via API
curl -H "X-API-Key: YOUR_KEY" http://localhost:8000/api/admin/ssl/status
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "SSL: error:0B080074" | Key doesn't match cert — regenerate both |
| "permission denied" | `chmod 600 key.pem` + check volume permissions |
| "certificate has expired" | Renew cert, copy new files, restart nginx |
| Browser "not secure" | Using self-signed cert — add to browser trust store |
| Mixed content warnings | Ensure ALL resources load via HTTPS |
