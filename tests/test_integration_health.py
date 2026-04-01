"""Integration tests for health check system."""
import sys
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))

# health.py imports sqlalchemy.ext.asyncio at the top level.  If an earlier
# test injected a bare MagicMock for "sqlalchemy" (which cannot resolve
# submodules like a real package), the import will fail.  Detect and skip.
_sqlalchemy_mocked = (
    "sqlalchemy" in sys.modules
    and isinstance(sys.modules["sqlalchemy"], MagicMock)
)


@pytest.mark.skipif(
    _sqlalchemy_mocked,
    reason="sqlalchemy is a MagicMock injected by another test — cannot import health.py",
)
class TestHealthIntegration:
    """Test health check system integration."""

    @pytest.mark.asyncio
    async def test_healthy_system(self):
        """Test health status when all services are up."""
        from health import get_health_status

        mock_result = MagicMock()
        mock_result.scalar.return_value = 1

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_cm

        with patch('health.httpx.AsyncClient') as mock_client_cls:
            mock_response_ok = MagicMock()
            mock_response_ok.status_code = 200
            mock_response_ok.json.return_value = {"models": [{"name": "test-model"}]}

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response_ok)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_health_status(mock_engine)

            assert result["status"] in ("healthy", "degraded")
            assert "services" in result
            assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_degraded_system(self):
        """Test health status when optional services are down."""
        from health import check_redis

        with patch.dict(os.environ, {"ENABLE_CACHE": "true", "REDIS_HOST": "nonexistent"}):
            result = await check_redis()
            assert result["status"] in ("unhealthy", "disabled")
