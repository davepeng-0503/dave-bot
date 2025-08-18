#!/usr/bin/env python
"""
This module contains a simple web server for handling user approval and feedback
through a web browser interface. It is used by the AI agents to get confirmation
before applying changes.
"""
import http.server
import json
import logging
import socket
import socketserver
import threading
from typing import Any, Optional, Tuple


class ApprovalWebServer(socketserver.TCPServer):
    """A simple web server to get user approval for a plan."""

    allow_reuse_address = False

    def __init__(self, server_address: Tuple[str, int], RequestHandlerClass: Any, html_file_path: str):
        super().__init__(server_address, RequestHandlerClass)
        self.html_file_path = html_file_path
        self.decision_made = threading.Event()
        self.user_decision: Optional[str] = None
        self.user_data: Optional[Any] = None

    def set_decision(self, decision: str, data: Optional[Any] = None):
        """Called by the handler to record the user's decision."""
        if not self.decision_made.is_set():
            self.user_decision = decision
            self.user_data = data
            self.decision_made.set()

    def wait_for_decision(self) -> Tuple[Optional[str], Optional[Any]]:
        """Blocks until a decision is made and returns it."""
        self.decision_made.wait()
        return self.user_decision, self.user_data
        
    def reset_decision(self):
        """Resets the server's state to wait for a new decision."""
        self.decision_made.clear()
        self.user_decision = None
        self.user_data = None
        logging.info("Server has been reset and is waiting for a new decision.")


class ApprovalHandler(http.server.BaseHTTPRequestHandler):
    """A simple HTTP request handler for the approval server."""
    server: ApprovalWebServer # type: ignore

    def _send_response(self, code: int, content_type: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        """Handle pre-flight requests for CORS."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Handles GET requests."""
        if self.path == "/":
            try:
                with open(self.server.html_file_path, "rb") as f:
                    self._send_response(200, "text/html", f.read())
            except FileNotFoundError:
                error_body = (
                    b"<html><body><h1>Error 404</h1><p>HTML file not found.</p></body></html>"
                )
                self._send_response(404, "text/html", error_body)
        else:
            error_body = b"<html><body><h1>Error 404</h1><p>Not Found.</p></body></html>"
            self._send_response(404, "text/html", error_body)

    def do_POST(self):
        """Handles POST requests for user actions."""
        if self.path in ["/approve", "/reject", "/feedback", "/user_input"]:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length)

            action = self.path.lstrip("/")
            data: Optional[Any] = None

            if post_data:
                try:
                    data = json.loads(post_data)
                except json.JSONDecodeError:
                    self._send_response(400, "text/plain", b"Invalid JSON")
                    return

            # The payload for 'approve', 'feedback', and 'user_input' is a JSON object.
            # For 'reject', it's empty. In all cases, we pass the data object as is.
            self.server.set_decision(action, data)

            success_message = (
                f"Decision '{action}' received. You can close this window."
            )
            self._send_response(
                200,
                "text/html",
                f"<html><body><p>{success_message}</p><script>window.close();</script></body></html>".encode(
                    "utf-8"
                ),
            )
        else:
            self._send_response(404, "text/plain", b"Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress logging to keep the console clean."""
        return


def find_available_port(start_port: int, max_retries: int = 100) -> Optional[int]:
    """
    Finds an available TCP port on the local machine by trying to bind to it.

    Args:
        start_port: The port number to start searching from.
        max_retries: The maximum number of ports to try.

    Returns:
        An available port number, or None if no port is found within the range.
    """
    for i in range(max_retries):
        port = start_port + i
        try:
            # Create a socket, try to bind it, and then close it.
            # This is a reliable way to check if a port is available.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
            return port
        except OSError:
            logging.info(f"Port {port} is already in use, trying next port.")
    
    logging.error(f"Could not find an available port in the range {start_port}-{start_port + max_retries - 1}.")
    return None


def wait_for_user_approval_from_browser(
    html_file_path: str, port: int
) -> Tuple[Optional[str], Optional[Any]]:
    """
    Starts a local web server to display an HTML file and waits for user interaction.

    The server hosts the provided HTML file and listens for POST requests to:
    - /approve: User approves the plan.
    - /reject: User rejects the plan.
    - /feedback: User submits feedback text.

    Args:
        html_file_path: The absolute path to the HTML file to serve.
        port: The port on which to run the server.

    Returns:
        A tuple containing the action (e.g., 'approve', 'reject', 'feedback')
        and optional data (the feedback text or other payload).
    """
    server = None
    
    def handler(*args: Any, **kwargs: Any):
        return ApprovalHandler(*args, **kwargs)

    try:
        server = ApprovalWebServer(("", port), handler, html_file_path=html_file_path)
        logging.info(f"Starting temporary web server on http://localhost:{port}")

        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()

        decision, data = server.wait_for_decision()
        logging.info(f"User decision received: {decision}")
        return decision, data

    finally:
        if server:
            logging.info("Shutting down web server.")
            server.shutdown()
            server.server_close()
