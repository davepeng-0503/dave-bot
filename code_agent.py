#!/usr/bin/env python
import argparse
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
import webbrowser
from typing import Any, Callable, Dict, List, Optional, Set
import markdown

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from html_utils import create_code_agent_html_viewer
from shared_agents_utils import (
    AgentTools,
    BaseAiAgent,
    build_context_from_dict,
    get_git_files,
    read_file_content,
    write_file_content,
)
from web_server_utils import ApprovalHandler, ApprovalWebServer

# --- Configuration ---
MAX_REANALYSIS_RETRIES = 3
MAX_ANALYSIS_GREP_RETRIES = 3
DEFAULT_SERVER_PORT = 8080

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
    branch_name: str = Field(
        description="A short, descriptive, git-friendly branch name based on the task, always prefixed with 'dave-bot/' (e.g., 'dave-bot/feat/add-user-auth', 'dave-bot/fix/bug-in-payment-processor')."
    )
    plan: List[str] = Field(
        default=[],
        description="A detailed, step-by-step plan of what needs to be done to accomplish the task."
    )
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
    additional_grep_queries_needed: List[str] = Field(
        default=[],
        description="A list of additional 'git grep' queries that you believe would significantly improve your confidence in the plan. If you are less than 90% confident, you should request more information via grep. Leave empty if you are confident."
    )
    use_flash_model: bool = Field(
        default=False,
        description="Set to true if the task is simple (e.g., minor text changes, version bumps, simple refactors) and can be handled by a faster, less powerful model for code generation. For complex tasks, leave as false."
    )
    user_request: str = Field(
        default="",
        description="If you are blocked and need to ask the user a clarifying question to proceed, state your question here. The user will provide an answer, and you will be re-run with their response. Only use this if you are blocked."
    )


class GeneratedCode(BaseModel):
    """Represents the AI-generated code for a single file."""
    file_path: str = Field(description="The path of the file for which code is being generated.")
    code: str = Field(description="The complete, production-ready source code for the file.")
    summary: str = Field(description="A concise summary of the changes made to the file. This should be a high-level overview of what was changed, added, or removed.")
    reasoning: str = Field(description="A brief explanation of why the changes were made, linking them back to the overall task.")
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
    add_to_generation_queue: List[str] = Field(
        default=[],
        description="A list of file paths (new or existing) that you believe need to be generated or regenerated to complete the task. You can use this to add files that were missed in the initial plan, or to revisit a file you have already generated if you realize a change is needed."
    )


# --- Core Logic for AI Interaction ---

class AiCodeAgent(BaseAiAgent):
    """Handles all interactions with the Gemini AI model."""

    def __init__(self, status_queue: Optional[queue.Queue[Dict[str, Any]]] = None):
        super().__init__()
        self.status_queue = status_queue

    def _log_info(self, message: str, icon: str = "ℹ️"):
        logging.info(message)
        if self.status_queue:
            self.status_queue.put({"status": "cli_log", "message": message, "icon": icon, "cssClass": ""})

    def get_initial_analysis(self, task: str, file_list: List[str], app_description: str = "", feedback: Optional[str] = None, previous_plan: Optional[CodeAnalysis] = None, git_grep_search_tool: Optional[Callable[..., Any]] = None, read_file_tool: Optional[Callable[..., Any]] = None, grep_results: Optional[str] = None) -> CodeAnalysis:
        """Runs the agent to get the code analysis, potentially using feedback or a search tool."""
        
        system_prompt = f"""
You are an expert software developer planning a coding task. Your goal is to create a comprehensive plan to modify a codebase.

**Your Goal**: Create a `CodeAnalysis` response. Your aim is to be at least 90% confident in your plan.

**You have access to these tools**:
1.  **`git_grep_search_tool(query: str)`**: Helps you find relevant code snippets and file locations. Use it to explore the codebase.
2.  **`read_file_tool(file_path: str)`**: Reads the entire content of a specific file. Use this when you need more context than `grep` can provide.

**The Process**:
1.  **Create Branch Name**: First, create a descriptive, git-friendly `branch_name` for the task, always prefixed with `dave-bot/` (e.g., 'dave-bot/feat/new-feature', 'dave-bot/fix/bug-fix').
2.  **Formulate a Plan**: Based on the task, create a step-by-step `plan`.
3.  **Identify Files**: Determine `files_to_edit`, `files_to_create`, and `relevant_files` for context.
4.  **Verify with Tools**: Use `git_grep_search_tool` and `read_file_tool` to confirm your file choices and understand the code. You can call these tools multiple times within a single turn.
5.  **Assess Confidence and Information Gaps**:
    - **If Blocked by Lack of User Intent**: If you cannot proceed because the user's request is ambiguous or requires a decision from them, populate `user_request` with a clear, concise question for the user. Do not populate any other fields.
    - **If Lacking Codebase Context**: If you are not blocked, but your confidence is < 90% because you need more information about the existing code, populate `additional_grep_queries_needed` with new search terms. Do not populate any other fields.
    - **If Confident (>= 90%)**: If you are confident, provide the full `CodeAnalysis`. Leave `user_request` and `additional_grep_queries_needed` empty.

**CRITICAL**:
- **`branch_name`**: Must be a valid git branch name.
- **`plan`**: This should be a detailed, step-by-step description of the changes you will make.
- **`generation_order`**: This is the most important part of your execution plan. It must list all files from `files_to_edit` and `files_to_create` in the correct dependency order.
- **Model Selection**: If the task is very simple (e.g., fixing a typo, updating a version number, a simple one-line change), set `use_flash_model` to `true`. This uses a faster model for code generation. For anything more complex, leave it `false` to use the more powerful model.
- **Asking Questions**: Use `user_request` for questions about the *task requirements*. Use `additional_grep_queries_needed` for questions about the *existing code*. Only fill out ONE of `user_request`, `additional_grep_queries_needed`, or the full plan.

Project Description:
---
{app_description or "No description provided."}
---"""
        if feedback:
            prompt_addition = "\n---\n"
            prompt_addition += "IMPORTANT: This is a re-analysis. You must generate a new plan.\n"
            if previous_plan:
                prompt_addition += f"\nHere was the previous plan you created:\n{previous_plan.model_dump_json(indent=2)}\n"
            
            prompt_addition += f"\nThe feedback provided is: \"{feedback}\"\n"
            prompt_addition += "\nPlease create a new, complete plan that addresses the feedback. Avoid asking for more grep queries or user input unless absolutely necessary.\n---"
            system_prompt += prompt_addition

        prompt = f"""
Full list of files in the repository:
{json.dumps(file_list, indent=2)}

My task is: "{task}"
"""
        if grep_results:
            prompt += f"""
---
You previously requested more information to increase your confidence. Here are the results of the 'git grep' commands you asked for:
{grep_results}
---
Now, please provide your final analysis. You should be confident enough to not require more grep queries. If you still lack confidence, it is better to make a best-effort plan than to ask for more information again.
"""
        else:
            prompt += """
Please provide your analysis. Use the `git_grep_search_tool` and `read_file_tool` if you need to find specific code snippets or understand file contents. If you are not confident in your plan, request more grep searches by populating `additional_grep_queries_needed`. If you are blocked by ambiguity in the task, use `user_request`.
"""
        
        tools: List[Callable[..., Any]] = []
        if git_grep_search_tool:
            tools.append(git_grep_search_tool)
        if read_file_tool:
            tools.append(read_file_tool)

        analysis_agent = Agent(
            self._get_gemini_model('gemini-2.5-flash'),
            output_type=CodeAnalysis,
            system_prompt=system_prompt,
            tools=tools
        )
        
        log_message = "Conducting initial codebase analysis..."
        icon = "🤖"
        if feedback:
            log_message = f"Re-analyzing codebase with feedback: {feedback}"
            icon = "🔁"
        elif grep_results:
            log_message = "Re-evaluating plan with new grep results..."
            icon = "🤔"

        self._log_info(log_message, icon=icon)
        
        analysis = analysis_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return analysis.output

    def generate_file_content(self, task: str, context: str, file_path: str, all_repo_files: List[str], generation_order: List[str], edited_files: List[str], original_content: Optional[str] = None, strict: bool = True, use_flash_model: bool = False) -> GeneratedCode:
        """Generates the full code for a given file."""
        action = "editing" if original_content is not None else "creating"
        
        system_prompt = f"""
You are an expert programmer tasked with writing a complete Python file.
Based on the overall task, the provided context from other relevant files, and the original code (if any),
you will generate the full, production-ready code for the specified file path.

**IMPORTANT RULES**:
1.  Your output must be the complete, raw code for the file. Do not include markdown backticks (```python ... ```) or any other explanations in the `code` field.
2.  The code should be well-structured, follow best practices, and be ready for integration.
3.  If you are unsure of how to implement something. Do not fill out the code, summary or reasoning fields. Instead, set `requires_more_context` to `true` and provide a clear `user_request` explaining what additional information you need.
4.  If you believe after generating this file that another file not included must be edited or a file needs to be revisited, you may request to add it to the generation queue by populating the `add_to_generation_queue` field with a list of file paths.
5.  You must also provide a concise `summary` of the changes and a `reasoning` for why these changes were made.
6.  {"You must only make code changes directly related to completion of the task, refactors and cleaning up should not be prioritised unless specifically part of the task given" if strict else "You may make other changes as you see fit to improve code maintainability and clarity."}
7.  You must not generate mocks or stubs for functions that are being imported from other files. If you need to use a function that is not defined in the current file, you must ensure it is imported correctly. If you are unable to do this, you must request more context.
8.  **Context Management**:
    a. **If you cannot generate the code for `{file_path}` due to insufficient context**: Set `requires_more_context` to `true`, leave `code` empty, and explain what you need in `context_request`.
    b. **If you can generate the code for `{file_path}` but you anticipate needing more context for FUTURE files**: Generate the code for the current file. Then, populate the `needed_context_for_future_files` list with the full paths of any other files you will need to see to complete subsequent steps. This is crucial for efficiency.
"""
        prompt = f"""
Overall Task: "{task}"

Full list of files in the repository:
{json.dumps(all_repo_files, indent=2)}

All files edited in this session: {json.dumps(edited_files)}
After this file is generated the following files will also be generated keep that in mind: {json.dumps(generation_order)}

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
        prompt += "\nPlease generate the complete, new source code for this file, along with a summary and reasoning. If you lack context for this file or foresee needing context for future files, please request it."

        model_name = "gemini-2.5-flash" if use_flash_model else "gemini-2.5-pro"

        generation_agent = Agent(
            self._get_gemini_model(model_name), 
            output_type=GeneratedCode, 
            system_prompt=system_prompt
        )
        
        self._log_info(f"Generating new code for {file_path} using {model_name}...", icon="💡")
        generated_code = generation_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return generated_code.output


# --- CLI and File Operations ---

class CliManager:
    """Manages CLI interactions, file I/O, and orchestrates the analysis and code generation."""

    status_queue: queue.Queue[Dict[str, Any]]
    original_branch: str
    
    def __init__(self):
        """Initializes the CLI manager and the AI code agent."""
        self.args = self._parse_args()
        self.status_queue = queue.Queue()
        self.ai_agent = AiCodeAgent(status_queue=self.status_queue)
        # Pass the queue to AgentTools to capture tool usage during analysis
        self.agent_tools = AgentTools(self.args.dir, status_queue=self.status_queue)
        self.original_branch = ""

    def _log_info(self, message: str, icon: str = "ℹ️"):
        logging.info(message)
        if not self.args.force:
            self.status_queue.put({"status": "cli_log", "message": message, "icon": icon, "cssClass": ""})

    def _log_warning(self, message: str, icon: str = "⚠️"):
        logging.warning(message)
        if not self.args.force:
            self.status_queue.put({"status": "cli_log", "message": message, "icon": icon, "cssClass": "warning"})

    def _log_error(self, message: str, icon: str = "❌"):
        logging.error(message)
        if not self.args.force:
            self.status_queue.put({"status": "cli_log", "message": message, "icon": icon, "cssClass": "error"})

    def _parse_args(self) -> argparse.Namespace:
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser(
            description="A tool to analyze a git repository and apply AI-generated code changes for a specific task."
        )
        parser.add_argument(
            "--task", type=str, required=True, help="The task description for the AI."
        )
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
            '--strict', dest='strict', action='store_true', help="Restrict AI to task-focused changes."
        )
        parser.add_argument(
            '--no-strict', dest='strict', action='store_false', help="Allow AI to make broader improvements."
        )
        parser.add_argument(
            "--port", type=int, default=DEFAULT_SERVER_PORT,
            help=f"The port to run the local web server on for user approval (default: {DEFAULT_SERVER_PORT})."
        )
        parser.set_defaults(strict=True)
        return parser.parse_args()

    def _get_all_repository_files(self) -> List[str]:
        """Gets all tracked and untracked files in the repository."""
        git_files = get_git_files(self.args.dir)
        try:
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=self.args.dir, capture_output=True, text=True, check=False,
            )
            if untracked_result.returncode == 0 and untracked_result.stdout:
                untracked_files = untracked_result.stdout.strip().split("\n")
                self._log_info(f"Found {len(untracked_files)} untracked files.")
                return sorted(list(set(git_files + untracked_files)))
            return git_files
        except Exception as e:
            self._log_warning(f"Could not get untracked git files: {e}. Proceeding with tracked files only.")
            return git_files

    def _reconcile_and_validate_analysis(self, analysis: CodeAnalysis, all_repo_files: List[str]) -> bool:
        """
        Validates and reconciles the AI's plan. It treats `generation_order` as the source of truth
        and adjusts `files_to_edit` and `files_to_create` to match it, ensuring consistency.
        """
        if not analysis:
            self._log_error("Cannot validate a null analysis.")
            return False

        planned_files: Set[str] = set(analysis.files_to_edit) | {f.file_path for f in analysis.files_to_create}
        ordered_files: Set[str] = set(analysis.generation_order)

        if planned_files == ordered_files:
            return True  # No mismatch, nothing to do.

        self._log_warning("Mismatch found between planned files and generation order. Reconciling lists using 'generation_order' as the source of truth.")

        new_files_to_edit: List[str] = []
        new_files_to_create: List[NewFile] = []
        
        # Keep existing NewFile objects if they are in the generation order
        existing_creations = {f.file_path: f for f in analysis.files_to_create}

        for file_path in analysis.generation_order:
            # We need to check if the file exists in the repo to decide if it's an edit or create.
            # The `all_repo_files` list includes all tracked and untracked files.
            if file_path in all_repo_files:
                if file_path not in new_files_to_edit:
                    new_files_to_edit.append(file_path)
            else:
                # It's a file to be created.
                if file_path in existing_creations:
                    # Preserve the detailed NewFile object if it exists
                    new_files_to_create.append(existing_creations[file_path])
                else:
                    # Create a placeholder NewFile object
                    self._log_warning(f"File '{file_path}' from generation_order was not in files_to_create. Adding it.")
                    new_files_to_create.append(NewFile(
                        file_path=file_path,
                        reasoning="File was added to the plan to match the generation order."
                    ))
        
        # Log what was removed from the original plan
        for file_path in planned_files - ordered_files:
            self._log_warning(f"File '{file_path}' was in the original plan but not in generation_order. Removing it.")

        analysis.files_to_edit = sorted(new_files_to_edit)
        analysis.files_to_create = sorted(new_files_to_create, key=lambda f: f.file_path)
        
        self._log_info("Analysis plan reconciled successfully.", icon="✅")
        return True

    def _create_and_checkout_branch(self, branch_name: str) -> bool:
        """Creates and checks out a new git branch."""
        try:
            self._log_info(f"Creating and switching to new branch: {branch_name}", icon="🌿")
            # Check if branch already exists
            check_branch_cmd = ["git", "rev-parse", "--verify", branch_name]
            branch_exists = subprocess.run(check_branch_cmd, cwd=self.args.dir, capture_output=True, text=True).returncode == 0
            
            if branch_exists:
                self._log_warning(f"Branch '{branch_name}' already exists. Checking it out.")
                command = ["git", "checkout", branch_name]
            else:
                command = ["git", "checkout", "-b", branch_name]
                
            subprocess.run(
                command,
                cwd=self.args.dir,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            self._log_info(f"Switched to branch '{branch_name}'.", icon="✅")
            return True
        except subprocess.CalledProcessError as e:
            self._log_error(f"Failed to create or checkout branch '{branch_name}': {e.stderr}")
            return False
        except FileNotFoundError:
            self._log_error("'git' command not found. Is Git installed and in your PATH?")
            return False

    def _commit_and_push_changes(self, branch_name: str, commit_message: str) -> Optional[str]:
        """
        Adds all changes, commits them, and pushes the branch to origin.
        Returns the pull request URL if found in the output, or an empty string if push was successful but no URL was found.
        Returns None if the push operation fails.
        """
        try:
            self._log_info("Staging changes...", icon="💾")
            subprocess.run(["git", "add", "."], cwd=self.args.dir, check=True)

            self._log_info(f"Committing changes with message: '{commit_message}'", icon="📝")
            subprocess.run(["git", "commit", "-m", commit_message], cwd=self.args.dir, check=True)

            self._log_info(f"Pushing branch '{branch_name}' to origin...", icon="🚀")
            push_result = subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                cwd=self.args.dir,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )

            # Log the full output for the user, as it's useful.
            full_output = (push_result.stdout or "") + "\n" + (push_result.stderr or "")
            self._log_info(f"Git push output:\n{full_output.strip()}")

            # Try to find the PR URL in the output (usually in stderr)
            url_pattern = re.compile(r'https?://[^\s]+')
            if push_result.stderr:
                for line in push_result.stderr.split('\n'):
                    if 'remote:' in line and ('pull/new' in line or 'pull-request' in line):
                        match = url_pattern.search(line)
                        if match:
                            url = match.group(0)
                            self._log_info(f"Found pull request creation link: {url}", icon="🔗")
                            return url
            
            self._log_info("Changes committed and pushed successfully.", icon="✅")
            return "" # Push successful, but no URL found.
        except subprocess.CalledProcessError as e:
            self._log_error(f"Git operation failed: {e.stderr}")
            if e.stdout:
                self._log_error(f"Git stdout: {e.stdout}")
            return None # Push failed
        except FileNotFoundError:
            self._log_error("'git' command not found.")
            return None # Push failed

    def _create_pull_request(self, branch_name: str, title: str, body: str) -> bool:
        """Creates a pull request using the GitHub CLI 'gh' and opens it in the browser."""
        try:
            subprocess.run(["gh", "--version"], check=True, capture_output=True, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            self._log_warning("'gh' command not found or not configured. Cannot create pull request.")
            self._log_warning(f"Please create the pull request manually for branch '{branch_name}'.")
            return False

        try:
            self._log_info(f"Creating pull request for branch '{branch_name}'...", icon="📦")
            command = [
                "gh", "pr", "create",
                "--title", title,
                "--body", body,
                "--base", self.original_branch,
                "--head", branch_name,
            ]
            
            result = subprocess.run(
                command,
                cwd=self.args.dir,
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            pr_url = result.stdout.strip()
            self._log_info(f"Successfully created pull request: {pr_url}", icon="✅")
            self._log_info("Opening pull request in your browser...", icon="🌐")
            webbrowser.open(pr_url)
            return True
        except subprocess.CalledProcessError as e:
            if "a pull request for" in e.stderr and "already exists" in e.stderr:
                self._log_warning(f"A pull request for branch '{branch_name}' already exists.")
                try:
                    # Check for an existing open PR
                    pr_list_cmd = ["gh", "pr", "list", "--head", branch_name, "--json", "url", "--state", "open"]
                    pr_list_result = subprocess.run(pr_list_cmd, cwd=self.args.dir, capture_output=True, text=True, check=True)
                    pr_info = json.loads(pr_list_result.stdout)
                    if pr_info:
                        pr_url = pr_info[0]['url']
                        self._log_info(f"Opening existing PR: {pr_url}", icon="🌐")
                        webbrowser.open(pr_url)
                    else:
                        self._log_warning("Could not find an open PR for this branch to open.")
                except Exception as find_e:
                    self._log_warning(f"Could not retrieve or open existing PR URL: {find_e}")
                return True
            
            self._log_error(f"Failed to create pull request: {e.stderr}")
            return False

    def _switch_to_original_branch(self):
        """Switches back to the original branch if it exists."""
        if not self.original_branch:
            self._log_warning("Original branch name not found, cannot switch back.")
            return

        try:
            self._log_info(f"Switching back to original branch '{self.original_branch}'...", icon="🌿")
            subprocess.run(
                ["git", "checkout", self.original_branch],
                cwd=self.args.dir,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self._log_info(f"Successfully switched back to branch '{self.original_branch}'.", icon="✅")
        except subprocess.CalledProcessError as e:
            self._log_error(f"Failed to switch back to branch '{self.original_branch}': {e.stderr}")
        except FileNotFoundError:
            self._log_error("'git' command not found. Cannot switch branch.")

    def _execute_generation_loop(self, analysis: CodeAnalysis, all_repo_files: List[str], app_desc_content: str) -> List[str]:
        """
        Manages the iterative process of generating code, handling context, and re-analyzing on failure.
        Returns a list of files that were not successfully processed.
        """
        files_to_process = list(analysis.generation_order)
        context_data: Dict[str, str] = {}
        feedback_for_reanalysis = ""
        retries = 0
        edited_files: List[str] = []

        while files_to_process and retries <= MAX_REANALYSIS_RETRIES:
            if feedback_for_reanalysis:
                self._log_info("--- Re-running Analysis with Feedback ---", icon="🔁")
                analysis = self.ai_agent.get_initial_analysis(
                    self.args.task, all_repo_files, app_desc_content, feedback=feedback_for_reanalysis, previous_plan=analysis, git_grep_search_tool=self.agent_tools.git_grep_search, read_file_tool=self.agent_tools.read_file
                )
                files_to_process = list(analysis.generation_order)
                feedback_for_reanalysis = ""  # Reset feedback

            # Pre-load context for the current batch of files
            files_for_context = list(set(analysis.relevant_files + analysis.files_to_edit))
            for fp in files_for_context:
                if fp not in context_data:  # Only load if not already in memory
                    content = read_file_content(self.args.dir, fp)
                    if content is not None:
                        context_data[fp] = content
            
            processed_in_loop: List[str] = []
            reanalysis_needed = False

            # Use an index-based loop to allow modification of files_to_process during iteration
            i = 0
            while i < len(files_to_process):
                file_path = files_to_process[i]
                i += 1 # Increment early, so we can `continue` or `break`

                self.status_queue.put({"status": "writing", "file_path": file_path})

                remaining_order = files_to_process[i:]
                context_str = build_context_from_dict(context_data, self.ai_agent.summarize_code, exclude_file=file_path)
                
                generated_code = self.ai_agent.generate_file_content(
                    self.args.task, context_str, file_path, all_repo_files,
                    remaining_order, edited_files, context_data.get(file_path), strict=self.args.strict,
                    use_flash_model=analysis.use_flash_model
                )

                if generated_code.requires_more_context:
                    self._log_warning(f"Generator needs more context for {file_path}: {generated_code.context_request}")
                    feedback_for_reanalysis = generated_code.context_request
                    retries += 1
                    reanalysis_needed = True
                    break  # Break inner loop to re-run analysis

                # Success case
                write_file_content(self.args.dir, file_path, generated_code.code)
                self.status_queue.put({
                    "status": "done",
                    "file_path": file_path,
                    "summary": markdown.markdown(generated_code.summary),
                    "reasoning": markdown.markdown(generated_code.reasoning),
                })

                context_data[file_path] = generated_code.code  # Update context for next file in this loop
                processed_in_loop.append(file_path)
                if file_path not in edited_files:
                    edited_files.append(file_path)

                # Dynamically load more context if requested for future files
                if generated_code.needed_context_for_future_files:
                    self._log_info(f"Agent requested more context for future steps: {generated_code.needed_context_for_future_files}")
                    for new_context_file in generated_code.needed_context_for_future_files:
                        if new_context_file not in context_data:
                            content = read_file_content(self.args.dir, new_context_file)
                            if content:
                                context_data[new_context_file] = content
                
                # Dynamically add files to the generation queue
                if generated_code.add_to_generation_queue:
                    files_to_add = generated_code.add_to_generation_queue
                    self._log_info(f"Agent requested to add {len(files_to_add)} file(s) to the generation queue: {files_to_add}")
                    
                    # Add new files to the end of the processing list and master plan
                    files_to_process.extend(files_to_add)
                    analysis.generation_order.extend(files_to_add)
                    
                    self.status_queue.put({
                        "status": "plan_updated",
                        "files_added": files_to_add,
                        "new_total_files": len(analysis.generation_order)
                    })

            # Update the list of files to process for the next iteration
            # This logic is now tricky because we used an index-based loop.
            # If reanalysis was needed, we need to figure out the remaining files.
            if reanalysis_needed:
                # The files from `i` onwards are the ones not yet processed in this attempt.
                files_to_process = files_to_process[i-1:]
            else:
                # The loop completed successfully
                files_to_process = []

            if not reanalysis_needed:
                break  # Exit while loop if all files processed successfully

        return files_to_process

    def _report_final_status(self, unprocessed_files: List[str]):
        """Prints the final status of the code generation task."""
        if unprocessed_files:
            self._log_error(f"Failed to complete the task after {MAX_REANALYSIS_RETRIES} retries.")
            self._log_error("The following files were not processed:")
            for file_path in unprocessed_files:
                self._log_error(f"  - {file_path}")
        else:
            self._log_info("All changes have been successfully applied.", icon="✅")

    def run(self):
        """The main entry point for the CLI tool."""
        # 1. Initial Setup
        try:
            original_branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.args.dir, capture_output=True, text=True, check=True, encoding="utf-8"
            )
            self.original_branch = original_branch_result.stdout.strip()
            self._log_info(f"Original branch is '{self.original_branch}'. This will be the base for the pull request.")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self._log_error(f"Could not determine the current git branch: {e}. Aborting.")
            return

        app_desc_content = read_file_content(self.args.dir, self.args.app_description) or ""
        all_repo_files = self._get_all_repository_files()
        if not all_repo_files:
            self._log_error("No tracked or untracked files found. Exiting.")
            return

        # 2. Start Web Server and open browser
        server = None
        if not self.args.force:
            viewer_html_path = create_code_agent_html_viewer(self.args.port, all_repo_files)
            if not viewer_html_path:
                self._log_error("Failed to create the HTML viewer file.")
                return

            class StatusAwareApprovalHandler(ApprovalHandler):
                cli_manager = self
                def do_GET(self):
                    if self.path == '/status':
                        try:
                            # Use a long poll timeout on the server side
                            update = self.cli_manager.status_queue.get(block=True, timeout=28)
                            self._send_response(200, 'application/json', json.dumps(update).encode('utf-8'))
                        except (queue.Empty, AttributeError):
                            # Send 204 No Content if queue is empty after timeout
                            self._send_response(204, 'text/plain', b'')
                    else:
                        # Serve the main HTML file for other paths
                        super().do_GET()

            server = ApprovalWebServer(('', self.args.port), StatusAwareApprovalHandler, html_file_path=os.path.realpath(viewer_html_path))
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.daemon = True
            server_thread.start()
            self._log_info(f"Interactive viewer is running. Opening in your browser...", icon="🌐")
            webbrowser.open(f"file://{os.path.realpath(viewer_html_path)}")
        else:
            self._log_info("Running in non-interactive mode due to --force flag.")

        analysis: Optional[CodeAnalysis] = None
        try:
            # 3. Analysis and Confirmation Loop
            previous_analysis: Optional[CodeAnalysis] = None
            user_feedback: Optional[str] = None
            feedback_loop = 0
            while True:  # This loop handles user feedback on the plan
                # A. Get Analysis
                if server and feedback_loop == 0:
                    self.status_queue.put({"status": "planning"})

                if user_feedback:
                    analysis = self.ai_agent.get_initial_analysis(
                        self.args.task, all_repo_files, app_desc_content,
                        feedback=user_feedback, previous_plan=previous_analysis,
                        git_grep_search_tool=self.agent_tools.git_grep_search,
                        read_file_tool=self.agent_tools.read_file
                    )
                    user_feedback = None
                else:
                    grep_results = ""
                    analysis_retries = 0
                    while analysis_retries < MAX_ANALYSIS_GREP_RETRIES:
                        current_analysis = self.ai_agent.get_initial_analysis(
                            self.args.task, all_repo_files, app_desc_content,
                            git_grep_search_tool=self.agent_tools.git_grep_search,
                            read_file_tool=self.agent_tools.read_file,
                            grep_results=grep_results or None
                        )
                        if current_analysis.additional_grep_queries_needed:
                            analysis_retries += 1
                            self._log_info("AI has requested more information via git grep. Running queries...", icon="🤖")
                            new_results = [self.agent_tools.git_grep_search(q) for q in current_analysis.additional_grep_queries_needed]
                            grep_results = "\n\n".join(new_results)
                            analysis = None
                        else:
                            analysis = current_analysis
                            break
                    if not analysis:
                        if server:
                            self.status_queue.put({"status": "error", "message": f"Failed to get a confident analysis after {MAX_ANALYSIS_GREP_RETRIES} attempts."})
                        self._log_error(f"Failed to get a confident analysis after {MAX_ANALYSIS_GREP_RETRIES} attempts.")
                        return

                # B. Handle user request from AI
                if analysis.user_request:
                    self._log_info(f"AI is asking a question: {analysis.user_request}", icon="❓")
                    if not self.args.force and server:
                        self.status_queue.put({
                            "status": "user_input_required",
                            "request": analysis.user_request
                        })
                        decision, data = server.wait_for_decision()
                        if decision == 'user_input':
                            user_response = data.get('user_input') if isinstance(data, dict) else None
                            if user_response:
                                self._log_info(f"User responded: {user_response}", icon="💬")
                                user_feedback = f"My previous question was: '{analysis.user_request}'. The user's answer is: '{user_response}'. Please create a plan based on this new information."
                                previous_analysis = analysis
                                feedback_loop += 1
                                server.reset_decision()
                                continue # Restart the main `while True` loop for re-analysis
                            else:
                                self._log_error("User did not provide input. Aborting.")
                                if server: self.status_queue.put({"status": "error", "message": "User did not provide input."})
                                return
                        else:
                            self._log_error(f"Expected user input, but got decision '{decision}'. Aborting.")
                            if server: self.status_queue.put({"status": "error", "message": f"Operation cancelled during user input. Decision: {decision}"})
                            return
                    else: # --force is on or server not running
                        self._log_error("AI requested user input in non-interactive mode. Aborting.")
                        return

                # C. Reconcile analysis
                if not self._reconcile_and_validate_analysis(analysis, all_repo_files):
                    if server:
                        self.status_queue.put({"status": "error", "message": "Failed to reconcile the analysis plan."})
                    self._log_error("Failed to reconcile the analysis plan. Aborting.")
                    return
                
                if not analysis.generation_order:
                    self._log_info("AI analysis resulted in no files to change. Exiting.")
                    if server:
                        self.status_queue.put({"status": "finished", "message": "AI analysis resulted in no files to change."})
                    return

                # D. User Confirmation
                if not self.args.force and server:
                    self._log_info("Analysis complete. Awaiting user confirmation in browser.", icon="✅")
                    
                    # Convert markdown fields to HTML for the view
                    analysis_for_view = analysis.model_copy(deep=True)
                    analysis_for_view.plan = [markdown.markdown(step) for step in analysis.plan]
                    analysis_for_view.reasoning = markdown.markdown(analysis.reasoning)
                    
                    self.status_queue.put({
                        "status": "plan_ready",
                        "plan": analysis_for_view.model_dump(),
                        "task": self.args.task
                    })

                    decision, data = server.wait_for_decision()

                    if decision == 'approve':
                        self._log_info("Plan approved by user. Proceeding with code generation.", icon="✅")
                        if data and isinstance(data, dict):
                            # Handle model override
                            if 'use_flash_model' in data:
                                override_value: bool = bool(data.get('use_flash_model', False))
                                if analysis.use_flash_model != override_value:
                                    analysis.use_flash_model = override_value
                                    self._log_info(f"Model selection overridden by user. 'Use Gemini Flash' is now set to: {analysis.use_flash_model}")
                            
                            # Handle additional context files
                            additional_files: List[str] = data.get('additional_context_files', [])
                            if additional_files:
                                self._log_info(f"User added {len(additional_files)} files to context: {additional_files}")
                                # Add to relevant_files, avoiding duplicates
                                analysis.relevant_files = sorted(list(set(analysis.relevant_files + additional_files)))
                        
                        if not self._create_and_checkout_branch(analysis.branch_name):
                            self.status_queue.put({"status": "error", "message": "Could not create git branch."})
                            self._log_error("Could not create git branch. Aborting.")
                            return
                        break # Exit feedback loop
                    elif decision == 'reject':
                        self._log_info("Plan rejected by user. Operation cancelled.", icon="❌")
                        return
                    elif decision == 'feedback':
                        if data and isinstance(data, dict):
                            user_feedback = data.get('feedback')
                            additional_files = data.get('additional_context_files', [])
                            if additional_files:
                                self._log_info(f"User added {len(additional_files)} files to context for re-analysis: {additional_files}")
                                analysis.relevant_files = sorted(list(set(analysis.relevant_files + additional_files)))
                        else:
                            # Fallback for older JS or unexpected data format
                            user_feedback = data if isinstance(data, str) else None

                        if not user_feedback:
                            self._log_warning("Feedback submitted without text. Ignoring and awaiting new decision.")
                            server.reset_decision()
                            continue
                        
                        previous_analysis = analysis
                        feedback_loop += 1
                        # The get_initial_analysis call will log the re-analysis message.
                        decision = None
                        data = None
                        server.reset_decision()
                        continue
                    else:
                        self._log_error("No decision received from the browser. Exiting.")
                        return
                else: # --force is on
                    self._log_info("Plan approved automatically (--force).", icon="✅")
                    if not self._create_and_checkout_branch(analysis.branch_name):
                        self._log_error("Could not create git branch. Aborting.")
                        return
                    break # Exit feedback loop

            # 4. Iterative Generation
            unprocessed_files = self._execute_generation_loop(analysis, all_repo_files, app_desc_content)
            
            # 5. Final Status
            self._report_final_status(unprocessed_files)

            if not unprocessed_files:
                self._log_info("All files processed. Proceeding with git operations.")
                commit_message = f"feat: {self.args.task}\n\n{analysis.reasoning}"
                push_result_url = self._commit_and_push_changes(analysis.branch_name, commit_message)
                if push_result_url is not None:  # This means push was successful
                    pr_title = f"AI-Gen: {analysis.branch_name}"
                    pr_body = f"This PR was automatically generated by an AI agent to address the following task:\n\n**Task:** {self.args.task}\n\n**AI's Plan:**\n"
                    for i, step in enumerate(analysis.plan):
                        pr_body += f"{i+1}. {step}\n"
                    # Try to create PR with gh first. _create_pull_request returns True on success.
                    if (self._create_pull_request(analysis.branch_name, pr_title, pr_body) == False):
                        webbrowser.open(push_result_url)
                else:
                    # This block is executed if push_result_url is None, which means push failed.
                    self._log_warning("Git push failed. Skipping PR creation.")

            else:
                self._log_warning("Some files were not processed. Skipping git commit and PR creation.")

            if server and self.status_queue:
                self.status_queue.put({"status": "finished"})
                time.sleep(2) # Give browser time to fetch final status
        finally:
            if server:
                self._log_info("Shutting down web server.", icon="🔌")
                server.shutdown()
                server.server_close()
            
            # Switch back to original branch if a new one was created
            if analysis and self.original_branch and analysis.branch_name != self.original_branch:
                self._switch_to_original_branch()


if __name__ == "__main__":
    if os.name == "nt":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    cli = CliManager()
    cli.run()
