from default_evaluator import VanillaJavaEvaluator, OpenHandsSettings
import os
import json
import re
import tiktoken

class AgenticJavaEvaluator(VanillaJavaEvaluator):
    def __init__(self, trajectory_path: str = None, root_path: str = "", repo_path: str = "repoclassbench/temp", dataset_path: str = "repoclassbench/datasets", outputs_path: str = "outputs", settings: OpenHandsSettings = None, context_path: str = "context") -> None:
        super().__init__(root_path, repo_path, dataset_path, outputs_path, settings)
        self.context_path = context_path
        self.settings = settings
        if not trajectory_path:
            self.trajectory_path = os.path.join(self.outputs_path, "vanilla_trajectories")
        else:
            self.trajectory_path = trajectory_path

    def get_context(self, i: int, task, repo_path: str = "repoclassbench/temp", prompt: str = "") -> str:
        trajectory = None
        task_file_name = task.file.split("/")[-1]
        trajectory_path = os.path.join(self.root_path, self.trajectory_path, f"task-{i}", "events")
        trajectory = []
        try:
            for filename in sorted(os.listdir(trajectory_path)):
                filepath = os.path.join(trajectory_path, filename)
                if os.path.isfile(filepath):
                    with open(filepath, 'r') as f:
                        try:
                            event = json.load(f)
                            trajectory.append(event)
                        except json.JSONDecodeError:
                            print(f"Error decoding JSON from file: {filepath}")
            trajectory.sort(key=lambda x: x.get("id", 0))
            context = ""
            sed_match = r"""sed\s+(?:-[a-zA-Z]+\s+)*(?:'[^']*'|"[^"]*")\s+([^\s;&|]+)"""
            for event in trajectory:
                content = event.get("content", "")
                if not content:
                    continue
                if event.get("observation", "") == "read" and "I read the file " in event.get("message", "") and task_file_name not in event.get("message", "") and not content.startswith("ERROR"):
                    context += f"{event.get('message', '')}\n{content}\n"
                elif event.get("observation", "") == "run":
                    extras = event.get("extras", {})
                    command = extras.get("command", "")
                    exit_code = extras.get("metadata", {}).get("exit_code", 1)
                    if (re.search(sed_match, command) or "grep" in command or "cat " in command) and exit_code == 0:
                        context += "Here's the result of the command '" + command + "':\n"
                        context += event.get("content", "") + "\n"
            
            # Tokenize and truncate context to last 5120 tokens
            # encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
            # tokens = encoding.encode(context)
            # if len(tokens) > 5120:
            #     tokens = tokens[-5120:]
            #     context = encoding.decode(tokens)

            if len(context) > 120000:
                context = context[:120000]
            prefix = "Additionally, here are some potentially relevant code snippets from the repository:\n\n"
            return prefix + context + prompt
        finally:
            # Clean up trajectory data to prevent memory leaks
            trajectory = None
            context = None
