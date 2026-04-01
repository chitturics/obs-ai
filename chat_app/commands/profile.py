"""
/profile command handler — shows profile info, agents, and skills.
"""
import logging
import chainlit as cl

logger = logging.getLogger(__name__)

PROFILE_INFO = {
    "general": {
        "name": "General Assistant",
        "icon": "robot-happy-outline",
        "desc": "All-purpose help with auto-detection. Routes your query to the best specialist automatically.",
        "tips": [
            "Ask anything -- I'll figure out the right approach",
            '"How do I use the stats command?" (auto-routes to SPL Expert)',
            '"Show my saved searches" (auto-routes to Org Expert)',
        ],
    },
    "spl_expert": {
        "name": "SPL Expert",
        "icon": "code-braces",
        "desc": "Deep mastery of 173+ SPL commands, query optimization, tstats, data models, and CIM.",
        "tips": [
            '"Optimize: index=main | stats count by host | sort -count"',
            '"When should I use tstats vs stats?"',
            '"Write a timechart for 404 errors by sourcetype"',
        ],
    },
    "config_helper": {
        "name": "Configuration Expert",
        "icon": "file-cog-outline",
        "desc": "Authoritative reference for .conf syntax, .spec file options, and stanza best practices.",
        "tips": [
            '"What are all the options for inputs.conf monitor stanzas?"',
            '"Explain the props.conf TRANSFORMS- setting"',
            '"Build a props.conf stanza for JSON parsing"',
        ],
    },
    "troubleshooter": {
        "name": "Troubleshooting Specialist",
        "icon": "bug-outline",
        "desc": "Systematic problem solver for ingestion, search, indexer, parsing, and permission issues.",
        "tips": [
            '"My forwarder is not sending data to the indexer"',
            '"Searches are timing out on the search head"',
            '"Events are not being parsed correctly for sourcetype X"',
        ],
    },
    "org_expert": {
        "name": "Organization Expert",
        "icon": "office-building-cog-outline",
        "desc": "Deep knowledge of YOUR Splunk deployment: apps, saved searches, inputs, and configs from your repo.",
        "tips": [
            '"Show my saved searches in org-search"',
            '"What inputs.conf stanzas do we have?"',
            '"Explain our TA-nmap configuration"',
        ],
    },
    "cribl_expert": {
        "name": "Cribl Expert",
        "icon": "pipe",
        "desc": "Data pipeline architect for Cribl Stream, Edge, Search, and Lake: routes, pipelines, and packs.",
        "tips": [
            '"How do I reduce Splunk license cost with Cribl?"',
            '"Create a pipeline to mask PII in syslog events"',
            '"Route data to both Splunk and S3"',
        ],
    },
    "observability_expert": {
        "name": "Observability Engineer",
        "icon": "chart-timeline-variant-shimmer",
        "desc": "Full-stack observability: Splunk metrics, OpenTelemetry, tracing, SLI/SLO, and monitoring.",
        "tips": [
            '"Write an mstats query for CPU utilization by host"',
            '"How do I correlate traces with logs in Splunk?"',
            '"Set up SLO-based alerting with error budgets"',
        ],
    },
}


async def profile_command():
    """Show current profile with tips and all available profiles."""
    profile = cl.user_session.get("chat_profile", "general")
    info = PROFILE_INFO.get(profile, PROFILE_INFO["general"])

    lines = [
        f"### Current Profile: {info['name']}",
        f"_{info['desc']}_",
        "",
        "**Try asking:**",
    ]
    for tip in info["tips"]:
        lines.append(f"- {tip}")

    lines.append("")
    lines.append("---")
    lines.append("### All Available Profiles")
    lines.append("")
    for key, pinfo in PROFILE_INFO.items():
        marker = " **(active)**" if key == profile else ""
        lines.append(f"- **{pinfo['name']}**{marker} -- {pinfo['desc']}")

    # Show agents and skills for this profile
    try:
        from chat_app.agent_catalog import AgentCatalog, Department
        catalog = AgentCatalog()
        # Map profiles to departments
        profile_dept_map = {
            "general": None,
            "spl_expert": Department.ENGINEERING,
            "config_helper": Department.INFRASTRUCTURE,
            "troubleshooter": Department.OPERATIONS,
            "org_expert": Department.KNOWLEDGE,
            "cribl_expert": Department.DATA,
            "observability_expert": Department.OPERATIONS,
        }
        dept = profile_dept_map.get(profile)
        if dept:
            agents = catalog.get_department(dept)
            if agents:
                lines.append("")
                lines.append(f"### Assigned Agents ({len(agents)})")
                for agent in agents[:6]:
                    lines.append(f"- **{agent.role}** (`{agent.name}`) — {agent.description[:60]}")
    except Exception:
        pass

    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        # Map profiles to intent patterns for skill lookup
        profile_intents = {
            "spl_expert": ["spl_query", "spl_explain", "spl_optimize"],
            "config_helper": ["config_help", "build_config"],
            "troubleshooter": ["troubleshoot", "diagnose"],
            "org_expert": ["org_knowledge"],
            "cribl_expert": ["cribl_help"],
            "observability_expert": ["metrics_query", "monitoring"],
        }
        intents = profile_intents.get(profile, [])
        if intents:
            skill_names = set()
            for intent in intents:
                for s in executor.get_skills_for_intent(intent):
                    skill_names.add(s["name"])
            if skill_names:
                lines.append(f"\n### Available Skills ({len(skill_names)})")
                lines.append(f"{', '.join(f'`{s}`' for s in sorted(skill_names)[:10])}")
    except Exception:
        pass

    lines.append("")
    lines.append("_Switch profiles by clicking your avatar in the chat header, or set `chat_profile` in the settings panel._")

    await cl.Message(content="\n".join(lines)).send()
