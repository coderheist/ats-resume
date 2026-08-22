"""
The tool (function-calling) schema the conversational agent is constrained
to. Per blueprint Section 4.3 / 4.5: the agent never rewrites the document
as free text -- it emits a dot-path patch against the JSON Resume schema,
and the server applies it deterministically.
"""

APPEND_WORK_HIGHLIGHT_TOOL = {
    "name": "append_work_highlight",
    "description": (
        "Append one polished, quantified achievement bullet to a specific "
        "job in the candidate's work history. Only call this once you have "
        "enough concrete detail (what was done, on what system/scope, and "
        "a measurable outcome) to write a strong bullet -- do not call it "
        "with vague or generic content."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "work_index": {
                "type": "integer",
                "description": "Index into resume.work[] this highlight belongs to.",
            },
            "highlight_text": {
                "type": "string",
                "description": "The polished bullet point text, starting with a strong action verb.",
            },
        },
        "required": ["work_index", "highlight_text"],
    },
}

ASK_CLARIFYING_QUESTION_TOOL = {
    "name": "ask_clarifying_question",
    "description": (
        "Ask the candidate one targeted question to fill a missing detail "
        "(system/scope, scale, or measurable outcome) before writing a "
        "bullet point. Only use when the missing detail would materially "
        "change the resulting bullet -- not for every utterance."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "missing_slot": {
                "type": "string",
                "enum": ["scope", "scale", "outcome_metric"],
            },
        },
        "required": ["question", "missing_slot"],
    },
}

VOICE_AGENT_TOOLS = [APPEND_WORK_HIGHLIGHT_TOOL, ASK_CLARIFYING_QUESTION_TOOL]
