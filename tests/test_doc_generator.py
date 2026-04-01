"""Tests for the documentation generator — snippets, directory scan, zip scan, formats."""

import json
import os
import zipfile
import pytest


@pytest.fixture
def gen():
    from chat_app.doc_generator import DocGenerator
    return DocGenerator()


# ---------------------------------------------------------------------------
# Snippet Mode Tests
# ---------------------------------------------------------------------------

class TestSnippetGeneration:

    def test_basic_snippet(self, gen):
        result = gen.from_snippets(
            snippets=["HEC is configured via Settings > Data Inputs > HTTP Event Collector"],
            title="HEC Guide",
        )
        assert result.title == "HEC Guide"
        assert "HEC" in result.content
        assert result.format == "markdown"

    def test_multiple_snippets(self, gen):
        result = gen.from_snippets(
            snippets=[
                "Overview of the monitoring system",
                "Step 1: Configure the inputs",
                "Step 2: Set up the forwarding",
            ],
            title="Monitoring Setup",
        )
        assert "Overview" in result.content
        assert "Step 1" in result.content or "Configure" in result.content
        assert len(result.sections) >= 4  # title + 3 sections + footer

    def test_with_comments(self, gen):
        result = gen.from_snippets(
            snippets=["Main content here"],
            title="Test Doc",
            comments=["Reviewed by John", "Needs update for v2"],
        )
        assert "Notes" in result.content
        assert "John" in result.content

    def test_with_image_descriptions(self, gen):
        result = gen.from_snippets(
            snippets=["Dashboard overview"],
            title="Dashboard Guide",
            image_descriptions=["Screenshot of main dashboard", "Metrics panel"],
        )
        assert "Figure 1" in result.content
        assert "Figure 2" in result.content

    def test_api_reference_style(self, gen):
        result = gen.from_snippets(
            snippets=["GET /api/admin/health\nReturns system health status"],
            title="API Reference",
            style="api-reference",
        )
        assert "```" in result.content  # Code block

    def test_result_metadata(self, gen):
        result = gen.from_snippets(
            snippets=["content 1", "content 2"],
            title="Test",
        )
        assert result.metadata["snippet_count"] == 2
        d = result.to_dict()
        assert d["section_count"] >= 2
        assert d["content_length"] > 0


# ---------------------------------------------------------------------------
# SharePoint Format Tests
# ---------------------------------------------------------------------------

class TestSharePointFormat:

    def test_sharepoint_output(self, gen):
        result = gen.from_snippets(
            snippets=["This is a test document"],
            title="SharePoint Test",
            format="sharepoint",
        )
        assert result.format == "sharepoint"
        assert "<html>" in result.content
        assert "SharePoint Test" in result.content
        assert "Segoe UI" in result.content  # SharePoint font

    def test_sharepoint_has_styling(self, gen):
        result = gen.from_snippets(
            snippets=["**Bold text** and `code`"],
            title="Styled Doc",
            format="sharepoint",
        )
        assert "<style>" in result.content

    def test_sharepoint_table_rendering(self, gen):
        result = gen.from_snippets(
            snippets=["| Col1 | Col2 |\n|------|------|\n| A | B |"],
            title="Table Test",
            format="sharepoint",
        )
        assert "<table>" in result.content or "Col1" in result.content


# ---------------------------------------------------------------------------
# Directory Scan Tests
# ---------------------------------------------------------------------------

class TestDirectoryScan:

    def test_scan_directory(self, gen, tmp_path):
        # Create test files
        (tmp_path / "main.py").write_text('"""Main module."""\n\nclass App:\n    def run(self):\n        pass\n')
        (tmp_path / "config.yaml").write_text("database:\n  host: localhost\n  port: 5432\n")
        (tmp_path / "README.md").write_text("# My Project\n\nA test project.\n")

        result = gen.from_directory(str(tmp_path), title="Test Project")
        assert "Test Project" in result.content
        assert result.metadata["files_analyzed"] == 3
        assert "python" in result.metadata["languages"]

    def test_scan_empty_directory(self, gen, tmp_path):
        result = gen.from_directory(str(tmp_path), title="Empty")
        assert "No analyzable files" in result.content

    def test_scan_nonexistent_directory(self, gen):
        result = gen.from_directory("/nonexistent/path", title="Missing")
        assert "not found" in result.content.lower()

    def test_scan_skips_pycache(self, gen, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "test.pyc").write_bytes(b"\x00")
        (tmp_path / "real.py").write_text("x = 1\n")

        result = gen.from_directory(str(tmp_path))
        assert result.metadata["files_analyzed"] == 1

    def test_scan_with_subdirectories(self, gen, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("class App:\n    pass\n")
        (tmp_path / "src" / "utils.py").write_text("def helper():\n    pass\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_app.py").write_text("def test_app():\n    pass\n")

        result = gen.from_directory(str(tmp_path), title="Structured Project")
        assert result.metadata["files_analyzed"] == 3
        assert "Directory Structure" in result.content

    def test_scan_generates_statistics(self, gen, tmp_path):
        (tmp_path / "a.py").write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")
        result = gen.from_directory(str(tmp_path))
        assert "Summary Statistics" in result.content


# ---------------------------------------------------------------------------
# Zip Scan Tests
# ---------------------------------------------------------------------------

class TestZipScan:

    def test_scan_zip(self, gen, tmp_path):
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("main.py", '"""Main."""\n\nclass App:\n    pass\n')
            zf.writestr("config.yaml", "host: localhost\nport: 8000\n")
        result = gen.from_zip(str(zip_path), title="Zip Project")
        assert result.metadata["files_analyzed"] == 2
        assert "Zip Project" in result.content

    def test_scan_invalid_zip(self, gen, tmp_path):
        bad_path = tmp_path / "notazip.txt"
        bad_path.write_text("not a zip file")
        result = gen.from_zip(str(bad_path))
        assert "Invalid zip" in result.content or "Error" in result.content

    def test_scan_nonexistent_zip(self, gen):
        result = gen.from_zip("/nonexistent/file.zip")
        assert len(result.warnings) > 0

    def test_zip_skips_binary_files(self, gen, tmp_path):
        zip_path = tmp_path / "mixed.zip"
        with zipfile.ZipFile(str(zip_path), "w") as zf:
            zf.writestr("code.py", "x = 1\n")
            zf.writestr("image.png", b"\x89PNG\r\n")  # Binary PNG header
        result = gen.from_zip(str(zip_path))
        assert result.metadata["files_analyzed"] == 1  # Only .py


# ---------------------------------------------------------------------------
# File Analysis Tests
# ---------------------------------------------------------------------------

class TestFileAnalysis:

    def test_analyze_python(self):
        from chat_app.doc_generator import _analyze_file
        content = '"""Module docstring."""\n\nclass MyClass:\n    pass\n\ndef my_function():\n    pass\n\nimport os\nfrom typing import Dict\n'
        analysis = _analyze_file("test.py", content)
        assert analysis.language == "python"
        assert analysis.has_docstring is True
        assert "MyClass" in analysis.classes
        assert "my_function" in analysis.functions

    def test_analyze_yaml(self):
        from chat_app.doc_generator import _analyze_file
        content = "database:\n  host: localhost\nllm:\n  model: llama3\n"
        analysis = _analyze_file("config.yaml", content)
        assert analysis.language == "yaml"
        assert "database" in analysis.description
        assert "llm" in analysis.description

    def test_analyze_json(self):
        from chat_app.doc_generator import _analyze_file
        content = json.dumps({"name": "test", "version": "1.0", "config": {}})
        analysis = _analyze_file("package.json", content)
        assert analysis.language == "json"
        assert "3 top-level keys" in analysis.description

    def test_analyze_typescript(self):
        from chat_app.doc_generator import _analyze_file
        content = "export class MyComponent {\n}\n\nexport function helper() {\n}\n"
        analysis = _analyze_file("app.tsx", content)
        assert analysis.language == "typescript"
        assert "MyComponent" in analysis.classes

    def test_analyze_markdown(self):
        from chat_app.doc_generator import _analyze_file
        content = "# Title\n\n## Section 1\n\n## Section 2\n"
        analysis = _analyze_file("README.md", content)
        assert analysis.language == "markdown"
        assert "3 sections" in analysis.description


# ---------------------------------------------------------------------------
# Format-Specific Tests
# ---------------------------------------------------------------------------

class TestFormats:

    def test_markdown_headings(self, gen):
        result = gen.from_snippets(["Content"], title="Test")
        lines = result.content.split("\n")
        assert any(line.startswith("# ") for line in lines)
        assert any(line.startswith("## ") for line in lines)

    def test_sharepoint_html_structure(self, gen):
        result = gen.from_snippets(["Content"], title="Test", format="sharepoint")
        assert result.content.startswith("<!DOCTYPE html>")
        assert "</html>" in result.content
        assert "<h1>" in result.content


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestDocGeneratorIntegration:

    def test_generate_for_chat_app(self, gen, tmp_path):
        """Test documentation generation on a realistic file structure."""
        (tmp_path / "app.py").write_text(
            '"""Main application."""\n\nfrom fastapi import FastAPI\n\napp = FastAPI()\n\n'
            '@app.get("/health")\ndef health():\n    return {"status": "ok"}\n'
        )
        (tmp_path / "settings.py").write_text(
            '"""Configuration."""\n\nfrom pydantic import BaseModel\n\n'
            'class Settings(BaseModel):\n    host: str = "localhost"\n    port: int = 8000\n'
        )
        (tmp_path / "config.yaml").write_text(
            "app:\n  name: TestApp\n  version: 1.0\nllm:\n  model: llama3\n"
        )

        result = gen.from_directory(str(tmp_path), title="TestApp Documentation")
        assert "TestApp Documentation" in result.content
        assert result.metadata["files_analyzed"] == 3
        assert "python" in result.metadata["languages"]
        assert "yaml" in result.metadata["languages"]
        # Should document classes and functions
        assert "Settings" in result.content or "FastAPI" in result.content

    def test_sharepoint_from_directory(self, gen, tmp_path):
        (tmp_path / "main.py").write_text("class Main:\n    pass\n")
        result = gen.from_directory(str(tmp_path), format="sharepoint")
        assert "<html>" in result.content
        assert "Main" in result.content
