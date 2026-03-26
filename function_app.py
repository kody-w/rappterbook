import azure.functions as func
import logging
import json
import os
import importlib
import inspect
import sys
import re
from agents.basic_agent import BasicAgent
import uuid
from openai import AzureOpenAI, OpenAI
from datetime import datetime
import time
from utils.azure_file_storage import AzureFileStorageManager

DEFAULT_USER_GUID = "c0p110t0-aaaa-bbbb-cccc-123456789abc"

def safe_json_loads(json_str):
    if not json_str: return {}
    try: return json.loads(json_str)
    except: return {}

def load_agents_from_folder(user_guid=None):
    declared_agents = {}
    
    # Load built-in agents
    agents_dir = os.path.join(os.path.dirname(__file__), "agents")
    for file in os.listdir(agents_dir):
        if file.endswith(".py") and file not in ["__init__.py", "basic_agent.py"]:
            try:
                module_name = file[:-3]
                module = importlib.import_module(f'agents.{module_name}')
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, BasicAgent) and obj is not BasicAgent:
                        instance = obj()
                        declared_agents[instance.name] = instance
            except Exception as e:
                logging.error(f"Error loading {file}: {e}")

    # Load local storage agents (simplified)
    storage = AzureFileStorageManager()
    agent_files = storage.list_files('agents')
    # Logic to load dynamic agents would go here
    
    return declared_agents

class Assistant:
    def __init__(self, declared_agents):
        self.config = {'assistant_name': 'LocalInsightBot'}
        
        if os.environ.get('USE_OLLAMA', 'false').lower() == 'true':
            logging.info("Initializing OpenAI client for Ollama.")
            self.client = OpenAI(
                base_url=os.environ.get('OLLAMA_API_BASE_URL', 'http://ollama:11434/v1'),
                api_key='ollama'
            )
            self.ollama_model_name = os.environ.get('OLLAMA_MODEL_NAME', 'llama2')
        else:
            self.client = AzureOpenAI(
                api_key=os.environ['AZURE_OPENAI_API_KEY'],
                api_version=os.environ['AZURE_OPENAI_API_VERSION'],
                azure_endpoint=os.environ['AZURE_OPENAI_ENDPOINT']
            )

        self.known_agents = declared_agents
        self.user_guid = DEFAULT_USER_GUID
        self.storage_manager = AzureFileStorageManager()
        self._initialize_context_memory(DEFAULT_USER_GUID)

    def _initialize_context_memory(self, user_guid):
        self.shared_memory = "Shared memory loaded."
        self.user_memory = "User memory loaded."
        if 'ContextMemory' in self.known_agents:
            self.storage_manager.set_memory_context(user_guid)
            # Simple init
            pass

    def get_agent_metadata(self):
        return [agent.metadata for agent in self.known_agents.values() if hasattr(agent, 'metadata')]

    def get_openai_api_call(self, messages):
        if os.environ.get('USE_OLLAMA', 'false').lower() == 'true':
            return self.client.chat.completions.create(
                model=self.ollama_model_name,
                messages=messages,
                functions=self.get_agent_metadata(),
                function_call="auto"
            )
        else:
            return self.client.chat.completions.create(
                model=os.environ.get('AZURE_OPENAI_DEPLOYMENT_NAME', 'gpt-deployment'),
                messages=messages,
                functions=self.get_agent_metadata(),
                function_call="auto"
            )

    def get_response(self, prompt, conversation_history):
        messages = [{"role": "system", "content": "You are a helpful AI assistant."}]
        for msg in conversation_history:
            if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                messages.append(msg)
        messages.append({"role": "user", "content": prompt})

        try:
            response = self.get_openai_api_call(messages)
            msg = response.choices[0].message
            content = msg.content or ""
            
            if msg.function_call:
                agent_name = msg.function_call.name
                agent = self.known_agents.get(agent_name)
                if agent:
                    args = safe_json_loads(msg.function_call.arguments)
                    if agent_name in ['ManageMemory', 'ContextMemory']:
                        args['user_guid'] = self.user_guid
                    
                    result = str(agent.perform(**args))
                    messages.append({"role": "function", "name": agent_name, "content": result})
                    
                    final_response = self.get_openai_api_call(messages)
                    content = final_response.choices[0].message.content or ""
                    return content, "Function executed.", f"Executed {agent_name}: {result}"
            
            # Simple voice extraction
            parts = content.split('.')
            voice = parts[0] if parts else "Done."
            return content, voice, ""
            
        except Exception as e:
            logging.error(f"Error: {e}")
            return f"Error: {str(e)}", "I encountered an error.", ""

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Serve the chat UI at root
@app.route(route="", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def serve_index(req: func.HttpRequest) -> func.HttpResponse:
    """Serve the chat UI as the default page"""
    try:
        index_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(index_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return func.HttpResponse(
            html_content,
            mimetype="text/html",
            status_code=200
        )
    except Exception as e:
        logging.error(f"Error serving index.html: {e}")
        return func.HttpResponse(f"Error loading UI: {str(e)}", status_code=500)

@app.route(route="businessinsightbot_function", auth_level=func.AuthLevel.ANONYMOUS)
def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing request.')
    
    # CORS
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*"
    }
    
    if req.method == 'OPTIONS':
        return func.HttpResponse(status_code=200, headers=headers)

    try:
        req_body = req.get_json()
        user_input = str(req_body.get('user_input', ''))
        history = req_body.get('conversation_history', [])
        user_guid = req_body.get('user_guid')
        
        agents = load_agents_from_folder(user_guid)
        assistant = Assistant(agents)
        if user_guid: assistant.user_guid = user_guid
        
        response_text, voice, logs = assistant.get_response(user_input, history)
        
        return func.HttpResponse(
            json.dumps({
                "assistant_response": response_text,
                "voice_response": voice,
                "agent_logs": logs,
                "user_guid": assistant.user_guid
            }),
            mimetype="application/json",
            headers=headers
        )
    except Exception as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, headers=headers)
