"""
Tests for TemplateEngine — Jinja2 template rendering from filesystem.
"""
import pytest
import tempfile
import os
from pathlib import Path

from src.infrastructure.outreach.template_engine import TemplateEngine


def _make_template(dir_path: str, stem: str, content: str):
    path = Path(dir_path) / f"{stem}.md"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def template_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def engine(template_dir):
    return TemplateEngine(template_dir=template_dir)


def test_render_basic_template(engine, template_dir):
    _make_template(template_dir, "test", """---
name: Test Template
channel: email
subject: "Hello {{first_name}}"
---
Hi {{first_name}}, welcome to {{company_name}}!
""")
    result = engine.render("test", {"first_name": "Alice", "company_name": "Acme"})
    assert result["subject"] == "Hello Alice"
    assert "Alice" in result["plain_body"]
    assert "Acme" in result["plain_body"]


def test_render_returns_html_body(engine, template_dir):
    _make_template(template_dir, "html_test", """---
name: HTML Test
channel: email
subject: "Hi"
---
Line one.

Line two.
""")
    result = engine.render("html_test", {})
    assert "<br>" in result["html_body"]


def test_render_with_dotmd_extension(engine, template_dir):
    _make_template(template_dir, "dotmd", """---
name: DotMD Test
channel: email
subject: "Test"
---
Body text.
""")
    result = engine.render("dotmd.md", {})
    assert result["subject"] == "Test"


def test_render_raises_file_not_found(engine):
    with pytest.raises(FileNotFoundError):
        engine.render("nonexistent_template", {})


def test_list_templates_empty_dir(engine):
    templates = engine.list_templates()
    assert templates == []


def test_list_templates_returns_metadata(engine, template_dir):
    _make_template(template_dir, "tmpl1", """---
name: Template 1
channel: email
subject: "Subject 1"
---
Body.
""")
    _make_template(template_dir, "tmpl2", """---
name: Template 2
channel: linkedin_connect
subject: "Subject 2"
---
Body.
""")
    templates = engine.list_templates()
    assert len(templates) == 2
    ids = [t["id"] for t in templates]
    assert "tmpl1" in ids
    assert "tmpl2" in ids


def test_render_missing_variable_silently_replaced(engine, template_dir):
    _make_template(template_dir, "missing", """---
name: Missing Vars
channel: email
subject: "Hi {{first_name}}"
---
Hello {{first_name}}, your company is {{company_name}}.
""")
    # Missing company_name should not raise
    result = engine.render("missing", {"first_name": "Bob"})
    assert "Bob" in result["plain_body"]


def test_render_channel_from_metadata(engine, template_dir):
    _make_template(template_dir, "li_test", """---
name: LinkedIn
channel: linkedin_connect
subject: null
---
Connection note.
""")
    result = engine.render("li_test", {})
    assert result["channel"] == "linkedin_connect"
