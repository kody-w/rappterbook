class BasicAgent:
    """Base class for all RAPP Brainstem agents. Extend this in your private agent files."""

    def __init__(self, name=None, metadata=None):
        if name is not None:
            self.name = name
        elif not hasattr(self, "name"):
            self.name = "BasicAgent"
        if metadata is not None:
            self.metadata = metadata
        elif not hasattr(self, "metadata"):
            self.metadata = {
                "name": self.name,
                "description": "Base agent -- override this.",
                "parameters": {"type": "object", "properties": {}, "required": []}
            }

    def perform(self, **kwargs):
        return "Not implemented."

    def system_context(self):
        """Optional: return a string to inject into the system prompt each turn.
        Override in agents that provide persistent context (e.g. memory)."""
        return None

    def to_tool(self):
        """Returns OpenAI function-calling tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.metadata.get("description", ""),
                "parameters": self.metadata.get("parameters", {"type": "object", "properties": {}})
            }
        }
