#!/usr/bin/env python3
"""
Token-Saving CLI Wrapper for OpenCode
Routes requests through9Router to save tokens using smart model selection.
"""
import asyncio
import sys
import os
from openai import AsyncOpenAI
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    ROUTER_BASE_URL, 
    ROUTER_API_KEY, 
    MODEL_SIMPLE, 
    MODEL_COMPLEX, 
    MODEL_COORDINATOR
)

console = Console()

class TokenSaverCLI:
    def __init__(self):
        # Use dummy key if no key provided (9Router may not require auth)
        api_key = ROUTER_API_KEY if ROUTER_API_KEY else "sk-dummy"
        self.client = AsyncOpenAI(base_url=ROUTER_BASE_URL, api_key=api_key)
        self.conversation_history = []
        
    def classify_request(self, user_input: str) -> str:
        """Classify request to pick cheapest adequate model."""
        lower = user_input.lower()
        
        # Complex requests - need strong model
        complex_keywords = ["debug", "error", "complex", "architect", "refactor", 
                           "optimize", "performance", "security", "critical"]
        if any(kw in lower for kw in complex_keywords):
            return MODEL_COMPLEX
        
        # Planning/reasoning requests
        planning_keywords = ["plan", "design", "strategy", "approach", "evaluate"]
        if any(kw in lower for kw in planning_keywords):
            return MODEL_COORDINATOR
        
        # Default to cheap model
        return MODEL_SIMPLE
    
    async def chat(self, user_input: str, use_history: bool = True):
        """Send chat request through9Router with smart model selection."""
        model = self.classify_request(user_input)
        
        console.print(f"[dim]Using model: {model}[/dim]")
        
        messages = []
        if use_history:
            messages.extend(self.conversation_history)
        messages.append({"role": "user", "content": user_input})
        
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
            )
            result = response.choices[0].message.content
            
            # Track token usage
            if response.usage:
                console.print(f"[dim]Tokens: {response.usage.prompt_tokens} prompt + {response.usage.completion_tokens} completion = {response.usage.total_tokens} total[/dim]")
            
            # Update history
            if use_history:
                self.conversation_history.append({"role": "user", "content": user_input})
                self.conversation_history.append({"role": "assistant", "content": result})
                # Keep history manageable
                if len(self.conversation_history) > 20:
                    self.conversation_history = self.conversation_history[-20:]
            
            return result
            
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
            return None
    
    async def execute_code(self, code: str, language: str = "python"):
        """Execute code through AI (explanation + execution plan)."""
        prompt = f"""Analyze and explain this {language} code. Provide:
1. What it does
2. Any issues or improvements
3. Expected output if run

Code:
```{language}
{code}
```"""
        return await self.chat(prompt, use_history=False)
    
    def clear_history(self):
        self.conversation_history = []
        console.print("[dim]Conversation history cleared.[/dim]")


async def interactive_mode():
    """Run interactive CLI mode."""
    saver = TokenSaverCLI()
    
    console.print(Panel.fit(
        "[bold cyan]Token-Saving CLI via9Router[/bold cyan]\n"
        "Smart model routing untuk hemat token.\n\n"
        "Commands:\n"
        "  /code <language> - Execute/analyze code\n"
        "  /clear - Clear history\n"
        "  /models - Show available models\n"
        "  /quit - Exit"
    ))
    
    while True:
        try:
            user_input = console.input("\n[bold green]> [/bold green]")
            
            if not user_input.strip():
                continue
            
            if user_input.lower() == "/quit":
                break
            
            if user_input.lower() == "/clear":
                saver.clear_history()
                continue
            
            if user_input.lower() == "/models":
                console.print("[dim]Models: murah (cheap), power (strong), plan (reasoning)[/dim]")
                continue
            
            if user_input.startswith("/code "):
                code = user_input[6:]
                result = await saver.execute_code(code)
                if result:
                    console.print(Markdown(result))
                continue
            
            result = await saver.chat(user_input)
            if result:
                console.print(Markdown(result))
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    
    console.print("[dim]Goodbye![/dim]")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Single command mode
        saver = TokenSaverCLI()
        prompt = " ".join(sys.argv[1:])
        asyncio.run(saver.chat(prompt, use_history=False))
    else:
        asyncio.run(interactive_mode())
