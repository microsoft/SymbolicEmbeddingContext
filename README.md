# What Do SWE Agents Look For? An Empirical Study of Semantic and Symbolic Context Usage in Repository Level Code Generation
This is the repository of evaluation framework and source code for "What Do SWE Agents Look For? An Empirical Study of Semantic and Symbolic Context Usage in Repository Level Code Generation".

This repository contains tools and scripts for evaluating different context retrieval strategies in code completion tasks using the RepoClassBench dataset and OpenHands framework.

## Overview

The evaluation framework tests various approaches for providing relevant code context to language models when implementing Java classes. It compares different retrieval strategies including:

- **Vanilla**: No additional context provided
- **Semantic**: Context retrieved using semantic embeddings
- **Symbolic**: Context retrieved using symbolic code analysis
- **Combined**: Hybrid approach combining semantic and symbolic retrieval
- **Agentic**: Agentic tool-based context retrieval

## Prerequisites

1. **OpenHands**: Install and configure OpenHands at `/home/azureuser` (or update paths in scripts): for more information, visit https://github.com/OpenHands/OpenHands/blob/main/Development.md
2. **RepoClassBench**: Dataset should be present in `repoclassbench/` directory, install requirements from `repoclassbench/requirements.txt`
3. **API Keys**: Create a `credentials.json` file in the parent directory with:
   ```json
   {
     "EMBED_API_KEY": "your-embed-api-key",
     "LLM_API_KEY": "your-llm-api-key"
   }
   ```
4. **Python Dependencies**: 
   - pandas
   - numpy
   - tiktoken
   - requests
   - javalang
   - langchain
   - tqdm

## Quick Start

The main evaluation script (`eval_script.py`) demonstrates how to run different evaluators.

**Important**: Before importing the evaluators, you need to set up the Python path correctly, the beginning of eval_script.py shows an example which may need to be edited depending on your setup.

## Best Practices

1. **Caching**: Use embedding caches to avoid re-computing embeddings for the same repository
2. **Context Paths**: Pre-compute context and save to disk for faster repeated evaluations
3. **Parallel Execution**: Adjust `num_workers` based on available resources
4. **Memory Management**: The framework includes cleanup to prevent memory leaks with large repositories
5. **Iterative Development**: Start with a small `task_list` to validate configuration before full runs