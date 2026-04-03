import tree_sitter_java as tsjava
from tree_sitter import Language, Parser
import os
from semantic_chunker import get_chunker
import pickle
import requests
import re
import sys
import tqdm
import logging
import time
import numpy as np
import json

logger = logging.getLogger(__name__)

# Initialize tree-sitter Java parser
JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)
def parse_java_file(parsed_file):
    """Parse Java AST using tree-sitter and extract imports, method calls, class instantiations, and super types."""
    tree = parsed_file
    imports = []
    method_calls = set()
    class_instantiations = set()
    super_types = set()
    
    def traverse(node):
        """Recursively traverse the tree-sitter AST."""
        node_type = node.type
        
        # Extract imports - get the full scoped_identifier text
        if node_type == 'import_declaration':
            for child in node.children:
                if child.type == 'scoped_identifier':
                    import_path = child.text.decode('utf-8')
                    imports.append(import_path)
                    break
        
        # Extract method invocations
        elif node_type == 'method_invocation':
            name_node = node.child_by_field_name('name')
            if name_node:
                method_calls.add(name_node.text.decode('utf-8'))
        
        # Extract class instantiations (object_creation_expression)
        elif node_type == 'object_creation_expression':
            type_node = node.child_by_field_name('type')
            if type_node:
                if type_node.type == 'type_identifier':
                    class_instantiations.add(type_node.text.decode('utf-8'))
                elif type_node.type == 'generic_type':
                    # Get the base type from generic_type
                    for child in type_node.children:
                        if child.type == 'type_identifier':
                            class_instantiations.add(child.text.decode('utf-8'))
                            break
        
        # Extract superclass and interfaces
        elif node_type == 'class_declaration':
            # Superclass
            for child in node.children:
                if child.type == 'superclass':
                    for subchild in child.children:
                        if subchild.type == 'type_identifier':
                            super_types.add(subchild.text.decode('utf-8'))
                        elif subchild.type == 'generic_type':
                            for gc in subchild.children:
                                if gc.type == 'type_identifier':
                                    super_types.add(gc.text.decode('utf-8'))
                                    break
                
                # Interfaces - look for super_interfaces
                elif child.type == 'super_interfaces':
                    for subchild in child.children:
                        if subchild.type == 'type_list':
                            for item in subchild.children:
                                if item.type == 'type_identifier':
                                    super_types.add(item.text.decode('utf-8'))
                                elif item.type == 'generic_type':
                                    for gc in item.children:
                                        if gc.type == 'type_identifier':
                                            super_types.add(gc.text.decode('utf-8'))
                                            break
        
        elif node_type == 'interface_declaration':
            # Interfaces can extend other interfaces
            for child in node.children:
                if child.type == 'extends_interfaces':
                    for subchild in child.children:
                        if subchild.type == 'type_list':
                            for item in subchild.children:
                                if item.type == 'type_identifier':
                                    super_types.add(item.text.decode('utf-8'))
                                elif item.type == 'generic_type':
                                    for gc in item.children:
                                        if gc.type == 'type_identifier':
                                            super_types.add(gc.text.decode('utf-8'))
                                            break
        
        # Recursively traverse children
        for child in node.children:
            traverse(child)
    
    traverse(tree.root_node)
    
    logger.info(f"Imports: {imports}")
    logger.info(f"Method Calls: {method_calls}")
    logger.info(f"Class Instantiations: {class_instantiations}")
    logger.info(f"Super Types: {super_types}")
    return imports, method_calls, class_instantiations, super_types

def find_repo_files_for_imports(imports, repo_root, repo_java_files=[]):
    logger.info(repo_java_files)
    # Map import paths to file paths in the repo
    import_to_file = set()
    # Collect all .java files in the repo
    if not repo_java_files:
        for root, dirs, files in os.walk(repo_root):
            for file in files:
                if file.endswith('.java'):
                    repo_java_files.append(os.path.join(root, file))
    for imp in imports:
        rel_path = imp.replace('.', '/') + '.java'
        for abs_path in repo_java_files:
            if abs_path.endswith(rel_path):
                import_to_file.add(abs_path)
                break  # Stop after finding the first match
    return import_to_file

def find_definitions_in_chunk(chunk_code):
    """Returns set of method and class/interface/enum names defined in the chunk using tree-sitter."""
    methods = set()
    types = set()
    
    try:
        tree = parser.parse(bytes(chunk_code, 'utf-8'))
        
        def traverse(node):
            # Extract method declarations
            if node.type == 'method_declaration':
                name_node = node.child_by_field_name('name')
                if name_node:
                    methods.add(name_node.text.decode('utf-8'))
            
            # Extract class, interface, and enum declarations
            elif node.type in ['class_declaration', 'interface_declaration', 'enum_declaration']:
                name_node = node.child_by_field_name('name')
                if name_node:
                    types.add(name_node.text.decode('utf-8'))
            
            # Recursively traverse children
            for child in node.children:
                traverse(child)
        
        traverse(tree.root_node)
        
        if methods or types:
            return methods, types
    except:
        pass  # Fallback to regex below if parsing fails

    # Fallback: regex scan for class/interface/enum declarations
    methods = set()
    types = set()
    # This regex matches 'class', 'interface', or 'enum' followed by a valid Java identifier
    for match in re.finditer(r'\b(class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)', chunk_code):
        types.add(match.group(2))
    return methods, types
def get_package_path(parsed_file, repo_root):
    """Extract package path from tree-sitter AST."""
    try:
        tree = parsed_file
        
        def find_package(node):
            if node.type == 'package_declaration':
                name_node = node.child_by_field_name('name')
                if name_node:
                    package_name = name_node.text.decode('utf-8')
                    return package_name.replace('.', '/')
            for child in node.children:
                result = find_package(child)
                if result:
                    return result
            return None
        
        package_path = find_package(tree.root_node)
        if package_path:
            return package_path
    except Exception as e:
        logger.info(f"Error parsing package: {e}")
    return None
def retrieve_symbolic_chunks(target_java_code, chunks, chunk_dict, repo_root, repo_java_files=[]): 
    try:
        parsed_file = parser.parse(bytes(target_java_code, 'utf-8'))
        imports, method_calls, class_insts, super_types = parse_java_file(parsed_file)
        import_files = find_repo_files_for_imports(imports, repo_root, repo_java_files=repo_java_files)
        imported_class_names = set(imp.split('.')[-1] for imp in imports)
        referenced_types = class_insts | imported_class_names | super_types
    except Exception as e:
        print(f"ERROR parsing target Java code: {type(e).__name__}: {str(e)}")
        logging.error(f"Unexpected error parsing target Java code: {type(e).__name__}: {str(e)}", exc_info=True)
        return []

    # Find all files in the same package
    package_dir = get_package_path(parsed_file, repo_root)
    package_files = set()
    if package_dir and os.path.isdir(package_dir):
        for file in os.listdir(package_dir):
            if file.endswith('.java'):
                package_files.add(os.path.join(package_dir, file))
    elif package_dir and repo_java_files:
        for file_path in repo_java_files:
            if package_dir in file_path:
                package_files.add(file_path)

    # Combine import files and package files
    files_to_search = import_files | package_files

    chunk_id_set = set()
    relevant_chunks = []
    for file in files_to_search:
        file_chunks = chunk_dict.get(file, {})
        for chunk in file_chunks.values():
            methods, classes = find_definitions_in_chunk(chunk['chunk'])
            if (
                methods & method_calls
                or classes & referenced_types
            ):
                if (chunk['file'], chunk['chunk_index']) not in chunk_id_set:
                    chunk_id_set.add((chunk['file'], chunk['chunk_index']))
                    relevant_chunks.append(chunk)
                    chunk_id_set.add((chunk["file"], chunk["chunk_index"]))
                    i = chunk["chunk_index"]
                    while len(chunk["chunk"]) < 1000 or "\n" not in chunk['chunk'].strip():
                        if chunk_dict[chunk["file"]].get(chunk["chunk_index"] + 1, {}) and (chunk["file"], chunk["chunk_index"] + 1) not in chunk_id_set:
                            relevant_chunks[-1]["chunk"] += chunk_dict[chunk["file"]].get(chunk["chunk_index"] + 1, {}).get("chunk", "")
                            chunk_id_set.add((chunk["file"], chunk["chunk_index"] + 1))
                        else:
                            break
    return relevant_chunks

def retrieve_semantic_chunks(query, chunks, chunk_dict, repo_path, repo_name, file_path, topk=10):
    cache_path = os.path.join("/home/azureuser/training_data_gen/embedding_cache", f"{repo_name}.pkl")
    cached_chunks = load_cached_embeddings(cache_path)
    if cached_chunks is not None and len(cached_chunks) == len(chunks):
        chunks = cached_chunks
    else:
        chunks = embed_chunks(chunks)
        cache_embeddings(chunks, cache_path)

    query_embedding = embed_query(query)

    def cosine_similarity(a, b):
        a = np.array(a)
        b = np.array(b)
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

    for chunk in chunks:
        if chunk["file"] == file_path or "test" in chunk["file"].lower():
            chunk["similarity"] = float('-inf')  # Deprioritize chunks from the same file
        else:
            chunk["similarity"] = cosine_similarity(query_embedding, chunk["embedding"])

    sorted_chunks = sorted(chunks, key=lambda x: x["similarity"], reverse=True)
    res = []
    file_set = set()
    while len(res) < topk and sorted_chunks:
        candidate = sorted_chunks.pop(0)
        if (candidate["file"], candidate["chunk_index"]) not in file_set:
            res.append(candidate)
            file_set.add((candidate["file"], candidate["chunk_index"]))
            if len(candidate["chunk"]) < 100 or "\n" not in candidate['chunk'].strip():
                if (candidate["file"], candidate["chunk_index"] + 1) in chunk_dict and (candidate["file"], candidate["chunk_index"] + 1) not in file_set:
                    file_set.add((candidate["file"], candidate["chunk_index"] + 1))
                    res.append(chunk_dict[candidate["file"]].get(candidate["chunk_index"] + 1, ""))
    return res

def read_repo_files(repo_path, file_extensions=None, parquets=False):
    file_contents = []
    if parquets:
        for root, _, files in os.walk(repo_path):
            for file in files:
                if file.endswith('.parquet'):
                    file_path = os.path.join(root, file)
                    try:
                        import pyarrow.parquet as pq
                        table = pq.read_table(file_path)
                        df = table.to_pandas()
                        for _, row in df.iterrows():
                            file_contents.append({"path": row['file_path'], "content": row['file_content']})
                    except Exception as e:
                        logger.info(f"Error reading {file_path}: {e}")
    else:
        for root, _, files in os.walk(repo_path):
            for file in files:
                if file_extensions is None or any(file.endswith(ext) for ext in file_extensions):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            file_contents.append({"path": file_path, "content": content})
                    except Exception as e:
                        logger.info(f"Error reading {file_path}: {e}")
    return file_contents
def semantic_chunking(contents, chunk_size=512, chunk_overlap=50, repo_path=None):
    # splitter = RecursiveCharacterTextSplitter(
    #     chunk_size=chunk_size,
    #     chunk_overlap=chunk_overlap,
    #     separators=["\n\n", "\n", " ", ""]
    # )
    chunker = get_chunker(
        "gpt-3.5-turbo",
        chunking_type="code",
        max_tokens=chunk_size,
        tree_sitter_language="java",  # required for code chunking
        trim=False,
        overlap=chunk_overlap,
    )
    chunks = []
    chunk_dict = {}
    for item in contents:
        # splits = splitter.split_text(item["content"])
        splits = chunker.chunks(item["content"])
        file_chunks = {}
        i = 0
        while i < len(splits):
            chunk = splits[i]
            j = i
            while len(chunk) < 1000 or "\n" not in chunk.strip():
                if j+1 < len(splits):
                    chunk += splits[j+1]
                    j += 1
                else:
                    break
            file_chunks[i] = {
                "file": item["path"],
                "chunk_index": i,
                "chunk": f"// filepath: {item['path'].replace(repo_path, '') if repo_path else item['path']}\n {chunk}"
            }
            chunks.append({
                "file": item["path"],
                "chunk_index": i,
                "chunk": f"// filepath: {item['path'].replace(repo_path, '') if repo_path else item['path']}\n {chunk}"
            })
            i = j + 1
        chunk_dict[item["path"]] = file_chunks
    return chunks, chunk_dict

def rerank_chunks(query, chunks, topk=0, timeout=600):
    if topk == 0:
        topk = len(chunks)
    else:
        topk = min(topk, len(chunks))
    url = ""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('EMBED_API_KEY')}"
    }

    data = {
        "query": f'<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n<Instruct>: Given a web search query, retrieve relevant passages that answer the query\n<Query>: {query}\n',
        "documents": [chunk["chunk"] for chunk in chunks],
    }
    response = requests.post(url, headers=headers, json=data, timeout=timeout)
    scores = response.json().get("results", [])
    reranked_chunks = []
    for score in scores:
        reranked_chunks.append(chunks[score["index"]])
    return reranked_chunks[:topk]


def robust_post(url, headers, json, max_retries=3, timeout=600):
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=json, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.info(f"Request failed (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(2 ** attempt)
    raise RuntimeError("All attempts to contact the API failed.")

def embed_chunks(chunks, embedder=None):
    if embedder:
        texts = [chunk["chunk"] for chunk in chunks]
        embeddings = embedder.embed_documents(texts)
        for i, emb in enumerate(embeddings):
            chunks[i]["embedding"] = emb
        return chunks

    url = ""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('EMBED_API_KEY')}"
    }
    max_chunks = 256
    chunk_lists = []
    n = len(chunks)
    num_parts = (n + max_chunks - 1) // max_chunks  # Ceiling division

    # Split chunks into num_parts sublists
    for part in range(num_parts):
        start = part * max_chunks
        end = min(start + max_chunks, n)
        chunk_lists.append(chunks[start:end])

    embeddings = []
    for idx, chunk_sublist in enumerate(chunk_lists):
        if not chunk_sublist:
            continue
        data = {"input": [chunk["chunk"] for chunk in chunk_sublist]}
        response = robust_post(url, headers, data, max_retries=3)
        for i, emb in enumerate(response.json()["data"]):
            chunk_sublist[i]["embedding"] = emb["embedding"]
        embeddings.extend(chunk_sublist)

    # Put embeddings back in the original order
    embeddings_sorted = sorted(embeddings, key=lambda x: (x["file"], x["chunk_index"]))
    # Update original chunks with embeddings
    for i, emb_chunk in enumerate(embeddings_sorted):
        chunks[i]["embedding"] = emb_chunk["embedding"]
    return chunks
def embed_query(query, embedder=None):
    if embedder:
        return embedder.embed_query(query)
    url = ""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('EMBED_API_KEY')}"
    }
    data = {"input": query}
    response = requests.post(url, headers=headers, json=data)
    return response.json()["data"][0]["embedding"]
def cache_embeddings(chunks, cache_path):
    if os.path.exists(cache_path):
        return
    with open(cache_path, "wb") as f:
        pickle.dump(chunks, f)

def load_cached_embeddings(cache_path):
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return pickle.load(f)
        
if __name__ == "__main__":
    filepath = sys.argv[1]
    task_num = sys.argv[2]
    # Load credentials from credentials.json if it exists
    credentials_path = os.path.join(os.path.dirname(__file__), "credentials.json")
    if os.path.exists(credentials_path):
        try:
            with open(credentials_path, "r") as f:
                credentials = json.load(f)
                if "EMBED_API_KEY" in credentials:
                    os.environ["EMBED_API_KEY"] = credentials["EMBED_API_KEY"]
                    logging.info("EMBED_API_KEY loaded from credentials.json")
        except Exception as e:
            logging.warning(f"Failed to load credentials.json: {e}")
    repo_path = "/home/azureuser/repoclassbench/temp/java/original_repo/"
    repo_name = filepath.replace(repo_path, "").split("/")[0]
    file_extensions = [".java"]
    filepath = os.path.join(repo_path, filepath)
    with open(filepath, "r", encoding="utf-8") as f:
        java_file_str = f.read()
    files = read_repo_files(repo_path+repo_name, file_extensions)
    chunks, chunk_dict = semantic_chunking(files)
    symbolic_chunks = retrieve_symbolic_chunks(java_file_str, chunks, repo_path)
    semantic_chunks = retrieve_semantic_chunks(java_file_str, chunks, chunk_dict, repo_path, repo_name, filepath, topk=50)
    # ranked_chunks = rerank_chunks(java_file_str, relevant_chunks)
    ranked_chunks = rerank_chunks(java_file_str, semantic_chunks, topk=10) + rerank_chunks(java_file_str, symbolic_chunks)
    logger.info(len(ranked_chunks))
    for chunk in ranked_chunks:
        logger.info(f"File: {chunk['file']}, Chunk Index: {chunk['chunk_index']}")

    output_dir = "/home/azureuser/repoclassbench/repoclassbench/rcb_java/temp/cc_top50-10/run0"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{task_num}.txt")
    with open(output_path, "w", encoding="utf-8") as out_f:
        for chunk in ranked_chunks:
            out_f.write(f"File: {chunk['file']}, Chunk Index: {chunk['chunk_index']}\n")
            out_f.write(chunk['chunk'])
            out_f.write("\n\n")    
