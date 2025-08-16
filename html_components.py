"""
This module provides functions that generate HTML components for the AI Code Agent's web interface.
Each function corresponds to a specific view or state of the agent.
"""

def get_planning_view():
    """Returns the HTML for the planning view."""
    return """
        <div id="status-planning" class="hidden">
            <div class="card">
                <h2>Planning...</h2>
                <p>The agent is analyzing the request and planning the necessary code changes.</p>
                <div class="spinner"></div>
                <div class="progress-container">
                    <div id="planning-progress-bar" class="progress-bar" style="width: 0%;"></div>
                </div>
                <h3 class="mt-4">Agent Log</h3>
                <div id="timeline" class="timeline"></div>
            </div>
        </div>
    """

def get_plan_review_view():
    """Returns the HTML for the plan review view."""
    return """
        <div id="status-plan-review" class="hidden">
            <div class="card">
                <h2>Plan Review</h2>
                <p>Please review the agent's plan. You can approve it, reject it, or provide feedback to refine it.</p>
                
                <div class="card-nested">
                    <h3>Reasoning</h3>
                    <p id="plan-reasoning"></p>
                </div>

                <div class="card-nested">
                    <h3>Relevant Files (for context)</h3>
                    <ul id="relevant-files-list"></ul>
                </div>

                <div class="card-nested">
                    <h3>Files to Edit/Create</h3>
                    <ul id="files-to-edit-list"></ul>
                </div>
                
                <div class="card-nested">
                    <h3>Generation Order</h3>
                    <ol id="generation-order-list"></ol>
                </div>

                <div class="card-nested">
                    <h3>Add Context Files</h3>
                    <p>If you think the agent is missing context, add more files to the plan.</p>
                    <div class="autocomplete">
                        <input id="context-file-input" type="text" placeholder="Start typing to search for a file...">
                    </div>
                    <button id="add-context-file-btn" class="button">Add Context File</button>
                </div>

                <div class="card-nested">
                    <h3>Provide Feedback</h3>
                    <p>Provide feedback to the agent to refine the plan.</p>
                    <textarea id="feedback-input" placeholder="e.g., 'Please use a different library for this task.'"></textarea>
                    <button id="send-feedback-btn" class="button">Refine Plan</button>
                </div>

                <div class="actions">
                    <button id="approve-btn" class="button">Approve Plan</button>
                    <button id="reject-btn" class="button reject-btn">Reject Plan</button>
                </div>
            </div>
        </div>
    """

def get_user_input_view():
    """Returns the HTML for the user input view."""
    return """
        <div id="status-user-input" class="hidden">
            <div class="card">
                <h2>Agent Requires Input</h2>
                <p id="user-prompt"></p>
                <textarea id="user-input-text" placeholder="Your response..."></textarea>
                <button id="submit-user-input-btn" class="button">Submit</button>
            </div>
        </div>
    """

def get_generating_view():
    """Returns the HTML for the code generation view."""
    return """
        <div id="status-generating" class="hidden">
            <div class="card">
                <h2>Generating Code</h2>
                <p>The agent is writing the code. Please wait.</p>
                <div class="progress-container">
                    <div id="generation-progress-bar" class="progress-bar" style="width: 0%;"></div>
                </div>
                <p id="generation-progress-text">0/0 files generated</p>
                
                <div class="file-lists">
                    <div>
                        <h3>Completed</h3>
                        <ul id="completed-files"></ul>
                    </div>
                    <div>
                        <h3>Pending</h3>
                        <ul id="pending-files"></ul>
                    </div>
                </div>
            </div>
        </div>
    """

def get_done_view():
    """Returns the HTML for the done view."""
    return """
        <div id="status-done" class="hidden">
            <div class="card">
                <h2>Task Completed!</h2>
                <p>The agent has finished the task. The changes have been committed.</p>
                <h3>Commit Message</h3>
                <pre id="commit-message" class="diff-container"></pre>
                <p>You can now close this window.</p>
            </div>
        </div>
    """

def get_error_view():
    """Returns the HTML for the error view."""
    return """
        <div id="status-error" class="hidden">
            <div class="card">
                <h2>An Error Occurred</h2>
                <p id="error-message" class="error-text"></p>
            </div>
        </div>
    """
