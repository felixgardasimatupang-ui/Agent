"""
Agent types and specialized prompts for the AI Swarm Orchestrator.
Defines different agent capabilities and their system prompts.
"""
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Optional


class AgentType(Enum):
    """Supported agent types with different capabilities."""
    CODER = "coder"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    TRANSLATOR = "translator"
    WRITER = "writer"
    DEBUGGER = "debugger"
    ARCHITECT = "architect"
    SIMPLE = "simple"


@dataclass
class AgentProfile:
    """Profile defining agent behavior and capabilities."""
    agent_type: AgentType
    system_prompt: str
    preferred_model: str
    max_tokens: int = 2048
    temperature: float = 0.7


# Specialized system prompts for each agent type
AGENT_PROMPTS: Dict[AgentType, str] = {
    AgentType.CODER: """You are an expert programmer. WRITE COMPLETE, WORKING CODE directly.
- Output ONLY code. No explanations, no "let me check", no questions.
- Use proper imports, error handling, and type hints.
- Follow Python/JS/etc best practices.
- Include comments only for complex logic.
- Output in the language/framework specified in the task.""",

    AgentType.RESEARCHER: """You are a technical researcher. Provide CONCISE, ACTIONABLE findings.
- Output findings directly. No preamble.
- Use bullet points for clarity.
- Include code examples when relevant.
- Cite sources when possible.
- Focus on practical implementation details.""",

    AgentType.ANALYST: """You are a data analyst. Provide DATA-DRIVEN insights directly.
- Output analysis directly. No "let me" preamble.
- Use tables and bullet points.
- Quantify where possible.
- Include code snippets for data processing.
- Focus on actionable recommendations.""",

    AgentType.TRANSLATOR: """You are an expert translator. Output the translation DIRECTLY.
- Preserve original tone and style.
- Handle technical terms accurately.
- No explanations unless ambiguous.
- Output only the translated text.""",

    AgentType.WRITER: """You are a skilled writer. Output the content DIRECTLY.
- Structure clearly with headers.
- Use active voice.
- Keep it concise.
- Output only the written content.""",

    AgentType.DEBUGGER: """You are a debugging specialist. FIND AND FIX issues directly.
- Output the fixed code directly.
- Include the bug explanation in a comment.
- Consider edge cases.
- No "let me check" — produce the solution.""",

    AgentType.ARCHITECT: """You are a software architect. DESIGN the system directly.
- Output the architecture design directly.
- Include component diagrams (mermaid or ASCII).
- Specify file structure and key interfaces.
- Consider scalability and security.
- Output only the design document.""",

    AgentType.SIMPLE: """You are a helpful assistant. Answer DIRECTLY and CONCISELY.
- No preamble, no "certainly", no "I'd be happy to".
- Start with the answer.
- Use simple language.
- Output only the answer.""",
}

# Model preferences based on task complexity
MODEL_PREFERENCES: Dict[AgentType, str] = {
    AgentType.CODER: "murah",      # Fast code generation
    AgentType.RESEARCHER: "murah",  # Fast research
    AgentType.ANALYST: "murah",     # Fast analysis
    AgentType.TRANSLATOR: "murah",  # Fast translation
    AgentType.WRITER: "murah",      # Fast writing
    AgentType.DEBUGGER: "power",    # Needs reasoning
    AgentType.ARCHITECT: "power",   # Needs deep thinking
    AgentType.SIMPLE: "murah",      # Fast simple tasks
}


def get_agent_profile(agent_type: AgentType) -> AgentProfile:
    """Get the profile for a specific agent type."""
    return AgentProfile(
        agent_type=agent_type,
        system_prompt=AGENT_PROMPTS[agent_type],
        preferred_model=MODEL_PREFERENCES[agent_type],
    )


def classify_task_type(task_description: str) -> AgentType:
    """Classify a task description to determine the best agent type."""
    lower = task_description.lower()

    # Debug/error handling
    if any(kw in lower for kw in ["debug", "error", "fix", "bug", "issue", "crash"]):
        return AgentType.DEBUGGER

    # Research
    if any(kw in lower for kw in ["research", "find", "search", "investigate", "explore"]):
        return AgentType.RESEARCHER

    # Coding tasks
    if any(kw in lower for kw in ["code", "function", "class", "implement", "write", "program", "create", "module", "endpoint"]):
        return AgentType.CODER

    # Architecture/design
    if any(kw in lower for kw in ["architect", "design", "system", "scale", "structure"]):
        return AgentType.ARCHITECT

    # Analysis
    if any(kw in lower for kw in ["analyze", "analysis", "data", "insight", "pattern"]):
        return AgentType.ANALYST

    # Translation
    if any(kw in lower for kw in ["translate", "translation", "language", "localize"]):
        return AgentType.TRANSLATOR

    # Writing
    if any(kw in lower for kw in ["write", "draft", "content", "blog", "article"]):
        return AgentType.WRITER

    # Default to simple
    return AgentType.SIMPLE
