"""#!/usr/bin/env python
import argparse
import json
import logging
import os
import queue
import subprocess
import threading
import time
import webbrowser
from typing import Callable, Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from html_utils import create_code_plan_html
from shared_agents_utils import (
    AgentTools,
    ApprovalHandler,
    ApprovalWebServer,
    BaseAiAgent,
    build_context_from_dict,
    get_git_files,
    read_file_content,
    write_file_content,
)

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


# --- Core Logic for AI Interaction ---

class AiCodeAgent(BaseAiAgent):
    """Handles all interactions with the Gemini AI model."""

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
5.  **Assess Confidence**: After your initial analysis and tool use, assess your confidence.
    - **If Confidence < 90%**: If you feel you're missing information or your plan is too speculative, populate `additional_grep_queries_needed` with new search terms that would help you build a better plan. If you do this, do not populate the other fields in the `CodeAnalysis` object.
    - **If Confidence >= 90%**: If you are confident, leave `additional_grep_queries_needed` empty and provide the full `CodeAnalysis`, including the `branch_name`, `plan`, file lists, and `generation_order`.

**CRITICAL**:
- **`branch_name`**: Must be a valid git branch name.
- **`plan`**: This should be a detailed, step-by-step description of the changes you will make.
- **`generation_order`**: This is the most important part of your execution plan. It must list all files from `files_to_edit` and `files_to_create` in the correct dependency order.
- **Model Selection**: If the task is very simple (e.g., fixing a typo, updating a version number, a simple one-line change), set `use_flash_model` to `true`. This uses a faster model for code generation. For anything more complex, leave it `false` to use the more powerful model.

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
            prompt_addition += "\nPlease create a new, complete plan that addresses the feedback. You must provide a full plan this time and not ask for more grep queries.\n---"
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
Please provide your analysis. Use the `git_grep_search_tool` and `read_file_tool` if you need to find specific code snippets or understand file contents. If you are not confident in your plan, request more grep searches by populating `additional_grep_queries_needed`.
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
        
        log_message = "🤖 Conducting initial codebase analysis..."
        if feedback:
            log_message = f"🔁 Re-analyzing codebase with feedback: {feedback}"
        elif grep_results:
            log_message = "🤔 Re-evaluating plan with new grep results..."

        logging.info(log_message)
        
        analysis = analysis_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return analysis.output

    def generate_file_content(self, task: str, context: str, file_path: str, all_repo_files: List[str], generation_order: List[str], original_content: Optional[str] = None, strict: bool = True, use_flash_model: bool = False) -> GeneratedCode:
        """Generates the full code for a given file."""
        action = "editing" if original_content is not None else "creating"
        
        system_prompt = f"""
You are an expert programmer tasked with writing a complete Python file.
Based on the overall task, the provided context from other relevant files, and the original code (if any),
you will generate the full, production-ready code for the specified file path.

**IMPORTANT RULES**:
1.  Your output must be the complete, raw code for the file. Do not include markdown backticks (```python ... ```) or any other explanations in the `code` field.
2.  The code should be well-structured, follow best practices, and be ready for integration.
3.  You must also provide a concise `summary` of the changes and a `reasoning` for why these changes were made.
4.  {"You must only make code changes directly related to completion of the task, refactors and cleaning up should not be prioritised unless specifically part of the task given" if strict else "You may make other changes as you see fit to improve code maintainability and clarity."}
5.  **Context Management**:
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
        prompt += "\nPlease generate the complete, new source code for this file, along with a summary and reasoning. If you lack context for this file or foresee needing context for future files, please request it."

        model_name = "gemini-2.5-flash" if use_flash_model else "gemini-2.5-pro"

        generation_agent = Agent(
            self._get_gemini_model(model_name), 
            output_type=GeneratedCode, 
            system_prompt=system_prompt
        )
        
        logging.info(f"💡 Generating new code for {file_path} using {model_name}...")
        generated_code = generation_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return generated_code.output


# --- CLI and File Operations ---

class CliManager:
    """Manages CLI interactions, file I/O, and orchestrates the analysis and code generation."""

    status_queue: Optional[queue.Queue[Dict[str, Any]]]
    
    def __init__(self):
        """Initializes the CLI manager and the AI code agent."""
        self.ai_agent = AiCodeAgent()
        self.args = self._parse_args()
        self.agent_tools = AgentTools(self.args.dir)
        self.status_queue:  Optional[queue.Queue[Dict[str, Any]]] = None

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
                logging.info(f"Found {len(untracked_files)} untracked files.")
                return sorted(list(set(git_files + untracked_files)))
            return git_files
        except Exception as e:
            logging.warning(f"Could not get untracked git files: {e}. Proceeding with tracked files only.")
            return git_files

    def _reconcile_and_validate_analysis(self, analysis: CodeAnalysis, all_repo_files: List[str]) -> bool:
        """
        Validates and reconciles the AI's plan. It treats `generation_order` as the source of truth
        and adjusts `files_to_edit` and `files_to_create` to match it, ensuring consistency.
        """
        if not analysis:
            logging.error("Cannot validate a null analysis.")
            return False

        planned_files: Set[str] = set(analysis.files_to_edit) | {f.file_path for f in analysis.files_to_create}
        ordered_files: Set[str] = set(analysis.generation_order)

        if planned_files == ordered_files:
            return True  # No mismatch, nothing to do.

        logging.warning("Analysis Warning: Mismatch found between planned files and generation order. Reconciling lists using 'generation_order' as the source of truth.")

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
                    logging.warning(f"  - File '{file_path}' from generation_order was not in files_to_create. Adding it.")
                    new_files_to_create.append(NewFile(
                        file_path=file_path,
                        reasoning="File was added to the plan to match the generation order."
                    ))
        
        # Log what was removed from the original plan
        for file_path in planned_files - ordered_files:
            logging.warning(f"  - File '{file_path}' was in the original plan but not in generation_order. Removing it.")

        analysis.files_to_edit = sorted(new_files_to_edit)
        analysis.files_to_create = sorted(new_files_to_create, key=lambda f: f.file_path)
        
        logging.info("✅ Analysis plan reconciled successfully.")
        return True

    def _create_and_checkout_branch(self, branch_name: str) -> bool:
        """Creates and checks out a new git branch."""
        try:
            logging.info(f"🌿 Creating and switching to new branch: {branch_name}")
            # Check if branch already exists
            check_branch_cmd = ["git", "rev-parse", "--verify", branch_name]
            branch_exists = subprocess.run(check_branch_cmd, cwd=self.args.dir, capture_output=True, text=True).returncode == 0
            
            if branch_exists:
                logging.warning(f"Branch '{branch_name}' already exists. Checking it out.")
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
            logging.info(f"✅ Switched to branch '{branch_name}'.")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"❌ Failed to create or checkout branch '{branch_name}': {e.stderr}")
            return False
        except FileNotFoundError:
            logging.error("❌ 'git' command not found. Is Git installed and in your PATH?")
            return False

    def _commit_and_push_changes(self, branch_name: str, commit_message: str) -> bool:
        """Adds all changes, commits them, and pushes the branch to origin."""
        try:
            logging.info("💾 Staging changes...")
            subprocess.run(["git", "add", "."], cwd=self.args.dir, check=True)

            logging.info(f"📝 Committing changes with message: '{commit_message}'")
            subprocess.run(["git", "commit", "-m", commit_message], cwd=self.args.dir, check=True)

            logging.info(f"🚀 Pushing branch '{branch_name}' to origin...")
            subprocess.run(["git", "push", "-u", "origin", branch_name], cwd=self.args.dir, check=True)
            
            logging.info("✅ Changes committed and pushed successfully.")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"❌ Git operation failed: {e.stderr}")
            return False
        except FileNotFoundError:
            logging.error("❌ 'git' command not found.")
            return False

    def _create_pull_request(self, branch_name: str, title: str, body: str) -> bool:
        """Creates a pull request using the GitHub CLI 'gh'."""
        try:
            subprocess.run(["gh", "--version"], check=True, capture_output=True, text=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            logging.warning("⚠️ 'gh' command not found or not configured. Cannot create pull request.")
            logging.warning(f"Please create the pull request manually for branch '{branch_name}'.")
            return False

        try:
            logging.info(f"📦 Creating pull request for branch '{branch_name}'...")
            command = [
                "gh", "pr", "create",
                "--title", title,
                "--body", body,
                "--base", "main",
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
            logging.info(f"✅ Successfully created pull request: {pr_url}")
            return True
        except subprocess.CalledProcessError as e:
            if "a pull request for" in e.stderr and "already exists" in e.stderr:
                logging.warning(f"⚠️ A pull request for branch '{branch_name}' already exists.")
                try:
                    pr_list_cmd = ["gh", "pr", "list", "--head", branch_name, "--json", "url"]
                    pr_list_result = subprocess.run(pr_list_cmd, cwd=self.args.dir, capture_output=True, text=True, check=True)
                    pr_info = json.loads(pr_list_result.stdout)
                    if pr_info:
                        logging.info(f"Existing PR URL: {pr_info[0]['url']}")
                except Exception as find_e:
                    logging.warning(f"Could not retrieve existing PR URL: {find_e}")
                return True
            
            logging.error(f"❌ Failed to create pull request: {e.stderr}")
            return False

    def _execute_generation_loop(self, analysis: CodeAnalysis, all_repo_files: List[str], app_desc_content: str) -> List[str]:
        """
        Manages the iterative process of generating code, handling context, and re-analyzing on failure.
        Returns a list of files that were not successfully processed.
        """
        files_to_process = analysis.generation_order
        context_data: Dict[str, str] = {}
        feedback_for_reanalysis = ""
        retries = 0

        while files_to_process and retries <= MAX_REANALYSIS_RETRIES:
            if feedback_for_reanalysis:
                logging.info("--- Re-running Analysis with Feedback ---")
                analysis = self.ai_agent.get_initial_analysis(
                    self.args.task, all_repo_files, app_desc_content, feedback=feedback_for_reanalysis, previous_plan=analysis, git_grep_search_tool=self.agent_tools.git_grep_search, read_file_tool=self.agent_tools.read_file
                )
                files_to_process = analysis.generation_order
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

            for file_path in files_to_process:
                if self.status_queue:
                    self.status_queue.put({"status": "writing", "file_path": file_path})

                remaining_order = [f for f in files_to_process if f not in processed_in_loop]
                context_str = build_context_from_dict(context_data, self.ai_agent.summarize_code, exclude_file=file_path)
                
                generated_code = self.ai_agent.generate_file_content(
                    self.args.task, context_str, file_path, all_repo_files,
                    remaining_order, context_data.get(file_path), strict=self.args.strict,
                    use_flash_model=analysis.use_flash_model
                )

                if generated_code.requires_more_context:
                    logging.warning(f"Generator needs more context for {file_path}: {generated_code.context_request}")
                    feedback_for_reanalysis = generated_code.context_request
                    retries += 1
                    reanalysis_needed = True
                    break  # Break inner loop to re-run analysis

                # Success case
                write_file_content(self.args.dir, file_path, generated_code.code)
                if self.status_queue:
                    self.status_queue.put({
                        "status": "done",
                        "file_path": file_path,
                        "summary": generated_code.summary,
                        "reasoning": generated_code.reasoning,
                    })

                context_data[file_path] = generated_code.code  # Update context for next file in this loop
                processed_in_loop.append(file_path)

                # Dynamically load more context if requested for future files
                if generated_code.needed_context_for_future_files:
                    logging.info(f"Agent requested more context for future steps: {generated_code.needed_context_for_future_files}")
                    for new_context_file in generated_code.needed_context_for_future_files:
                        if new_context_file not in context_data:
                            content = read_file_content(self.args.dir, new_context_file)
                            if content:
                                context_data[new_context_file] = content

            # Update the list of files to process for the next iteration
            files_to_process = [f for f in files_to_process if f not in processed_in_loop]

            if not reanalysis_needed:
                break  # Exit while loop if all files processed successfully

        return files_to_process

    def _report_final_status(self, unprocessed_files: List[str]):
        """Prints the final status of the code generation task."""
        if unprocessed_files:
            logging.error(f"❌ Failed to complete the task after {MAX_REANALYSIS_RETRIES} retries.")
            logging.error("The following files were not processed:")
            for file_path in unprocessed_files:
                logging.error(f"  - {file_path}")
        else:
            logging.info("✅ All changes have been successfully applied.")

    def run(self):
        """The main entry point for the CLI tool."""
        # 1. Initial Setup
        app_desc_content = read_file_content(self.args.dir, self.args.app_description) or ""
        all_repo_files = self._get_all_repository_files()
        if not all_repo_files:
            logging.error("No tracked or untracked files found. Exiting.")
            return

        # 2. Analysis and Confirmation Loop
        analysis: Optional[CodeAnalysis] = None
        previous_analysis: Optional[CodeAnalysis] = None
        user_feedback: Optional[str] = None
        server = None
        server_thread = None

        while True:  # This loop handles user feedback on the plan
            # A. Get Analysis
            if user_feedback:
                logging.info(f"🔁 Re-analyzing plan with user feedback: '{user_feedback}'")
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
                        logging.info("🤖 AI has requested more information via git grep. Running queries...")
                        new_results = [self.agent_tools.git_grep_search(q) for q in current_analysis.additional_grep_queries_needed]
                        grep_results = "\n\n".join(new_results)
                        analysis = None
                    else:
                        analysis = current_analysis
                        break
                if not analysis:
                    logging.error(f"❌ Failed to get a confident analysis after {MAX_ANALYSIS_GREP_RETRIES} attempts.")
                    return

            # B. Reconcile analysis and get user confirmation
            if not self._reconcile_and_validate_analysis(analysis, all_repo_files):
                logging.error("Failed to reconcile the analysis plan. Aborting.")
                return

            logging.info("✅ Analysis complete. Awaiting user confirmation in browser.")
            plan_html_path = create_code_plan_html(analysis, self.args.task, self.args.port)
            if not plan_html_path:
                logging.error("Failed to create the HTML plan file.")
                return
            
            if not analysis.generation_order:
                logging.info("AI analysis resulted in no files to change. Exiting.")
                return

            # C. User Confirmation
            if not self.args.force:
                class StatusAwareApprovalHandler(ApprovalHandler):
                    cli_manager = self
                    def do_GET(self):
                        if self.path == '/status':
                            try:
                                if self.cli_manager.status_queue:
                                    update = self.cli_manager.status_queue.get(block=True, timeout=28)
                                    self._send_response(200, 'application/json', json.dumps(update).encode('utf-8'))
                            except (queue.Empty, AttributeError):
                                self._send_response(204, 'text/plain', b'')
                        else:
                            super().do_GET()

                server = ApprovalWebServer(('', self.args.port), StatusAwareApprovalHandler, html_file_path=os.path.realpath(plan_html_path))
                self.status_queue = queue.Queue()
                server_thread = threading.Thread(target=server.serve_forever)
                server_thread.daemon = True
                server_thread.start()

                webbrowser.open(f"file://{os.path.realpath(plan_html_path)}")
                decision, data = server.wait_for_decision()

                if decision == 'approve':
                    logging.info("✅ Plan approved by user. Proceeding with code generation.")
                    # Handle model override from user
                    if data and isinstance(data, dict) and 'use_flash_model' in data:
                        override_value: bool = bool(data.get('use_flash_model', False)) # type: ignore
                        if analysis.use_flash_model != override_value:
                            analysis.use_flash_model = override_value
                            logging.info(f"Model selection overridden by user. 'Use Gemini Flash' is now set to: {analysis.use_flash_model}")
                    
                    if not self._create_and_checkout_branch(analysis.branch_name):
                        logging.error("Could not create git branch. Aborting.")
                        server.shutdown()
                        return
                    break
                elif decision == 'reject':
                    logging.info("❌ Plan rejected by user. Operation cancelled.")
                    server.shutdown()
                    return
                elif decision == 'feedback':
                    user_feedback = data
                    previous_analysis = analysis
                    logging.info("Re-running analysis with new feedback...")
                    server.shutdown()
                    server.server_close()
                    continue
                else:
                    logging.error("No decision received from the browser. Exiting.")
                    server.shutdown()
                    return
            else:
                logging.info("✅ Plan approved automatically (--force).")
                if not self._create_and_checkout_branch(analysis.branch_name):
                    logging.error("Could not create git branch. Aborting.")
                    return
                break

        try:
            # 5. Iterative Generation
            unprocessed_files = self._execute_generation_loop(analysis, all_repo_files, app_desc_content)
            # 6. Final Status
            self._report_final_status(unprocessed_files)

            if not unprocessed_files:
                logging.info("All files processed. Proceeding with git operations.")
                commit_message = f"feat: {self.args.task}\n\n{analysis.reasoning}"
                if self._commit_and_push_changes(analysis.branch_name, commit_message):
                    pr_title = f"AI-Gen: {self.args.task}"
                    pr_body = f"This PR was automatically generated by an AI agent to address the following task:\n\n**Task:** {self.args.task}\n\n**AI's Plan:**\n"
                    for i, step in enumerate(analysis.plan):
                        pr_body += f"{i+1}. {step}\n"
                    self._create_pull_request(analysis.branch_name, pr_title, pr_body)
            else:
                logging.warning("Some files were not processed. Skipping git commit and PR creation.")

            if server and self.status_queue:
                self.status_queue.put({"status": "finished"})
                time.sleep(5) # Give browser time to fetch final status
        finally:
            if server:
                logging.info("Shutting down web server.")
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    if os.name == "nt":
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    cli = CliManager()
    cli.run()
"