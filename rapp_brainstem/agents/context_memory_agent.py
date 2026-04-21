import logging
from agents.basic_agent import BasicAgent
from utils.azure_file_storage import AzureFileStorageManager


class ContextMemoryAgent(BasicAgent):
    def __init__(self):
        self.name = 'ContextMemory'
        self.metadata = {
            "name": self.name,
            "description": "Recalls and provides context based on stored memories of past interactions with the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_guid": {
                        "type": "string",
                        "description": "Optional unique identifier of the user to recall memories from a user-specific location."
                    },
                    "max_messages": {
                        "type": "integer",
                        "description": "Optional maximum number of messages to include in the context. Default is 10."
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of keywords to filter memories by."
                    },
                    "full_recall": {
                        "type": "boolean",
                        "description": "Optional flag to return all memories without filtering. Default is false."
                    }
                },
                "required": []
            }
        }
        self.storage_manager = AzureFileStorageManager()
        super().__init__(name=self.name, metadata=self.metadata)

    def system_context(self):
        """Inject stored memories into the system prompt each turn."""
        try:
            memories = self._recall_context(max_messages=50, keywords=[], full_recall=True)
            if "don't have any memories" in memories or "No memories" in memories:
                return None
            return f"""<memory>
{memories}
</memory>

<memory_instructions>
- The above are stored memories from previous conversations
- Use them to provide continuity and personalized responses
- When the user asks what you remember, reference these memories
</memory_instructions>"""
        except Exception:
            return None

    def perform(self, **kwargs):
        user_guid = kwargs.get('user_guid')
        max_messages = kwargs.get('max_messages', 10)
        keywords = kwargs.get('keywords', [])
        full_recall = kwargs.get('full_recall', False)

        if 'max_messages' not in kwargs and 'keywords' not in kwargs:
            full_recall = True

        self.storage_manager.set_memory_context(user_guid)
        return self._recall_context(max_messages, keywords, full_recall)

    def _recall_context(self, max_messages, keywords, full_recall=False):
        memory_data = self.storage_manager.read_json()

        if not memory_data:
            if self.storage_manager.current_guid:
                return f"I don't have any memories stored yet for user ID {self.storage_manager.current_guid}."
            else:
                return "I don't have any memories stored in the shared memory yet."

        legacy_memories = []
        for key, value in memory_data.items():
            if isinstance(value, dict) and 'message' in value:
                legacy_memories.append(value)

        if not legacy_memories:
            return "No memories found for this session."

        return self._format_legacy_memories(legacy_memories, max_messages, keywords, full_recall)

    def _format_legacy_memories(self, memories, max_messages, keywords, full_recall=False):
        if not memories:
            return "No memories found in the format I understand."

        if full_recall:
            sorted_memories = sorted(
                memories,
                key=lambda x: (x.get('date', ''), x.get('time', '')),
                reverse=True
            )
            memory_lines = []
            for memory in sorted_memories:
                message = memory.get('message', '')
                theme = memory.get('theme', 'Unknown')
                date = memory.get('date', '')
                time_str = memory.get('time', '')
                if date and time_str:
                    memory_lines.append(f"- {message} (Theme: {theme}, Recorded: {date} {time_str})")
                else:
                    memory_lines.append(f"- {message} (Theme: {theme})")

            if not memory_lines:
                return "No memories found."

            memory_source = f"for user ID {self.storage_manager.current_guid}" if self.storage_manager.current_guid else "from shared memory"
            return f"All memories {memory_source}:\n" + "\n".join(memory_lines)

        if keywords and len(keywords) > 0:
            filtered_memories = []
            for memory in memories:
                content = str(memory.get('message', '')).lower()
                theme = str(memory.get('theme', '')).lower()
                if any(kw.lower() in content for kw in keywords) or \
                        any(kw.lower() in theme for kw in keywords):
                    filtered_memories.append(memory)

            if filtered_memories:
                memories = filtered_memories
            else:
                memories = sorted(
                    memories,
                    key=lambda x: (x.get('date', ''), x.get('time', '')),
                    reverse=True
                )[:max_messages]
        else:
            memories = sorted(
                memories,
                key=lambda x: (x.get('date', ''), x.get('time', '')),
                reverse=True
            )[:max_messages]

        memory_lines = []
        for memory in memories:
            message = memory.get('message', '')
            theme = memory.get('theme', 'Unknown')
            date = memory.get('date', '')
            time_str = memory.get('time', '')
            if date and time_str:
                memory_lines.append(f"- {message} (Theme: {theme}, Recorded: {date} {time_str})")
            else:
                memory_lines.append(f"- {message} (Theme: {theme})")

        if not memory_lines:
            return "No matching memories found."

        memory_source = f"for user ID {self.storage_manager.current_guid}" if self.storage_manager.current_guid else "from shared memory"
        return f"Here's what I remember {memory_source}:\n" + "\n".join(memory_lines)
