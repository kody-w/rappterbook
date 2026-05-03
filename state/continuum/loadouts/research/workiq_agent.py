"""
WorkIQ Agent - Microsoft 365 Data Access via work-iq-mcp

This agent provides natural language access to Microsoft 365 data including:
- Emails and conversations
- Calendar meetings and events
- Documents (SharePoint, OneDrive)
- Teams messages and channels
- People and organizational contacts

Prerequisites:
    1. Install workiq CLI: npm install -g @microsoft/workiq
    2. Accept EULA: workiq accept-eula
    3. Authenticate: Run workiq ask once to complete Entra ID login

Usage:
    The agent accepts natural language queries about M365 data.
    Examples:
    - "What emails did I receive from my manager this week?"
    - "What meetings do I have tomorrow?"
    - "Find documents about project planning"
    - "What did Sarah say in Teams about the deadline?"
"""

import logging
import os
import re
import subprocess
import shutil
import json
from agents.basic_agent import BasicAgent

__manifest__ = {
    "schema": "rapp-agent/1.0",
    "name": "@kody/workiq",
    "version": "1.0.0",
    "display_name": "WorkIQ",
    "description": "Natural-language access to Microsoft 365 data — emails, calendar, SharePoint/OneDrive, Teams messages, people. Wraps the workiq CLI (Entra ID auth required).",
    "author": "Kody",
    "tags": ["m365", "microsoft", "email", "calendar", "teams", "sharepoint", "workiq"],
    "category": "integrations",
    "quality_tier": "community",
    "requires_env": [],
    "dependencies": ["@rapp/basic_agent"],
    "external_prereqs": [
        "npm install -g @microsoft/workiq",
        "workiq accept-eula",
        "Entra ID login (run `workiq ask` once)",
    ],
    "example_call": "What emails did I receive from my manager this week?",
}



_ANSI_RE = re.compile(r'\x1b(?:\[[0-9;?]*[a-zA-Z]|\][^\x07\x1b]*(?:\x07|\x1b\\))')


def _strip_ansi(text):
    return _ANSI_RE.sub('', text or '')


class WorkIQAgent(BasicAgent):
    def __init__(self):
        self.name = 'WorkIQ'
        self.metadata = {
            "name": self.name,
            "description": (
                "Access Microsoft 365 data using natural language queries. "
                "Can search emails, calendar meetings, documents, Teams messages, and people information. "
                "Use this agent when the user wants to find or retrieve information from their Microsoft 365 tenant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "The natural language query to search Microsoft 365 data. "
                            "Examples: 'What emails did I receive from John this week?', "
                            "'What meetings do I have tomorrow?', "
                            "'Find documents about the Q4 budget', "
                            "'What did the team say about the deadline in Teams?'"
                        )
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": (
                            "Optional Entra tenant ID for multi-tenant scenarios. "
                            "Leave empty to use the default 'common' tenant."
                        )
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["all", "email", "calendar", "documents", "teams", "people"],
                        "description": (
                            "Optional filter to search only specific data types. "
                            "Default is 'all' which searches across all Microsoft 365 data."
                        )
                    }
                },
                "required": ["query"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        """Execute a WorkIQ query against Microsoft 365 data."""
        query = kwargs.get('query', '')
        tenant_id = kwargs.get('tenant_id', '')
        data_type = kwargs.get('data_type', 'all')

        if not query:
            return "Error: No query provided. Please specify what information you want to find in Microsoft 365."

        if not self._check_workiq_installed():
            return self._get_installation_instructions()

        enhanced_query = self._build_enhanced_query(query, data_type)
        return self._execute_workiq_query(enhanced_query, tenant_id)

    def _check_workiq_installed(self):
        """Check if the workiq CLI is installed and available."""
        import sys as _sys
        if shutil.which('workiq'):
            return True
        if _sys.platform == 'win32':
            appdata_cmd = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm", "workiq.CMD")
            if os.path.isfile(appdata_cmd):
                return True
        if shutil.which('npx'):
            return True
        return False

    def _get_installation_instructions(self):
        """Return instructions for installing workiq."""
        return (
            "**WorkIQ CLI not found.** To use this agent, please install the WorkIQ CLI:\n\n"
            "**Option 1 - Global installation:**\n"
            "```bash\n"
            "npm install -g @microsoft/workiq\n"
            "workiq accept-eula\n"
            "```\n\n"
            "**Option 2 - Use without installation (via npx):**\n"
            "```bash\n"
            "npx -y @microsoft/workiq accept-eula\n"
            "```\n\n"
            "After installation, run `workiq ask 'test query'` once to complete Entra ID authentication."
        )

    def _build_enhanced_query(self, query, data_type):
        """Build an enhanced query with data type context."""
        if data_type == 'all':
            return query

        context_hints = {
            'email': f"In my emails: {query}",
            'calendar': f"In my calendar/meetings: {query}",
            'documents': f"In my documents (SharePoint/OneDrive): {query}",
            'teams': f"In Teams messages: {query}",
            'people': f"About people/contacts: {query}"
        }

        return context_hints.get(data_type, query)

    def _execute_workiq_query(self, query, tenant_id=''):
        """Execute a query using the workiq CLI."""
        import sys as _sys
        try:
            workiq_path = shutil.which('workiq')
            if not workiq_path and _sys.platform == 'win32':
                appdata_cmd = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm", "workiq.CMD")
                if os.path.isfile(appdata_cmd):
                    workiq_path = appdata_cmd

            if workiq_path:
                cmd = [workiq_path, 'ask', '-q', query]
            else:
                cmd = ['npx', '-y', '@microsoft/workiq', 'ask', '-q', query]

            if tenant_id:
                cmd.extend(['--tenant-id', tenant_id])

            logging.info(f"WorkIQ Agent executing query: {query[:100]}...")

            use_shell = _sys.platform == 'win32'

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                shell=use_shell
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"

                if 'EULA' in error_msg or 'accept-eula' in error_msg.lower():
                    return (
                        "**EULA not accepted.** Please run the following command first:\n"
                        "```bash\n"
                        "workiq accept-eula\n"
                        "```"
                    )
                elif 'login' in error_msg.lower() or 'auth' in error_msg.lower():
                    return (
                        "**Authentication required.** Please authenticate with Microsoft Entra ID:\n"
                        "```bash\n"
                        "workiq ask 'test'\n"
                        "```\n"
                        "This will open a browser window for authentication."
                    )
                else:
                    logging.error(f"WorkIQ error: {error_msg}")
                    return f"Error querying Microsoft 365: {error_msg}"

            output = _strip_ansi(result.stdout).strip()

            if not output:
                return "No results found for your query. Try rephrasing or broadening your search."

            return self._format_output(output)

        except subprocess.TimeoutExpired:
            logging.error("WorkIQ query timed out after 120 seconds")
            return (
                "The query timed out. This might happen if:\n"
                "- The query is too broad (try being more specific)\n"
                "- Network connectivity issues\n"
                "- Microsoft 365 services are slow to respond\n\n"
                "Please try a more specific query."
            )
        except FileNotFoundError:
            return self._get_installation_instructions()
        except Exception as e:
            logging.error(f"WorkIQ Agent error: {str(e)}")
            return f"Error executing WorkIQ query: {str(e)}"

    def _format_output(self, output):
        """Format the workiq output for better readability."""
        if output.startswith('{') or output.startswith('['):
            try:
                data = json.loads(output)
                return f"**Microsoft 365 Query Results:**\n\n```json\n{json.dumps(data, indent=2)}\n```"
            except json.JSONDecodeError:
                pass

        return f"**Microsoft 365 Query Results:**\n\n{output}"
