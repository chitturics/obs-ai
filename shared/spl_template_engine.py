"""
Template-based SPL Query Generator

This bypasses the LLM for query generation to prevent hallucination.
Uses pattern matching and templates to generate correct SPL queries.
"""
import re
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
import ipaddress


@dataclass
class QueryIntent:
    """Detected user intent for query generation."""
    query_type: str  # 'term_search', 'datamodel', 'raw_search', 'unknown'
    index: Optional[str] = None
    sourcetype: Optional[str] = None
    source: Optional[str] = None
    keywords: List[str] = None
    time_range: Optional[str] = None
    datamodel: Optional[str] = None
    groupby_fields: List[str] = None
    confidence: float = 0.0


class SPLTemplateEngine:
    """Generates correct SPL queries from templates, not LLM."""

    # Time range patterns
    TIME_PATTERNS = {
        r'last\s*(\d+)\s*min(?:ute)?s?': lambda m: f'-{m.group(1)}m',
        r'last\s*(\d+)\s*hours?': lambda m: f'-{m.group(1)}h',
        r'last\s*(\d+)\s*days?': lambda m: f'-{m.group(1)}d',
        r'last\s*(\d+)\s*weeks?': lambda m: f'-{m.group(1)}w',
        r'past\s*(\d+)\s*min(?:ute)?s?': lambda m: f'-{m.group(1)}m',
        r'past\s*(\d+)\s*hours?': lambda m: f'-{m.group(1)}h',
        r'past\s*(\d+)\s*days?': lambda m: f'-{m.group(1)}d',
        r'(\d+)\s*min(?:ute)?s?\s*ago': lambda m: f'-{m.group(1)}m',
        r'(\d+)\s*hours?\s*ago': lambda m: f'-{m.group(1)}h',
        r'last\s*hour': lambda _: '-1h',
        r'last\s*day': lambda _: '-1d',
        r'last\s*week': lambda _: '-7d',
        r'last\s*month': lambda _: '-30d',
        r'today': lambda _: '@d',
        r'yesterday': lambda _: '-1d@d',
        r'this\s*week': lambda _: '@w0',
    }

    # Aggregation type detection patterns
    AGGREGATION_PATTERNS = {
        'timechart': [
            r'\b(over time|trend|timeline|hourly|daily|weekly|per hour|per day|spike|surge)\b',
            r'\b(timechart|time chart|graph over time|plot)\b',
        ],
        'top': [
            r'\b(top|most common|most frequent|highest)\b',
        ],
        'rare': [
            r'\b(rare|uncommon|least common|infrequent|unusual)\b',
        ],
        'table': [
            r'\b(list|show me|display|table|raw events|details)\b',
        ],
        'stats_count': [
            r'\b(count|how many|number of|total)\b',
        ],
        'stats_avg': [
            r'\b(average|avg|mean)\b',
        ],
        'stats_sum': [
            r'\b(sum|total bytes|total volume)\b',
        ],
    }

    # Group-by field detection patterns
    GROUPBY_PATTERNS = [
        r'\bby\s+([\w_]+(?:\s*,\s*[\w_]+)*)\b',
        r'\bper\s+([\w_]+)\b',
        r'\bfor each\s+([\w_]+)\b',
        r'\bgrouped?\s+by\s+([\w_]+(?:\s*,\s*[\w_]+)*)\b',
    ]

    # Words that should never be extracted as keywords
    NOISE_WORDS = {
        'search', 'searching', 'find', 'finding', 'show', 'showing', 'give',
        'me', 'the', 'all', 'events', 'logs', 'data', 'get', 'can', 'you',
        'please', 'want', 'need', 'looking', 'for', 'with', 'from', 'and',
        'or', 'not', 'any', 'some', 'that', 'this', 'those', 'have', 'has',
        'are', 'were', 'was', 'will', 'would', 'could', 'should', 'what',
        'how', 'when', 'where', 'which', 'index', 'sourcetype', 'using',
        'last', 'past', 'minutes', 'hours', 'days', 'week', 'month',
        'tstats', 'term', 'prefix', 'spl', 'query', 'count',
        'use', 'explain', 'about', 'tell', 'teach', 'understand',
        'difference', 'between', 'syntax', 'example', 'examples',
    }

    # Index patterns (order matters - more specific first)
    INDEX_PATTERNS = [
        r'index[=\s]+(\w+)',  # "index=network" or "index network"
        r'(?:in|from)\s+(\w+)\s+index',  # "in firewall index"
        r'on\s+index\s+(\w+)',  # "on index network"
        r'(?:in|from)\s+index\s+(\w+)',  # "in index firewall"
    ]

    SOURCETYPE_PATTERNS = [
        r'sourcetype[=\s]+(\w+)',
        r'log\s+type\s+(\w+)',
    ]

    SOURCE_PATTERNS = [
        r'source[=\s]+([\w\./-]+)',
        r'file\s+([\w\./-]+)',
    ]

    # Words to exclude from being matched as index names
    INDEX_BLACKLIST = ['last', 'the', 'this', 'that', 'events', 'data', 'some', 'any']

    # Keyword extraction patterns (allow wider token set)
    KEYWORD_PATTERNS = [
        r'TERM\s*\([\'""]?([A-Za-z0-9_.:/-]+)[\'""]?\)',  # Already has TERM()
        r'(?:word|keyword)\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?',  # "word error" or "keyword denied"
        r'for\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?(?:\s+(?:on|in))',  # "for error on/in"
        r'search(?:ing)?\s+for\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?\s+(?:and|or)\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?',  # "search for X and Y"
        r'search(?:ing)?\s+for\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?',  # "searching for failed"
        r'find\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?',  # "find denied"
        r'containing\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?',  # "containing error"
        r'show(?:\s+me)?\s+[\'""]?([A-Za-z0-9_.:/-]+)[\'""]?',  # "show me errors"
    ]

    COMMON_INDEX_HINTS = {
        "firewall": "firewall",
        "pan": "pan",
        "proxy": "proxy",
        "wineventlog": "wineventlog",
        "windows": "wineventlog",
        "linux": "os",
        "os": "os",
        "endpoint": "edr",
        "edr": "edr",
        "ids": "ids",
        "vpn": "vpn",
    }

    FIELD_KEYWORDS = {
        "user": ["user", "username", "account", "principal"],
        "src": ["src", "source", "client", "src_ip", "ip"],
        "dest": ["dest", "destination", "server", "dst", "dst_ip", "host"],
        "url": ["url", "uri", "path"],
        "action": ["action", "result", "decision", "verdict", "allowed", "denied"],
        "status": ["status", "code", "status_code"],
    }

    @staticmethod
    def _is_ip(token: str) -> bool:
        try:
            ipaddress.ip_address(token)
            return True
        except Exception:
            return False

    @staticmethod
    def _is_cidr(token: str) -> bool:
        try:
            ipaddress.ip_network(token, strict=False)
            return True
        except Exception:
            return False

    @staticmethod
    def _classify_token(token: str) -> Tuple[Optional[str], str]:
        """Return (field, value) guess for a token."""
        if SPLTemplateEngine._is_ip(token):
            return "src_ip", token
        if SPLTemplateEngine._is_cidr(token):
            return "src_ip", token
        if re.fullmatch(r"\d{3}", token):  # status code
            return "status", token
        if re.fullmatch(r"[A-Za-z0-9._%-]+@[A-Za-z0-9.-]+", token):
            return "user", token
        if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,5}", token):
            return "dest", token
        return None, token

    @staticmethod
    def _escape_term(term: str) -> str:
        """Escape/quote a keyword for safe TERM() usage."""
        escaped = term.replace('"', r'\"')
        if re.search(r'[^A-Za-z0-9_]', term):
            return f'"{escaped}"'
        return term

    @staticmethod
    def _detect_aggregation_type(query_lower: str) -> str:
        """Detect the desired aggregation type from user query."""
        for agg_type, patterns in SPLTemplateEngine.AGGREGATION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return agg_type
        return 'stats_count'  # default

    @staticmethod
    def _extract_groupby_fields(query_lower: str) -> List[str]:
        """Extract group-by fields from natural language."""
        fields = []
        for pattern in SPLTemplateEngine.GROUPBY_PATTERNS:
            match = re.search(pattern, query_lower)
            if match:
                raw = match.group(1)
                fields = [f.strip() for f in raw.split(',') if f.strip()]
                break
        return fields

    @staticmethod
    def _infer_index_from_context(query_lower: str) -> Optional[str]:
        """Infer the index from context keywords using COMMON_INDEX_HINTS."""
        for hint_keyword, index_name in SPLTemplateEngine.COMMON_INDEX_HINTS.items():
            if hint_keyword in query_lower:
                return index_name
        return None

    @staticmethod
    def detect_intent(user_query: str) -> QueryIntent:
        """
        Detect user intent from natural language query.

        Args:
            user_query: User's natural language question

        Returns:
            QueryIntent object with detected parameters
        """
        query_lower = user_query.lower()
        intent = QueryIntent(query_type='unknown', keywords=[], groupby_fields=[])

        # Detect if user wants tstats + TERM specifically
        if 'tstats' in query_lower and 'term' in query_lower:
            intent.query_type = 'term_search'
            intent.confidence = 0.9
        elif 'term(' in query_lower or 'term ' in query_lower:
            intent.query_type = 'term_search'
            intent.confidence = 0.8
        elif 'datamodel' in query_lower or 'cim' in query_lower:
            intent.query_type = 'datamodel'
            intent.confidence = 0.8
        elif any(kw in query_lower for kw in ['search', 'find', 'show', 'get', 'give', 'list', 'count', 'top', 'rare']):
            intent.query_type = 'term_search'  # Default to TERM search
            intent.confidence = 0.6

        # Extract index (explicit patterns first)
        for pattern in SPLTemplateEngine.INDEX_PATTERNS:
            match = re.search(pattern, query_lower)
            if match:
                candidate_index = match.group(1)
                if candidate_index not in SPLTemplateEngine.INDEX_BLACKLIST:
                    intent.index = candidate_index
                    break

        # Fallback: infer index from context keywords
        if not intent.index:
            intent.index = SPLTemplateEngine._infer_index_from_context(query_lower)

        # Extract sourcetype
        for pattern in SPLTemplateEngine.SOURCETYPE_PATTERNS:
            match = re.search(pattern, query_lower)
            if match:
                intent.sourcetype = match.group(1)
                break

        # Extract source
        for pattern in SPLTemplateEngine.SOURCE_PATTERNS:
            match = re.search(pattern, query_lower)
            if match:
                intent.source = match.group(1)
                break

        # Extract keywords
        for pattern in SPLTemplateEngine.KEYWORD_PATTERNS:
            matches = re.findall(pattern, query_lower, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    intent.keywords.extend([m for m in match if m])
                else:
                    intent.keywords.append(match)

        # Fallback token extraction for hyphenated / dotted terms and CIDRs
        if not intent.keywords:
            fallback_tokens = re.findall(r'[A-Za-z0-9_.:/-]+', query_lower)
            intent.keywords.extend(tok for tok in fallback_tokens if len(tok) >= 3)

        # Filter noise words from keywords
        intent.keywords = [
            k for k in dict.fromkeys(intent.keywords)
            if k and k not in SPLTemplateEngine.NOISE_WORDS
        ]

        # Extract group-by fields
        intent.groupby_fields = SPLTemplateEngine._extract_groupby_fields(query_lower)

        # Extract time range
        for pattern, converter in SPLTemplateEngine.TIME_PATTERNS.items():
            match = re.search(pattern, query_lower)
            if match:
                intent.time_range = converter(match)
                break

        # Default time range if not specified
        if not intent.time_range:
            intent.time_range = '-15m'  # Default to 15 minutes

        return intent

    @staticmethod
    def _build_aggregation_tail(intent: QueryIntent, query_lower: str) -> str:
        """Build the aggregation tail (| stats/timechart/top/rare/table) from detected intent."""
        agg_type = SPLTemplateEngine._detect_aggregation_type(query_lower)
        by_fields = intent.groupby_fields

        if agg_type == 'timechart':
            span = '1h'
            if re.search(r'\bper minute\b|\bminutely\b', query_lower):
                span = '1m'
            elif re.search(r'\bper 5 min\b', query_lower):
                span = '5m'
            elif re.search(r'\bper 15 min\b', query_lower):
                span = '15m'
            elif re.search(r'\bdaily\b|\bper day\b', query_lower):
                span = '1d'
            by_clause = f" by {by_fields[0]}" if by_fields else ""
            return f" | timechart span={span} count{by_clause}"
        elif agg_type == 'top':
            limit = 10
            limit_match = re.search(r'top\s+(\d+)', query_lower)
            if limit_match:
                limit = int(limit_match.group(1))
            field = by_fields[0] if by_fields else "host"
            return f" | top limit={limit} {field}"
        elif agg_type == 'rare':
            limit = 20
            field = by_fields[0] if by_fields else "sourcetype"
            return f" | rare limit={limit} {field}"
        elif agg_type == 'table':
            fields = ", ".join(by_fields) if by_fields else "_time, host, sourcetype, _raw"
            return f" | table {fields}"
        elif agg_type == 'stats_avg':
            field = by_fields[0] if by_fields else "host"
            return f" | stats avg(response_time) as avg_response_time, count by {field}"
        elif agg_type == 'stats_sum':
            field = by_fields[0] if by_fields else "host"
            return f" | stats sum(bytes) as total_bytes, count by {field} | sort -total_bytes"
        else:
            # stats_count (default)
            by_clause = f" by {', '.join(by_fields)}" if by_fields else ""
            return f" | stats count{by_clause}"

    @staticmethod
    def generate_term_query(intent: QueryIntent) -> str:
        """
        Generate a safe search query from intent. Prefers tstats when all
        detected tokens can be mapped to fields; otherwise falls back to search.

        Args:
            intent: Detected query intent

        Returns:
            Valid SPL query string
        """
        terms = intent.keywords or ['error']
        query_lower = ' '.join(terms).lower()

        field_clauses: List[str] = []
        text_terms: List[str] = []

        for kw in terms:
            field, value = SPLTemplateEngine._classify_token(kw)
            if not field:
                # Heuristic mapping from keywords
                for f, synonyms in SPLTemplateEngine.FIELD_KEYWORDS.items():
                    if kw.lower() in synonyms:
                        field = f
                        break
            if field:
                field_clauses.append(f"TERM({field}={SPLTemplateEngine._escape_term(value)})")
            else:
                text_terms.append(f"\"{SPLTemplateEngine._escape_term(kw)}\"")

        # Determine aggregation type from intent context
        agg_type = SPLTemplateEngine._detect_aggregation_type(
            ' '.join(intent.keywords or []) + ' ' + (intent.query_type or '')
        )

        # Try tstats when we have an index and at least one fielded clause and no free-text terms
        # (only for count-based aggregations — timechart/top/rare need regular search)
        if (intent.index and field_clauses and not text_terms
                and agg_type in ('stats_count', 'stats_sum')):
            parts = ["| tstats count where", f"index={intent.index}"]
            if intent.sourcetype:
                parts.append(f"sourcetype={intent.sourcetype}")
            if intent.source:
                parts.append(f"source={intent.source}")
            parts.extend(field_clauses)
            parts.append(f"earliest={intent.time_range}")
            parts.append("latest=now")
            if intent.groupby_fields:
                parts.append(f"by {', '.join(intent.groupby_fields)}")
            return ' '.join(parts)

        # Otherwise fall back to search
        search_parts = ["search"]
        if intent.index:
            search_parts.append(f"index={intent.index}")
        if intent.sourcetype:
            search_parts.append(f"sourcetype={intent.sourcetype}")
        if intent.source:
            search_parts.append(f"source={intent.source}")

        if field_clauses:
            search_parts.extend(field_clauses)
        if text_terms:
            search_parts.append("(" + " OR ".join(text_terms) + ")")

        search_parts.append(f"earliest={intent.time_range}")
        search_parts.append("latest=now")

        return ' '.join(search_parts)

    @staticmethod
    def generate_datamodel_query(intent: QueryIntent) -> str:
        """
        Generate tstats + data model query.

        Args:
            intent: Detected query intent

        Returns:
            Valid SPL query string
        """
        # Detect datamodel from keywords
        datamodel_map = {
            'auth': ('Authentication', 'Authentication.Authentication'),
            'authentication': ('Authentication', 'Authentication.Authentication'),
            'login': ('Authentication', 'Authentication.Authentication'),
            'logon': ('Authentication', 'Authentication.Authentication'),
            'network': ('Network_Traffic', 'Network_Traffic.All_Traffic'),
            'firewall': ('Network_Traffic', 'Network_Traffic.All_Traffic'),
            'traffic': ('Network_Traffic', 'Network_Traffic.All_Traffic'),
            'web': ('Web', 'Web.Web'),
            'http': ('Web', 'Web.Web'),
            'proxy': ('Web', 'Web.Web'),
            'endpoint': ('Endpoint', 'Endpoint.Processes'),
            'process': ('Endpoint', 'Endpoint.Processes'),
            'dns': ('Network_Resolution', 'Network_Resolution.DNS'),
            'email': ('Email', 'Email.All_Email'),
            'malware': ('Malware', 'Malware.Malware_Attacks'),
            'ids': ('Intrusion_Detection', 'Intrusion_Detection.IDS_Attacks'),
            'intrusion': ('Intrusion_Detection', 'Intrusion_Detection.IDS_Attacks'),
            'change': ('Change', 'Change.All_Changes'),
            'vulnerability': ('Vulnerabilities', 'Vulnerabilities.Vulnerabilities'),
        }

        # Default by-fields per datamodel
        datamodel_by_fields = {
            'Authentication': ['Authentication.user', 'Authentication.src'],
            'Network_Traffic': ['All_Traffic.src', 'All_Traffic.dest'],
            'Web': ['Web.url', 'Web.status'],
            'Endpoint': ['Processes.process_name', 'Processes.dest'],
            'Network_Resolution': ['DNS.query', 'DNS.src'],
            'Email': ['All_Email.src_user', 'All_Email.recipient'],
            'Malware': ['Malware_Attacks.dest', 'Malware_Attacks.signature'],
            'Intrusion_Detection': ['IDS_Attacks.src', 'IDS_Attacks.dest'],
            'Change': ['All_Changes.user', 'All_Changes.object'],
        }

        dm_name = None
        datamodel = None
        for keyword, (name, dm) in datamodel_map.items():
            if keyword in ' '.join(intent.keywords or []).lower():
                dm_name = name
                datamodel = dm
                break

        if not datamodel:
            dm_name = 'Network_Traffic'
            datamodel = 'Network_Traffic.All_Traffic'

        query_parts = [
            '| tstats summariesonly=t count from',
            f'datamodel={datamodel}',
        ]

        # Add WHERE clause with TERM for relevant keywords (exclude noise)
        dm_noise = set(datamodel_map.keys())
        filter_keywords = [kw for kw in (intent.keywords or []) if kw not in dm_noise]
        if filter_keywords:
            where_clauses = [f'TERM({SPLTemplateEngine._escape_term(kw)})' for kw in filter_keywords]
            query_parts.append('where')
            query_parts.append(' '.join(where_clauses))

        # Add time range
        query_parts.append(f'earliest={intent.time_range}')
        query_parts.append('latest=now')

        # Add by-fields from intent or datamodel defaults
        if intent.groupby_fields:
            query_parts.append(f"by {', '.join(intent.groupby_fields)}")
        elif dm_name in datamodel_by_fields:
            by_fields = datamodel_by_fields[dm_name]
            query_parts.append(f"by {', '.join(by_fields)}")

        return ' '.join(query_parts)

    @staticmethod
    def generate_query(user_query: str) -> Tuple[str, QueryIntent, str]:
        """
        Main entry point - generate SPL query from natural language.

        Args:
            user_query: User's natural language question

        Returns:
            Tuple of (spl_query, intent, explanation)
        """
        # Detect intent
        intent = SPLTemplateEngine.detect_intent(user_query)

        # Detect aggregation type for explanation
        agg_type = SPLTemplateEngine._detect_aggregation_type(user_query.lower())

        # Generate query based on intent
        if intent.query_type == 'term_search':
            base_query = SPLTemplateEngine.generate_term_query(intent)
            # Only append aggregation tail if the query doesn't already have one
            # (tstats queries already include their own aggregation)
            if base_query.startswith("| tstats"):
                query = base_query
            else:
                agg_tail = SPLTemplateEngine._build_aggregation_tail(intent, user_query.lower())
                query = base_query + agg_tail
            kw_str = ', '.join(intent.keywords or ['events'])
            explanation = f"Searches for {kw_str}"
            if intent.index:
                explanation += f" in {intent.index} index"
            if intent.groupby_fields:
                explanation += f" grouped by {', '.join(intent.groupby_fields)}"
            explanation += f" over the last {intent.time_range.replace('-', '')}."
            if agg_type != 'stats_count':
                explanation += f" Uses {agg_type.replace('_', ' ')} aggregation."

        elif intent.query_type == 'datamodel':
            query = SPLTemplateEngine.generate_datamodel_query(intent)
            explanation = "Uses CIM data model for normalized field search with tstats acceleration."

        else:
            # Fallback to basic TERM query
            base_query = SPLTemplateEngine.generate_term_query(intent)
            if base_query.startswith("| tstats"):
                query = base_query
            else:
                agg_tail = SPLTemplateEngine._build_aggregation_tail(intent, user_query.lower())
                query = base_query + agg_tail
            explanation = "Basic keyword search using exact terms."

        return query, intent, explanation


# Example usage
if __name__ == "__main__":
    test_cases = [
        "Give me an example with tstats and TERM for word error on index network with events in last 15 minutes",
        "Search for 'failed' and 'timeout' in firewall index last hour",
        "Count authentication failures using TERM",
        "Find denied events in network index",
        "Show me errors in the last 5 minutes",
    ]

    print("=" * 70)
    print("SPL TEMPLATE ENGINE TEST")
    print("=" * 70)
    print()

    for test in test_cases:
        print(f"User: {test}")
        print()

        query, intent, explanation = SPLTemplateEngine.generate_query(test)

        print(f"Intent: {intent.query_type} (confidence: {intent.confidence})")
        print(f"  - Index: {intent.index}")
        print(f"  - Keywords: {intent.keywords}")
        print(f"  - Time: {intent.time_range}")
        print()
        print(f"Generated Query:")
        print(f"```spl")
        print(f"{query}")
        print(f"```")
        print()
        print(f"Explanation: {explanation}")
        print()
        print("-" * 70)
        print()
