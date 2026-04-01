#!/usr/bin/env python3
"""
Download Splunk SPL (Search Processing Language) command documentation
from Splunk official documentation website.

Crawls:
- https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/
- Identifies all SPL commands
- Downloads full documentation for each command
- Saves as markdown files for ingestion
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple, Callable
from urllib.parse import urljoin, urlparse
import logging

import requests
from bs4 import BeautifulSoup

# Optional Playwright-based fetch (uses chat_app/puppeteer.py)
FETCH_WITH_PLAYWRIGHT: Optional[Callable] = None
try:
    from pathlib import Path as _Path
    import sys as _sys
    _CHAT_APP_PATH = _Path(__file__).resolve().parents[1] / "chat_app"
    if _CHAT_APP_PATH.exists():
        _sys.path.append(str(_CHAT_APP_PATH))
        import puppeteer as _puppeteer  # type: ignore

        if hasattr(_puppeteer, "fetch_with_playwright"):
            FETCH_WITH_PLAYWRIGHT = _puppeteer.fetch_with_playwright
except Exception:
    FETCH_WITH_PLAYWRIGHT = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Base URLs for Splunk documentation
SPLUNK_DOCS_BASE = "https://docs.splunk.com"
SPL_SEARCH_REF_BASE = f"{SPLUNK_DOCS_BASE}/Documentation/Splunk/latest/SearchReference"

# Command index URLs
COMMAND_INDEX_URLS = [
    f"{SPL_SEARCH_REF_BASE}/WhatsInThisManual",  # Main index (splunk-enterprise)
    # Quick reference pages requested (enterprise)
    "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/quick-reference/commands-by-category",
    "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/quick-reference/command-quick-reference",
]

# Preferred command docs version (for help.splunk.com)
SEARCH_COMMAND_VERSION = os.getenv("SEARCH_COMMAND_VERSION", "9.4")

# Rate limiting
REQUEST_DELAY = 0.5  # Seconds between requests (be respectful to Splunk's servers)

# Timeout
REQUEST_TIMEOUT = 30

# Minimum acceptable content length (characters) to treat a page as valid
MIN_CONTENT_LEN = 600

# Local fallback: searchbnf.conf path (already cloned with specs)
SEARCH_BNF_PATH = Path(__file__).resolve().parent / "searchbnf.conf"

class SPLDocsDownloader:
    """Download and parse Splunk SPL command documentation"""

    def __init__(self, target_dir: Path):
        self.target_dir = target_dir
        self.target_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

        self.commands: Dict[str, Dict] = {}
        self.downloaded_count = 0
        self.failed_count = 0
        self.preview_max = 3  # how many payload previews to emit at info level

    def fetch_url(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch and parse a URL, preferring Playwright (JS-capable) first."""
        # 1) Try Playwright first (acts like a real browser)
        if FETCH_WITH_PLAYWRIGHT:
            try:
                logger.debug(f"[playwright] Fetching: {url}")
                ctype, html = FETCH_WITH_PLAYWRIGHT(url, headers=self.session.headers, timeout_ms=30000)
                logger.info(f"[playwright] Success for {url} (bytes={len(html)})")
                return BeautifulSoup(html, 'html.parser')
            except Exception as exc:
                logger.error(f"[playwright] Failed for {url}: {exc}")

        # 2) Fallback to simple requests if Playwright missing/fails
        try:
            logger.debug(f"[requests] Fetching: {url}")
            time.sleep(REQUEST_DELAY)

            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            logger.debug(f"[requests] Fetched {len(response.content)} bytes from {url}")

            body_text = soup.get_text(separator=" ", strip=True).lower()
            if (
                "enable javascript" in body_text
                or "unsupported browser" in body_text
                or "use one of the following browsers" in body_text
                or len(body_text) < 200
            ):
                logger.error(f"[requests] Page appears empty/blocked or JS-gated: {url}")
                return None

            return soup

        except Exception as e:
            logger.error(f"[requests] Failed to fetch {url}: {e}")
            return None

    def discover_commands_from_index(self, index_url: str) -> Set[Dict[str, str]]:
        """
        Discover SPL commands from an index page.
        Returns set of dicts with 'name' and 'url'.
        """
        logger.info(f"Discovering commands from: {index_url}")
        soup = self.fetch_url(index_url)

        if not soup:
            return set()

        commands = set()

        # Find all links to command pages
        for link in soup.find_all('a', href=True):
            href = link['href']
            text = link.get_text().strip()

            full_url = urljoin(SPLUNK_DOCS_BASE, href)
            # Normalize: drop fragment IDs and fix case for /en/
            full_url = full_url.split("#", 1)[0].replace("/En/", "/en/").replace("/EN/", "/en/")
            path = urlparse(full_url).path

            # Patterns to match command URLs
            patterns = [
                r"/Documentation/[^/]+/SearchReference/([^/?#]+)",                              # docs.splunk.com classic
                r"/splunk-enterprise/search/spl-search-reference/[^/]+/searchref/([^/?#]+)",    # help.splunk.com searchref
                r"/spl-search-reference/[^/]+/searchref/([^/?#]+)",                             # alternate searchref paths
                r"/search-commands/([^/?#]+)",                                                  # new help.splunk.com search-commands paths
            ]
            cmd_name = None
            for pat in patterns:
                m = re.search(pat, path, re.IGNORECASE)
                if m:
                    cmd_name = m.group(1).lower()
                    break

            if not cmd_name:
                continue

            # Filter out non-command pages
            if any(skip in cmd_name for skip in [
                'whatsinthismanual', 'commonsearchtimestatistics',
                'abstractcommands', 'listof', 'common', 'quick-reference'
            ]):
                continue

            # Build canonical help.splunk.com command URL (avoid docs.splunk.com 404s)
            canonical_url = (
                f"https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/"
                f"{SEARCH_COMMAND_VERSION}/search-commands/{cmd_name}"
            )

            commands.add((cmd_name, canonical_url, text))

        logger.info(f"Discovered {len(commands)} potential commands")
        if commands:
            sample = sorted(list(commands))[:5]
            logger.info("Sample discovered commands:")
            for name, url, text in sample:
                logger.info(f"  - {name} ({text}): {url}")
        return commands

    def discover_all_commands(self) -> Dict[str, Dict]:
        """
        Discover all SPL commands from multiple index pages.
        Returns dict of {command_name: {'url': ..., 'title': ...}}
        """
        logger.info("=" * 80)
        logger.info("DISCOVERING SPL COMMANDS")
        logger.info("=" * 80)

        all_commands = {}

        # Method 1: Crawl known command index pages
        for index_url in COMMAND_INDEX_URLS:
            discovered = self.discover_commands_from_index(index_url)
            for cmd_name, url, title in discovered:
                if cmd_name not in all_commands:
                    all_commands[cmd_name] = {
                        'url': url,
                        'title': title or cmd_name,
                        'discovered_from': index_url
                    }

        # Method 1b: Load from local searchbnf.conf as authoritative fallback
        bnf_cmds = self._load_searchbnf_commands()
        for cmd_name, meta in bnf_cmds.items():
            if cmd_name not in all_commands:
                all_commands[cmd_name] = {
                    'url': meta.get('url') or f"{SPL_SEARCH_REF_BASE}/{cmd_name.capitalize()}",
                    'title': meta.get('title') or cmd_name,
                    'discovered_from': 'searchbnf.conf'
                }

        # Method 2: Add well-known commands that might be missed
        well_known_commands = [
            'stats', 'eval', 'search', 'where', 'rex', 'table', 'fields',
            'rename', 'dedup', 'sort', 'head', 'tail', 'top', 'rare',
            'chart', 'timechart', 'transaction', 'streamstats', 'eventstats',
            'lookup', 'inputlookup', 'outputlookup', 'join', 'append',
            'appendcols', 'makemv', 'mvexpand', 'spath', 'xpath', 'multisearch',
            'subsearch', 'return', 'format', 'map', 'accum', 'addinfo',
            'addtotals', 'analyzefields', 'anomalies', 'anomalousvalue',
            'anomalydetection', 'append', 'appendcols', 'appendpipe', 'arules',
            'associate', 'autoregress', 'bin', 'bucket', 'bucketdir', 'collect',
            'concurrency', 'contingency', 'convert', 'correlate', 'datamodel',
            'dbinspect', 'delete', 'delta', 'diff', 'erex', 'eventcount',
            'eventstats', 'extract', 'kv', 'fieldformat', 'fields', 'fieldsummary',
            'filldown', 'fillnull', 'findtypes', 'folderize', 'foreach', 'format',
            'from', 'gauge', 'gentimes', 'geom', 'geomfilter', 'geostats', 'head',
            'highlight', 'history', 'iconify', 'input', 'inputcsv', 'inputlookup',
            'iplocation', 'join', 'kmeans', 'kvform', 'loadjob', 'localize',
            'localop', 'lookup', 'makecontinuous', 'makemv', 'makeresults',
            'map', 'metadata', 'metasearch', 'multikv', 'multisearch', 'mvcombine',
            'mvexpand', 'nomv', 'outlier', 'outputcsv', 'outputlookup',
            'outputtext', 'overlap', 'pivot', 'predict', 'rangemap', 'rare',
            'regex', 'relevancy', 'reltime', 'rename', 'replace', 'rest',
            'return', 'reverse', 'rex', 'rtorder', 'savedsearch', 'script',
            'scrub', 'search', 'searchtxn', 'selfjoin', 'sendemail', 'set',
            'setfields', 'sichart', 'sirare', 'sistats', 'sitimechart', 'sitop',
            'sort', 'spath', 'stats', 'strcat', 'streamstats', 'table', 'tags',
            'tail', 'timechart', 'timewrap', 'top', 'transaction', 'transpose',
            'trendline', 'tscollect', 'tstats', 'typeahead', 'typelearner',
            'typer', 'union', 'uniq', 'untable', 'where', 'x11', 'xmlkv',
            'xmlunescape', 'xpath', 'xyseries'
        ]

        for cmd in well_known_commands:
            if cmd not in all_commands:
                # Construct likely URL
                url = f"{SPL_SEARCH_REF_BASE}/{cmd.capitalize()}"
                all_commands[cmd] = {
                    'url': url,
                    'title': cmd,
                    'discovered_from': 'well_known_list'
                }

        logger.info(f"Total unique commands discovered: {len(all_commands)}")
        if all_commands:
            sample = sorted(all_commands.items())[:5]
            logger.info("Sample command map:")
            for name, meta in sample:
                logger.info(f"  - {name}: {meta}")
        return all_commands

    def extract_command_content(self, soup: BeautifulSoup, cmd_name: str) -> str:
        """
        Extract clean command documentation content from HTML.
        Returns markdown-formatted text.

        Handles help.splunk.com structure where content is nested in <section> elements.
        """
        # Find main content area - prioritize article/main for help.splunk.com
        content_div = soup.find('article') or \
                     soup.find('main') or \
                     soup.find('div', {'class': 'content'}) or \
                     soup.find('div', {'id': 'content'}) or \
                     soup.find('div', {'class': 'topic-body'}) or \
                     soup.find('div', {'role': 'main'})

        if not content_div:
            # Fallback: use body
            content_div = soup.find('body')

        if not content_div:
            return ""

        # Remove navigation, sidebars, footers, scripts
        for unwanted in content_div.find_all(['nav', 'aside', 'footer', 'script', 'style', 'header']):
            unwanted.decompose()

        # Also remove elements by class that are typically navigation/chrome
        for unwanted_class in ['breadcrumb', 'sidebar', 'toc', 'nav', 'feedback', 'footer']:
            for elem in content_div.find_all(class_=lambda x: x and unwanted_class in x.lower() if x else False):
                elem.decompose()

        # Build markdown content
        markdown_lines = []
        markdown_lines.append(f"# {cmd_name}")
        markdown_lines.append("")

        # Extract title/heading
        h1 = content_div.find('h1')
        if h1:
            title_text = h1.get_text().strip()
            if title_text.lower() != cmd_name.lower():
                markdown_lines.append(f"## {title_text}")
                markdown_lines.append("")

        # Method 1: Try section-based extraction (help.splunk.com structure)
        sections = content_div.find_all('section')
        if sections:
            for section in sections:
                self._extract_section_content(section, markdown_lines)
        else:
            # Method 2: Heading-based extraction with improved traversal
            self._extract_by_headings(content_div, markdown_lines)

        content_text = "\n".join(markdown_lines).strip()

        # Clean up excessive newlines
        content_text = re.sub(r'\n{3,}', '\n\n', content_text)

        # Fallback: if still too short, extract all text content intelligently
        if len(content_text) < MIN_CONTENT_LEN:
            logger.debug(f"Content short for {cmd_name} (len={len(content_text)}), using full extraction")
            content_text = self._extract_full_content(content_div, cmd_name)

        return content_text

    def _extract_section_content(self, section, markdown_lines: list) -> None:
        """Extract content from a <section> element (help.splunk.com structure)."""
        # Find the section heading
        heading = section.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if heading:
            level = int(heading.name[1])
            heading_text = heading.get_text().strip()
            if heading_text:
                markdown_lines.append(f"{'#' * (level + 1)} {heading_text}")
                markdown_lines.append("")

        # Extract all content within the section (excluding nested sections)
        for child in section.children:
            if child.name == 'section':
                # Recursively handle nested sections
                self._extract_section_content(child, markdown_lines)
            elif hasattr(child, 'name') and child.name:
                # Skip the heading we already processed
                if child.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    continue
                self._extract_element(child, markdown_lines)

    def _extract_by_headings(self, content_div, markdown_lines: list) -> None:
        """Extract content by finding headings and collecting all following content."""
        # Get all elements in document order
        all_elements = content_div.find_all(['h2', 'h3', 'h4', 'h5', 'p', 'pre', 'code',
                                              'ul', 'ol', 'table', 'div', 'dl'])

        for elem in all_elements:
            if elem.name in ['h2', 'h3', 'h4', 'h5']:
                level = int(elem.name[1])
                heading_text = elem.get_text().strip()
                if heading_text:
                    markdown_lines.append(f"{'#' * (level + 1)} {heading_text}")
                    markdown_lines.append("")
            else:
                self._extract_element(elem, markdown_lines)

    def _extract_element(self, elem, markdown_lines: list) -> None:
        """Extract content from a single element and add to markdown_lines."""
        if not elem or not hasattr(elem, 'name'):
            return

        # Skip if this element contains a heading (will be handled separately)
        if elem.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            return

        if elem.name == 'p':
            text = elem.get_text().strip()
            if text and len(text) > 10:  # Skip very short paragraphs
                markdown_lines.append(text)
                markdown_lines.append("")

        elif elem.name in ['ul', 'ol']:
            for li in elem.find_all('li', recursive=False):
                li_text = li.get_text().strip()
                if li_text:
                    # Handle nested lists
                    if li.find(['ul', 'ol']):
                        # Get just the direct text, not nested list text
                        direct_text = ''.join(li.find_all(string=True, recursive=False)).strip()
                        if direct_text:
                            markdown_lines.append(f"- {direct_text}")
                        for nested in li.find_all(['ul', 'ol'], recursive=False):
                            for nested_li in nested.find_all('li', recursive=False):
                                nested_text = nested_li.get_text().strip()
                                if nested_text:
                                    markdown_lines.append(f"  - {nested_text}")
                    else:
                        markdown_lines.append(f"- {li_text}")
            markdown_lines.append("")

        elif elem.name == 'pre' or (elem.name == 'code' and elem.parent.name != 'pre'):
            code_text = elem.get_text().strip()
            if code_text:
                markdown_lines.append("```")
                markdown_lines.append(code_text)
                markdown_lines.append("```")
                markdown_lines.append("")

        elif elem.name == 'table':
            table_md = self._table_to_markdown(elem)
            if table_md:
                markdown_lines.append(table_md)
                markdown_lines.append("")

        elif elem.name == 'dl':
            # Definition lists (common for argument descriptions)
            for dt in elem.find_all('dt'):
                term = dt.get_text().strip()
                dd = dt.find_next_sibling('dd')
                if dd:
                    definition = dd.get_text().strip()
                    markdown_lines.append(f"**{term}**")
                    markdown_lines.append(f": {definition}")
                    markdown_lines.append("")
                elif term:
                    markdown_lines.append(f"**{term}**")
                    markdown_lines.append("")

        elif elem.name == 'div':
            # Check for specific content divs
            div_class = elem.get('class', [])
            if isinstance(div_class, list):
                div_class = ' '.join(div_class)

            # Extract content from divs that contain actual content
            if any(c in div_class.lower() for c in ['content', 'body', 'text', 'description', 'syntax']):
                for child in elem.children:
                    if hasattr(child, 'name') and child.name:
                        self._extract_element(child, markdown_lines)
            else:
                # Check if this div has direct text content (not nested in elements)
                direct_text = elem.get_text().strip()
                # Only add if it has substantial content not already in child elements
                if len(direct_text) > 50 and not elem.find(['p', 'ul', 'ol', 'pre', 'table', 'div']):
                    markdown_lines.append(direct_text)
                    markdown_lines.append("")

    def _extract_full_content(self, content_div, cmd_name: str) -> str:
        """Fallback extraction that gets all text content intelligently."""
        markdown_lines = [f"# {cmd_name}", ""]

        # Walk through all elements in order
        for elem in content_div.descendants:
            if not hasattr(elem, 'name') or not elem.name:
                continue

            if elem.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                level = int(elem.name[1])
                text = elem.get_text().strip()
                if text:
                    markdown_lines.append(f"{'#' * level} {text}")
                    markdown_lines.append("")

            elif elem.name == 'p':
                text = elem.get_text().strip()
                if text and len(text) > 10:
                    markdown_lines.append(text)
                    markdown_lines.append("")

            elif elem.name == 'pre':
                text = elem.get_text().strip()
                if text:
                    markdown_lines.append("```")
                    markdown_lines.append(text)
                    markdown_lines.append("```")
                    markdown_lines.append("")

            elif elem.name == 'li':
                # Only process if parent is direct ul/ol (not nested)
                if elem.parent and elem.parent.name in ['ul', 'ol']:
                    text = elem.get_text().strip()
                    if text:
                        markdown_lines.append(f"- {text}")

            elif elem.name in ['ul', 'ol']:
                markdown_lines.append("")  # Add spacing after lists

        content = "\n".join(markdown_lines)
        # Clean up
        content = re.sub(r'\n{3,}', '\n\n', content)
        return content.strip()

    def _table_to_markdown(self, table) -> str:
        """Convert HTML table to markdown table"""
        lines = []

        # Headers
        headers = []
        for th in table.find_all('th'):
            headers.append(th.get_text().strip())

        if headers:
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Rows
        for tr in table.find_all('tr'):
            cells = []
            for td in tr.find_all('td'):
                cells.append(td.get_text().strip())
            if cells:
                lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines)

    def _load_searchbnf_commands(self) -> Dict[str, Dict[str, str]]:
        """
        Parse searchbnf.conf for command syntax/description.
        Returns {command: {'syntax': str, 'description': str, 'url': str}}
        """
        cmds: Dict[str, Dict[str, str]] = {}
        if not SEARCH_BNF_PATH.exists():
            return cmds

        current: Optional[str] = None
        buf: Dict[str, List[str]] = {"syntax": [], "description": []}

        def _commit():
            if current:
                syntax = " ".join(buf["syntax"]).strip()
                desc = " ".join(buf["description"]).strip()
                cmds[current] = {
                    "syntax": syntax,
                    "description": desc,
                    "url": f"{SPL_SEARCH_REF_BASE}/{current.capitalize()}",
                    "title": current,
                }

        with SEARCH_BNF_PATH.open(encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("[") and line.endswith("]"):
                    # New stanza
                    if "-command" in line:
                        _commit()
                        current = line.strip("[]").replace("-command", "")
                        buf = {"syntax": [], "description": []}
                    else:
                        continue
                elif "=" in line and current:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("\\")
                    if key.startswith("syntax"):
                        buf["syntax"].append(val)
                    elif key.startswith("shortdesc") or key.startswith("description"):
                        buf["description"].append(val)

        _commit()
        logger.info(f"Loaded {len(cmds)} commands from searchbnf.conf fallback")
        return cmds

    def download_command_doc(self, cmd_name: str, cmd_info: Dict, force_download: bool = False) -> bool:
        """
        Download documentation for a single command.

        Args:
            cmd_name: Command name
            cmd_info: Command metadata dict
            force_download: If False, skip if file already exists

        Returns True if successful, False otherwise.
        """
        url = cmd_info['url']
        filename = f"spl_cmd_{cmd_name}.md"
        filepath = self.target_dir / filename

        # Skip if file already exists (unless force_download=True)
        if not force_download and filepath.exists():
            file_size = filepath.stat().st_size
            if file_size > MIN_CONTENT_LEN:
                logger.info(f"⊘ Skipping {cmd_name} (file already exists, {file_size} bytes)")
                return True
            else:
                logger.warning(f"Existing file for {cmd_name} is too small ({file_size} bytes), re-downloading")

        try:
            # Try fetch from docs
            soup = self.fetch_url(url)
            if soup:
                content = self.extract_command_content(soup, cmd_name)
            else:
                content = ""

            # Fallback to searchbnf if fetch failed
            if not soup:
                bnf = self._load_searchbnf_commands().get(cmd_name)
                if not bnf:
                    logger.warning(f"No content and no searchbnf fallback for {cmd_name}")
                    return False
                if bnf.get("syntax"):
                    content += "## Syntax\n" + bnf["syntax"] + "\n\n"
                if bnf.get("description"):
                    content += "## Description\n" + bnf["description"] + "\n"
                logger.info(f"Using searchbnf fallback for {cmd_name} (fetch failed)")

            if not content or len(content) < 100:
                logger.warning(f"Content too short for {cmd_name}, skipping (len={len(content) if content else 0})")
                return False

            # Secondary fallback: append searchbnf if still short
            if len(content) < MIN_CONTENT_LEN:
                bnf = self._load_searchbnf_commands().get(cmd_name)
                if bnf:
                    fallback = []
                    if bnf.get("syntax"):
                        fallback.append("## Syntax")
                        fallback.append(bnf["syntax"])
                    if bnf.get("description"):
                        fallback.append("\n## Description")
                        fallback.append(bnf["description"])
                    fallback_text = "\n".join(fallback).strip()
                    if fallback_text:
                        content = content + "\n\n" + fallback_text
                        logger.warning(f"Content short for {cmd_name}; appended searchbnf fallback (len now {len(content)})")
                else:
                    logger.warning(f"Content still short for {cmd_name} after fallback (len={len(content)})")

            # Save to file (filename and filepath already defined above)
            # Add metadata header
            metadata = {
                'command': cmd_name,
                'source_url': url,
                'title': cmd_info.get('title', cmd_name),
                'download_date': time.strftime('%Y-%m-%d %H:%M:%S'),
            }

            full_content = f"""---
 command: {metadata['command']}
 source_url: {metadata['source_url']}
 title: {metadata['title']}
 download_date: {metadata['download_date']}
---

 {content}
 """

            filepath.write_text(full_content, encoding='utf-8')
            logger.info(f"✓ Downloaded: {cmd_name} ({len(content)} chars)")
            if self.downloaded_count < self.preview_max:
                logger.info(f"Payload preview for {cmd_name}:\n{full_content[:500]}...\n---")
            else:
                logger.debug(f"Payload preview for {cmd_name}:\n{full_content[:400]}...")

            return True

        except Exception as e:
            logger.error(f"Failed to download {cmd_name}: {e}")
            return False

    def download_all(self, force_download: bool = False) -> Dict[str, any]:
        """
        Main download process.

        Args:
            force_download: If False, skip files that already exist

        Returns summary statistics.
        """
        logger.info("=" * 80)
        logger.info("SPLUNK SPL DOCUMENTATION DOWNLOADER")
        logger.info("=" * 80)
        logger.info(f"Target directory: {self.target_dir}")
        logger.info(f"Mode: {'FORCE RE-DOWNLOAD' if force_download else 'SKIP EXISTING FILES'}")
        logger.info("")

        # Discover commands
        self.commands = self.discover_all_commands()

        if not self.commands:
            logger.error("No commands discovered!")
            return {'success': False}

        # Download each command
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"DOWNLOADING DOCUMENTATION FOR {len(self.commands)} COMMANDS")
        logger.info("=" * 80)

        for i, (cmd_name, cmd_info) in enumerate(sorted(self.commands.items()), 1):
            logger.info(f"[{i}/{len(self.commands)}] {cmd_name}")

            if self.download_command_doc(cmd_name, cmd_info, force_download=force_download):
                self.downloaded_count += 1
            else:
                self.failed_count += 1

        # Save metadata
        metadata = {
            'download_date': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_commands': len(self.commands),
            'downloaded': self.downloaded_count,
            'failed': self.failed_count,
            'commands': {
                name: {
                    'url': info['url'],
                    'title': info['title']
                }
                for name, info in self.commands.items()
            }
        }

        metadata_file = self.target_dir / '.spl_docs_metadata.json'
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding='utf-8')

        # Summary
        logger.info("")
        logger.info("=" * 80)
        logger.info("DOWNLOAD COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Total commands: {len(self.commands)}")
        logger.info(f"Successfully downloaded: {self.downloaded_count}")
        logger.info(f"Failed: {self.failed_count}")
        logger.info(f"Target directory: {self.target_dir}")
        logger.info(f"Metadata saved: {metadata_file}")

        return {
            'success': self.failed_count == 0,
            'total': len(self.commands),
            'downloaded': self.downloaded_count,
            'failed': self.failed_count
        }


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Download Splunk SPL command documentation'
    )
    parser.add_argument(
        'target_dir',
        type=Path,
        help='Directory to save documentation files to'
    )
    parser.add_argument(
        '--force-download',
        action='store_true',
        help='Force re-download even if files already exist (default: skip existing)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Download documentation
    downloader = SPLDocsDownloader(args.target_dir)
    result = downloader.download_all(force_download=args.force_download)

    sys.exit(0 if result['success'] else 1)


if __name__ == "__main__":
    main()
