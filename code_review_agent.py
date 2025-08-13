#!/usr/bin/env python
import argparse
import json
import logging
import os
import subprocess
from typing import Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from shared_agents_utils import (
    AgentTools,
    BaseAiAgent,
    build_context_from_dict,
    get_git_files,
    read_file_content,
)

# --- Configuration ---
MAX_REANALYSIS_RETRIES = 3
MAX_ANALYSIS_GREP_RETRIES = 3


# --- Pydantic Models for Code Review ---

class ReviewComment(BaseModel):
    """A single comment for a code review."""
    line_number: int = Field(description="The specific line number the comment refers to. Use 0 for general, file-level comments.")
    comment: str = Field(description="The content of the review comment, explaining the issue and suggesting an improvement.")
    severity: Literal["Info", "Warning", "Critical"] = Field(description="The severity of the issue found.")

class FileReview(BaseModel):
    """Represents the complete code review for a single file."""
    file_path: str = Field(description="The path of the file that was reviewed.")
    comments: List[ReviewComment] = Field(default=[], description="A list of line-specific review comments for the file.")
    general_feedback: str = Field(description="A high-level summary of the review for this file, not tied to a specific line.")
    requires_more_context: bool = Field(
        default=False,
        description="Set to true if you cannot complete the review due to insufficient context."
    )
    context_request: str = Field(
        default="",
        description="If requires_more_context is true, explain what specific information or files are needed."
    )

class ReviewAnalysis(BaseModel):
    """Initial analysis to determine which files to review and which to use for context."""
    files_to_review: List[str] = Field(
        description="A list of file paths that require a detailed review (e.g., changed files)."
    )
    relevant_context_files: List[str] = Field(
        description="A list of existing file paths to read for understanding the context of the changes."
    )
    reasoning: str = Field(
        description="A brief explanation of why these files were chosen for review and context."
    )
    additional_grep_queries_needed: List[str] = Field(
        default=[],
        description="A list of additional 'git grep' queries that you believe would significantly improve your confidence in the plan. If you are less than 90% confident, you should request more information via grep. Leave empty if you are confident."
    )


# --- Core Logic for AI Interaction ---

class AiCodeReviewAgent(BaseAiAgent):
    """Handles all AI interactions for conducting a code review."""

    def get_review_analysis(
        self, task: str, all_files: List[str], changed_files: List[str], app_description: str = "", feedback: Optional[str] = None, git_grep_search_tool: Optional[Callable] = None, read_file_tool: Optional[Callable] = None, grep_results: Optional[str] = None
    ) -> ReviewAnalysis:
        """Determines which files to review and which are needed for context."""
        system_prompt = f"""
You are an expert software developer planning a code review. Your goal is to analyze a list of changed files and the overall project structure to determine which files are essential to review and which other files are needed for context. Your aim is to be at least 90% confident in your plan.

**You have access to these tools**:
1.  **`git_grep_search_tool(query: str)`**: Helps you find relevant code snippets and file locations. Use it to explore the codebase to understand the impact of changes.
2.  **`read_file_tool(file_path: str)`**: Reads the entire content of a specific file. Use this when you need more context than `grep` can provide.

**The Process**:
1.  **Analyze Changes**: Based on the changed files and the task description, determine which files need a detailed review (`files_to_review`).
2.  **Identify Context**: Determine `relevant_context_files` needed to understand the changes.
3.  **Verify with Tools**: Use `git_grep_search_tool` and `read_file_tool` to confirm your file choices and understand relationships in the code. You can call these tools multiple times within a single turn.
4.  **Assess Confidence**: After your initial analysis and tool use, assess your confidence.
    - **If Confidence < 90%**: If you feel you're missing information, populate `additional_grep_queries_needed` with new search terms. If you do this, do not populate the other fields in the `ReviewAnalysis` object.
    - **If Confidence >= 90%**: If you are confident, leave `additional_grep_queries_needed` empty and provide the full `ReviewAnalysis`.

Project Description:
---
{app_description or "No description provided."}
---
"""
        if feedback:
            system_prompt += f"""
---
IMPORTANT: This is a re-analysis. A previous review attempt failed due to insufficient context.
The reviewer's feedback was: "{feedback}"
Please adjust your file selection. You MUST add more files to `relevant_context_files` to satisfy the context request. You should not need to ask for more grep queries.
---
"""
        prompt = f"""
Full list of files in the repository:
{json.dumps(all_files, indent=2)}

List of changed files for this review:
{json.dumps(changed_files, indent=2)}

The task or pull request description is: "{task}"
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
        
        tools = []
        if git_grep_search_tool:
            tools.append(git_grep_search_tool)
        if read_file_tool:
            tools.append(read_file_tool)

        analysis_agent = Agent(
            self._get_gemini_model("gemini-1.5-flash"),
            output_type=ReviewAnalysis,
            system_prompt=system_prompt,
            tools=tools
        )
        
        log_message = "🤖 Conducting initial review analysis..."
        if feedback:
            log_message = f"🔁 Re-analyzing review plan with feedback: {feedback}"
        elif grep_results:
            log_message = "🤔 Re-evaluating plan with new grep results..."

        logging.info(log_message)
        
        analysis = analysis_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return analysis.output

    def review_file_content(
        self, task: str, context: str, file_path: str, file_content: str, strict: bool = True
    ) -> FileReview:
        """Performs a code review on a single file."""
        strict_guideline = (
            "**Task-Focus**: Your review comments MUST be strictly related to the given task description. "
            "Do not comment on code style, potential refactors, or issues that are not directly relevant to the task "
            "unless they introduce a critical bug or security vulnerability."
        )
        liberal_guideline = (
            "**Broad Feedback**: You are encouraged to comment on any aspect of the code that could be improved, "
            "including code style, clarity, performance, and best practices, even if not directly related to the task."
        )

        system_prompt = f"""
You are an expert code reviewer, known for your thorough and constructive feedback. Your task is to review the provided code file based on the overall task description and the context of related files.

**CRITICAL REVIEW GUIDELINES**:
1.  **Be Thorough**: Look for bugs, logic errors, performance issues, security vulnerabilities, and deviations from best practices.
2.  **Be Constructive**: For each issue, explain *why* it's a problem and suggest a clear, actionable improvement.
3.  **Be Specific**: Tie comments to specific line numbers using the `ReviewComment` model. For general feedback, use the `general_feedback` field.
4.  **Check Consistency**: Ensure the code is consistent with the overall task and the provided context from other files.
5.  {strict_guideline if strict else liberal_guideline}
6.  **Use the Schema**: Structure your entire output as a single `FileReview` JSON object.

If you cannot perform a thorough review because you lack critical context (e.g., a referenced file is not provided), you MUST:
a. Set the `requires_more_context` flag to `true`.
b. Leave the `comments` list empty.
c. In the `context_request` field, clearly explain what information or files you need.
"""
        prompt = f"""
Overall Task / PR Description: "{task}"

Context from other relevant files in the project:
---
{context}
---

You are currently reviewing the file: `{file_path}`.
Original content of `{file_path}`:
---
{file_content}
---

Please provide your complete and thorough review for this file in the specified `FileReview` format.
"""
        review_agent = Agent(
            self._get_gemini_model("gemini-2.5-pro", temperature=0.1),
            output_type=FileReview,
            system_prompt=system_prompt,
        )
        logging.info(f"🔬 Reviewing file: {file_path}...")
        
        review = review_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return review.output


# --- CLI and Orchestration ---

class ReviewCliManager:
    """Manages CLI interactions and orchestrates the code review process."""

    def __init__(self):
        self.args = self._parse_arguments()
        self.ai_agent = AiCodeReviewAgent()
        self.directory = self.args.dir
        self.agent_tools = AgentTools(self.directory)

    def _parse_arguments(self) -> argparse.Namespace:
        """Parses command-line arguments for the code review agent."""
        parser = argparse.ArgumentParser(
            description="An AI agent that reviews code changes in a git repository. It can review local uncommitted changes or all changes against a specified branch."
        )
        parser.add_argument(
            "--task", type=str, required=True,
            help="The task description or goal of the changes for the AI to review against."
        )
        parser.add_argument(
            "--dir", type=str, default=os.getcwd(),
            help="The directory of the git repository."
        )
        parser.add_argument(
            "--app-description", type=str, default="app_description.txt",
            help="Path to a text file describing the app's purpose for better context."
        )
        parser.add_argument(
            "--compare", type=str, default=None,
            help="The git branch to compare against (e.g., 'origin/main'). If provided, reviews committed and local changes against this branch."
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Bypass confirmation before starting the review."
        )
        parser.add_argument(
            '--strict', dest='strict', action='store_true',
            help="Restrict comments to only those related to the task (default)."
        )
        parser.add_argument(
            '--no-strict', dest='strict', action='store_false',
            help="Allow more liberal feedback on code style, refactors, etc."
        )
        parser.set_defaults(strict=True)
        return parser.parse_args()

    def _run_git_command(self, command: List[str]) -> List[str]:
        """Runs a git command and returns its output split by lines."""
        try:
            result = subprocess.run(
                command,
                cwd=self.directory,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip().split("\n") if result.stdout.strip() else []
        except FileNotFoundError:
            logging.error("❌ 'git' command not found. Is Git installed?")
            raise
        except subprocess.CalledProcessError as e:
            logging.error(f"❌ Error running git command '{' '.join(command)}': {e.stderr}")
            raise

    def _get_local_changed_files(self) -> List[str]:
        """Gets all local changes: staged, unstaged, and untracked files."""
        logging.info("Checking for local changes (staged, unstaged, untracked)...")
        staged_files = self._run_git_command(["git", "diff", "--name-only", "--cached"])
        unstaged_files = self._run_git_command(["git", "diff", "--name-only"])
        untracked_files = self._run_git_command(["git", "ls-files", "--others", "--exclude-standard"])
        return sorted(list(set(staged_files + unstaged_files + untracked_files)))

    def _get_branch_diff_files(self, compare_branch: str) -> List[str]:
        """Gets the diff between a branch and the current working tree."""
        logging.info(f"Comparing current changes against branch '{compare_branch}'...")
        diff_files = self._run_git_command(["git", "diff", "--name-only", compare_branch])
        untracked_files = self._run_git_command(["git", "ls-files", "--others", "--exclude-standard"])
        return sorted(list(set(diff_files + untracked_files)))

    def _get_changed_files(self) -> List[str]:
        """Gets a list of changed files based on the selected mode."""
        try:
            if self.args.compare:
                changed_files = self._get_branch_diff_files(self.args.compare)
            else:
                changed_files = self._get_local_changed_files()

            if not changed_files:
                return []

            logging.info(f"✅ Found {len(changed_files)} changed files to review.")
            return changed_files
        except (FileNotFoundError, subprocess.CalledProcessError):
            logging.error("Could not retrieve changed files due to a git error. Exiting.")
            return []

    def _print_review_summary(self, reviews: List[FileReview]):
        """Prints the formatted review results for successfully reviewed files."""
        print("\n\n--- 📝 AI Code Review Summary ---")
        if not reviews:
            print("\nNo files were successfully reviewed.")
            return
            
        total_comments = 0
        for review in reviews:
            print("\n" + "="*80)
            print(f"📄 FILE: {review.file_path}")
            print("="*80)

            if review.general_feedback:
                print(f"\n💡 General Feedback:\n   {review.general_feedback}\n")

            if not review.comments:
                print("✅ No specific issues found.")
                continue
            
            total_comments += len(review.comments)
            sorted_comments = sorted(review.comments, key=lambda c: c.line_number)

            for comment in sorted_comments:
                print(f"  - L{comment.line_number} [{comment.severity.upper()}]: {comment.comment}")
        
        print("\n" + "="*80)
        print(f"✨ Review complete for {len(reviews)} files. Found {total_comments} total comments.")
        print("="*80)

    def _print_analysis_plan(self, analysis: ReviewAnalysis):
        """Prints the AI's plan for the review."""
        print("\n--- 🤖 AI Review Plan ---")
        print(f"Task: {self.args.task}\n")
        print(f"Reasoning:\n {analysis.reasoning}\n")
        print("Files to Review:", analysis.files_to_review or "None")
        print("Files for Context:", analysis.relevant_context_files or "None")
        print("--------------------------\n")

    def _execute_review_loop(self, analysis: ReviewAnalysis, all_git_files: List[str], original_changed_files: List[str], app_desc_content: str) -> Tuple[List[FileReview], List[str]]:
        """
        Manages the iterative process of reviewing files, handling context requests, and re-analyzing on failure.
        Returns a tuple of (successful_reviews, unprocessed_files).
        """
        files_to_process = analysis.files_to_review
        context_data: Dict[str, str] = {}
        feedback_for_reanalysis = ""
        retries = 0
        all_reviews: List[FileReview] = []

        while files_to_process and retries <= MAX_REANALYSIS_RETRIES:
            if feedback_for_reanalysis:
                logging.info("--- Re-running Analysis with Feedback ---")
                analysis = self.ai_agent.get_review_analysis(
                    self.args.task, all_git_files, original_changed_files, app_desc_content, 
                    feedback=feedback_for_reanalysis,
                    git_grep_search_tool=self.agent_tools.git_grep_search,
                    read_file_tool=self.agent_tools.read_file
                )
                self._print_analysis_plan(analysis)
                files_to_process = analysis.files_to_review
                feedback_for_reanalysis = ""

            files_for_context = list(set(analysis.relevant_context_files + files_to_process))
            for fp in files_for_context:
                if fp not in context_data:
                    content = read_file_content(self.directory, fp)
                    if content is not None:
                        context_data[fp] = content
            
            processed_in_loop: List[str] = []
            reanalysis_needed = False

            for file_to_review in files_to_process:
                if file_to_review not in context_data:
                    logging.error(f"Cannot review {file_to_review} as its content could not be read. Skipping.")
                    processed_in_loop.append(file_to_review)
                    continue

                full_context = build_context_from_dict(
                    context_data, self.ai_agent.summarize_code, exclude_file=file_to_review
                )
                file_content = context_data[file_to_review]
                
                review_result = self.ai_agent.review_file_content(
                    self.args.task, full_context, file_to_review, file_content, strict=self.args.strict
                )

                if review_result.requires_more_context:
                    logging.warning(f"Reviewer needs more context for {file_to_review}: {review_result.context_request}")
                    feedback_for_reanalysis = review_result.context_request
                    retries += 1
                    reanalysis_needed = True
                    break

                all_reviews.append(review_result)
                processed_in_loop.append(file_to_review)

            successfully_reviewed_files = {r.file_path for r in all_reviews}
            files_to_process = [f for f in analysis.files_to_review if f not in successfully_reviewed_files]

            if not reanalysis_needed:
                break

        return all_reviews, files_to_process

    def _report_final_status(self, unprocessed_files: List[str]):
        """Prints the final status of the code review task."""
        if unprocessed_files:
            logging.error(f"\n❌ Failed to complete the review for all files after {MAX_REANALYSIS_RETRIES} retries.")
            logging.error("The following files were not processed:")
            for file_path in unprocessed_files:
                logging.error(f"  - {file_path}")
        else:
            logging.info("✅ All planned files were successfully reviewed.")

    def run(self):
        """The main entry point for orchestrating the code review."""
        app_desc_content = read_file_content(self.directory, self.args.app_description) or ""
        all_git_files = get_git_files(self.directory)
        if not all_git_files:
            return
        
        changed_files = self._get_changed_files()
        if not changed_files:
            if self.args.compare:
                logging.info(f"No changes detected compared to '{self.args.compare}'. Exiting.")
            else:
                logging.info("No local changes detected. Exiting.")
            return

        # Analysis loop with grep for confidence
        analysis: Optional[ReviewAnalysis] = None
        grep_results = ""
        analysis_retries = 0
        while analysis_retries < MAX_ANALYSIS_GREP_RETRIES:
            current_analysis = self.ai_agent.get_review_analysis(
                self.args.task,
                all_git_files,
                changed_files,
                app_desc_content,
                git_grep_search_tool=self.agent_tools.git_grep_search,
                read_file_tool=self.agent_tools.read_file,
                grep_results=grep_results or None
            )

            if current_analysis.additional_grep_queries_needed:
                analysis_retries += 1
                logging.info("🤖 AI has requested more information via git grep to improve its review plan. Running queries.")
                
                new_results = []
                for query in current_analysis.additional_grep_queries_needed:
                    result = self.agent_tools.git_grep_search(query)
                    new_results.append(result)
                
                grep_results = "\n\n".join(new_results)
                analysis = None
            else:
                analysis = current_analysis
                break
        
        if not analysis:
            logging.error(f"❌ Failed to get a confident analysis from the AI after {MAX_ANALYSIS_GREP_RETRIES} attempts.")
            return

        self._print_analysis_plan(analysis)

        if not analysis.files_to_review:
            logging.info("AI analysis concluded no files need review. Exiting.")
            return

        if not self.args.force:
            proceed = input("Proceed with AI code review? (y/n): ").lower()
            if proceed != 'y':
                logging.info("Operation cancelled by user.")
                return

        successful_reviews, unprocessed_files = self._execute_review_loop(
            analysis, all_git_files, changed_files, app_desc_content
        )

        self._print_review_summary(successful_reviews)
        self._report_final_status(unprocessed_files)

def main():
    """Main entry point of the script."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    cli = ReviewCliManager()
    cli.run()

if __name__ == "__main__":
    main()
