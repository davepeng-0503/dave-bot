#!/usr/bin/env python
import argparse
import json
import logging
import os
import subprocess
import webbrowser
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from html_utils import create_advice_analysis_html, create_advice_html
from shared_agents_utils import (
    AgentTools,
    BaseAiAgent,
    build_context_from_dict,
    get_git_files,
    read_file_content,
    wait_for_user_approval_from_browser,
)

# --- Configuration ---
MAX_ANALYSIS_GREP_RETRIES = 3
DEFAULT_SERVER_PORT = 8080

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# --- Pydantic Models for Advice Generation ---

class AdviceAnalysis(BaseModel):
    """Represents the initial analysis of the codebase to answer a question."""
    plan_for_advice: List[str] = Field(
        default=[],
        description="A detailed, step-by-step plan of how to formulate the advice based on the codebase."
    )
    relevant_files: List[str] = Field(
        default=[],
        description="A list of existing file paths that are most relevant to read for understanding the context to answer the question."
    )
    reasoning: str = Field(
        default="",
        description="A brief, high-level explanation of the overall strategy and why these files were chosen."
    )
    additional_grep_queries_needed: List[str] = Field(
        default=[],
        description="A list of additional 'git grep' queries that you believe would significantly improve your confidence in the plan. If you are less than 90% confident, you should request more information via grep. Leave empty if you are confident."
    )


class Advice(BaseModel):
    """Represents the final generated advice."""
    response: str = Field(description="The detailed advice or answer to the user's question, formatted in Markdown.")
    references: List[str] = Field(
        default=[],
        description="A list of file paths that were used as primary sources to formulate the advice."
    )
    requires_more_context: bool = Field(
        default=False,
        description="Set to true if you cannot provide advice due to insufficient context."
    )
    context_request: str = Field(
        default="",
        description="If requires_more_context is true, explain what specific information or files are needed."
    )


# --- Core Logic for AI Interaction ---

class AiAdviseAgent(BaseAiAgent):
    """Handles all interactions with the Gemini AI model for giving advice."""

    def get_advice_analysis(self, question: str, file_list: List[str], app_description: str = "", feedback: Optional[str] = None, previous_plan: Optional["AdviceAnalysis"] = None, git_grep_search_tool: Optional[Callable] = None, read_file_tool: Optional[Callable] = None, grep_results: Optional[str] = None) -> AdviceAnalysis:
        """Runs the agent to analyze the codebase for a given question."""
        
        system_prompt = f"""
You are an expert software developer and architect. Your goal is to analyze a codebase to find the best way to answer a user's question.

**Your Goal**: Create an `AdviceAnalysis` response. Your aim is to be at least 90% confident in your plan to gather context.

**You have access to these tools**:
1.  **`git_grep_search_tool(query: str)`**: Helps you find relevant code snippets and file locations. Use it to explore the codebase.
2.  **`read_file_tool(file_path: str)`**: Reads the entire content of a specific file. Use this when you need more context than `grep` can provide.

**The Process**:
1.  **Formulate a Plan**: Based on the user's question, create a step-by-step `plan_for_advice`.
2.  **Identify Files**: Determine `relevant_files` to read to gather the necessary context.
3.  **Verify with Tools**: Use `git_grep_search_tool` and `read_file_tool` to confirm your file choices and understand the code. You can call these tools multiple times.
4.  **Assess Confidence**: After your initial analysis and tool use, assess your confidence.
    - **If Confidence < 90%**: If you feel you're missing information, populate `additional_grep_queries_needed` with new search terms. If you do this, do not populate the other fields in the `AdviceAnalysis` object.
    - **If Confidence >= 90%**: If you are confident, leave `additional_grep_queries_needed` empty and provide the full `AdviceAnalysis`.

Project Description:
---
{app_description or "No description provided."}
---
"""
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

My question is: "{question}"
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
        
        tools: List[Callable] = []
        if git_grep_search_tool:
            tools.append(git_grep_search_tool)
        if read_file_tool:
            tools.append(read_file_tool)

        analysis_agent = Agent(
            self._get_gemini_model('gemini-2.5-flash'),
            output_type=AdviceAnalysis,
            system_prompt=system_prompt,
            tools=tools
        )
        
        log_message = "🤖 Conducting initial codebase analysis for your question..."
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

    def generate_advice(self, question: str, context: str, relevant_files: List[str]) -> Advice:
        """Generates the final advice based on the gathered context."""
        
        system_prompt = """
You are an expert software developer and technical advisor.
Your task is to provide a clear, concise, and helpful answer to the user's question based on the provided context from their codebase.

**IMPORTANT RULES**:
1.  Base your answer *only* on the provided context. Do not invent features or assume knowledge outside of what is given.
2.  Format your response using Markdown for readability (e.g., use headings, lists, code blocks).
3.  Be direct and answer the question. Start with the most important information.
4.  If the provided context is insufficient to answer the question, set `requires_more_context` to `true` and explain what's missing in `context_request`.
5.  In your final response, list the files you used as primary sources in the `references` field.
"""
        prompt = f"""
My question is: "{question}"

Context from relevant files in the project:
---
{context}
---

Based on this context, please provide your advice.
"""

        generation_agent = Agent(
            self._get_gemini_model('gemini-2.5-pro'), 
            output_type=Advice, 
            system_prompt=system_prompt
        )
        
        logging.info("💡 Formulating advice based on gathered context...")
        advice = generation_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        # The agent might not know which files were used, so we'll add them from the analysis.
        advice.output.references = relevant_files
        return advice.output


# --- CLI and File Operations ---

class CliManager:
    """Manages CLI interactions and orchestrates the advice generation process."""

    def __init__(self):
        """Initializes the CLI manager and the AI advise agent."""
        self.ai_agent = AiAdviseAgent()
        self.args = self._parse_args()
        self.agent_tools = AgentTools(self.args.dir)

    def _parse_args(self) -> argparse.Namespace:
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser(
            description="An AI agent that provides advice about a codebase based on a user's question."
        )
        parser.add_argument(
            "--task", type=str, required=True, help="The question you want to ask about the codebase."
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
            help="Bypass user confirmation and proceed with advice generation automatically."
        )
        parser.add_argument(
            "--port", type=int, default=DEFAULT_SERVER_PORT,
            help=f"The port to run the local web server on for user approval (default: {DEFAULT_SERVER_PORT})."
        )
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

    def run(self):
        """The main entry point for the CLI tool."""
        # 1. Initial Setup
        app_desc_content = read_file_content(self.args.dir, self.args.app_description) or ""
        all_repo_files = self._get_all_repository_files()
        if not all_repo_files:
            logging.error("No tracked files found in this git repository. Exiting.")
            return

        # 2. Analysis and Confirmation Loop
        analysis: Optional[AdviceAnalysis] = None
        previous_analysis: Optional[AdviceAnalysis] = None
        user_feedback: Optional[str] = None

        while True:  # This loop handles user feedback on the plan
            # A. Get Analysis
            if user_feedback:
                analysis = self.ai_agent.get_advice_analysis(
                    self.args.task,
                    all_repo_files,
                    app_desc_content,
                    feedback=user_feedback,
                    previous_plan=previous_analysis,
                    git_grep_search_tool=self.agent_tools.git_grep_search,
                    read_file_tool=self.agent_tools.read_file
                )
                user_feedback = None
            else:
                # Grep confidence loop
                grep_results = ""
                analysis_retries = 0
                while analysis_retries < MAX_ANALYSIS_GREP_RETRIES:
                    current_analysis = self.ai_agent.get_advice_analysis(
                        self.args.task,
                        all_repo_files,
                        app_desc_content,
                        git_grep_search_tool=self.agent_tools.git_grep_search,
                        read_file_tool=self.agent_tools.read_file,
                        grep_results=grep_results or None
                    )

                    if current_analysis.additional_grep_queries_needed:
                        analysis_retries += 1
                        logging.info("🤖 AI has requested more information via git grep. Running queries.")
                        new_results = [self.agent_tools.git_grep_search(q) for q in current_analysis.additional_grep_queries_needed]
                        grep_results = "\n\n".join(new_results)
                        analysis = None
                    else:
                        analysis = current_analysis
                        break
                
                if not analysis:
                    logging.error(f"❌ Failed to get a confident analysis after {MAX_ANALYSIS_GREP_RETRIES} attempts.")
                    return

            # B. Display Analysis and get confirmation
            logging.info("✅ Analysis complete. Awaiting user confirmation in browser.")
            plan_html_path = create_advice_analysis_html(analysis, self.args.task, self.args.port)
            if not plan_html_path:
                return  # Error already logged

            if not analysis.relevant_files and not analysis.plan_for_advice:
                logging.warning("AI analysis resulted in no relevant files to read. The advice may be generic. Proceeding...")
                break

            # C. User Confirmation
            if not self.args.force:
                webbrowser.open(f"file://{os.path.realpath(plan_html_path)}")
                decision, data = wait_for_user_approval_from_browser(os.path.realpath(plan_html_path), self.args.port)

                if decision == 'approve':
                    logging.info("✅ Plan approved by user. Proceeding with advice generation.")
                    break
                elif decision == 'reject':
                    logging.info("❌ Plan rejected by user. Operation cancelled.")
                    return
                elif decision == 'feedback':
                    user_feedback = data
                    previous_analysis = analysis
                    logging.info(f"Re-running analysis with new feedback...")
                    # continue loop
                else:
                    logging.error("No decision received from the browser. Exiting.")
                    return
            else:
                logging.info("✅ Plan approved automatically (--force).")
                break

        # 3. Gather Context
        logging.info("Gathering context from relevant files...")
        if not analysis.relevant_files:
            logging.warning("AI analysis resulted in no relevant files to read. The advice may be generic.")
            context_str = "No relevant files were found to provide context."
        else:
            context_data: Dict[str, str] = {}
            for fp in analysis.relevant_files:
                content = read_file_content(self.args.dir, fp)
                if content is not None:
                    context_data[fp] = content
            context_str = build_context_from_dict(context_data, self.ai_agent.summarize_code)

        # 4. Generate Final Advice
        advice = self.ai_agent.generate_advice(self.args.task, context_str, analysis.relevant_files)

        if advice.requires_more_context:
            logging.error("❌ The AI could not provide advice with the current context.")
            logging.error(f"Reason: {advice.context_request}")
            return

        # 5. Display Advice
        logging.info("✅ Advice generated successfully. Opening in web browser.")
        advice_html_path = create_advice_html(advice, self.args.task)
        if advice_html_path:
            webbrowser.open(f"file://{os.path.realpath(advice_html_path)}")


if __name__ == "__main__":
    cli = CliManager()
    cli.run()
