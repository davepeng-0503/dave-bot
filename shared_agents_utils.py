#!/usr/bin/env python
import logging
import os
import subprocess
from typing import Callable, Dict, List, Optional

from dotenv import load_dotenv
from google.genai.types import HarmBlockThreshold, HarmCategory, SafetySettingDict
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

# --- Configuration ---
CONTEXT_SIZE_LIMIT = 200000


# --- File Utilities ---

def get_git_files(directory: str) -> List[str]:
    """Gets the list of files tracked by Git."""
    try:
        logging.info(f"🔍 Searching for git files in: {directory}")
        result = subprocess.run(
            ["git", "ls-files"], cwd=directory, capture_output=True, text=True, check=True
        )
        files = result.stdout.strip().split("\n")
        logging.info(f"✅ Found {len(files)} files tracked by git.")
        return files
    except FileNotFoundError:
        logging.error("❌ 'git' command not found. Is Git installed and in your PATH?")
        return []
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ Error executing 'git ls-files': {e.stderr}")
        return []


def read_file_content(directory: str, file_path: str) -> Optional[str]:
    """Safely reads the content of a single file."""
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


def write_file_content(directory: str, file_path: str, content: str):
    """Writes content to a file, creating directories if necessary."""
    full_path = os.path.join(directory, file_path)
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"✅ Successfully wrote changes to {full_path}")
    except Exception as e:
        logging.error(f"❌ Error writing to file {full_path}: {e}")


# --- Base AI Agent ---

class BaseAiAgent:
    """A base class for AI agents, handling API key and model configuration."""

    def __init__(self):
        """Initializes the agent and loads the API key."""
        load_dotenv()
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is not set. Please create a .env file and add it.")

    def _get_gemini_model(self, model_name: str, temperature: float = 0.2) -> GoogleModel:
        """Configures and returns a specific Gemini model instance."""
        if self.api_key is None:
            raise ValueError("API key is not set. Please set GOOGLE_API_KEY in your environment variables.")

        return GoogleModel(
            model_name,
            provider=GoogleProvider(
                api_key=self.api_key,
            ),
            settings={
                "temperature": temperature,
            },
        )

    def get_safety_settings(self) -> List[SafetySettingDict]:
        """Returns safety settings to block no harm categories."""
        harm_categories: List[HarmCategory] = [
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            HarmCategory.HARM_CATEGORY_HARASSMENT,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
        ]
        return [
            SafetySettingDict(category=cat, threshold=HarmBlockThreshold.BLOCK_NONE)
            for cat in harm_categories
        ]

    def summarize_code(self, file_path: str, code_content: str) -> str:
        """Summarizes a single file's code content."""
        system_prompt = """
You are an expert code analyst. Your task is to summarize the provided code. 
Focus on the file's primary purpose, its key functions, classes, and their responsibilities. 
Mention any important logic or side effects. The summary should be concise and informative.
"""
        prompt = f"Please summarize the following code from the file `{file_path}`:"
        summarizer_agent = Agent(
            self._get_gemini_model("gemini-2.5-flash"),
            output_type=str,
            system_prompt=system_prompt,
        )
        logging.info(f"📝 Summarizing code in {file_path}...")
        summary = summarizer_agent.run_sync(prompt)
        return summary.output


# --- Context Management ---

def build_context_from_dict(
    context_data: Dict[str, str],
    summarizer: Callable[[str, str], str],
    exclude_file: Optional[str] = None,
) -> str:
    """Builds a context string from a dictionary of file contents, summarizing if too large."""

    files_to_process = {k: v for k, v in context_data.items() if k != exclude_file}

    total_size = sum(len(content) for content in files_to_process.values())

    context_source = (
        f"(from {len(files_to_process)} files, excluding {exclude_file})"
        if exclude_file
        else f"(from {len(files_to_process)} files)"
    )

    if total_size > CONTEXT_SIZE_LIMIT:
        logging.warning(
            f"Context size {context_source} is {total_size} chars, exceeding limit of {CONTEXT_SIZE_LIMIT}. Summarizing..."
        )
        context_parts: List[str] = []
        for file_path, content in files_to_process.items():
            summary = summarizer(file_path, content)
            context_parts.append(f"--- Summary of {file_path} ---\n{summary}\n")
        return "\n".join(context_parts)
    else:
        logging.info(f"Context size {context_source} is {total_size} chars. Using full file contents.")
        context_parts = []
        for file_path, content in files_to_process.items():
            context_parts.append(f"--- Content of {file_path} ---\n{content}\n")
        return "\n".join(context_parts)
