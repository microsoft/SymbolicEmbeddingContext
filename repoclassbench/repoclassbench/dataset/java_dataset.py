# """Java dataset setup"""

# import os
# import zipfile
# import json
# import shutil
# from repoclassbench.evaluator.java_evaluator import (
#     JavaEvaluationMetadata,
#     JavaEvaluator,
# )
# from repoclassbench.dataset.base_dataset import BaseDataset, TaskData
# import gdown


# class JavaDataset(BaseDataset):
#     """Class to load the Java dataset."""

#     def __init__(self, specification: str, delete_relatives: bool) -> None:
#         self.specification = specification
#         self.delete_relatives = delete_relatives
#         self.data = json.load(open("data/input/java_data.json", "r"))
#         self._download_data()
#         ## Extract jdk and maven

#         os.makedirs("external/java",exist_ok=True)

#         if not os.path.exists("external/java/jdk-17.0.6"):
#             if not os.path.exists("external/java/jdk-17.0.6.zip"):
#                 data_url = "https://drive.google.com/uc?id=1HIJICJgQQvM_LzbSVRdBlQyiD_kY5BNc"
#                 gdown.download(data_url, "external/java/jdk-17.0.6.zip", quiet=False)            
#             with zipfile.ZipFile("external/java/jdk-17.0.6.zip", "r") as zip_ref:
#                 zip_ref.extractall("external/java")
        
#         if not os.path.exists("external/java/apache-maven-3.8.7"):
#             if not os.path.exists("external/java/apache-maven-3.8.7.zip"):
#                 data_url = "https://drive.google.com/uc?id=1JFzF2oAzS8D31fhtpn3uIWhhWJTGG-5i"
#                 gdown.download(data_url, "external/java/apache-maven-3.8.7.zip", quiet=False)                        
#             with zipfile.ZipFile(
#                 "external/java/apache-maven-3.8.7.zip", "r"
#             ) as zip_ref:
#                 zip_ref.extractall("external/java")
#         ## Give permissions
#         for root, dirs, files in os.walk("external/java"):
#             for d in dirs:
#                 os.chmod(
#                     os.path.join(root, d), 0o777
#                 )  # Set permissions for directories
#             for f in files:
#                 os.chmod(os.path.join(root, f), 0o777)  # Set permissions for files

#     def _download_data(self) -> None:
#         if os.path.exists("temp/java/original_repo"):
#             return
        
#         os.makedirs("temp/java",exist_ok=True)

#         data_url = "https://drive.google.com/uc?id=16ZeWM_wKfeBfm7rvsBnksbVJZuLAZ1yo"
#         gdown.download(data_url, "temp/java/java_repos.zip", quiet=False)

#         extract_dir = "temp/java"
#         with zipfile.ZipFile("temp/java/java_repos.zip", "r") as zip_ref:
#             zip_ref.extractall(extract_dir)

#         extracted_folder_path = os.path.join(extract_dir, "LLMTools_dataset")
#         new_folder_name = os.path.join(extract_dir, "original_repo")
#         os.rename(extracted_folder_path, new_folder_name)

#     def __len__(self) -> int:
#         return len(self.data)

#     def get_instance_and_setup_env(self, i: int) -> TaskData:
#         data_instance = self.data[i]
#         if self.delete_relatives:
#             raise NotImplementedError("Not implemented yet")
        
#         ## Delete the working repo
#         if os.path.exists(f"temp/java/working_repo{i}"):
#             shutil.rmtree(f"temp/java/working_repo{i}")

#         ## Copy the original repo to working repo
#         shutil.copytree(
#             "temp/java/original_repo/" + data_instance["repo_metadata"]["repo_name"],
#             f"temp/java/working_repo{i}/" + data_instance["repo_metadata"]["repo_name"],
#             dirs_exist_ok=True,
#         )

#         repo_path = f"temp/java/working_repo{i}/" + data_instance["repo_metadata"]["repo_name"]
#         test_file_path = os.path.join(
#             f"temp/java/working_repo{i}/",
#             data_instance["evaluation_metadata"]["test_file"],
#         )
        
#         # Get absolute paths for test file and repo
#         test_file_path_abs = os.path.abspath(test_file_path)
#         repo_path_abs = os.path.abspath(repo_path)
        
#         # Extract the test file path relative to the repo root
#         # The test_file includes the repo name, so we need to remove it
#         test_file_in_json = data_instance["evaluation_metadata"]["test_file"]
#         repo_name = data_instance["repo_metadata"]["repo_name"]
#         if test_file_in_json.startswith(repo_name + "/"):
#             test_file_relative = test_file_in_json[len(repo_name) + 1:]
#         else:
#             test_file_relative = test_file_in_json
        
#         test_file_in_repo = os.path.join(repo_path_abs, test_file_relative)
        
#         ## Set up Maven and Java paths
#         maven_bin = os.path.join(os.path.dirname(__file__), "../../external/java/apache-maven-3.8.7/bin/mvn")
#         java_home = os.path.join(os.path.dirname(__file__), "../../external/java/jdk-17.0.6")
#         java_home_abs = os.path.abspath(java_home)
#         javac_bin = os.path.join(java_home_abs, "bin/javac")
        
#         # Set up environment with JAVA_HOME
#         maven_env = os.environ.copy()
#         maven_env["JAVA_HOME"] = java_home_abs
        
#         ## Check if this is a multi-module project
#         ## Start from the directory containing the test file and look for parent pom.xml files
#         test_file_dir = os.path.dirname(test_file_in_repo)
#         # Go up until we find a pom.xml (the module containing the test)
#         current_dir = test_file_dir
#         module_root = repo_path_abs
#         while current_dir != repo_path_abs and current_dir.startswith(repo_path_abs):
#             if os.path.exists(os.path.join(current_dir, "pom.xml")):
#                 module_root = current_dir
#                 break
#             current_dir = os.path.dirname(current_dir)
        
#         # Now look for parent modules
#         maven_root = module_root
#         current_dir = module_root
#         while True:
#             parent_dir = os.path.dirname(current_dir)
#             parent_pom = os.path.join(parent_dir, "pom.xml")
#             # Check if parent has pom.xml and is still within the working repo
#             if os.path.exists(parent_pom) and f"working_repo{i}" in parent_dir:
#                 # Check if parent pom has <modules> tag
#                 try:
#                     with open(parent_pom, 'r') as f:
#                         if '<modules>' in f.read():
#                             maven_root = parent_dir
#                             current_dir = parent_dir
#                             continue
#                 except:
#                     pass
#             break
        
#         if maven_root != repo_path_abs:
#             print(f"Detected multi-module project for task {i}")
#             print(f"  Module root: {module_root}")
#             print(f"  Maven root: {maven_root}")
        
#         ## Compile main code and tests BEFORE deleting ground truth
#         import subprocess
        
#         print(f"Compiling main code and tests for task {i} (ground truth still intact)...")
        
#         # First ensure main code is compiled
#         main_compile = subprocess.run(
#             [maven_bin, "compile"],
#             cwd=maven_root,
#             capture_output=True,
#             text=True,
#             env=maven_env
#         )
        
#         if main_compile.returncode != 0:
#             print(f"Warning: Main compilation failed for task {i}: {main_compile.stderr[:500]}")
        
#         # Try to compile all tests with Maven
#         test_class = data_instance["evaluation_metadata"]["test_class_name"]
#         compile_result = subprocess.run(
#             [maven_bin, "test-compile"],
#             cwd=maven_root,
#             capture_output=True,
#             text=True,
#             env=maven_env
#         )
        
#         compilation_successful = False
        
#         if compile_result.returncode == 0:
#             compilation_successful = True
#             print(f"Maven test compilation succeeded for task {i}")
#         else:
#             print(f"Maven test compilation failed for task {i}, trying javac fallback...")
#             print(f"Maven stderr (truncated): {compile_result.stderr[:500]}")
            
#             # Fallback: Try to compile just the specific test file with javac
#             try:
#                 # First, make sure main code compiled successfully
#                 # For multi-module projects, check the module's target directory
#                 target_classes = os.path.join(module_root, "target/classes")
#                 if not os.path.exists(target_classes) or not os.listdir(target_classes):
#                     print(f"Warning: Main classes not found or empty at {target_classes}")
#                     print(f"Attempting to compile main code for javac fallback...")
#                     main_recompile = subprocess.run(
#                         [maven_bin, "compile", "-DskipTests"],
#                         cwd=maven_root,
#                         capture_output=True,
#                         text=True,
#                         env=maven_env
#                     )
#                     if main_recompile.returncode != 0:
#                         print(f"Main recompilation failed: {main_recompile.stderr[:300]}")
                
#                 # Build classpath: main classes + test classes + Maven dependencies
#                 target_test_classes = os.path.join(module_root, "target/test-classes")
                
#                 # Ensure test-classes directory exists
#                 os.makedirs(target_test_classes, exist_ok=True)
                
#                 # Get Maven classpath for dependencies
#                 # First, ensure dependencies are downloaded
#                 subprocess.run(
#                     [maven_bin, "dependency:resolve"],
#                     cwd=maven_root,
#                     capture_output=True,
#                     text=True,
#                     env=maven_env
#                 )
                
#                 cp_temp_file = f"/tmp/cp_temp_{i}.txt"
#                 cp_result = subprocess.run(
#                     [maven_bin, "dependency:build-classpath", "-DincludeScope=test", f"-Dmdep.outputFile={cp_temp_file}"],
#                     cwd=maven_root,
#                     capture_output=True,
#                     text=True,
#                     env=maven_env
#                 )
                
#                 if cp_result.returncode != 0:
#                     print(f"Warning: dependency:build-classpath failed: {cp_result.stderr[:300]}")
                
#                 classpath_parts = [target_classes, target_test_classes]
                
#                 # Read Maven dependencies classpath if available
#                 if os.path.exists(cp_temp_file):
#                     with open(cp_temp_file, "r") as f:
#                         maven_cp = f.read().strip()
#                         if maven_cp:
#                             classpath_parts.append(maven_cp)
#                             print(f"Added {len(maven_cp.split(':'))} dependencies to classpath")
#                     os.remove(cp_temp_file)
#                 else:
#                     print(f"Warning: Classpath file not created at {cp_temp_file}")
                
#                 classpath = ":".join(classpath_parts)
#                 print(f"Final classpath has {len(classpath_parts)} parts")
                
#                 # Debug: Check if key classes exist
#                 if os.path.exists(target_classes):
#                     class_count = sum([len(files) for r, d, files in os.walk(target_classes) if files])
#                     print(f"Found {class_count} compiled main classes")
#                 else:
#                     print(f"Warning: target/classes directory doesn't exist!")
                
#                 # Compile the specific test file with javac using absolute path
#                 print(f"Attempting javac with test file: {test_file_in_repo}")
#                 print(f"Using classpath length: {len(classpath)} characters")
#                 javac_result = subprocess.run(
#                     [javac_bin, "-cp", classpath, "-d", target_test_classes, test_file_in_repo],
#                     cwd=repo_path_abs,
#                     capture_output=True,
#                     text=True
#                 )
                
#                 if javac_result.returncode == 0:
#                     compilation_successful = True
#                     print(f"javac compilation succeeded for task {i}")
#                 else:
#                     print(f"javac compilation also failed for task {i}")
#                     print(f"javac stderr (truncated): {javac_result.stderr[:500]}")
#             except Exception as e:
#                 print(f"Exception during javac fallback for task {i}: {str(e)}")
        
#         ## NOW delete ground truth from working repo (after compilation)
#         ## This ensures tests can be compiled even though they test the ground truth class
#         print(f"Deleting ground truth for task {i}...")
#         with open(f"temp/java/working_repo{i}/" + data_instance["file"], "w") as file:
#             pass
        
#         ## Also delete the compiled ground truth .class file if it exists
#         ## This forces the agent to recompile their implementation
#         ground_truth_file_relative = "/".join(data_instance["file"].split("/")[1:])  # Remove repo name
#         class_file_relative = ground_truth_file_relative.replace("src/main/java/", "target/classes/").replace(".java", ".class")
#         compiled_class_path = os.path.join(repo_path_abs, class_file_relative)
#         if os.path.exists(compiled_class_path):
#             os.remove(compiled_class_path)
#             print(f"Removed compiled ground truth class file for task {i}")
        
#         ## Only delete the test source file if compilation was successful
#         if compilation_successful:
#             if os.path.exists(test_file_in_repo):
#                 os.remove(test_file_in_repo)
#                 print(f"Removed test source file for task {i}")
#         else:
#             print(f"Keeping test source file for task {i} due to compilation failure")

#         ## Read ground truth
#         with open("temp/java/original_repo/" + data_instance["file"], "r") as file:
#             ground_truth = file.read()
        
#         return TaskData(
#             file="/".join(data_instance["file"].split("/")[1:]),
#             class_name=data_instance["class_name"],
#             description=(
#                 data_instance["detailed_description"]
#                 if self.specification == "detailed"
#                 else data_instance["sketchy_description"]
#             ),
#             evaluator=None,
#             repo_dir=repo_path,
#             repo_metadata=data_instance["repo_metadata"],
#             ground_truth=ground_truth,
#             test_file=data_instance["evaluation_metadata"]["test_file"],
#             test_class_name=data_instance["evaluation_metadata"]["test_class_name"],
#             evaluation_metadata=None,
#         )
"""Java dataset setup"""

import os
import zipfile
import json
import shutil
from repoclassbench.evaluator.java_evaluator import (
    JavaEvaluationMetadata,
    JavaEvaluator,
)
from repoclassbench.dataset.base_dataset import BaseDataset, TaskData
import gdown


class JavaDataset(BaseDataset):
    """Class to load the Java dataset."""

    def __init__(self, specification: str, delete_relatives: bool) -> None:
        self.specification = specification
        self.delete_relatives = delete_relatives
        self.data = json.load(open("data/input/java_data.json", "r"))
        self._download_data()
        ## Extract jdk and maven

        os.makedirs("external/java",exist_ok=True)

        if not os.path.exists("external/java/jdk-17.0.6"):
            if not os.path.exists("external/java/jdk-17.0.6.zip"):
                data_url = "https://drive.google.com/uc?id=1HIJICJgQQvM_LzbSVRdBlQyiD_kY5BNc"
                gdown.download(data_url, "external/java/jdk-17.0.6.zip", quiet=False)            
            with zipfile.ZipFile("external/java/jdk-17.0.6.zip", "r") as zip_ref:
                zip_ref.extractall("external/java")
        
        if not os.path.exists("external/java/apache-maven-3.8.7"):
            if not os.path.exists("external/java/apache-maven-3.8.7.zip"):
                data_url = "https://drive.google.com/uc?id=1JFzF2oAzS8D31fhtpn3uIWhhWJTGG-5i"
                gdown.download(data_url, "external/java/apache-maven-3.8.7.zip", quiet=False)                        
            with zipfile.ZipFile(
                "external/java/apache-maven-3.8.7.zip", "r"
            ) as zip_ref:
                zip_ref.extractall("external/java")
        ## Give permissions
        for root, dirs, files in os.walk("external/java"):
            for d in dirs:
                os.chmod(
                    os.path.join(root, d), 0o777
                )  # Set permissions for directories
            for f in files:
                os.chmod(os.path.join(root, f), 0o777)  # Set permissions for files

    def _download_data(self) -> None:
        if os.path.exists("temp/java/original_repo"):
            return
        
        os.makedirs("temp/java",exist_ok=True)

        data_url = "https://drive.google.com/uc?id=16ZeWM_wKfeBfm7rvsBnksbVJZuLAZ1yo"
        gdown.download(data_url, "temp/java/java_repos.zip", quiet=False)

        extract_dir = "temp/java"
        with zipfile.ZipFile("temp/java/java_repos.zip", "r") as zip_ref:
            zip_ref.extractall(extract_dir)

        extracted_folder_path = os.path.join(extract_dir, "LLMTools_dataset")
        new_folder_name = os.path.join(extract_dir, "original_repo")
        os.rename(extracted_folder_path, new_folder_name)

    def __len__(self) -> int:
        return len(self.data)

    def get_instance_and_setup_env(self, i: int) -> TaskData:
        data_instance = self.data[i]
        if self.delete_relatives:
            raise NotImplementedError("Not implemented yet")
        
        ## Delete the working repo
        if os.path.exists(f"temp/java/working_repo{i}"):
            shutil.rmtree(f"temp/java/working_repo{i}")

        ## Copy the original repo to working repo
        # os.chmod("temp/java/original_repo", 0o777)
        # os.makedirs("temp/java/working_repo", exist_ok=True)
        shutil.copytree(
            "temp/java/original_repo/" + data_instance["repo_metadata"]["repo_name"],
            f"temp/java/working_repo{i}/" + data_instance["repo_metadata"]["repo_name"],
            dirs_exist_ok=True,
        )
        # for dirpath, dirnames, filenames in os.walk("temp/java/working_repo"):
        #     os.chmod(dirpath, 0o777)
        #     for filename in filenames:
        #         os.chmod(os.path.join(dirpath, filename), 0o777)

        ## Delete the test code. This should only be available during evaluation and not in the working repo.
        for file in os.walk(
            f"temp/java/working_repo{i}/" + data_instance["repo_metadata"]["repo_name"]
        ):
            if "src/test" in file and ".java" in file:
                os.chmod(file, 0o333)
                # with open(file, "w") as f:
                #     pass

        ## Delete ground truth from working repo
        with open(f"temp/java/working_repo{i}/" + data_instance["file"], "w") as file:
            pass

        ## Read ground truth
        with open("temp/java/original_repo/" + data_instance["file"], "r") as file:
            ground_truth = file.read()

        return TaskData(
            file="/".join(data_instance["file"].split("/")[1:]),
            class_name=data_instance["class_name"],
            description=(
                data_instance["detailed_description"]
                if self.specification == "detailed"
                else data_instance["sketchy_description"]
            ),
            # evaluator=JavaEvaluator(
            #     repo_name=data_instance["repo_metadata"]["repo_name"],
            #     file_name=data_instance["file"],
            #     evaluation_metadata=JavaEvaluationMetadata(
            #         **data_instance["evaluation_metadata"]
            #     ),
            # ),
            evaluator=None,
            repo_dir=f"temp/java/working_repo{i}/"
            + data_instance["repo_metadata"]["repo_name"],
            repo_metadata=data_instance["repo_metadata"],
            ground_truth=ground_truth,
            test_file=data_instance["evaluation_metadata"]["test_file"],
            test_class_name=data_instance["evaluation_metadata"]["test_class_name"],
            evaluation_metadata=None
        )
