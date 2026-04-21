import uuid
from datetime import datetime
from agents.basic_agent import BasicAgent
from utils.azure_file_storage import AzureFileStorageManager


class ManageMemoryAgent(BasicAgent):
    def __init__(self):
        self.name = 'ManageMemory'
        self.metadata = {
            "name": self.name,
            "description": "Saves information to persistent memory for future conversations. You MUST call this tool whenever the user asks you to remember something, shares personal facts (name, preferences, birthdays, etc.), or tells you something they expect you to recall later. Do not just acknowledge — call this tool or the information will be lost.",
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_type": {
                        "type": "string",
                        "description": "Type of memory to store.",
                        "enum": ["fact", "preference", "insight", "task"]
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to store in memory."
                    },
                    "importance": {
                        "type": "integer",
                        "description": "Importance rating from 1-5.",
                        "minimum": 1,
                        "maximum": 5
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of tags to categorize this memory."
                    },
                    "user_guid": {
                        "type": "string",
                        "description": "Optional unique identifier of the user to store memory in a user-specific location."
                    }
                },
                "required": ["memory_type", "content"]
            }
        }
        self.storage_manager = AzureFileStorageManager()
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        memory_type = kwargs.get('memory_type', 'fact')
        content = kwargs.get('content', '')
        importance = kwargs.get('importance', 3)
        tags = kwargs.get('tags', [])
        user_guid = kwargs.get('user_guid')

        if not content:
            return "Error: No content provided for memory storage."

        self.storage_manager.set_memory_context(user_guid)
        return self.store_memory(memory_type, content, importance, tags)

    def store_memory(self, memory_type, content, importance, tags):
        memory_data = self.storage_manager.read_json()
        if not memory_data:
            memory_data = {}

        memory_id = str(uuid.uuid4())
        memory_data[memory_id] = {
            "conversation_id": self.storage_manager.current_guid or "current",
            "session_id": "current",
            "message": content,
            "mood": "neutral",
            "theme": memory_type,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M:%S")
        }

        self.storage_manager.write_json(memory_data)

        memory_location = f"for user {self.storage_manager.current_guid}" if self.storage_manager.current_guid else "in shared memory"
        return f'Successfully stored {memory_type} memory {memory_location}: "{content}"'
