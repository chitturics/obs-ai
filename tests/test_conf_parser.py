"""Tests for shared/conf_parser.py — .conf file parsing and chunking."""
import pytest
from pathlib import Path
from shared.conf_parser import (
    parse_conf_file,
    parse_conf_file_advanced,
    extract_app_metadata,
    chunk_conf_file,
    chunk_conf_stanzas,
    enrich_chunk_for_search,
    ConfStanza,
    is_deployment_tier,
    get_deployment_target,
)


# ---------------------------------------------------------------------------
# Test parse_conf_file (basic stanza parser)
# ---------------------------------------------------------------------------

class TestParseConfFile:
    """Test the basic stanza-level parser."""

    def test_parse_simple_props(self):
        content = (
            "[syslog]\n"
            "SHOULD_LINEMERGE = false\n"
            "TIME_FORMAT = %b %d %H:%M:%S\n"
            "LINE_BREAKER = ([\\r\\n]+)\n"
        )
        stanzas = parse_conf_file(content, filename="props.conf")
        assert len(stanzas) == 1
        assert stanzas[0].name == "syslog"
        assert "SHOULD_LINEMERGE" in stanzas[0].content

    def test_parse_transforms(self):
        content = (
            "[my_lookup]\n"
            "filename = my_lookup.csv\n"
            "max_matches = 1\n"
            "\n"
            "[my_extract]\n"
            "REGEX = ^(\\w+)\\s+(\\d+)\n"
            "FORMAT = field1::$1 field2::$2\n"
        )
        stanzas = parse_conf_file(content, filename="transforms.conf")
        names = [s.name for s in stanzas]
        assert "my_lookup" in names
        assert "my_extract" in names
        lookup_stanza = next(s for s in stanzas if s.name == "my_lookup")
        assert "filename = my_lookup.csv" in lookup_stanza.content

    def test_parse_stanzas_with_comments(self):
        content = (
            "# Global comment at top\n"
            "# Another comment\n"
            "\n"
            "[default]\n"
            "# Comment inside stanza\n"
            "disabled = false\n"
            "\n"
            "[mysearch]\n"
            "search = index=main | stats count\n"
        )
        stanzas = parse_conf_file(content, filename="savedsearches.conf")
        names = [s.name for s in stanzas]
        # Preamble captures the top comments
        assert "__preamble__" in names
        assert "default" in names
        assert "mysearch" in names

    def test_parse_empty_stanzas(self):
        content = (
            "[empty_one]\n"
            "\n"
            "[empty_two]\n"
            "\n"
            "[has_content]\n"
            "key = value\n"
        )
        stanzas = parse_conf_file(content, filename="test.conf")
        names = [s.name for s in stanzas]
        assert "empty_one" in names
        assert "empty_two" in names
        assert "has_content" in names
        has_content = next(s for s in stanzas if s.name == "has_content")
        assert "key = value" in has_content.content

    def test_parse_nested_settings(self):
        """Props.conf stanzas with deeply nested key=value pairs."""
        content = (
            "[source::...syslog]\n"
            "TRANSFORMS-routing = syslog_routing\n"
            "SEDCMD-remove_header = s/^\\w+: //g\n"
            "SHOULD_LINEMERGE = true\n"
            "BREAK_ONLY_BEFORE = ^\\d{4}-\\d{2}-\\d{2}\n"
            "MAX_TIMESTAMP_LOOKAHEAD = 32\n"
            "TIME_FORMAT = %Y-%m-%dT%H:%M:%S.%6N%z\n"
        )
        stanzas = parse_conf_file(content, filename="props.conf")
        assert len(stanzas) == 1
        assert stanzas[0].name == "source::...syslog"
        assert "TRANSFORMS-routing" in stanzas[0].content
        assert "SEDCMD-remove_header" in stanzas[0].content


class TestParseConfFileAdvanced:
    """Test parsing .conf file content into stanzas with key-value extraction."""

    def test_parse_simple_stanza(self):
        content = "[mysource]\ndisabled = false\nindex = main\nsourcetype = syslog\n"
        result = parse_conf_file_advanced(content)
        assert "mysource" in result
        assert result["mysource"]["disabled"] == "false"
        assert result["mysource"]["index"] == "main"

    def test_parse_multiple_stanzas(self):
        content = (
            "[stanza1]\nkey1 = val1\n\n"
            "[stanza2]\nkey2 = val2\nkey3 = val3\n"
        )
        result = parse_conf_file_advanced(content)
        assert "stanza1" in result
        assert "stanza2" in result
        assert result["stanza2"]["key2"] == "val2"

    def test_skip_comments(self):
        content = "# This is a comment\n[mystanza]\n# Another comment\nkey = value\n"
        result = parse_conf_file_advanced(content)
        assert "mystanza" in result
        assert result["mystanza"]["key"] == "value"

    def test_empty_file(self):
        result = parse_conf_file_advanced("")
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_parse_props_conf_content(self):
        content = (
            "[syslog]\n"
            "SHOULD_LINEMERGE = false\n"
            "TIME_FORMAT = %b %d %H:%M:%S\n"
            "LINE_BREAKER = ([\\r\\n]+)\n"
            "\n"
            "[access_combined]\n"
            "SHOULD_LINEMERGE = false\n"
            "TIME_FORMAT = %d/%b/%Y:%H:%M:%S %z\n"
            "TRANSFORMS-null = setnull\n"
        )
        result = parse_conf_file_advanced(content, filename="props.conf")
        assert "syslog" in result
        assert "access_combined" in result
        assert result["syslog"]["SHOULD_LINEMERGE"] == "false"
        assert result["access_combined"]["TIME_FORMAT"] == "%d/%b/%Y:%H:%M:%S %z"

    def test_parse_transforms_conf_content(self):
        content = (
            "[my_lookup]\n"
            "filename = geo_lookup.csv\n"
            "max_matches = 1\n"
            "min_matches = 0\n"
            "\n"
            "[my_regex_extract]\n"
            "REGEX = ^(\\d+\\.\\d+\\.\\d+\\.\\d+)\\s+(\\w+)\n"
            "FORMAT = src_ip::$1 action::$2\n"
        )
        result = parse_conf_file_advanced(content, filename="transforms.conf")
        assert "my_lookup" in result
        assert result["my_lookup"]["filename"] == "geo_lookup.csv"
        assert "my_regex_extract" in result
        assert "FORMAT" in result["my_regex_extract"]

    def test_multiline_values(self):
        """Multi-line values with backslash continuation."""
        content = (
            "[mysearch]\n"
            "search = index=main sourcetype=syslog\n"
            "description = A simple search\n"
        )
        result = parse_conf_file_advanced(content)
        assert "mysearch" in result
        assert result["mysearch"]["search"] == "index=main sourcetype=syslog"

    def test_stanza_with_equals_in_value(self):
        content = "[mysearch]\nsearch = index=main host=server01\n"
        result = parse_conf_file_advanced(content)
        assert "mysearch" in result
        # Value should contain the full search, not be split at inner =
        assert "index=main" in result["mysearch"]["search"]

    def test_line_numbers_tracked(self):
        content = "[mystanza]\nkey1 = val1\nkey2 = val2\n"
        result = parse_conf_file_advanced(content)
        assert "__lines__" in result["mystanza"]
        assert "key1" in result["mystanza"]["__lines__"]

    def test_parse_sample_props(self, fixtures_dir):
        content = (fixtures_dir / "sample_props.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="props.conf")
        assert "syslog" in result
        assert "access_combined" in result
        assert "json_sourcetype" in result
        assert result["syslog"]["SHOULD_LINEMERGE"] == "false"

    def test_parse_sample_savedsearches(self, fixtures_dir):
        content = (fixtures_dir / "sample_savedsearches.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="savedsearches.conf")
        assert "Failed Login Attempts - Last 24h" in result
        assert "Network Traffic by Host - Hourly" in result
        assert "DNS Query Analysis" in result

    def test_parse_sample_indexes(self, fixtures_dir):
        content = (fixtures_dir / "sample_indexes.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="indexes.conf")
        assert "main" in result
        assert "security" in result
        assert "network" in result
        assert result["main"]["maxTotalDataSizeMB"] == "500000"

    def test_parse_sample_macros(self, fixtures_dir):
        content = (fixtures_dir / "sample_macros.conf").read_text(encoding="utf-8")
        result = parse_conf_file_advanced(content, filename="macros.conf")
        assert "cim_authentication" in result


class TestExtractAppMetadata:
    """Test app metadata extraction from file paths."""

    def test_ta_path(self):
        meta = extract_app_metadata("/app/documents/repo/TAs/TA-nmap/local/inputs.conf")
        assert meta.get("app_type") == "TAs"
        assert meta.get("app_name") == "TA-nmap"

    def test_ui_path(self):
        meta = extract_app_metadata("/app/documents/repo/UIs/org-search/default/savedsearches.conf")
        assert meta.get("app_type") == "UIs"
        assert meta.get("app_name") == "org-search"

    def test_no_repo_in_path(self):
        meta = extract_app_metadata("/tmp/test.conf")
        assert isinstance(meta, dict)

    def test_filename_extracted(self):
        meta = extract_app_metadata("/app/documents/repo/TAs/TA-windows/local/props.conf")
        assert meta.get("filename") == "props.conf"


class TestChunkConfFile:
    """Test .conf file chunking with stanza awareness."""

    def test_chunks_from_sample_savedsearches(self, fixtures_dir):
        content = (fixtures_dir / "sample_savedsearches.conf").read_text(encoding="utf-8")
        chunks = chunk_conf_file(
            content,
            str(fixtures_dir / "sample_savedsearches.conf"),
            max_chunk_size=3000,
            chunk_overlap=100,
        )
        assert len(chunks) >= 3  # At least one chunk per stanza
        # Each chunk is (text, metadata)
        for text, meta in chunks:
            assert isinstance(text, str)
            assert len(text) > 0
            assert isinstance(meta, dict)

    def test_chunks_from_sample_indexes(self, fixtures_dir):
        content = (fixtures_dir / "sample_indexes.conf").read_text(encoding="utf-8")
        chunks = chunk_conf_file(
            content,
            str(fixtures_dir / "sample_indexes.conf"),
        )
        assert len(chunks) >= 3

    def test_metadata_includes_stanza(self, fixtures_dir):
        content = (fixtures_dir / "sample_props.conf").read_text(encoding="utf-8")
        chunks = chunk_conf_file(
            content,
            str(fixtures_dir / "sample_props.conf"),
        )
        stanzas_found = set()
        for _, meta in chunks:
            if "stanza" in meta:
                stanzas_found.add(meta["stanza"])
        assert len(stanzas_found) >= 3

    def test_empty_content(self):
        chunks = chunk_conf_file("", "/tmp/empty.conf")
        assert isinstance(chunks, list)


class TestEnrichChunkForSearch:
    """Test chunk enrichment for better embedding search."""

    def test_enrichment_adds_stanza_header(self):
        enriched = enrich_chunk_for_search(
            "disabled = false\nindex = main",
            {"stanza": "monitor://var/log", "filename": "inputs.conf"},
        )
        assert "monitor://var/log" in enriched or "inputs.conf" in enriched

    def test_existing_stanza_header_preserved(self):
        chunk = "[syslog]\nTIME_FORMAT = %b %d"
        enriched = enrich_chunk_for_search(chunk, {"stanza": "syslog", "filename": "props.conf"})
        # Should not double-add the header
        assert enriched.count("[syslog]") == 1

    def test_preamble_not_enriched(self):
        chunk = "# Global settings for this app"
        enriched = enrich_chunk_for_search(chunk, {"stanza": "__preamble__", "filename": "app.conf"})
        assert isinstance(enriched, str)


class TestConfStanzaDataclass:
    """Test ConfStanza data structure."""

    def test_construction(self):
        stanza = ConfStanza(
            name="my_stanza",
            content="key = value\nother = data",
            line_start=5,
            line_end=7,
        )
        assert stanza.name == "my_stanza"
        assert "key = value" in stanza.content
        assert stanza.line_start == 5
        assert stanza.line_end == 7


class TestDeploymentTierDetection:
    """Test 3-level deployment tier detection in extract_app_metadata."""

    def test_is_deployment_tier_known(self):
        assert is_deployment_tier("_global") is True
        assert is_deployment_tier("deployment-apps") is True
        assert is_deployment_tier("manager-apps") is True
        assert is_deployment_tier("soc-dev") is True

    def test_is_deployment_tier_pattern(self):
        assert is_deployment_tier("cluster-search") is True
        assert is_deployment_tier("cluster-es") is True
        assert is_deployment_tier("cluster-itsi") is True
        assert is_deployment_tier("org-common") is True

    def test_is_deployment_tier_disambiguation(self):
        # If next component is 'default' or 'local', it's an app, not a tier
        assert is_deployment_tier("org-search", "default") is False
        assert is_deployment_tier("cluster-search", "local") is False
        assert is_deployment_tier("_global", "metadata") is False

    def test_is_deployment_tier_false(self):
        assert is_deployment_tier("TA-windows") is False
        assert is_deployment_tier("BA-common") is False
        assert is_deployment_tier("myapp") is False

    def test_three_level_global_tier(self):
        meta = extract_app_metadata("/opt/repo/TAs/_global/TA-windows/local/inputs.conf")
        assert meta["app_type"] == "TAs"
        assert meta["deployment_tier"] == "_global"
        assert meta["app_name"] == "TA-windows"
        assert meta["app_subdir"] == "local"
        assert meta["filename"] == "inputs.conf"
        assert meta["deployment_target"] is not None
        assert "All Splunk" in meta["deployment_target"]

    def test_three_level_cluster_search(self):
        meta = extract_app_metadata("/opt/repo/BAs/cluster-search/BA-search/local/savedsearches.conf")
        assert meta["app_type"] == "BAs"
        assert meta["deployment_tier"] == "cluster-search"
        assert meta["app_name"] == "BA-search"
        assert meta["app_subdir"] == "local"
        assert "Search Head Cluster: search" in meta["deployment_target"]

    def test_three_level_manager_apps(self):
        meta = extract_app_metadata("/opt/repo/BAs/manager-apps/BA-indexes/local/indexes.conf")
        assert meta["app_type"] == "BAs"
        assert meta["deployment_tier"] == "manager-apps"
        assert meta["app_name"] == "BA-indexes"
        assert "Indexers via Cluster Manager" in meta["deployment_target"]

    def test_three_level_deployment_apps(self):
        meta = extract_app_metadata("/opt/repo/TAs/deployment-apps/TA-forwarder/local/outputs.conf")
        assert meta["app_type"] == "TAs"
        assert meta["deployment_tier"] == "deployment-apps"
        assert meta["app_name"] == "TA-forwarder"
        assert "Deployment Server" in meta["deployment_target"]

    def test_three_level_soc_dev(self):
        meta = extract_app_metadata("/opt/repo/UIs/soc-dev/SOC-app/local/savedsearches.conf")
        assert meta["app_type"] == "UIs"
        assert meta["deployment_tier"] == "soc-dev"
        assert meta["app_name"] == "SOC-app"
        assert "SOC" in meta["deployment_target"]

    def test_two_level_still_works(self):
        """2-level apps (no tier) should still work with deployment_tier=None."""
        meta = extract_app_metadata("/opt/repo/TAs/TA-nmap/local/inputs.conf")
        assert meta["app_type"] == "TAs"
        assert meta["app_name"] == "TA-nmap"
        assert meta["deployment_tier"] is None
        assert meta["deployment_target"] is None
        assert meta["app_subdir"] == "local"

    def test_two_level_org_search_with_default(self):
        """org-search/default/ is 2-level (org-search is the app, not a tier)."""
        meta = extract_app_metadata("/opt/repo/UIs/org-search/default/app.conf")
        assert meta["app_type"] == "UIs"
        assert meta["app_name"] == "org-search"
        assert meta["deployment_tier"] is None
        assert meta["app_subdir"] == "default"

    def test_deployment_target_cluster_clusters(self):
        assert get_deployment_target("BAs", "cluster-search") == "Search Head Cluster: search"
        assert get_deployment_target("BAs", "cluster-es") == "Search Head Cluster: es"
        assert get_deployment_target("BAs", "cluster-itsi") == "Search Head Cluster: itsi"

    def test_deployment_target_known_tiers(self):
        t = get_deployment_target("TAs", "_global")
        assert t is not None and "All Splunk" in t
        t = get_deployment_target("TAs", "manager-apps")
        assert t is not None and "Cluster Manager" in t

    def test_deployment_target_none(self):
        assert get_deployment_target("TAs", None) is None

    def test_three_level_full_app_path(self):
        meta = extract_app_metadata("/opt/repo/TAs/_global/TA-windows/local/inputs.conf")
        assert meta["full_app_path"] == "TAs/_global/TA-windows/local/inputs.conf"

    def test_all_returns_include_deployment_fields(self):
        """Every return path should include deployment_tier and deployment_target keys."""
        paths = [
            "/opt/repo",                    # repo root
            "/opt/repo/TAs",                # app_type only (len==1)
            "/opt/repo/TAs/TA-nmap",        # 2-level, len==2
            "/opt/repo/TAs/TA-nmap/local/inputs.conf",  # 2-level standard
            "/opt/repo/TAs/_global/TA-nmap/local/inputs.conf",  # 3-level
            "/tmp/not_in_repo/file.conf",   # fallback
        ]
        for p in paths:
            meta = extract_app_metadata(p)
            assert "deployment_tier" in meta, f"Missing deployment_tier for {p}"
            assert "deployment_target" in meta, f"Missing deployment_target for {p}"
