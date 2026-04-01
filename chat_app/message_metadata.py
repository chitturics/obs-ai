"""
Message metadata and tag extraction for the Splunk Assistant.

Extracts structured tags from user messages for tracking and routing.
"""
import re
from typing import Dict, List, Tuple


# Index keyword mapping for tag detection
INDEX_KEYWORDS = {
    'firewall': ['firewall', 'fw', 'pan_logs', 'idc_asa'],
    'windows': ['windows', 'wineventlog', 'eventlog'],
    'linux': ['linux', 'syslog', 'unix'],
    'network': ['network', 'cisco', 'switch', 'router'],
    'o365': ['o365', 'office365', 'microsoft 365'],
    'web': ['proxy', 'web', 'http', 'https'],
}


def extract_message_metadata(user_input: str) -> Tuple[List[str], Dict[str, str]]:
    """
    Extract tags and metadata from user input.

    Returns:
        (tags, metadata) tuple where tags is a list of string tags
        and metadata is a dict of key-value pairs.
    """
    tags = []
    metadata = {}

    # Detect unit_id mentions
    unit_id_match = re.search(
        r'\b(U\d{3,4}|unit_id[=\s]+[\"\']?(\w+))', user_input, re.IGNORECASE
    )
    if unit_id_match:
        unit_id = unit_id_match.group(2) if unit_id_match.group(2) else unit_id_match.group(1)
        tags.append(f"unit_id:{unit_id}")
        metadata["unit_id"] = unit_id

    # Detect circuit mentions
    circuit_match = re.search(
        r'\b(circuit[=\s]+[\"\']?(\w+))', user_input, re.IGNORECASE
    )
    if circuit_match:
        circuit = circuit_match.group(2)
        tags.append(f"circuit:{circuit}")
        metadata["circuit"] = circuit

    # Detect index mentions
    for index_type, keywords in INDEX_KEYWORDS.items():
        if any(kw in user_input.lower() for kw in keywords):
            tags.append(f"index:{index_type}")
            metadata["splunk_index"] = index_type
            break

    # Detect query type
    lower = user_input.lower()
    if any(word in lower for word in ['tstats', 'query', 'search', 'spl']):
        tags.append("query_generation")
        metadata["query_type"] = "spl_generation"
    elif any(word in lower for word in ['.conf', 'config', 'props', 'transforms', 'inputs']):
        tags.append("configuration")
        metadata["query_type"] = "configuration"
    elif any(word in lower for word in ['error', 'issue', 'problem', 'troubleshoot', 'debug']):
        tags.append("troubleshooting")
        metadata["query_type"] = "troubleshooting"
    else:
        tags.append("general")
        metadata["query_type"] = "general"

    return tags, metadata
