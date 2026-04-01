"""
/search command handler.
"""
import logging

import chainlit as cl
from vectorstore import search_similar_chunks

logger = logging.getLogger(__name__)


async def search_command(query: str, *, vector_store=None):
    """Direct search command."""
    if not query:
        await cl.Message(
            content="Missing query\n\n**Usage:** `/search <query>`"
        ).send()
        return

    msg = cl.Message(content=f"**Searching for:** {query}\n\n")
    await msg.send()

    try:
        results = await cl.make_async(search_similar_chunks)(vector_store, query, k=15)

        if not results:
            msg.content += "No results found.\n"
            await msg.update()
            return

        msg.content += f"Found **{len(results)}** results:\n\n"

        for i, result in enumerate(results[:5], 1):
            source = result.get('source', 'Unknown')
            text_preview = result.get('text', '')[:150].replace('\n', ' ') + "..."
            msg.content += f"**{i}.** `{source}`\n   {text_preview}\n\n"

        if len(results) > 5:
            msg.content += f"\n_...and {len(results) - 5} more results_\n"

        # Add knowledge graph context if available
        try:
            from chat_app.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            if kg:
                kg_context = kg.generate_context_for_query(query, "general")
                if kg_context:
                    msg.content += f"\n---\n**Knowledge Graph Context:**\n{kg_context}\n"
        except Exception:
            pass  # KG is optional enhancement

    except Exception as e:
        msg.content += f"**Search failed:** {str(e)}\n"
        logger.error(f"Search command failed: {e}")

    await msg.update()
