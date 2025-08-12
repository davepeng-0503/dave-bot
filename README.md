# AI Developer Assistant Suite

This repository contains a suite of AI-powered developer assistant tools designed to automate parts of the software development lifecycle. The tools are built in Python and leverage Google's Gemini series of models via the `pydantic-ai` library to understand and manipulate code within a git repository.

## Features

*   **Autonomous Coding**: Generate and modify code based on natural language task descriptions.
*   **Automated Code Review**: Review code changes, providing line-specific comments and high-level feedback.
*   **Intelligent Context Management**: Automatically identifies relevant files for context and can summarize large codebases to fit within model context limits.
*   **Dependency-Aware Planning**: Creates a logical plan for code generation, respecting file dependencies.
*   **Iterative Self-Correction**: Agents can re-analyze their plan if they lack context, request more information, and retry.
*   **Git Integration**: Works directly with your local git repository to find files, identify changes, and apply updates.

---

## The Agents

There are two primary agents in this suite:

### 1. Code Agent (`code_agent.py`)

*   **Purpose**: To autonomously perform coding tasks based on a natural language description.
*   **Workflow**:
    1.  It starts by performing an initial analysis of the entire codebase to identify relevant files, files that need editing, and new files that need to be created. It creates a dependency-aware generation plan.
    2.  It can use a `git grep` tool to search the codebase for specific keywords or functions to improve its analysis.
    3.  It then iteratively generates or modifies files one by one, according to its plan.
    4.  If it lacks the necessary information to generate a file, it can request more context and trigger a re-analysis of its plan.

### 2. Code Review Agent (`code_review_agent.py`)

*   **Purpose**: To perform an automated code review on a set of changes.
*   **Workflow**:
    1.  It identifies changed files in the repository (either local uncommitted changes or changes relative to a specific branch).
    2.  It performs an analysis to determine which other files are needed as context to understand the changes.
    3.  It then reviews each changed file, providing line-specific comments, severity levels, and general feedback.
    4.  Like the Code Agent, it can request more context if a review is not possible and re-run its analysis to create a better plan.

---

## Getting Started

### Prerequisites

*   Python 3.8+
*   Git
*   A Google AI API Key

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
    Create a file named `.env` in the root of the project directory and add your Google API key:
    ```
    GOOGLE_API_KEY="your_google_api_key_here"
    ```

---

## Usage

### Code Agent

The Code Agent modifies your codebase to accomplish a given task.

**Basic Usage:**
Run the agent from the command line with a `--task` argument describing the desired change.

```bash
python code_agent.py --task "Add a new endpoint `/api/v2/users` that returns a list of usernames."
```

**Arguments:**

*   `--task` (required): The task description for the AI.
*   `--dir`: The directory of the git repository (defaults to the current directory).
*   `--app-description`: Path to a text file describing the app's purpose for better context (defaults to `app_description.txt`).
*   `--force`: Bypass the confirmation prompt before writing file changes.
*   `--strict` / `--no-strict`: Control whether the AI can make broader improvements or must stick strictly to the task. Defaults to `--strict`.

### Code Review Agent

The Code Review Agent analyzes code changes and provides feedback.

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
*   `--force`: Bypass the confirmation prompt before starting the review.
*   `--strict` / `--no-strict`: Control whether the AI gives broad feedback or focuses only on the task. Defaults to `--strict`.

---
## Project Structure

*   `code_agent.py`: The main script for the autonomous coding agent.
*   `code_review_agent.py`: The main script for the automated code review agent.
*   `shared_agents_utils.py`: Common utilities for file I/O, Git operations, and base AI agent configuration (model setup, context building).
*   `app_description.txt`: A high-level description of the project to provide context to the agents.
*   `requirements.txt`: A list of Python packages required to run the agents.
*   `LICENSE`: The license for the project.

---
