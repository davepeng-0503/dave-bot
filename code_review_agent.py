#!/usr/bin/env python
import argparse
import json
import logging
import os
import subprocess
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from shared_agents_utils import (
    BaseAiAgent,
    build_context_from_dict,
    get_git_files,
    read_file_content,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

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


# --- Core Logic for AI Interaction ---

class AiCodeReviewAgent(BaseAiAgent):
    """Handles all AI interactions for conducting a code review."""

    def get_review_analysis(
        self, task: str, all_files: List[str], changed_files: List[str], app_description: str = ""
    ) -> ReviewAnalysis:
        """Determines which files to review and which are needed for context."""
        system_prompt = f"""
You are an expert software developer planning a code review. Your goal is to analyze a list of changed files 
and the overall project structure to determine which files are essential to review and which other files are needed for context.

Project Description:
---
{app_description or "No description provided."}
---

Your task is to populate the `ReviewAnalysis` object based on the user's request (or PR description) and the file lists.

- `files_to_review`: This should generally be the list of changed files. However, you can add other files if the task description strongly implies they are part of the logical change and need scrutiny.
- `relevant_context_files`: This is crucial. Include any files that help understand the impact and correctness of the changes. Think about files that import the changed modules, modules that are imported by the changed files, related tests, or documentation.

Provide a clear `reasoning` for your choices.
"""
        prompt = f"""
Full list of files in the repository:
{json.dumps(all_files, indent=2)}

List of changed files for this review:
{json.dumps(changed_files, indent=2)}

The task or pull request description is: "{task}"

Please provide your analysis of which files to review and which to use for context.
"""
        analysis_agent = Agent(
            self._get_gemini_model("gemini-2.5-flash"),
            output_type=ReviewAnalysis,
            system_prompt=system_prompt,
        )
        logging.info("🤖 Conducting initial review analysis...")
        
        analysis = analysis_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return analysis.output

    def review_file_content(
        self, task: str, context: str, file_path: str, file_content: str
    ) -> FileReview:
        """Performs a code review on a single file."""
        system_prompt = """
You are an expert code reviewer, known for your thorough and constructive feedback. Your task is to review the provided code file based on the overall task description and the context of related files.

**CRITICAL REVIEW GUIDELINES**:
1.  **Be Thorough**: Look for bugs, logic errors, performance issues, security vulnerabilities, and deviations from best practices.
2.  **Be Constructive**: For each issue, explain *why* it's a problem and suggest a clear, actionable improvement.
3.  **Be Specific**: Tie comments to specific line numbers using the `ReviewComment` model. For general feedback, use the `general_feedback` field.
4.  **Check Consistency**: Ensure the code is consistent with the overall task and the provided context from other files.
5.  **Use the Schema**: Structure your entire output as a single `FileReview` JSON object.

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

class CliManager:
    """Manages CLI interactions and orchestrates the code review process."""

    def __init__(self):
        self.ai_agent = AiCodeReviewAgent()

    def _get_changed_files(self, directory: str) -> List[str]:
        """Gets all local changes: staged, unstaged, and untracked files."""
        try:
            logging.info("Checking for local changes (staged, unstaged, untracked)...")

            # Staged changes (files added to the index but not yet committed)
            staged_result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                cwd=directory, capture_output=True, text=True, check=True
            )
            staged_files = staged_result.stdout.strip().split("\n") if staged_result.stdout.strip() else []

            # Unstaged changes (files modified in the working directory but not staged)
            unstaged_result = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=directory, capture_output=True, text=True, check=True
            )
            unstaged_files = unstaged_result.stdout.strip().split("\n") if unstaged_result.stdout.strip() else []

            # Untracked files (new files not yet staged)
            untracked_result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                cwd=directory, capture_output=True, text=True, check=True
            )
            untracked_files = untracked_result.stdout.strip().split("\n") if untracked_result.stdout.strip() else []

            # Combine and get unique file paths
            all_changed_files = sorted(list(set(staged_files + unstaged_files + untracked_files)))

            if not all_changed_files:
                return []

            logging.info(f"✅ Found {len(all_changed_files)} locally changed files to review.")
            return all_changed_files
        except FileNotFoundError:
            logging.error("❌ 'git' command not found. Is Git installed?")
            return []
        except subprocess.CalledProcessError as e:
            logging.error(f"❌ Error getting local changes: {e.stderr}")
            logging.error("Please ensure you are in a valid git repository.")
            return []

    def _print_review(self, reviews: List[FileReview]):
        """Prints the formatted review results."""
        print("\n\n--- 📝 AI Code Review Summary ---")
        total_comments = 0
        for review in reviews:
            print("\n" + "="*80)
            print(f"📄 FILE: {review.file_path}")
            print("="*80)

            if review.requires_more_context:
                print("⚠️ CONTEXT REQUIRED:")
                print(f"   {review.context_request}")
                continue

            if review.general_feedback:
                print(f"\n💡 General Feedback:\n   {review.general_feedback}\n")

            if not review.comments:
                print("✅ No specific issues found.")
                continue
            
            total_comments += len(review.comments)
            # Sort comments by line number
            sorted_comments = sorted(review.comments, key=lambda c: c.line_number)

            for comment in sorted_comments:
                print(f"  - L{comment.line_number} [{comment.severity.upper()}]: {comment.comment}")
        
        print("\n" + "="*80)
        print(f"✨ Review complete. Found {total_comments} total comments across {len(reviews)} files.")
        print("="*80)

    def run(self):
        """The main entry point for the CLI tool."""
        parser = argparse.ArgumentParser(
            description="An AI agent that reviews local, uncommitted code changes in a git repository."
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
        args = parser.parse_args()

        # --- 1. Initial Setup ---
        app_desc_content = read_file_content(args.dir, args.app_description) or ""
        all_git_files = get_git_files(args.dir)
        if not all_git_files:
            return
        
        changed_files = self._get_changed_files(args.dir)
        if not changed_files:
            logging.info("No local changes detected. Exiting.")
            return

        # --- 2. Initial Analysis ---
        analysis = self.ai_agent.get_review_analysis(
            args.task, all_git_files, changed_files, app_desc_content
        )
        
        print("\n--- 🤖 AI Review Plan ---")
        print(f"Task: {args.task}\n")
        print(f"Reasoning:\n {analysis.reasoning}\n")
        print("Files to Review:", analysis.files_to_review or "None")
        print("Files for Context:", analysis.relevant_context_files or "None")
        print("--------------------------\n")

        proceed = input("Proceed with AI code review? (y/n): ").lower()
        if proceed != 'y':
            logging.info("Operation cancelled by user.")
            return

        # --- 3. Load Context and Review Files ---
        files_for_context = list(set(analysis.relevant_context_files + analysis.files_to_review))
        context_data: Dict[str, str] = {}
        logging.info("Pre-loading all file contents for review...")
        for fp in files_for_context:
            content = read_file_content(args.dir, fp)
            if content is not None:
                context_data[fp] = content
            else:
                logging.warning(f"Could not read file {fp}, it will be excluded from context.")

        all_reviews: List[FileReview] = []
        for file_to_review in analysis.files_to_review:
            if file_to_review not in context_data:
                logging.error(f"Cannot review {file_to_review} as its content could not be read.")
                continue

            # Build context string, excluding the file currently under review
            full_context = build_context_from_dict(
                context_data, self.ai_agent.summarize_code, exclude_file=file_to_review
            )
            
            file_content = context_data[file_to_review]
            
            review_result = self.ai_agent.review_file_content(
                args.task, full_context, file_to_review, file_content
            )
            all_reviews.append(review_result)

        # --- 4. Print Final Report ---
        self._print_review(all_reviews)


if __name__ == "__main__":
    cli = CliManager()
    cli.run()
