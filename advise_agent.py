#!/usr/bin/env python
import argparse
import json
import logging
import os
import subprocess
import webbrowser
from typing import Callable, Dict, List, Optional

import markdown
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from shared_agents_utils import (
    BaseAiAgent,
    build_context_from_dict,
    get_git_files,
    read_file_content,
    read_file_for_agent_tool,
)

# --- Configuration ---
MAX_ANALYSIS_GREP_RETRIES = 3

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

class GitGrepSearchInput(BaseModel):
    """Input model for the git grep search tool."""
    query: str = Field(description="The keyword or regex pattern to search for within the git repository.")

class ReadFileContentInput(BaseModel):
    """Input model for the read file content tool."""
    file_path: str = Field(description="The path of the file to read.")

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

    def get_advice_analysis(self, question: str, file_list: List[str], app_description: str = "", git_grep_search_tool: Optional[Callable] = None, read_file_tool: Optional[Callable] = None, grep_results: Optional[str] = None) -> AdviceAnalysis:
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
        
        tools = []
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
        if grep_results:
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
        return parser.parse_args()

    def _read_file_content_tool(self, file_path: str) -> str:
        """Reads the full content of a specific file within the project directory."""
        logging.info(f"🛠️ Agent requested to read file: '{file_path}'")
        return read_file_for_agent_tool(self.args.dir, file_path)

    def _git_grep_search_tool(self, query: str) -> str:
        """Performs a case-insensitive 'git grep' search in the codebase."""
        logging.info(f"🛠️ Running git grep search for: '{query}'")
        try:
            result = subprocess.run(
                ['git', 'grep', '-i', '-n', query],
                cwd=self.args.dir,
                capture_output=True,
                text=True,
                check=False
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

    def _create_and_open_advice_html(self, advice: Advice, analysis: AdviceAnalysis):
        """Generates an HTML report from the advice and opens it."""
        
        response_html = markdown.markdown(advice.response, extensions=['fenced_code', 'tables'])

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI-Generated Advice</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; padding: 20px; max-width: 1000px; margin: auto; background-color: #f7f9fc; color: #333; }}
        h1, h2 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h1 {{ text-align: center; font-size: 2.5em; color: #1a2533; }}
        .container {{ background-color: #fff; border: 1px solid #ddd; padding: 25px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.05); }}
        ul, ol {{ padding-left: 25px; }}
        li {{ margin-bottom: 12px; }}
        code {{ background-color: #ecf0f1; padding: 3px 6px; border-radius: 4px; font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 0.95em; color: #c0392b; }}
        pre code {{ white-space: pre-wrap; display: block; padding: 15px; background-color: #2d3436; color: #dfe6e9; border-radius: 5px; }}
        blockquote {{ border-left: 4px solid #3498db; padding-left: 15px; color: #666; margin-left: 0; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
    </style>
</head>
<body>
    <h1>🤖 AI-Generated Advice 🤖</h1>

    <div class="container">
        <h2>Your Question</h2>
        <p>{self.args.task}</p>
    </div>

    <div class="container">
        <h2>Advice</h2>
        {response_html}
    </div>

    <div class="container">
        <h2>References</h2>
        <p>This advice was formulated based on the following files:</p>
        <ul>
            {''.join([f'<li><code>{file}</code></li>' for file in advice.references]) if advice.references else "<li>No specific files were referenced.</li>"}
        </ul>
    </div>

</body>
</html>
        """

        advice_file_path = os.path.join(self.args.dir, "advice.html")
        try:
            with open(advice_file_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logging.info(f"✅ Advice saved to {advice_file_path}")
            webbrowser.open(f"file://{os.path.realpath(advice_file_path)}")
        except Exception as e:
            logging.error(f"❌ Could not write or open the HTML advice file: {e}")

    def run(self):
        """The main entry point for the CLI tool."""
        # 1. Initial Setup
        app_desc_content = read_file_content(self.args.dir, self.args.app_description) or ""
        all_repo_files = self._get_all_repository_files()
        if not all_repo_files:
            logging.error("No tracked files found in this git repository. Exiting.")
            return

        # 2. Analysis Loop to Gain Confidence
        analysis: Optional[AdviceAnalysis] = None
        grep_results = ""
        analysis_retries = 0
        while analysis_retries < MAX_ANALYSIS_GREP_RETRIES:
            current_analysis = self.ai_agent.get_advice_analysis(
                self.args.task,
                all_repo_files,
                app_desc_content,
                git_grep_search_tool=self._git_grep_search_tool,
                read_file_tool=self._read_file_content_tool,
                grep_results=grep_results or None
            )

            if current_analysis.additional_grep_queries_needed:
                analysis_retries += 1
                logging.info("🤖 AI has requested more information via git grep to improve its plan. Running queries automatically.")

                new_results = []
                for query in current_analysis.additional_grep_queries_needed:
                    result = self._git_grep_search_tool(query)
                    new_results.append(result)
                
                grep_results = "\n\n".join(new_results)
                analysis = None  # Not a final analysis
            else:
                analysis = current_analysis
                break  # We have a final analysis

        if not analysis:
            logging.error(f"❌ Failed to get a confident analysis from the AI after {MAX_ANALYSIS_GREP_RETRIES} attempts.")
            return

        logging.info("✅ Analysis complete. Identified relevant files for context.")
        
        # 3. Gather Context
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
        self._create_and_open_advice_html(advice, analysis)


if __name__ == "__main__":
    # The markdown library is an optional dependency for displaying the report.
    try:
        import markdown
    except ImportError:
        print("Please install the 'markdown' library for HTML report generation: pip install markdown")
        exit(1)
        
    cli = CliManager()
    cli.run()
