# Training Data Generation for Code Context Retrieval

This directory contains tools for automatically generating training data for code context retrieval models. The system analyzes Java repositories to create query-context pairs suitable for training embedding models.

## Overview

The training data generation pipeline processes Java repositories to:
1. Extract Java classes and their metadata
2. Generate natural language descriptions of classes
3. Retrieve relevant symbolic and semantic code chunks
4. Create positive and negative training examples

## Files

### `training_data_gen.py`
Main orchestration script that processes multiple repositories in parallel to generate training data.

**Key Features:**
- Multi-threaded processing (configurable worker count)
- Repository-level logging
- Caching of previously processed repositories
- Automatic retry and error handling
- Progress tracking and statistics

### `combined_retrieval.py`
Core retrieval library providing symbolic and semantic context retrieval functionality.

**Key Features:**
- Tree-sitter based Java AST parsing
- Symbolic chunk retrieval (imports, method calls, class instantiations)
- Semantic embedding-based retrieval
- Chunk reranking using Qwen3-Reranker
- Embedding caching for efficiency

## Requirements

### Python Dependencies
```bash
# Core dependencies
tree-sitter
tree-sitter-java
openai
pyarrow
semantic-chunker
numpy
requests
```

### API Keys
Create a `credentials.json` file with:
```json
{
  "OPENAI_API_KEY": "your-azure-openai-key",
  "EMBED_API_KEY": "your-EMBED-api-key"
}
```

### Data Structure
- Input: Java repositories stored as parquet files in `/data2/10k_repo_data/repo_id=<repo_id>/`
- Output: Training data JSON files in the configured output directory

## Usage

### Basic Usage

```bash
# Configure credentials
cat > credentials.json << EOF
{
  "OPENAI_API_KEY": "your-key",
  "EMBED_API_KEY": "your-key"
}
EOF

# Run training data generation
python training_data_gen.py
```

### Configuration

Key configuration variables in `training_data_gen.py`:

```python
# Number of samples per repository
num_samples = 10

# Number of parallel workers
max_workers = 32

# Output directory
data_results_path = "08_top1_filtered_data"

# Input repository path
repo_data_path = "/data2/10k_repo_data"
```

### Output Format

The script generates JSON files (`<repo_id>.json`) with the following structure:

```json
[
  {
    "query": "Natural language description of the Java class",
    "pos": [
      "// filepath: src/example/Helper.java\npublic class Helper {...}",
      "// filepath: src/example/Utils.java\npublic class Utils {...}"
    ],
    "neg": [
      "// filepath: src/other/Unrelated.java\npublic class Unrelated {...}",
      ...
    ]
  }
]
```

- **query**: Natural language description of the target Java class
- **pos**: List of relevant code chunks (positive examples)
- **neg**: List of unrelated code chunks (negative examples)

## How It Works

### 1. Repository Processing

For each repository:
1. Reads Java files from parquet format
2. Performs semantic chunking of code
3. Samples Java classes (50-500 lines, excluding tests)
4. Generates class descriptions using GPT-4

### 2. Context Retrieval

**Symbolic Retrieval** (`combined_retrieval.py`):
- Parses target class AST to extract:
  - Import statements
  - Method invocations
  - Class instantiations
  - Super types (extends/implements)
- Finds chunks that define referenced symbols
- Includes files from same package and imports

**Semantic Retrieval** (optional):
- Embeds code chunks using Qwen3-Embedding-4B
- Computes cosine similarity with target class
- Retrieves top-k most similar chunks

### 3. Filtering and Ranking

- Uses LLM-based filtering to score chunk relevance
- Applies threshold-based filtering (default: 0.6)
- Caches scores for efficiency
- Selects top-k chunks as positive examples

### 4. Negative Sampling

- Randomly samples unrelated chunks from the repository
- Ensures diversity by excluding positive examples

## Advanced Features

### Class Filtering

The pipeline automatically filters out:
- Test classes (containing "test" in name or path)
- Classes shorter than 50 lines
- Classes longer than 500 lines
- Repositories with fewer than 10 Java files

### Logging

- Per-repository logs stored in `/home/azureuser/training_data_gen/runlogs/<repo_id>/run.log`
- Console output for errors only
- Thread-safe logging for parallel processing

### Caching

**Embedding Cache:**
- Location: `/home/azureuser/training_data_gen/embedding_cache/<repo_id>.pkl`
- Stores computed embeddings to avoid recomputation

**Score Cache:**
- Location: `scores/<repo_id>.json`
- Caches LLM filtering scores for reuse

### Resume Capability

The script automatically skips repositories that have already been processed (existing JSON files in output directory).

## Example Workflow

```bash
# 1. Prepare data directory
mkdir -p /data2/10k_repo_data/repo_id=example_repo/

# 2. Add parquet files with Java code
# Files should contain columns: file_path, file_content

# 3. Run generation
python training_data_gen.py

# 4. Monitor progress
tail -f /home/azureuser/training_data_gen/runlogs/example_repo/run.log

# 5. Check results
cat 08_top1_filtered_data/example_repo.json
```

## Performance Tuning

### Parallelization
```python
# Adjust worker count based on available resources
max_workers = 32  # Default
```

### Chunk Retrieval
```python
# In combined_retrieval.py
topk = 50  # Number of semantic chunks to retrieve
filter_threshold = 0.6  # Minimum relevance score
```

### Timeout Settings
```python
# Per-repository timeout
timeout = 3600  # 1 hour
```

## Troubleshooting

### Common Issues

**1. API Rate Limits**
- Reduce `max_workers` to decrease concurrent API calls
- Add retry logic with exponential backoff

**2. Memory Issues**
- Process repositories in smaller batches
- Clear embedding cache periodically

**3. Parsing Errors**
- Check Java syntax in parquet files
- Verify tree-sitter-java installation

**4. Empty Results**
- Verify symbolic retrieval finds matches
- Lower `filter_threshold` for more results
- Check that repositories have sufficient Java files

### Debug Mode

Enable detailed logging:
```python
# At top of training_data_gen.py
root_logger.setLevel(logging.DEBUG)
console_handler.setLevel(logging.DEBUG)
```

## Output Statistics

The script reports:
- ✓ Completed repositories (with sample count)
- ⊘ Skipped repositories (with reason)
- ✗ Failed repositories (with error message)

Example:
```
✓ repo_123: 10 samples
⊘ repo_456: insufficient_files: 8 found
✗ repo_789: API timeout

Results: 1 completed, 1 skipped, 1 failed
```

## Integration

The generated training data can be used with:
- Sentence transformers for contrastive learning
- Custom embedding model training
- Fine-tuning code search models
- Context retrieval evaluation benchmarks
