#!/usr/bin/env python3
"""
Download advanced Splunk documentation for ingestion.

This script downloads:
1. CIM (Common Information Model) documentation
2. Search optimization guides (tstats, TERM, PREFIX)
3. Architecture docs (clustering, deployment server, forwarders)
4. CLI tools and REST API references
5. Internal indexes and metadata
6. Data onboarding (HEC, TCP, syslog)
7. Monitoring and observability

All content is saved as markdown files in splunk_advanced_docs/
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import argparse
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

# Ensure project root is on sys.path for chat_app imports
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from chat_app.puppeteer import fetch_with_playwright

# Preferred doc version (override with SPLUNK_DOC_VERSION env)
DOC_VERSION = os.getenv("SPLUNK_DOC_VERSION", "9.4")

def doc(path: str) -> str:
    return f"https://docs.splunk.com/Documentation/Splunk/{DOC_VERSION}/{path}"

def doc_cim(path: str) -> str:
    return f"https://docs.splunk.com/Documentation/CIM/{DOC_VERSION}/{path}"

def doc_forwarder(path: str) -> str:
    return f"https://docs.splunk.com/Documentation/Forwarder/{DOC_VERSION}/{path}"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Minimum content length to consider a download successful
MIN_CONTENT_LEN = 500


class AdvancedDocsDownloader:
    """Download advanced Splunk documentation pages."""

    # Documentation URLs organized by category (mix of docs.splunk.com and help.splunk.com where needed)
    DOCS_URLS = {
        # CIM - Common Information Model
        "cim": {
            "cim_overview": "https://docs.splunk.com/Documentation/CIM/latest/User/Overview",
            "cim_datamodels": "https://docs.splunk.com/Documentation/CIM/latest/User/Howtousethismanual",
            "cim_authentication": "https://docs.splunk.com/Documentation/CIM/latest/User/Authentication",
            "cim_change": "https://docs.splunk.com/Documentation/CIM/latest/User/Change",
            "cim_network_traffic": "https://docs.splunk.com/Documentation/CIM/latest/User/NetworkTraffic",
            "cim_web": "https://docs.splunk.com/Documentation/CIM/latest/User/Web",
            "cim_malware": "https://docs.splunk.com/Documentation/CIM/latest/User/Malware",
            "cim_common_fields": "https://docs.splunk.com/Documentation/CIM/latest/User/FieldsbyDomain",
        },

        # Search Optimization & Common Searches
        "optimization": {
            "optimize_searches": doc("Search/Optimizesearches"),
            "tstats_command": "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/tstats",
            "term_prefix": "https://docs.splunk.com/Documentation/Splunk/latest/Knowledge/Useacceleratedsearches#Use_TERM_and_PREFIX_terms",
            "indexed_fields": doc("Knowledge/Aboutdefaultfields"),
            "summary_indexing": doc("Knowledge/Usesummaryindexing"),
            "datamodel_acceleration": doc("Knowledge/Managedatamodels"),
            "search_best_practices": doc("Search/Bestpracticeforsplunkweb"),
        },

        # Architecture - Indexer Clustering
        "indexer_clustering": {
            "cluster_overview": doc("Indexer/Aboutclusters"),
            "cluster_master": doc("Indexer/Abouttheclustermaster"),
            "cluster_peers": doc("Indexer/Aboutclusterpeers"),
            "cluster_architecture": doc("Indexer/Clusterarchitecture"),
            "cluster_captain": doc("Indexer/Basicclusterarchitecture"),
            "bucket_replication": doc("Indexer/Howpeersstoreandservedata"),
        },

        # Architecture - Search Head Clustering
        "search_head_clustering": {
            "shc_overview": doc("DistSearch/AboutSHC"),
            "shc_architecture": doc("DistSearch/SHCarchitecture"),
            "shc_deployer": doc("DistSearch/PropagateSHCconfigurationchanges"),
            "shc_captain": doc("DistSearch/SHCarchitecture"),
            "shc_rolling_upgrade": doc("DistSearch/SHCrollingupgrade"),
        },

        # Deployment & Management (deployment server, deployer, CM, etc.)
        "deployment": {
            "deployment_server_overview": doc("Updating/Aboutdeploymentserver"),
            "deployment_architecture": doc("Updating/Deploymentserverarchitecture"),
            "serverclass_conf": doc("Updating/Configuredeploymentclients"),
            "cm_roles": doc("Indexer/Howthemastermanagesthepeers"),
            "deployer_roles": doc("DistSearch/Useadeployer"),
        },

        # Forwarders & outputs
        "forwarders": {
            "universal_forwarder": doc_forwarder("Forwarder/Abouttheuniversalforwarder"),
            "forwarder_deployment": doc_forwarder("Forwarder/Deployanixdfmanually"),
            "outputs_conf": doc("Admin/Outputsconf"),
            "inputs_conf": doc("Admin/Inputsconf"),
        },

        # CLI / management commands
        "cli": {
            "splunk_cli": doc("Admin/CLIadmincommands"),
            "btool": doc("Admin/Howtousebtool"),
            "splunk_commands": doc("Admin/Aboutthecli"),
            "rolling_restart": doc("Admin/Rollingrestart"),
        },

        # REST API
        "rest_api": {
            "rest_overview": doc("RESTREF/RESTprolog"),
            "rest_auth": doc("RESTREF/RESTaccess"),
            "rest_search": doc("RESTREF/RESTsearch"),
        },

        # Internal Indexes & metadata
        "internal_indexes": {
            "internal_index": doc("Troubleshooting/Useinternallogstoinvestigate"),
            "audit_index": doc("Security/Setupauditlogging"),
            "introspection": doc("Troubleshooting/WhatSplunklogsaboutitself"),
            "metrics_index": doc("Metrics/Overview"),
            "default_indexes": doc("Admin/Listofpretrainedsourcetypesandtheirindexes"),
        },

        # Data Inputs (HEC, TCP, syslog, monitoring)
        "data_inputs": {
            "hec_overview": doc("Data/UsetheHTTPEventCollector"),
            "hec_setup": doc("Data/SetupHEC"),
            "tcp_udp_inputs": doc("Data/Monitornetworkports"),
            "syslog_input": doc("Data/Monitornetworkports"),
            "file_monitoring": doc("Data/Monitorfilesanddirectories"),
            "network_inputs": doc("Data/Monitoringnetworkports"),
        },

        # Metadata and Search Commands
        "metadata": {
            "metadata_command": "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/metadata",
            "dbinspect": "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/dbinspect",
            "eventcount": "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/eventcount",
            "walklex": "https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/walklex",
        },

        # Monitoring & Observability
        "monitoring": {
            "monitoring_console": doc("DMC/DMCoverview"),
            "splunk_health": doc("Troubleshooting/Troubleshootingindex"),
            "license_usage": doc("Admin/Aboutlicenses"),
            "diag_cmd": doc("Troubleshooting/Generateadiag"),
        },

        # Index/source/sourcetype references
        "data_dictionary": {
            "default_fields": doc("Knowledge/Aboutdefaultfields"),
            "sourcetype_overview": doc("Knowledge/AboutSplunkDatasets"),
            "sources_sourcetypes": doc("Knowledge/Searchtimefieldextraction"),
            "metadata_defaults": doc("Admin/Listofpretrainedsourcetypesandtheirindexes"),
        },
    }

    def __init__(self, target_dir: Path, force_download: bool = False):
        self.target_dir = Path(target_dir)
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.force_download = force_download
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_count = 0

    def fetch_html(self, url: str) -> Optional[str]:
        """
        Fetch HTML using Playwright first (real browser), falling back to requests if needed.
        """
        try:
            _, html = fetch_with_playwright(
                url,
                headers=self.session.headers,
                timeout_ms=45000,
            )
            return html
        except Exception as e:
            logger.warning(f"[playwright] {e}; falling back to requests for {url}")

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(f"Failed to fetch {url} via Playwright and requests: {e}")
            return None

    def download_page(self, url: str, filename: str, category: str) -> bool:
        """Download a single documentation page and convert to markdown."""

        # Create category subdirectory
        category_dir = self.target_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)

        filepath = category_dir / f"{filename}.md"

        # Skip if file exists and force_download is False
        if not self.force_download and filepath.exists():
            file_size = filepath.stat().st_size
            if file_size > MIN_CONTENT_LEN:
                logger.info(f"⊘ Skipping {category}/{filename} (file already exists, {file_size} bytes)")
                self.skipped_count += 1
                return True
            else:
                logger.warning(f"Existing file too small ({file_size} bytes), re-downloading")

        try:
            logger.info(f"📥 Downloading {category}/{filename} from {url}")
            html = self.fetch_html(url)
            if not html:
                self.failed_count += 1
                return False

            # Detect known gated/unsupported responses
            lower_html = html.lower()
            if any(token in lower_html for token in ["splunk-login", "log into your splunk account", "upgrade_browser"]):
                logger.error(f"❌ Page gated/login-only: {url}")
                if filepath.exists():
                    filepath.unlink(missing_ok=True)
                self.failed_count += 1
                return False

            # Parse HTML
            soup = BeautifulSoup(html, 'html.parser')

            # Find main content (Splunk docs typically use div with class 'content' or 'article-content')
            main_content = soup.find('div', class_=['content', 'article-content', 'main-content'])

            if not main_content:
                # Fallback: try to find main article or body
                main_content = soup.find('article') or soup.find('main') or soup.body

            if not main_content:
                logger.error(f"❌ Could not find main content in {url}")
                self.failed_count += 1
                return False

            # Remove navigation, footer, and script elements
            for element in main_content.find_all(['nav', 'footer', 'script', 'style']):
                element.decompose()

            # Convert to markdown
            markdown_content = md(str(main_content), heading_style="ATX")

            # Add metadata header
            header = f"""# {filename.replace('_', ' ').title()}

**Source:** {url}
**Category:** {category}
**Downloaded:** {time.strftime('%Y-%m-%d')}

---

"""
            markdown_content = header + markdown_content

            # Write to file
            filepath.write_text(markdown_content, encoding='utf-8')

            file_size = filepath.stat().st_size
            if file_size < MIN_CONTENT_LEN:
                logger.warning(f"⚠️  Downloaded file is small ({file_size} bytes), may be incomplete")
                self.failed_count += 1
                return False

            logger.info(f"✓ Downloaded {category}/{filename} ({file_size} bytes)")
            self.downloaded_count += 1
            time.sleep(1)  # Be nice to Splunk's servers
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to download {url}: {e}")
            self.failed_count += 1
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error downloading {url}: {e}")
            self.failed_count += 1
            return False

    def download_all(self) -> Dict[str, any]:
        """Download all documentation pages."""

        logger.info("=" * 80)
        logger.info("DOWNLOADING ADVANCED SPLUNK DOCUMENTATION")
        logger.info("=" * 80)
        logger.info(f"Target directory: {self.target_dir}")
        logger.info(f"Mode: {'FORCE RE-DOWNLOAD' if self.force_download else 'SKIP EXISTING FILES'}")
        logger.info("")

        total_pages = sum(len(urls) for urls in self.DOCS_URLS.values())
        logger.info(f"Total pages to download: {total_pages}")
        logger.info("")

        for category, urls in self.DOCS_URLS.items():
            logger.info(f"📁 Category: {category.upper()}")
            logger.info(f"   Pages: {len(urls)}")

            for filename, url in urls.items():
                self.download_page(url, filename, category)

            logger.info("")

        logger.info("=" * 80)
        logger.info("DOWNLOAD SUMMARY")
        logger.info("=" * 80)
        logger.info(f"✓ Downloaded: {self.downloaded_count}")
        logger.info(f"⊘ Skipped: {self.skipped_count}")
        logger.info(f"❌ Failed: {self.failed_count}")
        logger.info(f"📊 Total: {total_pages}")
        logger.info("")

        return {
            'downloaded': self.downloaded_count,
            'skipped': self.skipped_count,
            'failed': self.failed_count,
            'total': total_pages
        }


def main():
    parser = argparse.ArgumentParser(
        description='Download advanced Splunk documentation for ingestion'
    )
    parser.add_argument(
        'target_dir',
        type=Path,
        help='Target directory for downloaded documentation'
    )
    parser.add_argument(
        '--force-download',
        action='store_true',
        help='Force re-download even if files already exist'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    downloader = AdvancedDocsDownloader(
        target_dir=args.target_dir,
        force_download=args.force_download
    )

    result = downloader.download_all()

    if result['failed'] > 0:
        logger.warning(f"⚠️  {result['failed']} pages failed to download")
        sys.exit(1)

    logger.info("✅ All documentation downloaded successfully!")
    sys.exit(0)


if __name__ == '__main__':
    main()
