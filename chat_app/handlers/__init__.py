"""Handler modules — extracted from skill_executor.py for modularity.

Each module exports a HANDLERS dict mapping handler_key -> function.
The skill_executor imports and merges all HANDLERS dicts at startup.

Handler signature: def handler(user_input: str = "", **kwargs) -> str
"""


def get_all_handlers() -> dict:
    """Collect handlers from all submodules."""
    handlers = {}
    from chat_app.handlers import cognitive_handlers
    from chat_app.handlers import skill_handlers
    from chat_app.handlers import scripting_handlers
    from chat_app.handlers import meta_handlers
    from chat_app.handlers import utility_handlers
    from chat_app.handlers import infra_handlers
    handlers.update(cognitive_handlers.HANDLERS)
    handlers.update(skill_handlers.HANDLERS)
    handlers.update(scripting_handlers.HANDLERS)
    handlers.update(meta_handlers.HANDLERS)
    handlers.update(utility_handlers.HANDLERS)
    handlers.update(infra_handlers.HANDLERS)
    return handlers
