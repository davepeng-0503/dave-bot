"""
This module provides functions that generate HTML components for the AI Code Agent's web interface.
Each function corresponds to a specific view or state of the agent.
"""

def get_planning_view():
    """Returns the HTML for the planning view."""
    return """
        <div class="card">
            <h2>Planning...</h2>
            <p>The agent is analyzing the request and planning the necessary code changes.</p>
            <div class="spinner"></div>
            <div class="progress-container">
                <div id="planning-progress" class="progress-bar" style="width: 0%;"></div>
            </div>
            <h3 class="mt-4">Agent Log</h3>
            <div id="timeline" class="timeline"></div>
        </div>
    """

def get_plan_review_view():
    """Returns the HTML for the plan review view."""
    return """
        <div class="card">
            <h2>Plan Review</h2>
            <p>Please review the agent's plan. You can approve it, reject it, or provide feedback to refine it.</p>
            
            <div id="plan-and-reasoning" class="card-nested">
                <!-- Plan and reasoning will be injected here by JS -->
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
                <p>If you think the agent is missing context, add more files to the plan. These files will be read and added to the context for the generation step.</p>
                <div class="autocomplete">
                    <input id="context-file-input" type="text" placeholder="Start typing to search for a file...">
                    <div id="autocomplete-list" class="autocomplete-items hidden"></div>
                </div>
                <button id="add-context-file-btn" class="button">Add File</button>
                <h4>Added Context Files:</h4>
                <ul id="user-context-files-list"></ul>
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
    """

def get_user_input_view():
    """Returns the HTML for the user input view."""
    return """
        <div class="card">
            <h2>Agent Requires Input</h2>
            <p id="user-input-prompt"></p>
            <textarea id="user-input-area" placeholder="Your response..."></textarea>
            <button id="send-user-input-btn" class="button">Submit</button>
        </div>
    """

def get_generating_view():
    """Returns the HTML for the code generation view."""
    return """
        <div class="card">
            <h2>Generating Code</h2>
            <p>The agent is writing the code. Please wait.</p>
            <div class="progress-container">
                <div id="generation-progress" class="progress-bar" style="width: 0%;"></div>
            </div>
            <p>
                <span id="completed-files-count">0</span>/<span id="total-files-count">0</span> files generated
            </p>
            
            <div class="file-lists">
                <div class="file-list-column">
                    <h3>Completed</h3>
                    <div id="completed-files-container">
                        <!-- Completed file details will be appended here -->
                    </div>
                </div>
                <div class="file-list-column">
                    <h3>Pending</h3>
                    <ul id="pending-files-list"></ul>
                </div>
            </div>
        </div>
    """

def get_done_view():
    """Returns the HTML for the done view."""
    return """
        <div class="card">
            <h2>Task Completed!</h2>
            <p id="done-message">The agent has finished the task.</p>
            <div id="commit-message">
                <!-- Commit message will be injected here by JS -->
            </div>
            <p>You can now close this window.</p>
        </div>
    """

def get_error_view():
    """Returns the HTML for the error view."""
    return """
        <div class="card">
            <h2>An Error Occurred</h2>
            <p id="error-message" class="error-text"></p>
        </div>
    """
