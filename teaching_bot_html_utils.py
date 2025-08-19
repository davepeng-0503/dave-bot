#!/usr/bin/env python
"""
Utilities for generating and managing the HTML content for the Teaching Bot's user interface.
"""

import json
import logging
import tempfile
from typing import Optional


def create_teaching_bot_html_viewer(port: int) -> Optional[str]:
    """Generates a dynamic HTML viewer for the teaching bot chat interface."""

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Teaching Bot</title>
    <style>
        :root {{
            --primary-color: #4a90e2;
            --secondary-color: #50e3c2;
            --background-color: #f4f7f9;
            --container-bg-color: #ffffff;
            --text-color: #333;
            --heading-color: #1a2533;
            --border-color: #e0e6ed;
            --code-bg-color: #2d2d2d;
            --code-text-color: #f8f8f2;
            --bot-message-bg: #eef2f5;
            --user-message-bg: #4a90e2;
            --user-message-text: #ffffff;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}

        body {{
            font-family: var(--font-family);
            background-color: var(--background-color);
            margin: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }}

        #chat-container {{
            width: 90%;
            max-width: 800px;
            height: 90vh;
            max-height: 900px;
            display: flex;
            flex-direction: column;
            background-color: var(--container-bg-color);
            border-radius: 12px;
            box-shadow: 0 8px 24px rgba(26, 37, 51, 0.1);
            overflow: hidden;
        }}

        #chat-header {{
            background: linear-gradient(45deg, var(--primary-color), var(--secondary-color));
            color: white;
            padding: 1rem;
            text-align: center;
        }}

        #chat-header h1 {{
            margin: 0;
            font-size: 1.5em;
        }}

        #chat-messages {{
            flex-grow: 1;
            padding: 1.5rem;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}

        .message {{
            padding: 0.75rem 1.25rem;
            border-radius: 18px;
            max-width: 75%;
            line-height: 1.5;
            word-wrap: break-word;
        }}

        .bot-message {{
            background-color: var(--bot-message-bg);
            color: var(--text-color);
            align-self: flex-start;
            border-bottom-left-radius: 4px;
        }}

        .user-message {{
            background-color: var(--user-message-bg);
            color: var(--user-message-text);
            align-self: flex-end;
            border-bottom-right-radius: 4px;
        }}

        #chat-input-container {{
            border-top: 1px solid var(--border-color);
            padding: 1rem;
            display: flex;
            flex-direction: column;
        }}
        
        #action-buttons {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 0.75rem;
            justify-content: center;
        }}

        .action-button {{
            background-color: var(--primary-color);
            color: white;
            border: none;
            padding: 0.6rem 1.2rem;
            font-size: 0.9rem;
            border-radius: 20px;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }}

        .action-button:hover {{
            background-color: #3a82d2;
        }}

        #input-wrapper {{
            display: flex;
        }}

        #user-input {{
            flex-grow: 1;
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 0.75rem 1rem;
            font-size: 1rem;
            font-family: var(--font-family);
        }}

        #user-input:focus {{
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 2px rgba(74, 144, 226, 0.2);
        }}

        #send-button {{
            background-color: var(--primary-color);
            color: white;
            border: none;
            border-radius: 50%;
            width: 44px;
            height: 44px;
            margin-left: 0.75rem;
            font-size: 1.5rem;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }}

        #send-button:hover {{
            background-color: #3a82d2;
        }}
        
        #send-button:disabled, .action-button:disabled {{
            background-color: #bdc3c7;
            cursor: not-allowed;
        }}

        pre {{
            background-color: var(--code-bg-color);
            color: var(--code-text-color);
            padding: 1rem;
            border-radius: 8px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            font-size: 0.9em;
        }}
        
        .feedback-correct {{
            border-left: 4px solid #2ecc71;
            padding-left: 1rem;
            background-color: #f0fff4;
        }}
        
        .feedback-incorrect {{
            border-left: 4px solid #e74c3c;
            padding-left: 1rem;
            background-color: #fff1f0;
        }}
    </style>
</head>
<body>
    <div id="chat-container">
        <div id="chat-header">
            <h1>AI Teaching Bot</h1>
        </div>
        <div id="chat-messages">
            <!-- Messages will be appended here by JavaScript -->
        </div>
        <div id="chat-input-container">
            <div id="action-buttons"></div>
            <div id="input-wrapper">
                <input type="text" id="user-input" placeholder="Type your message..." autocomplete="off">
                <button id="send-button" title="Send Message">&#10148;</button>
            </div>
        </div>
    </div>

    <script>
        const port = {port};
        let pollingActive = true;

        // DOM elements
        const messagesContainer = document.getElementById('chat-messages');
        const userInput = document.getElementById('user-input');
        const sendButton = document.getElementById('send-button');
        const actionButtonsContainer = document.getElementById('action-buttons');

        // Event Listeners
        sendButton.addEventListener('click', sendMessageFromInput);
        userInput.addEventListener('keypress', (e) => {{
            if (e.key === 'Enter' && !e.shiftKey) {{
                e.preventDefault();
                sendMessageFromInput();
            }}
        }});

        function escapeHtml(unsafe) {{
            if (typeof unsafe !== 'string') return '';
            return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }}

        function postMessageToServer(message) {{
            toggleInput(false);
            fetch(`http://localhost:${{port}}/send_message`, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ message: message }})
            }}).catch(err => {{
                console.error("Failed to send message:", err);
                appendMessage('bot', "Error: Could not connect to the bot. Please check the console.");
                toggleInput(true);
            }});
        }}

        function sendMessageFromInput() {{
            const content = userInput.value.trim();
            if (!content) return;
            appendMessage('user', content);
            userInput.value = '';
            postMessageToServer(content);
        }}

        function sendChoice(choice) {{
            appendMessage('user', choice);
            actionButtonsContainer.innerHTML = ''; // Clear buttons
            postMessageToServer(choice);
        }}

        function appendMessage(role, content, isHtml = false) {{
            const messageDiv = document.createElement('div');
            messageDiv.classList.add('message', `${{role}}-message`);
            if (isHtml) {{
                messageDiv.innerHTML = content;
            }} else {{
                messageDiv.textContent = content;
            }}
            messagesContainer.appendChild(messageDiv);
            // Scroll to the bottom
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }}

        function toggleInput(enabled) {{
            userInput.disabled = !enabled;
            sendButton.disabled = !enabled;
            document.querySelectorAll('.action-button').forEach(btn => btn.disabled = !enabled);
            if (enabled) {{
                userInput.focus();
            }}
        }}

        function pollStatus() {{
            if (!pollingActive) return;

            fetch(`http://localhost:${{port}}/status`)
                .then(response => {{
                    if (response.status === 204) {{ // No new update
                        setTimeout(pollStatus, 1000);
                        return null;
                    }}
                    if (!response.ok) throw new Error(`HTTP error! status: ${{response.status}}`);
                    return response.json();
                }})
                .then(data => {{
                    if (data) {{
                        handleStatusUpdate(data);
                    }}
                    if (pollingActive) {{
                        setTimeout(pollStatus, 500);
                    }}
                }})
                .catch(err => {{
                    pollingActive = false;
                    console.error('Error polling status:', err);
                    appendMessage('bot', "Connection to the bot was lost. Please restart the application.", true);
                    toggleInput(false);
                }});
        }}

        function handleStatusUpdate(data) {{
            const {{ action_type, speech, explanation, example, question, feedback, is_correct, next_topic_suggestions }} = data;

            if (speech) {{
                appendMessage('bot', speech);
            }}

            if (explanation) {{
                appendMessage('bot', `<h3>Explanation</h3><div>${{explanation}}</div>`, true);
            }}

            if (example) {{
                appendMessage('bot', `<h4>Example</h4><pre><code>${{escapeHtml(example)}}</code></pre>`, true);
            }}
            
            if (feedback !== null && feedback !== undefined) {{
                const feedbackClass = is_correct ? 'feedback-correct' : 'feedback-incorrect';
                const feedbackTitle = is_correct ? 'Correct!' : 'Not quite.';
                appendMessage('bot', `<div class="${{feedbackClass}}"><b>${{feedbackTitle}}</b> ${{feedback}}</div>`, true);
            }}

            actionButtonsContainer.innerHTML = ''; // Clear old buttons

            if (question) {{
                appendMessage('bot', `<h4>Question</h4><p>${{question.question_text}}</p>`, true);
                if (question.question_type === 'multiple_choice' && question.choices) {{
                    renderActionButtons(question.choices);
                    toggleInput(false); // Disable text input for MCQs
                    userInput.placeholder = "Select an option above";
                }} else {{
                    toggleInput(true);
                    userInput.placeholder = "Type your answer here...";
                }}
            }} else if (next_topic_suggestions) {{
                appendMessage('bot', "What would you like to learn about next?");
                renderActionButtons(next_topic_suggestions);
                toggleInput(true);
                userInput.placeholder = "Choose a topic or type your own...";
            }} else {{
                toggleInput(true);
                userInput.placeholder = "Type your message...";
            }}
        }}
        
        function renderActionButtons(options) {{
            options.forEach(option => {{
                const button = document.createElement('button');
                button.textContent = option;
                button.classList.add('action-button');
                button.onclick = () => sendChoice(option);
                actionButtonsContainer.appendChild(button);
            }});
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            toggleInput(false); // Initially disabled until first message from bot
            pollStatus();
        }});
    </script>
</body>
</html>
    """

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".html", encoding="utf-8"
        ) as f:
            viewer_file_path = f.name
            f.write(html_content)
        logging.info(f"✅ Teaching Bot HTML viewer saved to temporary file: {viewer_file_path}")
        return viewer_file_path
    except Exception as e:
        logging.error(f"❌ Could not write the HTML viewer file: {e}")
        return None
