#!/usr/bin/env python
"""
This module contains a simple web server for handling the interactive chat
for the AI Teaching Bot.
"""
import http.server
import json
import logging
import queue
import socketserver
import threading
from typing import Any, Dict, Optional, Tuple

from web_server_utils import find_available_port


class TeachingBotWebServer(socketserver.TCPServer):
    """A web server to handle the chat interface for the Teaching Bot."""

    allow_reuse_address = True

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: Any,
        html_file_path: str,
    ):
        super().__init__(server_address, RequestHandlerClass)
        self.html_file_path = html_file_path
        self.bot_message_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.user_message_queue: "queue.Queue[str]" = queue.Queue()
        self.user_message_event = threading.Event()

    def send_bot_message(self, message_data: Dict[str, Any]):
        """Puts a message from the bot into the queue for the UI to fetch."""
        self.bot_message_queue.put(message_data)

    def wait_for_user_message(self) -> str:
        """Blocks until a message from the user is received and returns it."""
        self.user_message_event.wait()
        message = self.user_message_queue.get()
        self.user_message_event.clear()
        return message

    def _add_user_message(self, message: str):
        """Called by the handler to record a user's message."""
        if not self.user_message_event.is_set():
            self.user_message_queue.put(message)
            self.user_message_event.set()


class TeachingBotHandler(http.server.BaseHTTPRequestHandler):
    """A simple HTTP request handler for the teaching bot server."""

    server: TeachingBotWebServer  # type: ignore

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
        """Handles GET requests for the main page and status updates."""
        if self.path == "/":
            try:
                with open(self.server.html_file_path, "rb") as f:
                    self._send_response(200, "text/html", f.read())
            except FileNotFoundError:
                self._send_response(404, "text/html", b"HTML file not found.")
        elif self.path == "/status":
            try:
                # Use long polling to wait for a message from the bot
                update = self.server.bot_message_queue.get(block=True, timeout=28)
                self._send_response(200, "application/json", json.dumps(update).encode("utf-8"))
            except queue.Empty:
                # Send 204 No Content if queue is empty after timeout
                self._send_response(204, "text/plain", b"")
        else:
            self._send_response(404, "text/html", b"Not Found")

    def do_POST(self):
        """Handles POST requests from the user."""
        if self.path == "/send_message":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data)
                message = data.get("message")

                if message is not None and isinstance(message, str):
                    self.server._add_user_message(message)
                    self._send_response(200, "application/json", b'{"status": "ok"}')
                else:
                    self._send_response(400, "text/plain", b"Invalid message format.")
            except (json.JSONDecodeError, KeyError):
                self._send_response(400, "text/plain", b"Invalid JSON or missing 'message' key.")
        else:
            self._send_response(404, "text/plain", b"Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress logging to keep the console clean."""
        return
