"""
Base dataclass for eval test cases, shared across all test case modules.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class TestCase:
    query: str
    category: str
    expected_collection: str  # spl_commands_mxbai, specs_mxbai_embed_large_v3, org_repo_mxbai, etc.
    expected_keywords: List[str]
    difficulty: str = "medium"  # easy, medium, hard
    expected_type: str = "command_help"  # command_help, optimization, generation, config, troubleshoot
