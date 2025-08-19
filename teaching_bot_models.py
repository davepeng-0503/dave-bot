from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Question(BaseModel):
    """A question to test the user's understanding."""

    question_text: str = Field(description="The text of the question.")
    question_type: Literal["multiple_choice", "open_ended"] = Field(
        description="The type of question."
    )
    choices: Optional[List[str]] = Field(
        default=None, description="A list of choices for a multiple-choice question."
    )
    answer_explanation: str = Field(
        description="A clear explanation of the correct answer, to be used when providing feedback."
    )


class TeachingAction(BaseModel):
    """
    Represents the AI's next action in the teaching conversation.
    This model structures the bot's response, guiding what it should say and do.
    """

    action_type: Literal[
        "GREET_AND_ASK_SUBJECT",
        "EXPLAIN_CONCEPT",
        "PROVIDE_EXAMPLE",
        "ASK_QUESTION",
        "PROVIDE_FEEDBACK",
        "CONCLUDE_TOPIC",
        "CHANGE_TOPIC",
    ] = Field(description="The specific type of action the bot should take in its turn.")

    speech: str = Field(
        description="The text the bot should say to the user for this turn. This is the primary conversational output."
    )

    explanation: Optional[str] = Field(
        default=None, description="A detailed explanation of a concept, theory, or fact."
    )

    example: Optional[str] = Field(
        default=None,
        description="A relevant and illustrative example to help the user understand the explanation.",
    )

    question: Optional[Question] = Field(
        default=None, description="A question to pose to the user to test their understanding."
    )

    feedback: Optional[str] = Field(
        default=None,
        description="Constructive feedback on the user's answer, explaining why it was right or wrong.",
    )

    is_correct: Optional[bool] = Field(
        default=None,
        description="Indicates if the user's last answer was correct. This is essential for the PROVIDE_FEEDBACK action.",
    )

    next_topic_suggestions: Optional[List[str]] = Field(
        default=None,
        description="A list of suggested next topics to continue the lesson, used when concluding a topic.",
    )

    user_understanding_level: Optional[Literal["beginner", "intermediate", "advanced"]] = Field(
        default="beginner",
        description="An assessment of the user's current understanding level to adapt the content's complexity going forward.",
    )


class ConversationTurn(BaseModel):
    """Represents one turn in the conversation from either the user or the bot."""

    role: Literal["user", "bot"]
    content: str


class TeachingState(BaseModel):
    """
    Represents the complete state of the teaching session at any given point.
    This object is used to provide the AI with the necessary context to make informed decisions.
    """

    subject: Optional[str] = Field(
        default=None, description="The subject the user wants to learn about."
    )
    current_topic: Optional[str] = Field(
        default=None, description="The specific topic currently being discussed."
    )
    conversation_history: List[ConversationTurn] = Field(
        default=[], description="The full history of the conversation, turn by turn."
    )
    user_understanding_level: Literal["beginner", "intermediate", "advanced"] = Field(
        default="beginner",
        description="The user's assessed understanding level, which adapts over time.",
    )
    topics_covered: List[str] = Field(
        default=[],
        description="A list of topics that have already been covered in the session to avoid repetition.",
    )
