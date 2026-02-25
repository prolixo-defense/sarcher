"""
Jinja2-based email/message template engine.

Templates are stored as .md files in ./data/templates/ with frontmatter metadata:

---
name: Initial Outreach
channel: email
subject: "Quick question about {{company_name}}"
---
Hi {{first_name}},
...
"""
import logging
from pathlib import Path

import jinja2
import frontmatter

logger = logging.getLogger(__name__)


class TemplateEngine:
    """
    Loads and renders Jinja2 templates from the filesystem.
    """

    def __init__(self, template_dir: str = "./data/templates"):
        self._template_dir = Path(template_dir)
        self._jinja_env = jinja2.Environment(
            loader=jinja2.BaseLoader(),
            autoescape=False,
            undefined=jinja2.Undefined,  # silently ignore missing vars
        )

    def render(self, template_id: str, context: dict) -> dict:
        """
        Render a template with context variables.

        Returns {subject: str, html_body: str, plain_body: str, channel: str}.
        """
        template_path = self._resolve_path(template_id)
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_id}")

        post = frontmatter.load(str(template_path))
        metadata = post.metadata
        body_template = post.content

        # Render subject from frontmatter
        subject_raw = metadata.get("subject", "")
        subject = self._render_string(subject_raw, context)

        # Render body
        plain_body = self._render_string(body_template, context)

        # Simple HTML: preserve newlines
        html_body = plain_body.replace("\n", "<br>\n")

        return {
            "subject": subject,
            "html_body": html_body,
            "plain_body": plain_body,
            "channel": metadata.get("channel", "email"),
            "name": metadata.get("name", template_id),
        }

    def list_templates(self) -> list[dict]:
        """List all available templates with metadata."""
        if not self._template_dir.exists():
            return []
        templates = []
        for path in sorted(self._template_dir.glob("*.md")):
            try:
                post = frontmatter.load(str(path))
                templates.append({
                    "id": path.stem,
                    "name": post.metadata.get("name", path.stem),
                    "channel": post.metadata.get("channel", "email"),
                    "subject": post.metadata.get("subject", ""),
                })
            except Exception as exc:
                logger.warning("Failed to load template %s: %s", path, exc)
        return templates

    def _render_string(self, template_str: str, context: dict) -> str:
        try:
            tmpl = self._jinja_env.from_string(template_str)
            return tmpl.render(**context)
        except Exception as exc:
            logger.warning("Template render error: %s", exc)
            return template_str

    def _resolve_path(self, template_id: str) -> Path:
        """Resolve template_id to a file path."""
        # Strip .md suffix if provided
        stem = template_id.removesuffix(".md")
        return self._template_dir / f"{stem}.md"
