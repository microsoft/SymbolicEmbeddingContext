import os
from openai import AzureOpenAI
import random
import tree_sitter_java as tsjava
from tree_sitter import Language, Parser
import combined_retrieval
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import sys
import shutil
import threading
import traceback

# Initialize tree-sitter Java parser
JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

# Set up root logger with console output (errors only)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Remove existing handlers
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Add console handler to root logger (errors only)
console_handler = logging.StreamHandler(sys.stdout)
console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.ERROR)
root_logger.addHandler(console_handler)

# Thread-local storage for file handlers
_thread_local = threading.local()

def get_repo_logger(repo_id):
    """Get a logger specific to this repo and thread."""
    log_file = f"/home/azureuser/training_data_gen/runlogs/{repo_id}/run.log"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Create a repo-specific logger (not the root logger)
    logger = logging.getLogger(f"repo_{repo_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Don't propagate to root logger
    
    # Remove old handlers
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    
    # Add file handler
    file_handler = logging.FileHandler(log_file, mode='w')
    file_formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    
    # Store for cleanup
    _thread_local.file_handler = file_handler
    _thread_local.logger = logger
    
    return logger

def cleanup_repo_logger():
    """Clean up the file handler for this thread."""
    if hasattr(_thread_local, 'file_handler'):
        try:
            _thread_local.file_handler.close()
        except:
            pass
    if hasattr(_thread_local, 'logger'):
        logger = _thread_local.logger
        for handler in logger.handlers[:]:
            try:
                handler.close()
                logger.removeHandler(handler)
            except:
                pass
def find_java_files(repo_path, parquets=False):
    """Find all Java files in the repository."""
    java_files = []
    content = []
    if parquets:
        for root, dirs, files in os.walk(repo_path):
            for file in files:
                if file.endswith('.parquet'):
                    file_path = os.path.join(root, file)
                    try:
                        import pyarrow.parquet as pq
                        table = pq.read_table(file_path)
                        df = table.to_pandas()
                        for _, row in df.iterrows():
                            java_files.append(row['file_path'])
                            content.append(row['file_content'])
                    except Exception as e:
                        print(f"Error reading {file_path}: {e}")
    else:
        for root, dirs, files in os.walk(repo_path):
            for file in files:
                if file.endswith('.java'):
                    java_files.append(os.path.join(root, file))
    return java_files, content


def parse_java_file(file_path, content=None):
    """Parse a Java file and extract classes using tree-sitter."""
    try:
        if content is None:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        
        tree = parser.parse(bytes(content, 'utf-8'))
        lines = content.split('\n')
        
        # Extract package declaration
        package_declaration = ""
        def extract_package(node):
            if node.type == 'package_declaration':
                return node.text.decode('utf-8')
            for child in node.children:
                result = extract_package(child)
                if result:
                    return result
            return None
        
        package_declaration = extract_package(tree.root_node)
        if not package_declaration:
            package_declaration = ""
        
        # Extract import statements
        imports = []
        
        def extract_imports(node):
            if node.type == 'import_declaration':
                import_text = node.text.decode('utf-8')
                imports.append(import_text)
            for child in node.children:
                extract_imports(child)
        
        extract_imports(tree.root_node)
        import_block = '\n'.join(imports) if imports else ""
        
        # Extract class declarations
        classes = []
        
        def extract_classes(node):
            if node.type == 'class_declaration':
                name_node = node.child_by_field_name('name')
                if name_node:
                    class_name = name_node.text.decode('utf-8')
                    
                    # Get the start and end positions of the class
                    start_line = node.start_point[0]
                    end_line = node.end_point[0]
                    
                    # Extract class lines
                    class_lines = lines[start_line:end_line + 1]
                    line_count = len(class_lines)
                    
                    # Only include classes with 50-500 lines
                    if 50 <= line_count <= 500:
                        # Combine package, imports, and class body
                        class_body_with_imports = ""
                        if package_declaration:
                            class_body_with_imports = package_declaration + "\n\n"
                        if import_block:
                            class_body_with_imports += import_block + '\n\n'
                        class_body_with_imports += '\n'.join(class_lines)
                        
                        classes.append({
                            'file_path': file_path,
                            'class_name': class_name,
                            'node': node,
                            'line_count': line_count,
                            'class_body': class_body_with_imports
                        })
            
            # Recursively traverse children
            for child in node.children:
                extract_classes(child)
        
        extract_classes(tree.root_node)
        return classes
    except Exception as e:
        logging.error(f"Unexpected error parsing {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
        return []

def get_all_classes(repo_path, parquets=False):
    """Get all Java classes in a repository."""
    java_files, content = find_java_files(repo_path, parquets=parquets)
    print(f"Found {len(java_files)} Java files")
    
    all_classes = []
    if len(content) == len(java_files):
        for java_file, content in zip(java_files, content):
            classes = parse_java_file(java_file, content=content)
            all_classes.extend(classes)
    
    print(f"Found {len(all_classes)} Java classes")
    return all_classes

def sample_java_classes(repo_path, num_samples, available_classes, parquets=False):
    """Randomly sample x Java classes from a repository."""

    if num_samples > len(available_classes):
        print(f"Warning: Requested {num_samples} samples but only {len(available_classes)} classes available")
        num_samples = len(available_classes)

    sampled_classes = []
    
    while len(sampled_classes) < num_samples and available_classes:
        sample = random.choice(available_classes)
        available_classes.remove(sample)
        
        # Skip if it's a test class
        class_name = sample['class_name'].lower()
        file_path = sample['file_path'].lower()
        if 'test' in class_name or 'test' in file_path:
            continue
            
        sampled_classes.append(sample)
    return sampled_classes, available_classes

def load_fewshot_examples(json_path, num_examples=3):
    """Load few-shot examples from java_data.json"""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    examples = []
    for i, item in enumerate(data[:num_examples]):
        examples.append({
            'class_body': item['ground_truth_class_body'],
            'description': item['detailed_description']  # or 'sketchy_description'
        })
    return examples

def get_class_description(java_file_str, client):
    """Generate a brief description of a Java class."""
    model_name = "deepprompt-gpt-5-mini-2025-08-07-global"
    fewshot_examples = load_fewshot_examples('/home/azureuser/repoclassbench/data/input/java_data.json', num_examples=3)
    fewshot_text = ""
    for i, example in enumerate(fewshot_examples, 1):
        fewshot_text += f"\n\n### Example {i}:\n"
        fewshot_text += f"Java Class:\n```java\n{example['class_body']}\n```\n\n"
        fewshot_text += f"Description:\n{example['description']}\n"
    
    response = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant.",
            },
            {
                "role": "user",
                "content": f"""Given the following Java class implementation, generate a concise natural language description that explains what this class does, its purpose, and briefly summarize what the methods in the class do. Write informally without bulleted or numbered lists.
                            Here are some examples of good descriptions:
                            {fewshot_text}

                            Now, please provide a similar detailed description for the following Java class:

                            Java Class:
                            ```java
                            {java_file_str}
                            ```"""
            }
        ],
        max_completion_tokens=16384,
        model=model_name
    )
    return response.choices[0].message.content

def filter_chunks(query, full_chunks, client, repo_id, filepath, class_name, max_chunks=60, filter_threshold=0.6, top_k=3):
        """Filter relevant chunks based on a query."""
        scores_dir = "scores"
        if os.path.isfile(os.path.join(scores_dir, f"{repo_id}.json")):
            with open(os.path.join(scores_dir, f"{repo_id}.json"), "r", encoding="utf-8") as scores_f:
                repo_json = json.load(scores_f)
            if filepath in repo_json:
                output_json = repo_json[filepath]
                filtered_indices = sorted(output_json.keys(), key=lambda k: output_json[k]['score'], reverse=True)
                filtered_chunks = [output_json[k]['chunk'] for k in filtered_indices if output_json[k]['score'] > filter_threshold]
                return filtered_chunks[:min(top_k, len(filtered_chunks))]
        split_chunks = [full_chunks[max_chunks*i:max_chunks*(i+1)] for i in range((len(full_chunks) + max_chunks - 1)//max_chunks)]
        model_name = "deepprompt-gpt-5-mini-2025-08-07-global"
        total_data = {}

        for j, chunks in enumerate(split_chunks):
            snippets = ""
            for i, chunk in enumerate(chunks):
                snippets += f"snippet_id_{max_chunks*j + i + 1}: {chunk['chunk']}\n\n"

            prompt_path = "filtration_prompt.txt"
            with open(prompt_path, "r", encoding="utf-8") as pf:
                prompt = f"{pf.read()}"
                prompt = prompt.replace("<QUERY>", query)
                prompt = prompt.replace("<SNIPPETS>", snippets)
            response = client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant.",
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_completion_tokens=16384,
                model=model_name
            )

            try:
                output = response.choices[0].message.content
                response_json = json.loads(output)
                total_data.update(response_json)
                if response_json is None:
                    raise ValueError("No valid JSON response found in the output.")
            except json.JSONDecodeError as e:
                logging.error(f"JSON decoding error in filter_chunks: {e}")
                return full_chunks
        output_json = {}
        for snippet_id, score in total_data.items():
            idx = int(snippet_id.rsplit('_', 1)[1]) - 1
            if idx < len(full_chunks):
                new_chunk = full_chunks[idx].copy()
                new_chunk["score"] = score
                output_json[snippet_id] = new_chunk
        output_json["description"] = query
        filtered_indices = sorted(total_data.keys(), key=lambda k: total_data[k], reverse=True)
        filtered_chunks = [full_chunks[int(k.rsplit('_', 1)[1]) - 1] for k in filtered_indices if int(k.rsplit('_', 1)[1]) - 1 < len(full_chunks) and total_data[k] > filter_threshold]
        scores_dir = "scores"
        os.makedirs(scores_dir, exist_ok=True)
        scores_path = os.path.join(scores_dir, f"{repo_id}.json")
        if os.path.exists(scores_path):
            with open(scores_path, "r", encoding="utf-8") as scores_f:
                repo_json = json.load(scores_f)
            repo_json[f"{filepath}|{class_name}"] = output_json
        else:
            repo_json = {f"{filepath}|{class_name}": output_json}
        with open(scores_path, "w", encoding="utf-8") as scores_f:
            json.dump(repo_json, scores_f)
        return filtered_chunks[:min(top_k, len(filtered_chunks))]


def generate_pairs(repo_id):
    """Process a single repository and return results."""
    scores_dir = "scores"
    path_exists = os.path.isfile(os.path.join(scores_dir, f"{repo_id}.json"))

    try:
        curr_run_dir = "/home/azureuser/training_data_gen/curr_run"
        os.makedirs(os.path.join(curr_run_dir, f"{repo_id}"), exist_ok=True)
        logger = None
        # Get repo-specific logger
        logger = get_repo_logger(repo_id)
        logger.info(f"Starting processing for repo {repo_id}")
        
        repo_path = f"/data2/10k_repo_data/repo_id={repo_id}"
        num_samples = 10
        
        try:
            client = AzureOpenAI(
                api_version="2024-12-01-preview",
                azure_endpoint="https://deepprompteastus2.openai.azure.com/",
                api_key=os.environ["OPENAI_API_KEY"]
            )
        except Exception as e:
            logger.error(f"Failed to create Azure client: {e}")
            raise
        
        file_extensions = [".java"]
        try:
            files = combined_retrieval.read_repo_files(repo_path, file_extensions, parquets=True)
        except Exception as e:
            logger.error(f"Failed to read repo files: {e}")
            raise
            
        logger.info(f"Found {len(files)} Java files in the repository")
        
        if len(files) < 10:
            logger.info(f"Skipping repository {repo_id} due to insufficient Java files: {len(files)} found")
            return {"status": "skipped", "reason": f"insufficient_files: {len(files)} found", "repo_id": repo_id}
        
        try:
            chunks, chunk_dict = combined_retrieval.semantic_chunking(files)
        except Exception as e:
            logger.error(f"Failed semantic chunking: {e}")
            raise
            
        if chunk_dict:
            sample_key = next(iter(chunk_dict))
            logger.info(f"Sample chunk_dict element: {sample_key}: {chunk_dict[sample_key]}")
        
        final_data = []
        try:
            available_classes = get_all_classes(repo_path, parquets=True)
        except Exception as e:
            logger.error(f"Failed to get all classes: {e}")
            raise
            
        logger.info(f"Found {len(available_classes)} Java classes in the repository")
        
        attempts = 0
        max_total_attempts = len(available_classes) + 50
        seen_set = set()
        while len(final_data) < num_samples and available_classes and attempts < max_total_attempts:
            attempts += 1
            scores_dir = "scores"
            if path_exists and os.path.isfile(os.path.join(scores_dir, f"{repo_id}.json")):
                with open(os.path.join(scores_dir, f"{repo_id}.json"), "r", encoding="utf-8") as scores_f:
                    repo_json = json.load(scores_f)
                sampled_key = None
                while sampled_key is None or sampled_key in seen_set:
                    sampled_key = random.sample(list(repo_json.keys()), 1)[0]
                seen_set.add(sampled_key)
                if len(seen_set) >= len(repo_json.keys()):
                    path_exists = False  # Exhausted all scored samples
                try:
                    sampled_file_path, sampled_class_name = sampled_key.split("|", 1)
                    for sample in available_classes:
                        if sample['file_path'] == sampled_file_path and sample['class_name'] == sampled_class_name:
                            print(f"Removed class {sample['class_name']} from file {sample['file_path']} from available_classes")
                            available_classes.remove(sample)
                            break
                except ValueError:
                    print(f"Sampled key {sampled_key} not in available_classes, skipping removal")
                    pass
                print(f"Sampled key from scores for {repo_id}: {sampled_key}")
                sym_chunks = list(repo_json[sampled_key].values())
                sym_chunks = [c for c in sym_chunks if isinstance(c, dict) and 'score' in c]
                ranked_chunks = sorted(enumerate(sym_chunks), key=lambda x: (x[1]['score'], -x[0]), reverse=True)
                ranked_chunks = [c[1] for c in ranked_chunks]
                ranked_chunks = [c for c in ranked_chunks if c['score'] > 0.8]
                ranked_chunks = ranked_chunks[:min(3, len(ranked_chunks))]
                description = repo_json[sampled_key].get("description", "")
            else:

                try:
                    samples, available_classes = sample_java_classes(repo_path, 1, available_classes, parquets=True)
                except Exception as e:
                    logger.error(f"Failed to sample classes: {e}")
                    raise
                
                if len(samples) == 0:
                    logger.info(f"No valid samples available (all remaining classes filtered out)")
                    continue
                    
                sample = samples[0]
                filepath = sample['file_path']
                java_file_str = sample['class_body']
                print(f"Processing class {sample['class_name']} from file {filepath}")
                logger.info(f"Processing class {sample['class_name']} from file {filepath}")
                
                try:
                    symbolic_chunks = combined_retrieval.retrieve_symbolic_chunks(
                        java_file_str, chunks, chunk_dict, repo_path, 
                        repo_java_files=[file["path"] for file in files]
                    )
                    logger.info(f"Retrieved {len(symbolic_chunks)} symbolic chunks")
                except Exception as e:
                    logger.warning(f"Error retrieving symbolic chunks for {sample['class_name']}: {e}")
                    logger.warning(f"Traceback: {traceback.format_exc()}")
                    continue
                
                if len(symbolic_chunks) == 0:
                    logger.info(f"Skipping class {sample['class_name']} in {filepath} due to no symbolic matches")
                    try:
                        available_classes.remove(sample)
                    except ValueError:
                        pass
                    continue

                
                logger.info(f"Symbolic chunks: {len(symbolic_chunks)}")

                try:
                    description = get_class_description(java_file_str, client)
                except Exception as e:
                    logger.warning(f"Error generating description for {filepath}: {e}")
                    continue
                try:
                    # ranked_chunks = combined_retrieval.rerank_chunks(java_file_str, symbolic_chunks)
                    ranked_chunks = filter_chunks(description, symbolic_chunks, client, repo_id, sample["file_path"], sample["class_name"])
                except Exception as e:
                    logger.warning(f"Error reranking chunks for {filepath}: {e}")
                    continue
            
            try:
                if len(ranked_chunks) == 0:
                    logger.info(f"No relevant chunks found for class {sample['class_name']} in {filepath}, skipping")
                    continue
                ranked_chunk_ids = {chunk.get('chunk_id', id(chunk['chunk'])) for chunk in ranked_chunks}
                available_chunks = [chunk for chunk in chunks 
                                  if id(chunk) not in ranked_chunk_ids and chunk not in [rc['chunk'] for rc in ranked_chunks]]
                negative_chunks = random.sample(available_chunks, min(20, len(available_chunks)))
                
                datum = {
                    "query": description,
                    "pos": [chunk['chunk'] for chunk in ranked_chunks],
                    "neg": [chunk["chunk"] for chunk in negative_chunks],
                }
                final_data.append(datum)
                logger.info(f"Successfully added sample {len(final_data)}/{num_samples}")
            except Exception as e:
                logger.warning(f"Error creating data point for {sample['class_name']}: {e}")
                continue

        os.makedirs(f"{data_results_path}", exist_ok=True)
        with open(f'{data_results_path}/{repo_id}.json', 'w', encoding='utf-8') as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Successfully processed repository {repo_id} with {len(final_data)} samples")
        return {"status": "success", "samples": len(final_data), "repo_id": repo_id}
    
    except Exception as e:
        error_msg = f"Error processing repository {repo_id}: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        if logger:
            logger.error(error_msg)
        else:
            logging.error(error_msg)
        return {"status": "error", "error": str(e), "repo_id": repo_id}
    
    finally:
        # Remove the directory created for this repo
        try:
            if os.path.exists(os.path.join(curr_run_dir, f"{repo_id}")):
                shutil.rmtree(os.path.join(curr_run_dir, f"{repo_id}"))
        except Exception as e:
            if logger:
                logger.error(f"Error removing curr_run directory: {e}")
        
        # Clean up logger
        cleanup_repo_logger()

if __name__ == "__main__":
    global data_results_path
    repo_data_path = "/data2/10k_repo_data"
    repo_ids = []
    existing_repo_ids = set()
    data_results_path = "08_top1_filtered_data"
    
    with open('credentials.json', 'r') as f:
        credentials = json.load(f)
        os.environ["OPENAI_API_KEY"] = credentials['OPENAI_API_KEY']
        os.environ["EMBED_API_KEY"] = credentials['EMBED_API_KEY']
    
    if os.path.exists(data_results_path):
        for filename in os.listdir(data_results_path):
            if filename.endswith('.json'):
                repo_id = filename[:-5]
                existing_repo_ids.add(repo_id)
    
    for dir_name in os.listdir(repo_data_path):
        if dir_name.startswith("repo_id=") and dir_name[8:] not in existing_repo_ids:
            # Check if parquet files have more than 10 rows
            parquet_found = False
            try:
                import pyarrow.parquet as pq
                for root, dirs, files in os.walk(os.path.join(repo_data_path, dir_name)):
                    for file in files:
                        if file.endswith('.parquet'):
                            parquet_found = True
                            file_path = os.path.join(root, file)
                            table = pq.read_table(file_path)
                            if len(table) < 10:
                                break
                    if parquet_found:
                        break
                if not parquet_found or len(table) < 10:
                    continue
            except Exception:
                pass
            repo_id = dir_name.split("=")[1]
            repo_ids.append(repo_id)
    repo_ids = repo_ids[::-1]
    print(f"Processing {len(repo_ids)} repositories with 32 workers...")
    
    completed = 0
    failed = 0
    skipped = 0
    
    with ThreadPoolExecutor(max_workers=32) as executor:
        # Use as_completed to properly track which tasks finish
        futures = {executor.submit(generate_pairs, repo_id): repo_id for repo_id in repo_ids}
        
        for future in as_completed(futures):
            repo_id = futures[future]
            try:
                result = future.result(timeout=3600)  # 1 hour timeout per repo
                if result["status"] == "success":
                    completed += 1
                    print(f"✓ {repo_id}: {result['samples']} samples")
                elif result["status"] == "skipped":
                    skipped += 1
                    print(f"⊘ {repo_id}: {result['reason']}")
                else:
                    failed += 1
                    print(f"✗ {repo_id}: {result['error']}")
            except Exception as e:
                failed += 1
                print(f"✗ {repo_id}: Unhandled exception: {e}")
    
    print(f"\nResults: {completed} completed, {skipped} skipped, {failed} failed")
