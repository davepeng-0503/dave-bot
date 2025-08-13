"""
A web interface for running the AI developer agents in this repository.

This script launches a Flask web server that provides a user interface to
run the code, code review, and advise agents. It allows users to specify
all relevant command-line arguments through a web form and view the
agent's output in real-time.
"""
import os
import subprocess
import sys
from flask import Flask, render_template, request, Response

# Initialize the Flask application.
# Flask will look for the 'index.html' template in the 'templates' folder.
app = Flask(__name__, template_folder='templates')

# Define a port for the agents' own approval web servers.
# This avoids conflicts with the main UI's port (5000).
AGENT_APPROVAL_PORT = 8081

@app.route('/')
def index():
    """
    Renders the main web page that contains the forms for running the agents.
    """
    return render_template('index.html')

@app.route('/run', methods=['POST'])
def run_agent():
    """
    Handles the form submission to run an agent.

    It constructs the appropriate command-line arguments based on the form data,
    runs the agent script as a subprocess, and streams its stdout/stderr
    back to the client using Server-Sent Events (SSE).
    """
    data = request.form
    agent = data.get('agent')

    if not agent or f"{agent}.py" not in ['advise_agent.py', 'code_review_agent.py', 'code_agent.py']:
        return Response("Error: Invalid agent specified.", status=400, mimetype='text/plain')

    # Use the same Python interpreter that is running this web interface.
    python_executable = sys.executable
    cmd = [python_executable, f"{agent}.py"]

    # --- Argument Construction ---

    # The --task argument is required for all agents.
    task = data.get('task')
    if task:
        cmd.extend(['--task', task])
    else:
        return Response("Error: The 'task' field is required.", status=400, mimetype='text/plain')

    # Optional arguments common to all agents.
    if directory := data.get('dir'):
        cmd.extend(['--dir', directory])

    if app_description := data.get('app_description'):
        cmd.extend(['--app-description', app_description])

    # --- Agent-Specific Arguments ---

    if agent == 'code_review_agent':
        if compare_branch := data.get('compare'):
            cmd.extend(['--compare', compare_branch])
        # The 'strict' checkbox determines whether to add --strict or --no-strict.
        if 'strict' in data:
            cmd.append('--strict')
        else:
            cmd.append('--no-strict')

    if agent == 'code_agent':
        if 'strict' in data:
            cmd.append('--strict')
        else:
            cmd.append('--no-strict')
        # This agent may start its own web server, so we pass a non-conflicting port.
        cmd.extend(['--port', str(AGENT_APPROVAL_PORT)])

    if agent == 'advise_agent':
        # This agent may also start its own web server.
        cmd.extend(['--port', str(AGENT_APPROVAL_PORT)])

    # The --force flag bypasses the agent's browser-based approval step.
    if 'force' in data:
        cmd.append('--force')

    def generate_output():
        """
        A generator function that runs the subprocess and yields its output line by line.
        """
        try:
            # Start the agent script as a subprocess.
            # The output is piped, and stderr is redirected to stdout.
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,  # Line-buffered
                cwd=os.path.dirname(os.path.abspath(__file__)) # Run from script's dir
            )

            # Send initial messages to the client.
            yield "data: Process started...\n\n"
            yield f"data: > {' '.join(cmd)}\n\n"
            yield "data: \n\n"

            # Stream the agent's output in real-time.
            while True:
                output = process.stdout.readline()
                if output:
                    # Format the output as a Server-Sent Event.
                    cleaned_output = output.strip().replace('\n', '<br>')
                    yield f"data: {cleaned_output}\n\n"
                
                # Break the loop if the process has finished and there's no more output.
                if process.poll() is not None and not output:
                    break
            
            return_code = process.poll()
            yield "data: \n\n"
            yield f"data: Process finished with exit code: {return_code}\n\n"

        except FileNotFoundError:
            yield f"data: Error: The script for agent '{agent}' was not found.\n\n"
        except Exception as e:
            yield f"data: An unexpected error occurred: {str(e)}\n\n"

    # Return a streaming response to the client.
    return Response(generate_output(), mimetype='text/event-stream')

if __name__ == '__main__':
    """
    Runs the Flask development server.
    
    Note: The agents themselves may open new browser tabs for user approval.
    This web interface acts as a launcher and a central log viewer for them.
    """
    # Running on port 5000 to avoid conflict with agents' default port 8080.
    app.run(debug=True, port=5000)
