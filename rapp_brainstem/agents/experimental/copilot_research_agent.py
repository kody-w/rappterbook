"""
Runs online research by shelling out to the GitHub Copilot CLI in non-interactive
mode with web_search and web_fetch tools enabled. Returns the CLI's response text.
"""

import subprocess
import shutil
from agents.basic_agent import BasicAgent


# Locate the copilot binary once at import time
_COPILOT_BIN = shutil.which("copilot") or shutil.which("github-copilot-cli")


class CopilotResearchAgent(BasicAgent):
    def __init__(self):
        self.name = "CopilotResearch"
        self.metadata = {
            "name": self.name,
            "description": (
                "Performs live online research using the GitHub Copilot CLI. "
                "Pass a research question or topic and receive a sourced answer "
                "synthesised from the web. Use this whenever the user asks about "
                "current events, recent data, documentation, or anything that "
                "requires up-to-date information beyond your training data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The research question or topic to look up online."
                    }
                },
                "required": ["query"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        query = kwargs.get("query", "")
        if not query:
            return "No query provided."

        if not _COPILOT_BIN:
            return (
                "Copilot CLI binary not found on PATH. "
                "Install it with: npm install -g @githubnext/github-copilot-cli  "
                "or via Homebrew."
            )

        cmd = [
            _COPILOT_BIN,
            "-p", query,
            "--allow-tool=web_search",
            "--allow-tool=web_fetch",
            "--output-format", "text",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout.strip()
            if result.returncode != 0 and not output:
                return f"Copilot CLI error (exit {result.returncode}): {result.stderr.strip()}"
            return output or "No results returned."
        except subprocess.TimeoutExpired:
            return "Research timed out after 120 seconds."
        except Exception as e:
            return f"Error running Copilot CLI: {e}"
