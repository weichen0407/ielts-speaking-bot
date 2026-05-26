"""Prompt Injector - Loads prompt templates and injects variables."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class PromptInjector:
    """Loads mode-specific prompt templates and injects context variables.

    Templates use {{variable}} syntax for variable substitution.
    Example: "You are an IELTS examiner for topic: {{topic_title}}"
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        # Templates can be in various locations depending on how workspace is set:
        # - bot/nanobot/templates/prompts/ (standard when workspace is project root)
        # - nanobot/templates/prompts/ (when workspace is the bot/ directory)
        # - templates/prompts/ (when workspace is the nanobot package directory)
        possible_paths = [
            self.workspace / "bot" / "nanobot" / "templates" / "prompts",
            self.workspace / "nanobot" / "templates" / "prompts",
            self.workspace / "templates" / "prompts",
        ]
        for path in possible_paths:
            if path.exists():
                self.templates_dir = path
                break
        else:
            # Default to the first option (will fail gracefully if not found)
            self.templates_dir = possible_paths[0]

    def inject(self, mode: str, context: dict[str, Any]) -> str:
        """Load and render a prompt template with the given context.

        Args:
            mode: The template name (e.g., "freechat", "ielts_exam")
            context: Dictionary of variables to inject into the template

        Returns:
            The rendered prompt string with all {{variable}} placeholders replaced.

        Raises:
            FileNotFoundError: If the template file doesn't exist
        """
        template_path = self.templates_dir / f"{mode}.md"
        if not template_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_path}")

        template = template_path.read_text(encoding="utf-8")
        return self._render(template, context)

    def _render(self, template: str, context: dict[str, Any]) -> str:
        """Replace {{variable}} placeholders with values from context.

        Unknown variables are left as-is (e.g., {{unknown}} stays unchanged).
        """
        def replacer(match: re.Match[str]) -> str:
            var_name = match.group(1).strip()
            if var_name in context:
                value = context[var_name]
                if isinstance(value, list):
                    return "\n".join(str(item) for item in value)
                return str(value)
            return match.group(0)  # Keep unknown variables as-is

        return re.sub(r"\{\{(.+?)\}\}", replacer, template)
