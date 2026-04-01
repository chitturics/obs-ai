# Secrets Rotation Procedures

## Rotation Schedule

| Secret | Rotation | Method |
|--------|----------|--------|
| Admin API Key | Every 90 days | Regenerate in start_all.sh |
| Admin Password | Every 90 days | Update .env + restart app |
| PostgreSQL Password | Every 180 days | Update .env + restart DB + app |
| JWT / Auth Secret | Every 180 days | Update .env + restart app (invalidates sessions) |
| Redis Password | Every 180 days | Update .env + restart Redis + app |
| Splunk Token | Per org policy | Update via Admin UI > Settings > Splunk |
| Grafana Password | Every 180 days | Update .env + restart Grafana |

## Procedures

### API Key Rotation (zero-downtime)
```bash
# 1. Generate new key
NEW_KEY="obsai_$(openssl rand -hex 24)"

# 2. Add to API_KEYS as comma-separated (both old and new work)
# Edit .env: API_KEYS=new_key,old_key

# 3. Restart app (both keys valid during transition)
podman restart chat_ui_app

# 4. Update all clients to use new key

# 5. Remove old key from API_KEYS, restart again
```

### Database Password Rotation
```bash
# 1. Generate new password
NEW_PASS=$(openssl rand -hex 16)

# 2. Change in PostgreSQL
podman exec chat_db_app psql -U chainlit_user -d chainlit_db \
  -c "ALTER USER chainlit_user PASSWORD '$NEW_PASS';"

# 3. Update .env with new POSTGRES_PASSWORD
# 4. Update DATABASE_URL in .env
# 5. Restart app container
podman restart chat_ui_app
```

### JWT Secret Rotation
```bash
# WARNING: This invalidates ALL active sessions
# 1. Generate new secret
NEW_SECRET=$(openssl rand -hex 32)

# 2. Update .env: CHAINLIT_AUTH_SECRET and JWT_SECRET
# 3. Restart app — all users must re-login
podman restart chat_ui_app
```

## Verification
After any rotation:
1. Check health: `curl http://localhost:8000/ready`
2. Test admin API: `curl -H "X-API-Key: $NEW_KEY" http://localhost:8000/api/admin/version`
3. Test login: Open http://localhost:8000 and authenticate
