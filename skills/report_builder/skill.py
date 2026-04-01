"""
Report Builder Skill — Design dashboards, generate SimpleXML panels,
suggest visualizations, and schedule reports.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Visualization mapping rules
# ---------------------------------------------------------------------------

_VIZ_RULES: List[Dict[str, Any]] = [
    {
        "keywords": ["over time", "trend", "timeline", "timechart", "time series"],
        "viz_type": "line",
        "description": "Line chart for time-series data showing trends over time",
        "simplexml_type": "chart",
        "charting_type": "line",
    },
    {
        "keywords": ["distribution", "histogram", "spread", "range"],
        "viz_type": "bar",
        "description": "Bar chart for showing distribution across categories",
        "simplexml_type": "chart",
        "charting_type": "bar",
    },
    {
        "keywords": ["top", "most common", "rank", "leaderboard", "comparison"],
        "viz_type": "column",
        "description": "Column chart for ranking and comparison",
        "simplexml_type": "chart",
        "charting_type": "column",
    },
    {
        "keywords": ["proportion", "percentage", "share", "breakdown", "composition"],
        "viz_type": "pie",
        "description": "Pie chart for showing proportional breakdown",
        "simplexml_type": "chart",
        "charting_type": "pie",
    },
    {
        "keywords": ["single value", "kpi", "count", "total", "average", "metric"],
        "viz_type": "single",
        "description": "Single value display for KPIs and key metrics",
        "simplexml_type": "single",
        "charting_type": None,
    },
    {
        "keywords": ["map", "geo", "location", "country", "region", "geography"],
        "viz_type": "map",
        "description": "Choropleth or cluster map for geographic data",
        "simplexml_type": "map",
        "charting_type": None,
    },
    {
        "keywords": ["table", "list", "detail", "raw", "events", "log"],
        "viz_type": "table",
        "description": "Table for detailed tabular data display",
        "simplexml_type": "table",
        "charting_type": None,
    },
    {
        "keywords": ["scatter", "correlation", "relationship", "xy"],
        "viz_type": "scatter",
        "description": "Scatter plot for showing correlation between two variables",
        "simplexml_type": "chart",
        "charting_type": "scatter",
    },
    {
        "keywords": ["area", "stacked", "cumulative", "volume"],
        "viz_type": "area",
        "description": "Area chart for showing volume or cumulative values over time",
        "simplexml_type": "chart",
        "charting_type": "area",
    },
    {
        "keywords": ["gauge", "threshold", "level", "capacity", "utilization"],
        "viz_type": "gauge",
        "description": "Gauge chart for showing values against thresholds",
        "simplexml_type": "chart",
        "charting_type": "radialGauge",
    },
]

# ---------------------------------------------------------------------------
# Panel type templates
# ---------------------------------------------------------------------------

_PANEL_TEMPLATES: Dict[str, str] = {
    "table": """    <panel>
      <title>{title}</title>
      <table>
        <search>
          <query>{query}</query>
          <earliest>{earliest}</earliest>
          <latest>{latest}</latest>
        </search>
        <option name="count">20</option>
        <option name="drilldown">row</option>
        <option name="wrap">true</option>
      </table>
    </panel>""",

    "chart": """    <panel>
      <title>{title}</title>
      <chart>
        <search>
          <query>{query}</query>
          <earliest>{earliest}</earliest>
          <latest>{latest}</latest>
        </search>
        <option name="charting.chart">{chart_type}</option>
        <option name="charting.drilldown">all</option>
        <option name="charting.legend.placement">bottom</option>
      </chart>
    </panel>""",

    "single": """    <panel>
      <title>{title}</title>
      <single>
        <search>
          <query>{query}</query>
          <earliest>{earliest}</earliest>
          <latest>{latest}</latest>
        </search>
        <option name="drilldown">none</option>
        <option name="colorMode">block</option>
        <option name="useColors">true</option>
      </single>
    </panel>""",

    "map": """    <panel>
      <title>{title}</title>
      <map>
        <search>
          <query>{query}</query>
          <earliest>{earliest}</earliest>
          <latest>{latest}</latest>
        </search>
        <option name="mapping.type">choropleth</option>
        <option name="drilldown">all</option>
      </map>
    </panel>""",

    "event": """    <panel>
      <title>{title}</title>
      <event>
        <search>
          <query>{query}</query>
          <earliest>{earliest}</earliest>
          <latest>{latest}</latest>
        </search>
        <option name="count">20</option>
        <option name="list.drilldown">full</option>
      </event>
    </panel>""",
}

# ---------------------------------------------------------------------------
# Dashboard component catalog
# ---------------------------------------------------------------------------

_DASHBOARD_COMPONENTS: Dict[str, Dict[str, Any]] = {
    "login_stats": {
        "title": "Login Statistics",
        "query": 'index=security sourcetype=*auth* | stats count by action | sort -count',
        "viz": "pie",
    },
    "failed_logins": {
        "title": "Failed Logins Over Time",
        "query": 'index=security sourcetype=*auth* action=failure | timechart count',
        "viz": "line",
    },
    "top_users": {
        "title": "Top Users",
        "query": 'index=security sourcetype=*auth* | top limit=10 user',
        "viz": "column",
    },
    "threat_map": {
        "title": "Threat Geography",
        "query": 'index=security | iplocation src | geostats count by Country',
        "viz": "map",
    },
    "alert_table": {
        "title": "Recent Alerts",
        "query": 'index=notable | table _time, rule_name, severity, src, dest, user | sort -_time',
        "viz": "table",
    },
    "error_rate": {
        "title": "Error Rate",
        "query": 'index=* log_level=ERROR | timechart count as errors',
        "viz": "line",
    },
    "kpi_events": {
        "title": "Total Events",
        "query": 'index=* | stats count',
        "viz": "single",
    },
    "status_codes": {
        "title": "HTTP Status Codes",
        "query": 'index=web | stats count by status | sort -count',
        "viz": "pie",
    },
    "response_time": {
        "title": "Response Time",
        "query": 'index=web | timechart avg(response_time) as avg_response_ms',
        "viz": "line",
    },
    "data_volume": {
        "title": "Data Volume by Sourcetype",
        "query": 'index=_internal source=*metrics.log group=per_sourcetype_thruput | eval mb=kb/1024 | stats sum(mb) by series | sort -sum(mb)',
        "viz": "column",
    },
}

# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def design_dashboard(requirements: str, title: Optional[str] = None) -> str:
    """
    Design a dashboard layout from requirements.

    Args:
        requirements: Description of dashboard requirements.
        title: Optional dashboard title.

    Returns:
        JSON string with dashboard design specification.
    """
    if not requirements or not requirements.strip():
        return json.dumps({"status": "error", "error": "Requirements cannot be empty"})

    req_lower = requirements.lower()
    dash_title = title or "Custom Dashboard"

    # Match components from requirements
    matched_panels = []
    for comp_key, comp_info in _DASHBOARD_COMPONENTS.items():
        # Check if component keywords appear in requirements
        keywords = comp_key.replace("_", " ").split()
        if any(kw in req_lower for kw in keywords):
            matched_panels.append({
                "id": comp_key,
                "title": comp_info["title"],
                "query": comp_info["query"],
                "visualization": comp_info["viz"],
            })

    # If no matches, suggest a general layout
    if not matched_panels:
        matched_panels = [
            {"id": "kpi_events", "title": "Total Events", "query": _DASHBOARD_COMPONENTS["kpi_events"]["query"], "visualization": "single"},
            {"id": "error_rate", "title": "Error Rate", "query": _DASHBOARD_COMPONENTS["error_rate"]["query"], "visualization": "line"},
            {"id": "data_volume", "title": "Data Volume", "query": _DASHBOARD_COMPONENTS["data_volume"]["query"], "visualization": "column"},
        ]

    # Arrange into rows (2-3 panels per row)
    rows = []
    current_row = []
    for panel in matched_panels:
        current_row.append(panel)
        if len(current_row) >= 3 or (panel["visualization"] == "single" and len(current_row) >= 4):
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    # Generate SimpleXML skeleton
    xml_lines = [
        f'<dashboard>',
        f'  <label>{dash_title}</label>',
        f'  <description>Auto-generated dashboard</description>',
    ]
    for row in rows:
        xml_lines.append('  <row>')
        for panel in row:
            template = _PANEL_TEMPLATES.get(panel["visualization"], _PANEL_TEMPLATES["table"])
            chart_type = "line"
            for rule in _VIZ_RULES:
                if rule["viz_type"] == panel["visualization"]:
                    chart_type = rule.get("charting_type") or "line"
                    break
            xml_lines.append(template.format(
                title=panel["title"],
                query=panel["query"],
                earliest="-24h@h",
                latest="now",
                chart_type=chart_type,
            ))
        xml_lines.append('  </row>')
    xml_lines.append('</dashboard>')

    return json.dumps({
        "status": "ok",
        "title": dash_title,
        "panel_count": len(matched_panels),
        "row_count": len(rows),
        "panels": matched_panels,
        "layout": rows,
        "simplexml": "\n".join(xml_lines),
    }, indent=2)


def generate_panel(query: str, title: str, viz_type: Optional[str] = None) -> str:
    """
    Generate a SimpleXML dashboard panel definition.

    Args:
        query: SPL query for the panel.
        title: Panel title.
        viz_type: Optional visualization type.

    Returns:
        JSON string with panel SimpleXML.
    """
    if not query or not query.strip():
        return json.dumps({"status": "error", "error": "Query cannot be empty"})
    if not title or not title.strip():
        return json.dumps({"status": "error", "error": "Title cannot be empty"})

    # Auto-detect viz type if not specified
    if not viz_type:
        query_lower = query.lower()
        if "timechart" in query_lower:
            viz_type = "chart"
            chart_type = "line"
        elif "stats count" in query_lower and "by" not in query_lower:
            viz_type = "single"
            chart_type = None
        elif "top" in query_lower or "chart" in query_lower:
            viz_type = "chart"
            chart_type = "column"
        elif "table" in query_lower:
            viz_type = "table"
            chart_type = None
        elif "geostats" in query_lower or "iplocation" in query_lower:
            viz_type = "map"
            chart_type = None
        else:
            viz_type = "table"
            chart_type = None
    else:
        viz_type = viz_type.lower()
        if viz_type == "timechart":
            viz_type = "chart"
            chart_type = "line"
        elif viz_type in ("chart", "line", "bar", "column", "pie", "area", "scatter"):
            chart_type = viz_type if viz_type != "chart" else "line"
            viz_type = "chart"
        else:
            chart_type = None

    template_key = viz_type if viz_type in _PANEL_TEMPLATES else "table"
    template = _PANEL_TEMPLATES[template_key]

    panel_xml = template.format(
        title=title,
        query=query,
        earliest="-24h@h",
        latest="now",
        chart_type=chart_type or "line",
    )

    return json.dumps({
        "status": "ok",
        "title": title,
        "visualization": viz_type,
        "chart_type": chart_type,
        "simplexml": panel_xml,
    }, indent=2)


def suggest_visualizations(data_description: str) -> str:
    """
    Suggest the best visualization type for given data.

    Args:
        data_description: Description of the data characteristics.

    Returns:
        JSON string with visualization suggestions.
    """
    if not data_description or not data_description.strip():
        return json.dumps({"status": "error", "error": "Data description cannot be empty"})

    desc_lower = data_description.lower()
    suggestions = []

    for rule in _VIZ_RULES:
        score = 0
        matched_keywords = []
        for keyword in rule["keywords"]:
            if keyword in desc_lower:
                score += 1
                matched_keywords.append(keyword)
        if score > 0:
            suggestions.append({
                "viz_type": rule["viz_type"],
                "description": rule["description"],
                "simplexml_type": rule["simplexml_type"],
                "charting_type": rule.get("charting_type"),
                "match_score": score,
                "matched_keywords": matched_keywords,
            })

    # Sort by match score
    suggestions.sort(key=lambda x: x["match_score"], reverse=True)

    if not suggestions:
        # Default suggestion
        suggestions = [{
            "viz_type": "table",
            "description": "Table is a safe default for any data type",
            "simplexml_type": "table",
            "charting_type": None,
            "match_score": 0,
            "matched_keywords": [],
        }]

    return json.dumps({
        "status": "ok",
        "data_description": data_description,
        "primary_suggestion": suggestions[0] if suggestions else None,
        "all_suggestions": suggestions,
        "tips": [
            "Use line charts for time-series data with trends",
            "Use bar/column charts for categorical comparisons",
            "Use pie charts only when showing parts of a whole (5 or fewer categories)",
            "Use single value for KPIs and summary metrics",
            "Use tables for detailed drill-down views",
        ],
    }, indent=2)


def schedule_report(query: str, name: str, schedule: str,
                    alert_email: Optional[str] = None) -> str:
    """
    Generate saved search config for scheduled reports.

    Args:
        query: SPL query for the report.
        name: Name for the saved search.
        schedule: Cron schedule expression.
        alert_email: Optional email for report delivery.

    Returns:
        JSON string with savedsearches.conf configuration.
    """
    if not query or not query.strip():
        return json.dumps({"status": "error", "error": "Query cannot be empty"})
    if not name or not name.strip():
        return json.dumps({"status": "error", "error": "Report name cannot be empty"})
    if not schedule or not schedule.strip():
        return json.dumps({"status": "error", "error": "Schedule cannot be empty"})

    # Validate cron format (basic check)
    cron_parts = schedule.strip().split()
    if len(cron_parts) != 5:
        return json.dumps({
            "status": "error",
            "error": f"Invalid cron schedule: expected 5 fields, got {len(cron_parts)}",
            "hint": "Format: minute hour day_of_month month day_of_week (e.g., '0 6 * * *')",
        })

    conf_lines = [
        f'[{name}]',
        f'search = {query}',
        f'cron_schedule = {schedule}',
        'enableSched = 1',
        'is_scheduled = 1',
        'dispatch.earliest_time = -24h@h',
        'dispatch.latest_time = now',
        'max_concurrent = 1',
    ]

    if alert_email:
        conf_lines.extend([
            'action.email = 1',
            f'action.email.to = {alert_email}',
            f'action.email.subject = Scheduled Report: {name}',
            'action.email.format = table',
            'action.email.inline = 1',
            'action.email.sendresults = 1',
        ])

    return json.dumps({
        "status": "ok",
        "name": name,
        "schedule": schedule,
        "email": alert_email,
        "savedsearches_conf": "\n".join(conf_lines),
        "notes": [
            "Place in $SPLUNK_HOME/etc/apps/<app>/local/savedsearches.conf",
            "Verify the cron schedule matches your intended frequency",
            "Ensure the search user has appropriate permissions",
            "Monitor via Settings > Searches, reports, and alerts",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("report_builder skill cleaned up")
