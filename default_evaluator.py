from typing import Dict
from pyparsing import Any
from repoclassbench.dataset import Dataset
import os
import shutil
import logging
import re
import subprocess
import time
import gc
import fcntl
import select
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import json
from dataclasses import dataclass
from enum import Enum
from tqdm import tqdm

@dataclass
class OpenHandsSettings:
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    max_iterations: int = 100
    num_workers: int = 6
    openhands_path: str = ""
    prompt_cache: bool = True
    task_list: list = None

class VanillaJavaEvaluator:

    def __init__(self, root_path: str = "", repo_path: str = "repoclassbench/temp", dataset_path: str = "repoclassbench/datasets", outputs_path: str = "outputs", settings: OpenHandsSettings = None) -> None:
        self.repo_path = repo_path
        self.dataset_path = dataset_path
        self.outputs_path = outputs_path
        self.root_path = root_path
        self.dataset = Dataset(language="java", specification="sketchy", delete_relatives=False)
        self.logger = logging.getLogger(__name__)
        if not settings:
            raise ValueError("settings must be provided.")
        self.settings = settings

        logging.basicConfig(level=logging.INFO)

    def evaluate(self, output_name: str) -> Dict[str, Any]:
        # Existing evaluation logic...
        def find_outermost_pom(start_path=None):
            # Start from the given path or the current working directory
            current_path = start_path or os.getcwd()
            outermost_pom = None
            while current_path != os.path.dirname(current_path):  # Stop at the root directory
                pom_path = os.path.join(current_path, "pom.xml")
                if os.path.isfile(pom_path):
                    outermost_pom = pom_path  # Update the outermost pom.xml found
                current_path = os.path.dirname(current_path)  # Move one level up
            return outermost_pom
        
        def get_trajectory(i, max_retries=3):
            retry_count = 0
            while retry_count < max_retries:
                try:
                    log_file = f"{self.outputs_path}/runlogs/java/task-{i}/run.log"
                    log_file = os.path.join(self.root_path, self.outputs_path, f"runlogs/java/task-{i}/run.log")
                    os.makedirs(os.path.dirname(log_file), exist_ok=True)
                    file_handler = logging.FileHandler(log_file, mode='w')  # Write mode to overwrite logs on each retry
                    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
                    file_handler.setFormatter(formatter)
                    logger = logging.getLogger(f"task_{i}")
                    logger.setLevel(logging.INFO)
                    # Remove any old handlers to avoid duplicate logs
                    if logger.hasHandlers():
                        logger.handlers.clear()
                    logger.addHandler(file_handler)
                    logger.propagate = False  # Prevent propagation to root logger
                    
                    if retry_count > 0:
                        logger.warning(f"Retry attempt {retry_count} for task {i}")
                    
                    task = self.dataset.get_instance_and_setup_env(i)
                    logger.info(task.repo_dir)
                    openhands_init_script_path = os.path.join(self.root_path, "openhands_init.sh")
                    openhands_env = os.environ.copy()
                    print(os.path.join(f"{self.root_path}/repoclassbench/temp/java/original_repo/", task.repo_metadata["repo_name"], task.file))
                    outer_pom = find_outermost_pom(os.path.join(f"{self.root_path}/repoclassbench/temp/java/original_repo/", task.repo_metadata["repo_name"], task.file))
                    outer_pom = "/workspace" + outer_pom.split(f"/original_repo", 2)[1]
                    outer_pom = outer_pom.replace("pom.xml", "")
                    prompt = f"""Implement the following class located at {os.path.join("workspace", task.repo_metadata["repo_name"], task.file)}: 
                    {task.description}\n Make sure your implementation passes the tests at {task.test_file}. 
                    To run the test, run the command 'cd {outer_pom} && export JAVA_HOME=/external/java/jdk-17.0.6/ && /external/java/apache-maven-3.8.7/bin/mvn test -Dtest="{task.test_class_name}" -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false'.
                    You will not have permission to read the test file contents, so only execute the tests and read the output.\n"""
                    openhands_env["TASK"] = prompt
                    openhands_env["TASK"] += f"\n\n{self.get_context(i, task, self.repo_path, prompt)}"
                    openhands_env["TASK_NUM"] = str(i)
                    working_repo_path = os.path.join(self.root_path, self.repo_path, f"java/working_repo{i}")
                    externals_path = os.path.join(self.root_path, "repoclassbench/external/java")
                    openhands_env["SANDBOX_VOLUMES"] = f"{working_repo_path}:/workspace:rw,{externals_path}:/external/java:rw"
                    openhands_env["MAX_ITERATIONS"] = str(self.settings.max_iterations)
                    openhands_env["LLM_TEMPERATURE"] = "1"
                    openhands_env["LLM_BASE_URL"] = self.settings.llm_base_url
                    openhands_env["LLM_API_KEY"] = self.settings.llm_api_key
                    openhands_env["LLM_MODEL"] = self.settings.llm_model
                    openhands_env["LLM_CACHING_PROMPT"] = "true" if self.settings.prompt_cache else "false"
                    
                    pattern = re.compile(r'Agent Controller ([a-z0-9-]+)')
                    buffer = ""
                    process = None
                    conversation_name = None
                    rate_limited = False
                    
                    try:
                        process = subprocess.Popen(
                            [openhands_init_script_path],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            env=openhands_env,
                            bufsize=1,  # Line buffered to avoid accumulating large buffers
                        )
                        
                        # Make stdout non-blocking
                        import fcntl
                        import select
                        flags = fcntl.fcntl(process.stdout, fcntl.F_GETFL)
                        fcntl.fcntl(process.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                        
                        last_log_time = time.time()
                        timeout = 300  # 5 minutes in seconds

                        while True:
                            # Use select to check if there's data available with a timeout
                            ready, _, _ = select.select([process.stdout], [], [], 1.0)
                            
                            if ready:
                                # Data is available, read it
                                try:
                                    line = process.stdout.readline()
                                    if line:
                                        logger.info(line)
                                        last_log_time = time.time()
                                        
                                        # Check for rate limiting
                                        if "agent_state='rate_limited'" in line or "AgentState.RATE_LIMITED" in line:
                                            rate_limited = True
                                            logger.warning(f"Rate limit detected for task {i}, will retry")
                                            process.kill()
                                            process.wait()  # Wait for process to fully terminate
                                            break
                                        if "AgentState.AWAITING_USER_INPUT" in line and conversation_name is not None:
                                            process.kill()
                                            process.wait()  # Wait for process to fully terminate
                                            break
                                        if not conversation_name:
                                            buffer += line
                                            match = pattern.search(buffer)
                                            if match:
                                                conversation_name = match.group(1)
                                except:
                                    pass
                            
                            # Check if process has ended
                            if process.poll() is not None:
                                # Process ended, read any remaining output
                                try:
                                    remaining = process.stdout.read()
                                    if remaining:
                                        logger.info(remaining)
                                        # Check remaining output for rate limiting too
                                        if "agent_state='rate_limited'" in remaining or "AgentState.RATE_LIMITED" in remaining or "AgentState.ERROR" in remaining:
                                            rate_limited = True
                                            logger.warning(f"Rate limit detected in final output for task {i}, will retry")
                                except:
                                    pass
                                break
                            
                            # Check timeout
                            # if time.time() - last_log_time > timeout:
                            #     logger.error(f"No logs for {timeout} seconds, killing subprocess for task {i}")
                            #     process.kill()
                            #     process.wait()  # Wait for process to fully terminate
                            #     break
                        
                        if not rate_limited:
                            logger.info(f"Extracted conversation name: {conversation_name}")    
                            process.wait()
                        
                        # Clean up buffer to free memory
                        buffer = None
                        
                    except subprocess.CalledProcessError as e:
                        logger.error(f"Error executing bash script: {e}")
                        logger.error(f"Stderr: {e.stderr}")
                        rate_limited = True
                    except FileNotFoundError:
                        logger.error(f"Error: Bash script not found at {openhands_init_script_path}")
                        raise  # Don't retry on file not found
                    finally:
                        # Ensure process is terminated
                        if process and process.poll() is None:
                            process.kill()
                            process.wait()
                    
                    # If rate limited, retry
                    if rate_limited:
                        retry_count += 1
                        logger.warning(f"Rate limit occurred for task {i}, retry {retry_count}/{max_retries}")
                        
                        # Clean up working repo before retry
                        try:
                            shutil.rmtree(os.path.join(self.root_path, self.repo_path, f"java/working_repo{i}"))
                        except Exception as e:
                            logger.error(f"Error deleting working repo during retry: {e}")
                        
                        # Clean up logger handlers
                        try:
                            for handler in logger.handlers[:]:
                                handler.close()
                                logger.removeHandler(handler)
                        except Exception as e:
                            logger.error(f"Error cleaning up logger handlers: {e}")
                        
                        gc.collect()
                        time.sleep(5)  # Wait a bit before retrying
                        continue
                    
                    # Success - copy events and break out of retry loop
                    if conversation_name:
                        src_events = os.path.join(self.settings.openhands_path, f".openhands/sessions/{conversation_name}/events")
                        dst_dir = os.path.join(self.root_path, self.outputs_path, f"{output_name}/task-{i}/events")
                        shutil.copytree(src_events, dst_dir)
                        logger.info(f"Copied events from {src_events} to {dst_dir}")
                    else:
                        logger.error(f"No conversation name found for task {i}")
                    
                    break  # Success, exit retry loop
                    
                except Exception as e:
                    logger.error(f"Error in get_trajectory for task {i} (attempt {retry_count + 1}): {e}")
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"Max retries reached for task {i}, giving up")
                        break
                    time.sleep(5)
                    continue

            # Final cleanup after all retries
            try:
                shutil.rmtree(os.path.join(self.root_path, self.repo_path, f"java/working_repo{i}"))
            except Exception as e:
                print(f"Error deleting working repo: {e}")
            
            # Clean up logger handlers to prevent memory leaks
            try:
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)
            except Exception as e:
                print(f"Error cleaning up logger handlers: {e}")
            
            # Force garbage collection to free memory
            gc.collect()
            
            return True if retry_count < max_retries else False

        existing_tasks = set()
        trajectories_dir = os.path.join(self.root_path, self.outputs_path, output_name)
        if os.path.exists(trajectories_dir):
            for task_dir in os.listdir(trajectories_dir):
                if task_dir.startswith("task-"):
                    task_num = int(task_dir.split("-")[1])
                    existing_tasks.add(task_num)
        if self.settings.task_list:
            inputs = [i for i in self.settings.task_list if i not in existing_tasks]
        else:
            inputs = [i for i in range(len(self.dataset)) if i not in existing_tasks]
        with ThreadPoolExecutor(max_workers=self.settings.num_workers) as executor:
            results = list(tqdm(executor.map(lambda i: get_trajectory(i), inputs), total=len(inputs)))
        # Retry failed tasks one at a time
        failed_tasks = [inputs[idx] for idx, success in enumerate(results) if not success]
        if failed_tasks:
            self.logger.info(f"Retrying {len(failed_tasks)} failed tasks one at a time")
            for task_id in tqdm(failed_tasks, desc="Retrying failed tasks"):
                get_trajectory(task_id)
        
        return {"evaluated_tasks": len(results)}

    def get_context(self, i, task, repo_path: str = "repoclassbench/temp", prompt: str = "") -> str:
        # Logic to extract context from the Java repository...
        return ""