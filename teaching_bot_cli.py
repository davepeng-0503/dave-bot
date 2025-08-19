#!/usr/bin/env python
"""
This module provides a command-line interface (CLI) to run the AI Teaching Bot.
It sets up a web server to host the chat interface, manages the conversation state,
and orchestrates the interaction between the user and the AI agent.
"""

import argparse
import logging
import os
import sys
import threading
import webbrowser
from typing import Optional

from teaching_bot_agent import TeachingBotAgent
from teaching_bot_html_utils import create_teaching_bot_html_viewer
from teaching_bot_models import ConversationTurn, TeachingAction, TeachingState
from teaching_bot_web_server_utils import (
    TeachingBotHandler,
    TeachingBotWebServer,
)
from web_server_utils import find_available_port

# --- Configuration ---
DEFAULT_SERVER_PORT = 8081

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class TeachingBotCLI:
    """Manages the command-line interface and orchestrates the teaching bot session."""

    def __init__(self):
        """Initializes the CLI manager."""
        self.args = self._parse_args()
        self.agent = TeachingBotAgent()
        self.state = TeachingState()
        self.server: Optional[TeachingBotWebServer] = None

    def _parse_args(self) -> argparse.Namespace:
        """Parses command-line arguments."""
        parser = argparse.ArgumentParser(description="An AI-powered teaching bot.")
        parser.add_argument(
            "--port",
            type=int,
            default=DEFAULT_SERVER_PORT,
            help=f"The port to run the web server on (default: {DEFAULT_SERVER_PORT}).",
        )
        return parser.parse_args()

    def _update_state_after_action(self, action: TeachingAction, user_message: str):
        """Updates the conversation state based on the bot's last action."""
        # Add the bot's speech to history
        self.state.conversation_history.append(
            ConversationTurn(role="bot", content=action.speech)
        )

        # Update understanding level
        if action.user_understanding_level:
            self.state.user_understanding_level = action.user_understanding_level

        # If this was the first turn, the user's message is the subject
        if self.state.subject is None and action.action_type != "GREET_AND_ASK_SUBJECT":
            # A heuristic: the user's message after the greeting is the subject.
            self.state.subject = user_message
            self.state.current_topic = user_message

        # Handle topic changes
        if action.action_type == "CONCLUDE_TOPIC":
            if self.state.current_topic:
                self.state.topics_covered.append(self.state.current_topic)
            self.state.current_topic = None  # Ready for a new topic

        elif action.action_type == "CHANGE_TOPIC":
            # Reset state for a new subject
            if self.state.current_topic:
                self.state.topics_covered.append(self.state.current_topic)
            self.state.subject = None
            self.state.current_topic = None

        # If a topic was concluded, the next user message sets the new topic
        elif self.state.current_topic is None and self.state.subject is not None:
            self.state.current_topic = user_message

    def _conversation_loop(self):
        """The main loop that handles the conversation flow."""
        logging.info("Starting conversation loop...")

        # 1. Initial greeting from the bot
        try:
            initial_action = self.agent.get_next_action(
                self.state, "<initial_greeting>"
            )
            if self.server:
                self.server.send_bot_message(initial_action.model_dump())
            self.state.conversation_history.append(
                ConversationTurn(role="bot", content=initial_action.speech)
            )
        except Exception as e:
            logging.error(f"Failed to get initial action from agent: {e}")
            return

        # 2. Main conversation loop
        while True:
            if not self.server:
                logging.error("Web server is not running. Exiting loop.")
                break

            user_message = self.server.wait_for_user_message()
            logging.info(f"User message received: {user_message}")

            # Add user message to history
            self.state.conversation_history.append(
                ConversationTurn(role="user", content=user_message)
            )

            try:
                # Get the next action from the agent
                action = self.agent.get_next_action(self.state, user_message)
                logging.info(f"Bot action determined: {action.action_type}")

                # Send the action to the UI
                self.server.send_bot_message(action.model_dump())

                # Update the state based on the action
                self._update_state_after_action(action, user_message)

            except Exception as e:
                logging.error(
                    f"An error occurred while processing the conversation turn: {e}"
                )
                # Send an error message to the user
                error_message = {
                    "action_type": "EXPLAIN_CONCEPT",
                    "speech": "I'm sorry, I encountered an error. Please try again or restart the application.",
                    "explanation": f"Error details: {e}",
                }
                if self.server:
                    self.server.send_bot_message(error_message)

    def run(self):
        """The main entry point for the CLI tool."""
        actual_port = find_available_port(self.args.port)
        if actual_port is None:
            logging.error(
                f"Could not find an available port starting from {self.args.port}. Aborting."
            )
            return

        viewer_html_path = create_teaching_bot_html_viewer(actual_port)
        if not viewer_html_path:
            logging.error("Failed to create the HTML viewer file. Aborting.")
            return

        try:
            self.server = TeachingBotWebServer(
                ("", actual_port), TeachingBotHandler, html_file_path=viewer_html_path
            )
            server_thread = threading.Thread(target=self.server.serve_forever)
            server_thread.daemon = True
            server_thread.start()

            url = f"http://localhost:{actual_port}"
            logging.info(f"Teaching Bot is running. Open your browser to: {url}")
            webbrowser.open(url)

            self._conversation_loop()

        except KeyboardInterrupt:
            logging.info("Keyboard interrupt received. Shutting down...")
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}", exc_info=True)
        finally:
            if self.server:
                logging.info("Shutting down web server.")
                self.server.shutdown()
                self.server.server_close()
            if viewer_html_path and os.path.exists(viewer_html_path):
                os.remove(viewer_html_path)
            logging.info("Shutdown complete.")
            sys.exit(0)


if __name__ == "__main__":
    cli = TeachingBotCLI()
    cli.run()
