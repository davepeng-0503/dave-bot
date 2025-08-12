#!/usr/bin/env python
import argparse
import json
import logging
import os
import subprocess
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from shared_agents_utils import (
    BaseAiAgent,
    build_context_from_dict,
    get_git_files,
    read_file_content,
    write_file_content,
)

# --- Configuration ---
MAX_REANALYSIS_RETRIES = 3

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- Pydantic Models for Code Analysis & Generation ---
class NewFile(BaseModel):
    """Represents a new file that needs to be created for the task."""
    file_path: str = Field(description="The full path for the new file to be created.")
    reasoning: str = Field(description="Brief explanation of why this file is needed.")
    content_suggestions: List[str] = Field(
        default=[],
        description="A list of suggested functions, classes, or other code structures for the new file."
    )

class CodeAnalysis(BaseModel):
    """Represents the initial analysis of the codebase for a given task."""
    relevant_files: List[str] = Field(
        default=[],
        description="A list of existing file paths that are most relevant to read for understanding the context."
    )
    files_to_edit: List[str] = Field(
        default=[],
        description="A list of existing file paths that will likely need to be modified to complete the task."
    )
    files_to_create: List[NewFile] = Field(
        default=[],
        description="A list of new files that should be created to complete the task."
    )
    generation_order: List[str] = Field(
        default=[],
        description="The recommended order to process files (both creating and editing) to satisfy dependencies. For example, create a utility file before editing a file that uses it."
    )
    reasoning: str = Field(
        default="",
        description="A brief, high-level explanation of the overall strategy, why these files were chosen, and why the generation order is correct."
    )

class GitGrepSearchInput(BaseModel):
    """Input model for the git grep search tool."""
    query: str = Field(description="The keyword or regex pattern to search for within the git repository.")

class GeneratedCode(BaseModel):
    """Represents the AI-generated code for a single file."""
    file_path: str = Field(description="The path of the file for which code is being generated.")
    code: str = Field(description="The complete, production-ready source code for the file.")
    reasoning: str = Field(description="A brief explanation of the changes made or the file's purpose.")
    requires_more_context: bool = Field(
        default=False,
        description="Set to true if you cannot generate the code for the CURRENT file due to insufficient context."
    )
    context_request: str = Field(
        default="",
        description="If requires_more_context is true, explain what specific information or files are needed to generate the CURRENT file."
    )
    needed_context_for_future_files: List[str] = Field(
        default=[],
        description="A list of additional file paths that should be added to the context for subsequent file generation steps. Use this even if you were able to generate the current file successfully. Provide file paths from the full list of repository files."
    )


# --- Core Logic for AI Interaction ---
class AiCodeAgent(BaseAiAgent):
    """Handles all interactions with the Gemini AI model."""

    def get_initial_analysis(self, task: str, file_list: List[str], directory: str, app_description: str = "", feedback: Optional[str] = None) -> CodeAnalysis:
        """Runs the agent to get the code analysis, potentially using feedback or a search tool."""
        
        # Tool definition within the method's scope to capture the 'directory' argument
        def git_grep_search_tool(query: str) -> str:
            """
            Performs a case-insensitive 'git grep' search in the codebase to find relevant files.
            Returns a list of files and line numbers containing the query.
            """
            logging.info(f"🛠️ Running git grep search for: '{query}'")
            try:
                result = subprocess.run(
                    ['git', 'grep', '-i', '-n', query],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    check=False # Don't raise error if grep returns 1 (no matches)
                )
                if result.returncode == 0:
                    return f"Git grep results for '{query}':\n{result.stdout}"
                elif result.returncode == 1:
                    return f"No results found for '{query}'."
                else:
                    logging.error(f"Error during git grep: {result.stderr}")
                    return f"Error executing git grep: {result.stderr}"
            except FileNotFoundError:
                logging.error("❌ 'git' command not found. Is Git installed?")
                return "Error: 'git' command not found. Cannot perform search."
            except Exception as e:
                logging.error(f"An unexpected error occurred during git grep: {e}")
                return f"An unexpected error occurred: {e}"

        system_prompt = f"""
You are an expert software developer planning a coding task. Your goal is to analyze a project's file structure 
to determine which files are relevant, which need editing, which new files to create, and the correct order of operations.

**You have access to a tool: `git_grep_search_tool`**.

- **When to use the tool**: Use this tool if the file list is large, or the task description contains specific keywords, function names, or variable names. This helps you pinpoint relevant code. For example, if the task is "add a new endpoint to the user API", a good search query would be "user_api" or "app.route('/api/user'".
- **How to use the tool**: Call the tool with a single `query` string.
- **After using the tool**: Use the search results to populate the `relevant_files` and `files_to_edit` fields accurately.
- **If you don't need the tool**: If the file list is small and you can easily identify the correct files, you don't need to use the tool. Just provide the `CodeAnalysis` directly.

Project Description:
---
{app_description or "No description provided."}
---

Your task is to populate the CodeAnalysis object based on the user's request and the provided file list.

**CRITICAL**: You must determine the correct `generation_order`. This is the most important part of your plan.
List all file paths from `files_to_edit` and `files_to_create` in the specific sequence they should be processed.
The order must respect dependencies. For example, if you create `new_module.py` and then modify `main.py` to import and use it, the `generation_order` MUST be `['new_module.py', 'main.py']`.
Explain your reasoning for this order in the `reasoning` field.
"""
        if feedback:
            system_prompt += f"""
---
IMPORTANT: This is a re-analysis. A previous attempt failed due to insufficient context.
The programmer's feedback was: "{feedback}"
Please adjust your file selection. You might need to use the `git_grep_search_tool` or add more files to `relevant_files`.
---
"""

        prompt = f"""
Full list of files in the repository:
{json.dumps(file_list, indent=2)}

My task is: "{task}"

Please provide your analysis. Use the `git_grep_search_tool` if you need to find specific code snippets.
"""
        analysis_agent = Agent(
            self._get_gemini_model('gemini-2.5-flash'),
            output_type=CodeAnalysis,
            system_prompt=system_prompt,
            tools=[git_grep_search_tool]
        )
        log_message = "🤖 Conducting initial codebase analysis..." if not feedback else f"🔁 Re-analyzing codebase with feedback: {feedback}"
        logging.info(log_message)
        
        google_safety_settings = self.get_safety_settings()
        analysis = analysis_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(
            google_safety_settings=google_safety_settings
            ),
        )
        return analysis.output

    def generate_file_content(self, task: str, context: str, file_path: str, all_repo_files: List[str], generation_order: List[str], original_content: Optional[str] = None, strict: bool = True) -> GeneratedCode:
        """Generates the full code for a given file."""
        action = "editing" if original_content is not None else "creating"
        
        system_prompt = f"""
You are an expert programmer tasked with writing a complete Python file.
Based on the overall task, the provided context from other relevant files, and the original code (if any), 
you will generate the full, production-ready code for the specified file path.

**IMPORTANT RULES**:
1.  Your output must be the complete, raw code for the file. Do not include markdown backticks (```python ... ```) or any other explanations in the `code` field.
2.  The code should be well-structured, follow best practices, and be ready for integration.
3.  {"You must only make code changes directly related to completion of the task, refactors and cleaning up should not be prioritised unless specifically part of the task given" if strict else "You may make other changes as you see fit to improve code maintainability and clarity."}
4.  **Context Management**:
    a. **If you cannot generate the code for `{file_path}` due to insufficient context**: Set `requires_more_context` to `true`, leave `code` empty, and explain what you need in `context_request`.
    b. **If you can generate the code for `{file_path}` but you anticipate needing more context for FUTURE files**: Generate the code for the current file. Then, populate the `needed_context_for_future_files` list with the full paths of any other files you will need to see to complete subsequent steps. This is crucial for efficiency.
"""
        prompt = f"""
Overall Task: "{task}"

Full list of files in the repository:
{json.dumps(all_repo_files, indent=2)}

Remaining generation order: {generation_order}

Context from other relevant files in the project:
---
{context}
---

You are currently {action} the file: `{file_path}`.
"""
        if original_content is not None:
            prompt += f"""
Original content of `{file_path}`:
---
{original_content}
---
"""
        prompt += "\nPlease generate the complete, new source code for this file. If you lack context for this file or foresee needing context for future files, please request it."

        # Use a more powerful model for code generation
        generation_agent = Agent(self._get_gemini_model('gemini-2.5-pro'), output_type=GeneratedCode, system_prompt=system_prompt)
        
        logging.info(f"💡 Generating new code for {file_path}...")
        google_safety_settings = self.get_safety_settings()
        generated_code = generation_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(
            google_safety_settings=google_safety_settings
            ),
        )
        return generated_code.output


# --- CLI and File Operations ---
class CliManager:
    """Manages CLI interactions, file I/O, and orchestrates the analysis and code generation."""

    def __init__(self):
        self.ai_agent = AiCodeAgent()
    
    def run(self):
        """The main entry point for the CLI tool."""
        task = ""

        parser = argparse.ArgumentParser(
            description="A tool to analyze a git repository and apply AI-generated code changes for a specific task."
        )
        parser.add_argument("--task", type=str, default=task, help="The task description for the AI.")
        parser.add_argument(
            "--dir", type=str, default=os.getcwd(), help="The directory of the git repository."
        )
        parser.add_argument(
            "--app-description", type=str, default="app_description.txt",
            help="Path to a text file describing the app's purpose."
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Bypass confirmation before overwriting files."
        )
        parser.add_argument(
            "--strict", type=bool, default=True,
            help="Whether the AI should be liberal with making changes or restrict changes to only those needed for the task"
        )
        args = parser.parse_args()

        # --- 1. Initial Setup ---
        app_desc_content = read_file_content(args.dir, args.app_description) or ""
        git_files = get_git_files(args.dir)
        if not git_files:
            logging.warning("No files tracked by git were found.")

        # Get untracked files as well to give the AI full context
        try:
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=args.dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if untracked_result.returncode == 0 and untracked_result.stdout:
                untracked_files = untracked_result.stdout.strip().split("\n")
                logging.info(f"Found {len(untracked_files)} untracked files.")
                all_repo_files = sorted(list(set(git_files + untracked_files)))
            else:
                all_repo_files = git_files
        except Exception as e:
            logging.warning(f"Could not get untracked git files: {e}")
            all_repo_files = git_files

        if not all_repo_files:
            logging.error("No tracked or untracked files found in the repository. Exiting.")
            return

        # --- 2. Initial Analysis ---
        analysis = self.ai_agent.get_initial_analysis(args.task, all_repo_files, args.dir, app_desc_content)
        
        print("\n--- AI Code Analysis Result ---")
        print(f"Task: {args.task}\n")
        print(f"Overall Reasoning:\n {analysis.reasoning}\n")
        print("Relevant Files for Context:", analysis.relevant_files or "None")
        print("Files to Edit:", analysis.files_to_edit or "None")
        print("Files to Create:", [f.file_path for f in analysis.files_to_create] or "None")
        print("Proposed Generation Order:", analysis.generation_order or "None")
        print("---------------------------------\n")

        # Validate the plan for consistency
        planned_files: Set[str] = set(analysis.files_to_edit) | {f.file_path for f in analysis.files_to_create}
        ordered_files: Set[str] = set(analysis.generation_order)

        if planned_files != ordered_files:
            logging.error("Analysis Error: Mismatch between files to change and the generation order.")
            if planned_files - ordered_files:
                logging.error(f"Planned but not in order: {planned_files - ordered_files}")
            if ordered_files - planned_files:
                logging.error(f"In order but not planned: {ordered_files - planned_files}")
            return
            
        all_files_to_process = analysis.generation_order # Use the AI-provided intelligent order
        if not all_files_to_process:
            logging.info("No files to edit or create based on initial analysis. Exiting.")
            return

        # --- 3. User Confirmation ---
        if not args.force:
            proceed = input("Proceed with generating and writing file changes? (y/n): ").lower()
            if proceed != 'y':
                logging.info("Operation cancelled by user.")
                return

        # --- 4. Iterative Generation and Re-analysis Loop ---
        retries = 0
        feedback_for_next_loop = ""

        while all_files_to_process and retries < MAX_REANALYSIS_RETRIES:
            if feedback_for_next_loop:
                # Re-analyze with feedback
                analysis = self.ai_agent.get_initial_analysis(
                    args.task, all_repo_files, args.dir, app_desc_content, feedback=feedback_for_next_loop
                )
                # We update the full list of files to process based on the new analysis
                all_files_to_process = analysis.generation_order
                feedback_for_next_loop = "" # Reset feedback

            # Pre-load all necessary context into an in-memory dictionary.
            files_for_context = list(set(analysis.relevant_files + analysis.files_to_edit))
            context_data: Dict[str, str] = {}
            logging.info("Pre-loading context from disk for dynamic updates...")
            for fp in files_for_context:
                content = read_file_content(args.dir, fp)
                if content is not None:
                    context_data[fp] = content
            
            processed_in_this_loop: List[str] = []
            reanalysis_needed = False

            for file_path in all_files_to_process:
                full_context = build_context_from_dict(
                    context_data, self.ai_agent.summarize_code, exclude_file=file_path
                )
                
                original_content = context_data.get(file_path)
                
                # The current list of files to process is the remaining generation order
                remaining_generation_order = [f for f in all_files_to_process if f not in processed_in_this_loop]

                generated_code = self.ai_agent.generate_file_content(
                    args.task,
                    full_context,
                    file_path,
                    all_repo_files,
                    remaining_generation_order,
                    original_content,
                    strict=args.strict
                )

                if generated_code.requires_more_context:
                    logging.warning(f"Generator needs more context for file {file_path}.")
                    logging.info(f"Reason: {generated_code.context_request}")
                    feedback_for_next_loop = generated_code.context_request
                    retries += 1
                    reanalysis_needed = True
                    break # Exit the for loop to start the while loop again with re-analysis
                else:
                    write_file_content(args.dir, file_path, generated_code.code)
                    # Update context with the newly generated code for subsequent steps in this loop
                    context_data[file_path] = generated_code.code
                    processed_in_this_loop.append(file_path)

                    # Handle request for more context for FUTURE files
                    if generated_code.needed_context_for_future_files:
                        logging.info(
                            f"Agent requested additional context for future steps: {generated_code.needed_context_for_future_files}"
                        )
                        for new_context_file in generated_code.needed_context_for_future_files:
                            if new_context_file not in context_data:
                                content = read_file_content(args.dir, new_context_file)
                                if content is not None:
                                    logging.info(f"Loading '{new_context_file}' into context.")
                                    context_data[new_context_file] = content
                                else:
                                    logging.warning(
                                        f"AI requested context for a non-existent file: {new_context_file}. Ignoring."
                                    )

            # Update the list of files that still need processing
            all_files_to_process = [f for f in all_files_to_process if f not in processed_in_this_loop]

            if not reanalysis_needed:
                # If we completed a full loop without needing re-analysis, we are done
                break
        
        # --- 5. Final Status ---
        if all_files_to_process:
            logging.error(f"❌ Failed to complete the task after {MAX_REANALYSIS_RETRIES} retries. The following files were not processed:")
            for file_path in all_files_to_process:
                logging.error(f"   - {file_path}")
        else:
            logging.info("✅ All changes have been successfully applied.")

if __name__ == "__main__":
    cli = CliManager()
    cli.run()
