#!/usr/bin/env python3
"""
ObsAI CLI — Query ObsAI from the terminal.

Usage:
  obsai ask "What is Splunk?"
  obsai search "tstats" --collection spl_commands_mxbai
  obsai config show
  obsai config versions
  obsai config rollback <commit_id>
  obsai costs [--hours 24]
  obsai health
  obsai skills [--family cognitive]
  obsai agents [--department engineering]
  obsai traces [--limit 10]
  obsai prompt list
  obsai prompt test "What is SPL?"
  obsai analytics taxonomy
  obsai analytics gaps
  obsai kg search "stats"
"""
import argparse
import json
import os
import sys
import time
from typing import Optional

try:
    import httpx
except ImportError:
    print("Error: httpx is required. Install with: pip install httpx")
    sys.exit(1)

# Configuration
DEFAULT_URL = os.environ.get("OBSAI_URL", "http://localhost:8000")
API_KEY = os.environ.get("OBSAI_API_KEY", "")

def get_client():
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    return httpx.Client(base_url=f"{DEFAULT_URL}/api/admin", headers=headers, timeout=120.0)

def cmd_ask(args):
    """Ask ObsAI a question."""
    # Use MCP server tool-call endpoint
    client = get_client()
    resp = client.post("/mcp/server/tool-call", json={
        "tool_name": "obsai_ask",
        "arguments": {"question": args.question}
    })
    data = resp.json()
    result = data.get("result", data)
    print(result.get("answer", json.dumps(result, indent=2)))

def cmd_search(args):
    """Search the knowledge base."""
    client = get_client()
    body = {"query": args.query, "k": args.k}
    if args.collection:
        body["collections"] = [args.collection]
    resp = client.post("/collections/search", json=body)
    data = resp.json()
    results = data.get("results", data.get("chunks", []))
    if not results:
        print("No results found.")
        return
    for i, r in enumerate(results, 1):
        text = r.get("text", r.get("page_content", ""))[:200]
        source = r.get("source", r.get("metadata", {}).get("source", "unknown"))
        score = r.get("score", r.get("distance", 0))
        print(f"\n--- Result {i} (score: {score:.2f}) ---")
        print(f"Source: {source}")
        print(text)

def cmd_health(args):
    """Check system health."""
    client = get_client()
    resp = client.get("/dashboard")
    data = resp.json()
    health = data.get("health", {})
    resources = data.get("resources", {})
    print(f"Overall: {health.get('overall', 'unknown')}")
    for svc in health.get("services", []):
        status = svc.get("status", "?")
        latency = svc.get("latency_ms", 0)
        print(f"  {svc['name']:20s} {status:10s} {latency:.0f}ms")
    print(f"\nCPU: {resources.get('cpu_pct', 0):.0f}%  MEM: {resources.get('memory_pct', 0):.0f}%  DISK: {resources.get('disk_pct', 0):.0f}%")

def cmd_costs(args):
    """Show cost summary."""
    client = get_client()
    resp = client.get(f"/costs?hours={args.hours}")
    data = resp.json()
    print(f"Cost Summary ({args.hours}h)")
    print(f"  Total: ${data.get('total_usd', 0):.4f}")
    print(f"  Calls: {data.get('total_calls', 0)}")
    print(f"  Avg/query: ${data.get('avg_cost_per_query', 0):.6f}")
    by_model = data.get("by_model", {})
    if by_model:
        print("  By model:")
        for m, c in by_model.items():
            print(f"    {m}: ${c:.4f}")

def cmd_config_show(args):
    """Show current config."""
    client = get_client()
    resp = client.get("/settings")
    data = resp.json()
    if args.section:
        sections = data.get("sections", data)
        section_data = sections.get(args.section, {})
        print(json.dumps(section_data, indent=2))
    else:
        sections = data.get("sections", data)
        for name in sorted(sections.keys()):
            print(f"  {name}")

def cmd_config_versions(args):
    """Show config version history."""
    client = get_client()
    resp = client.get(f"/config/versions?limit={args.limit}")
    data = resp.json()
    for commit in data.get("commits", data.get("history", [])):
        cid = commit.get("id", "?")[:8]
        section = commit.get("section", "?")
        msg = commit.get("message", "")
        author = commit.get("author", "?")
        ts = commit.get("timestamp", "")[:19]
        print(f"  {cid}  {ts}  [{section}]  {msg}  by {author}")

def cmd_traces(args):
    """Show recent traces."""
    client = get_client()
    resp = client.get(f"/otel/traces?limit={args.limit}")
    data = resp.json()
    for trace in data.get("traces", []):
        tid = trace.get("trace_id", "?")[:12]
        root = trace.get("root_name", "?")
        dur = trace.get("duration_ms", 0)
        spans = trace.get("span_count", 0)
        print(f"  {tid}  {root:30s}  {dur:.0f}ms  {spans} spans")

def cmd_skills(args):
    """List skills."""
    client = get_client()
    resp = client.get("/skills")
    data = resp.json()
    skills = data.get("skills", [])
    if args.family:
        skills = [s for s in skills if s.get("family") == args.family]
    for s in skills:
        name = s.get("name", "?")
        family = s.get("family", "?")
        status = s.get("status", "?")
        print(f"  {name:30s}  {family:15s}  {status}")
    print(f"\nTotal: {len(skills)} skills")

def cmd_agents(args):
    """List agents."""
    client = get_client()
    resp = client.get("/agents")
    data = resp.json()
    agents = data.get("agents", [])
    if args.department:
        agents = [a for a in agents if a.get("department") == args.department]
    for a in agents:
        name = a.get("name", "?")
        dept = a.get("department", "?")
        print(f"  {name:30s}  {dept}")
    print(f"\nTotal: {len(agents)} agents")

def cmd_analytics(args):
    """Show analytics."""
    client = get_client()
    if args.subcommand == "taxonomy":
        resp = client.get("/analytics/taxonomy")
        data = resp.json()
        print(f"Total queries: {data.get('total_queries', 0)}")
        print(f"Avg confidence: {data.get('avg_confidence', 0):.0%}")
        print(f"Avg quality: {data.get('avg_quality', 0):.0%}")
        for intent, count in data.get("by_intent", {}).items():
            print(f"  {intent:30s}  {count}")
    elif args.subcommand == "gaps":
        resp = client.get("/analytics/gaps")
        data = resp.json()
        gaps = data.get("gaps", data)
        if isinstance(gaps, list):
            for g in gaps:
                print(f"  [{g.get('occurrences',0)}x]  {g.get('pattern','?')[:80]}")
        else:
            print(json.dumps(data, indent=2))
    elif args.subcommand == "adoption":
        resp = client.get("/analytics/adoption")
        data = resp.json()
        print(f"Active today: {data.get('today_active', 0)}")
        print(f"Active 7d: {data.get('7d_active', 0)}")
        print(f"Active 30d: {data.get('30d_active', 0)}")
        print(f"Total queries: {data.get('total_queries', 0)}")
    elif args.subcommand == "roi":
        resp = client.get("/analytics/roi")
        data = resp.json()
        print(f"Total queries: {data.get('total_queries', 0)}")
        print(f"Automated: {data.get('automated_queries', 0)} ({data.get('automation_rate', 0):.0%})")
        print(f"Time saved: {data.get('estimated_time_saved_hours', 0):.1f} hours")

def cmd_kg(args):
    """Knowledge graph queries."""
    client = get_client()
    if args.subcommand == "search":
        resp = client.post("/mcp/server/tool-call", json={
            "tool_name": "obsai_kg_query",
            "arguments": {"entity": args.entity}
        })
        data = resp.json()
        result = data.get("result", data)
        print(result.get("context", json.dumps(result, indent=2)))
    elif args.subcommand == "stats":
        resp = client.get("/knowledge-graph/stats")
        data = resp.json()
        print(f"Entities: {data.get('total_entities', 0)}")
        print(f"Relationships: {data.get('total_relationships', 0)}")
        for etype, count in data.get("entity_type_counts", {}).items():
            print(f"  {etype:20s}  {count}")

def _apply_globals(url, api_key):
    global DEFAULT_URL, API_KEY
    if url:
        DEFAULT_URL = url
    if api_key:
        API_KEY = api_key

def main():
    parser = argparse.ArgumentParser(prog="obsai", description="ObsAI CLI")
    parser.add_argument("--url", default=DEFAULT_URL, help="ObsAI server URL")
    parser.add_argument("--api-key", default=API_KEY, help="API key")

    sub = parser.add_subparsers(dest="command")

    # ask
    p = sub.add_parser("ask", help="Ask a question")
    p.add_argument("question", help="Question to ask")

    # search
    p = sub.add_parser("search", help="Search knowledge base")
    p.add_argument("query", help="Search query")
    p.add_argument("--collection", "-c", help="Collection to search")
    p.add_argument("--k", type=int, default=5, help="Number of results")

    # health
    sub.add_parser("health", help="Check system health")

    # costs
    p = sub.add_parser("costs", help="Show cost summary")
    p.add_argument("--hours", type=int, default=24, help="Hours to look back")

    # config
    p = sub.add_parser("config", help="Configuration management")
    config_sub = p.add_subparsers(dest="config_cmd")
    cs = config_sub.add_parser("show", help="Show config")
    cs.add_argument("--section", help="Specific section")
    cv = config_sub.add_parser("versions", help="Version history")
    cv.add_argument("--limit", type=int, default=20)

    # traces
    p = sub.add_parser("traces", help="Show recent traces")
    p.add_argument("--limit", type=int, default=10)

    # skills
    p = sub.add_parser("skills", help="List skills")
    p.add_argument("--family", help="Filter by family")

    # agents
    p = sub.add_parser("agents", help="List agents")
    p.add_argument("--department", help="Filter by department")

    # analytics
    p = sub.add_parser("analytics", help="Analytics & BI")
    p.add_argument("subcommand", choices=["taxonomy", "gaps", "adoption", "roi"])

    # kg
    p = sub.add_parser("kg", help="Knowledge graph")
    p.add_argument("subcommand", choices=["search", "stats"])
    p.add_argument("entity", nargs="?", default="")

    args = parser.parse_args()
    _apply_globals(args.url, args.api_key)

    if not args.command:
        parser.print_help()
        return

    try:
        if args.command == "ask": cmd_ask(args)
        elif args.command == "search": cmd_search(args)
        elif args.command == "health": cmd_health(args)
        elif args.command == "costs": cmd_costs(args)
        elif args.command == "config":
            if args.config_cmd == "show": cmd_config_show(args)
            elif args.config_cmd == "versions": cmd_config_versions(args)
            else: print("Usage: obsai config {show|versions}")
        elif args.command == "traces": cmd_traces(args)
        elif args.command == "skills": cmd_skills(args)
        elif args.command == "agents": cmd_agents(args)
        elif args.command == "analytics": cmd_analytics(args)
        elif args.command == "kg": cmd_kg(args)
    except httpx.ConnectError:
        print(f"Error: Cannot connect to ObsAI at {DEFAULT_URL}")
        print("Make sure the server is running and the URL is correct.")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"Error: HTTP {e.response.status_code}")
        print(e.response.text[:300])
        sys.exit(1)

if __name__ == "__main__":
    main()
