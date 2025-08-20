#!/usr/bin/env python
"""
Utilities for generating and managing HTML content for the Code Agent's user interaction.

This module centralizes the creation of HTML pages used by the code agent
to display plans, gather feedback, and show results.
"""

import json
import logging
import tempfile
from typing import List, Optional

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

    /* --- Donation Container Styles --- */
    .donation-container {
        background-color: #f9fafb;
        padding: 1.5rem;
        border-radius: 8px;
        border: 1px solid var(--border-color);
        text-align: center;
        margin-top: 1rem;
        margin-bottom: 2rem;
    }
    .donation-container p {
        margin-top: 0;
        margin-bottom: 1rem;
        color: #555;
        font-size: 0.95em;
    }
    .donation-form {
        display: inline-grid;
        justify-items: center;
        gap: 0.5rem;
    }
    .donation-form input[type="submit"] {
        color: #000;
        background-color: #FFD140; /* PayPal yellow */
        border: none;
        padding: 0.8rem 1.8rem;
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
    .donation-form input[type="submit"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.15);
        background-color: #ffc107; /* Darker yellow */
    }
    .donation-form .payment-methods {
        margin-top: 0.5rem;
        max-width: 200px;
        display: inline-block;
    }
    .donation-form .powered-by {
        font-size: 0.75rem;
        color: #777;
        margin-top: 0.75rem;
    }
    .donation-form .powered-by img {
        height: 0.875rem;
        vertical-align: middle;
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
        left: 30px;
        margin-left: -2px;
        border-radius: 2px;
    }

    .timeline-item {
        padding: 10px 0 10px 70px;
        position: relative;
        background-color: inherit;
        width: 100%;
    }

    .timeline-item::after {
        content: '';
        position: absolute;
        width: 20px;
        height: 20px;
        left: 19px;
        background-color: white;
        border: 4px solid var(--primary-color);
        top: 25px;
        border-radius: 50%;
        z-index: 1;
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
    .timeline-content.warning {
        background-color: #fffbe6;
        border-left: 4px solid #fadb14;
    }
    .timeline-content.error {
        background-color: #fff1f0;
        border-left: 4px solid #ff4d4f;
    }

    /* --- Autocomplete Styles --- */
    .autocomplete-container {
        position: relative;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
    }
    .autocomplete-container input {
        width: calc(100% - 2rem);
        padding: 0.75rem 1rem;
        font-size: 1rem;
        border: 1px solid var(--border-color);
        border-radius: 8px;
    }
    .autocomplete-items {
        position: absolute;
        border: 1px solid var(--border-color);
        border-top: none;
        z-index: 99;
        top: 100%;
        left: 0;
        right: 0;
        background-color: white;
        max-height: 200px;
        overflow-y: auto;
        box-shadow: 0 8px 16px rgba(0,0,0,0.1);
        border-radius: 0 0 8px 8px;
    }
    .autocomplete-items div {
        padding: 10px;
        cursor: pointer;
        background-color: #fff;
        border-bottom: 1px solid #d4d4d4;
    }
    .autocomplete-items div:last-child {
        border-bottom: none;
    }
    .autocomplete-items div:hover {
        background-color: #e9e9e9;
    }

    /* --- Generation View File Lists --- */
    .file-list-container {
        margin-top: 2rem;
    }
    .file-list {
        list-style-type: none;
        padding: 0;
    }
    .file-item {
        border: 1px solid var(--border-color);
        border-radius: 8px;
        margin-bottom: 0.75rem;
        background-color: #fff;
        overflow: hidden; /* To contain the border-radius */
    }
    .file-header {
        padding: 0.8rem 1.2rem;
        cursor: pointer;
        display: flex;
        justify-content: space-between;
        align-items: center;
        background-color: #f9fafb;
        transition: background-color 0.2s ease;
    }
    .file-header:hover {
        background-color: #f1f5f9;
    }
    .file-header code {
        font-size: 1.1em;
    }
    .file-header .toggle-arrow {
        transition: transform 0.3s ease;
    }
    .file-item.active .file-header .toggle-arrow {
        transform: rotate(90deg);
    }
    .file-details {
        display: none;
        padding: 1rem 1.5rem;
        border-top: 1px solid var(--border-color);
        background-color: #ffffff;
    }
    .file-item.active .file-details {
        display: block;
    }
    .diff-container {
        background-color: var(--code-bg-color);
        color: var(--code-text-color);
        padding: 1rem;
        border-radius: 8px;
        overflow-x: auto;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        font-size: 0.9em;
        white-space: pre;
    }
    .diff-line {
        display: block;
    }
    .diff-add {
        background-color: rgba(46, 160, 67, 0.2);
    }
    .diff-remove {
        background-color: rgba(248, 81, 73, 0.2);
    }
    .diff-context {
        color: #999;
    }
    .processing-queue {
        list-style-type: none;
        padding: 0;
    }
    .processing-queue li {
        padding: 0.5rem 1rem;
        background-color: #f9fafb;
        border: 1px solid var(--border-color);
        border-radius: 6px;
        margin-bottom: 0.5rem;
    }
    .processing-queue li.processing {
        font-weight: bold;
        background-color: var(--primary-color);
        color: white;
        border-color: var(--primary-color);
    }
</style>
"""


def create_code_agent_html_viewer(port: int, all_repo_files: List[str]) -> Optional[str]:
    """Generates a dynamic HTML viewer for the code agent lifecycle."""

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Code Agent</title>
    {COMMON_STYLE}
    <style>
        .view {{ display: none; }}
        .view.active {{ display: block; }}
        
        @keyframes progress-bar-stripes {{
            from {{ background-position: 1rem 0; }}
            to {{ background-position: 0 0; }}
        }}
        .progress-bar.animated {{
            animation: progress-bar-stripes 1s linear infinite;
            background-image: linear-gradient(45deg,rgba(255,255,255,.15) 25%,transparent 25%,transparent 50%,rgba(255,255,255,.15) 50%,rgba(255,255,255,.15) 75%,transparent 75%,transparent);
            background-size: 1rem 1rem;
        }}
    </style>
</head>
<body>
    <div id="main-container" class="main-container">
        <!-- Content will be rendered here by JavaScript -->
    </div>

    <script>
        const port = {port};
        const allRepoFiles = {json.dumps(all_repo_files)};
        const mainContainer = document.getElementById('main-container');
        
        let state = {{
            task: '',
            initial_task: '',
            plan: null,
            status: 'initializing',
            totalFiles: 0,
            timelineItemCounter: 0,
            pollingActive: false,
            additionalContextFiles: [],
            completedFilesData: {{}},
        }};

        // UTILITY FUNCTIONS
        function escapeHtml(unsafe) {{
            if (typeof unsafe !== 'string') return '';
            return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }}

        // RENDER FUNCTIONS
        function renderInitializingView() {{
            mainContainer.innerHTML = `
                <div id="initializing-view" class="view active">
                    <div class="container">
                        <h1>🤖 AI Code Agent</h1>
                        <p>Connecting to agent...</p>
                    </div>
                </div>
            `;
        }}

        function renderTaskDefinitionView() {{
            mainContainer.innerHTML = `
            <div id="task-definition-view" class="view active">
                <div class="container">
                    <h1>Define Your Task</h1>
                    <p>Start with your initial prompt. You can refine it directly or use the AI to help generate a more detailed task specification.</p>
                    
                    <div class="feedback-form" style="text-align: left; margin-top: 2rem;">
                        <h3>Initial Prompt</h3>
                        <p>This is the prompt you provided on the command line. You can edit it here.</p>
                        <textarea id="initial-prompt-input">${{escapeHtml(state.initial_task)}}</textarea>
                        
                        <div class="actions" style="border-top: none; padding-top: 1rem; margin-top: 1rem;">
                            <button id="generate-task-btn" class="feedback-btn" onclick="generateTask()">✨ Generate Detailed Task</button>
                        </div>

                        <h3>Final Task for Agent</h3>
                        <p>This is the task that will be sent to the agent for planning. You can edit it at any time.</p>
                        <textarea id="final-task-input" placeholder="The detailed task for the AI agent will appear here...">${{escapeHtml(state.initial_task)}}</textarea>
                    </div>

                    <div class="actions" style="margin-top: 2rem;">
                        <button id="start-analysis-btn" class="approve-btn" onclick="startAnalysis()">Start Analysis</button>
                    </div>
                </div>
            </div>
            `;
        }}

        function renderPlanningView(message = 'Analyzing your request...') {{
            state.timelineItemCounter = 0;
            state.additionalContextFiles = []; // Reset for new plan
            mainContainer.innerHTML = `
                <div id="planning-view" class="view active">
                    <div class="container">
                        <h1>🤖 AI Code Agent</h1>
                        <div id="planning-status">
                            <h2>${{escapeHtml(message)}}</h2>
                            <p>The AI agent is currently analyzing the codebase and formulating a plan. This may take a few moments.</p>
                            <div class="progress-bar-container" style="margin-top: 2rem;">
                                <div class="progress-bar animated" style="width: 100%; background-color: var(--primary-color);">Thinking...</div>
                            </div>
                            <div id="tool-log" class="timeline">
                                <div class="timeline-item placeholder">
                                    <div class="timeline-content">
                                        <h3>🚀 Process Started</h3>
                                        <p>Waiting for the agent to begin analysis...</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }}

        function formatFilesToCreateHtml(files) {{
            if (!files || files.length === 0) return "<p>None</p>";
            const rows = files.map(file => {{
                const suggestions = (file.content_suggestions && file.content_suggestions.length > 0)
                    ? `<ul>${{file.content_suggestions.map(s => `<li><code>${{escapeHtml(s)}}</code></li>`).join('')}}</ul>`
                    : 'None';
                return `
                    <tr>
                        <td><code>${{escapeHtml(file.file_path)}}</code></td>
                        <td>${{escapeHtml(file.reasoning)}}</td>
                        <td>${{suggestions}}</td>
                    </tr>
                `;
            }}).join('');

            return `
                <table>
                    <thead><tr><th>File Path</th><th>Reasoning</th><th>Content Suggestions</th></tr></thead>
                    <tbody>${{rows}}</tbody>
                </table>
            `;
        }}

        function renderPlanReviewView() {{
            const {{ plan, task }} = state;
            if (!plan) return;

            // The backend converts markdown to HTML, so we just join the strings.
            const planHtml = plan.plan.join('');
            
            mainContainer.innerHTML = `
            <div id="plan-review-view" class="view active">
                <h1>🤖 AI Code Generation Plan</h1>
                <div class="container">
                    <h2>Task</h2>
                    ${{task}}
                </div>
                <div class="container">
                    <h2>High-level Plan</h2>
                    ${{planHtml || "<p>No plan provided.</p>"}}
                </div>
                <div class="container">
                    <h2>Overall Reasoning</h2>
                    <p>${{plan.reasoning || "No reasoning provided."}}</p>
                </div>
                <div class="container">
                    <h2>File Breakdown</h2>
                    <h3>Relevant Files for Context</h3>
                    <p>These files were identified by the AI as important for understanding the task. You can add more files below.</p>
                    <ul id="relevant-files-list">${{plan.relevant_files.length > 0 ? plan.relevant_files.map(f => `<li><code>${{escapeHtml(f)}}</code></li>`).join('') : "<li>None</li>"}}</ul>
                    
                    <div class="autocomplete-container">
                        <h4>Add more files to context:</h4>
                        <input type="text" id="file-search" placeholder="Search for files to add to context...">
                        <div id="autocomplete-results" class="autocomplete-items"></div>
                    </div>

                    <h3>Files to Edit</h3>
                    <ul>${{plan.files_to_edit.length > 0 ? plan.files_to_edit.map(f => `<li><code>${{escapeHtml(f)}}</code></li>`).join('') : "<li>None</li>"}}</ul>
                    <h3>Files to Create</h3>
                    ${{formatFilesToCreateHtml(plan.files_to_create)}}
                </div>
                <div class="container">
                    <h2>Proposed Generation Order</h2>
                    <ol>${{plan.generation_order.length > 0 ? plan.generation_order.map(f => `<li><code>${{escapeHtml(f)}}</code></li>`).join('') : "<li>None</li>"}}</ol>
                </div>
                <div id="actions-container" class="container actions">
                    <h2>Confirm Plan</h2>
                    <p>Do you want to proceed with generating the code based on this plan?</p>
                    <div class="model-toggle">
                        <input type="checkbox" id="use-flash-model" name="use-flash-model" ${{plan.use_flash_model ? 'checked' : ''}}>
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
            `;
            setupFileAutocomplete();
        }}

        function renderUserInputView(request) {{
            mainContainer.innerHTML = `
            <div id="user-input-view" class="view active">
                <div class="container">
                    <h1>🤖 AI Agent Needs Your Input</h1>
                    <div class="container">
                        <h2>Question from the Agent</h2>
                        <blockquote>${{escapeHtml(request)}}</blockquote>
                    </div>
                    <div class="feedback-form">
                        <h3>Your Response</h3>
                        <textarea id="user-input-text" placeholder="Provide your answer here..."></textarea>
                        <br>
                        <button class="approve-btn" onclick="sendUserInput()">Submit Response</button>
                    </div>
                </div>
            </div>
            `;
            document.getElementById('user-input-text').focus();
        }}

        function renderGenerationView() {{
            state.completedFilesData = {{}};
            state.totalFiles = state.plan.generation_order.length;

            mainContainer.innerHTML = `
            <div id="generation-view" class="view active">
                <div class="container">
                    <h1>⚙️ Code Generation Progress</h1>
                    
                    <div class="donation-container">
                        <p>If you find this tool useful, please consider supporting its development.</p>
                        <form action="https://www.paypal.com/ncp/payment/ELWZ6Q2MZ72CE" method="post" target="_blank" class="donation-form">
                            <input type="submit" value="Donate" />
                            <img class="payment-methods" src="https://www.paypalobjects.com/images/Debit_Credit_APM.svg" alt="Visa, Mastercard, American Express, Discover" />
                            <div class="powered-by">
                                Powered by <img src="https://www.paypalobjects.com/paypal-ui/logos/svg/paypal-wordmark-color.svg" alt="paypal"/>
                            </div>
                        </form>
                    </div>

                    <div class="progress-bar-container">
                        <div class="progress-bar" id="generation-progress-bar" style="width: 0%;">0%</div>
                    </div>
                    
                    <div id="completed-files-container" class="file-list-container">
                        <h2>Completed Files</h2>
                        <div id="completed-files-list" class="file-list">
                            <p id="no-completed-files">No files have been generated yet.</p>
                        </div>
                    </div>

                    <div id="processing-queue-container" class="file-list-container">
                        <h2>Processing Queue</h2>
                        <ul id="processing-queue-list" class="processing-queue">
                            <!-- Queue will be populated by JS -->
                        </ul>
                    </div>
                </div>
            </div>
            `;
        }}

        function addGenericTimelineItem(message, icon, cssClass) {{
            const planningLog = document.getElementById('tool-log');
            if (!planningLog) return;

            if (state.timelineItemCounter === 0 && planningLog.querySelector('.placeholder')) {{
                planningLog.innerHTML = '';
            }}

            const item = document.createElement('div');
            item.className = "timeline-item";
            item.innerHTML = `
                <div class="timeline-content ${{cssClass || ''}}">
                    <h3>${{icon || 'ℹ️'}} ${{message}}</h3>
                </div>
            `;
            planningLog.appendChild(item);
            state.timelineItemCounter++;
        }}

        function showMessage(title, message, isError = false) {{
            mainContainer.innerHTML = `
                <div class="container">
                    <h1 style="${{isError ? 'color: var(--danger-color);' : ''}}">${{title}}</h1>
                    <p>${{message}}</p>
                </div>`;
        }}

        // --- Autocomplete and Context Management ---
        function setupFileAutocomplete() {{
            const searchInput = document.getElementById('file-search');
            const resultsContainer = document.getElementById('autocomplete-results');
            if (!searchInput) return;

            searchInput.addEventListener('input', function(e) {{
                const value = this.value;
                resultsContainer.innerHTML = '';
                if (!value) return;

                const suggestions = allRepoFiles.filter(file => 
                    file.toLowerCase().includes(value.toLowerCase()) &&
                    !state.plan.relevant_files.includes(file) // Don't suggest files already in context
                );

                suggestions.slice(0, 10).forEach(file => {{ // Show max 10 suggestions
                    const item = document.createElement('div');
                    item.innerHTML = file.replace(new RegExp(escapeHtml(value), "gi"), (match) => `<strong>${{match}}</strong>`);
                    item.addEventListener('click', function() {{
                        addFileToContext(file);
                        searchInput.value = '';
                        resultsContainer.innerHTML = '';
                    }});
                    resultsContainer.appendChild(item);
                }});
            }});

            // Close dropdown when clicking outside
            document.addEventListener('click', function (e) {{
                if (e.target !== searchInput) {{
                    resultsContainer.innerHTML = '';
                }}
            }});
        }}

        function addFileToContext(file) {{
            if (!state.plan.relevant_files.includes(file)) {{
                state.plan.relevant_files.push(file);
                state.additionalContextFiles.push(file); // Keep track of user-added files
                
                // Re-render the list
                const listElement = document.getElementById('relevant-files-list');
                if (listElement) {{
                    if (listElement.querySelector('li') && listElement.querySelector('li').textContent === 'None') {{
                        listElement.innerHTML = ''; // Clear "None" message
                    }}
                    const li = document.createElement('li');
                    li.innerHTML = `<code>${{escapeHtml(file)}}</code>`;
                    listElement.appendChild(li);
                }}
            }}
        }}

        // --- Generation View Logic ---
        function renderDiff(diffString) {{
            if (!diffString || diffString === "No changes detected.") {{
                return `<div class="diff-container"><span class="diff-context">${{escapeHtml(diffString)}}</span></div>`;
            }}
            const lines = diffString.split('\\n');
            const htmlLines = lines.map(line => {{
                const escapedLine = escapeHtml(line);
                if (line.startsWith('+')) {{
                    return `<span class="diff-line diff-add">${{escapedLine}}</span>`;
                }} else if (line.startsWith('-')) {{
                    return `<span class="diff-line diff-remove">${{escapedLine}}</span>`;
                }} else if (line.startsWith('@@') || line.startsWith('diff') || line.startsWith('index')) {{
                    return `<span class="diff-line diff-context">${{escapedLine}}</span>`;
                }}
                return `<span class="diff-line">${{escapedLine}}</span>`;
            }}).join('');
            return `<div class="diff-container">${{htmlLines}}</div>`;
        }}

        function toggleFileDetails(filePath) {{
            const elementId = `item-${{filePath.replace(/[^a-zA-Z0-9]/g, '-')}}`;
            const fileItem = document.getElementById(elementId);
            if (fileItem) {{
                fileItem.classList.toggle('active');
            }}
        }}

        // STATUS POLLING AND EVENT HANDLING
        function pollStatus() {{
            if (!state.pollingActive) return;

            fetch(`http://localhost:${{port}}/status`)
                .then(response => {{
                    if (response.status === 204) {{ // No content, just continue polling
                        setTimeout(pollStatus, 1000);
                        return null;
                    }}
                    if (!response.ok) throw new Error(`HTTP error! status: ${{response.status}}`);
                    return response.json();
                }})
                .then(data => {{
                    if (!data) return;
                    handleStatusUpdate(data);
                    
                    if (data.status !== 'finished' && data.status !== 'error') {{
                        setTimeout(pollStatus, 500);
                    }} else {{
                        state.pollingActive = false;
                    }}
                }})
                .catch(err => {{
                    state.pollingActive = false;
                    showMessage('Connection Error', 'Connection to the agent was lost. Please check the console output.', true);
                    console.error('Error polling status:', err);
                    window.close();
                }});
        }}

        function handleStatusUpdate(data) {{
            const newStatus = data.status;
            const oldStatus = state.status;

            // Allow certain event-like statuses to be processed repeatedly.
            if (newStatus === oldStatus && !['tool_used', 'writing', 'done', 'cli_log', 'plan_updated'].includes(newStatus)) return;

            state.status = newStatus;

            switch (newStatus) {{
                case 'awaiting_task':
                    state.initial_task = data.initial_task;
                    renderTaskDefinitionView();
                    break;
                
                case 'task_generated':
                    const finalTaskInput = document.getElementById('final-task-input');
                    if (finalTaskInput) {{
                        finalTaskInput.value = data.task;
                    }}
                    break;

                case 'cli_log':
                    addGenericTimelineItem(data.message, data.icon, data.cssClass);
                    break;

                case 'tool_used':
                    updateToolLog(data);
                    break;

                case 'plan_ready':
                    state.plan = data.plan;
                    state.task = data.task;
                    renderPlanReviewView();
                    break;
                
                case 'user_input_required':
                    renderUserInputView(data.request);
                    break;

                case 'plan_updated':
                    state.totalFiles = data.new_total_files;
                    const filesHtml = data.files_added.map(f => `<code>${{escapeHtml(f)}}</code>`).join(', ');
                    const message = `Agent requested to add ${{data.files_added.length}} file(s) to the plan: ${{filesHtml}}. The total number of files to process is now ${{state.totalFiles}}.`;
                    addGenericTimelineItem(message, '🔄', 'warning');
                    break;

                case 'writing':
                case 'done':
                    updateGenerationProgress(data);
                    break;
                
                case 'finished':
                    handleFinishedStatus();
                    break;
                
                case 'error':
                    showMessage('Agent Error', data.message, true);
                    break;
            }}
        }}

        function updateToolLog(data) {{
            const logContainer = document.getElementById('tool-log');
            if (!logContainer) return;

            if (state.timelineItemCounter === 0 && logContainer.querySelector('.placeholder')) {{
                logContainer.innerHTML = '';
            }}

            const toolItem = document.createElement('div');
            toolItem.className = "timeline-item";
            toolItem.innerHTML = `
                <div class="timeline-content">
                    <h3>🛠️ Tool Used: <code>${{escapeHtml(data.tool_name)}}</code></h3>
                    <p>Input:</p>
                    <pre><code>${{escapeHtml(JSON.stringify(data.tool_input, null, 2))}}</code></pre>
                </div>
            `;
            logContainer.appendChild(toolItem);
            state.timelineItemCounter++;
        }}

        function updateGenerationProgress(data) {{
            const completedList = document.getElementById('completed-files-list');
            const queueList = document.getElementById('processing-queue-list');
            if (!completedList || !queueList) return;

            // Update Progress Bar
            const completedCount = data.completed_files.length;
            const percentage = state.totalFiles > 0 ? (completedCount / state.totalFiles) * 100 : 0;
            const progressBar = document.getElementById('generation-progress-bar');
            if (progressBar) {{
                progressBar.style.width = `${{percentage}}%`;
                progressBar.textContent = `${{Math.round(percentage)}}%`;
            }}

            // Update Completed Files List
            const noCompletedFilesMsg = document.getElementById('no-completed-files');
            if (data.completed_files.length > 0 && noCompletedFilesMsg) {{
                noCompletedFilesMsg.style.display = 'none';
            }}

            if (data.status === 'done') {{
                state.completedFilesData[data.file_path] = {{
                    summary: data.summary,
                    reasoning: data.reasoning,
                    git_diff: data.git_diff
                }};
            }}

            completedList.innerHTML = ''; // Clear and rebuild
            data.completed_files.forEach(filePath => {{
                const details = state.completedFilesData[filePath];
                if (!details) return;

                const elementId = `item-${{filePath.replace(/[^a-zA-Z0-9]/g, '-')}}`;
                const fileItem = document.createElement('div');
                fileItem.id = elementId;
                fileItem.className = 'file-item';
                fileItem.innerHTML = `
                    <div class="file-header" onclick="toggleFileDetails('${{filePath}}')">
                        <code>${{escapeHtml(filePath)}}</code>
                        <span class="toggle-arrow">▶</span>
                    </div>
                    <div class="file-details">
                        <h4>Summary of Changes</h4>
                        <div>${{details.summary || 'No summary provided.'}}</div>
                        <h4>Reasoning for Changes</h4>
                        <blockquote>${{details.reasoning || 'No reasoning provided.'}}</blockquote>
                        <h4>Git Diff</h4>
                        ${{renderDiff(details.git_diff)}}
                    </div>
                `;
                completedList.appendChild(fileItem);
            }});

            // Update Processing Queue List
            queueList.innerHTML = '';
            data.processing_queue.forEach((filePath, index) => {{
                const li = document.createElement('li');
                li.innerHTML = `<code>${{escapeHtml(filePath)}}</code>`;
                if (index === 0) {{
                    li.className = 'processing';
                    li.innerHTML = `⚙️ ${{li.innerHTML}}`;
                }}
                queueList.appendChild(li);
            }});
        }}

        function handleFinishedStatus() {{
            const progressBar = document.getElementById('generation-progress-bar');
            if (progressBar) {{
                progressBar.style.width = '100%';
                progressBar.textContent = '100%';
            }}

            const queueList = document.getElementById('processing-queue-list');
            if (queueList) {{
                queueList.innerHTML = '<li>✅ All files processed.</li>';
            }}

            const generationView = document.getElementById('generation-view');
            if (generationView) {{
                const container = generationView.querySelector('.container');
                if (container) {{
                    const finishedItem = document.createElement('div');
                    finishedItem.innerHTML = `
                        <div style="background-color: var(--success-color); color: white; padding: 1.5rem; border-radius: 8px; text-align: center; margin-top: 2rem;">
                            <h2 style="color: white;">🎉 Process Finished!</h2>
                            <p>All files generated successfully. You can now close this window.</p>
                        </div>
                    `;
                    container.appendChild(finishedItem);
                }}
            }}
        }}

        // --- ACTION FUNCTIONS ---
        function startAnalysis() {{
            const finalTask = document.getElementById('final-task-input').value;
            if (!finalTask) {{
                alert('Please provide a task for the agent.');
                return;
            }}
            
            state.task = finalTask; // Store the final task in state
            renderPlanningView(`Analyzing your request...`);

            const payload = {{ task: finalTask }};

            fetch(`http://localhost:${{port}}/start_analysis`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }}).catch(err => {{
                showMessage('Error', "Could not start analysis. Check the agent's console.", true);
                console.error('Error sending start_analysis request:', err);
            }});
        }}

        function generateTask() {{
            const initialPrompt = document.getElementById('initial-prompt-input').value;
            const generateBtn = document.getElementById('generate-task-btn');
            const finalTaskInput = document.getElementById('final-task-input');

            generateBtn.disabled = true;
            generateBtn.textContent = 'Generating...';
            finalTaskInput.value = 'AI is thinking...';

            const payload = {{ prompt: initialPrompt }};

            fetch(`http://localhost:${{port}}/generate_task`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }})
            .catch(err => {{
                finalTaskInput.value = 'Error generating task. Please try again or write the task manually.';
                console.error('Error sending generate_task request:', err);
            }})
            .finally(() => {{
                generateBtn.disabled = false;
                generateBtn.textContent = '✨ Generate Detailed Task';
            }});
        }}

        function sendDecision(decision) {{
            if (decision === 'approve') {{
                const useFlash = document.getElementById('use-flash-model').checked;
                renderGenerationView();
                
                const payload = {{
                    use_flash_model: useFlash,
                    additional_context_files: state.additionalContextFiles
                }};
                
                fetch(`http://localhost:${{port}}/approve`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }}).catch(err => {{
                    showMessage('Error', "Could not start generation process. Check the agent's console.", true);
                    console.error('Error sending approval:', err);
                }});
                return;
            }}

            // For reject
            fetch(`http://localhost:${{port}}/reject`, {{ method: 'POST' }})
                .then(response => response.text())
                .then(text => {{
                    state.pollingActive = false;
                    showMessage('Plan Rejected', 'The operation was cancelled. You can close this tab.');
                    setTimeout(() => window.close(), 5000);
                }})
                .catch(err => {{
                    showMessage('Error', `Could not contact server while sending 'reject'.`, true);
                    console.error(`Error sending reject:`, err);
                }});
        }}

        function sendFeedback() {{
            const feedback = document.getElementById('feedback-text').value;
            if (!feedback) {{
                alert('Please enter feedback before submitting.');
                return;
            }}
            
            renderPlanningView();
            const payload = {{
                feedback: feedback,
                additional_context_files: state.additionalContextFiles
            }};

            fetch(`http://localhost:${{port}}/feedback`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }})
            .then(res => {{
                if (!res.ok) throw new Error('Feedback request failed');
            }})
            .catch(err => {{
                showMessage('Error', 'Could not submit feedback. Please check the agent console.', true);
                console.error('Error sending feedback:', err);
            }});
        }}

        function sendUserInput() {{
            const userInput = document.getElementById('user-input-text').value;
            if (!userInput) {{
                alert('Please provide a response.');
                return;
            }}
            
            renderPlanningView('Re-analyzing with your input...');
            
            const payload = {{
                user_input: userInput
            }};

            fetch(`http://localhost:${{port}}/user_input`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }})
            .catch(err => {{
                showMessage('Error', 'Could not submit your input. Please check the agent console.', true);
                console.error('Error sending user input:', err);
            }});
        }}

        // INITIALIZATION
        document.addEventListener('DOMContentLoaded', () => {{
            renderInitializingView();
            state.pollingActive = true;
            pollStatus();
        }});
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
        logging.info(f"✅ Viewer HTML saved to temporary file: {plan_file_path}")
        return plan_file_path
    except Exception as e:
        logging.error(f"❌ Could not write the HTML viewer file: {e}")
        return None
