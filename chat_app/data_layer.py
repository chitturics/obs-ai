"""
This module contains a custom SQLAlchemy data layer with graceful error handling.
"""
import logging
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

logger = logging.getLogger(__name__)


class LenientSQLAlchemyDataLayer(SQLAlchemyDataLayer):
    """SQLAlchemy data layer with graceful error handling."""

    async def get_thread_author(self, thread_id):
        try:
            return await super().get_thread_author(thread_id)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to get thread author for thread_id {thread_id}: {e}")
            return None

    async def create_element(self, element):
        try:
            return await super().create_element(element)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to create element: {e}")
            return None

    async def get_element(self, thread_id, element_id):
        try:
            return await super().get_element(thread_id, element_id)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to get element for thread_id {thread_id} and element_id {element_id}: {e}")
            return None
