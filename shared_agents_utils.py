#!/usr/bin/env python
"""
Utilities shared across different AI agents, including file operations,
base AI agent configuration, and context management.
"""
import hashlib
import logging
import os
import subprocess
from typing import Callable, Dict, List, Optional

from dotenv import load_dotenv
from google.genai.types import HarmBlockThreshold, HarmCategory, SafetySettingDict
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

# --- Configuration ---
CONTEXT_SIZE_LIMIT = (
    200000  # The maximum size of context to be sent to the LLM in characters.
)

# A list of harm categories to be disabled in the safety settings for the Google AI model.
# This allows the model to process and generate code that might otherwise be flagged.
DISABLED_HARM_CATEGORIES: List[HarmCategory] = [
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    HarmCategory.HARM_CATEGORY_HARASSMENT,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH,
]


# --- File Utilities ---


def get_git_files(directory: str) -> List[str]:
    """
    Gets the list of all files tracked by Git in the specified directory.

    Args:
        directory: The path to the git repository.

    Returns:
        A list of file paths relative to the repository root.
        Returns an empty list if git is not found or an error occurs.
    """
    try:
        logging.info(f"🔍 Searching for git-tracked files in: {directory}")
        command = ["git", "ls-files"]
        result = subprocess.run(
            command,
            cwd=directory,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )

        stdout = result.stdout.strip()
        if not stdout:
            logging.warning("Git command 'ls-files' returned no files.")
            return []

        files = stdout.split("\n")
        logging.info(f"✅ Found {len(files)} files tracked by git.")
        return files
    except FileNotFoundError:
        logging.error("❌ 'git' command not found. Is Git installed and in your PATH?")
        return []
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Error executing 'git ls-files': {e.stderr}")
        return []
    except Exception as e:
        logging.error(f"An unexpected error occurred in get_git_files: {e}")
        return []


def read_file_content(directory: str, file_path: str) -> Optional[str]:
    """
    Safely reads the content of a single file.

    Args:
        directory: The base directory of the project.
        file_path: The relative path to the file.

    Returns:
        The content of the file as a string, or None if an error occurs.
    """
    if not file_path:
        logging.warning("read_file_content received an empty file_path.")
        return None
    full_path = os.path.join(directory, file_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logging.warning(f"⚠️ File not found while reading: {full_path}")
        return None
    except Exception as e:
        logging.error(f"❌ Error reading file {full_path}: {e}")
        return None


def write_file_content(directory: str, file_path: str, content: str) -> None:
    """
    Writes content to a file, creating parent directories if they don't exist.

    Args:
        directory: The base directory of the project.
        file_path: The relative path to the file.
        content: The string content to write to the file.
    """
    full_path = os.path.join(directory, file_path)
    try:
        # Ensure the parent directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"✅ Successfully wrote changes to {full_path}")
    except Exception as e:
        logging.error(f"❌ Error writing to file {full_path}: {e}")


# --- Base AI Agent ---


class BaseAiAgent:
    """
    A base class for AI agents, handling API key loading, model configuration,
    and common AI-related tasks like summarization.
    """
    summarizer_agent: Agent
    api_key: str
    summaries_cache: Dict[str, str]

    def __init__(self):
        """
        Initializes the agent by loading the Google API key and pre-creating
        a summarizer agent instance for reuse.
        """
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY") or ""
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY is not set. Please create a .env file and add it."
            )
        self.summaries_cache = {}

        # Create a cached summarizer agent for performance.
        summarizer_system_prompt = """
You are an expert code analyst. Your task is to summarize the provided code.
Focus on the file's primary purpose, its key functions, classes, and their responsibilities.
Mention any important logic or side effects. The summary should be concise and informative.
"""
        self.summarizer_agent = Agent(
            self._get_gemini_model("gemini-2.5-flash"),
            output_type=str,
            system_prompt=summarizer_system_prompt,
        )

    def _get_gemini_model(
        self, model_name: str, temperature: float = 0.2
    ) -> GoogleModel:
        """
        Configures and returns a specific Gemini model instance.

        Args:
            model_name: The name of the Gemini model to use (e.g., 'gemini-1.5-pro').
            temperature: The creativity of the model, from 0.0 to 1.0.

        Returns:
            An instance of the configured GoogleModel.
        """
        # The API key is validated in the constructor, so no need to check here.
        return GoogleModel(
            model_name,
            provider=GoogleProvider(api_key=self.api_key),
            settings={"temperature": temperature},
        )

    def get_safety_settings(self) -> List[SafetySettingDict]:
        """
        Returns safety settings to disable blocking for specific harm categories.
        This is often necessary for code generation tasks where code might be
        misinterpreted as harmful content.

        Returns:
            A list of safety setting dictionaries for the Google API.
        """
        return [
            SafetySettingDict(category=cat, threshold=HarmBlockThreshold.BLOCK_NONE)
            for cat in DISABLED_HARM_CATEGORIES
        ]

    def summarize_code(self, file_path: str, code_content: str) -> str:
        """
        Summarizes a single file's code content using a cached AI model.
        Caches the summary against a hash of the content to avoid re-summarizing
        the same content.

        Args:
            file_path: The path of the file being summarized (for context).
            code_content: The actual code content to summarize.

        Returns:
            A string containing the AI-generated summary.
        """
        content_hash = hashlib.md5(code_content.encode("utf-8")).hexdigest()
        if content_hash in self.summaries_cache:
            logging.info(f"📝 Reusing cached summary for {file_path}")
            return self.summaries_cache[content_hash]

        prompt = f"Please summarize the following code from the file `{file_path}`:\n\n{code_content}"

        logging.info(f"📝 Summarizing code in {file_path}...")
        summary = self.summarizer_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(
                google_safety_settings=self.get_safety_settings()
            ),
        )
        summary_output = summary.output
        self.summaries_cache[content_hash] = summary_output
        return summary_output


# --- Context Management ---


def build_context_from_dict(
    context_data: Dict[str, str],
    summarizer: Callable[[str, str], str],
    exclude_file: Optional[str] = None,
) -> str:
    """
    Builds a context string from a dictionary of file contents.

    If the total size of the content exceeds a defined limit, it uses the
    provided summarizer function to shorten the content of each file. Otherwise,
    it includes the full file content.

    Args:
        context_data: A dictionary mapping file paths to their content.
        summarizer: A callable function that takes a file path and content
                    and returns a summary string.
        exclude_file: An optional file path to exclude from the context.

    Returns:
        A single string formatted for use as context in an LLM prompt.
    """
    files_to_process = {
        path: content
        for path, content in context_data.items()
        if path != exclude_file and content
    }
    if not files_to_process:
        return "No context files provided."

    total_size = sum(len(content) for content in files_to_process.values())

    context_source_info = (
        f"(from {len(files_to_process)} files, excluding {exclude_file})"
        if exclude_file
        else f"(from {len(files_to_process)} files)"
    )

    context_parts: List[str] = []
    if total_size > CONTEXT_SIZE_LIMIT:
        logging.warning(
            f"Context size {context_source_info} is {total_size} chars, "
            f"exceeding limit of {CONTEXT_SIZE_LIMIT}. Summarizing..."
        )
        for file_path, content in files_to_process.items():
            summary = summarizer(file_path, content)
            context_parts.append(f"--- Summary of {file_path} ---\n{summary}\n")
    else:
        logging.info(
            f"Context size {context_source_info} is {total_size} chars. "
            "Using full file contents."
        )
        for file_path, content in files_to_process.items():
            context_parts.append(f"--- Content of {file_path} ---\n{content}\n")

    return "\n".join(context_parts)
