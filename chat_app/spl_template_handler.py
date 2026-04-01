"""
SPL template handler for the Splunk Assistant.
"""
import logging
from typing import Optional

from shared.spl_template_engine import SPLTemplateEngine

logger = logging.getLogger(__name__)


def try_spl_template(user_input: str) -> Optional[str]:
    """Try to generate SPL using the template engine."""
    try:
        query, intent, explanation = SPLTemplateEngine.generate_query(user_input)
        return f"""Here's the SPL query you requested:

```spl
{query}
```

**Explanation:** {explanation}

**Query Details:**
- Type: tstats + TERM (optimized for performance)
- Index: {intent.index or 'not specified'}
- Keywords: {', '.join(intent.keywords) if intent.keywords else 'default (error)'}
- Time range: {intent.time_range}

This query uses TERM() for exact literal string matching, which provides 10-100x better performance than wildcard searches."""
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Template engine failed: {e}, falling back to LLM")
        return None
