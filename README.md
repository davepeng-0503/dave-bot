# AI Developer Assistant Suite

This repository contains a suite of AI-powered developer assistant tools designed to automate and assist with parts of the software development lifecycle. The tools are built in Python and leverage Google's Gemini models via the `pydantic-ai` library to understand and manipulate code within a git repository.

A key feature of the Code and Advise agents is an **interactive, browser-based UI** for reviewing and approving the AI's proposed plan before any action is taken, ensuring you are always in control.

## Features

*   **Autonomous Coding**: Generate and modify code based on natural language task descriptions.
*   **Automated Code Review**: Review code changes, providing line-specific comments and high-level feedback.
*   **Codebase Q&A**: Ask questions about your codebase and get detailed, context-aware answers.
*   **Interactive Plan Approval**: For coding and advisory tasks, review the AI's step-by-step plan in a local web browser and provide feedback before execution.
*   **Intelligent Context Management**: Automatically identifies relevant files for context and can summarize large codebases to fit within model context limits.
*   **Dependency-Aware Planning**: Creates a logical plan for code generation, respecting file dependencies.
*   **Iterative Self-Correction**: Agents can re-analyze their plan if they lack context, request more information, and retry based on internal checks or user feedback.
*   **Full Git Integration**: Creates branches, commits, pushes, and can even create a GitHub Pull Request for you.

---

## The Agents

There are three primary agents in this suite:

### 1. Code Agent (`code_agent.py`)

*   **Purpose**: To autonomously perform coding tasks based on a natural language description.
*   **Workflow**:
    1.  Analyzes the entire codebase to create a comprehensive, dependency-aware plan, including which files to create, edit, and reference.
    2.  **Launches a local web server** to display its plan for your review. You can approve, reject, or provide feedback to refine the plan.
    3.  Once approved, it iteratively generates or modifies files one by one, showing real-time status updates in the browser.
    4.  If it lacks context during generation, it can re-analyze its plan.
    5.  Upon completion, it automatically creates a new git branch, commits the changes, pushes to the remote, and attempts to create a GitHub Pull Request.

### 2. Code Review Agent (`code_review_agent.py`)

*   **Purpose**: To perform an automated code review on a set of changes.
*   **Workflow**:
    1.  It identifies changed files in the repository (either local uncommitted changes or changes relative to a specific branch).
    2.  It performs an analysis to determine which other files are needed as context to understand the changes.
    3.  It then reviews each changed file, providing line-specific comments, severity levels, and general feedback directly in your terminal.
    4.  Like the Code Agent, it can request more context if a review is not possible and re-run its analysis to create a better plan.

### 3. Advise Agent (`advise_agent.py`)

*   **Purpose**: To act as a technical advisor, answering questions about your codebase.
*   **Workflow**:
    1.  Analyzes your question and the codebase to determine which files are relevant for finding an answer.
    2.  **Presents its analysis plan for your approval in a web browser**, showing which files it intends to read.
    3.  After approval, it reads and summarizes the content of the relevant files.
    4.  It generates a detailed, Markdown-formatted response to your question, which is then displayed in a new browser tab.

---

## Getting Started

### Prerequisites

*   Python 3.8+
*   Git
*   A Google AI API Key
*   (Optional) [GitHub CLI](https://cli.github.com/) (`gh`) for automatic Pull Request creation.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/davepeng-0503/dave-bot.git
    cd dave-bot
    ```

2.  **Install dependencies:**
    It is recommended to create a virtual environment.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
    Install the required packages from `requirements.txt`.
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up your API Key:**
    The script will prompt you for your Google API key on first run, or you can set it as an environment variable named `GOOGLE_API_KEY`.

---

## Usage

### Code Agent

The Code Agent modifies your codebase to accomplish a given task. It will launch a web browser for you to approve its plan before it makes any changes.

**Basic Usage:**
Run the agent from the command line with a `--task` argument describing the desired change.

```bash
python code_agent.py --task "Add a new endpoint `/api/v2/users` that returns a list of usernames."
```

**Arguments:**

*   `--task` (required): The task description for the AI.
*   `--dir`: The directory of the git repository (defaults to the current directory).
*   `--app-description`: Path to a text file describing the app's purpose for better context (defaults to `app_description.txt`).
*   `--force`: Bypass the interactive web-based approval and automatically accept the AI's first plan.
*   `--strict` / `--no-strict`: Control whether the AI can make broader improvements or must stick strictly to the task. Defaults to `--strict`.
*   `--port`: The port for the local web server used for plan approval (defaults to 8080).

### Code Review Agent

The Code Review Agent analyzes code changes and provides feedback in the terminal.

**1. Reviewing Local Uncommitted Changes:**
This is the default mode. It will review all staged, unstaged, and untracked files.

```bash
python code_review_agent.py --task "Reviewing the implementation of the new caching layer."
```

**2. Reviewing Changes Against a Branch:**
Use the `--compare` flag to review all changes in your current working directory against a specified branch (e.g., `main` or `origin/main`).

```bash
python code_review_agent.py --task "Reviewing the bugfix for ticket #123" --compare "origin/main"
```

**Arguments:**

*   `--task` (required): The task description or goal of the changes (e.g., a pull request title/description).
*   `--compare`: The git branch to compare against (e.g., 'origin/main'). If omitted, it reviews local uncommitted changes.
*   `--dir`: The directory of the git repository (defaults to the current directory).
*   `--strict` / `--no-strict`: Control whether the AI gives broad feedback or focuses only on the task. Defaults to `--strict`.

### Advise Agent

The Advise Agent answers questions about your codebase, launching a browser for plan approval and to display the final answer.

**Basic Usage:**
Run the agent from the command line with a `--task` argument containing your question.

```bash
python advise_agent.py --task "How is user authentication handled in this project?"
```

**Arguments:**

*   `--task` (required): The question you want to ask about the codebase.
*   `--dir`: The directory of the git repository (defaults to the current directory).
*   `--app-description`: Path to a text file describing the app's purpose for better context (defaults to `app_description.txt`).
*   `--port`: The port for the local web server used for plan approval (defaults to 8080).

---
## Project Structure

*   `code_agent.py`: The main script for the autonomous coding agent.
*   `code_review_agent.py`: The main script for the automated code review agent.
*   `advise_agent.py`: The main script for the codebase Q&A agent.
*   `shared_agents_utils.py`: Common utilities for file I/O, Git operations, base AI agent configuration, and the local web server for user interaction.
*   `html_utils.py`: Helper functions for generating the HTML pages used in the interactive approval process.
*   `app_description.txt`: A high-level description of the project to provide context to the agents.
*   `requirements.txt`: A list of Python packages required to run the agents.
*   `LICENSE`: The license for the project.
