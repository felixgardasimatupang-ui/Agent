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
    AgentType.CODER: """Expert programmer. Output COMPLETE WORKING CODE only.
- NO explanations, NO questions, NO preamble.
- Include imports, error handling, type hints.
- Follow language/framework best practices.
- Keep code focused: 50-150 lines max unless asked otherwise.""",

    AgentType.RESEARCHER: """Technical researcher. Output CONCISE findings only.
- MAX 150 words. Be brief, focused, actionable.
- Use bullet points. Include code examples when relevant.
- No preamble. Start with the answer.""",

    AgentType.ANALYST: """Data analyst. Output DATA-DRIVEN insights only.
- MAX 150 words. Use tables and bullet points.
- Quantify where possible. No preamble.""",

    AgentType.TRANSLATOR: """Expert translator. Output translation DIRECTLY.
- Preserve tone and style. Handle technical terms accurately.
- Output only the translated text. Nothing else.""",

    AgentType.WRITER: """Skilled writer. Output content DIRECTLY.
- Clear headers, active voice, concise.
- MAX 300 words. Output only the content.""",

    AgentType.DEBUGGER: """Debugging specialist. FIND AND FIX issues directly.
- Output fixed code with bug explanation in comment.
- Consider edge cases. Include the solution.""",

    AgentType.ARCHITECT: """Software architect. DESIGN system directly.
- Output architecture with component diagrams.
- Specify file structure and key interfaces.
- Keep design focused: 200 words max.""",

    AgentType.SIMPLE: """Helpful assistant. Answer DIRECTLY and CONCISELY.
- No preamble. Start with the answer.
- Use simple language. Output only the answer.""",

    AgentType.WEB_SEARCHER: """Web research specialist. SEARCH and SYNTHESIZE directly.
- Use web_search tool. Summarize concisely.
- Include source URLs. MAX 200 words.""",
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
    AgentType.CODER: "power",
    AgentType.RESEARCHER: "power",
    AgentType.ANALYST: "power",
    AgentType.TRANSLATOR: "power",
    AgentType.WRITER: "power",
    AgentType.DEBUGGER: "power",
    AgentType.ARCHITECT: "power",
    AgentType.SIMPLE: "murah",
    AgentType.WEB_SEARCHER: "tavily/search",
}


def get_agent_profile(agent_type: AgentType) -> AgentProfile:
    # Optimized for 30s timeout: max_tokens tuned to complete within time
    settings = {
        AgentType.CODER:      {"max_tokens": 2048, "temperature": 0.2},   # focused code, ~15-20s
        AgentType.DEBUGGER:   {"max_tokens": 2048, "temperature": 0.1},   # precise fixes, ~15-20s
        AgentType.ARCHITECT:  {"max_tokens": 1536, "temperature": 0.4},   # concise design, ~12-15s
        AgentType.RESEARCHER: {"max_tokens": 1024, "temperature": 0.5},   # brief findings, ~8-12s
        AgentType.ANALYST:    {"max_tokens": 1024, "temperature": 0.3},   # concise analysis, ~8-12s
        AgentType.WRITER:     {"max_tokens": 1536, "temperature": 0.7},   # focused writing, ~12-15s
        AgentType.TRANSLATOR: {"max_tokens": 1024, "temperature": 0.3},   # accurate translation, ~8-12s
        AgentType.SIMPLE:     {"max_tokens": 512,  "temperature": 0.5},   # quick answer, ~5-8s
        AgentType.WEB_SEARCHER: {"max_tokens": 1024, "temperature": 0.3}, # focused results, ~8-12s
    }
    s = settings.get(agent_type, {"max_tokens": 1024, "temperature": 0.5})
    return AgentProfile(
        agent_type=agent_type,
        system_prompt=AGENT_PROMPTS[agent_type],
        preferred_model=MODEL_PREFERENCES[agent_type],
        max_tokens=s["max_tokens"],
        temperature=s["temperature"],
    )


def classify_task_type(task_description: str) -> AgentType:
    lower = task_description.lower()

    if any(kw in lower for kw in ["research", "find", "investigate"]):
        return AgentType.RESEARCHER
    if any(kw in lower for kw in ["search online", "web search", "find online", "web", "latest", "current", "news"]):
        return AgentType.WEB_SEARCHER
    if any(kw in lower for kw in ["debug", "error", "fix", "bug", "issue", "crash"]):
        return AgentType.DEBUGGER
    if any(kw in lower for kw in ["sql", "query", "database", "schema"]):
        return AgentType.ANALYST
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
