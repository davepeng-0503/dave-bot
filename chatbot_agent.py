#!/usr/bin/env python
"""
An intelligent chatbot that analyzes user queries and routes them to the
appropriate AI model and tools for an optimal response.
"""
import argparse
import json
import logging
import os
from typing import Any, Callable, List

from code_agent_models import QueryAnalysis, QueryCategory
from pydantic_ai import Agent
from pydantic_ai.models import LLMOptions
from pydantic_ai.models.google import GoogleModelSettings
from shared_agents_utils import (AgentTools, BaseAiAgent, get_git_files,
                                 read_file_content)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class ChatbotAgent(BaseAiAgent):
    """
    An intelligent agent that routes user queries to the best model and tools.
    """

    def __init__(self, directory: str, app_description_path: str):
        """
        Initializes the ChatbotAgent.

        Args:
            directory: The root directory of the codebase.
            app_description_path: Path to the application description file.
        """
        super().__init__()
        self.directory = directory
        self.agent_tools = AgentTools(directory)
        self.all_repo_files = get_git_files(directory)
        self.app_description = read_file_content(directory, app_description_path) or ""

        # --- Agent Definitions ---
        self.query_analyzer = self._create_query_analyzer()
        self.codebase_agent = self._create_codebase_agent()
        self.general_agent = self._create_general_agent()
        self.complex_agent = self._create_complex_agent()

    def _create_agent(
        self,
        model_name: str,
        system_prompt: str,
        tools: List[Callable[..., Any]] = None,
    ) -> Agent:
        """Helper function to create a configured pydantic-ai Agent."""
        return Agent(
            self._get_gemini_model(model_name),
            system_prompt=system_prompt,
            tools=tools or [],
        )

    def _create_query_analyzer(self) -> Agent:
        """Creates the agent responsible for categorizing user queries."""
        system_prompt = f"""
You are an expert routing agent. Your task is to analyze a user's query and categorize it into one of the following categories:

1.  **codebase_specific**: For questions that are directly about the code in this repository. This includes asking for file locations, the content of a file, how a specific function is used, or searching for a term in the code.
    *   Examples: "Where is `html_utils.py`?", "Show me `app_description.txt`", "Find all uses of `web_server_utils`".

2.  **general_knowledge**: For questions that are not related to this specific codebase and can be answered with general programming or world knowledge.
    *   Examples: "What's the difference between a list and a tuple in Python?", "Explain object-oriented programming."

3.  **complex_task**: For queries that require both understanding the codebase AND performing a complex reasoning task, like analysis, debugging, or suggesting new features. These are open-ended and require a deeper understanding than simple lookups.
    *   Examples: "Analyze `code_agent.py` and suggest improvements.", "How could I add a new feature to the web server?", "Debug a potential issue in `shared_agents_utils.py`."

4.  **ambiguous**: If the query is unclear and could fit into multiple categories. For example, "Tell me about agents" could be general or codebase-specific.

Here is the full list of files in the repository to help you identify codebase-specific terms:
{json.dumps(self.all_repo_files, indent=2)}

If you categorize as 'ambiguous', you MUST provide a `clarification_question` to help the user specify their intent. Otherwise, leave it empty.
"""
        return self._create_agent(
            model_name="gemini-2.5-flash",
            system_prompt=system_prompt,
        )

    def _create_codebase_agent(self) -> Agent:
        """Creates the agent for answering simple, factual questions about the code."""
        system_prompt = """
You are a helpful AI assistant specialized in answering specific, factual questions about the current codebase.
Use the provided tools (`git_grep_search` and `read_file`) to find information.
Your answers should be concise, accurate, and directly address the user's question based on the tool output.
"""
        return self._create_agent(
            model_name="gemini-2.5-flash",
            system_prompt=system_prompt,
            tools=[self.agent_tools.git_grep_search, self.agent_tools.read_file],
        )

    def _create_general_agent(self) -> Agent:
        """Creates the agent for answering general knowledge questions."""
        system_prompt = """
You are a helpful and knowledgeable AI assistant.
Answer the user's general knowledge question clearly and concisely.
"""
        return self._create_agent(
            model_name="gemini-2.5-pro", system_prompt=system_prompt
        )

    def _create_complex_agent(self) -> Agent:
        """Creates the agent for complex reasoning and analysis of the codebase."""
        system_prompt = f"""
You are an expert senior software architect. Your task is to analyze the user's request, which requires deep understanding and reasoning about the provided codebase.
Use the tools (`git_grep_search` and `read_file`) to explore the code, then provide a comprehensive answer, analysis, or suggestion.
Think step-by-step and explain your reasoning clearly.

Here is a high-level description of the application to give you context:
---
{self.app_description}
---
"""
        return self._create_agent(
            model_name="gemini-2.5-pro",
            system_prompt=system_prompt,
            tools=[self.agent_tools.git_grep_search, self.agent_tools.read_file],
        )

    def analyze_query(self, user_query: str) -> QueryAnalysis:
        """
        Analyzes the user's query to determine the correct routing.

        Args:
            user_query: The user's input string.

        Returns:
            A QueryAnalysis object with the category and reasoning.
        """
        logging.info("Analyzing query...")
        response = self.query_analyzer.run_sync(
            prompt=user_query,
            output_type=QueryAnalysis,
            llm_options=LLMOptions(
                model_settings=GoogleModelSettings(
                    google_safety_settings=self.get_safety_settings()
                )
            ),
        )
        logging.info(f"Query categorized as: {response.output.category}")
        logging.info(f"Reasoning: {response.output.reasoning}")
        return response.output

    def chat(self):
        """
        Starts the main conversational loop for the chatbot.
        """
        print("🤖 Hello! I'm your intelligent codebase assistant. How can I help you?")
        print("   You can ask me about the code, general questions, or complex tasks.")
        print("   Type 'exit' or 'quit' to end the conversation.")

        last_query = ""
        while True:
            try:
                user_input = input("\n> ")
                if user_input.lower() in ["exit", "quit"]:
                    print("🤖 Goodbye!")
                    break

                # If the last query was ambiguous, prepend it to the user's clarification
                if last_query:
                    user_input = (
                        f"Original query: '{last_query}'\nMy answer to your clarification question: '{user_input}'"
                    )
                    last_query = ""

                analysis = self.analyze_query(user_input)

                agent_to_run = None
                if analysis.category == QueryCategory.CODEBASE_SPECIFIC:
                    print("🤖 Asking the codebase expert (Flash)...")
                    agent_to_run = self.codebase_agent
                elif analysis.category == QueryCategory.GENERAL_KNOWLEDGE:
                    print("🤖 Consulting my general knowledge (Pro)...")
                    agent_to_run = self.general_agent
                elif analysis.category == QueryCategory.COMPLEX_TASK:
                    print("🤖 Engaging senior architect for complex analysis (Pro)...")
                    agent_to_run = self.complex_agent
                elif analysis.category == QueryCategory.AMBIGUOUS:
                    print(f"🤖 {analysis.clarification_question}")
                    last_query = user_input
                    continue

                if agent_to_run:
                    print("-" * 20)
                    # Stream the response
                    for chunk in agent_to_run.run(
                        prompt=user_input,
                        llm_options=LLMOptions(
                            model_settings=GoogleModelSettings(
                                google_safety_settings=self.get_safety_settings()
                            )
                        ),
                    ):
                        print(chunk, end="", flush=True)
                    print("\n" + "-" * 20)

            except KeyboardInterrupt:
                print("\n🤖 Goodbye!")
                break
            except Exception as e:
                logging.error(f"An unexpected error occurred: {e}")
                print("🤖 I'm sorry, an error occurred. Please try again.")


def main():
    """Main function to run the chatbot agent."""
    parser = argparse.ArgumentParser(
        description="An intelligent chatbot for interacting with your codebase."
    )
    parser.add_argument(
        "--dir",
        type=str,
        default=os.getcwd(),
        help="The directory of the git repository.",
    )
    parser.add_argument(
        "--app-description",
        type=str,
        default="app_description.txt",
        help="Path to a text file describing the app's purpose.",
    )
    args = parser.parse_args()

    try:
        chatbot = ChatbotAgent(
            directory=args.dir, app_description_path=args.app_description
        )
        chatbot.chat()
    except ValueError as e:
        logging.error(e)


if __name__ == "__main__":
    main()
