"""
Path-Aware Repository Ingestion
Preserves full path structure and semantic meaning for organization repository
"""
import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Tuple
import re

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PathSemanticParser:
    """
    Parse organization repository paths to extract semantic meaning.

    Repository structure:
    /opt/obsai/chatapp/documents/repo/splunk/
    ├── TAs/              # Technology Add-ons
    ├── IAs/              # Input Apps
    ├── Scripts/          # Admin scripts
    ├── BAs/              # Base Apps
    └── UIs/              # UI Apps
        ├── soc-dev/          # Security dev
        ├── org-search/       # Department/program users
        ├── org-es/           # Enterprise Security
        ├── org-ds/           # Deployment Server
        ├── org-itsi/         # ITSI
        ├── org-mltk/         # ML Toolkit
        ├── org-dma/          # Data Model Accel
        ├── _global/          # All SH/indexers/HF
        └── manager-apps/     # Indexers
    """

    APP_TYPE_MEANINGS = {
        "TAs": "Technology Add-on (data collection and parsing)",
        "IAs": "Input App (inputs.conf for Universal Forwarders)",
        "Scripts": "Administrative scripts",
        "BAs": "Base App (HEC tokens, outputs.conf, foundational configs)",
        "UIs": "UI App (dashboards, reports, saved searches - visibility enabled)"
    }

    INSTANCE_MEANINGS = {
        "soc-dev": "Security Operations Center - Development environment",
        "org-search": "Organization Search (org-search) - Department/program users",
        "org-es": "Enterprise Security (org-es) - Security analytics",
        "org-ds": "Deployment Server - App deployment management",
        "org-itsi": "IT Service Intelligence - Observability and monitoring",
        "org-mltk": "Machine Learning Toolkit Server",
        "org-dma": "Data Model Acceleration Server",
        "_global": "Global deployment - All search heads, indexers, heavy forwarders",
        "manager-apps": "Indexer Manager Apps - Indexer-specific configurations"
    }

    DEPLOYMENT_TARGETS = {
        "TAs": "Search heads and indexers (for data parsing)",
        "IAs": "Universal Forwarders (for data collection)",
        "Scripts": "Administrative servers",
        "BAs": "All Splunk components (foundational)",
        "UIs": "Search heads (for UI visibility)"
    }

    @staticmethod
    def parse_path(file_path: str) -> Dict[str, str]:
        """
        Extract semantic meaning from repository path.

        Args:
            file_path: Full path like /opt/obsai/.../repo/splunk/UIs/org-search/app/default/savedsearches.conf

        Returns:
            Dict with semantic context
        """
        # Normalize path
        path = str(file_path).replace('\\', '/')

        # Split into parts
        parts = path.split('/')

        # Find repo/splunk base
        try:
            # Look for 'repo' in path
            repo_idx = None
            for i, part in enumerate(parts):
                if part == 'repo':
                    repo_idx = i
                    break

            if repo_idx is None:
                return {"error": "Not a repo path", "full_path": file_path}

            # Find 'splunk' after repo
            splunk_idx = None
            for i in range(repo_idx + 1, len(parts)):
                if parts[i] == 'splunk':
                    splunk_idx = i
                    break

            if splunk_idx is None:
                return {"error": "No splunk directory found", "full_path": file_path}

        except (ValueError, IndexError) as e:
            return {"error": f"Path parsing error: {e}", "full_path": file_path}

        # Get path components after repo/splunk/
        repo_parts = parts[splunk_idx + 1:]

        if len(repo_parts) < 1:
            return {"error": "Invalid repo structure - no subdirectories", "full_path": file_path}

        # Extract semantic components
        app_type = repo_parts[0] if len(repo_parts) > 0 else None
        instance = repo_parts[1] if len(repo_parts) > 1 else None
        app_name = repo_parts[2] if len(repo_parts) > 2 else None
        config_scope = repo_parts[3] if len(repo_parts) > 3 else None
        filename = parts[-1] if parts else "unknown"

        # Build context
        context = {
            "app_type": app_type,
            "app_type_meaning": PathSemanticParser.APP_TYPE_MEANINGS.get(
                app_type, f"Unknown type: {app_type}"
            ),
            "instance": instance,
            "instance_meaning": PathSemanticParser.INSTANCE_MEANINGS.get(
                instance, f"Environment: {instance}" if instance else ""
            ),
            "app_name": app_name,
            "config_scope": config_scope,  # default or local
            "filename": filename,
            "full_path": file_path,
            "relative_path": '/'.join(repo_parts),
            "deployment_target": PathSemanticParser._get_deployment_target(app_type, instance)
        }

        return context

    @staticmethod
    def _get_deployment_target(app_type: str, instance: str) -> str:
        """Determine where this config should be deployed"""

        # Special instances override app type
        if instance == "_global":
            return "All search heads, indexers, and heavy forwarders"
        elif instance == "manager-apps":
            return "Indexers only"
        elif instance == "org-ds":
            return "Deployment Server"

        # Get base target from app type
        base_target = PathSemanticParser.DEPLOYMENT_TARGETS.get(
            app_type, "Unknown target"
        )

        if instance:
            return f"{base_target} - Environment: {instance}"

        return base_target

    @staticmethod
    def build_context_header(path_context: Dict, stanza: str = None) -> str:
        """Build context-rich header for chunk text"""

        if "error" in path_context:
            return f"## {path_context.get('filename', 'Unknown')}\n"

        header = f"""## {path_context['filename']}

**Type:** {path_context['app_type_meaning']}
**Environment:** {path_context['instance_meaning']}
**App:** {path_context.get('app_name', 'N/A')}
**Scope:** {path_context.get('config_scope', 'N/A')} ({"environment-specific override" if path_context.get('config_scope') == 'local' else "default configuration"})
**Deployment Target:** {path_context['deployment_target']}
**Path:** `{path_context['relative_path']}`
"""

        if stanza:
            header += f"\n**Stanza:** `[{stanza}]`\n"

        header += "\n### Configuration Content\n\n"

        return header


def ingest_repo_with_path_context(
    repo_root: str = "/opt/obsai/chatapp/documents/repo/splunk",
    output_file: str = None
):
    """
    Ingest repository with full path-aware metadata.

    Args:
        repo_root: Root directory of repository
        output_file: Optional output file for debugging
    """

    from chat_app.vectorstore import get_vector_store
    from chat_app.conf_parser import chunk_conf_file

    logger.info(f"Starting path-aware ingestion from: {repo_root}")

    if not os.path.exists(repo_root):
        logger.error(f"Repository root not found: {repo_root}")
        return

    # Get vector store
    try:
        store = get_vector_store("org_repo_mxbai")
    except Exception as e:
        logger.error(f"Failed to get vector store: {e}")
        return

    # Stats
    total_files = 0
    total_chunks = 0
    files_by_type = {}

    # Walk repository
    for root, dirs, files in os.walk(repo_root):
        for filename in files:
            # Only process .conf files
            if not filename.endswith('.conf'):
                continue

            file_path = os.path.join(root, filename)

            try:
                # Parse path for semantic context
                path_context = PathSemanticParser.parse_path(file_path)

                if "error" in path_context:
                    logger.warning(f"Skipping {file_path}: {path_context['error']}")
                    continue

                # Track by app type
                app_type = path_context.get('app_type', 'unknown')
                files_by_type[app_type] = files_by_type.get(app_type, 0) + 1

                # Read file
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # Parse into stanzas using conf_parser
                stanza_chunks = chunk_conf_file(
                    content,
                    filename,
                    max_chunk_size=500
                )

                # Enhance each chunk with path context
                enhanced_chunks = []
                for chunk_text, chunk_metadata in stanza_chunks:
                    # Get stanza name if available
                    stanza = chunk_metadata.get('stanza') or chunk_metadata.get('stanzas', [None])[0]

                    # Build context header
                    context_header = PathSemanticParser.build_context_header(
                        path_context, stanza
                    )

                    # Enhanced text with context
                    enhanced_text = context_header + chunk_text

                    # Enhanced metadata
                    enhanced_metadata = {
                        # Original
                        **chunk_metadata,

                        # Path semantics
                        "source": file_path,
                        "app_type": path_context['app_type'],
                        "app_type_meaning": path_context['app_type_meaning'],
                        "instance": path_context.get('instance'),
                        "instance_meaning": path_context.get('instance_meaning'),
                        "app_name": path_context.get('app_name'),
                        "config_scope": path_context.get('config_scope'),
                        "relative_path": path_context['relative_path'],
                        "deployment_target": path_context['deployment_target'],

                        # Collection
                        "collection": "org_repo_mxbai",
                        "type": "org_config_path_aware"
                    }

                    enhanced_chunks.append((enhanced_text, enhanced_metadata))

                # Add to vector store
                if enhanced_chunks:
                    texts = [text for text, _ in enhanced_chunks]
                    metadatas = [meta for _, meta in enhanced_chunks]

                    store.add_texts(texts=texts, metadatas=metadatas)

                    total_files += 1
                    total_chunks += len(enhanced_chunks)

                    logger.info(
                        f"✅ {path_context['app_type']}/{path_context.get('instance', '?')}/{filename}: "
                        f"{len(enhanced_chunks)} chunks"
                    )

            except Exception as e:
                logger.error(f"Failed to process {file_path}: {e}")
                continue

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("PATH-AWARE INGESTION COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Total files ingested: {total_files}")
    logger.info(f"Total chunks created: {total_chunks}")
    logger.info("\nFiles by app type:")
    for app_type, count in sorted(files_by_type.items()):
        logger.info(f"  {app_type}: {count} files")
    logger.info("=" * 70)


def test_path_parser():
    """Test path parsing with sample paths"""

    test_paths = [
        "/opt/obsai/chatapp/documents/repo/splunk/UIs/org-search/search_app/default/savedsearches.conf",
        "/opt/obsai/chatapp/documents/repo/splunk/IAs/_global/syslog/default/inputs.conf",
        "/opt/obsai/chatapp/documents/repo/splunk/BAs/org-es/hec_tokens/local/inputs.conf",
        "/opt/obsai/chatapp/documents/repo/splunk/TAs/org-itsi/ta_monitoring/default/props.conf",
        "/opt/obsai/chatapp/documents/repo/splunk/Scripts/manager-apps/admin_scripts/backup.sh",
    ]

    print("=" * 70)
    print("PATH PARSER TEST")
    print("=" * 70)

    for path in test_paths:
        context = PathSemanticParser.parse_path(path)
        print(f"\n📁 Path: {path}")
        print(f"   App Type: {context.get('app_type')} - {context.get('app_type_meaning')}")
        print(f"   Instance: {context.get('instance')} - {context.get('instance_meaning')}")
        print(f"   App Name: {context.get('app_name')}")
        print(f"   Scope: {context.get('config_scope')}")
        print(f"   Deployment: {context.get('deployment_target')}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test mode
        test_path_parser()
    else:
        # Ingestion mode
        repo_root = sys.argv[1] if len(sys.argv) > 1 else "/opt/obsai/chatapp/documents/repo/splunk"
        ingest_repo_with_path_context(repo_root)
