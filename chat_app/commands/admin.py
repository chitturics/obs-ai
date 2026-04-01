"""
/admin command handler - Quick access to admin console and config management.
"""
import chainlit as cl


async def admin_command(args: str = ""):
    """Open admin console or show config editing guidance."""
    sub = args.strip().lower() if args else ""

    if sub in ("config", "yaml", "config.yaml", "settings"):
        await cl.Message(content="""**Config.yaml Editing**

The full `config.yaml` is editable via the **Admin Console**:

1. Click [Admin Console](/api/admin/v2/) (opens in new tab)
2. Navigate to the **config.yaml Editor** section in the sidebar
3. Select a section (retrieval, prompts, security, etc.)
4. Edit values inline and save -- changes apply immediately for hot-reload sections

**Hot-reload sections** (no restart needed):
`ingestion`, `retrieval`, `prompts`, `security`, `features`, `organization`, `sharepoint`, `github`

**App-restart sections:**
`active_profile`, `profiles`, `directories`, `ui`, `mcp_gateway`

**Full-restart sections:**
`database`

You can also use:
- `/config` -- View/change session settings (temporary, per-chat)
- `/config search_depth=10` -- Quick session setting change
- `PATCH /api/admin/config/section/{section}` -- REST API for automation""").send()

    elif sub in ("docs", "documentation", "help"):
        await cl.Message(content="""**Documentation**

Open the full documentation page: [Documentation](/api/admin/v2/)

Sections include: Getting Started, Profiles, Commands, Settings, Ingestion, Feedback, Admin Console, Users, Containers, Architecture, RAG Pipeline, Self-Learning, Workflows, API Reference, Troubleshooting, and Configuration.""").send()

    elif sub in ("users", "user"):
        await cl.Message(content="""**User Management**

Manage users in the Admin Console: [Admin Console](/api/admin/v2/)

Navigate to the **Users** section to:
- View all registered users
- Update roles (admin/user)
- Check login history
- Manage user sessions""").send()

    else:
        await cl.Message(content="""**Admin Quick Links**

| Link | Description |
|------|-------------|
| [Admin Console](/api/admin/v2/) | Full admin dashboard, config editor, user management |
| [Documentation](/api/admin/v2/) | Complete documentation with all features |
| [Health API](/api/health/stats) | JSON health status |
| [Metrics](/api/metrics/internal) | Internal metrics |

**Sub-commands:**
- `/admin config` -- Config.yaml editing guide
- `/admin docs` -- Documentation links
- `/admin users` -- User management

**Note:** The gear icon (Settings) in the chat adjusts *session-level* settings only. For persistent **config.yaml** changes, use the [Admin Console](/api/admin/v2/).""").send()
