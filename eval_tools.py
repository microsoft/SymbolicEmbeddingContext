import tiktoken
from langchain.text_splitter import RecursiveCharacterTextSplitter, Language
import os
import requests
import time
import pickle
import numpy as np
import javalang
import re

def read_repo_files(repo_path, file_extensions=None):
    print("Reading repository files...")
    file_contents = []
    for root, _, files in os.walk(repo_path):
        for file in files:
            if file_extensions is None or any(file.endswith(ext) for ext in file_extensions):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        file_contents.append({"path": file_path, "content": content})
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
    return file_contents
def semantic_chunking(contents, chunk_size=512, chunk_overlap=100):
    print("Performing semantic chunking...")
    def token_length(text: str) -> int:
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")
        return len(encoding.encode(text))
    java_splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.JAVA, chunk_size=512, chunk_overlap=50, length_function=token_length
        )
    chunks = []
    chunk_dict = {}
    for item in contents:
        splits = java_splitter.split_text(item["content"])
        file_chunks = {}
        i = 0
        while i < len(splits):
            chunk = splits[i]
            j = i
            file_chunks[j] = {
                "file": item["path"],
                "chunk_index": j,
                "chunk": f"// filepath: {item['path']}\n\n{chunk}"
            }
            chunks.append({
                "file": item["path"],
                "chunk_index": j,
                "chunk": f"// filepath: {item['path']}\n\n{chunk}"
            })
            i += 1
        chunk_dict[item["path"]] = file_chunks
    return chunks, chunk_dict

def rerank_chunks(query, chunks, url, api_key, topk=0, timeout=600):
    print("Reranking chunks...")
    if topk == 0:
        topk = len(chunks)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
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
            print(f"Request failed (attempt {attempt+1}/{max_retries}): {e}")
            print(response.text if 'response' in locals() else "No response received")
            time.sleep(2 ** attempt)
    raise RuntimeError("All attempts to contact the API failed.")

def retrieve_semantic_chunks(query, chunks, chunk_dict, repo_path, repo_name, file_path, cache_path, embed_url, embed_api, topk=10):
    print("Retrieving relevant chunks...")
    cache_path = os.path.join(cache_path, f"{repo_name}.pkl")
    cached_chunks = load_cached_embeddings(cache_path)
    if cached_chunks is not None and len(cached_chunks) == len(chunks):
        chunks = cached_chunks
    else:
        chunks = embed_chunks(chunks, embed_url, embed_api)
        cache_embeddings(chunks, cache_path)

    query_embedding = embed_query(query, embed_url, embed_api)

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
            # Remove embedding from result to save memory
            result_chunk = {k: v for k, v in candidate.items() if k != "embedding"}
            res.append(result_chunk)
            file_set.add((candidate["file"], candidate["chunk_index"]))

    
    # Clear embeddings from chunks to free memory
    for chunk in chunks:
        if "embedding" in chunk:
            del chunk["embedding"]
    
    return res

def embed_chunks(chunks, url, api_key):
    print("Embedding chunks...")
    if "sym" in url:
        input_type="texts"
        url += "?input_type=document"
        output_type="embeddings"
    else:
        input_type="input"
        output_type="data"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    num_parts = 10
    chunk_lists = []
    n = len(chunks)
    part_size = (n + num_parts - 1) // num_parts  # Ceiling division

    # Split chunks into num_parts sublists
    for part in range(num_parts):
        start = part * part_size
        end = min(start + part_size, n)
        chunk_lists.append(chunks[start:end])

    embeddings = []
    for idx, chunk_sublist in enumerate(chunk_lists):
        if not chunk_sublist:
            continue
        data = {input_type: [chunk["chunk"] for chunk in chunk_sublist]}
        response = robust_post(url, headers, data, max_retries=num_parts)
        for i, emb in enumerate(response.json()[output_type]):
            chunk_sublist[i]["embedding"] = emb["embedding"] if output_type == "data" else emb
        embeddings.extend(chunk_sublist)

    # Put embeddings back in the original order
    embeddings_sorted = sorted(embeddings, key=lambda x: (x["file"], x["chunk_index"]))
    # Update original chunks with embeddings
    for i, emb_chunk in enumerate(embeddings_sorted):
        chunks[i]["embedding"] = emb_chunk["embedding"]
    return chunks

def embed_query(query, url, api_key):
    if "sym" in url:
        input_type="texts"
        url += "?input_type=query"
        output_type="embeddings"
    else:
        input_type="input"
        output_type="data"
    print("Embedding query...")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {input_type: query if input_type=="input" else [query]}
    response = requests.post(url, headers=headers, json=data)
    return response.json()["data"][0]["embedding"] if output_type == "data" else response.json()[output_type][0]

def cache_embeddings(chunks, cache_path):
    if os.path.exists(cache_path):
        return
    print(f"Caching embeddings to {cache_path}...")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(chunks, f)

def load_cached_embeddings(cache_path):
    if os.path.exists(cache_path):
        print(f"Loading cached embeddings from {cache_path}...")
        with open(cache_path, "rb") as f:
            return pickle.load(f)


# Symbolic Tools
def parse_java_file(parsed_file):
    tree = parsed_file
    imports = [imp.path for imp in tree.imports]
    method_calls = set()
    class_instantiations = set()
    super_types = set()
    for path, node in tree:
        if isinstance(node, javalang.tree.MethodInvocation):
            method_calls.add(node.member)
        if isinstance(node, javalang.tree.ClassCreator):
            class_instantiations.add(node.type.name)
        if isinstance(node, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
            # Superclass
            if node.extends:
                if isinstance(node.extends, list):
                    for ext in node.extends:
                        super_types.add(ext.name)
                else:
                    super_types.add(node.extends.name)
            # Interfaces
            if node.implements:
                for impl in node.implements:
                    super_types.add(impl.name)
    print(f"Imports: {imports}")
    print(f"Method Calls: {method_calls}")
    print(f"Class Instantiations: {class_instantiations}")
    print(f"Super Types: {super_types}")
    return imports, method_calls, class_instantiations, super_types

def find_repo_files_for_imports(imports, repo_root):
    # Map import paths to file paths in the repo
    import_to_file = set()
    # Collect all .java files in the repo
    repo_java_files = []
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
    # Returns set of method and class/interface/enum names defined in the chunk
    try:
        tree = javalang.parse.parse(chunk_code)
        methods = set()
        types = set()
        for path, node in tree:
            if isinstance(node, javalang.tree.MethodDeclaration):
                methods.add(node.name)
            if isinstance(node, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration, javalang.tree.EnumDeclaration)):
                types.add(node.name)
        if methods or types:
            print(methods, types)
            return methods, types
    except:
        pass  # Fallback to regex below if parsing fails

    # Fallback: regex scan for class/interface/enum declarations
    methods = set()
    types = set()
    # This regex matches 'class', 'interface', or 'enum' followed by a valid Java identifier
    for match in re.finditer(r'\b(class|interface|enum)\s+([A-Za-z_][A-Za-z0-9_]*)', chunk_code):
        types.add(match.group(2))
    print(methods, types)
    return methods, types
def get_package_path(parsed_file, repo_root):
    try:
        tree = parsed_file
        if tree.package:
            package_path = tree.package.name.replace('.', '/')
            return os.path.join(repo_root, 'src', 'main', 'java', package_path)
    except Exception as e:
        print(f"Error parsing package: {e}")
    return None
def retrieve_symbolic_chunks(target_java_code, chunks, chunk_dict, repo_root, file_path):
    parsed_file = javalang.parse.parse(target_java_code)
    imports, method_calls, class_insts, super_types = parse_java_file(parsed_file)
    import_files = find_repo_files_for_imports(imports, repo_root)
    imported_class_names = set(imp.split('.')[-1] for imp in imports)
    referenced_types = class_insts | imported_class_names | super_types

    # Find all files in the same package
    package_dir = get_package_path(parsed_file, repo_root)
    package_files = set()
    if package_dir and os.path.isdir(package_dir):
        for file in os.listdir(package_dir):
            if file.endswith('.java'):
                package_files.add(os.path.join(package_dir, file))

    # Combine import files and package files
    files_to_search = import_files | package_files
    files_to_search.discard(file_path)

    chunk_id_set = set()
    relevant_chunks = []
    for chunk in chunks:
        if chunk['file'] in files_to_search:
            methods, classes = find_definitions_in_chunk(chunk['chunk'])
            if (
                methods & method_calls
                or classes & referenced_types
            ):
                if (chunk['file'], chunk['chunk_index']) not in chunk_id_set:
                    chunk_id_set.add((chunk['file'], chunk['chunk_index']))
                    relevant_chunks.append(chunk)

    return relevant_chunks