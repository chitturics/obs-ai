"""
SPL-related test case generator functions for RAG evaluation.

Data constants are in eval_test_cases_spl_data.py.
Imported by eval_test_cases.py which combines all cases.
"""

import random
from typing import List

from chat_app.eval_test_cases_base import TestCase
from chat_app.eval_test_cases_spl_data import (  # noqa: F401
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
)


def _generate_command_help_cases() -> List[TestCase]:
    """Generate test cases for individual SPL commands."""
    cases = []
    for cmd in SPL_COMMANDS:
        for template in COMMAND_TEMPLATES:
            q = template.format(cmd=cmd)
            cases.append(TestCase(
                query=q,
                category="command_help",
                expected_collection="spl_commands_mxbai",
                expected_keywords=[cmd],
                difficulty="easy",
                expected_type="command_help",
            ))
    return cases


def _generate_command_family_cases() -> List[TestCase]:
    """Generate cross-reference questions between related commands."""
    cases = []
    for family_name, family in COMMAND_FAMILIES.items():
        for q in family["questions"]:
            cases.append(TestCase(
                query=q,
                category=f"command_family_{family_name}",
                expected_collection="spl_commands_mxbai",
                expected_keywords=family["commands"][:3],
                difficulty="medium",
                expected_type="command_help",
            ))
    return cases


def _generate_optimization_cases() -> List[TestCase]:
    """Generate SPL optimization questions."""
    cases = []
    for spl in SAMPLE_SPL_QUERIES:
        for template in OPTIMIZATION_TEMPLATES[:8]:  # First 8 are query-based
            q = template.format(spl=spl)
            cases.append(TestCase(
                query=q,
                category="optimization",
                expected_collection="spl_commands_mxbai",
                expected_keywords=["stats", "eval", "where", "index"],
                difficulty="medium",
                expected_type="optimization",
            ))
    # Command-specific optimization
    for cmd in ["stats", "join", "lookup", "transaction", "eval", "where",
                "search", "tstats", "timechart", "rex", "streamstats"]:
        for template in OPTIMIZATION_TEMPLATES[8:]:
            q = template.format(cmd=cmd)
            cases.append(TestCase(
                query=q,
                category="optimization",
                expected_collection="spl_commands_mxbai",
                expected_keywords=[cmd, "performance"],
                difficulty="medium",
                expected_type="optimization",
            ))
    return cases


def _generate_nl_to_spl_cases() -> List[TestCase]:
    """Generate natural language to SPL questions."""
    cases = []
    for query, cat, keywords in NL_TO_SPL_QUERIES:
        cases.append(TestCase(
            query=query,
            category=f"nl_to_spl_{cat}",
            expected_collection="spl_commands_mxbai",
            expected_keywords=keywords,
            difficulty="medium",
            expected_type="generation",
        ))
    prefixes = [
        "Write SPL to ", "Create a search that ", "How to search for ",
        "Build a query to ", "I need a Splunk search to ",
        "Help me write a search for ", "Give me SPL for ",
        "Splunk query to ", "Generate a search for ",
        "What SPL would ", "Write a Splunk search that ",
        "Can you create SPL for ", "Need SPL to ",
    ]
    for query, cat, keywords in NL_TO_SPL_QUERIES:
        for prefix in prefixes:
            cases.append(TestCase(
                query=prefix + query.lower(),
                category=f"nl_to_spl_{cat}",
                expected_collection="spl_commands_mxbai",
                expected_keywords=keywords,
                difficulty="medium",
                expected_type="generation",
            ))
    return cases


def _generate_eval_function_cases() -> List[TestCase]:
    """Generate eval function questions."""
    cases = []
    for func in EVAL_FUNCTIONS:
        for template in EVAL_TEMPLATES:
            q = template.format(func=func)
            cases.append(TestCase(
                query=q,
                category="eval_functions",
                expected_collection="spl_commands_mxbai",
                expected_keywords=["eval", func],
                difficulty="easy",
                expected_type="command_help",
            ))
    return cases


def _generate_cim_cases() -> List[TestCase]:
    """Generate CIM / Data Model questions."""
    cases = []
    for model in CIM_MODELS:
        for template in CIM_TEMPLATES:
            q = template.format(model=model)
            cases.append(TestCase(
                query=q,
                category="cim",
                expected_collection="spl_commands_mxbai",
                expected_keywords=["datamodel", model.lower()],
                difficulty="medium",
                expected_type="command_help",
            ))
    return cases


def _generate_raw_spl_improvement_cases() -> List[TestCase]:
    """Generate 'improve this SPL' test cases — raw SPL input."""
    cases = []
    improvements = [
        "can you improve", "optimize this", "make this faster",
        "rewrite this better", "fix this search", "what is wrong with",
    ]
    for spl in SAMPLE_SPL_QUERIES:
        for imp in improvements:
            cases.append(TestCase(
                query=f"{imp} {spl}",
                category="spl_improvement",
                expected_collection="spl_commands_mxbai",
                expected_keywords=["stats", "index"],
                difficulty="medium",
                expected_type="optimization",
            ))
    return cases


def _generate_scenario_cases() -> List[TestCase]:
    """Generate scenario-based SPL queries for bulk expansion."""
    cases = []
    random.seed(42)
    for template in SCENARIO_TEMPLATES:
        for idx in INDEXES:
            fields = FIELDS_PER_INDEX.get(idx, ["count", "host"])
            for _ in range(11):  # 11 random combos per index per template
                fld = random.choice(fields)
                func = random.choice(STAT_FUNCS)
                by = random.choice(BY_FIELDS)
                tr = random.choice(TIME_RANGES)
                q = template.format(idx=idx, func=func, field=fld, by_field=by, time=tr)
                cases.append(TestCase(
                    query=q,
                    category=f"scenario_{idx}",
                    expected_collection="spl_commands_mxbai",
                    expected_keywords=[idx, func],
                    difficulty="medium",
                    expected_type="generation",
                ))
    return cases


def _generate_pipeline_cases() -> List[TestCase]:
    """Generate two-command pipeline questions."""
    cases = []
    for cmd1, cmd2 in PIPELINE_COMBOS:
        for template in PIPELINE_TEMPLATES:
            q = template.format(cmd1=cmd1, cmd2=cmd2)
            cases.append(TestCase(
                query=q,
                category="pipeline_combo",
                expected_collection="spl_commands_mxbai",
                expected_keywords=[cmd1, cmd2],
                difficulty="medium",
                expected_type="command_help",
            ))
    return cases


def _generate_field_operation_cases() -> List[TestCase]:
    """Generate field-specific operation questions."""
    cases = []
    field_ops = [
        ("How to extract {field} from raw events?", "extract"),
        ("How to rename {field} to a new name?", "rename"),
        ("How to filter by {field} value?", "filter"),
        ("How to calculate statistics on {field}?", "stats"),
        ("How to find null or empty {field}?", "null_check"),
        ("How to convert {field} to a different type?", "convert"),
        ("How to create a new field based on {field}?", "eval"),
        ("How to display only {field} in results?", "display"),
    ]
    all_fields = set()
    for fields in FIELDS_PER_INDEX.values():
        all_fields.update(fields)
    all_fields.update(BY_FIELDS)

    for field in all_fields:
        for template, op in field_ops:
            q = template.format(field=field)
            cases.append(TestCase(
                query=q,
                category=f"field_ops_{op}",
                expected_collection="spl_commands_mxbai",
                expected_keywords=[field],
                difficulty="easy",
                expected_type="command_help",
            ))
    return cases


def _generate_use_case_cases() -> List[TestCase]:
    """Generate security/compliance/ops use case questions."""
    use_cases = [
        "How to detect brute force attacks in Splunk?",
        "How to find lateral movement in network logs?",
        "How to detect data exfiltration?",
        "How to monitor privileged account activity?",
        "How to detect unauthorized access attempts?",
        "How to find command and control traffic?",
        "How to monitor for ransomware indicators?",
        "How to detect insider threats?",
        "How to build a SOC dashboard in Splunk?",
        "How to implement MITRE ATT&CK in Splunk?",
        "How to detect phishing attempts in email logs?",
        "How to monitor DNS tunneling?",
        "How to find suspicious PowerShell execution?",
        "How to detect credential dumping?",
        "How to monitor for policy violations?",
        "How to generate PCI compliance reports?",
        "How to track user access for audit?",
        "How to monitor data retention compliance?",
        "How to generate SOX compliance reports?",
        "How to track system changes for compliance?",
        "How to monitor application health?",
        "How to track SLA compliance?",
        "How to create capacity planning reports?",
        "How to monitor backup job status?",
        "How to track infrastructure changes?",
        "How to detect performance degradation?",
        "How to monitor certificate expiration?",
        "How to track deployment frequency?",
        "How to measure MTTR for incidents?",
        "How to create an executive dashboard?",
        "How to monitor bandwidth utilization?",
        "How to detect network anomalies?",
        "How to track VPN usage patterns?",
        "How to monitor DHCP lease activity?",
        "How to detect rogue devices on the network?",
        "How to monitor wireless access points?",
        "How to track BGP route changes?",
        "How to detect port scanning activity?",
        "How to monitor QoS metrics?",
        "How to track SSL/TLS certificate issues?",
    ]
    cases = []
    for q in use_cases:
        cases.append(TestCase(
            query=q,
            category="use_cases",
            expected_collection="spl_commands_mxbai",
            expected_keywords=["index", "stats"],
            difficulty="hard",
            expected_type="generation",
        ))
        for prefix in ["Write a Splunk search to ", "SPL query for ", "How would I "]:
            cases.append(TestCase(
                query=prefix + q.lower().replace("how to ", ""),
                category="use_cases",
                expected_collection="spl_commands_mxbai",
                expected_keywords=["index", "stats"],
                difficulty="hard",
                expected_type="generation",
            ))
    return cases


def _generate_advanced_spl_cases() -> List[TestCase]:
    """Generate advanced SPL pattern questions to bulk up to 10K+."""
    cases = []
    subsearch_queries = [
        "How to use subsearch in Splunk?",
        "What is the difference between subsearch and join?",
        "Subsearch performance limitations",
        "How to return values from a subsearch?",
        "Subsearch vs append for combining results",
        "How to use format with subsearch?",
        "Maximum events in subsearch default",
        "How to debug a subsearch?",
    ]
    for q in subsearch_queries:
        cases.append(TestCase(query=q, category="advanced_spl",
            expected_collection="spl_commands_mxbai",
            expected_keywords=["subsearch", "return", "format"],
            difficulty="hard", expected_type="command_help"))

    macro_queries = [
        "How to create a search macro?",
        "How to pass arguments to a macro?",
        "What is macro validation?",
        "How to use backtick macros in SPL?",
        "Macro with default arguments",
        "How to list all macros?",
        "Macro vs saved search differences",
        "How to debug a macro expansion?",
    ]
    for q in macro_queries:
        cases.append(TestCase(query=q, category="advanced_spl",
            expected_collection="specs_mxbai_embed_large_v3",
            expected_keywords=["macros.conf", "definition", "args"],
            difficulty="medium", expected_type="config"))

    patterns = [
        "How to use {cmd} with earliest and latest?",
        "Can {cmd} handle multivalue fields?",
        "How to use {cmd} in a saved search?",
        "What happens when {cmd} has no results?",
        "How does {cmd} affect search performance?",
        "Using {cmd} in a dashboard panel",
        "How to use {cmd} with a subsearch?",
        "Can I chain multiple {cmd} commands?",
        "How does {cmd} interact with distributed search?",
        "What is the memory limit for {cmd}?",
        "How to use {cmd} with a lookup?",
        "Default behavior of {cmd} command",
    ]
    for cmd in SPL_COMMANDS:
        for template in patterns:
            q = template.format(cmd=cmd)
            cases.append(TestCase(
                query=q, category="advanced_command_usage",
                expected_collection="spl_commands_mxbai",
                expected_keywords=[cmd],
                difficulty="medium", expected_type="command_help",
            ))

    error_msgs = [
        "Error: field not found",
        "Error: too many results",
        "Error: search timed out",
        "Error: permission denied",
        "Error: max memory limit reached",
        "Error: chunk too large",
        "Error: role does not have access",
        "Error: no results found",
        "Error: invalid argument",
        "Error: command not found",
        "Error: cannot resolve host",
        "Error: license violation",
    ]
    for err in error_msgs:
        for prefix in ["How to fix", "What causes", "Troubleshoot", "Why am I getting"]:
            cases.append(TestCase(
                query=f'{prefix} "{err}" in Splunk?',
                category="error_resolution",
                expected_collection="spl_commands_mxbai",
                expected_keywords=["error"],
                difficulty="hard", expected_type="troubleshoot",
            ))

    return cases


def _generate_stats_function_cases() -> List[TestCase]:
    """Generate detailed stats function questions."""
    cases = []
    for func in STAT_FUNCS:
        templates = [
            f"How to use {func}() function in stats?",
            f"What does {func} do in stats command?",
            f"Example of stats {func}(field) by groupby",
            f"Can I use {func} in eventstats?",
            f"How does {func} work in streamstats?",
            f"Using {func} with timechart command",
            f"stats {func}(field) as alias syntax",
            f"Difference between {func} in stats vs chart",
        ]
        for q in templates:
            cases.append(TestCase(
                query=q,
                category="stats_functions",
                expected_collection="spl_commands_mxbai",
                expected_keywords=["stats", func],
                difficulty="easy",
                expected_type="command_help",
            ))
    return cases


def generate_spl_test_cases() -> List[TestCase]:
    """Generate all SPL-related test cases."""
    cases = []
    cases.extend(_generate_command_help_cases())
    cases.extend(_generate_command_family_cases())
    cases.extend(_generate_optimization_cases())
    cases.extend(_generate_nl_to_spl_cases())
    cases.extend(_generate_eval_function_cases())
    cases.extend(_generate_cim_cases())
    cases.extend(_generate_raw_spl_improvement_cases())
    cases.extend(_generate_scenario_cases())
    cases.extend(_generate_pipeline_cases())
    cases.extend(_generate_field_operation_cases())
    cases.extend(_generate_use_case_cases())
    cases.extend(_generate_advanced_spl_cases())
    cases.extend(_generate_stats_function_cases())
    return cases
