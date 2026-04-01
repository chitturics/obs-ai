"""Enterprise auth providers: OIDC, LDAP, with config.yaml integration."""
import base64
import hmac
import json
import logging
import os
import time
from typing import Any, Dict, Optional

# ADR-005: Algorithms that must be rejected to prevent JWT algorithm confusion attacks.
# Symmetric (HMAC) algorithms are rejected because they require sharing the secret with
# the verifier, making them unsuitable for OIDC id_token verification where the provider
# uses an asymmetric key pair.  "none" is rejected because it disables verification entirely.
_REJECTED_JWT_ALGORITHMS = {"none", "hs256", "hs384", "hs512"}  # symmetric + none

# Asymmetric algorithms acceptable for OIDC id_token signature verification (RS* / ES*).
# Only these algorithms are passed to jwt.decode() to prevent algorithm-confusion attacks.
_ALLOWED_ASYMMETRIC_ALGORITHMS = [
    "RS256", "RS384", "RS512",
    "ES256", "ES384", "ES512",
]

# JWKS cache entry lifetime in seconds (1 hour).  Kept short enough to pick up key
# rotations within a reasonable window without hammering the OIDC provider on every call.
_JWKS_CACHE_TTL_SECONDS = 3600

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JWKS in-memory cache
# ---------------------------------------------------------------------------

class _JwksCache:
    """Thread-safe in-memory cache for JWKS key sets, keyed by jwks_uri.

    Each entry stores the raw JWKS JSON and a monotonic expiry timestamp.
    Entries are replaced on first access after TTL expiry, which is acceptable
    because OIDC key sets change rarely (key rotation events).
    """

    def __init__(self, ttl_seconds: int = _JWKS_CACHE_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        # Mapping: jwks_uri → {"keys": <raw-dict>, "expires_at": <float>}
        self._store: Dict[str, Dict] = {}

    def get(self, jwks_uri: str) -> Optional[Dict]:
        """Return cached JWKS dict if present and not expired, else None."""
        entry = self._store.get(jwks_uri)
        if entry and entry["expires_at"] > time.monotonic():
            return entry["keys"]
        return None

    def set(self, jwks_uri: str, jwks_dict: Dict) -> None:
        """Store a JWKS dict with a fresh expiry timestamp."""
        self._store[jwks_uri] = {
            "keys": jwks_dict,
            "expires_at": time.monotonic() + self._ttl_seconds,
        }

    def invalidate(self, jwks_uri: str) -> None:
        """Remove a cached entry (used to force refresh after a key-miss)."""
        self._store.pop(jwks_uri, None)


# Module-level singleton cache shared across all OIDCProvider instances.
_jwks_cache = _JwksCache()


def _auth_identity(user_id: str, **kwargs) -> Dict[str, Any]:
    return {"user_id": user_id, "email": "", "display_name": "", "roles": ["USER"],
            "groups": [], "provider": "", "metadata": {},
            "access_token": "", "refresh_token": "", "token_expiry": 0, **kwargs}

# Keep AuthIdentity as alias for backward compat (was a dataclass, now a dict constructor)
AuthIdentity = _auth_identity


class OIDCProvider:
    provider_type = "oidc"

    def __init__(self, config: Dict[str, Any]):
        self.issuer_url = config.get("issuer_url", "")
        self.client_id = config.get("client_id", "")
        self.client_secret = config.get("client_secret", "")
        self.scopes = config.get("scopes", ["openid", "profile", "email"])
        self.claim_mappings = config.get("claim_mappings", {})
        self.group_to_role = config.get("group_to_role_mappings", {})
        self.name = config.get("name", "oidc")
        self.audience = config.get("audience", "")  # Expected aud claim
        self._discovery_doc: Optional[Dict] = None
        # State/nonce store: {state_value: {"nonce": nonce, "expires": timestamp}}
        self._pending_states: Dict[str, Dict] = {}

    async def _discover(self) -> Optional[Dict]:
        if self._discovery_doc:
            return self._discovery_doc
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                self._discovery_doc = (
                    await client.get(f"{self.issuer_url}/.well-known/openid-configuration")
                ).json()
            return self._discovery_doc
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("[OIDC] Discovery failed for %s: %s", self.issuer_url, exc)
            return None

    async def authenticate(self, credentials: Dict[str, Any]) -> Optional[Dict]:
        code = credentials.get("code", "")
        redirect_uri = credentials.get("redirect_uri", "")
        expected_nonce = credentials.get("expected_nonce", "")
        if not code:
            return None
        discovery = await self._discover()
        if not discovery:
            return None
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                tokens = (await client.post(discovery["token_endpoint"], data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                })).json()
            if "error" in tokens:
                logger.error(
                    "[OIDC] Token exchange failed: %s",
                    tokens.get("error_description", tokens["error"]),
                )
                return None

            id_token_raw = tokens.get("id_token", "")
            # Use JWKS-based cryptographic verification when available; fall back to
            # unverified extraction (with a security warning) only when PyJWT is absent.
            jwks_uri = discovery.get("jwks_uri", "")
            if jwks_uri:
                claims = await self._verify_id_token_with_jwks(id_token_raw, jwks_uri, expected_nonce)
            else:
                logger.warning(
                    "[OIDC][SECURITY] Discovery document has no jwks_uri — "
                    "falling back to unverified payload extraction.  "
                    "Configure jwks_uri on the provider for full signature verification."
                )
                claims = self._decode_jwt_unverified(id_token_raw)
                if claims and expected_nonce:
                    claims = self._validate_nonce(claims, expected_nonce)

            if not claims:
                return None
            return self._map_claims(claims, tokens)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("[OIDC] Auth failed: %s", exc)
            return None

    async def validate_token(self, token: str) -> Optional[Dict]:
        discovery = await self._discover()
        if not discovery:
            return None
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    discovery["userinfo_endpoint"],
                    headers={"Authorization": f"Bearer {token}"},
                )
                if resp.status_code != 200:
                    return None
                return self._map_claims(resp.json(), {"access_token": token})
        except Exception:  # broad catch — resilience against all failures
            return None

    def get_login_url(self, redirect_uri: str) -> str:
        state = os.urandom(16).hex()
        nonce = os.urandom(16).hex()
        # Store state+nonce for validation in callback (5 min TTL).
        self._pending_states[state] = {"nonce": nonce, "expires": time.time() + 300}
        # Prune expired states to prevent unbounded growth.
        now = time.time()
        self._pending_states = {
            k: v for k, v in self._pending_states.items() if v["expires"] > now
        }
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.scopes),
            "state": state,
            "nonce": nonce,
        }
        return f"{self.issuer_url}/authorize?" + "&".join(f"{k}={v}" for k, v in params.items())

    def validate_state(self, state: str) -> Optional[str]:
        """Validate and consume an OIDC state parameter. Returns nonce if valid."""
        entry = self._pending_states.pop(state, None)
        if not entry:
            logger.warning("[OIDC] State validation failed: unknown state")
            return None
        if entry["expires"] < time.time():
            logger.warning("[OIDC] State validation failed: expired")
            return None
        return entry["nonce"]

    # ------------------------------------------------------------------
    # JWKS-based cryptographic id_token verification (primary path)
    # ------------------------------------------------------------------

    async def _fetch_jwks(self, jwks_uri: str) -> Optional[Dict]:
        """Fetch the JWKS document from *jwks_uri*, returning the raw dict.

        Results are cached in the module-level _jwks_cache for _JWKS_CACHE_TTL_SECONDS
        (default 1 hour) to avoid hammering the OIDC provider on every authentication
        attempt.  The cache entry is invalidated and refreshed when a key-ID is not
        found in the cached set (handles key rotation between cache refreshes).
        """
        cached = _jwks_cache.get(jwks_uri)
        if cached is not None:
            return cached
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(jwks_uri)
                resp.raise_for_status()
                jwks_dict = resp.json()
            _jwks_cache.set(jwks_uri, jwks_dict)
            logger.debug("[OIDC] Fetched and cached JWKS from %s (%d keys)", jwks_uri, len(jwks_dict.get("keys", [])))
            return jwks_dict
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("[OIDC] Failed to fetch JWKS from %s: %s", jwks_uri, exc)
            return None

    async def _verify_id_token_with_jwks(
        self,
        id_token: str,
        jwks_uri: str,
        expected_nonce: str = "",
    ) -> Dict:
        """Cryptographically verify *id_token* using the JWKS published at *jwks_uri*.

        Verification steps (in order):
          1. Reject tokens signed with algorithms in _REJECTED_JWT_ALGORITHMS.
          2. Fetch (or serve from cache) the JWKS key set.
          3. Use PyJWT to decode and verify the signature with the matching public key.
          4. Verify standard claims: iss, aud, exp (handled by PyJWT options).
          5. Verify the nonce claim using a timing-safe comparison (ADR-005).

        Falls back to unverified extraction with a prominent security warning if PyJWT
        is not installed, so that misconfigured environments fail loudly rather than
        silently.  Callers should treat that path as a degraded-mode security risk.

        Returns the verified claims dict, or an empty dict on any failure.
        """
        if not id_token:
            return {}

        # --- Step 1: Algorithm pre-check from JWT header ---
        alg_from_header = self._extract_jwt_algorithm(id_token)
        if alg_from_header and alg_from_header.lower() in _REJECTED_JWT_ALGORITHMS:
            logger.warning(
                "[OIDC][SECURITY] id_token uses rejected algorithm '%s' — rejecting "
                "(algorithm confusion attack prevention)",
                alg_from_header,
            )
            return {}

        # --- Step 2: Try PyJWT cryptographic verification ---
        try:
            import jwt as pyjwt
            from jwt import PyJWKSet, DecodeError, ExpiredSignatureError, InvalidTokenError
            from jwt.exceptions import PyJWKSetError, PyJWKError
        except ImportError:
            logger.warning(
                "[OIDC][SECURITY] PyJWT is not installed.  id_token signature cannot be "
                "cryptographically verified.  Install PyJWT[crypto] to enable JWKS verification.  "
                "Falling back to unverified payload extraction — TREAT THIS AS A SECURITY RISK."
            )
            claims = self._decode_jwt_unverified(id_token)
            return self._validate_nonce(claims, expected_nonce) if (claims and expected_nonce) else (claims or {})

        # --- Step 3: Fetch JWKS and locate the signing key by kid ---
        signing_key = await self._get_signing_key_for_token(id_token, jwks_uri, pyjwt, PyJWKSet)
        if signing_key is None:
            return {}

        # --- Step 4: Decode and verify the token signature + standard claims ---
        decode_options: Dict = {
            "verify_signature": True,
            "verify_exp": True,
            "verify_iss": bool(self.issuer_url),
            "verify_aud": bool(self.audience),
        }
        decode_kwargs: Dict = {
            "algorithms": _ALLOWED_ASYMMETRIC_ALGORITHMS,
            "options": decode_options,
        }
        if self.issuer_url:
            decode_kwargs["issuer"] = self.issuer_url
        if self.audience:
            decode_kwargs["audience"] = self.audience

        try:
            claims: Dict = pyjwt.decode(id_token, signing_key, **decode_kwargs)
        except ExpiredSignatureError:
            logger.warning("[OIDC][SECURITY] id_token signature is valid but token is expired")
            return {}
        except DecodeError as exc:
            logger.warning("[OIDC][SECURITY] id_token signature verification failed: %s", exc)
            return {}
        except InvalidTokenError as exc:
            logger.warning("[OIDC][SECURITY] id_token claim validation failed: %s", exc)
            return {}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("[OIDC] Unexpected error during id_token verification: %s", exc)
            return {}

        logger.debug("[OIDC] id_token signature verified successfully for sub=%s", claims.get("sub", "<no-sub>"))

        # --- Step 5: Nonce verification (ADR-005: timing-safe) ---
        if expected_nonce:
            return self._validate_nonce(claims, expected_nonce)

        return claims

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get_signing_key_for_token(self, id_token: str, jwks_uri: str, pyjwt, PyJWKSet):
        """Resolve the signing key for *id_token* from the JWKS at *jwks_uri*.

        Extracts the `kid` from the token header, then looks it up in the cached JWKS.
        If the kid is absent from the cached set, invalidates the cache and retries once
        (handles key rotation that happened between cache fills).

        Returns the matching PyJWK key object, or None on any failure.
        """
        # Extract kid from the unverified header so we can match it against the JWKS.
        try:
            unverified_header = pyjwt.get_unverified_header(id_token)
            kid = unverified_header.get("kid")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[OIDC] Could not read JWT header for kid extraction: %s", exc)
            return None

        def _find_key_in_jwks(jwks_dict: Dict):
            """Build a PyJWKSet from *jwks_dict* and return the key matching *kid*."""
            try:
                jwk_set = PyJWKSet.from_dict(jwks_dict)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.error("[OIDC] Failed to parse JWKS: %s", exc)
                return None
            if kid:
                # Match by kid when the token specifies one.
                for key in jwk_set.keys:
                    if getattr(key, "key_id", None) == kid:
                        return key
                return None
            # No kid in the token header — use the first available key (single-key JWKS).
            return jwk_set.keys[0] if jwk_set.keys else None

        jwks_dict = await self._fetch_jwks(jwks_uri)
        if not jwks_dict:
            logger.error("[OIDC] Cannot verify id_token: JWKS unavailable from %s", jwks_uri)
            return None

        signing_key = _find_key_in_jwks(jwks_dict)
        if signing_key is None and kid:
            # kid not found — could be a recently rotated key not yet in cache.
            logger.info(
                "[OIDC] kid '%s' not found in cached JWKS — invalidating cache and retrying", kid
            )
            _jwks_cache.invalidate(jwks_uri)
            jwks_dict = await self._fetch_jwks(jwks_uri)
            if jwks_dict:
                signing_key = _find_key_in_jwks(jwks_dict)

        if signing_key is None:
            logger.error("[OIDC] Could not locate signing key (kid=%s) in JWKS from %s", kid, jwks_uri)
        return signing_key

    @staticmethod
    def _extract_jwt_algorithm(token: str) -> str:
        """Return the 'alg' value from the JWT header, or empty string on failure."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return ""
            header_b64 = parts[0] + "=" * (4 - len(parts[0]) % 4)
            header = json.loads(base64.urlsafe_b64decode(header_b64))
            return str(header.get("alg", ""))
        except Exception:  # broad catch — resilience at boundary
            return ""

    def _validate_nonce(self, claims: Dict, expected_nonce: str) -> Dict:
        """Verify nonce claim with a timing-safe comparison (ADR-005).

        Returns *claims* unchanged if nonce matches, else returns empty dict.
        """
        token_nonce = claims.get("nonce", "")
        if not hmac.compare_digest(token_nonce, expected_nonce):
            logger.warning(
                "[OIDC][SECURITY] Nonce mismatch: expected=%s got=%s",
                expected_nonce[:8],
                token_nonce[:8] if token_nonce else "MISSING",
            )
            return {}
        return claims

    def _decode_jwt_unverified(self, token: str) -> Dict:
        """Extract JWT payload WITHOUT signature verification.

        This method is intentionally named to make it clear it performs NO
        cryptographic verification.  It should only be called when:
          - jwks_uri is absent from the discovery document, OR
          - PyJWT is not installed (degraded-mode security risk).

        For the primary authentication path, use _verify_id_token_with_jwks().
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                logger.warning("[OIDC] JWT does not have 3 parts — rejecting")
                return {}
            # ADR-005: Reject unsafe algorithms before processing payload
            alg = self._extract_jwt_algorithm(token)
            if alg.lower() in _REJECTED_JWT_ALGORITHMS:
                logger.warning(
                    "[OIDC] JWT uses rejected algorithm '%s' — rejecting (algorithm confusion attack prevention)",
                    alg,
                )
                return {}
            payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload_b64))
            # Require at least one identity claim
            if not claims.get("sub") and not claims.get("email"):
                logger.warning("[OIDC] JWT missing sub and email claims — rejecting")
                return {}
            # Expiry check
            exp = claims.get("exp")
            if exp and isinstance(exp, (int, float)) and exp < time.time():
                logger.warning("[OIDC] JWT expired at %s", exp)
                return {}
            # Issuer check
            iss = claims.get("iss", "")
            if self.issuer_url and iss and not iss.startswith(self.issuer_url.rstrip("/")):
                logger.warning("[OIDC] JWT issuer mismatch: expected=%s got=%s", self.issuer_url, iss)
                return {}
            # Audience check
            if self.audience:
                aud = claims.get("aud", "")
                if isinstance(aud, list):
                    if self.audience not in aud:
                        logger.warning("[OIDC] JWT audience mismatch: expected=%s got=%s", self.audience, aud)
                        return {}
                elif aud != self.audience:
                    logger.warning("[OIDC] JWT audience mismatch: expected=%s got=%s", self.audience, aud)
                    return {}
            return claims
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[OIDC] JWT unverified decode failed: %s", exc)
            return {}

    def _map_claims(self, claims: Dict, tokens: Dict) -> Dict:
        cm = self.claim_mappings
        groups = claims.get(cm.get("groups", "groups"), [])
        if isinstance(groups, str):
            groups = [groups]
        roles = set()
        for g in groups:
            if mapped := self.group_to_role.get(g):
                roles.update(mapped if isinstance(mapped, list) else [mapped])
        return _auth_identity(
            user_id=claims.get(cm.get("user_id", "sub"), ""),
            email=claims.get(cm.get("email", "email"), ""),
            display_name=claims.get(cm.get("name", "name"), ""),
            roles=sorted(roles) if roles else ["USER"], groups=groups,
            provider=f"oidc:{self.name}", access_token=tokens.get("access_token", ""),
            refresh_token=tokens.get("refresh_token", ""), metadata={"claims": claims})


class LDAPProvider:
    provider_type = "ldap"

    def __init__(self, config: Dict[str, Any]):
        self.server_url = config.get("server_url", "")
        self.bind_dn = config.get("bind_dn", "")
        self.user_search_base = config.get("user_search_base", "")
        self.group_search_base = config.get("group_search_base", "")
        self.group_to_role = config.get("group_to_role_mappings", {})
        self.name = config.get("name", "ldap")

    async def authenticate(self, credentials: Dict[str, Any]) -> Optional[Dict]:
        username, password = credentials.get("username", ""), credentials.get("password", "")
        if not username or not password:
            return None
        try:
            import ldap3
            server = ldap3.Server(self.server_url, get_info=ldap3.ALL)
            conn = ldap3.Connection(server, user=f"{self.user_search_base}\\{username}", password=password)
            if not conn.bind():
                return None
            conn.search(self.group_search_base, f"(member={conn.user})", attributes=["cn"])
            groups = [entry.cn.value for entry in conn.entries]
            roles = set()
            for g in groups:
                if mapped := self.group_to_role.get(g):
                    roles.update(mapped if isinstance(mapped, list) else [mapped])
            return _auth_identity(user_id=username, display_name=username,
                                  roles=sorted(roles) if roles else ["USER"],
                                  groups=groups, provider=f"ldap:{self.name}")
        except ImportError:
            logger.error("[LDAP] ldap3 not installed")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error("[LDAP] Auth failed: %s", e)
        return None

    async def validate_token(self, token: str) -> Optional[Dict]:
        return None

    def get_login_url(self, redirect_uri: str) -> str:
        return ""


# Provider registry
_providers: Dict[str, Any] = {}

def register_provider(name: str, provider):
    _providers[name] = provider
    logger.info("[AUTH] Registered: %s (%s)", name, provider.provider_type)

def get_provider(name: str):
    return _providers.get(name)

def get_all_providers() -> Dict:
    return dict(_providers)

def init_auth_providers():
    try:
        from chat_app.settings import get_settings
        auth_config = getattr(get_settings(), "auth", None)
        if not auth_config:
            return
        for pconf in getattr(auth_config, "providers", []):
            if not isinstance(pconf, dict):
                continue
            ptype, pname = pconf.get("type", ""), pconf.get("name", pconf.get("type", ""))
            if ptype == "oidc":
                register_provider(pname, OIDCProvider(pconf))
            elif ptype == "ldap":
                register_provider(pname, LDAPProvider(pconf))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.debug("[AUTH] Init skipped: %s", e)
