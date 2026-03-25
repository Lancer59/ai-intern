import os
from typing import Optional, Union
from dotenv import load_dotenv

# Import LangChain chat models
from langchain_openai import ChatOpenAI, AzureChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama

# Load environment variables from .env file
load_dotenv()

def get_llm(
    provider: str,
    model_name: Optional[str] = None,
    temperature: float = 0.7,
    **kwargs
) -> Union[ChatOpenAI, AzureChatOpenAI, ChatGoogleGenerativeAI, ChatOllama]:
    """
    Factory function to initialize and return a LangChain LLM object.
    
    Args:
        provider (str): One of 'openai', 'azure', 'google', 'ollama'.
        model_name (str, optional): The specific model to use. Defaults to provider-specific defaults.
        temperature (float): Sampling temperature. Defaults to 0.7.
        **kwargs: Additional parameters passed to the model constructor.
        
    Returns:
        A LangChain chat model object.
    """
    provider = provider.lower()

    if provider == "openai":
        return ChatOpenAI(
            model=model_name or "gpt-4o",
            temperature=temperature,
            api_key=os.getenv("OPENAI_API_KEY"),
            **kwargs
        )

    elif provider == "azure":
        return AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),
            openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            temperature=temperature,
            **kwargs
        )

    elif provider == "google":
        return ChatGoogleGenerativeAI(
            model=model_name or "gemini-1.5-pro",
            temperature=temperature,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            **kwargs
        )

    elif provider == "ollama":
        # Specifically for local models like llama3, qwen2, etc.
        return ChatOllama(
            model=model_name or "llama3",
            temperature=temperature,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            **kwargs
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}. Choose from 'openai', 'azure', 'google', 'ollama'.")

if __name__ == "__main__":
    # Quick internal check (won't run if API keys are missing, unless mocked)
    print("LLM Factory initialized. Use get_llm(provider='...') to get an LLM object.")
