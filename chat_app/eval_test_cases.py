"""
10,000+ Splunk search test cases for RAG evaluation.

Each test case has:
  - query: The user question
  - category: Topic category
  - expected_collection: Which collection should match
  - expected_keywords: Keywords expected in retrieved context
  - difficulty: easy | medium | hard
  - expected_type: command_help | optimization | generation | config | troubleshoot

Usage:
    from chat_app.eval_test_cases import generate_all_test_cases
    cases = generate_all_test_cases()
    print(f"Generated {len(cases)} test cases")

This module re-exports everything from the split sub-modules for backward compatibility.
"""

import random
from typing import List, Dict

# Re-export the base dataclass
from chat_app.eval_test_cases_base import TestCase  # noqa: F401

# Re-export SPL data constants and generators
from chat_app.eval_test_cases_spl import (  # noqa: F401
    SPL_COMMANDS,
    COMMAND_TEMPLATES,
    COMMAND_FAMILIES,
    OPTIMIZATION_TEMPLATES,
    SAMPLE_SPL_QUERIES,
    NL_TO_SPL_QUERIES,
    EVAL_FUNCTIONS,
    EVAL_TEMPLATES,
    CIM_MODELS,
    CIM_TEMPLATES,
    INDEXES,
    STAT_FUNCS,
    BY_FIELDS,
    TIME_RANGES,
    SCENARIO_TEMPLATES,
    FIELDS_PER_INDEX,
    PIPELINE_COMBOS,
    PIPELINE_TEMPLATES,
    generate_spl_test_cases,
    _generate_command_help_cases,
    _generate_command_family_cases,
    _generate_optimization_cases,
    _generate_nl_to_spl_cases,
    _generate_eval_function_cases,
    _generate_cim_cases,
    _generate_raw_spl_improvement_cases,
    _generate_scenario_cases,
    _generate_pipeline_cases,
    _generate_field_operation_cases,
    _generate_use_case_cases,
    _generate_advanced_spl_cases,
    _generate_stats_function_cases,
)

# Re-export general data constants and generators
from chat_app.eval_test_cases_general import (  # noqa: F401
    CONF_FILES,
    CONF_TEMPLATES,
    CONF_SCENARIOS,
    TROUBLESHOOTING_QUERIES,
    BEST_PRACTICE_QUERIES,
    ORG_QUERIES,
    CRIBL_QUERIES,
    COMPOUND_QUERIES,
    generate_general_test_cases,
    _generate_config_cases,
    _generate_troubleshooting_cases,
    _generate_best_practice_cases,
    _generate_org_cases,
    _generate_cribl_cases,
    _generate_compound_cases,
)


def generate_all_test_cases(seed: int = 42) -> List[TestCase]:
    """
    Generate 10,000+ comprehensive Splunk search test cases.

    Categories:
      - command_help:       ~2,088 (174 commands × 12 templates)
      - command_families:   ~90 (9 families × 10 questions)
      - optimization:       ~273 (30 queries × 8 + 11 commands × 3)
      - nl_to_spl:          ~480 (60 queries × 8 variations)
      - config:             ~1,200+ (26 conf files × templates × scenarios)
      - troubleshooting:    ~100 (25 × 4 variations)
      - eval_functions:     ~330 (66 functions × 5 templates)
      - cim:                ~114 (19 models × 6 templates)
      - best_practices:     ~25
      - org_specific:       ~12
      - cribl:              ~12
      - compound:           ~8
      - spl_improvement:    ~180 (30 × 6)
    """
    random.seed(seed)

    all_cases = []
    all_cases.extend(generate_spl_test_cases())
    all_cases.extend(generate_general_test_cases())

    # Deduplicate by query text
    seen = set()
    unique = []
    for tc in all_cases:
        key = tc.query.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(tc)

    return unique


def get_stratified_sample(cases: List[TestCase], n: int = 500, seed: int = 42) -> List[TestCase]:
    """Get a stratified random sample across categories."""
    random.seed(seed)
    by_category: Dict[str, List[TestCase]] = {}
    for tc in cases:
        by_category.setdefault(tc.category, []).append(tc)

    # Allocate proportionally, minimum 1 per category
    total = len(cases)
    sample = []
    for cat, cat_cases in sorted(by_category.items()):
        cat_n = max(1, round(n * len(cat_cases) / total))
        sample.extend(random.sample(cat_cases, min(cat_n, len(cat_cases))))

    # Trim or pad to exact n
    if len(sample) > n:
        sample = random.sample(sample, n)
    elif len(sample) < n:
        remaining = [c for c in cases if c not in sample]
        sample.extend(random.sample(remaining, min(n - len(sample), len(remaining))))

    return sample


if __name__ == "__main__":
    cases = generate_all_test_cases()
    print(f"Total test cases: {len(cases)}")
    print()
    # Count by category
    by_cat: Dict[str, int] = {}
    for tc in cases:
        by_cat[tc.category] = by_cat.get(tc.category, 0) + 1
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat:40s} {count:6d}")
    print()
    # Count by collection
    by_coll: Dict[str, int] = {}
    for tc in cases:
        by_coll[tc.expected_collection] = by_coll.get(tc.expected_collection, 0) + 1
    for coll, count in sorted(by_coll.items(), key=lambda x: -x[1]):
        print(f"  {coll:40s} {count:6d}")
    print()
    # Count by difficulty
    by_diff: Dict[str, int] = {}
    for tc in cases:
        by_diff[tc.difficulty] = by_diff.get(tc.difficulty, 0) + 1
    for diff, count in sorted(by_diff.items()):
        print(f"  {diff:10s} {count:6d}")
    # Sample
    sample = get_stratified_sample(cases, n=500)
