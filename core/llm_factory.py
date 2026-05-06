import os
from typing import Optional, Union, Any
from dotenv import load_dotenv

# Import LangChain chat models
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage

# Load environment variables from .env file
load_dotenv()


class PromptDebugCallback(BaseCallbackHandler):
    """Prints the full prompt to stdout before every LLM call.

    Enable by setting DEBUG_PRINT_PROMPT=true in .env.
    Useful for identifying token waste in the system prompt or message history.
    """

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        sep = "=" * 80
        print(f"\n{sep}")
        print("DEBUG PROMPT — full message list sent to LLM")
        print(sep)
        total_chars = 0
        for batch in messages:
            for msg in batch:
                role = getattr(msg, "type", type(msg).__name__)
                content = msg.content

                # Handle list-of-blocks content (deepagents injects multiple text blocks)
                if isinstance(content, list):
                    block_chars = sum(len(b.get("text", "") if isinstance(b, dict) else str(b)) for b in content)
                    total_chars += block_chars
                    print(f"\n[{role.upper()}] ({block_chars:,} chars across {len(content)} block(s))")
                    for i, block in enumerate(content):
                        text = block.get("text", str(block)) if isinstance(block, dict) else str(block)
                        print(f"  ── block {i+1} ({len(text):,} chars) ──")
                        print(f"  {text[:300]}{'...' if len(text) > 300 else ''}")
                else:
                    text = str(content)
                    total_chars += len(text)
                    print(f"\n[{role.upper()}] ({len(text):,} chars)")
                    print(f"  {text[:300]}{'...' if len(text) > 300 else ''}")

        # Tool schemas are passed separately in kwargs — not in messages
        tools = kwargs.get("invocation_params", {}).get("tools", []) or kwargs.get("tools", [])
        tool_count = len(tools)
        tool_chars = sum(len(str(t)) for t in tools)

        print(f"\n{sep}")
        print(f"MESSAGES  — chars: {total_chars:,}  |  est. tokens: ~{total_chars // 4:,}")
        if tool_count:
            print(f"TOOLS     — {tool_count} tool schemas  |  chars: {tool_chars:,}  |  est. tokens: ~{tool_chars // 4:,}")
            print(f"TOTAL EST — ~{(total_chars + tool_chars) // 4:,} tokens  (messages + tools)")
        else:
            print(f"TOOLS     — not visible at callback level (counted separately by the API)")
            print(f"NOTE: dashboard token count = messages + tool schemas. Tool schemas add ~200 tokens/tool.")
            print(f"      With {20}+ tools registered, expect ~4,000-6,000 extra tokens per call vs this estimate.")
        print(f"{sep}\n")

def get_llm(
    provider: str,
    model_name: Optional[str] = None,
    temperature: float = 1,
    use_responses_api: bool = False,
    **kwargs
) -> Union[ChatOpenAI, AzureChatOpenAI, ChatGoogleGenerativeAI, ChatOllama]:
    """
    Factory function to initialize and return a LangChain LLM object.

    Args:
        provider (str): One of 'openai', 'azure', 'google', 'ollama'.
        model_name (str, optional): The specific model to use. Defaults to provider-specific defaults.
        temperature (float): Sampling temperature. Defaults to 1.
        use_responses_api (bool): OpenAI/Azure only. Set True for models that require the
            Responses API instead of Chat Completions (e.g. codex-mini, o3, o4-mini with
            extended thinking). Ignored for other providers.
        **kwargs: Additional parameters passed to the model constructor.

    Returns:
        A LangChain chat model object.
    """
    provider = provider.lower()

    # Attach the debug callback when DEBUG_PRINT_PROMPT=true
    debug_callbacks = [PromptDebugCallback()] if os.getenv("DEBUG_PRINT_PROMPT", "").lower() == "true" else []

    if provider == "openai":
        extra = {"use_responses_api": True} if use_responses_api else {}
        return ChatOpenAI(
            model=model_name or "gpt-4o",
            temperature=temperature,
            api_key=os.getenv("OPENAI_API_KEY"),
            callbacks=debug_callbacks or None,
            **extra,
            **kwargs,
        )

    elif provider == "azure":
        extra = {"use_responses_api": True} if use_responses_api else {}
        return AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
            openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            temperature=temperature,
            callbacks=debug_callbacks or None,
            **extra,
            **kwargs,
        )

    elif provider == "google":
        return ChatGoogleGenerativeAI(
            model=model_name or "gemini-1.5-pro",
            temperature=temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            callbacks=debug_callbacks or None,
            **kwargs,
        )

    elif provider == "ollama":
        return ChatOllama(
            model=model_name or "llama3",
            temperature=temperature,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            callbacks=debug_callbacks or None,
            **kwargs,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}. Choose from 'openai', 'azure', 'google', 'ollama'.")

if __name__ == "__main__":
    # Quick internal check (won't run if API keys are missing, unless mocked)
    print("LLM Factory initialized. Use get_llm(provider='...') to get an LLM object.")
