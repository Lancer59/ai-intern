"""Tests for core/llm_factory.py"""
import pytest
from unittest.mock import patch


class TestGetLlm:
    def test_unsupported_provider_raises(self):
        from core.llm_factory import get_llm
        with pytest.raises(ValueError, match="Unsupported provider"):
            get_llm(provider="cohere")

    def test_provider_case_insensitive(self):
        """get_llm normalises provider to lowercase — OPENAI should work same as openai."""
        from core.llm_factory import get_llm
        from langchain_openai import ChatOpenAI
        import os
        os.environ.setdefault("OPENAI_API_KEY", "sk-test")
        llm = get_llm(provider="OPENAI")
        assert isinstance(llm, ChatOpenAI)

    @patch.dict("os.environ", {
        "OPENAI_API_KEY": "sk-test",
    })
    def test_openai_returns_chat_openai(self):
        from core.llm_factory import get_llm
        from langchain_openai import ChatOpenAI
        llm = get_llm(provider="openai", model_name="gpt-4o-mini")
        assert isinstance(llm, ChatOpenAI)

    @patch.dict("os.environ", {
        "AZURE_OPENAI_API_KEY": "test-key",
        "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
        "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4o",
        "AZURE_OPENAI_API_VERSION": "2024-02-01",
    })
    def test_azure_returns_azure_chat_openai(self):
        from core.llm_factory import get_llm
        from langchain_openai import AzureChatOpenAI
        llm = get_llm(provider="azure")
        assert isinstance(llm, AzureChatOpenAI)

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"})
    def test_google_returns_google_genai(self):
        from core.llm_factory import get_llm
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = get_llm(provider="google")
        assert isinstance(llm, ChatGoogleGenerativeAI)

    def test_ollama_returns_chat_ollama(self):
        from core.llm_factory import get_llm
        from langchain_ollama import ChatOllama
        llm = get_llm(provider="ollama", model_name="llama3")
        assert isinstance(llm, ChatOllama)

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"})
    def test_temperature_passed_through(self):
        from core.llm_factory import get_llm
        llm = get_llm(provider="openai", temperature=0.0)
        assert llm.temperature == 0.0
