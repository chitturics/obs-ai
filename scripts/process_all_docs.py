#!/usr/bin/env python3
"""
Comprehensive document processing pipeline:
1. Rename PDFs with proper descriptive names
2. Convert specs, commands, and PDFs to clean text
3. Generate Q&A pairs for all documents

Usage:
    python scripts/process_all_docs.py
    python scripts/process_all_docs.py --rename-only
    python scripts/process_all_docs.py --qa-only
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import hashlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DOCS_DIR = PROJECT_ROOT / "documents"
SPECS_DIR = DOCS_DIR / "specs"
COMMANDS_DIR = DOCS_DIR / "commands"
PDFS_DIR = DOCS_DIR / "pdfs"
QA_OUTPUT_DIR = PROJECT_ROOT / "qa_dataset"

# Try to import PDF processing libraries
try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    logger.warning("PyMuPDF not installed. PDF processing will be limited.")

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


def extract_pdf_title(pdf_path: Path) -> Optional[str]:
    """Extract title from PDF metadata or first page content."""
    if HAS_PYMUPDF:
        try:
            doc = fitz.open(str(pdf_path))
            # Try metadata first
            metadata = doc.metadata
            if metadata and metadata.get("title"):
                title = metadata["title"].strip()
                if len(title) > 5 and not title.startswith("Microsoft"):
                    doc.close()
                    return title

            # Try first page text
            if doc.page_count > 0:
                first_page = doc[0]
                text = first_page.get_text()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                # Find first substantial line that looks like a title
                for line in lines[:10]:
                    # Skip short lines, URLs, dates
                    if len(line) > 10 and len(line) < 150:
                        if not re.match(r'^(http|www\.|[0-9]{1,2}/|page|©)', line.lower()):
                            doc.close()
                            return line
            doc.close()
        except Exception as e:
            logger.debug(f"PyMuPDF error for {pdf_path.name}: {e}")

    if HAS_PYPDF:
        try:
            reader = PdfReader(str(pdf_path))
            if reader.metadata and reader.metadata.title:
                title = reader.metadata.title.strip()
                if len(title) > 5:
                    return title
        except Exception as e:
            logger.debug(f"pypdf error for {pdf_path.name}: {e}")

    return None


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract full text from PDF."""
    text_parts = []

    if HAS_PYMUPDF:
        try:
            doc = fitz.open(str(pdf_path))
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.warning(f"PyMuPDF extraction failed for {pdf_path.name}: {e}")

    if HAS_PYPDF:
        try:
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.warning(f"pypdf extraction failed for {pdf_path.name}: {e}")

    return ""


def sanitize_filename(name: str) -> str:
    """Convert title to valid filename."""
    # Remove/replace invalid characters
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '-', name)
    name = re.sub(r'-+', '-', name)
    name = name.strip('-')
    # Truncate to reasonable length
    if len(name) > 80:
        name = name[:80].rsplit('-', 1)[0]
    return name.lower()


def rename_pdfs(dry_run: bool = False) -> Dict[str, str]:
    """Rename PDFs with descriptive names based on content."""
    logger.info("=" * 60)
    logger.info("RENAMING PDFs")
    logger.info("=" * 60)

    if not PDFS_DIR.exists():
        logger.warning(f"PDFs directory not found: {PDFS_DIR}")
        return {}

    renamed = {}
    skipped = []

    # Mapping of known PDFs to better names (manual overrides)
    known_mappings = {
        # Research papers
        "1912.11283v1.pdf": "sentence-bert-embeddings-paper.pdf",

        # Splunk .conf presentations
        "Advanced Dashboards & Visualizations (.CONF 2015).pdf": "splunk-conf2015-advanced-dashboards.pdf",
        "Building Splunk Apps (.CONF 2015).pdf": "splunk-conf2015-building-apps.pdf",
        "Creating Splunk 6.2 Knowledge Objects (.CONF 2015).pdf": "splunk-conf2015-knowledge-objects.pdf",
        "Creating Splunk 6.2 Knowledge Objects.pdf": "splunk-knowledge-objects-guide.pdf",
        "Deployment Best Practices (.CONF 2015).pdf": "splunk-conf2015-deployment-best-practices.pdf",
        "Searching & Reporting with Splunk 6.2 (.CONF 2015).pdf": "splunk-conf2015-searching-reporting.pdf",
        "Searching and Reporting with Splunk 6.2.pdf": "splunk-searching-reporting-guide.pdf",
        "Splunk 6.2 Administration.pdf": "splunk-administration-guide.pdf",
        "Splunk Cluster Administration.pdf": "splunk-cluster-administration-guide.pdf",

        # Clustering guides
        "behind-the-magnifying-glass-how-search-works.pdf": "splunk-how-search-works.pdf",
        "easing-into-clustering.pdf": "splunk-clustering-introduction.pdf",
        "indexer-clustering-basics-internals-and-debugging.pdf": "splunk-indexer-clustering-basics.pdf",
        "indexer-clustering-fixups-how-a-cluster-recovers-from-failures.pdf": "splunk-indexer-clustering-recovery.pdf",
        "indexer-clustering-internals-scaling-and-performance.pdf": "splunk-indexer-clustering-scaling.pdf",
        "pushing-configuration-bundles-in-an-indexer-cluster.pdf": "splunk-cluster-config-bundles.pdf",
        "rebalancing-data-across-an-indexer-cluster.pdf": "splunk-cluster-data-rebalancing.pdf",
        "replication-of-summary-data-in-indexer-cluster.pdf": "splunk-cluster-summary-replication.pdf",
        "scaling-indexer-clustering-5-million-unique-buckets-and-beyond.pdf": "splunk-cluster-scaling-millions.pdf",
        "search-head-clustering-basics-to-best-practices.pdf": "splunk-search-head-clustering.pdf",

        # Search optimization
        "best-practices-and-better-practices-for-users.pdf": "splunk-best-practices-users.pdf",
        "lesser-known-search-commands.pdf": "splunk-lesser-known-commands.pdf",
        "optimized-search-optimization.pdf": "splunk-search-optimization.pdf",
        "power-of-spl.pdf": "splunk-power-of-spl.pdf",
        "term and prefix.pdf": "splunk-term-prefix-optimization.pdf",

        # Reference guides
        "splunk-quick-reference-guide.pdf": "splunk-quick-reference-guide.pdf",
        "splunk-dashboards-quick-reference-guide.pdf": "splunk-dashboards-quick-reference.pdf",
        "splunk-dashboards-quick-reference-guide (1).pdf": "splunk-dashboards-quick-reference-2.pdf",
        "splunk-validated-architectures.pdf": "splunk-validated-architectures.pdf",
        "Splunk_Cheat_Sheet.pdf": "splunk-cheat-sheet.pdf",
        "exploring-splunk.pdf": "splunk-exploring-guide.pdf",
        "splunk_tutorial.pdf": "splunk-tutorial-guide.pdf",
        "splunk_getting_started_ug.pdf": "splunk-getting-started-guide.pdf",

        # Security
        "splunk-cybersecurity-framework.pdf": "splunk-cybersecurity-framework.pdf",
        "splunk-es-correlation-searches-best-practices-v1.0-rev2.pdf": "splunk-es-correlation-searches.pdf",
        "EssentialGuidetoSecurity-Splunk-ES.pdf": "splunk-essential-guide-security.pdf",
        "Splunk-Enterprise-Security.pdf": "splunk-enterprise-security-factsheet.pdf",
        "SEC1583_TurningSecurityUseCases_Final_1538510573435001VmSg.pdf": "splunk-turning-security-use-cases.pdf",
        "discovering-security-events-interest-splunk_33478.pdf": "splunk-discovering-security-events.pdf",
        "Splunk201312-Security_Analytics.pdf": "splunk-security-analytics.pdf",
        "QDS-0004_Suspicious Login Activity.pdf": "splunk-suspicious-login-activity.pdf",

        # Training and courses
        "Fundamentals2_LabGuide8.0.pdf": "splunk-fundamentals2-lab-guide.pdf",
        "SplunkFundamentals1_module7.pdf": "splunk-fundamentals1-module7.pdf",
        "distributed-search-course-description.pdf": "splunk-distributed-search-course.pdf",
        "working-with-time-course-description.pdf": "splunk-working-with-time.pdf",
        "logo_345_1650015173_using-splunk-search-language-beginner.pdf": "splunk-search-language-beginner.pdf",
        "angularJS_essentials.pdf": "angularjs-essentials.pdf",

        # Troubleshooting
        "Troubleshoot backend indexinig pipeline.pdf": "splunk-troubleshoot-indexing-pipeline.pdf",

        # Third-party integrations
        "CrowdStrike-Scheduled-Search-Technical-Add-Guide-v2.2.0.pdf": "crowdstrike-splunk-integration.pdf",
        "ForeScout-App-Splunk-2.5-Guide.pdf": "forescout-splunk-app-guide.pdf",
        "DomainTools_Splunk_App_5-2_userguide.pdf": "domaintools-splunk-app-guide.pdf",
        "Tenable_and_Splunk_Integration_Guide.pdf": "tenable-splunk-integration.pdf",
        "7252-tr4650.pdf": "netapp-ontap-splunk-guide.pdf",
        "proofpoint-splunk-et-intelligence-tech-brief-fin.pdf": "proofpoint-splunk-integration.pdf",
        "sb-fireeye-splunk.pdf": "fireeye-splunk-integration.pdf",

        # Architecture and deployment
        "Architecting and Deploying Splunk 6.4.pdf": "splunk-architecting-deploying.pdf",
        "twp-splunk-smartstore-portworx-flashblade.pdf": "splunk-smartstore-guide.pdf",
        "h19160-da-pm-splunk-wp.pdf": "splunk-cloud-native-smartstore.pdf",
        "migrating-to-splunk-cloud.pdf": "splunk-migrating-to-cloud.pdf",
        "Spluk-VMware-IT-draft-case-study_final.pdf": "splunk-vmware-vsan-case-study.pdf",
        "Nutanix-ClearShark-286-EN-6.pdf": "nutanix-splunk-solution.pdf",

        # Other useful docs
        "Splunk_CIS-Critical-Security-Controls_eBook.pdf": "splunk-cis-security-controls.pdf",
        "Splunk_Datasheet.pdf": "splunk-datasheet.pdf",
        "Splunk+Essentials+-+A+Summary+by+Dr.+Alvin+Ang.pdf": "splunk-essentials-summary.pdf",
        "splunk-enterprise.pdf": "splunk-enterprise-product-brief.pdf",
        "splunk-enterprise-dns.pdf": "splunk-enterprise-dns-correlation.pdf",
        "splunk-light-tech-brief.pdf": "splunk-light-tech-brief.pdf",
        "Splunk-Getting-started-for-monitoring-and-diagnostics.pdf": "splunk-monitoring-diagnostics-guide.pdf",
        "splunk_connector_en.pdf": "splunk-connector-guide.pdf",
        "microsoft-expanded-cloud-logs-implementation-playbook-508c.pdf": "microsoft-cloud-logs-splunk-playbook.pdf",
        "trino-summit-2024-intuit.pdf": "trino-summit-2024-intuit.pdf",
        "TDR226-S_Building-a-better-lake-Federated-search-for-Amazon-Security-Lake-sponsored-by-Splunk.pdf": "splunk-federated-search-amazon-lake.pdf",
        "A-Guide-to-reduce-Splunk-costs.pdf": "splunk-cost-reduction-guide.pdf",
        "BUCamp2016-Finding-Little-Things.pdf": "splunk-finding-little-things.pdf",
        "Creative_Componenent_FatimaAbdElmajid.pdf": "splunk-cybersecurity-courses.pdf",
        "Apptitude Rules.pdf": "apptitude-rules.pdf",
        "DOS_Splunk_Program_FAQs_Jan_2021.pdf": "dos-splunk-program-faqs.pdf",
        "ARIACS-ARIASDS-Five-Enhancements-SplunkES.pdf": "ariacs-splunk-es-enhancements.pdf",

        # Remove unrelated/junk files (map to keep original)
        "5ff01936b0d057bd6daa87670a878fee.pdf": "splunk-cheatsheet-old.pdf",
        "611681806284845-service-definition-document-2024-05-01-1216.pdf": "splunk-service-definition.pdf",
        "71-1637097759.pdf": "jordanian-jjcit-splunk.pdf",
        "FN1061.pdf": "splunk-conf-aplura-integration.pdf",
        "FN1407.pdf": "splunk-conf-landen.pdf",
        "FN1635.pdf": "splunk-conf-scalability.pdf",
        "FN2067.pdf": "splunk-conf-architecting.pdf",
        "FN2188.pdf": "splunk-conf-kawasaki.pdf",
        "FNC2751.pdf": "splunk-conf-sideview.pdf",
        "splunk.pdf": "splunk-general.pdf",
        "real-splunk-splk-2002-study-questions-by-acosta.pdf": "splunk-splk-2002-study-questions.pdf",
        "fraudulent-cv-2.pdf": "fraudulent-cv-unrelated.pdf",
        "DMO100786636-whitepaper.pdf": "hybrid-cloud-tco-analysis.pdf",
        "lucidworks_fusion_splunk_datasheet.pdf": "lucidworks-fusion-splunk.pdf",
        "micro-focus-sodp-and-splunk-flyer.pdf": "micro-focus-arcsight-splunk.pdf",
        "ps-sd-splunk.pdf": "pulse-secure-splunk-guide.pdf",
        "sdmt-pia.pdf": "sdmt-pia-unrelated.pdf",
        "SA-devforall_handson_leave_behind.pdf": "splunk-dev-handson-guide.pdf",
        "Academy-brochure-Data-Analysis-2-page.pdf": "academy-data-analysis-brochure.pdf",
    }

    for pdf_file in sorted(PDFS_DIR.glob("*.pdf")):
        original_name = pdf_file.name

        # Check if we have a manual mapping
        if original_name in known_mappings:
            new_name = known_mappings[original_name]
        else:
            # Try to extract title from PDF
            title = extract_pdf_title(pdf_file)
            if title:
                new_name = sanitize_filename(title) + ".pdf"
            else:
                # Use original name but sanitize
                new_name = sanitize_filename(original_name.replace(".pdf", "")) + ".pdf"

        # Ensure unique name
        if new_name != original_name:
            new_path = pdf_file.parent / new_name
            counter = 1
            while new_path.exists() and new_path != pdf_file:
                base = new_name.rsplit(".", 1)[0]
                new_name = f"{base}-{counter}.pdf"
                new_path = pdf_file.parent / new_name
                counter += 1

            if dry_run:
                logger.info(f"  [DRY RUN] {original_name} -> {new_name}")
            else:
                try:
                    pdf_file.rename(new_path)
                    logger.info(f"  Renamed: {original_name} -> {new_name}")
                    renamed[original_name] = new_name
                except Exception as e:
                    logger.error(f"  Failed to rename {original_name}: {e}")
                    skipped.append(original_name)
        else:
            logger.debug(f"  Skipped (already named): {original_name}")
            skipped.append(original_name)

    logger.info(f"Renamed {len(renamed)} PDFs, skipped {len(skipped)}")
    return renamed


def read_spec_file(spec_path: Path) -> str:
    """Read and return spec file content."""
    try:
        return spec_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Failed to read {spec_path}: {e}")
        return ""


def read_command_file(cmd_path: Path) -> str:
    """Read and return command markdown file content."""
    try:
        content = cmd_path.read_text(encoding="utf-8", errors="ignore")
        # Remove YAML frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()
        return content
    except Exception as e:
        logger.error(f"Failed to read {cmd_path}: {e}")
        return ""


def generate_spec_qa(spec_path: Path) -> List[Dict]:
    """Generate Q&A pairs from a spec file."""
    content = read_spec_file(spec_path)
    if not content:
        return []

    qa_pairs = []
    filename = spec_path.name
    conf_name = filename.replace(".spec", "").replace(".conf", "")

    # Parse stanzas
    current_stanza = None
    current_settings = []
    stanza_description = ""

    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for stanza header
        if stripped.startswith("[") and stripped.endswith("]"):
            # Save previous stanza
            if current_stanza and current_settings:
                qa = create_stanza_qa(conf_name, current_stanza, current_settings, stanza_description)
                if qa:
                    qa_pairs.append(qa)

            current_stanza = stripped[1:-1]
            current_settings = []
            stanza_description = ""

            # Look for description in comments before stanza
            j = i - 1
            desc_lines = []
            while j >= 0 and lines[j].strip().startswith("#"):
                desc_lines.insert(0, lines[j].strip().lstrip("#").strip())
                j -= 1
            stanza_description = " ".join(desc_lines)

        elif current_stanza and "=" in stripped and not stripped.startswith("#"):
            # Setting definition
            current_settings.append(stripped)

        i += 1

    # Don't forget last stanza
    if current_stanza and current_settings:
        qa = create_stanza_qa(conf_name, current_stanza, current_settings, stanza_description)
        if qa:
            qa_pairs.append(qa)

    # Add overview Q&A for the whole file
    if qa_pairs:
        overview_qa = {
            "instruction": f"What is {filename} used for in Splunk?",
            "output": f"{filename} is a Splunk configuration file that defines settings for {conf_name}. It contains {len(qa_pairs)} main stanzas/sections. Key stanzas include: {', '.join([qa.get('metadata', {}).get('stanza', '')[:30] for qa in qa_pairs[:5]])}...",
            "metadata": {
                "source_file": filename,
                "source_type": "spec",
                "stanza": "overview",
                "confidence": 0.9
            }
        }
        qa_pairs.insert(0, overview_qa)

    return qa_pairs


def create_stanza_qa(conf_name: str, stanza: str, settings: List[str], description: str) -> Optional[Dict]:
    """Create a Q&A pair for a stanza."""
    if not settings:
        return None

    # Build answer
    answer_parts = []
    if description:
        answer_parts.append(description)
        answer_parts.append("")

    answer_parts.append(f"Stanza: [{stanza}]")
    answer_parts.append("Settings:")
    for setting in settings[:15]:  # Limit to avoid huge answers
        answer_parts.append(f"  {setting}")

    if len(settings) > 15:
        answer_parts.append(f"  ... and {len(settings) - 15} more settings")

    answer = "\n".join(answer_parts)

    # Create question
    if stanza == "default":
        question = f"What are the default settings in {conf_name}.conf?"
    elif stanza.startswith("<"):
        # Template stanza like <name> or <stanza>
        question = f"How do I configure a custom {stanza} stanza in {conf_name}.conf?"
    else:
        question = f"How do I configure the [{stanza}] stanza in {conf_name}.conf?"

    return {
        "instruction": question,
        "output": answer,
        "metadata": {
            "source_file": f"{conf_name}.conf.spec",
            "source_type": "spec",
            "stanza": stanza,
            "confidence": 0.85
        }
    }


def generate_command_qa(cmd_path: Path) -> List[Dict]:
    """Generate Q&A pairs from a command documentation file."""
    content = read_command_file(cmd_path)
    if not content or len(content) < 100:
        return []

    qa_pairs = []
    cmd_name = cmd_path.stem.replace("spl_cmd_", "")

    # Extract sections
    sections = re.split(r'^#{2,3}\s+', content, flags=re.MULTILINE)

    # Main overview Q&A
    overview = content[:1500] if len(content) > 1500 else content
    qa_pairs.append({
        "instruction": f"What is the {cmd_name} command in Splunk SPL?",
        "output": f"The {cmd_name} command is a Splunk SPL command.\n\n{overview}",
        "metadata": {
            "source_file": cmd_path.name,
            "source_type": "spl_command",
            "stanza": cmd_name,
            "confidence": 0.9
        }
    })

    # Look for syntax section
    syntax_match = re.search(r'(?:syntax|usage)[\s:]*\n+```?\n?([^`]+)', content, re.IGNORECASE)
    if syntax_match:
        syntax = syntax_match.group(1).strip()
        qa_pairs.append({
            "instruction": f"What is the syntax for the {cmd_name} command in Splunk?",
            "output": f"Syntax for {cmd_name}:\n\n```spl\n{syntax}\n```",
            "metadata": {
                "source_file": cmd_path.name,
                "source_type": "spl_command",
                "stanza": f"{cmd_name}_syntax",
                "confidence": 0.9
            }
        })

    # Look for examples section
    examples_match = re.search(r'(?:example|examples)[\s:]*\n(.+?)(?=^#{2,3}|\Z)', content, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    if examples_match:
        examples = examples_match.group(1).strip()[:2000]
        qa_pairs.append({
            "instruction": f"Show me examples of using the {cmd_name} command in Splunk SPL.",
            "output": f"Examples of {cmd_name}:\n\n{examples}",
            "metadata": {
                "source_file": cmd_path.name,
                "source_type": "spl_command",
                "stanza": f"{cmd_name}_examples",
                "confidence": 0.85
            }
        })

    return qa_pairs


def generate_pdf_qa(pdf_path: Path) -> List[Dict]:
    """Generate Q&A pairs from a PDF document."""
    text = extract_pdf_text(pdf_path)
    if not text or len(text) < 500:
        return []

    qa_pairs = []
    filename = pdf_path.stem

    # Clean up text
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)  # Split camelCase

    # Create overview Q&A
    overview = text[:2000] if len(text) > 2000 else text

    # Try to extract title from filename or first line
    title = filename.replace("-", " ").replace("_", " ").title()

    qa_pairs.append({
        "instruction": f"What is covered in the document '{title}'?",
        "output": f"Document: {title}\n\nSummary:\n{overview}",
        "metadata": {
            "source_file": pdf_path.name,
            "source_type": "pdf_document",
            "stanza": "overview",
            "confidence": 0.7
        }
    })

    # Split into sections and create Q&A for each meaningful section
    # Look for section headers (lines that are short and followed by longer content)
    sections = re.split(r'\n(?=[A-Z][A-Za-z\s]{5,50}:?\n)', text)

    for section in sections[1:10]:  # Limit sections
        lines = section.strip().split('\n', 1)
        if len(lines) == 2:
            section_title = lines[0].strip()
            section_content = lines[1].strip()[:1500]

            if len(section_content) > 200:
                qa_pairs.append({
                    "instruction": f"Explain '{section_title}' from {title}",
                    "output": section_content,
                    "metadata": {
                        "source_file": pdf_path.name,
                        "source_type": "pdf_document",
                        "stanza": section_title[:50],
                        "confidence": 0.7
                    }
                })

    return qa_pairs


def generate_all_qa():
    """Generate Q&A pairs from all document sources."""
    logger.info("=" * 60)
    logger.info("GENERATING Q&A PAIRS")
    logger.info("=" * 60)

    QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_qa = []
    stats = {"specs": 0, "commands": 0, "pdfs": 0}

    # Process specs
    if SPECS_DIR.exists():
        logger.info(f"Processing specs from {SPECS_DIR}...")
        for spec_file in sorted(SPECS_DIR.glob("*.spec")):
            qa_pairs = generate_spec_qa(spec_file)
            all_qa.extend(qa_pairs)
            stats["specs"] += len(qa_pairs)
            logger.debug(f"  {spec_file.name}: {len(qa_pairs)} Q&A pairs")

    # Process commands
    if COMMANDS_DIR.exists():
        logger.info(f"Processing commands from {COMMANDS_DIR}...")
        for cmd_file in sorted(COMMANDS_DIR.glob("*.md")):
            qa_pairs = generate_command_qa(cmd_file)
            all_qa.extend(qa_pairs)
            stats["commands"] += len(qa_pairs)
            logger.debug(f"  {cmd_file.name}: {len(qa_pairs)} Q&A pairs")

    # Process PDFs
    if PDFS_DIR.exists() and (HAS_PYMUPDF or HAS_PYPDF):
        logger.info(f"Processing PDFs from {PDFS_DIR}...")
        for pdf_file in sorted(PDFS_DIR.glob("*.pdf")):
            qa_pairs = generate_pdf_qa(pdf_file)
            all_qa.extend(qa_pairs)
            stats["pdfs"] += len(qa_pairs)
            logger.debug(f"  {pdf_file.name}: {len(qa_pairs)} Q&A pairs")
    elif PDFS_DIR.exists():
        logger.warning("Skipping PDFs: PyMuPDF or pypdf not installed")

    # Write combined output
    output_file = QA_OUTPUT_DIR / "documents_qa.jsonl"
    with open(output_file, "w", encoding="utf-8") as f:
        for qa in all_qa:
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    logger.info(f"Generated {len(all_qa)} Q&A pairs total:")
    logger.info(f"  Specs: {stats['specs']}")
    logger.info(f"  Commands: {stats['commands']}")
    logger.info(f"  PDFs: {stats['pdfs']}")
    logger.info(f"Output: {output_file}")

    # Also merge with existing all_qa.jsonl if it exists
    existing_qa_file = QA_OUTPUT_DIR / "all_qa.jsonl"
    if existing_qa_file.exists():
        logger.info("Merging with existing all_qa.jsonl...")
        existing_qa = []
        with open(existing_qa_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        existing_qa.append(json.loads(line))
                    except:
                        pass

        # Combine and dedupe by question
        combined = existing_qa + all_qa
        seen = set()
        unique = []
        for qa in combined:
            key = qa.get("instruction", "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(qa)

        # Write back
        with open(existing_qa_file, "w", encoding="utf-8") as f:
            for qa in unique:
                f.write(json.dumps(qa, ensure_ascii=False) + "\n")

        logger.info(f"Merged into {existing_qa_file}: {len(unique)} unique Q&A pairs")

    return stats


def main():
    parser = argparse.ArgumentParser(description="Process all documents into Q&A pairs")
    parser.add_argument("--rename-only", action="store_true", help="Only rename PDFs")
    parser.add_argument("--qa-only", action="store_true", help="Only generate Q&A pairs")
    parser.add_argument("--dry-run", action="store_true", help="Don't make actual changes")
    args = parser.parse_args()

    if args.rename_only:
        rename_pdfs(dry_run=args.dry_run)
    elif args.qa_only:
        generate_all_qa()
    else:
        # Full pipeline
        rename_pdfs(dry_run=args.dry_run)
        generate_all_qa()

    logger.info("Done!")


if __name__ == "__main__":
    main()
