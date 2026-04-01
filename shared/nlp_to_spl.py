"""
NLP to SPL Generator - Convert natural language to Splunk queries.

Uses the LLM with organization-specific examples for accurate query generation.
Learns from macros, saved searches, and user feedback to improve over time.

Usage:
    from nlp_to_spl import NLPtoSPL

    generator = NLPtoSPL()
    result = generator.generate("show me failed logins in the last hour")
    print(result.query)  # index=wineventlog EventCode=4625 earliest=-1h latest=now | stats count by user
"""

import os
import re
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import logging

from shared.spl_robust_analyzer import analyze_spl

from shared.spl_intents import SPLIntent, INTENT_TEMPLATES

logger = logging.getLogger(__name__)


@dataclass
class SPLGenerationResult:
    """Result of NLP to SPL generation."""
    query: str
    confidence: float  # 0.0 - 1.0
    explanation: str
    examples_used: List[str]  # Names of macros/searches used as examples
    intent: str  # Detected intent (aggregation, filter, alert, etc.)
    suggestions: List[str]  # Additional optimization suggestions


@dataclass
class QueryExample:
    """Example query for few-shot learning."""
    name: str
    description: str
    query: str
    intent: str
    source: str  # 'macro', 'savedsearch', 'feedback', 'builtin'
    rank: int = 0


class NLPtoSPL:
    """
    Natural Language to SPL Query Generator.

    Uses few-shot learning with organization-specific examples:
    - Macros from macros.conf
    - Saved searches from savedsearches.conf
    - Feedback Q&A pairs
    - Built-in example patterns
    """

    # Keywords with weights: (keyword, weight)
    # Multi-word phrases get higher weight to prioritize specific intents over generic ones
    INTENT_KEYWORDS = {
        # Generic intents (low weight - only win if nothing specific matches)
        SPLIntent.SEARCH_EVENTS: [("show", 1), ("find", 1), ("get", 1), ("list", 1), ("search", 1)],
        SPLIntent.STATS_BY_FIELD: [("group by", 3), ("per", 1)],  # "by" alone removed - too generic
        # Aggregation
        SPLIntent.COUNT_EVENTS: [("count", 2), ("how many", 3), ("number of", 3)],
        SPLIntent.TOP_VALUES: [("top ", 3), ("most common", 3), ("highest", 2)],
        SPLIntent.RARE_EVENTS: [("rare", 3), ("least common", 3), ("lowest", 2)],
        SPLIntent.TIMECHART: [("trend", 3), ("over time", 3), ("timechart", 3), ("timeline", 3)],
        # Security (high weight - specific domain)
        SPLIntent.FAILED_LOGINS: [("failed login", 5), ("login failure", 5), ("failed logon", 5),
                                   ("authentication failure", 5), ("failed auth", 5)],
        SPLIntent.BRUTE_FORCE_DETECTION: [("brute force", 5), ("password spray", 5), ("credential stuffing", 5)],
        SPLIntent.ANOMALY_DETECTION: [("anomaly", 4), ("outlier", 4), ("unusual", 3), ("abnormal", 3)],
        SPLIntent.DATA_EXFILTRATION: [("exfiltration", 5), ("data theft", 5), ("data leak", 5)],
        SPLIntent.PRIVILEGE_ESCALATION: [("privilege escalation", 5), ("admin access", 4), ("group change", 4)],
        # Troubleshooting
        SPLIntent.ERROR_ANALYSIS: [("error", 2), ("exception", 3), ("crash", 3)],
        SPLIntent.LATENCY_ANALYSIS: [("latency", 4), ("slow", 2), ("response time", 4), ("performance", 2)],
        SPLIntent.THROUGHPUT_METRICS: [("throughput", 4), ("per second", 3), ("events per", 3)],
        # Compliance
        SPLIntent.USER_ACTIVITY: [("user activity", 4), ("actions by user", 4), ("what did user", 4)],
        SPLIntent.ACCESS_AUDIT: [("access audit", 5), ("who accessed", 4), ("access log", 3)],
        SPLIntent.CHANGE_TRACKING: [("change tracking", 4), ("modified", 2), ("deleted", 2)],
        # Data pipeline
        SPLIntent.SOURCE_MONITORING: [("source monitoring", 4), ("data source", 3), ("ingestion", 3)],
        SPLIntent.INDEXING_PERFORMANCE: [("indexing performance", 5), ("indexer throughput", 5), ("index rate", 4)],
        SPLIntent.FORWARDER_HEALTH: [("forwarder health", 5), ("forwarder status", 5), ("forwarder", 3)],
        # Network
        SPLIntent.NETWORK_TRAFFIC: [("network traffic", 4), ("connections", 2), ("network", 2)],
        SPLIntent.FIREWALL_DENIES: [("firewall deny", 5), ("firewall denied", 5), ("firewall deni", 5),
                                     ("blocked by firewall", 5), ("firewall block", 5), ("firewall drop", 5),
                                     ("denied connection", 4), ("blocked connection", 4)],
        SPLIntent.VPN_CONNECTIONS: [("vpn connection", 5), ("vpn login", 5), ("vpn", 3)],
        SPLIntent.DNS_QUERIES: [("dns query", 5), ("dns lookup", 5), ("dns", 3), ("nxdomain", 4)],
        # Application
        SPLIntent.APP_ERRORS: [("application error", 4), ("app crash", 4), ("app error", 4)],
        SPLIntent.APP_TRANSACTIONS: [("transaction", 3), ("user flow", 4), ("user journey", 4)],
        SPLIntent.API_PERFORMANCE: [("api performance", 5), ("api latency", 5), ("api error", 4)],
    }

    # Built-in example patterns — covering aggregation, security, network, DNS, web, endpoint, cloud
    BUILTIN_EXAMPLES = [
        # ── Aggregation ──
        QueryExample(
            name="count_by_host",
            description="Count events by host",
            query="index=main earliest=-1h latest=now | stats count by host",
            intent="aggregation",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="top_users",
            description="Top users by event count",
            query="index=main earliest=-1h latest=now | stats count by user | sort -count | head 10",
            intent="aggregation",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="rare_sourcetypes",
            description="Rare or uncommon sourcetypes",
            query="index=* earliest=-24h latest=now | rare limit=20 sourcetype",
            intent="aggregation",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="tstats_count",
            description="Fast aggregation using tstats",
            query="| tstats count where index=network TERM(error) earliest=-1h latest=now by host",
            intent="aggregation",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="tstats_prefix_by",
            description="Fast tstats with PREFIX() BY clause for search-time fields",
            query='| tstats count where index=main TERM(error) earliest=-1h latest=now by PREFIX(action=) | rename "action=*" AS action | search action=error',
            intent="aggregation",
            source="builtin",
            rank=100,
        ),
        # ── Timechart ──
        QueryExample(
            name="error_trend",
            description="Error count over time",
            query="index=main TERM(error) earliest=-24h latest=now | timechart span=1h count by sourcetype",
            intent="timechart",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="login_trend",
            description="Login attempts over time by result",
            query="index=wineventlog EventCode=4625 OR EventCode=4624 earliest=-24h latest=now | timechart span=1h count by EventCode",
            intent="timechart",
            source="builtin",
            rank=100,
        ),
        # ── Authentication / Security ──
        QueryExample(
            name="failed_logins",
            description="Find failed login attempts",
            query="index=wineventlog EventCode=4625 earliest=-1h latest=now | stats count by user, src_ip",
            intent="authentication",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="successful_logins",
            description="Successful logins",
            query="index=wineventlog EventCode=4624 earliest=-1h latest=now | stats count by user, src_ip",
            intent="authentication",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="brute_force_detection",
            description="Detect brute force login attempts",
            query="index=wineventlog EventCode=4625 earliest=-1h latest=now | stats count by user, src_ip | where count > 5",
            intent="security",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="account_lockout",
            description="Account lockout events",
            query="index=wineventlog EventCode=4740 earliest=-24h latest=now | stats count by user, src_ip | sort -count",
            intent="authentication",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="privilege_escalation",
            description="Privilege escalation or admin group changes",
            query="index=wineventlog (EventCode=4728 OR EventCode=4732 OR EventCode=4756) earliest=-24h latest=now | table _time, user, MemberName, Group_Name",
            intent="security",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="auth_datamodel_tstats",
            description="Authentication failures using CIM data model",
            query="| tstats summariesonly=t count from datamodel=Authentication.Authentication where Authentication.action=failure earliest=-4h latest=now by Authentication.user, Authentication.src",
            intent="authentication",
            source="builtin",
            rank=100,
        ),
        # ── Network ──
        QueryExample(
            name="firewall_denied",
            description="Firewall denied connections",
            query="index=firewall TERM(action=denied) earliest=-4h latest=now | stats count by src_ip, dest_ip",
            intent="network",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="network_traffic_tstats",
            description="Network traffic using data model",
            query="| tstats summariesonly=t count from datamodel=Network_Traffic.All_Traffic where earliest=-4h latest=now by All_Traffic.src, All_Traffic.dest",
            intent="network",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="top_talkers",
            description="Top network talkers by bytes",
            query="| tstats summariesonly=t sum(All_Traffic.bytes) as total_bytes from datamodel=Network_Traffic.All_Traffic where earliest=-4h latest=now by All_Traffic.src | sort -total_bytes | head 10",
            intent="network",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="vpn_connections",
            description="VPN connection events",
            query="index=vpn earliest=-24h latest=now | stats count by user, src_ip, action | sort -count",
            intent="network",
            source="builtin",
            rank=100,
        ),
        # ── DNS ──
        QueryExample(
            name="dns_queries",
            description="DNS query activity by domain",
            query="index=dns earliest=-1h latest=now | stats count by query, query_type | sort -count | head 20",
            intent="dns",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="dns_nxdomain",
            description="DNS NXDOMAIN failures",
            query='index=dns TERM(reply_code=NXDOMAIN) earliest=-4h latest=now | stats count by query, src_ip | where count > 10 | sort -count',
            intent="dns",
            source="builtin",
            rank=100,
        ),
        # ── Web / Proxy ──
        QueryExample(
            name="http_errors",
            description="HTTP error responses",
            query="index=proxy status>=400 earliest=-4h latest=now | stats count by status, url | sort -count | head 20",
            intent="web",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="web_datamodel_tstats",
            description="Web traffic using CIM data model",
            query="| tstats summariesonly=t count from datamodel=Web.Web where earliest=-4h latest=now by Web.url, Web.status | sort -count",
            intent="web",
            source="builtin",
            rank=100,
        ),
        # ── Endpoint ──
        QueryExample(
            name="process_execution",
            description="Process execution events",
            query="index=edr earliest=-1h latest=now | stats count by process_name, user, dest | sort -count",
            intent="endpoint",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="powershell_activity",
            description="PowerShell execution activity",
            query='index=wineventlog sourcetype=WinEventLog:Microsoft-Windows-PowerShell/Operational earliest=-24h latest=now | stats count by user, host | sort -count',
            intent="endpoint",
            source="builtin",
            rank=100,
        ),
        # ── Cloud (AWS, Azure, GCP) ──
        QueryExample(
            name="aws_cloudtrail_errors",
            description="AWS CloudTrail API errors",
            query='index=aws sourcetype=aws:cloudtrail TERM(errorCode) earliest=-24h latest=now | stats count by errorCode, eventName, userIdentity.arn | sort -count',
            intent="security",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="azure_signin_failures",
            description="Azure AD sign-in failures",
            query='index=azure sourcetype=azure:aad:signin ResultType!=0 earliest=-24h latest=now | stats count by UserPrincipalName, IPAddress, ResultType | sort -count',
            intent="authentication",
            source="builtin",
            rank=100,
        ),
        # ── Data Exfiltration / DLP ──
        QueryExample(
            name="large_outbound_transfers",
            description="Large outbound data transfers (potential exfiltration)",
            query='| tstats summariesonly=t sum(All_Traffic.bytes_out) as bytes_out from datamodel=Network_Traffic.All_Traffic where All_Traffic.action=allowed earliest=-24h latest=now by All_Traffic.src | where bytes_out > 1073741824 | sort -bytes_out',
            intent="data_exfiltration",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="usb_device_usage",
            description="USB device insertions and removals",
            query='index=wineventlog (EventCode=6416 OR EventCode=6419 OR EventCode=6420) earliest=-24h latest=now | stats count by user, DeviceDescription, ClassName | sort -count',
            intent="data_exfiltration",
            source="builtin",
            rank=100,
        ),
        # ── Splunk Admin / Internal ──
        QueryExample(
            name="indexing_volume",
            description="Indexing volume per index over time",
            query='index=_internal sourcetype=splunkd group=per_index_thruput earliest=-24h latest=now | timechart span=1h sum(kb) as kb_indexed by series',
            intent="indexing_performance",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="forwarder_connections",
            description="Universal forwarder connection status",
            query='index=_internal sourcetype=splunkd group=tcpin_connections earliest=-15m latest=now | stats latest(connectionType) as type, latest(version) as version, latest(fwdType) as fwdType by hostname | sort hostname',
            intent="forwarder_health",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="search_activity",
            description="Search activity by user showing expensive searches",
            query='index=_audit action=search info=completed earliest=-4h latest=now | stats count, avg(total_run_time) as avg_runtime, max(total_run_time) as max_runtime by user | where avg_runtime > 30 | sort -avg_runtime',
            intent="user_activity",
            source="builtin",
            rank=100,
        ),
        QueryExample(
            name="license_usage",
            description="License usage by index",
            query='index=_internal sourcetype=splunkd group=license_usage earliest=-24h latest=now | stats sum(b) as bytes by idx | eval GB=round(bytes/1073741824,2) | sort -GB | table idx, GB',
            intent="source_monitoring",
            source="builtin",
            rank=100,
        ),
        # ── Change Tracking ──
        QueryExample(
            name="windows_audit_policy_changes",
            description="Windows audit policy changes",
            query='index=wineventlog (EventCode=4719 OR EventCode=4907) earliest=-24h latest=now | table _time, user, ObjectName, ObjectType, SubjectUserName | sort -_time',
            intent="change_tracking",
            source="builtin",
            rank=100,
        ),
        # ── Access Audit ──
        QueryExample(
            name="file_access_audit",
            description="File access audit events",
            query='index=wineventlog EventCode=4663 earliest=-24h latest=now | stats count by ObjectName, SubjectUserName, AccessMask | sort -count | head 50',
            intent="access_audit",
            source="builtin",
            rank=100,
        ),
    ]

    # Default index mappings (overridden by org config)
    DEFAULT_INDEX_MAPPINGS = {
        "authentication": "wineventlog",
        "network": "firewall",
        "web": "proxy",
        "dns": "dns",
        "endpoint": "main",
        "email": "exchange",
    }

    # Default field mappings (overridden by org config)
    DEFAULT_FIELD_MAPPINGS = {
        "user": "user",
        "source_ip": "src_ip",
        "destination_ip": "dest_ip",
        "action": "action",
        "status": "status",
    }

    def __init__(self, llm=None):
        """
        Initialize the NLP to SPL generator.

        Args:
            llm: Optional LLM instance. If not provided, uses Ollama.
        """
        self._llm = llm
        self._examples: List[QueryExample] = list(self.BUILTIN_EXAMPLES)
        self._macros_loaded = False
        self._searches_loaded = False
        self._feedback_loaded = False
        self._index_mappings: Dict[str, str] = dict(self.DEFAULT_INDEX_MAPPINGS)
        self._field_mappings: Dict[str, str] = dict(self.DEFAULT_FIELD_MAPPINGS)

    def load_macros(self, macros: Dict[str, Dict[str, Any]]) -> int:
        """Load macros as examples for few-shot learning."""
        count = 0
        for name, macro in macros.items():
            definition = macro.get("definition", "")
            if not definition or len(definition) < 10:
                continue

            # Infer intent from definition
            intent = self._detect_intent(definition)

            self._examples.append(QueryExample(
                name=name,
                description=macro.get("description", f"Macro: {name}"),
                query=definition,
                intent=intent,
                source="macro",
                rank=macro.get("rank", 50),
            ))
            count += 1

        self._macros_loaded = True
        logger.info(f"Loaded {count} macros as NLP examples")
        return count

    def load_saved_searches(self, searches: Dict[str, Dict[str, Any]]) -> int:
        """Load saved searches as examples for few-shot learning."""
        count = 0
        for name, search in searches.items():
            query = search.get("search", "")
            if not query or len(query) < 20:
                continue

            # Skip if too complex (>500 chars)
            if len(query) > 500:
                continue

            intent = self._detect_intent(query)

            self._examples.append(QueryExample(
                name=name,
                description=search.get("description", f"Saved search: {name}"),
                query=query,
                intent=intent,
                source="savedsearch",
                rank=search.get("rank", 50),
            ))
            count += 1

        self._searches_loaded = True
        logger.info(f"Loaded {count} saved searches as NLP examples")
        return count

    def load_feedback_qa(self, qa_pairs: List[Dict[str, Any]]) -> int:
        """Load feedback Q&A pairs as examples."""
        count = 0
        for qa in qa_pairs:
            query = qa.get("answer", "") or qa.get("query", "")
            question = qa.get("question", "")

            if not query or not question:
                continue

            intent = self._detect_intent(query)

            self._examples.append(QueryExample(
                name=f"feedback_{count}",
                description=question[:100],
                query=query,
                intent=intent,
                source="feedback",
                rank=qa.get("rank", 80),  # Higher rank for user-validated
            ))
            count += 1

        self._feedback_loaded = True
        logger.info(f"Loaded {count} feedback Q&A pairs as NLP examples")
        return count

    def set_index_mappings(self, mappings: Dict[str, str]) -> None:
        """Override default index mappings with org-specific ones."""
        self._index_mappings.update(mappings)
        logger.info(f"Updated index mappings: {list(mappings.keys())}")

    def set_field_mappings(self, mappings: Dict[str, str]) -> None:
        """Override default field mappings with org-specific ones."""
        self._field_mappings.update(mappings)
        logger.info(f"Updated field mappings: {list(mappings.keys())}")

    def _detect_intent(self, text: str) -> SPLIntent:
        """Detect the intent from text using weighted keyword matching."""
        text_lower = text.lower()

        scores = {intent: 0 for intent in SPLIntent}
        for intent, keyword_weights in self.INTENT_KEYWORDS.items():
            for keyword, weight in keyword_weights:
                if keyword in text_lower:
                    scores[intent] += weight

        if any(scores.values()):
            return max(scores, key=scores.get)
        return SPLIntent.SEARCH_EVENTS

    def _select_examples(self, nl_query: str, max_examples: int = 5) -> List[QueryExample]:
        """Select the most relevant examples for the query."""
        nl_lower = nl_query.lower()
        intent = self._detect_intent(nl_query)

        scored = []
        for ex in self._examples:
            score = ex.rank

            # Boost if intent matches (check both enum name and value)
            ex_intent_lower = ex.intent.lower() if isinstance(ex.intent, str) else ex.intent.value.lower()
            if ex_intent_lower in (intent.name.lower(), intent.value.lower()):
                score += 50

            # Boost if words overlap with description
            for word in nl_lower.split():
                if len(word) > 3 and word in ex.description.lower():
                    score += 10
                if len(word) > 3 and word in ex.name.lower():
                    score += 15

            # Boost user-validated examples
            if ex.source == "feedback":
                score += 20

            scored.append((score, ex))

        # Sort by score and return top N
        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:max_examples]]

    def _build_prompt(self, nl_query: str, examples: List[QueryExample]) -> str:
        """Build the architect-level prompt for the LLM."""
        examples_text = "\n".join([
            f'{{"description": "{ex.description}", "query": "{ex.query}"}}'
            for ex in examples
        ])

        # Build org-context snippet so the LLM knows which indexes/fields to use
        idx_ctx = ", ".join(f"{k}={v}" for k, v in self._index_mappings.items())
        fld_ctx = ", ".join(f"{k}={v}" for k, v in self._field_mappings.items())

        prompt = f"""You are a Senior Observability & Security Architect acting as a Splunk SPL query generator.
You operate at principal-level, assuming production-scale data volumes and strict correctness.

VALIDATION-FIRST RULE:
Before generating any query, reason through data structure, field availability, index-time vs search-time considerations, and execution cost. Never blindly generate SPL.

MANDATORY RULES:
1. Output a single JSON object: {{"query": "...", "confidence": 0.0-1.0, "explanation": "..."}}
2. Always include earliest/latest time range. Default to earliest=-24h latest=now unless the user specifies otherwise.
3. Always specify a concrete index (index=...). NEVER use index=*.
4. Prefer tstats over stats for simple aggregations on indexed fields — 10-100x faster.
5. Use TERM(field=value) in tstats WHERE clauses and in regular search for bloom filter optimization. NEVER put wildcards inside TERM().
6. Use PREFIX(field=prefix) for prefix matching in tstats.
7. Use standard CIM field names: src_ip, dest_ip, src, dest, user, action, status, host.
8. End with an appropriate aggregation or transformation: stats, timechart, top, rare, table, chart.
9. Avoid bare keywords floating in queries. Use field=value or quote free-text terms.
10. Consider command execution order: filter early, aggregate late, avoid expensive commands before stats.

SPL EXECUTION ORDER AWARENESS:
- Streaming commands (eval, where, rex, rename) process events individually — use them early for filtering.
- Transforming commands (stats, timechart, top, chart) aggregate results — place after filtering.
- Generating commands (tstats, inputlookup, makeresults) must be first in the pipeline.
- Non-streaming commands (sort, dedup, transaction) require all events — expensive, use sparingly.

ANTI-PATTERNS TO AVOID:
- Do NOT use "| stats count" after "| table" — table is a final display command.
- Do NOT use "| search" when "| where" is more efficient for evaluated expressions.
- Do NOT use "| join" when "| stats" with multi-value fields or "| lookup" suffices.
- Do NOT place "| sort" before "| stats" — stats destroys ordering.
- Do NOT put "| head" before "| stats" — it limits input events, not final results.

ORGANIZATION CONTEXT:
Index mappings: {idx_ctx}
Field mappings: {fld_ctx}

EXAMPLES:
{examples_text}

Convert this natural language request to SPL. Respond with ONLY a valid JSON object, nothing else.

Question: {nl_query}
JSON:"""
        return prompt

    def generate(self, nl_query: str, context: Optional[Dict] = None) -> SPLGenerationResult:
        """
        Generate SPL from natural language query.

        Args:
            nl_query: Natural language query (e.g., "show me failed logins")
            context: Optional context dict with unit_id, index preferences, etc.

        Returns:
            SPLGenerationResult with the generated query and metadata
        """
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            if isinstance(self._llm, ChatGoogleGenerativeAI):
                return generate_with_gemini(nl_query)
        except ImportError:
            pass

        # Detect intent
        intent = self._detect_intent(nl_query)

        # Select relevant examples
        examples = self._select_examples(nl_query)
        example_names = [ex.name for ex in examples]

        # Check for direct pattern match
        direct_match = self._try_direct_match(nl_query, intent)
        if direct_match:
            return SPLGenerationResult(
                query=direct_match,
                confidence=0.9,
                explanation=f"Generated from pattern match for '{intent}' intent",
                examples_used=example_names,
                intent=intent,
                suggestions=[],
            )

        # Use LLM if available
        if self._llm:
            try:
                prompt = self._build_prompt(nl_query, examples)
                response = self._llm.invoke(prompt)
                llm_output = response.content if hasattr(response, 'content') else str(response)
                
                # Extract JSON from the response
                json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
                if not json_match:
                    raise ValueError("LLM did not return a JSON object.")
                
                parsed_json = json.loads(json_match.group(0))
                query = parsed_json.get("query", "")
                confidence = float(parsed_json.get("confidence", 0.7))
                explanation = parsed_json.get("explanation", "Generated by LLM.")

                # Post-validate and fix common LLM mistakes
                if not query:
                    raise ValueError("LLM returned empty query.")

                # Strip markdown first
                if query.strip().startswith("```"):
                    lines = query.strip().split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    query = "\n".join(lines).strip()

                # Now, use the robust analyzer to validate and fix
                try:
                    logger.info(f"Robustly analyzing generated SPL: {query}")
                    analysis = analyze_spl(query, auto_fix=True)
                    if analysis.optimized_query and analysis.optimized_query != query:
                        logger.info(f"Optimized LLM query from '{query}' to '{analysis.optimized_query}'")
                        query = analysis.optimized_query
                except Exception as analysis_exc:
                    logger.error(f"Robust analyzer failed during NLP generation: {analysis_exc}")

                return SPLGenerationResult(
                    query=query,
                    confidence=confidence,
                    explanation=explanation,
                    examples_used=example_names,
                    intent=intent,
                    suggestions=self._get_suggestions(query),
                )
            except (Exception, json.JSONDecodeError) as e:
                logger.warning(f"LLM generation or parsing failed: {e}. Falling back.")

        # Fallback: use best matching example
        if examples:
            best = examples[0]
            return SPLGenerationResult(
                query=best.query,
                confidence=0.5,
                explanation=f"Using closest matching example: {best.name}",
                examples_used=[best.name],
                intent=intent,
                suggestions=["This is a template - modify as needed"],
            )

        # Last resort: generate basic template
        template = self._generate_template(nl_query, intent, context)
        return SPLGenerationResult(
            query=template,
            confidence=0.3,
            explanation="Generated basic template - please review and modify",
            examples_used=[],
            intent=intent,
            suggestions=["Add specific field filters", "Adjust time range as needed"],
        )

    def _extract_time_range(self, nl_lower: str) -> str:
        """Extract time range from natural language, defaulting to 1 hour."""
        time_patterns = [
            (r"last\s+(\d+)\s*min", lambda m: f"earliest=-{m.group(1)}m latest=now"),
            (r"last\s+(\d+)\s*hour", lambda m: f"earliest=-{m.group(1)}h latest=now"),
            (r"last\s+(\d+)\s*day", lambda m: f"earliest=-{m.group(1)}d latest=now"),
            (r"past\s+(\d+)\s*min", lambda m: f"earliest=-{m.group(1)}m latest=now"),
            (r"past\s+(\d+)\s*hour", lambda m: f"earliest=-{m.group(1)}h latest=now"),
            (r"past\s+(\d+)\s*day", lambda m: f"earliest=-{m.group(1)}d latest=now"),
            (r"last 24 hour|past day|yesterday", lambda _: "earliest=-24h latest=now"),
            (r"last hour", lambda _: "earliest=-1h latest=now"),
            (r"last 15 min", lambda _: "earliest=-15m latest=now"),
            (r"last week|past week", lambda _: "earliest=-7d latest=now"),
            (r"last 30 day|last month|past month", lambda _: "earliest=-30d latest=now"),
            (r"today", lambda _: "earliest=@d latest=now"),
            (r"this week", lambda _: "earliest=@w0 latest=now"),
            (r"all time", lambda _: "earliest=0 latest=now"),
        ]
        for pattern, converter in time_patterns:
            match = re.search(pattern, nl_lower)
            if match:
                return converter(match)
        return "earliest=-1h latest=now"

    def _try_direct_match(self, nl_query: str, intent: SPLIntent) -> Optional[str]:
        """Try to directly match common query patterns using intent templates."""
        nl_lower = nl_query.lower()

        # Extract entities from the natural language query
        extracted = self._extract_entities(nl_lower)

        # Extract time range
        time_range = self._extract_time_range(nl_lower)
        time_parts = time_range.split(" ")
        time_start = time_parts[0].split("=")[1] if "earliest" in time_range else "-1h"
        time_end = time_parts[1].split("=")[1] if len(time_parts) > 1 else "now"

        # Detect if user wants "top N" of a domain-specific intent
        has_top_modifier = bool(re.search(r"\btop\s+\d+\b", nl_lower))
        limit = extracted.get("limit", 10)
        group_field = extracted.get("field", "host")

        if intent not in INTENT_TEMPLATES:
            return None

        template_info = INTENT_TEMPLATES[intent]
        template = template_info["template"]
        params = template_info["default_params"].copy()

        params["time_start"] = time_start
        params["time_end"] = time_end

        # Override index from org mappings based on detected domain
        domain = extracted.get("domain")
        if domain and domain in self._index_mappings and "index" in params:
            params["index"] = self._index_mappings[domain]

        # Override explicit index
        if extracted.get("explicit_index") and "index" in params:
            params["index"] = extracted["explicit_index"]

        # Override specific fields if extracted
        if extracted.get("user") and "user" in params:
            params["user"] = extracted["user"]
        if extracted.get("field") and "field" in params:
            params["field"] = extracted["field"]
        if extracted.get("group_field") and "group_field" in params:
            params["group_field"] = extracted["group_field"]
        if extracted.get("limit") and "limit" in params:
            params["limit"] = extracted["limit"]
        if extracted.get("span") and "span" in params:
            params["span"] = extracted["span"]

        try:
            query = template.format(**params)

            # If "top N" modifier on a non-TOP_VALUES intent, rewrite aggregation
            if has_top_modifier and intent != SPLIntent.TOP_VALUES:
                base_search = query.split("|")[0].strip()
                query = (
                    f"{base_search} "
                    f"| stats count by {group_field} "
                    f"| sort - count | head {limit}"
                )

            return query
        except KeyError as e:
            logger.warning(f"Template format error for {intent}: missing key {e}")
            return None

    def _extract_entities(self, nl_lower: str) -> Dict[str, Any]:
        """Extract entities like users, IPs, indexes, fields from natural language."""
        entities: Dict[str, Any] = {}

        # Detect domain context
        domain_patterns = {
            "authentication": r"\b(login|logon|auth|sign.?in|password|credential)\b",
            "network": r"\b(network|firewall|traffic|connection|packet|deny|denied|block)\b",
            "web": r"\b(web|http|proxy|url|request)\b",
            "dns": r"\b(dns|domain|resolve|nxdomain)\b",
            "endpoint": r"\b(endpoint|process|edr|sysmon|powershell)\b",
        }
        for domain, pattern in domain_patterns.items():
            if re.search(pattern, nl_lower):
                entities["domain"] = domain
                break

        # Extract "top N" limit
        top_match = re.search(r"\btop\s+(\d+)\b", nl_lower)
        if top_match:
            entities["limit"] = int(top_match.group(1))

        # Extract field references from natural language
        # "source IPs", "source addresses", "src_ip", "destination IPs"
        field_phrases = {
            r"\bsource\s+ips?\b": "src_ip",
            r"\bsrc\s+ips?\b": "src_ip",
            r"\bsource\s+address": "src_ip",
            r"\bsource\s+hosts?\b": "src",
            r"\bdestination\s+ips?\b": "dest_ip",
            r"\bdest\s+ips?\b": "dest_ip",
            r"\bdestination\s+address": "dest_ip",
            r"\bdestination\s+hosts?\b": "dest",
            r"\bdestination\s+ports?\b": "dest_port",
            r"\bsource\s+ports?\b": "src_port",
            r"\busers?\b": "user",
            r"\bhosts?\b": "host",
            r"\bsourcetypes?\b": "sourcetype",
            r"\bdomains?\b": "query",
            r"\burls?\b": "url",
            r"\bapplications?\b": "app",
            r"\bprocesse?s?\b": "process_name",
            r"\bactions?\b": "action",
            r"\bstatus\s+codes?\b": "status",
        }
        detected_fields = []
        for pattern, spl_field in field_phrases.items():
            if re.search(pattern, nl_lower):
                detected_fields.append(spl_field)

        if detected_fields:
            # Use the first detected field as the primary grouping field
            entities["field"] = detected_fields[0]
            entities["group_field"] = detected_fields[0]
            if len(detected_fields) > 1:
                entities["extra_fields"] = detected_fields[1:]

        # Extract "by <field>" grouping (override if explicit)
        by_match = re.search(r"\bby\s+(\w+)", nl_lower)
        if by_match:
            field = by_match.group(1)
            field_map = {
                "user": "user", "users": "user",
                "ip": "src_ip", "source": "src_ip", "src": "src_ip",
                "destination": "dest_ip", "dest": "dest_ip",
                "host": "host", "hosts": "host",
                "sourcetype": "sourcetype",
                "index": "index",
                "port": "dest_port",
                "action": "action",
            }
            entities["group_field"] = field_map.get(field, field)
            entities["field"] = entities["group_field"]

        # Extract "for user X"
        user_match = re.search(r"\bfor\s+user\s+(\w+)", nl_lower)
        if user_match:
            entities["user"] = user_match.group(1)

        # Extract specific IP addresses
        ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", nl_lower)
        if ip_match:
            entities["ip_address"] = ip_match.group(1)

        # Extract specific index name
        idx_match = re.search(r"\bindex\s*=\s*(\w+)", nl_lower)
        if idx_match:
            entities["explicit_index"] = idx_match.group(1)

        # Extract span for timechart
        span_match = re.search(r"\b(\d+)\s*(min|minute|hour|day)s?\s*(span|interval|bucket)", nl_lower)
        if not span_match:
            span_match = re.search(r"\b(span|interval|bucket)\s*(?:of\s+)?(\d+)\s*(min|minute|hour|day)s?", nl_lower)
            if span_match:
                entities["span"] = f"{span_match.group(2)}{span_match.group(3)[0]}"
        else:
            entities["span"] = f"{span_match.group(1)}{span_match.group(2)[0]}"

        return entities



    def _generate_template(self, nl_query: str, intent: SPLIntent, context: Optional[Dict]) -> str:
        """Generate a basic template query using configurable mappings."""
        index = "main"
        time_range = "earliest=-1h latest=now"

        if context:
            index = context.get("index", "main")

        # Use org-configurable index/field mappings
        auth_index = self._index_mappings.get("authentication", "wineventlog")
        net_index = self._index_mappings.get("network", "firewall")
        user_field = self._field_mappings.get("user", "user")
        src_ip_field = self._field_mappings.get("source_ip", "src_ip")
        dest_ip_field = self._field_mappings.get("destination_ip", "dest_ip")

        if intent == SPLIntent.COUNT_EVENTS:
            return f"index={index} {time_range} | stats count by host"
        elif intent == SPLIntent.TIMECHART:
            return f"index={index} {time_range} | timechart span=1h count"
        elif intent == SPLIntent.FAILED_LOGINS:
            return f"index={auth_index} EventCode=4625 {time_range} | stats count by {user_field}"
        elif intent == SPLIntent.NETWORK_TRAFFIC:
            return f"index={net_index} {time_range} | stats count by {src_ip_field}, {dest_ip_field}"
        else:
            return f"index={index} {time_range} | stats count"



    def _get_suggestions(self, query: str) -> List[str]:
        """Get optimization suggestions for the generated query."""
        suggestions = []

        if "index=*" in query:
            suggestions.append("Specify a concrete index instead of index=* to reduce scan scope")
        elif "index=" not in query and "tstats" not in query:
            suggestions.append("Add a specific index to improve performance")

        if "earliest" not in query:
            suggestions.append("Add time range (earliest/latest) to limit data scanned")

        if "| stats count" in query and "tstats" not in query:
            suggestions.append("Consider tstats for faster aggregation: | tstats count where index=... TERM(field=value) by host")

        if "| join" in query:
            suggestions.append("Consider replacing | join with | stats or | lookup for better performance at scale")

        if "| transaction" in query:
            suggestions.append("transaction is memory-intensive; consider | stats values() with a grouping field instead")

        if re.search(r'\|\s*sort\b.*\|\s*stats\b', query, re.IGNORECASE):
            suggestions.append("| sort before | stats is wasteful — stats destroys ordering")

        if "| table" in query and "| sort" not in query and "| stats" not in query:
            suggestions.append("Consider adding | sort or | stats before | table to order results")

        if re.search(r'\bNOT\s+\w+=', query) and "TERM" not in query:
            suggestions.append("Negative filtering (NOT field=value) scans broadly; filter positively first when possible")

        return suggestions

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about loaded examples."""
        by_source = {}
        by_intent = {}

        for ex in self._examples:
            by_source[ex.source] = by_source.get(ex.source, 0) + 1
            by_intent[ex.intent] = by_intent.get(ex.intent, 0) + 1

        return {
            "total_examples": len(self._examples),
            "by_source": by_source,
            "by_intent": by_intent,
            "macros_loaded": self._macros_loaded,
            "searches_loaded": self._searches_loaded,
            "feedback_loaded": self._feedback_loaded,
        }


# Singleton instance
_nlp_to_spl: Optional[NLPtoSPL] = None


def get_nlp_generator(llm=None) -> NLPtoSPL:
    """Get or create the NLP to SPL generator singleton.

    Args:
        llm: Optional LLM instance to use for generation.
             Only used on first call (when singleton is created).
             Pass None to use direct-match/template-only mode.
    """
    global _nlp_to_spl
    if _nlp_to_spl is None:
        _nlp_to_spl = NLPtoSPL(llm=llm)
    elif llm is not None and _nlp_to_spl._llm is None:
        # Allow late-binding the LLM if it wasn't available at creation
        _nlp_to_spl._llm = llm
        logger.info("LLM late-bound to existing NLPtoSPL singleton")
    return _nlp_to_spl


def generate_with_gemini(nl_query: str) -> SPLGenerationResult:
    """Generate SPL from natural language query using Gemini API."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    llm = ChatGoogleGenerativeAI(model="gemini-pro", convert_system_message_to_human=True)
    prompt = ChatPromptTemplate.from_template("You are a Splunk expert. Generate a Splunk search query for the following user request: {user_request}")
    chain = prompt | llm | StrOutputParser()
    query = chain.invoke({"user_request": nl_query})

    return SPLGenerationResult(
        query=query,
        confidence=0.8,
        explanation="Generated by Gemini API.",
        examples_used=[],
        intent="spl_generation",
        suggestions=[],
    )


def generate_spl_from_nl(nl_query: str, context: Optional[Dict] = None) -> SPLGenerationResult:
    """Convenience function to generate SPL from natural language."""
    generator = get_nlp_generator()
    return generator.generate(nl_query, context)
