from default_evaluator import VanillaJavaEvaluator, OpenHandsSettings
import os
import numpy as np
import tiktoken
import requests
import time
import pickle
from eval_tools import read_repo_files, semantic_chunking, rerank_chunks, robust_post, embed_chunks, embed_query, load_cached_embeddings, cache_embeddings, retrieve_semantic_chunks

class SemanticJavaEvaluator(VanillaJavaEvaluator):
    def __init__(self, root_path: str = "", repo_path: str = "repoclassbench/temp", dataset_path: str = "repoclassbench/datasets", outputs_path: str = "outputs", settings: OpenHandsSettings = None, embedding_cache_path: str = "embedding_cache", embed_url: str = "", rerank_url: str = "", nlq=False, context_path: str = "context", embed_api_key: str = "", rerank_api_key: str = "", embed_top_k: int = 50, rerank_top_k: int = 10) -> None:
        if not embed_url or (not rerank_url and rerank_top_k > 0):
            raise ValueError("Both embed_url and rerank_url must be provided.")
        super().__init__(root_path, repo_path, dataset_path, outputs_path, settings)
        self.embedding_cache_path = os.path.join(root_path, embedding_cache_path)
        self.embed_url = embed_url
        self.rerank_url = rerank_url
        self.nlq = nlq
        self.context_path = context_path
        self.embed_api_key = embed_api_key
        self.rerank_api_key = rerank_api_key
        self.embed_top_k = embed_top_k
        self.rerank_top_k = rerank_top_k
        self.settings = settings

    def get_context(self, i: int, task, repo_path: str = "repoclassbench/temp", prompt: str = "") -> str:
        context_file = os.path.join(self.root_path, self.context_path, f"{i}.txt")
        if os.path.exists(context_file):
            print(f"Loading existing context from {context_file}")
            with open(context_file, "r", encoding="utf-8") as f:
                existing_context = f.read()
            prefix = "Additionally, here are some potentially relevant code snippets from the repository:\n\n"
            return prefix + existing_context + prompt
        
        repo_path = os.path.join(self.root_path, repo_path, "java/original_repo/")
        filepath = task.file
        file_extensions = [".java"]
        filepath = os.path.join(repo_path, task.repo_dir.split("/")[-1], filepath)
        repo_name = filepath.replace(repo_path, "").split("/")[0]
        with open(filepath, "r", encoding="utf-8") as f:
            java_file_str = f.read()
        
        try:
            files = read_repo_files(os.path.join(repo_path, repo_name), file_extensions)
            print(f"Total files found: {len(files)}")
            chunks, chunk_dict = semantic_chunking(files)
            print(f"Total chunks created: {len(chunks)}")
            if self.nlq:
                java_file_str = task.description
            relevant_chunks = retrieve_semantic_chunks(java_file_str, chunks, chunk_dict, repo_path, repo_name, filepath, self.embedding_cache_path, self.embed_url, self.embed_api_key, topk=self.embed_top_k)
            if self.rerank_top_k > 0:
                ranked_chunks = rerank_chunks(java_file_str, relevant_chunks, self.rerank_url, self.rerank_api_key, topk=self.rerank_top_k)
            else:
                ranked_chunks = relevant_chunks

            for chunk in ranked_chunks:
                print(f"File: {chunk['file']}, Chunk Index: {chunk['chunk_index']}")

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
        finally:
            # Clean up large data structures to prevent memory leaks
            files = None
            chunks = None
            chunk_dict = None
            relevant_chunks = None
            ranked_chunks = None
