import logging
import re

from chat_app.registry import Intent

logger = logging.getLogger(__name__)

# Intent detection patterns
META_PATTERNS = [
    "who are you", "what are you", "introduce yourself",
    "what can you do", "how can you help", "your capabilities", "what do you know",
    "what connections", "what data", "what sources", "what do you have access",
    # NOTE: General Splunk knowledge questions moved to general_qa (they benefit from RAG context)
]

SPL_KEYWORDS = ['tstats', 'term(', 'term ', 'query', 'search for']
# Word-boundary regex for "spl" to avoid matching "splunk"
_SPL_WORD_PATTERN = re.compile(r'\bspl\b')
# Patterns that indicate raw SPL query (not just asking about SPL)
RAW_SPL_PATTERNS = [
    r'\bindex\s*=',           # index=main
    r'\bsourcetype\s*=',      # sourcetype=access_combined
    r'\|\s*stats\b',          # | stats
    r'\|\s*eval\b',           # | eval
    r'\|\s*where\b',          # | where
    r'\|\s*table\b',          # | table
    r'\|\s*fields\b',         # | fields
    r'\|\s*search\b',         # | search
    r'\|\s*rex\b',            # | rex
    r'\|\s*timechart\b',      # | timechart
    r'\|\s*tstats\b',         # | tstats
    r'\|\s*join\b',           # | join
    r'\|\s*lookup\b',         # | lookup
    r'\|\s*sort\b',           # | sort
    r'\|\s*head\b',           # | head
    r'\|\s*tail\b',           # | tail
    r'\|\s*dedup\b',          # | dedup
    r'\|\s*transaction\b',    # | transaction
    r'\bearliest\s*=',        # earliest=-24h
    r'\blatest\s*=',          # latest=now
]
TEMPLATE_KEYWORDS = ['tstats', 'term']
CONFIG_KEYWORDS = ['.conf', 'config', 'props', 'transforms', 'inputs', 'outputs', 'spec', 'stanza',
                    'savedsearch', 'saved search', 'saved_search', 'savedsearches', 'macros']
TROUBLESHOOT_KEYWORDS = ['error', 'issue', 'problem', 'troubleshoot', 'debug', 'not working', 'failed', 'broken']
REPO_PATTERNS = [
    r'\b(org-|TA-|SA-|DA-)',
    r'\b(our|my)\s+(app|config|setup|environment)',
    r'\b(github|repo|repository)\b',
]
SAVED_SEARCH_PATTERNS = [
    r'\banalyze\b.*\b(saved|scheduled)\s+searches',
    r'\breview\b.*\b(saved|scheduled)\s+searches',
    r'\bcheck\b.*\b(saved|scheduled)\s+searches',
    r'\boptimize\b.*\b(saved|scheduled)\s+searches',
]
CONFIG_HEALTH_PATTERNS = [
    r'\b(check|analyze|review|scan)\b.*\b(config|configurations|conf)\b.*\b(health|issues|problems|errors|best practice|security)',
    r'\b(run|perform)\b.*\b(config|configuration)\s+(health\s+check|analysis|scan)',
    r'\b(health\s+check)\b',
]
RUN_SEARCH_PATTERNS = [
    r'\b(run|execute)\b.*\b(search|query|spl)\b',
    r'^\s*(run|execute|search|spl)\s*:', # "run: <query>"
]
CREATE_ALERT_PATTERNS = [
    r'\b(create|make|build|add|schedule)\b.*\b(alert|report)\b',
    r'\b(alert me when|notify me if)\b',
]

# Ansible / Shell / Python / Compare patterns
ANSIBLE_PATTERNS = [
    r'\bansible\b', r'\bplaybook\b', r'\byaml\s+task\b', r'\bansible[-_]playbook\b',
    r'\brole\b.*\bansible\b', r'\binventory\b.*\bhost\b', r'\bansible\s+module\b',
    r'\bansible[-_]vault\b', r'\bansible[-_]galaxy\b',
]
SHELL_SCRIPT_PATTERNS = [
    r'\bshell\s*script\b', r'\bbash\s*script\b', r'\bwrite\b.*\bscript\b',
    r'\bshebang\b', r'\bset\s+-e\b', r'\bgetopts\b', r'\b\.sh\b',
    r'\banalyze\b.*\bscript\b', r'\bgenerate\b.*\bscript\b',
]
PYTHON_SCRIPT_PATTERNS = [
    r'\bpython\s*script\b', r'\bwrite\b.*\bpython\b', r'\bpython\s+code\b',
    r'\bargparse\b', r'\bfastapi\b', r'\bflask\b', r'\bpytest\b',
    r'\banalyze\b.*\bpython\b', r'\bgenerate\b.*\bpython\b',
]
COMPARE_PATTERNS = [
    r'\b(compare|difference|differ|vs|versus)\b.*\b(command|spl|query|search)\b',
    r'\b(command|spl|query|search)\b.*\b(compare|difference|differ|vs|versus)\b',
    r'\bwhat.s the difference between\b',
    r'\bhow (does|do) .+ differ from\b',
    r'\bstats vs\b|\bchart vs\b|\btimechart vs\b|\bjoin vs\b|\blookup vs\b',
]

# SPL optimizer action detection patterns
SPL_EXPLAIN_PATTERNS = [
    r'\bexplain\b.*\b(spl|query|search|tstats|prefix|term)',
    r'\b(spl|query|search|tstats|prefix|term).*\bexplain\b',
    r'\bwhat does\b.*\b(spl|query|search)\b.*\b(mean|do)\b',
    r'\bwhat does\b.*\b(index\s*=|sourcetype\s*=|\|\s*stats)',
    r'\bhow does\b.*\b(spl|query|search|tstats|prefix|term)\b.*\bwork\b',
    r'\bunderstand\b.*\b(spl|query|search|tstats|prefix|term)\b',
    r'\bbreak down\b.*\b(spl|query|search)\b',
    r'\bstep.?by.?step\b',
    r'^explain\s*:\s*',
    r'\bexplain\s+this\s*:\s*',
    # Educational "how to use" / "what is" patterns for SPL concepts
    r'\bhow (to use|do i use|can i use)\b.*\b(tstats|stats|eval|rex|prefix|term|lookup|join|transaction|where|datamodel)\b',
    r'\bwhat (?:is|does|are)\b.*\b(tstats|prefix|term|cim|data\s*model|accelerat)',
    r'\bwhen (to use|should i use)\b.*\b(tstats|stats|prefix|term)\b',
    r'\b(difference|diff)\b.*\b(tstats|stats|prefix|term)\b',
    r'\btstats\b.*\bvs\b|\bvs\b.*\btstats\b',
    r'\btell me about\b.*\b(tstats|prefix|term|stats)\b',
    r'\bteach me\b.*\b(tstats|prefix|term|spl)\b',
    r'\b(syntax|usage)\b.*\b(tstats|prefix|term)\b',
    # "help me with tstats", "help with prefix", "help me understand tstats"
    r'\bhelp\b.*\b(tstats|prefix|term|stats|eval|rex|lookup|datamodel|cim)\b',
    # "show me how tstats works", "show me prefix examples"
    r'\bshow me\b.*\b(tstats|prefix|term)\b.*(example|usage|syntax|work)',
    r'\b(example|examples|sample)\b.*\b(tstats|prefix|term)\b',
    r'\b(tstats|prefix|term)\b.*(example|examples|sample|tutorial|guide)',
]
SPL_OPTIMIZE_PATTERNS = [
    r'\boptimize\b.*\b(spl|query|search|tstats)',
    r'\b(spl|query|search|tstats).*\boptimize\b',
    r'\bimprove\b.*\b(spl|query|search|performance)\b',
    r'\b(faster|speed up|slow)\b.*\b(spl|query|search)\b',
    r'\bconvert to tstats\b',
    r'\bmake.*(faster|efficient)\b',
]
SPL_REVIEW_PATTERNS = [
    r'\breview\b.*\b(spl|query|search)\b',
    r'\banalyze\b.*\b(spl|query|search)\b',
    r'\bvalidate\b.*\b(spl|query|search)\b',
    r'\bcheck\b.*\b(spl|query|search)\b',
    r'\bis this (spl|query|search)\b.*(correct|right|valid)',
    r'^review\s*:\s*',  # "review: <query>" at start
    r'\breview\s+this\s*:\s*',  # "review this: <query>"
]
SPL_SCORE_PATTERNS = [
    r'\bscore\b.*\b(spl|query|search)\b',
    r'\brate\b.*\b(spl|query|search)\b',
    r'\bhow good\b.*\b(spl|query|search)\b',
    r'\bquality\b.*\b(spl|query|search)\b',
]
SPL_ANNOTATE_PATTERNS = [
    r'\bannotate\b.*\b(spl|query|search)\b',
    r'\bcomment\b.*\b(spl|query|search)\b',
    r'\badd comments\b',
]
NLP_TO_SPL_PATTERNS = [
    r'\b(write|create|generate|build|give me)\b.*\b(spl|query|search)\b',
    r'\bspl for\b',
    r'\bquery (for|to)\b',
    r'\bhow (do i|can i|to)\b.*\bsearch\b',
    r'\bfind\b.*\b(events|logs|data|logins?|attempts?|errors?|failures?|connections?|traffic)\b',
    r'\bshow me\b.*\b(events|logs|data|logins?|attempts?|errors?|traffic|connections?)\b',
    r'\bshow\b.*\b(failed|denied|blocked|error|success)\b',
    r'\bfind all\b',
    r'\bcount\b.*\b(of|all|by)\b',
    r'\blist\b.*\b(all|the)\b',
    r'\bhow many\b',
    r'\btop\s+\d*\s*\b(user|host|source|ip|domain|url)',
    r'\brare\b.*\b(event|sourcetype|error)',
    r'\bwhat.*(denied|blocked|failed|error)',
    r'\b(detect|alert on|find)\b.*\b(brute.?force|attack|anomal|suspicious|exfiltrat)',
    r'\b(dns|firewall|proxy|vpn|authentication)\b.*(query|search|events|logs|activity)',
]

SEARCH_SUGGESTION_PATTERNS = [
    r'\b(suggest|give me|can you give me)\b.*\b(search|query)\b',
]

# --- Cribl-specific patterns ---
CRIBL_PIPELINE_PATTERNS = [
    r'\bcribl\b.*\b(pipeline|route|pack|function|source|destination)\b',
    r'\b(pipeline|route|pack)\b.*\bcribl\b',
    r'\bcribl\s+(stream|edge|search|lake)\b',
    r'\b(create|build|configure|modify|analyze|debug)\b.*\b(cribl|pipeline|route)\b.*\b(cribl|pipeline|route)\b',
    r'\bdata\s+(routing|transformation|reduction|masking|enrichment)\b',
    r'\bevent\s+(breaker|filter|router|pipeline)\b.*\b(cribl|stream)\b',
    r'\bcribl\b',  # Any mention of Cribl triggers Cribl-aware handling
]
CRIBL_CONFIG_PATTERNS = [
    r'\bcribl\b.*\b(config|configuration|setup|deploy|worker|leader)\b',
    r'\b(worker|leader)\s*(group|node|process)\b.*\bcribl\b',
    r'\bcribl\b.*\b(input|output|source|dest)\b',
    r'\b(s3|splunk|kafka|kinesis|syslog|http)\b.*\b(destination|output|source|input)\b.*\bcribl\b',
]

# --- Observability-specific patterns ---
OBSERVABILITY_METRICS_PATTERNS = [
    r'\b(mstats|mcatalog|mpreview|metric|metrics)\b',
    r'\b(cpu|memory|disk|network|latency|throughput|error.rate|p99|p95|p50)\b.*\b(metric|monitor|alert|query)\b',
    r'\bopentelemetry\b|\botel\b|\botlp\b',
    r'\b(trace|tracing|span|distributed.trace)\b',
    r'\b(apm|application.performance|service.map)\b',
    r'\b(sli|slo|error.budget|availability)\b',
    r'\b(observability|o11y)\b',
    r'\b(prometheus|grafana|datadog|newrelic|dynatrace)\b.*\b(query|metric|dashboard)\b',
    r'\b(log.routing|log.pipeline|log.aggregation)\b',
]
OBSERVABILITY_INFRA_PATTERNS = [
    r'\b(kubernetes|k8s|container|pod|node|namespace|helm)\b.*\b(monitor|log|metric|trace|observ)\b',
    r'\b(monitor|observ)\b.*\b(kubernetes|k8s|container|pod)\b',
    r'\b(cloud|aws|azure|gcp)\b.*\b(monitor|log|metric|observ)\b',
    r'\b(serverless|lambda|function)\b.*\b(monitor|trace|log)\b',
    r'\b(docker|ecs|fargate)\b.*\b(log|monitor|metric)\b',
]

_UTILITY_PATTERNS = [
    re.compile(r'\b(base64|hex|url|html)\s*(encode|decode)\b', re.I),
    re.compile(r'\b(md5|sha\d*)\s*(hash|of|for)?\b', re.I),
    re.compile(r'\b(json|csv|xml|kv)\s*(to|parse|prettify|minify|convert)\b', re.I),
    re.compile(r'\bconvert\s+.+\s+to\s+(json|csv|base64|hex|md5|sha)', re.I),
    re.compile(r'\b(timestamp|epoch|unix.?time)\s*(convert|to)\b', re.I),
    re.compile(r'\bgenerate\s+(uuid|guid)\b', re.I),
    re.compile(r'\bvalidate\s+(\w+\s+)*(conf|config|cim|props|transforms)\b', re.I),
    re.compile(r'\b(uppercase|lowercase|to upper|to lower)\b', re.I),
]
# SPL pipe/index patterns — if present, this is NOT a utility request
_SPL_INDICATORS = re.compile(r'(index\s*=|^\s*\||\|\s*(stats|sort|table|where|eval|search|head|tail|rex|rename|fields))', re.I)

CLARIFICATION_PATTERNS = [
    # Only trigger clarification for very vague stand-alone pronoun queries
    # like "what about it?" or "explain that" (short queries dominated by pronouns)
    r'^(?:what about|explain|tell me about|more about)\s+(?:it|that|this|those|them)\s*\??$',
]

# Vague query indicators — used to trigger clarification for underspecified queries
VAGUE_PATTERNS = [r'\b(stuff|things|data|info|information|everything|anything|something)\b']

# Short valid queries that should NOT trigger clarification despite being < 3 words
SHORT_VALID_PATTERNS = [
    r'\btstats\s+vs\s+stats\b',
    r'\bcim\s+models?\b',
    r'\bdata\s+models?\b',
    r'\bindex\s*=',
    r'\|\s*\w+',  # Pipe commands are always valid SPL
]


class IntentClassifier:
    """Classifies user intent based on patterns."""

    def __init__(self):
        # Regex-based patterns (used with re.search)
        self.regex_patterns = {
            "run_search": RUN_SEARCH_PATTERNS,
            "create_alert": CREATE_ALERT_PATTERNS,
            "ingestion": [r'read_url\s*:|read_file\s*:|read_text\s*:'],
            "clarification": CLARIFICATION_PATTERNS,
            "saved_search_analysis": SAVED_SEARCH_PATTERNS,
            "config_health_check": CONFIG_HEALTH_PATTERNS,
            "repo_query": REPO_PATTERNS,
            "raw_spl": RAW_SPL_PATTERNS,
            "nlp_to_spl": NLP_TO_SPL_PATTERNS,
            "search_suggestion": SEARCH_SUGGESTION_PATTERNS,
            "cribl_pipeline": CRIBL_PIPELINE_PATTERNS,
            "cribl_config": CRIBL_CONFIG_PATTERNS,
            "observability_metrics": OBSERVABILITY_METRICS_PATTERNS,
            "observability_infra": OBSERVABILITY_INFRA_PATTERNS,
            "ansible": ANSIBLE_PATTERNS,
            "shell_script": SHELL_SCRIPT_PATTERNS,
            "python_script": PYTHON_SCRIPT_PATTERNS,
            "compare_commands": COMPARE_PATTERNS,
        }

        # Keyword-based patterns (used with substring 'in' check)
        self.keyword_patterns = {
            "meta_question": META_PATTERNS,
            "spl_keywords": SPL_KEYWORDS,
            "config_lookup": CONFIG_KEYWORDS,
            "troubleshooting": TROUBLESHOOT_KEYWORDS,
        }

        self.spl_action_patterns = {
            "explain": SPL_EXPLAIN_PATTERNS,
            "optimize": SPL_OPTIMIZE_PATTERNS,
            "review": SPL_REVIEW_PATTERNS,
            "score": SPL_SCORE_PATTERNS,
            "annotate": SPL_ANNOTATE_PATTERNS,
        }

        self._template_keywords = TEMPLATE_KEYWORDS

    def _matches_regex(self, lower_input, intent):
        """Check if input matches any regex patterns for given intent."""
        return any(re.search(p, lower_input) for p in self.regex_patterns.get(intent, []))

    def _matches_keywords(self, lower_input, intent):
        """Check if input contains any keywords for given intent."""
        return any(kw in lower_input for kw in self.keyword_patterns.get(intent, []))

    def classify(self, user_input, word_count):
        """
        Classify user intent and build an execution plan.

        Priority order (highest to lowest):
        1. Meta-questions → skip retrieval, answer from system knowledge
        2. Run Search → execute SPL directly against Splunk
        3. Create Alert → schedule an alert in Splunk
        4. Ingestion → load documents into knowledge base
        5. Clarification → query too vague, ask for details
        6. SPL actions → explain/optimize/review/score/annotate
        7. Raw SPL → user pasted SPL code
        8. NLP-to-SPL → natural language query generation
        9. SPL keywords → general SPL-related question
        10. Saved Search Analysis → bulk analysis of saved searches
        11. Config Health Check → configuration audit
        12. Config Lookup → .conf file questions
        13. Troubleshooting → error/issue investigation
        14. Repo Query → organization-specific questions
        15. Search Suggestion → suggest searches for a use case
        16. General Q&A → catch-all
        """
        import query_router as qr

        plan = qr.QueryPlan()
        lower = user_input.lower()

        # 1. Meta-questions (skip retrieval entirely)
        if self._matches_keywords(lower, "meta_question"):
            plan.intent = Intent.META_QUESTION
            plan.skip_retrieval = True
            plan.confidence = 0.95
            return plan

        # 1b. General knowledge questions about Splunk/Cribl/Observability (use RAG)
        # Any "what is X" / "explain X" / "describe X" is general knowledge, not SPL generation
        # General knowledge questions benefit from RAG context, but queries with
        # explicit SPL context words should go to the SPL pipeline instead
        _SPL_CONTEXT_WORDS = {'query', 'search', 'tstats', 'prefix', 'term(', 'index='}
        _has_spl_context = any(w in lower for w in _SPL_CONTEXT_WORDS) or _SPL_WORD_PATTERN.search(lower)
        _is_knowledge_query = (
            not _has_spl_context
            and bool(re.match(
                r'^(what (?:is|are)|explain|describe|tell me about|how does .* work|.* overview|help me (?:understand|learn))',
                lower
            ))
        )
        if _is_knowledge_query:
            plan.intent = Intent.GENERAL_QA
            plan.profile = "general"
            plan.confidence = 0.85
            return plan

        # 1c. Utility / data transform operations (skip retrieval — pure computation)
        # Only match if no SPL indicators present (pipe, index=, etc.)
        if any(p.search(lower) for p in _UTILITY_PATTERNS) and not _SPL_INDICATORS.search(lower):
            plan.intent = Intent.DATA_TRANSFORM
            plan.skip_retrieval = True
            plan.confidence = 0.9
            return plan

        # 2. Run Search (high priority — user wants to execute SPL)
        if self._matches_regex(lower, "run_search"):
            extracted_query = qr.extract_spl_from_input(user_input)
            if extracted_query:
                plan.intent = Intent.RUN_SEARCH
                plan.skip_retrieval = True
                plan.extracted_query = extracted_query
                plan.confidence = 0.9
                return plan

        # 3. Create Alert
        if self._matches_regex(lower, "create_alert"):
            plan.intent = Intent.CREATE_ALERT
            plan.skip_retrieval = True
            plan.confidence = 0.85
            return plan

        # 4. Ingestion directives
        if self._matches_regex(lower, "ingestion"):
            plan.intent = Intent.INGESTION
            plan.confidence = 0.9
            # Still do retrieval after ingestion if there's a question

        # 5. Clarification needed - for vague or underspecified queries
        # But skip clarification for known short valid queries (e.g., "tstats vs stats")
        is_short_valid = any(re.search(p, lower) for p in SHORT_VALID_PATTERNS)
        is_vague_query = any(re.search(p, lower) for p in VAGUE_PATTERNS) and word_count < 7
        is_pronoun_only = word_count <= 3 and self._matches_regex(lower, "clarification")

        if not is_short_valid and (is_pronoun_only or (word_count < 3 and not self._matches_regex(lower, "raw_spl")) or is_vague_query):
            # Check for keywords to make the clarification more helpful
            if 'spl' in lower or 'query' in lower or 'search' in lower:
                plan.clarification_question = "I can help with that. What kind of SPL query are you looking for? For example, you could ask for 'failed logins last hour' or 'top 10 talking hosts on the firewall'."
            elif 'network' in lower or 'firewall' in lower or 'traffic' in lower:
                plan.clarification_question = "It seems you're asking about network data. Could you be more specific? For example, are you interested in firewall denies, top source IPs, or VPN connections?"
            elif 'auth' in lower or 'login' in lower or 'user' in lower:
                plan.clarification_question = "It seems you're asking about authentication. What specifically are you looking for? For example, failed logins, successful logins, or account lockouts?"
            elif 'error' in lower or 'fail' in lower:
                plan.clarification_question = "I can help look for errors. Can you tell me which index or sourcetype you're interested in? For example, 'errors in the web index' or 'failures in the authentication logs'."
            else:
                plan.clarification_question = "That's a bit vague, could you please provide more details? For example, you could ask 'show me failed logins' or 'what are the top sourcetypes by volume?'"

            plan.intent = Intent.CLARIFICATION
            return plan

        # 6. SPL-related queries - detect specific action needed
        # Check for specific SPL actions first (explain, optimize, review, score, annotate)
        # Map actions to their most appropriate intent for better downstream handling
        _ACTION_TO_INTENT = {
            "explain": Intent.SPL_EXPLANATION,
            "optimize": Intent.SPL_OPTIMIZATION,
            "review": Intent.SPL_VALIDATION,
            "score": Intent.SPL_VALIDATION,
            "annotate": Intent.SPL_EXPLANATION,
        }
        for action, patterns in self.spl_action_patterns.items():
            if any(re.search(p, lower) for p in patterns):
                plan.intent = _ACTION_TO_INTENT.get(action, Intent.SPL_GENERATION)
                plan.profile = "spl_expert"
                plan.optimizer_action = action
                plan.confidence = 0.85
                plan.retrieval_collections = ["spl_commands_mxbai", "specs_mxbai_embed_large_v3"]
                return plan

        # Check for raw SPL patterns (index=, sourcetype=, | stats, etc.)
        # High confidence — user pasted actual SPL code
        if self._matches_regex(lower, "raw_spl"):
            plan.intent = Intent.SPL_GENERATION
            plan.profile = "spl_expert"
            plan.optimizer_type = "spl"
            plan.confidence = 0.9
            plan.retrieval_collections = ["spl_commands_mxbai", "specs_mxbai_embed_large_v3"]

            # Detect context-less SPL paste: no question words, no natural language context
            # If user just pasted a query with no instructions, auto-explain + optimize
            _NL_SIGNALS = ['?', 'how', 'what', 'why', 'when', 'where', 'can you', 'please',
                           'help', 'fix', 'check', 'make', 'convert', 'change', 'improve',
                           'show me', 'find', 'get me', 'i want', 'i need']
            has_nl_context = any(sig in lower for sig in _NL_SIGNALS)
            if not has_nl_context:
                plan.optimizer_action = "explain"
                plan.auto_explain = True
                logger.info("[INTENT] Raw SPL without context detected — auto-explain mode")
            else:
                plan.optimizer_action = "optimize"

            if any(kw in lower for kw in self._template_keywords):
                plan.use_template_engine = True
            return plan

        # Check for NLP-to-SPL patterns (natural language requests for queries)
        if self._matches_regex(lower, "nlp_to_spl"):
            plan.intent = Intent.SPL_GENERATION
            plan.profile = "spl_expert"
            plan.optimizer_action = "optimize"
            plan.optimizer_type = "nlp"
            plan.confidence = 0.8
            plan.retrieval_collections = ["spl_commands_mxbai", "specs_mxbai_embed_large_v3"]
            return plan

        # Check for compare commands (before SPL keywords, since "stats vs eventstats" has SPL keywords)
        if self._matches_regex(lower, "compare_commands"):
            plan.intent = Intent.COMPARE_COMMANDS
            plan.profile = "spl_expert"
            plan.confidence = 0.8
            plan.retrieval_collections = ["spl_commands_mxbai", "specs_mxbai_embed_large_v3"]
            return plan

        # Check for general SPL keywords (lower confidence — "query" is ambiguous)
        # Also check word-boundary "spl" separately (avoids matching "splunk")
        if self._matches_keywords(lower, "spl_keywords") or _SPL_WORD_PATTERN.search(lower):
            plan.intent = Intent.SPL_GENERATION
            plan.profile = "spl_expert"
            plan.optimizer_action = "optimize"
            plan.confidence = 0.65
            plan.retrieval_collections = ["spl_commands_mxbai", "specs_mxbai_embed_large_v3"]

            if any(kw in lower for kw in self._template_keywords):
                plan.use_template_engine = True
            return plan

        # 7. Saved Search Analysis
        if self._matches_regex(lower, "saved_search_analysis"):
            plan.intent = Intent.SAVED_SEARCH_ANALYSIS
            plan.profile = "spl_expert"
            plan.skip_retrieval = True
            plan.confidence = 0.85
            return plan

        # 8. Config Health Check
        if self._matches_regex(lower, "config_health_check"):
            plan.intent = Intent.CONFIG_HEALTH_CHECK
            plan.profile = "config_helper"
            plan.skip_retrieval = True
            plan.confidence = 0.85
            return plan

        # 9. Configuration lookup
        if self._matches_keywords(lower, "config_lookup"):
            plan.intent = Intent.CONFIG_LOOKUP
            plan.profile = "config_helper"
            plan.confidence = 0.75
            plan.retrieval_collections = ["specs_mxbai_embed_large_v3", "org_repo_mxbai"]
            return plan

        # 10. Troubleshooting
        if self._matches_keywords(lower, "troubleshooting"):
            plan.intent = Intent.TROUBLESHOOTING
            plan.profile = "troubleshooter"
            plan.confidence = 0.7
            plan.retrieval_collections = ["local_docs_mxbai", "feedback_qa_mxbai_embed_large"]
            return plan

        # 11. Repository/org query
        if self._matches_regex(lower, "repo_query"):
            plan.intent = Intent.REPO_QUERY
            plan.profile = "org_expert"
            plan.confidence = 0.8
            plan.retrieval_collections = ["org_repo_mxbai", "specs_mxbai_embed_large_v3"]
            return plan

        # 12. Cribl pipeline/route/pack questions
        if self._matches_regex(lower, "cribl_pipeline"):
            plan.intent = Intent.CRIBL_PIPELINE
            plan.profile = "cribl_expert"
            plan.confidence = 0.8
            plan.retrieval_collections = ["cribl_docs_mxbai", "local_docs_mxbai"]
            return plan

        # 13. Cribl configuration/deployment questions
        if self._matches_regex(lower, "cribl_config"):
            plan.intent = Intent.CRIBL_CONFIG
            plan.profile = "cribl_expert"
            plan.confidence = 0.75
            plan.retrieval_collections = ["cribl_docs_mxbai", "local_docs_mxbai"]
            return plan

        # 14. Observability metrics (mstats, OpenTelemetry, traces)
        if self._matches_regex(lower, "observability_metrics"):
            plan.intent = Intent.OBSERVABILITY_METRICS
            plan.profile = "observability_expert"
            plan.confidence = 0.8
            plan.retrieval_collections = ["spl_commands_mxbai", "local_docs_mxbai", "cribl_docs_mxbai"]
            return plan

        # 15. Observability infrastructure monitoring
        if self._matches_regex(lower, "observability_infra"):
            plan.intent = Intent.OBSERVABILITY_INFRA
            plan.profile = "observability_expert"
            plan.confidence = 0.75
            plan.retrieval_collections = ["local_docs_mxbai", "spl_commands_mxbai"]
            return plan

        # 16. Search suggestion
        if self._matches_regex(lower, "search_suggestion"):
            plan.intent = Intent.SEARCH_SUGGESTION
            plan.skip_retrieval = True
            plan.confidence = 0.75
            return plan

        # 17. Ansible playbook / automation
        if self._matches_regex(lower, "ansible"):
            plan.intent = Intent.ANSIBLE
            plan.skip_retrieval = True
            plan.confidence = 0.85
            return plan

        # 18. Shell scripting
        if self._matches_regex(lower, "shell_script"):
            plan.intent = Intent.SHELL_SCRIPT
            plan.skip_retrieval = True
            plan.confidence = 0.8
            return plan

        # 19. Python scripting
        if self._matches_regex(lower, "python_script"):
            plan.intent = Intent.PYTHON_SCRIPT
            plan.skip_retrieval = True
            plan.confidence = 0.8
            return plan

        # 20. Compare commands
        if self._matches_regex(lower, "compare_commands"):
            plan.intent = Intent.COMPARE_COMMANDS
            plan.confidence = 0.8
            plan.retrieval_collections = ["spl_commands_mxbai", "specs_mxbai_embed_large_v3"]
            return plan

        # 21. General query (fallback — lowest confidence)
        plan.intent = Intent.GENERAL_QA
        plan.profile = "general"
        plan.confidence = 0.5
        logger.debug(f"[INTENT] No specific intent matched, falling back to general_qa for: '{user_input[:60]}...'")
        return plan
