import os
import json
import glob
import uuid
import shutil
import importlib
import yaml
from pathlib import Path
from dotenv import load_dotenv
from inspect import signature, Parameter
from provider import Provider
from Config import Config

load_dotenv()


class Agent(Config):
    def __init__(self, agent_name=None):
        # General Configuration
        self.AGENT_NAME = agent_name if agent_name is not None else "AgentLLM"
        # Need to get the following from the agent config file:
        self.AGENT_CONFIG = self.get_agent_config()
        # AI Configuration
        if "settings" in self.AGENT_CONFIG:
            self.PROVIDER_SETTINGS = self.AGENT_CONFIG["settings"]
            if "provider" in self.PROVIDER_SETTINGS:
                self.AI_PROVIDER = self.PROVIDER_SETTINGS["provider"]
                self.PROVIDER = Provider(self.AI_PROVIDER, **self.PROVIDER_SETTINGS)
                self.instruct = self.PROVIDER.instruct
            self._load_agent_config_keys(["AI_MODEL", "AI_TEMPERATURE", "MAX_TOKENS"])
            if "AI_MODEL" in self.PROVIDER_SETTINGS:
                self.AI_MODEL = self.PROVIDER_SETTINGS["AI_MODEL"]
                if self.AI_MODEL == "":
                    self.AI_MODEL = "default"
            else:
                self.AI_MODEL = "openassistant"
            if "embedder" in self.PROVIDER_SETTINGS:
                self.EMBEDDER = self.PROVIDER_SETTINGS["embedder"]
            else:
                if self.AI_PROVIDER == "openai":
                    self.EMBEDDER = "openai"
                else:
                    self.EMBEDDER = "default"
            if not os.path.exists(f"model-prompts/{self.AI_MODEL}"):
                self.AI_MODEL = "default"
            if "MAX_TOKENS" in self.PROVIDER_SETTINGS:
                self.MAX_TOKENS = self.PROVIDER_SETTINGS["MAX_TOKENS"]
            else:
                self.MAX_TOKENS = 4000

        # Memory Settings
        self.USE_LONG_TERM_MEMORY_ONLY = os.getenv("USE_LONG_TERM_MEMORY_ONLY", False)
        # Yaml Memory
        self.memory_file = f"agents/{self.AGENT_NAME}.yaml"
        self._create_parent_directories(self.memory_file)
        self.memory = self.load_memory()
        self.agent_instances = {}
        self.commands = self.load_commands()

    def _load_agent_config_keys(self, keys):
        for key in keys:
            if key in self.AGENT_CONFIG:
                setattr(self, key, self.AGENT_CONFIG[key])

    def _create_parent_directories(self, file_path):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

    def get_provider(self):
        config_file = self.get_agent_config()
        if "provider" in config_file:
            return config_file["provider"]
        else:
            return "openai"

    def create_agent_folder(self, agent_name):
        agent_folder = f"agents/{agent_name}"
        if not os.path.exists("agents"):
            os.makedirs("agents")
        if not os.path.exists(agent_folder):
            os.makedirs(agent_folder)
        return agent_folder

    def get_command_params(self, func):
        params = {}
        sig = signature(func)
        for name, param in sig.parameters.items():
            if param.default == Parameter.empty:
                params[name] = None
            else:
                params[name] = param.default
        return params

    def load_commands(self):
        commands = []
        command_files = glob.glob("commands/*.py")
        for command_file in command_files:
            module_name = os.path.splitext(os.path.basename(command_file))[0]
            module = importlib.import_module(f"commands.{module_name}")
            command_class = getattr(module, module_name.lower())()
            if hasattr(command_class, "commands"):
                for command_name, command_function in command_class.commands.items():
                    params = self.get_command_params(command_function)
                    commands.append((command_name, command_function.__name__, params))
        return commands

    def load_command_files(self):
        command_files = glob.glob("commands/*.py")
        return command_files

    def create_agent_config_file(self, agent_name, provider_settings, commands):
        agent_dir = os.path.join("agents", agent_name)
        agent_config_file = os.path.join(agent_dir, "config.json")
        if (
            provider_settings is None
            or provider_settings == ""
            or provider_settings == {}
        ):
            provider_settings = {
                "provider": "gpt4free",
                "AI_MODEL": "gpt-4",
                "AI_TEMPERATURE": "0.7",
                "MAX_TOKENS": "4000",
                "embedder": "default",
            }
        settings = json.dumps(
            {
                "commands": commands,
                "settings": provider_settings,
            }
        )

        # Check and create agent directory if it doesn't exist
        if not os.path.exists(agent_dir):
            os.makedirs(agent_dir)

        # Write the settings to the agent config file
        with open(agent_config_file, "w") as f:
            f.write(settings)

        return agent_config_file

    def load_agent_config(self, agent_name):
        try:
            with open(
                os.path.join("agents", agent_name, "config.json")
            ) as agent_config:
                try:
                    agent_config_data = json.load(agent_config)
                    return agent_config_data
                except json.JSONDecodeError:
                    agent_config_data = {}
                    # Populate the agent_config with all commands enabled
                    agent_config_data["commands"] = {
                        command_name: "false"
                        for command_name, _, _ in self.load_commands(agent_name)
                    }
                    agent_config_data["settings"] = {
                        "provider": "gpt4free",
                        "AI_MODEL": "gpt-4",
                        "AI_TEMPERATURE": "0.7",
                        "MAX_TOKENS": "4000",
                        "embedder": "default",
                    }
                    # Save the updated agent_config to the file
                    with open(
                        os.path.join("agents", agent_name, "config.json"), "w"
                    ) as agent_config_file:
                        json.dump(agent_config_data, agent_config_file)
                    return agent_config_data
        except:
            # Add all commands to agent/{agent_name}/config.json in this format {"command_name": "false"}
            agent_config_file = os.path.join("agents", agent_name, "config.json")
            with open(agent_config_file, "w") as f:
                f.write(
                    json.dumps(
                        {
                            "commands": {
                                command_name: "false"
                                for command_name, _, _ in self.load_commands()
                            },
                            "settings": {
                                "provider": "gpt4free",
                                "AI_MODEL": "gpt-4",
                                "AI_TEMPERATURE": "0.7",
                                "MAX_TOKENS": "4000",
                                "embedder": "default",
                            },
                        }
                    )
                )
        return agent_config_data

    def write_agent_config(self, agent_config, config_data):
        with open(agent_config, "w") as f:
            json.dump(config_data, f)

    def add_agent(self, agent_name, provider_settings):
        agent_folder = self.create_agent_folder(agent_name)

        commands_list = self.load_commands()
        command_dict = {}
        for command in commands_list:
            friendly_name, command_name, command_args = command
            command_dict[friendly_name] = False
        agent_config = self.create_agent_config_file(
            agent_name, provider_settings, command_dict
        )
        # self.write_agent_config(agent_config, {"commands": command_dict})
        return {"agent_file": f"{agent_name}.yaml"}

    def rename_agent(self, agent_name, new_name):
        agent_file = f"agents/{agent_name}.yaml"
        agent_folder = f"agents/{agent_name}/"
        agent_file = os.path.abspath(agent_file)
        agent_folder = os.path.abspath(agent_folder)
        if os.path.exists(agent_file):
            os.rename(agent_file, os.path.join("agents", f"{new_name}.yaml"))
        if os.path.exists(agent_folder):
            os.rename(agent_folder, os.path.join("agents", f"{new_name}"))

    def delete_agent(self, agent_name):
        agent_file = f"agents/{agent_name}.yaml"
        agent_folder = f"agents/{agent_name}/"
        agent_file = os.path.abspath(agent_file)
        agent_folder = os.path.abspath(agent_folder)
        try:
            os.remove(agent_file)
        except FileNotFoundError:
            return {"message": f"Agent file {agent_file} not found."}, 404

        if os.path.exists(agent_folder):
            shutil.rmtree(agent_folder)

        return {"message": f"Agent {agent_name} deleted."}, 200

    def get_agent_config(self):
        while True:
            agent_file = os.path.abspath(f"agents/{self.AGENT_NAME}/config.json")
            if os.path.exists(agent_file):
                with open(agent_file, "r") as f:
                    file_content = f.read().strip()
                    if file_content:
                        agent_config = json.loads(file_content)
                        break
                    else:
                        self.add_agent(self.AGENT_NAME, {})
            else:
                self.add_agent(self.AGENT_NAME, {})
        return agent_config

    def update_agent_config(self, new_config, config_key):
        agent_name = self.AGENT_NAME
        agent_config_file = os.path.join("agents", agent_name, "config.json")
        if os.path.exists(agent_config_file):
            with open(agent_config_file, "r") as f:
                current_config = json.load(f)

            # Ensure the config_key is present in the current configuration
            if config_key not in current_config:
                current_config[config_key] = {}

            # Update the specified key with new_config while preserving other keys and values
            for key, value in new_config.items():
                current_config[config_key][key] = value

            # Save the updated configuration back to the file
            with open(agent_config_file, "w") as f:
                json.dump(current_config, f)
            return f"Agent {agent_name} configuration updated."
        else:
            return f"Agent {agent_name} configuration not found."

    def get_chat_history(self, agent_name):
        if not os.path.exists(os.path.join("agents", f"{agent_name}.yaml")):
            return ""
        with open(os.path.join("agents", f"{agent_name}.yaml"), "r") as f:
            chat_history = f.read()
        return chat_history

    def wipe_agent_memories(self, agent_name):
        agent_folder = f"agents/{agent_name}/"
        agent_folder = os.path.abspath(agent_folder)
        memories_folder = os.path.join(agent_folder, "memories")
        if os.path.exists(memories_folder):
            shutil.rmtree(memories_folder)

    def load_memory(self):
        if os.path.exists(self.memory_file):
            with open(self.memory_file, "r") as file:
                memory = yaml.safe_load(file)
        else:
            with open(self.memory_file, "w") as file:
                yaml.safe_dump({"interactions": []}, file)
            memory = {"interactions": []}
        return memory

    def save_memory(self):
        with open(self.memory_file, "w") as file:
            yaml.safe_dump(self.memory, file)

    def log_interaction(self, role: str, message: str):
        if self.memory is None:
            self.memory = {"interactions": []}
        self.memory["interactions"].append({"role": role, "message": message})
        self.save_memory()

    def get_task_output(self, agent_name, primary_objective=None):
        if primary_objective is None:
            return "No primary objective specified."
        task_output_file = os.path.join(
            "agents", agent_name, "tasks", f"{primary_objective}.txt"
        )
        if os.path.exists(task_output_file):
            with open(task_output_file, "r") as f:
                task_output = f.read()
        else:
            task_output = ""
        return task_output

    def save_task_output(self, agent_name, task_output, primary_objective=None):
        # Check if agents/{agent_name}/tasks/task_name.txt exists
        # If it does, append to it
        # If it doesn't, create it
        if "tasks" not in os.listdir(os.path.join("agents", agent_name)):
            os.makedirs(os.path.join("agents", agent_name, "tasks"))
        if primary_objective is None:
            primary_objective = str(uuid.uuid4())
        task_output_file = os.path.join(
            "agents", agent_name, "tasks", f"{primary_objective}.txt"
        )
        with open(
            task_output_file,
            "a" if os.path.exists(task_output_file) else "w",
            encoding="utf-8",
        ) as f:
            f.write(task_output)
        return task_output
