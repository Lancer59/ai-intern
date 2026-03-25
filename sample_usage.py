from llm_factory import get_llm

def main():
    print("--- LLM Initialization Examples ---")

    # 1. OpenAI
    try:
        openai_llm = get_llm(provider="openai", model_name="gpt-4o")
        print(f"Initialized OpenAI: {openai_llm.model_name}")
    except Exception as e:
        print(f"OpenAI Init failed (likely missing key): {e}")

    # 2. Google Gemini
    try:
        google_llm = get_llm(provider="google", model_name="gemini-1.5-flash")
        print(f"Initialized Google: {google_llm.model}")
    except Exception as e:
        print(f"Google Init failed (likely missing key): {e}")

    # 3. Ollama (Local)
    try:
        # User mentioned 'lamma' and 'quen2b'
        llama_llm = get_llm(provider="ollama", model_name="llama3")
        qwen_llm = get_llm(provider="ollama", model_name="qwen2:7b") # Example for 'quen2b'
        ans = qwen_llm.invoke("hi")
        print(ans)
        print(f"Initialized Ollama (Llama): {llama_llm.model}")
        print(f"Initialized Ollama (Qwen): {qwen_llm.model}")
    except Exception as e:
        print(f"Ollama Init failed: {e}")

    # 4. Azure OpenAI
    try:
        azure_llm = get_llm(provider="azure")
        print("Initialized Azure OpenAI")
    except Exception as e:
        print(f"Azure Init failed: {e}")

if __name__ == "__main__":
    main()
