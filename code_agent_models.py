from typing import List, Optional
from pydantic import BaseModel, Field
# --- Pydantic Models for Code Analysis & Generation ---

class NewFile(BaseModel):
    """Represents a new file that needs to be created for the task."""
    file_path: str = Field(description="The full path for the new file to be created.")
    reasoning: str = Field(description="Brief explanation of why this file is needed.")
    content_suggestions: List[str] = Field(
        default=[],
        description="A list of suggested functions, classes, or other code structures for the new file."
    )

class CodeAnalysis(BaseModel):
    """Represents the initial analysis of the codebase for a given task."""
    branch_name: str = Field(
        description="A short, descriptive, git-friendly branch name based on the task, always prefixed with 'dave-bot/' (e.g., 'dave-bot/feat/add-user-auth', 'dave-bot/fix/bug-in-payment-processor')."
    )
    plan: List[str] = Field(
        default=[],
        description="A detailed, step-by-step plan of what needs to be done to accomplish the task."
    )
    relevant_files: List[str] = Field(
        default=[],
        description="A list of existing file paths that are most relevant to read for understanding the context."
    )
    files_to_edit: List[str] = Field(
        default=[],
        description="A list of existing file paths that will likely need to be modified to complete the task."
    )
    files_to_create: List[NewFile] = Field(
        default=[],
        description="A list of new files that should be created to complete the task."
    )
    generation_order: List[str] = Field(
        default=[],
        description="The recommended order to process files (both creating and editing) to satisfy dependencies. For example, create a utility file before editing a file that uses it."
    )
    reasoning: str = Field(
        default="",
        description="A brief, high-level explanation of the overall strategy, why these files were chosen, and why the generation order is correct."
    )
    additional_grep_queries_needed: List[str] = Field(
        default=[],
        description="A list of additional 'git grep' queries that you believe would significantly improve your confidence in the plan. If you are less than 90% confident, you should request more information via grep. Leave empty if you are confident."
    )
    use_flash_model: bool = Field(
        default=False,
        description="Set to true if the task is simple (e.g., minor text changes, version bumps, simple refactors) and can be handled by a faster, less powerful model for code generation. For complex tasks, leave as false."
    )
    user_request: str = Field(
        default="",
        description="If you are blocked and need to ask the user a clarifying question to proceed, state your question here. The user will provide an answer, and you will be re-run with their response. Only use this if you are blocked."
    )


class GeneratedCode(BaseModel):
    """Represents the AI-generated code for a single file."""
    file_path: str = Field(description="The path of the file for which code is being generated.")
    code: str = Field(description="The complete, production-ready source code for the file.")
    summary: str = Field(description="A concise summary of the changes made to the file. This should be a high-level overview of what was changed, added, or removed.")
    reasoning: str = Field(description="A brief explanation of why the changes were made, linking them back to the overall task.")
    requires_more_context: bool = Field(
        default=False,
        description="Set to true if you cannot generate the code for the CURRENT file due to insufficient context."
    )
    context_request: str = Field(
        default="",
        description="If requires_more_context is true, explain what specific information or files are needed to generate the CURRENT file."
    )
    needed_context_for_future_files: List[str] = Field(
        default=[],
        description="A list of additional file paths that should be added to the context for subsequent file generation steps. Use this even if you were able to generate the current file successfully. Provide file paths from the full list of repository files."
    )
    add_to_generation_queue: List[str] = Field(
        default=[],
        description="A list of file paths (new or existing) that you believe need to be generated or regenerated to complete the task. You can use this to add files that were missed in the initial plan, or to revisit a file you have already generated if you realize a change is needed."
    )

class GeneratedCodeWithDiff(GeneratedCode):
    """Represents a generated code file along with its git diff."""
    git_diff: str = Field(description="The git diff of the changes for the file.")

# --- Pydantic Models for Google Places Scraper Bot ---

class Restaurant(BaseModel):
    """Represents the structured information for a single restaurant."""
    name: str = Field(description="The name of the restaurant.")
    address: Optional[str] = Field(default=None, description="The full address of the restaurant.")
    phone_number: Optional[str] = Field(default=None, description="The contact phone number of the restaurant.")
    website: Optional[str] = Field(default=None, description="The official website of the restaurant.")
    rating: Optional[float] = Field(default=None, description="The average user rating, typically out of 5.")
    reviews_count: Optional[int] = Field(default=None, description="The total number of user reviews.")
    cuisine: Optional[List[str]] = Field(default=[], description="A list of cuisines or categories the restaurant belongs to.")
