"""
/tutorial — Interactive tutorial for learning how to use ObsAI.

Walks users through the key features with hands-on examples.
"""
import chainlit as cl


_TUTORIALS = {
    "basics": {
        "title": "Getting Started",
        "steps": [
            ("Welcome", "ObsAI is your AI assistant for Splunk, Cribl, and Observability. Let's walk through the basics."),
            ("Ask a question", 'Try asking a natural language question like:\n\n> "How do I use the stats command to count events by host?"'),
            ("Use profiles", "Switch profiles using the dropdown at the top of the chat:\n\n"
             "- **General** -- Balanced across all knowledge\n"
             "- **SPL Expert** -- Optimized for writing and optimizing queries\n"
             "- **Config Helper** -- Best for `.conf` file questions\n"
             "- **Troubleshooter** -- Focused on error diagnosis\n"
             "- **Org Expert** -- Uses your organization-specific docs"),
            ("Settings", "Click the gear icon to adjust:\n\n"
             "- **Search Depth** -- How many results to retrieve\n"
             "- **Temperature** -- Lower for precise answers, higher for creative\n"
             "- **Response Style** -- Concise, detailed, or tutorial mode"),
            ("Done", "You're all set! Try asking your first question."),
        ],
    },
    "spl": {
        "title": "SPL Query Help",
        "steps": [
            ("SPL Generation", "Ask me to write SPL queries in natural language:\n\n"
             '> "Write a query to find failed login attempts in the last 24 hours"'),
            ("SPL Optimization", "Paste an existing query and ask me to optimize it:\n\n"
             '> "optimize this: index=main sourcetype=access_combined | stats count by status"'),
            ("Query Explanation", "Use `/explain` followed by SPL to get a breakdown:\n\n"
             "> /explain index=_internal | stats count by component | sort -count"),
            ("SPL Validation", "I check generated SPL for common issues:\n"
             "- Missing time ranges\n- Inefficient wildcard usage\n- Missing `index=` prefix\n- Command syntax errors"),
            ("Tips", "For best SPL results:\n"
             "- Mention the index and sourcetype if you know them\n"
             "- Specify the Splunk version in Settings if syntax matters\n"
             "- Use the **SPL Expert** profile for query-heavy sessions"),
        ],
    },
    "config": {
        "title": "Configuration Help",
        "steps": [
            ("Conf Files", "Ask about any Splunk `.conf` file:\n\n"
             '> "What are the key settings in inputs.conf for monitoring files?"'),
            ("Spec Lookup", "Use `/spec` to look up spec file details:\n\n"
             "> /spec inputs.conf\n> /spec transforms.conf LOOKUP"),
            ("Build Config", "Use `/build-config` to generate stanzas:\n\n"
             '> /build-config monitor stanza for /var/log/syslog with sourcetype=syslog'),
            ("Organization Configs", "If your org has custom configs loaded, switch to the **Org Expert** profile to get answers specific to your environment."),
        ],
    },
    "ingestion": {
        "title": "Knowledge Ingestion",
        "steps": [
            ("Inline Ingestion", "Feed me knowledge on the fly:\n\n"
             "- `read_url: https://docs.splunk.com/...` -- Ingest a web page\n"
             "- `read_file: /path/to/file.conf` -- Ingest a local file\n"
             '- `read_text: "your text here"` -- Ingest raw text'),
            ("File Upload", "Drag and drop files into the chat to ingest them. Supported formats:\n\n"
             "`.conf`, `.spec`, `.txt`, `.md`, `.json`, `.yaml`, `.pdf`"),
            ("Bulk Ingest", "Use `/ingest` for bulk operations:\n\n"
             "> /ingest scan -- Scan and ingest all docs in the documents directory"),
            ("Knowledge Gaps", "I'll tell you when I notice gaps in my knowledge and suggest what to ingest."),
        ],
    },
    "admin": {
        "title": "Admin & Configuration",
        "steps": [
            ("Admin Console", "Access the full admin configuration page at:\n\n"
             "[Admin Console](/api/admin/v2/)\n\n"
             "From there you can manage all settings, feature flags, profiles, and containers."),
            ("Container Management", "Start, stop, and rebuild containers from the admin console.\n\n"
             "You can also monitor container health and runtime info."),
            ("Feature Flags", "Toggle features like:\n- Query expansion\n- Reranking\n- Compound query detection\n- Response streaming"),
            ("Backup & Restore", "Export your config and restore from backups in the admin console."),
        ],
    },
}


async def tutorial_command(args: str = ""):
    """Handle the /tutorial command."""
    args = args.strip().lower()

    if not args or args == "list":
        tutorial_list = "\n".join(
            f"- `/tutorial {key}` -- {info['title']}"
            for key, info in _TUTORIALS.items()
        )
        await cl.Message(content=(
            "**Available Tutorials:**\n\n"
            f"{tutorial_list}\n\n"
            "Type `/tutorial <name>` to start one."
        )).send()
        return

    tutorial = _TUTORIALS.get(args)
    if not tutorial:
        await cl.Message(content=f"Unknown tutorial: `{args}`. Type `/tutorial` to see available tutorials.").send()
        return

    # Send tutorial steps as a single message
    parts = [f"**Tutorial: {tutorial['title']}**\n"]
    for i, (step_title, step_content) in enumerate(tutorial["steps"], 1):
        parts.append(f"### Step {i}: {step_title}\n{step_content}\n")

    await cl.Message(content="\n".join(parts)).send()
