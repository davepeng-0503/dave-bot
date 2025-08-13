#!/usr/bin/env python
"""
Utilities for generating and managing HTML content for user interaction.

This module centralizes the creation of HTML pages used by different agents
to display plans, gather feedback, and show results.
"""

import logging
import tempfile
from typing import TYPE_CHECKING, List, Optional

import markdown

# Use TYPE_CHECKING to avoid circular imports at runtime.
# The agent files will import this module, and this module needs type hints from them.
if TYPE_CHECKING:
    from advise_agent import Advice, AdviceAnalysis
    from code_agent import CodeAnalysis, NewFile


# --- Shared HTML Components ---

COMMON_STYLE = """
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

    h1, h2, h3, h4 {
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
    
    h3 {
        font-size: 1.4em;
    }
    
    h4 {
        font-size: 1.1em;
        color: #555;
        margin-top: 1.5rem;
        margin-bottom: 0.5rem;
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
        background-color: #f9fafb;
        padding-top: 0.5rem;
        padding-bottom: 0.5rem;
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

    .model-toggle {
        margin-top: 1.5rem;
        margin-bottom: 1.5rem;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.9em;
        background-color: #f9fafb;
        padding: 0.75rem;
        border-radius: 8px;
        border: 1px solid var(--border-color);
    }
    .model-toggle input[type="checkbox"] {
        margin-right: 0.75rem;
        width: 16px;
        height: 16px;
        cursor: pointer;
    }
    .model-toggle label {
        cursor: pointer;
        color: #555;
        font-weight: 500;
    }

    .progress-bar-container {
        width: 100%;
        background-color: #e0e6ed;
        border-radius: 8px;
        margin-top: 1rem;
        margin-bottom: 1.5rem;
        overflow: hidden; /* To keep the inner bar's corners rounded */
    }

    .progress-bar {
        width: 0%;
        height: 24px;
        background-color: var(--primary-color);
        transition: width 0.5s ease-in-out;
        text-align: center;
        line-height: 24px;
        color: white;
        font-weight: 500;
        font-size: 0.9em;
    }

    /* --- Timeline Styles --- */
    .timeline {
        position: relative;
        max-width: 900px;
        margin: 2rem auto;
        padding: 2rem 0;
    }

    .timeline::after {
        content: '';
        position: absolute;
        width: 4px;
        background-color: var(--primary-color);
        top: 0;
        bottom: 0;
        left: 50%;
        margin-left: -2px;
        border-radius: 2px;
    }

    .timeline-item {
        padding: 10px 40px;
        position: relative;
        background-color: inherit;
        width: 50%;
    }

    .timeline-item.left {
        left: 0;
    }

    .timeline-item.right {
        left: 50%;
    }

    .timeline-item::after {
        content: '';
        position: absolute;
        width: 20px;
        height: 20px;
        right: -11px;
        background-color: white;
        border: 4px solid var(--primary-color);
        top: 25px;
        border-radius: 50%;
        z-index: 1;
    }

    .timeline-item.right::after {
        left: -9px;
    }

    .timeline-content {
        padding: 20px 30px;
        background-color: white;
        position: relative;
        border-radius: 8px;
        border: 1px solid var(--border-color);
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
    .timeline-content h3 {
        margin-top: 0;
        font-size: 1.2em;
    }
    .timeline-content code {
        font-size: 95%;
    }
</style>
"""

# --- Code Agent HTML Generation ---


def _format_files_to_create_html(files_to_create: List["NewFile"]) -> str:
    """Formats the list of files to create into an HTML table."""
    if not files_to_create:
        return "<p>None</p>"

    table_rows = ""
    for file in files_to_create:
        suggestions_html = (
            "<ul>"
            + "".join([f"<li><code>{sug}</code></li>" for sug in file.content_suggestions])
            + "</ul>"
            if file.content_suggestions
            else "None"
        )
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


def create_code_plan_html(analysis: "CodeAnalysis", task: str, port: int) -> Optional[str]:
    """Generates an HTML report for the code generation plan and returns the file path."""
    if not analysis:
        return None

    plan_html = "".join([f'{markdown.markdown(step, extensions=["fenced_code", "tables"])}' for step in analysis.plan])

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Code Generation Plan</title>
    {COMMON_STYLE}
</head>
<body>
    <div id="main-content" class="main-container">
        <h1>🤖 AI Code Generation Plan</h1>

        <div class="container">
            <h2>Task</h2>
            <p>{task}</p>
        </div>

        <div class="container">
            <h2>High-level Plan</h2>
            {plan_html if analysis.plan else "<p>No plan provided.</p>"}
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
            {_format_files_to_create_html(analysis.files_to_create)}
        </div>
        
        <div class="container">
            <h2>Proposed Generation Order</h2>
            <ol>
                {''.join([f'<li><code>{file}</code></li>' for file in analysis.generation_order]) if analysis.generation_order else "<li>None</li>"}
            </ol>
        </div>

        <div id="actions-container" class="container actions">
            <h2>Confirm Plan</h2>
            <p>Do you want to proceed with generating the code based on this plan?</p>
            
            <div class="model-toggle">
                <input type="checkbox" id="use-flash-model" name="use-flash-model" {'checked' if analysis.use_flash_model else ''}>
                <label for="use-flash-model">Override: Use Gemini Flash Model (faster, for simple tasks)</label>
            </div>

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
        const port = {port};
        const mainContent = document.getElementById('main-content');
        const totalFiles = {len(analysis.generation_order) if analysis.generation_order else 0};
        let completedFiles = 0;
        let progressUpdater = null;
        let currentFileStartTime = null;
        const estimatedTimePerFile = 180; // 3 minutes in seconds
        let timelineItemCounter = 0;

        function escapeHtml(unsafe) {{
            if (typeof unsafe !== 'string') {{
                return '';
            }}
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

        function updateProgressBar() {{
            if (!currentFileStartTime) return;
            const elapsedTime = (Date.now() - currentFileStartTime) / 1000;
            const currentFileTimeProgress = Math.min(1.0, elapsedTime / estimatedTimePerFile);
            const completedProgress = (completedFiles / totalFiles);
            const currentProgress = (currentFileTimeProgress / totalFiles);
            const totalPercentage = Math.min(99, Math.floor((completedProgress + currentProgress) * 100));
            const progressBar = document.getElementById('generation-progress-bar');
            if (progressBar) {{
                progressBar.style.width = `${{totalPercentage}}%`;
                progressBar.textContent = `${{totalPercentage}}% Complete`;
            }}
        }}

        function pollStatus() {{
            fetch(`http://localhost:${{port}}/status`)
                .then(response => {{
                    if (response.status === 204) {{
                        setTimeout(pollStatus, 1000);
                        return null;
                    }}
                    if (!response.ok) throw new Error(`HTTP error! status: ${{response.status}}`);
                    return response.json();
                }})
                .then(data => {{
                    if (!data) return;

                    const logContainer = document.getElementById('generation-log');
                    if (!logContainer) return;

                    if (timelineItemCounter === 0 && logContainer.querySelector('.placeholder')) {{
                        logContainer.innerHTML = '';
                    }}

                    if (data.status === 'writing') {{
                        if (progressUpdater) clearInterval(progressUpdater);
                        currentFileStartTime = Date.now();
                        progressUpdater = setInterval(updateProgressBar, 1000);

                        const side = timelineItemCounter % 2 === 0 ? 'left' : 'right';
                        const elementId = `item-${{data.file_path.replace(/[^a-zA-Z0-9]/g, '-')}}`;
                        
                        const timelineItem = document.createElement('div');
                        timelineItem.id = elementId;
                        timelineItem.className = `timeline-item ${{side}}`;
                        timelineItem.innerHTML = `
                            <div class="timeline-content">
                                <h3>⏳ Generating File...</h3>
                                <code>${{escapeHtml(data.file_path)}}</code>
                            </div>
                        `;
                        logContainer.appendChild(timelineItem);
                        timelineItemCounter++;

                    }} else if (data.status === 'done') {{
                        if (progressUpdater) {{
                            clearInterval(progressUpdater);
                            progressUpdater = null;
                        }}
                        currentFileStartTime = null;
                        completedFiles++;
                        
                        const percentage = totalFiles > 0 ? Math.round((completedFiles / totalFiles) * 100) : 0;
                        const progressBar = document.getElementById('generation-progress-bar');
                        if (progressBar) {{
                            progressBar.style.width = `${{percentage}}%`;
                            progressBar.textContent = `${{percentage}}% Complete`;
                        }}

                        const elementId = `item-${{data.file_path.replace(/[^a-zA-Z0-9]/g, '-')}}`;
                        const timelineItem = document.getElementById(elementId);
                        
                        if (timelineItem) {{
                            timelineItem.innerHTML = `
                                <div class="timeline-content">
                                    <h3>✅ File Complete: <code>${{escapeHtml(data.file_path)}}</code></h3>
                                    <h4>Summary of Changes</h4>
                                    <p>${{escapeHtml(data.summary || 'No summary provided.')}}</p>
                                    <h4>Reasoning for Changes</h4>
                                    <blockquote>${{escapeHtml(data.reasoning || 'No reasoning provided.')}}</blockquote>
                                </div>
                            `;
                        }}

                    }} else if (data.status === 'finished') {{
                        if (progressUpdater) clearInterval(progressUpdater);
                        currentFileStartTime = null;

                        const progressBar = document.getElementById('generation-progress-bar');
                        if (progressBar) {{
                            progressBar.style.width = '100%';
                            progressBar.textContent = '100% Complete';
                        }}

                        const side = timelineItemCounter % 2 === 0 ? 'left' : 'right';
                        const finishedItem = document.createElement('div');
                        finishedItem.className = `timeline-item ${{side}}`;
                        finishedItem.innerHTML = `
                            <div class="timeline-content" style="background-color: var(--success-color); color: white;">
                                <h3>🎉 Process Finished!</h3>
                                <p>All files generated successfully. You can now close this window.</p>
                            </div>
                        `;
                        logContainer.appendChild(finishedItem);
                        return; // Stop polling
                    }}
                    setTimeout(pollStatus, 500);
                }})
                .catch(err => {{
                    if (progressUpdater) clearInterval(progressUpdater);
                    const logContainer = document.getElementById('generation-log');
                    if (logContainer) {{
                        logContainer.innerHTML += `<p style="color: var(--danger-color);">Connection to server lost. Please check the agent's console output.</p>`;
                    }}
                    console.error('Error polling status:', err);
                }});
        }}

        function sendDecision(decision) {{
            if (decision === 'approve') {{
                const generationContainer = document.createElement('div');
                generationContainer.className = 'container';
                generationContainer.innerHTML = `
                    <h2>⚙️ Code Generation Progress</h2>
                    <div class="progress-bar-container">
                        <div class="progress-bar" id="generation-progress-bar" style="width: 0%;">0%</div>
                    </div>
                    <div id="generation-log" class="timeline">
                         <div class="timeline-item left placeholder">
                            <div class="timeline-content">
                                <h3>🚀 Process Started</h3>
                                <p>Waiting for the agent to begin generating files...</p>
                            </div>
                        </div>
                    </div>
                `;
                
                const useFlash = document.getElementById('use-flash-model').checked;
                const actionsContainer = document.getElementById('actions-container');
                if (actionsContainer) {{
                    actionsContainer.parentNode.replaceChild(generationContainer, actionsContainer);
                }} else {{
                    mainContent.appendChild(generationContainer);
                }}
                
                fetch(`http://localhost:${{port}}/approve`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ use_flash_model: useFlash }})
                }})
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

    try:
        # Use a temporary file to avoid cluttering the user's directory
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".html", encoding="utf-8"
        ) as f:
            plan_file_path = f.name
            f.write(html_content)
        logging.info(f"✅ Plan saved to temporary file: {plan_file_path}")
        return plan_file_path
    except Exception as e:
        logging.error(f"❌ Could not write the HTML plan: {e}")
        return None


# --- Advise Agent HTML Generation ---


def create_advice_analysis_html(
    analysis: "AdviceAnalysis", question: str, port: int
) -> Optional[str]:
    """Generates an HTML report for the advice analysis and returns the file path."""
    if not analysis:
        return None

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Advice Generation Plan</title>
    {COMMON_STYLE}
</head>
<body>
    <div id="main-content" class="main-container">
        <h1>🤖 AI Advice Generation Plan</h1>

        <div class="container">
            <h2>Your Question</h2>
            <p>{question}</p>
        </div>

        <div class="container">
            <h2>High-level Plan for Advice</h2>
            <ol>
                {''.join([f'<li>{step}</li>' for step in analysis.plan_for_advice]) if analysis.plan_for_advice else "<li>No plan provided.</li>"}
            </ol>
        </div>

        <div class="container">
            <h2>Overall Reasoning</h2>
            <p>{analysis.reasoning or "No reasoning provided."}</p>
        </div>

        <div class="container">
            <h2>Relevant Files for Context</h2>
            <ul>
                {''.join([f'<li><code>{file}</code></li>' for file in analysis.relevant_files]) if analysis.relevant_files else "<li>None</li>"}
            </ul>
        </div>

        <div class="container actions">
            <h2>Confirm Plan</h2>
            <p>Do you want to proceed with generating the advice based on this plan?</p>
            <button class="approve-btn" onclick="sendDecision('approve')">Approve & Generate Advice</button>
            <button class="reject-btn" onclick="sendDecision('reject')">Reject</button>
            <div class="feedback-form">
                <h3>Refine the Plan</h3>
                <p>If the plan isn't quite right, provide feedback below and submit it for a new plan.</p>
                <textarea id="feedback-text" placeholder="e.g., 'Please also consider file X' or 'The plan seems to miss the point about Y'"></textarea>
                <br>
                <button class="feedback-btn" onclick="sendFeedback()">Submit Feedback</button>
            </div>
        </div>
    </div>

    <script>
        const port = {port};
        const mainContent = document.getElementById('main-content');

        function showMessage(title, message) {{
            mainContent.innerHTML = `<div class="container"><h1>${{title}}</h1><p>${{message}}</p></div>`;
        }}

        function sendDecision(decision) {{
            let fetchOptions = {{ method: 'POST' }};
            let url = `http://localhost:${{port}}/${{decision}}`;

            fetch(url, fetchOptions)
                .then(response => response.text())
                .then(text => {{
                    const title = 'Decision Received';
                    const message = text + ' You can close this tab now.';
                    showMessage(title, message);
                    setTimeout(() => window.close(), 3000);
                }})
                .catch(err => {{
                    showMessage('Error', `Could not contact server. Please check the console.`);
                    console.error('Error sending decision:', err);
                }});
        }}

        function sendFeedback() {{
            const feedback = document.getElementById('feedback-text').value;
            if (!feedback) {{
                alert('Please enter feedback before submitting.');
                return;
            }}
            fetch(`http://localhost:${{port}}/feedback`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ feedback: feedback }})
            }})
            .then(response => response.text())
            .then(text => {{
                const title = 'Feedback Submitted';
                const message = text + ' You can close this tab now.';
                showMessage(title, message);
                setTimeout(() => window.close(), 3000);
            }})
            .catch(err => {{
                showMessage('Error', 'Could not contact server. Please check the console.');
                console.error('Error sending feedback:', err);
            }});
        }}
    </script>
</body>
</html>
    """

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".html", encoding="utf-8"
        ) as f:
            plan_file_path = f.name
            f.write(html_content)
        logging.info(f"✅ Analysis plan saved to temporary file: {plan_file_path}")
        return plan_file_path
    except Exception as e:
        logging.error(f"❌ Could not write the HTML plan: {e}")
        return None


def create_advice_html(advice: "Advice", question: str) -> Optional[str]:
    """Generates an HTML report from the advice and returns the file path."""

    response_html = markdown.markdown(advice.response, extensions=["fenced_code", "tables"])

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI-Generated Advice</title>
    {COMMON_STYLE}
</head>
<body>
    <div class="main-container">
        <h1>🤖 AI-Generated Advice</h1>

        <div class="container">
            <h2>Your Question</h2>
            <p>{question}</p>
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
    </div>
</body>
</html>
    """

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".html", encoding="utf-8"
        ) as f:
            advice_file_path = f.name
            f.write(html_content)
        logging.info(f"✅ Advice saved to temporary file: {advice_file_path}")
        return advice_file_path
    except Exception as e:
        logging.error(f"❌ Could not write or open the HTML advice file: {e}")
        return None
