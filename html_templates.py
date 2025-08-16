"""
This module provides the main HTML template for the AI Code Agent's web interface.
"""

from html_components import (
    get_done_view,
    get_error_view,
    get_generating_view,
    get_plan_review_view,
    get_planning_view,
    get_user_input_view,
)


def get_main_html_template(css_content: str, js_content: str) -> str:
    """
    Generates the main HTML structure for the Code Agent web viewer.

    This function assembles a complete, self-contained HTML document by embedding
    the provided CSS and JavaScript content, and including the various UI
    components for different states of the agent's operation.

    Args:
        css_content: A string containing the full CSS stylesheet.
        js_content: A string containing the full JavaScript application code.

    Returns:
        A string containing the complete HTML document.
    """
    # Get the HTML for each view from html_components
    planning_view = get_planning_view()
    plan_review_view = get_plan_review_view()
    user_input_view = get_user_input_view()
    generating_view = get_generating_view()
    done_view = get_done_view()
    error_view = get_error_view()

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Code Agent</title>
    <style>
        {css_content}
    </style>
</head>
<body>
    <div class="container">
        <h1>AI Code Agent</h1>
        
        <!-- Views will be shown/hidden by JavaScript based on status -->
        <div id="planning-view" class="hidden">
            {planning_view}
        </div>

        <div id="plan-review-view" class="hidden">
            {plan_review_view}
        </div>

        <div id="user-input-view" class="hidden">
            {user_input_view}
        </div>

        <div id="generating-view" class="hidden">
            {generating_view}
        </div>

        <div id="done-view" class="hidden">
            {done_view}
        </div>

        <div id="error-view" class="hidden">
            {error_view}
        </div>

    </div>

    <script>
        {js_content}
    </script>
</body>
</html>
"""
    return html_content
