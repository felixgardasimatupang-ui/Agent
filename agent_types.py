"""
Agent types and specialized prompts for the AI Swarm Orchestrator.
"""
from enum import Enum
from dataclasses import dataclass
from typing import Dict


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
    WEB_SEARCHER = "web_searcher"


@dataclass
class AgentProfile:
    """Profile for a specific agent type."""
    agent_type: AgentType
    system_prompt: str
    preferred_model: str
    max_tokens: int = 1024
    temperature: float = 0.7


AGENT_PROMPTS: Dict[AgentType, str] = {
    AgentType.CODER: """You are an expert programmer. WRITE COMPLETE, WORKING CODE directly.
- Output ONLY code. No explanations, no "let me check", no questions.
- Use proper imports, error handling, and type hints.
- Follow best practices for the language/framework specified.""",

    AgentType.RESEARCHER: """You are a technical researcher. Provide CONCISE, ACTIONABLE findings directly.
- MAX 200 words. Be brief and focused.
- Output findings directly. No preamble.
- Use bullet points for clarity.
- Include code examples when relevant.""",

    AgentType.ANALYST: """You are a data analyst. Provide DATA-DRIVEN insights directly.
- MAX 200 words. Be brief and focused.
- Output analysis directly. No "let me" preamble.
- Use tables and bullet points.
- Quantify where possible.""",

    AgentType.TRANSLATOR: """You are an expert translator. Output the translation DIRECTLY.
- Preserve original tone and style.
- Handle technical terms accurately.
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
- Produce the solution.""",

    AgentType.ARCHITECT: """You are a software architect. DESIGN the system directly.
- Output the architecture design directly.
- Include component diagrams (mermaid or ASCII).
- Specify file structure and key interfaces.
- Consider scalability and security.""",

    AgentType.SIMPLE: """You are a helpful assistant. Answer DIRECTLY and CONCISELY.
- No preamble, no "certainly", no "I'd be happy to".
- Start with the answer.
- Use simple language.
- Output only the answer.""",

    AgentType.WEB_SEARCHER: """You are a web research specialist. SEARCH and SYNTHESIZE information directly.
- Use the web_search tool to find current information.
- Summarize findings concisely.
- Include source URLs when available.
- MAX 300 words. Be focused and actionable.""",
}

# Web search tool definition for agents that need it
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information on any topic",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                }
            },
            "required": ["query"],
        },
    },
}

MODEL_PREFERENCES: Dict[AgentType, str] = {
    AgentType.CODER: "murah",
    AgentType.RESEARCHER: "murah",
    AgentType.ANALYST: "murah",
    AgentType.TRANSLATOR: "murah",
    AgentType.WRITER: "murah",
    AgentType.DEBUGGER: "murah",
    AgentType.ARCHITECT: "murah",
    AgentType.SIMPLE: "murah",
    AgentType.WEB_SEARCHER: "tavily/search",
}


def get_agent_profile(agent_type: AgentType) -> AgentProfile:
    return AgentProfile(
        agent_type=agent_type,
        system_prompt=AGENT_PROMPTS[agent_type],
        preferred_model=MODEL_PREFERENCES[agent_type],
    )


def classify_task_type(task_description: str) -> AgentType:
    lower = task_description.lower()

    if any(kw in lower for kw in ["search", "find online", "web", "latest", "current", "news"]):
        return AgentType.WEB_SEARCHER
    if any(kw in lower for kw in ["debug", "error", "fix", "bug", "issue", "crash"]):
        return AgentType.DEBUGGER
    if any(kw in lower for kw in ["sql", "query", "database", "schema"]):
        return AgentType.ANALYST
    if any(kw in lower for kw in ["research", "find", "investigate"]):
        return AgentType.RESEARCHER
    if any(kw in lower for kw in ["code", "function", "class", "implement", "write", "program", "create", "endpoint"]):
        return AgentType.CODER
    if any(kw in lower for kw in ["architect", "design", "system", "scale", "structure"]):
        return AgentType.ARCHITECT
    if any(kw in lower for kw in ["analyze", "analysis", "data", "insight"]):
        return AgentType.ANALYST
    if any(kw in lower for kw in ["translate", "translation", "language"]):
        return AgentType.TRANSLATOR
    if any(kw in lower for kw in ["write", "draft", "content", "blog", "article", "document"]):
        return AgentType.WRITER
    if any(kw in lower for kw in ["explain", "what is", "how to", "define"]):
        return AgentType.SIMPLE

    return AgentType.SIMPLE
