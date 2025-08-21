# AI Developer Assistant & Scraper Bots

This repository contains an AI-powered developer assistant tool and a collection of scraper bots designed to automate and assist with parts of the software development lifecycle and data collection. The tools are built in Python and leverage Google's Gemini models via the `pydantic-ai` library to understand and manipulate code within a git repository.

A key feature of the Code agent is an **interactive, browser-based UI** for reviewing and approving the AI's proposed plan before any action is taken, ensuring you are always in control.

## Features

*   **Autonomous Coding**: Generate and modify code based on natural language task descriptions.
*   **Interactive Plan Approval**: For coding tasks, review the AI's step-by-step plan in a local web browser and provide feedback before execution.
*   **Data Scraping**: Extract structured information from websites, such as Google Maps.
*   **Intelligent Context Management**: Automatically identifies relevant files for context and can summarize large codebases to fit within model context limits.
*   **Dependency-Aware Planning**: Creates a logical plan for code generation, respecting file dependencies.
*   **Iterative Self-Correction**: The agent can re-analyze its plan if it lacks context, request more information, and retry based on internal checks or user feedback.
*   **Full Git Integration**: Creates branches, commits, pushes, and can even create a GitHub Pull Request for you.

## License and Contributions

This project is free to use and fork under the [LICENSE](./LICENSE) terms.

If you fork this project, we require that you provide a link back to the original GitHub repository: [https://github.com/davepeng-0503/dave-bot](https://github.com/davepeng-0503/dave-bot).

Contributions are welcome!

### Donations

If you find this tool useful, please consider supporting its development. Donations are greatly appreciated!

[![Donate](https://img.shields.io/badge/Donate-PayPal-yellow.svg)](https://www.paypal.com/ncp/payment/ELWZ6Q2MZ72CE)

---

## The Agents

### Code Agent (`code_agent.py`)

*   **Purpose**: To autonomously perform coding tasks based on a natural language description.
*   **Workflow**:
    1.  Analyzes the entire codebase to create a comprehensive, dependency-aware plan, including which files to create, edit, and reference.
    2.  **Launches a local web server** to display its plan for your review. You can approve, reject, or provide feedback to refine the plan.
    3.  Once approved, it iteratively generates or modifies files one by one, showing real-time status updates in the browser.
    4.  If it lacks context during generation, it can re-analyze its plan.
    5.  Upon completion, it automatically creates a new git branch, commits the changes, pushes to the remote, and attempts to create a GitHub Pull Request.

### Google Places Scraper Bot (`google_places_scraper_bot.py`)

*   **Purpose**: To scrape business information (specifically restaurants) from Google Maps search results.
*   **Workflow**:
    1.  Takes a search query (e.g., "restaurants in New York").
    2.  Performs a search on Google Maps and fetches the resulting HTML.
    3.  Parses the HTML to extract details for each restaurant found on the page, such as name, address, rating, and review count.
    4.  Appends the extracted data to a CSV file.

---

## Getting Started

### Prerequisites

*   Python 3.8+
*   Git
*   A Google AI API Key (only for the `code_agent.py`)
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

3.  **Set up your API Key (for Code Agent):**
    To get your Google API Key for Gemini:
    1.  Go to [Google AI Studio](https://aistudio.google.com/).
    2.  Log in with your Google account.
    3.  Click on the **"Get API key"** button (usually found in the top left or top right corner).
    4.  Click on **"Create API key in new project"** (or select an existing project if you have one).
    5.  Your API key will be generated. Copy it and keep it safe.

    The script will prompt you for this key on the first run, or you can set it as an environment variable named `GOOGLE_API_KEY` for a more permanent setup.

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

### Google Places Scraper Bot

The Scraper Bot runs from the command line and saves its output to a CSV file.

**Basic Usage:**

```bash
python google_places_scraper_bot.py --query "restaurants in San Francisco" --output-file sf_restaurants.csv
```

**Arguments:**

*   `--query` (required): The search query, e.g., 'restaurants in San Francisco'.
*   `--output-file`: The path to the output CSV file (defaults to `restaurants.csv`).

---
## Project Structure

*   `code_agent.py`: The main script for the autonomous coding agent.
*   `google_places_scraper_bot.py`: The main script for the Google Maps restaurant scraper.
*   `scraper_html_parser.py`: A helper module for parsing HTML from Google Maps.
*   `code_agent_models.py`: Pydantic models used by the agents (e.g., `CodeAnalysis`, `Restaurant`).
*   `shared_agents_utils.py`: Common utilities for file I/O, Git operations, and base AI agent configuration.
*   `web_server_utils.py`: Utilities for the local web server used for user interaction.
*   `html_utils.py`: Helper functions for generating the HTML page used by the Code Agent for the interactive approval process.
*   `app_description.txt`: A high-level description of the project to provide context to the agent.
*   `requirements.txt`: A list of Python packages required to run the agent.
*   `LICENSE`: The license for the project.

---
