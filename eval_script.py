import sys
import os

# Change to the repoclassbench directory before importing
os.chdir('/home/azureuser/context_retrieval_evals/repoclassbench')

# Add the repoclassbench subdirectory to Python path
repo_root = '/home/azureuser/context_retrieval_evals/repoclassbench'
sys.path.insert(0, repo_root)

# Import from the context_retrieval_evals directory (parent of repoclassbench)
sys.path.insert(0, '/home/azureuser/context_retrieval_evals')

from agentic_evaluator import AgenticJavaEvaluator
from default_evaluator import VanillaJavaEvaluator, OpenHandsSettings
from semantic_evaluator import SemanticJavaEvaluator
from symbolic_evaluator import SymbolicJavaEvaluator
from combined_evaluator import CombinedJavaEvaluator

import json
# Load API key from credentials.json

credentials_path = os.path.join("/home/azureuser/credentials.json")
with open(credentials_path, 'r') as f:
    credentials = json.load(f)
    embed_api_key = credentials.get("EMBED_API_KEY", "")
    llm_api_key = credentials.get("LLM_API_KEY", "")

settings = OpenHandsSettings(
    max_iterations=100,
    llm_model="azure/deepprompt-gpt-5-2025-08-07",
    llm_base_url="", # Insert your own here
    llm_api_key=llm_api_key,
    num_workers=3,
    openhands_path="/home/azureuser",
    prompt_cache=False
)
outputs_path = "outputs"

embed_top_k = 50
rerank_top_k_list = [10, 5]

vanilla_evaluator = VanillaJavaEvaluator(
    root_path="/home/azureuser/context_retrieval_evals",
    repo_path="repoclassbench/temp",
    dataset_path="repoclassbench/datasets",
    outputs_path=outputs_path,
    settings=settings
)
result_vanilla = vanilla_evaluator.evaluate(output_name=f"vanilla_trajectories")
print(result_vanilla)

agentic_evaluator = AgenticJavaEvaluator(
    root_path="/home/azureuser/context_retrieval_evals",
    repo_path="repoclassbench/temp",
    dataset_path="repoclassbench/datasets",
    outputs_path=outputs_path,
    settings=settings
)
result_agentic = agentic_evaluator.evaluate(output_name=f"agentic_trajectories")
print(result_agentic)

semantic_nlq_evaluator = SemanticJavaEvaluator(
    root_path="/home/azureuser/context_retrieval_evals",
    repo_path="repoclassbench/temp",
    dataset_path="repoclassbench/datasets",
    outputs_path=outputs_path,
    embedding_cache_path="embedding_cache",
    embed_url="",
    rerank_url="",
    nlq=True,
    context_path=f"context/java/semantic_nlq/50_10",
    embed_api_key=embed_api_key,
    rerank_api_key=embed_api_key,
    embed_top_k=embed_top_k,
    rerank_top_k=10,
    settings=settings
)

result_semantic_nlq = semantic_nlq_evaluator.evaluate(output_name=f"semantic_nlq_default_trajectories")
print(result_semantic_nlq)

symbolic_evaluator = SymbolicJavaEvaluator(
    root_path="/home/azureuser/context_retrieval_evals",
    repo_path="repoclassbench/temp",
    dataset_path="repoclassbench/datasets",
    outputs_path=outputs_path,
    embedding_cache_path="embedding_cache",
    rerank_url="",
    context_path=f"context/java/symbolic/10_n",
    rerank_api_key=embed_api_key,
    rerank_top_k=10,
    settings=settings
)
result_symbolic = symbolic_evaluator.evaluate(output_name=f"symbolic_10_trajectories")
print(result_symbolic)

semantic_evaluator = SemanticJavaEvaluator(
    root_path="/home/azureuser/context_retrieval_evals",
    repo_path="repoclassbench/temp",
    dataset_path="repoclassbench/datasets",
    outputs_path=outputs_path,
    embedding_cache_path="embedding_cache",
    embed_url="",
    rerank_url="",
    nlq=False,
    context_path=f"context/java/semantic/{embed_top_k}_{10}_n",
    embed_api_key=embed_api_key,
    rerank_api_key=embed_api_key,
    embed_top_k=embed_top_k,
    rerank_top_k=10,
    settings=settings
)
result_semantic = semantic_evaluator.evaluate(output_name=f"semantic_{10}_trajectories")
print(result_semantic)
