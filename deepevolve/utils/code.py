from pathlib import Path
import os
import logging
import shutil

import re
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

def get_files_and_code(
    local_path, online_link, workspace_dir, code_extension=".py"
) -> Tuple[Dict[str, str], str]:
    """
    Get all program files from a directory or a single file path.

    Args:
        local_path: local path to the code
        online_link: online link to the code
        workspace_dir: Directory for outputs
        code_extension: File extension to look for (default: .py)

    Returns:
        A tuple of:
        - dict: {filename (relative): source code}
        - str: concatenated code with filename markers
    """
    if local_path is None and online_link is None:
        logger.error("No local path or online link provided")
        return {}, ""

    if local_path:
        path = Path(local_path)

    elif online_link:
        from git import Repo
        # online should be a github repo url like https://github.com/username/repo_name
        # download the github repo directly to the initial_code folder
        # ask user to confirm the download

        # Ask for user confirmation before downloading
        print(f"About to download repository from: {online_link}")
        confirmation = (
            input("Do you want to proceed with downloading this repository? (y/N): ")
            .strip()
            .lower()
        )

        if confirmation not in ["y", "yes"]:
            logger.info("Repository download cancelled by user")
            return {}, ""

        try:
            # Create seed directory if it doesn't exist
            seed_dir = os.path.join(workspace_dir, "initial_code")
            os.makedirs(seed_dir, exist_ok=True)

            # Create a temporary directory for cloning
            temp_dir = os.path.join(workspace_dir, "temp_clone")
            os.makedirs(temp_dir, exist_ok=True)

            # Extract repo name from URL
            repo_name = online_link.split("/")[-1]
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            temp_repo_path = os.path.join(temp_dir, repo_name)

            # Clone the repository to temp dir
            if os.path.exists(temp_repo_path):
                shutil.rmtree(temp_repo_path)

            logger.info(f"Cloning repository from {online_link} to temporary location")
            Repo.clone_from(online_link, temp_repo_path)

            # Copy all contents from the temp repo to the seed directory
            for item in os.listdir(temp_repo_path):
                source = os.path.join(temp_repo_path, item)
                dest = os.path.join(seed_dir, item)

                if os.path.isdir(source):
                    if os.path.exists(dest):
                        shutil.rmtree(dest)
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)

            # Clean up temp directory
            shutil.rmtree(temp_dir)

            logger.info(f"Copied repository contents directly to {seed_dir}")
            path = Path(seed_dir)

        except Exception as e:
            logger.error(f"Failed to clone repository: {e}")
            return {}, ""

    # Search for all code files in the path
    code_files = {}
    if path.is_file():
        if path.suffix == code_extension:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                code = f.read()
                code_files[path.name] = code
    elif path.is_dir():
        for file_path in path.glob(f"**/*{code_extension}"):
            if file_path.is_file() and not file_path.name.startswith("."):
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        relative_path = str(file_path.relative_to(path))
                        code_files[relative_path] = f.read()
                except Exception as e:
                    logger.warning(f"Could not read file {file_path}: {e}")

    # Create concatenated code with filename markers
    concatenated_code = "\n\n".join(
        f"# === {filename} ===\n{code}" for filename, code in code_files.items()
    )

    return code_files, concatenated_code


def save_code_to_files(concatenated_code: str, output_dir: str) -> Dict[str, str]:
    """
    Save concatenated code back to individual files based on filename markers.

    Args:
        concatenated_code: String containing code with filename markers
        output_dir: Directory to save the files to

    Returns:
        dict: {filename: file_path} mapping of saved files
    """
    os.makedirs(output_dir, exist_ok=True)

    # Remove Markdown code block markers like ```python and ```
    cleaned_code = re.sub(r"```[\w]*\n", "", concatenated_code)
    cleaned_code = re.sub(r"```", "", cleaned_code)

    # Match all sections of the form "# === filename ===\n<code...>"
    pattern = re.compile(r"# === (.+?) ===\n(.*?)(?=(?:# === .+? ===\n)|\Z)", re.DOTALL)
    matches = pattern.findall(cleaned_code)

    saved_files = {}

    for filename, code_content in matches:
        filename = filename.strip()
        if not filename:
            continue

        file_path = os.path.join(output_dir, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code_content.lstrip())  # Remove leading whitespace if any
            saved_files[filename] = file_path
            logger.info(f"Saved file: {file_path}")
        except Exception as e:
            logger.error(f"Error saving {filename}: {e}")

    return saved_files


# from https://github.com/codelion/openevolve/blob/main/openevolve/utils/code_utils.py
"""
Utilities for code parsing, diffing, and manipulation
"""

def parse_evolve_blocks(code: str) -> List[Tuple[int, int, str]]:
    """
    Parse evolve blocks from code

    Args:
        code: Source code with evolve blocks

    Returns:
        List of tuples (start_line, end_line, block_content)
    """
    lines = code.split("\n")
    blocks = []

    in_block = False
    start_line = -1
    block_content = []

    for i, line in enumerate(lines):
        if "DEEPEVOLVE-BLOCK-START" in line:
            in_block = True
            start_line = i
            block_content = []
        elif "DEEPEVOLVE-BLOCK-END" in line and in_block:
            in_block = False
            blocks.append((start_line, i, "\n".join(block_content)))
        elif in_block:
            block_content.append(line)

    return blocks


def extract_diffs(diff_text: str) -> List[Tuple[str, str]]:
    # Accept `<<<<<<< SEARCH` or `<<<<<<< <any filename>` as the opening marker
    # The debugger LLM sometimes writes `<<<<<<< infra.rs` instead of `<<<<<<< SEARCH`
    pattern = r"<<<<<<<[^\n]*\n(.*?)=======\n(.*?)>>>>>>> REPLACE"
    blocks = re.findall(pattern, diff_text, re.DOTALL)
    return [(a.rstrip("\n"), b.rstrip("\n")) for a, b in blocks]

def apply_diff(original_code: str, diff_text: str) -> str:
    """
    Apply a diff to the original code

    Args:
        original_code: Original source code
        diff_text: Diff in the SEARCH/REPLACE format

    Returns:
        Modified code
    """
    # Split into lines for easier processing
    original_lines = original_code.split("\n")
    result_lines = original_lines.copy()

    # Extract diff blocks
    diff_blocks = extract_diffs(diff_text)

    # Apply each diff block
    for search_text, replace_text in diff_blocks:
        search_lines = search_text.split("\n")
        replace_lines = replace_text.split("\n")

        # Find where the search pattern starts in the original code
        matched = False
        for i in range(len(result_lines) - len(search_lines) + 1):
            if result_lines[i : i + len(search_lines)] == search_lines:
                result_lines[i : i + len(search_lines)] = replace_lines
                matched = True
                break

        # Fuzzy fallback: if exact match failed, try stripping trailing whitespace
        if not matched:
            stripped_search = [l.rstrip() for l in search_lines]
            for i in range(len(result_lines) - len(search_lines) + 1):
                if [l.rstrip() for l in result_lines[i : i + len(search_lines)]] == stripped_search:
                    result_lines[i : i + len(search_lines)] = replace_lines
                    matched = True
                    break

    # Fallback: if the diff contains a full RUST_CODE replacement, extract and apply it directly
    # This handles cases where the LLM replaces only the Rust content rather than the Python wrapper
    if "RUST_CODE" not in "\n".join(result_lines).replace("\n".join(original_lines), ""):
        rust_code_pattern = re.compile(
            r'RUST_CODE\s*=\s*"""(.*?)"""',
            re.DOTALL
        )
        # Check if diff_text contains a new RUST_CODE assignment
        new_rust_match = rust_code_pattern.search(diff_text)
        if new_rust_match:
            new_rust_content = new_rust_match.group(1)
            # Replace RUST_CODE in the result
            result_str = "\n".join(result_lines)
            result_str = rust_code_pattern.sub(
                f'RUST_CODE = """{new_rust_content}"""',
                result_str,
                count=1
            )
            result_lines = result_str.split("\n")

    result = "\n".join(result_lines)

    # Repair: detect the broken pattern where the LLM wrote a nested `RUST_CODE = """` inside
    # the RUST_CODE string. Python's non-greedy regex (and the Python parser) sees the inner """
    # as terminating the outer string, leaving bare Rust code at Python scope.
    #
    # Detection: the RUST_CODE assignment's content (between the outer """) contains the literal
    # text `RUST_CODE = """`, indicating the LLM wrote a second assignment inside the string.
    # When this happens, the true Rust code starts AFTER that inner `RUST_CODE = """` marker
    # and extends to the last `"""` in the file (which was the intended closing delimiter).
    #
    # Regex captures the first (short, broken) RUST_CODE = """...""" block.
    rust_assign_re = re.compile(r'(?:^|\n)RUST_CODE(?![_A-Z])\s*=\s*"""(.*?)"""', re.DOTALL)
    m = rust_assign_re.search(result)
    if m and 'RUST_CODE' in m.group(1):
        logger.warning("apply_diff: detected nested RUST_CODE assignment inside RUST_CODE string - repairing")
        # The real Rust code starts after the inner `RUST_CODE = """` and runs to the last `"""`
        after_inner = result[m.end():]  # everything after the first (broken) closing """
        # Strip the stray inner RUST_CODE = """ prefix that opened the real content
        real_rust = re.sub(r'^\s*RUST_CODE\s*=\s*"""', '', after_inner, count=1)
        # Strip the trailing """ that closed the real content and any stray DEEPEVOLVE markers after it
        real_rust = re.sub(r'"""\s*(?://[^\n]*)?\s*$', '', real_rust.rstrip())
        # Now reconstruct: replace the broken RUST_CODE block with the correct one
        before_block = result[:m.start()]
        result = before_block + f'\nRUST_CODE = """{real_rust}\n"""\n'

    return result