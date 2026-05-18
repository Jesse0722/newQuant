"""LLM 调用统一封装：支持 OpenAI 兼容、通义千问、Ollama。"""

from __future__ import annotations
import os


def _call_openai(prompt: str, temperature: float = 0.3, model: str | None = None) -> str:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key and not base_url:
        raise RuntimeError("未配置 AI：请设置 OPENAI_API_KEY 或使用 Ollama 配置 OLLAMA_BASE_URL")

    client = OpenAI(api_key=api_key or "ollama", base_url=base_url)
    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    resp = client.chat.completions.create(
        model=selected_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def _call_ollama(prompt: str, temperature: float = 0.3) -> str:
    from openai import OpenAI

    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    client = OpenAI(base_url=f"{base}/v1", api_key="ollama")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def _call_qwen(prompt: str, temperature: float = 0.3) -> str:
    from dashscope import Generation

    api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise RuntimeError("未配置通义千问：请设置 DASHSCOPE_API_KEY")

    model = os.getenv("DASHSCOPE_MODEL", "qwen-plus")
    resp = Generation.call(
        api_key=api_key,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        result_format="message",
        temperature=temperature,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"通义千问调用失败: {resp.message}")
    return resp.output.choices[0].message.content or ""


def _call_deepseek(prompt: str, temperature: float = 0.3, model: str | None = None) -> str:
    from openai import OpenAI

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("未配置 DeepSeek：请设置 DEEPSEEK_API_KEY")

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    client = OpenAI(api_key=api_key, base_url=f"{base_url}/v1")
    selected_model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    resp = client.chat.completions.create(
        model=selected_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def call_llm(prompt: str, provider: str | None = None, temperature: float = 0.3) -> str:
    """按 provider 路由调用 LLM，provider 不传则读取 AI_PROVIDER。"""
    selected = (provider or os.getenv("AI_PROVIDER", "openai")).lower()
    if selected == "ollama":
        return _call_ollama(prompt, temperature=temperature)
    if selected == "qwen":
        return _call_qwen(prompt, temperature=temperature)
    if selected == "deepseek":
        return _call_deepseek(prompt, temperature=temperature)
    return _call_openai(prompt, temperature=temperature)


def call_llm_model(prompt: str, provider: str, model: str, temperature: float = 0.3) -> str:
    """按指定 provider/model 调用 LLM。用于需要区分快慢模型的场景。"""
    selected = provider.lower()
    if selected == "deepseek":
        return _call_deepseek(prompt, temperature=temperature, model=model)
    if selected == "openai":
        return _call_openai(prompt, temperature=temperature, model=model)
    return call_llm(prompt, provider=provider, temperature=temperature)
