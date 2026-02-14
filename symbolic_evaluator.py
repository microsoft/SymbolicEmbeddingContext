from default_evaluator import VanillaJavaEvaluator, OpenHandsSettings
import os
import numpy as np
import tiktoken
import requests
import time
import pickle
from eval_tools import read_repo_files, semantic_chunking, rerank_chunks, retrieve_symbolic_chunks
import json

class SymbolicJavaEvaluator(VanillaJavaEvaluator):
    def __init__(self, root_path: str = "", repo_path: str = "repoclassbench/temp", dataset_path: str = "repoclassbench/datasets", outputs_path: str = "outputs", settings: OpenHandsSettings = None, embedding_cache_path: str = "embedding_cache", rerank_url: str = "", context_path: str = "context", rerank_api_key: str = "", rerank_top_k: int = 10, filter_threshold: float = 0.0, filter_url: str = "", filter_api_key: str = "", filter_model: str = "") -> None:
        if not rerank_url:
            raise ValueError("rerank_url must be provided.")
        super().__init__(root_path, repo_path, dataset_path, outputs_path, settings)
        self.embedding_cache_path = os.path.join(root_path, embedding_cache_path)
        self.rerank_url = rerank_url
        self.context_path = context_path
        self.rerank_api_key = rerank_api_key
        self.rerank_top_k = rerank_top_k
        self.settings = settings
        self.filter_threshold = filter_threshold
        self.filter_url = filter_url
        self.filter_api_key = filter_api_key
        self.filter_model = filter_model

    def get_context(self, i: int, task, repo_path: str = "repoclassbench/temp", prompt: str = "") -> str:
        try:
            scores_path = os.path.join(self.root_path, self.context_path.rsplit("/", 1)[0], "scores", f"{i}.json")
            context_file = os.path.join(self.root_path, self.context_path, f"{i}.txt")
            if os.path.exists(context_file):
                print(f"Loading existing context from {context_file}")
                with open(context_file, "r", encoding="utf-8") as f:
                    existing_context = f.read()
                prefix = "Additionally, here are some potentially relevant code snippets from the repository:\n\n"
                return prefix + existing_context + prompt
            elif self.filter_threshold > 0.0 and os.path.exists(scores_path):
                with open(scores_path, "r", encoding="utf-8") as scores_f:
                    score_data = json.load(scores_f)
                filtered_indices = sorted(score_data.keys(), key=lambda k: score_data[k]["score"], reverse=True)
                filtered_chunks = [score_data[k] for k in filtered_indices if score_data[k]["score"] > self.filter_threshold]
                ranked_chunks = filtered_chunks[:min(self.rerank_top_k, len(filtered_chunks))]
            else:
                repo_path = os.path.join(self.root_path, repo_path, "java/original_repo/")
                filepath = task.file
                file_extensions = [".java"]
                filepath = os.path.join(repo_path, task.repo_dir.split("/")[-1], filepath)
                repo_name = filepath.replace(repo_path, "").split("/")[0]
                with open(filepath, "r", encoding="utf-8") as f:
                    java_file_str = f.read()
                java_file_str = task.ground_truth
                
                files = None
                chunks = None
                chunk_dict = None
                relevant_chunks = None
                ranked_chunks = None
                
                try:
                    files = read_repo_files(os.path.join(repo_path, repo_name), file_extensions)
                    print(f"Total files found: {len(files)}")
                    chunks, chunk_dict = semantic_chunking(files)
                    print(f"Total chunks created: {len(chunks)}")
                    relevant_chunks = retrieve_symbolic_chunks(java_file_str, chunks, chunk_dict, repo_path, filepath)
                    if self.filter_threshold > 0.0:
                        filtered_chunks = self.filter_chunks(task.description, relevant_chunks, i)
                        ranked_chunks = filtered_chunks[:min(self.rerank_top_k, len(filtered_chunks))]
                    else:
                        ranked_chunks = rerank_chunks(java_file_str, relevant_chunks, self.rerank_url, self.rerank_api_key, topk=self.rerank_top_k)
                except Exception as e:
                    self.logger.error(f"Error during chunk retrieval/reranking for task {i}: {str(e)}")
                    ranked_chunks = relevant_chunks if relevant_chunks is not None else []
            # ranked_chunks = relevant_chunks
            output_dir = os.path.join(self.root_path, self.context_path)
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"{i}.txt")
            res = ""
            for i, chunk in enumerate(ranked_chunks):
                res += f"Snippet {i + 1}:\n"
                res += chunk['chunk']
                res += "\n\n"
            with open(output_path, "w", encoding="utf-8") as out_f:
                out_f.write(res)
        
            prefix = "Additionally, here are some potentially relevant code snippets from the repository:\n\n"
            return prefix + res + prompt
        except Exception as e:
            self.logger.error(f"Error in get_context for task {i}: {str(e)}")
            # context_file = os.path.join(self.root_path, self.context_path, f"{i}.txt")
            # os.makedirs(os.path.dirname(context_file), exist_ok=True)
            # with open(context_file, "w", encoding="utf-8") as f:
            #     f.write("")
            return ""
    def filter_chunks(self, query, chunks, task_id):
        """Filter relevant chunks based on a query."""
        snippets = ""
        for i, chunk in enumerate(chunks):
            snippets += f"snippet_id_{i + 1}: {chunk['chunk']}\n\n"
        
        prompt_path = os.path.join(self.root_path, "filtration_prompt.txt")
        with open(prompt_path, "r", encoding="utf-8") as pf:
            prompt = f"{pf.read()}"
            prompt = prompt.replace("<QUERY>", query)
            prompt = prompt.replace("<SNIPPETS>", snippets)
        url = self.filter_url

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.filter_api_key}"
        }

        data = {
            "input": prompt,
            "max_output_tokens": 16384,
            "model": self.filter_model
        }

        response = requests.post(url, headers=headers, json=data)

        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
        try:
            output = result["output"]
            response_json = None
            for item in output:
                if isinstance(item, dict) and "content" in item:
                    content = item["content"]
                    if isinstance(content, list) and len(content) > 0 and "text" in content[0]:
                        text = content[0]["text"]
                        response_json = json.loads(text)
                        break
            if response_json is None:
                raise ValueError("No valid JSON response found in the output.")
            # Write response_json to context/scores/i.jsonl
            output_json = {}
            for snippet_id, score in response_json.items():
                new_chunk = chunks[int(snippet_id.rsplit('_', 1)[1]) - 1]
                new_chunk["score"] = score
                output_json[snippet_id] = new_chunk
            filtered_indices = sorted(response_json.keys(), key=lambda k: response_json[k], reverse=True)
            filtered_chunks = [chunks[int(k.rsplit('_', 1)[1]) - 1] for k in filtered_indices if response_json[k] > self.filter_threshold]
            scores_dir = os.path.join(self.root_path, self.context_path.rsplit("/", 1)[0], "scores")
            os.makedirs(scores_dir, exist_ok=True)
            scores_path = os.path.join(scores_dir, f"{task_id}.json")
            with open(scores_path, "w", encoding="utf-8") as scores_f:
                json.dump(output_json, scores_f)
                scores_f.write("\n")
            return filtered_chunks

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decoding error in filter_chunks: {e}")
            return chunks

        return result.choices[0].message.content