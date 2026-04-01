"""
A simple analyzer for Splunk .conf files to find common issues.
"""
import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

from shared.conf_parser import parse_conf_file_advanced

logger = logging.getLogger(__name__)

class ConfigAnalyzer:
    """
    Analyzes Splunk configuration files for health and best practices.
    """
    def __init__(self, config_root: str):
        self.config_root = Path(config_root)
        self.findings = []

    def _parse_conf(self, file_path: Path) -> Dict[str, Dict[str, Any]]:
        """
        A simple .conf file parser.
        """
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return parse_conf_file_advanced(content, filename=str(file_path))

    def _check_for_wildcard_index_in_saved_searches(self, file_path: Path, conf_data: Dict[str, Dict[str, Any]]):
        """
        Check for saved searches using 'index=*'.
        """
        if file_path.name != 'savedsearches.conf':
            return
            
        for stanza, data in conf_data.items():
            search_query = data.get('search')
            if search_query and 'index=*' in search_query.lower():
                self.findings.append({
                    "file": str(file_path.relative_to(self.config_root)),
                    "line": data['__lines__'].get('search', 1),
                    "severity": "High",
                    "title": "Saved Search Uses Wildcard Index",
                    "description": f"The saved search '{stanza}' uses 'index=*', which is very inefficient. This causes the search to scan all indexes, consuming significant resources.",
                    "evidence": search_query,
                })

    def run_checks(self) -> List[Dict[str, Any]]:
        """
        Run all checks against the configuration files.
        """
        self.findings = []
        if not self.config_root.is_dir():
            logger.error(f"Configuration root directory not found: {self.config_root}")
            return []
        
        for conf_file in self.config_root.rglob('*.conf'):
            try:
                parsed_data = self._parse_conf(conf_file)
                self._check_for_wildcard_index_in_saved_searches(conf_file, parsed_data)
                self._check_for_disabled_saved_searches(conf_file, parsed_data)
                self._check_for_missing_index_in_monitor(conf_file, parsed_data)
            except Exception as e:
                logger.error(f"Failed to analyze file {conf_file}: {e}")

        return self.findings

    def _check_for_disabled_saved_searches(self, file_path: Path, conf_data: Dict[str, Dict[str, Any]]):
        """
        Check for disabled saved searches.
        """
        if file_path.name != 'savedsearches.conf':
            return

        for stanza, data in conf_data.items():
            disabled = str(data.get('disabled', '0')).lower()
            if disabled in ['1', 'true']:
                self.findings.append({
                    "file": str(file_path.relative_to(self.config_root)),
                    "line": data['__lines__'].get('disabled', 1),
                    "severity": "Medium",
                    "title": "Disabled Saved Search",
                    "description": f"The saved search '{stanza}' is disabled. Disabled searches clutter the configuration and should be reviewed and removed if no longer needed.",
                    "evidence": f"disabled = {data.get('disabled')}",
                })

    def _check_for_missing_index_in_monitor(self, file_path: Path, conf_data: Dict[str, Dict[str, Any]]):
        """
        Check for monitor stanzas without an index defined.
        """
        if file_path.name != 'inputs.conf':
            return
        
        for stanza, data in conf_data.items():
            if stanza.startswith('monitor://'):
                if 'index' not in data:
                    self.findings.append({
                        "file": str(file_path.relative_to(self.config_root)),
                        "line": 1, # Stanza level, line is harder here
                        "severity": "High",
                        "title": "Monitor Stanza Missing Index",
                        "description": f"The monitor stanza '{stanza}' does not specify an index. Data from this input will be sent to the default index (e.g., 'main'), which is against best practices.",
                        "evidence": f"[{stanza}]",
                    })


# Example Usage
if __name__ == '__main__':
    # This is a placeholder for the original main block.
    # The original error was on line 194, which suggests a substantial file.
    pass
