#!/usr/bin/env python
import argparse
import json
import logging
import os
import queue
import subprocess
import threading
import time
import webbrowser
from typing import Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

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

    def get_initial_analysis(self, task: str, file_list: List[str], app_description: str = "", feedback: Optional[str] = None, previous_plan: Optional[CodeAnalysis] = None, git_grep_search_tool: Optional[Callable] = None, read_file_tool: Optional[Callable] = None, grep_results: Optional[str] = None) -> CodeAnalysis:
        """Runs the agent to get the code analysis, potentially using feedback or a search tool."""
        
        system_prompt = f"""
You are an expert software developer planning a coding task. Your goal is to create a comprehensive plan to modify a codebase.

**Your Goal**: Create a `CodeAnalysis` response. Your aim is to be at least 90% confident in your plan.

**You have access to these tools**:
1.  **`git_grep_search_tool(query: str)`**: Helps you find relevant code snippets and file locations. Use it to explore the codebase.
2.  **`read_file_tool(file_path: str)`**: Reads the entire content of a specific file. Use this when you need more context than `grep` can provide.

**The Process**:
1.  **Formulate a Plan**: Based on the task, create a step-by-step `plan`.
2.  **Identify Files**: Determine `files_to_edit`, `files_to_create`, and `relevant_files` for context.
3.  **Verify with Tools**: Use `git_grep_search_tool` and `read_file_tool` to confirm your file choices and understand the code. You can call these tools multiple times within a single turn.
4.  **Assess Confidence**: After your initial analysis and tool use, assess your confidence.
    - **If Confidence < 90%**: If you feel you're missing information or your plan is too speculative, populate `additional_grep_queries_needed` with new search terms that would help you build a better plan. If you do this, do not populate the other fields in the `CodeAnalysis` object.
    - **If Confidence >= 90%**: If you are confident, leave `additional_grep_queries_needed` empty and provide the full `CodeAnalysis`, including the `plan`, file lists, and `generation_order`.

**CRITICAL**:
- **`plan`**: This should be a detailed, step-by-step description of the changes you will make.
- **`generation_order`**: This is the most important part of your execution plan. It must list all files from `files_to_edit` and `files_to_create` in the correct dependency order.

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
        
        tools = []
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

        generation_agent = Agent(
            self._get_gemini_model('gemini-2.5-pro'), 
            output_type=GeneratedCode, 
            system_prompt=system_prompt
        )
        
        logging.info(f"💡 Generating new code for {file_path}...")
        generated_code = generation_agent.run_sync(
            prompt,
            model_settings=GoogleModelSettings(google_safety_settings=self.get_safety_settings()),
        )
        return generated_code.output


# --- CLI and File Operations ---

class CliManager:
    """Manages CLI interactions, file I/O, and orchestrates the analysis and code generation."""

    _COMMON_STYLE = """
<style>
    :root {
        --primary-color: #4a90e2;
        --secondary-color: #50e3c2;
        --background-color: #f4f7f9;
        --container-bg-color: #ffffff;
        --text-color: #333;
        --heading-color: #1a2533;
        --border-color: #e0e6ed;
        --code-bg-color: #2d2d2d;
        --code-text-color: #f8f8f2;
        --inline-code-bg: #eef2f5;
        --inline-code-text: #d6336c;
        --success-color: #2ecc71;
        --danger-color: #e74c3c;
        --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
    }

    body {
        font-family: var(--font-family);
        line-height: 1.7;
        padding: 2rem;
        background-color: var(--background-color);
        color: var(--text-color);
        margin: 0;
    }

    .main-container {
        max-width: 1100px;
        margin: auto;
    }

    h1, h2, h3 {
        color: var(--heading-color);
        font-weight: 700;
        margin-top: 2rem;
        margin-bottom: 1rem;
    }

    h1 {
        text-align: center;
        font-size: 2.8em;
        margin-bottom: 2rem;
        background: linear-gradient(45deg, var(--primary-color), var(--secondary-color));
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }

    h2 {
        font-size: 1.8em;
        border-bottom: 3px solid var(--primary-color);
        padding-bottom: 0.5rem;
    }

    .container {
        background-color: var(--container-bg-color);
        border: 1px solid var(--border-color);
        padding: 2rem;
        margin-bottom: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(26, 37, 51, 0.07);
        transition: transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out;
    }

    .container:hover {
        transform: translateY(-3px);
        box-shadow: 0 12px 32px rgba(26, 37, 51, 0.1);
    }

    ul, ol {
        padding-left: 2rem;
    }

    li {
        margin-bottom: 0.75rem;
    }

    code {
        background-color: var(--inline-code-bg);
        color: var(--inline-code-text);
        padding: 0.2em 0.4em;
        margin: 0;
        font-size: 85%;
        border-radius: 6px;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    }

    pre {
        background-color: var(--code-bg-color);
        color: var(--code-text-color);
        padding: 1.5rem;
        border-radius: 8px;
        overflow-x: auto;
        white-space: pre-wrap;
        word-wrap: break-word;
    }

    pre code {
        background-color: transparent;
        color: inherit;
        padding: 0;
        margin: 0;
        font-size: inherit;
        border-radius: 0;
    }

    blockquote {
        border-left: 5px solid var(--primary-color);
        padding-left: 1.5rem;
        color: #555;
        margin-left: 0;
        font-style: italic;
    }

    table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 1.5rem;
        box-shadow: 0 4px 8px rgba(0,0,0,0.05);
        border-radius: 8px;
        overflow: hidden;
    }

    th, td {
        border: 1px solid var(--border-color);
        padding: 0.8rem 1rem;
        text-align: left;
    }

    th {
        background-color: var(--primary-color);
        color: white;
        font-weight: 500;
    }

    tr:nth-child(even) {
        background-color: #f9fafb;
    }

    .actions {
        text-align: center;
        margin-top: 2rem;
        padding-top: 2rem;
        border-top: 1px solid var(--border-color);
    }

    .actions button {
        color: white;
        border: none;
        padding: 1rem 2rem;
        font-size: 1rem;
        font-weight: 500;
        border-radius: 8px;
        cursor: pointer;
        margin: 0.5rem;
        transition: all 0.3s ease;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .actions button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.15);
    }

    .actions button:disabled {
        background-color: #bdc3c7;
        cursor: not-allowed;
        transform: none;
        box-shadow: none;
    }

    .approve-btn { background-color: var(--primary-color); }
    .approve-btn:hover { background-color: #3a82d2; }

    .reject-btn { background-color: var(--danger-color); }
    .reject-btn:hover { background-color: #c0392b; }

    .feedback-btn { background-color: var(--success-color); }
    .feedback-btn:hover { background-color: #27ae60; }

    .feedback-form {
        margin-top: 2rem;
        background-color: #fdfdfe;
        padding: 1.5rem;
        border-radius: 8px;
        border: 1px solid var(--border-color);
        text-align: left;
    }

    .feedback-form h3 {
        margin-top: 0;
        color: var(--heading-color);
        font-size: 1.2em;
    }

    .feedback-form textarea {
        width: calc(100% - 2rem);
        min-height: 100px;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid var(--border-color);
        margin-bottom: 1rem;
        font-family: var(--font-family);
        font-size: 1rem;
        resize: vertical;
    }
</style>
"""

    def __init__(self):
        """Initializes the CLI manager and the AI code agent."""
        self.ai_agent = AiCodeAgent()
        self.args = self._parse_args()
        self.agent_tools = AgentTools(self.args.dir)
        self.status_queue: Optional[queue.Queue] = None

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

    def _validate_analysis(self, analysis: CodeAnalysis) -> bool:
        """Validates the AI's plan for consistency."""
        planned_files: Set[str] = set(analysis.files_to_edit) | {f.file_path for f in analysis.files_to_create}
        ordered_files: Set[str] = set(analysis.generation_order)

        if planned_files != ordered_files:
            logging.error("Analysis Error: Mismatch between files to change and the generation order.")
            missing_from_order = planned_files - ordered_files
            extra_in_order = ordered_files - planned_files
            if missing_from_order:
                logging.error(f"  - Planned but not in order: {missing_from_order}")
            if extra_in_order:
                logging.error(f"  - In order but not planned: {extra_in_order}")
            return False
        return True

    def _format_files_to_create_html(self, files_to_create: List[NewFile]) -> str:
        """Formats the list of files to create into an HTML table."""
        if not files_to_create:
            return "<p>None</p>"
        
        table_rows = ""
        for file in files_to_create:
            suggestions_html = "<ul>" + "".join([f"<li><code>{sug}</code></li>" for sug in file.content_suggestions]) + "</ul>" if file.content_suggestions else "None"
            table_rows += f"""
            <tr>
                <td><code>{file.file_path}</code></td>
                <td>{file.reasoning}</td>
                <td>{suggestions_html}</td>
            </tr>
            """

        return f"""
        <table>
            <thead>
                <tr>
                    <th>File Path</th>
                    <th>Reasoning</th>
                    <th>Content Suggestions</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
        """

    def _create_and_open_plan_html(self, analysis: CodeAnalysis) -> str:
        """Generates an HTML report for the analysis and returns the file path."""
        if not analysis:
            return ""

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Code Generation Plan</title>
    {self._COMMON_STYLE}
</head>
<body>
    <div id="main-content" class="main-container">
        <h1>🤖 AI Code Generation Plan</h1>

        <div class="container">
            <h2>Task</h2>
            <p>{self.args.task}</p>
        </div>

        <div class="container">
            <h2>High-level Plan</h2>
            <ol>
                {''.join([f'<li>{step}</li>' for step in analysis.plan]) if analysis.plan else "<li>No plan provided.</li>"}
            </ol>
        </div>

        <div class="container">
            <h2>Overall Reasoning</h2>
            <p>{analysis.reasoning or "No reasoning provided."}</p>
        </div>

        <div class="container">
            <h2>File Breakdown</h2>

            <h3>Relevant Files for Context</h3>
            <ul>
                {''.join([f'<li><code>{file}</code></li>' for file in analysis.relevant_files]) if analysis.relevant_files else "<li>None</li>"}
            </ul>

            <h3>Files to Edit</h3>
            <ul>
                {''.join([f'<li><code>{file}</code></li>' for file in analysis.files_to_edit]) if analysis.files_to_edit else "<li>None</li>"}
            </ul>

            <h3>Files to Create</h3>
            {self._format_files_to_create_html(analysis.files_to_create)}
        </div>
        
        <div class="container">
            <h2>Proposed Generation Order</h2>
            <ol>
                {''.join([f'<li><code>{file}</code></li>' for file in analysis.generation_order]) if analysis.generation_order else "<li>None</li>"}
            </ol>
        </div>

        <div class="container actions">
            <h2>Confirm Plan</h2>
            <p>Do you want to proceed with generating the code based on this plan?</p>
            <button class="approve-btn" onclick="sendDecision('approve')">Approve & Generate Code</button>
            <button class="reject-btn" onclick="sendDecision('reject')">Reject</button>
            <div class="feedback-form">
                <h3>Refine the Plan</h3>
                <p>If the plan isn't quite right, provide feedback below and submit it for a new plan.</p>
                <textarea id="feedback-text" placeholder="e.g., 'Please also create a new file for utility functions' or 'The plan seems to miss the point about Y'"></textarea>
                <br>
                <button class="feedback-btn" onclick="sendFeedback()">Submit Feedback</button>
            </div>
        </div>
    </div>

    <script>
        const port = {self.args.port};
        const mainContent = document.getElementById('main-content');

        function escapeHtml(unsafe) {{
            return unsafe
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        }}

        function showMessage(title, message) {{
            mainContent.innerHTML = `<div class="container"><h1>${{title}}</h1><p>${{message}}</p></div>`;
        }}

        function pollStatus() {{
            fetch(`http://localhost:${{port}}/status`)
                .then(response => {{
                    if (response.status === 204) {{
                        setTimeout(pollStatus, 1000); // Poll again
                        return null;
                    }}
                    if (!response.ok) throw new Error(`HTTP error! status: ${{response.status}}`);
                    return response.json();
                }})
                .then(data => {{
                    if (!data) return;

                    const logContainer = document.getElementById('generation-log');
                    if (!logContainer) return;

                    // Clear "Waiting for generation to start..." message on first update
                    if (logContainer.querySelector('p')?.textContent.includes('Waiting for generation')) {{
                        logContainer.innerHTML = '';
                    }}

                    if (data.status === 'writing') {{
                        const writingElement = document.createElement('p');
                        // Create a unique but valid ID for the element
                        const elementId = `writing-${{data.file_path.replace(/[^a-zA-Z0-9]/g, '-')}}`;
                        writingElement.id = elementId;
                        writingElement.innerHTML = `Writing file: <code>${{data.file_path}}</code>...`;
                        logContainer.appendChild(writingElement);

                    }} else if (data.status === 'done') {{
                        // Remove the "writing..." message for this file
                        const elementId = `writing-${{data.file_path.replace(/[^a-zA-Z0-9]/g, '-')}}`;
                        const writingElement = document.getElementById(elementId);
                        if (writingElement) {{
                            writingElement.remove();
                        }}

                        const doneElement = document.createElement('div');
                        doneElement.className = 'file-generation-result';
                        doneElement.style.marginBottom = '1.5rem';
                        doneElement.innerHTML = `
                            <h3>Generated File: <code>${{data.file_path}}</code></h3>
                            <pre><code>${{escapeHtml(data.code)}}</code></pre>
                        `;
                        logContainer.appendChild(doneElement);

                    }} else if (data.status === 'finished') {{
                        const finishedElement = document.createElement('p');
                        finishedElement.style.marginTop = '1rem';
                        finishedElement.style.color = 'var(--success-color)';
                        finishedElement.innerHTML = '✅ All files generated successfully! You can close this window.';
                        logContainer.appendChild(finishedElement);
                        return; // Stop polling
                    }}
                    setTimeout(pollStatus, 500); // Poll for next update
                }})
                .catch(err => {{
                    const logContainer = document.getElementById('generation-log');
                    if (logContainer) {{
                        logContainer.innerHTML += `<p style="color: var(--danger-color);">Connection to server lost. Please check the agent's console output.</p>`;
                    }}
                    console.error('Error polling status:', err);
                }});
        }}

        function sendDecision(decision) {{
            if (decision === 'approve') {{
                // Disable all action buttons to prevent re-submission
                document.querySelectorAll('.actions button').forEach(button => button.disabled = true);

                // Create a new container for the generation status and append it
                const generationContainer = document.createElement('div');
                generationContainer.className = 'container';
                generationContainer.innerHTML = `
                    <h2>⚙️ Code Generation Progress</h2>
                    <div id="generation-log">
                        <p>Waiting for generation to start...</p>
                    </div>
                `;
                // Find the actions container and insert the new container before it
                const actionsContainer = document.querySelector('.actions');
                if (actionsContainer) {{
                    actionsContainer.parentNode.insertBefore(generationContainer, actionsContainer);
                }} else {{
                    // Fallback if actions container isn't found
                    mainContent.appendChild(generationContainer);
                }}
                
                fetch(`http://localhost:${{port}}/approve`, {{ method: 'POST' }})
                    .then(res => {{
                        if (!res.ok) throw new Error('Approval request failed');
                        pollStatus();
                    }})
                    .catch(err => {{
                        const log = document.getElementById('generation-log');
                        if (log) log.innerHTML = `<p style="color: var(--danger-color);">Could not start generation process. Check the agent's console.</p>`;
                        console.error('Error sending approval:', err);
                    }});
                return;
            }}

            const isFeedback = decision === 'feedback';
            let fetchOptions = {{ method: 'POST' }};
            let url = `http://localhost:${{port}}/${{decision}}`;

            if (isFeedback) {{
                const feedback = document.getElementById('feedback-text').value;
                if (!feedback) {{
                    alert('Please enter feedback before submitting.');
                    return;
                }}
                url = `http://localhost:${{port}}/feedback`;
                fetchOptions.headers = {{ 'Content-Type': 'application/json' }};
                fetchOptions.body = JSON.stringify({{ feedback: feedback }});
            }}

            fetch(url, fetchOptions)
                .then(response => response.text())
                .then(text => {{
                    const message = isFeedback ? 'The agent is re-analyzing. You can close this tab now.' : text;
                    const title = isFeedback ? 'Feedback Submitted' : 'Decision Received';
                    showMessage(title, message);
                    setTimeout(() => window.close(), 3000);
                }})
                .catch(err => {{
                    showMessage('Error', `Could not contact server while sending '${{decision}}'.`);
                    console.error(`Error sending ${{decision}}:`, err);
                }});
        }}

        function sendFeedback() {{
            sendDecision('feedback');
        }}
    </script>
</body>
</html>
        """

        plan_file_path = os.path.join(self.args.dir, "plan.html")
        try:
            with open(plan_file_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            logging.info(f"✅ Plan saved to {plan_file_path}")
            return plan_file_path
        except Exception as e:
            logging.error(f"❌ Could not write the HTML plan: {e}")
            return ""

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
                    remaining_order, context_data.get(file_path), strict=self.args.strict
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
                    self.status_queue.put({"status": "done", "file_path": file_path, "code": generated_code.code})

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

            # B. Display Analysis and get confirmation
            logging.info("✅ Analysis complete. Awaiting user confirmation in browser.")
            plan_html_path = self._create_and_open_plan_html(analysis)
            if not plan_html_path or not self._validate_analysis(analysis):
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
                                update = self.cli_manager.status_queue.get(block=True, timeout=28)
                                self._send_response(200, 'application/json', json.dumps(update).encode('utf-8'))
                            except (queue.Empty, AttributeError):
                                self._send_response(204, 'text/plain', b'')
                        else:
                            super().do_GET()

                server = ApprovalWebServer(("", self.args.port), StatusAwareApprovalHandler, html_file_path=os.path.realpath(plan_html_path))
                self.status_queue = queue.Queue()
                server_thread = threading.Thread(target=server.serve_forever)
                server_thread.daemon = True
                server_thread.start()

                webbrowser.open(f"file://{os.path.realpath(plan_html_path)}")
                decision, data = server.wait_for_decision()

                if decision == 'approve':
                    logging.info("✅ Plan approved by user. Proceeding with code generation.")
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
                break

        try:
            # 5. Iterative Generation
            unprocessed_files = self._execute_generation_loop(analysis, all_repo_files, app_desc_content)
            # 6. Final Status
            self._report_final_status(unprocessed_files)
            if server and self.status_queue:
                self.status_queue.put({"status": "finished"})
                time.sleep(5) # Give browser time to fetch final status
        finally:
            if server:
                logging.info("Shutting down web server.")
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    cli = CliManager()
    cli.run()
