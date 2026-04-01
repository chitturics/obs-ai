"""
Knowledge Graph — RAG Context Generation Methods.

Mixin class extracted from knowledge_graph.py for size management.
SplunkKnowledgeGraph inherits from KnowledgeGraphRAGMixin.

Provides:
- analyze_spl_query / inject_spl_entities
- _extract_entity_mentions / _extract_entity_mentions_fuzzy
- _analyze_inline_spl / _intent_rel_priority
- expand_query_with_graph
- generate_context_for_query (2-hop, relevance-ranked)
- _edit_distance (Levenshtein)
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple


class KnowledgeGraphRAGMixin:
    """
    Mixin providing GraphRAG context generation for SplunkKnowledgeGraph.

    Requires the host class to have these attributes:
        _entity_index, _name_index, _type_index,
        get_neighbors()
    """

    # --- Context generation for RAG ---

    def analyze_spl_query(self, spl: str) -> Dict[str, Any]:
        """Public interface to SPL query analysis. Returns structured decomposition."""
        from chat_app.kg_extractors_basic import SPLQueryAnalyzer
        return SPLQueryAnalyzer.analyze(spl)

    def inject_spl_entities(self, spl: str, search_name: str = "user_query") -> int:
        """Analyze SPL and inject entities into the live graph. Returns entity count."""
        from chat_app.kg_extractors_basic import SPLQueryAnalyzer
        ents, rels = SPLQueryAnalyzer.to_entities_and_relationships(spl, search_name)
        for e in ents:
            self.add_entity(e)
        for r in rels:
            self.add_relationship(r)
        return len(ents)

    def _extract_entity_mentions(self, text: str) -> list:
        """Extract entity mentions from text using name index."""
        text_lower = text.lower()
        tokens = set(re.findall(r'[a-z_][a-z0-9_.:-]+', text_lower))

        found = []
        seen_ids = set()

        # First pass: exact token matches against entity names
        for token in tokens:
            eid = self._name_index.get(token)
            if eid and eid not in seen_ids:
                entity = self._entity_index[eid]
                found.append(entity)
                seen_ids.add(eid)

        # Second pass: multi-word entity names (e.g., saved search names)
        for name_lower, eid in self._name_index.items():
            if eid in seen_ids:
                continue
            if " " in name_lower or "_" in name_lower:
                if name_lower in text_lower:
                    maybe_entity = self._entity_index.get(eid)
                    if maybe_entity:
                        found.append(maybe_entity)
                        seen_ids.add(eid)

        # Sort: Commands first, then SavedSearch/Macro, then Functions, then others
        type_order = {
            "Command": 0, "SavedSearch": 1, "Macro": 2,
            "Function": 3, "Index": 4, "Sourcetype": 5,
            "Field": 6, "Lookup": 7,
        }
        found.sort(key=lambda e: type_order.get(e.entity_type, 8))

        return found[:8]  # Expanded from 5 to 8 for multi-context

    def _analyze_inline_spl(self, text: str) -> Optional[str]:
        """Detect and analyze inline SPL in user input, return context string."""
        # Look for SPL-like patterns (pipe-delimited commands)
        spl_match = re.search(r'(?:^|\s)((?:index\s*=|source\s*=|\|)\s*.{10,})', text)
        if not spl_match:
            # Try backtick-delimited SPL
            bt_match = re.search(r'`([^`]{10,})`', text)
            if bt_match:
                spl_text = bt_match.group(1)
            else:
                return None
        else:
            spl_text = spl_match.group(1)

        from chat_app.kg_extractors_basic import SPLQueryAnalyzer
        analysis = SPLQueryAnalyzer.analyze(spl_text)

        # Only provide context if we found meaningful entities
        parts = []
        if analysis["commands"]:
            parts.append(f"Commands: {', '.join(analysis['commands'][:8])}")
        if analysis["functions"]:
            parts.append(f"Functions: {', '.join(analysis['functions'][:6])}")
        if analysis["indexes"]:
            parts.append(f"Indexes: {', '.join(analysis['indexes'][:5])}")
        if analysis["sourcetypes"]:
            parts.append(f"Sourcetypes: {', '.join(analysis['sourcetypes'][:5])}")
        if analysis["fields"]:
            parts.append(f"Fields: {', '.join(analysis['fields'][:10])}")
        if analysis["macros"]:
            parts.append(f"Macros: {', '.join(analysis['macros'][:5])}")
        if analysis["lookups"]:
            parts.append(f"Lookups: {', '.join(analysis['lookups'][:5])}")
        if analysis["datamodels"]:
            parts.append(f"Datamodels: {', '.join(analysis['datamodels'][:3])}")
        if analysis["has_tstats"]:
            parts.append("Uses tstats (summarization/acceleration)")
        if analysis["filters"]:
            filter_strs = [f"{f['field']}={f['value']}" for f in analysis["filters"][:5]]
            parts.append(f"Filters: {', '.join(filter_strs)}")

        if not parts:
            return None

        return "**SPL Query Analysis:**\n" + "\n".join(f"- {p}" for p in parts)

    @staticmethod
    def _intent_rel_priority(intent: str) -> List[str]:
        """Return prioritized relationship types based on intent."""
        if intent in ("spl_generation", "raw_spl", "nlp_to_spl"):
            return ["has_arguments", "uses_functions", "pipes_to",
                     "operates_on", "alternative_to", "compatible_with",
                     "uses_index", "uses_field", "uses_macro",
                     "reads_config", "configures"]
        elif intent in ("troubleshooting", "error_analysis"):
            return ["compatible_with", "requires", "alternative_to",
                     "uses_functions", "operates_on", "uses_sourcetype",
                     "reads_config", "configured_by", "related_stanza"]
        elif intent in ("config_lookup", "spec_lookup"):
            return ["defines", "belongs_to", "references", "enriches",
                     "extracts_field", "has_source", "has_sourcetype",
                     "configures", "reads_config", "related_stanza",
                     "configured_by", "targets_index"]
        elif intent in ("optimization", "performance"):
            return ["alternative_to", "pipes_to", "compatible_with",
                     "uses_functions", "accelerated_by", "summarizes",
                     "reads_config", "configures"]
        elif intent in ("saved_search", "macro_lookup"):
            return ["uses_index", "uses_field", "uses_sourcetype",
                     "uses_macro", "uses_lookup", "uses_command",
                     "accelerated_by", "configures"]
        else:
            return ["has_arguments", "uses_functions", "pipes_to",
                     "alternative_to", "operates_on", "compatible_with",
                     "uses_index", "uses_field", "configures",
                     "reads_config"]

    # --- GraphRAG: Query expansion using KG relationships ---

    def expand_query_with_graph(self, query: str, intent: str,
                                max_terms: int = 8) -> List[str]:
        """Use KG to generate expanded search terms for better retrieval.

        Resolves entities mentioned in the query, then traverses their
        relationships to find semantically related concepts. Returns a
        list of additional search terms that can be appended to or used
        alongside the original query for vector search.

        Example: "tstats" -> ["tstats", "datamodel", "summariesonly",
                              "accelerated search", "from"]
        """
        mentioned = self._extract_entity_mentions(query)
        if not mentioned:
            return []

        # Collect expansion terms weighted by relevance
        expansion_scores: Dict[str, float] = {}
        priority_rels = self._intent_rel_priority(intent)

        for entity in mentioned[:4]:  # Limit seed entities
            neighbors = self.get_neighbors(entity.id, direction="both")
            for n in neighbors:
                rel_type = n.get("rel_type", "")
                # Higher weight for priority relationship types
                base_weight = 1.0
                if rel_type in priority_rels:
                    idx = priority_rels.index(rel_type)
                    base_weight = 2.0 - (idx * 0.1)  # First rels score higher

                edge_weight = n.get("weight", 1.0)
                combined = base_weight * edge_weight

                # Get the target/source name
                if n.get("direction") == "outgoing":
                    term = n.get("target_name", "")
                    term_type = n.get("target_type", "")
                else:
                    term = n.get("source_name", "")
                    term_type = n.get("source_type", "")

                if not term or len(term) < 2:
                    continue
                # Skip config stanza paths (too specific for query expansion)
                if "/" in term and term_type == "ConfigStanza":
                    continue
                # Skip arguments (too granular)
                if term_type == "Argument":
                    combined *= 0.3

                term_lower = term.lower()
                # Don't expand with terms already in the query
                if term_lower in query.lower():
                    continue

                expansion_scores[term_lower] = max(
                    expansion_scores.get(term_lower, 0), combined
                )

            # Also add the entity description keywords for richer expansion
            if entity.description:
                desc_words = re.findall(r'[a-z]{4,}', entity.description.lower())
                for w in desc_words[:3]:
                    if w not in query.lower() and w not in (
                        "command", "function", "field", "splunk", "search",
                        "that", "this", "with", "from", "used", "uses",
                    ):
                        expansion_scores[w] = max(
                            expansion_scores.get(w, 0), 0.5
                        )

        # Sort by score and return top terms
        ranked = sorted(expansion_scores.items(), key=lambda x: -x[1])
        return [term for term, _score in ranked[:max_terms]]

    # --- GraphRAG: Enhanced context with 2-hop traversal & relevance ranking ---

    def generate_context_for_query(self, user_input: str, intent: str,
                                   max_facts: int = 12) -> Optional[str]:
        """Generate graph-augmented context for a user query.

        Enhanced version with:
        1. Fuzzy entity resolution (edit distance fallback)
        2. 2-hop relationship traversal for richer context
        3. Relevance-ranked facts (not just listed)
        4. Entity descriptions included for grounding
        5. Inline SPL analysis for deeper understanding
        """
        mentioned = self._extract_entity_mentions_fuzzy(user_input)

        # Also analyze any inline SPL in the query for deeper context
        spl_context = self._analyze_inline_spl(user_input)

        if not mentioned and not spl_context:
            return None

        # Prioritize relationship types based on intent
        priority_rels = self._intent_rel_priority(intent)

        # Collect all facts with relevance scores for ranking
        scored_facts: List[Tuple[float, str, str]] = []  # (score, entity_name, fact_line)

        for entity in mentioned:
            # --- 1-hop neighbors ---
            out_neighbors = self.get_neighbors(entity.id, direction="out")
            in_neighbors = self.get_neighbors(entity.id, direction="in")

            if not out_neighbors and not in_neighbors:
                # Still include the entity if it has a description
                if entity.description:
                    scored_facts.append((
                        0.5, entity.name,
                        f"**{entity.name}** ({entity.entity_type}) — {entity.description[:150]}"
                    ))
                continue

            # Entity header with description
            desc_snippet = entity.description[:150] if entity.description else ""
            header = f"**{entity.name}** ({entity.entity_type})"
            if desc_snippet:
                header += f" — {desc_snippet}"
            scored_facts.append((1.5, entity.name, header))

            # Group outgoing by relationship type
            grouped: Dict[str, List[Dict]] = defaultdict(list)
            for n in out_neighbors:
                grouped[n["rel_type"]].append(n)

            # Group incoming by relationship type
            in_grouped: Dict[str, List[Dict]] = defaultdict(list)
            for n in in_neighbors:
                in_grouped[n["rel_type"]].append(n)

            # Score and collect outgoing facts
            for rel_type, targets in grouped.items():
                score = 1.0
                if rel_type in priority_rels:
                    idx = priority_rels.index(rel_type)
                    score = 2.0 - (idx * 0.08)

                target_names = [t["target_name"] for t in targets[:6]]
                label = rel_type.replace("_", " ").title()
                scored_facts.append((
                    score, entity.name,
                    f"- {label}: {', '.join(target_names)}"
                ))

                # --- 2-hop traversal for high-priority relationships ---
                if score > 1.2 and len(scored_facts) < max_facts * 2:
                    for t in targets[:3]:
                        hop2_neighbors = self.get_neighbors(
                            t["target_id"], direction="out"
                        )
                        for h2 in hop2_neighbors[:3]:
                            h2_rel = h2.get("rel_type", "")
                            if h2_rel in priority_rels:
                                scored_facts.append((
                                    score * 0.5, t["target_name"],
                                    f"  - {t['target_name']} {h2_rel.replace('_', ' ')}: {h2['target_name']}"
                                ))

            # Valuable incoming relationships
            _valuable_incoming = {
                "configures", "reads_config", "configured_by",
                "related_stanza", "targets_index", "defines",
                "uses_functions", "pipes_to", "references",
                "uses_command", "uses_index", "uses_field",
            }
            for rel_type, sources in in_grouped.items():
                if rel_type not in _valuable_incoming:
                    continue
                score = 0.8
                if rel_type in priority_rels:
                    idx = priority_rels.index(rel_type)
                    score = 1.5 - (idx * 0.08)
                source_names = [s["source_name"] for s in sources[:4]]
                label = rel_type.replace("_", " ").title()
                scored_facts.append((
                    score, entity.name,
                    f"- {label} (from): {', '.join(source_names)}"
                ))

        # Rank facts by score and take top max_facts
        scored_facts.sort(key=lambda x: -x[0])

        # Group by entity for readable output
        entity_order: List[str] = []
        entity_facts: Dict[str, List[str]] = defaultdict(list)
        for _score, ename, line in scored_facts:
            if ename not in entity_order:
                entity_order.append(ename)
            entity_facts[ename].append(line)

        sections = []
        facts_used = 0
        for ename in entity_order:
            if facts_used >= max_facts:
                break
            lines = entity_facts[ename]
            remaining = max_facts - facts_used
            section_lines = lines[:remaining + 1]  # +1 for header
            if section_lines:
                sections.append("\n".join(section_lines))
                facts_used += len(section_lines) - 1  # Header doesn't count

        # Add SPL analysis context
        if spl_context:
            sections.append(spl_context)

        if not sections:
            return None

        return "### Knowledge Graph Context\n\n" + "\n\n".join(sections)

    def _extract_entity_mentions_fuzzy(self, text: str) -> list:
        """Extract entity mentions with fuzzy matching fallback.

        Extends _extract_entity_mentions with:
        1. Exact token matches (fast path)
        2. Multi-word entity name matches
        3. Edit-distance fuzzy matching for near-misses (e.g., "timechrt" -> "timechart")
        """
        # Start with exact matching
        found = self._extract_entity_mentions(text)
        found_ids = {e.id for e in found}

        # Fuzzy matching for remaining tokens that didn't match
        text_lower = text.lower()
        tokens = set(re.findall(r'[a-z_][a-z0-9_.:-]+', text_lower))

        # Only attempt fuzzy match for tokens that look like they could be
        # SPL commands or entity names (3+ chars, not stopwords)
        _stopwords = {
            "the", "and", "for", "with", "how", "what", "does", "can",
            "this", "that", "from", "into", "about", "between", "show",
            "list", "get", "use", "using", "help", "please", "explain",
            "why", "when", "where", "which",
        }
        candidate_tokens = {
            t for t in tokens
            if len(t) >= 3 and t not in _stopwords
            and not self._name_index.get(t)  # Skip already-matched
        }

        if candidate_tokens:
            # Build a quick list of entity names to match against
            # (only Command, Function, Index, Lookup, Datamodel — not Fields)
            matchable_types = {"Command", "Function", "Index", "Lookup", "Datamodel", "Macro"}
            matchable_names: Dict[str, str] = {}  # name_lower -> entity_id
            for name_lower, eid in self._name_index.items():
                entity = self._entity_index.get(eid)
                if entity and entity.entity_type in matchable_types:
                    matchable_names[name_lower] = eid

            for token in candidate_tokens:
                best_match = None
                best_dist = 3  # Maximum edit distance threshold
                for name_lower, eid in matchable_names.items():
                    if eid in found_ids:
                        continue
                    dist = self._edit_distance(token, name_lower, max_dist=best_dist)
                    if dist < best_dist and dist <= max(1, len(token) // 4):
                        best_dist = dist
                        best_match = eid
                if best_match and best_match not in found_ids:
                    entity = self._entity_index.get(best_match)
                    if entity:
                        found.append(entity)
                        found_ids.add(best_match)

        # Sort: Commands first, then SavedSearch/Macro, then Functions, then others
        type_order = {
            "Command": 0, "SavedSearch": 1, "Macro": 2,
            "Function": 3, "Index": 4, "Sourcetype": 5,
            "Field": 6, "Lookup": 7,
        }
        found.sort(key=lambda e: type_order.get(e.entity_type, 8))

        return found[:10]

    @staticmethod
    def _edit_distance(s1: str, s2: str, max_dist: int = 3) -> int:
        """Compute Levenshtein edit distance with early termination."""
        if abs(len(s1) - len(s2)) > max_dist:
            return max_dist + 1
        if s1 == s2:
            return 0

        # Use two-row DP with early termination
        len1, len2 = len(s1), len(s2)
        if len1 > len2:
            s1, s2 = s2, s1
            len1, len2 = len2, len1

        prev = list(range(len1 + 1))
        for j in range(1, len2 + 1):
            curr = [j] + [0] * len1
            row_min = j
            for i in range(1, len1 + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                curr[i] = min(curr[i - 1] + 1, prev[i] + 1, prev[i - 1] + cost)
                row_min = min(row_min, curr[i])
            if row_min > max_dist:
                return max_dist + 1
            prev = curr
        return prev[len1]


# ---------------------------------------------------------------------------
# SPLQueryAnalyzer is imported at class-use time to avoid circular imports.
# The mixin methods that use it (analyze_spl_query, inject_spl_entities,
# _analyze_inline_spl) call it via module-level lazy import below.
# ---------------------------------------------------------------------------

def _get_spl_analyzer():
    """Lazy import SPLQueryAnalyzer to avoid circular import."""
    from chat_app.kg_builders import SPLQueryAnalyzer
    return SPLQueryAnalyzer


# Make SPLQueryAnalyzer available as a module-level name for the mixin methods
# that reference it directly (they will see it via the class scope or globals).
try:
    from chat_app.kg_builders import SPLQueryAnalyzer  # noqa: F401
except ImportError:
    SPLQueryAnalyzer = None  # type: ignore[assignment,misc]
