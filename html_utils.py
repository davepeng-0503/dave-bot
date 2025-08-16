#!/usr/bin/env python
"""
Utilities for generating the HTML viewer for the Code Agent's user interaction.

This module reads the static CSS and JavaScript files, injects them into a main
HTML template, and serves it from a temporary file.
"""

import logging
import os
import tempfile
from typing import List, Optional

from html_templates import get_main_html_template


def _read_static_file(file_path: str) -> str:
    """Reads a static file and returns its content."""
    try:
        # Assuming static files are in a 'static' directory relative to this file
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # If html_utils.py is at the root, the path is correct.
        # If it's in a subdirectory, this might need adjustment, but for this project structure it's fine.
        full_path = os.path.join(base_dir, file_path)
        if not os.path.exists(full_path):
             # Fallback for running from a different working directory
             full_path = os.path.join(os.getcwd(), file_path)

        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"Static file not found at expected paths: {file_path}")
        return ""
    except Exception as e:
        logging.error(f"Error reading static file {file_path}: {e}")
        return ""


def create_code_agent_html_viewer(port: int, all_repo_files: List[str]) -> Optional[str]:
    """
    Generates a self-contained HTML viewer for the code agent lifecycle.

    This function reads the CSS and JavaScript from the static files,
    embeds them into the main HTML template, and writes the result to a
    temporary file.

    Args:
        port: The port the web server is running on. (Currently unused in the new design
              but kept for API compatibility).
        all_repo_files: A list of all files in the repository. (This is now passed
                        via status updates, so it is not injected directly here).

    Returns:
        The file path to the generated temporary HTML file, or None on failure.
    """
    # The port and all_repo_files arguments are maintained for API compatibility
    # with code_agent.py, but the new JS fetches data dynamically from the server.

    css_content = _read_static_file("static/css/style.css")
    js_content = _read_static_file("static/js/script.js")

    if not css_content or not js_content:
        logging.error(
            "Could not read necessary static CSS/JS files. Aborting HTML generation."
        )
        return None

    # The new design passes repository files via a status update,
    # so we don't need to inject them here anymore.
    html_content = get_main_html_template(
        css_content=css_content, js_content=js_content
    )

    try:
        # Use a temporary file to avoid cluttering the user's directory
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".html", encoding="utf-8"
        ) as f:
            viewer_file_path = f.name
            f.write(html_content)
        logging.info(f"✅ Viewer HTML saved to temporary file: {viewer_file_path}")
        return viewer_file_path
    except Exception as e:
        logging.error(f"❌ Could not write the HTML viewer file: {e}")
        return None
