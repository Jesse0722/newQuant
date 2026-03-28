"""LLM 调用统一封装：支持 OpenAI 兼容、通义千问、Ollama。"""
import os


def _call_openai(prompt: str, temperature: float = 0.3) -> str:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key and not base_url:
        raise RuntimeError("未配置 AI：请设置 OPENAI_API_KEY 或使用 Ollama 配置 OLLAMA_BASE_URL")

    client = OpenAI(api_key=api_key or "ollama", base_url=base_url)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    resp = client.chat.completions.create(
        model=model,
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


def call_llm(prompt: str, provider: str | None = None, temperature: float = 0.3) -> str:
    """按 provider 路由调用 LLM，provider 不传则读取 AI_PROVIDER。"""
    selected = (provider or os.getenv("AI_PROVIDER", "openai")).lower()
    if selected == "ollama":
        return _call_ollama(prompt, temperature=temperature)
    if selected == "qwen":
        return _call_qwen(prompt, temperature=temperature)
    return _call_openai(prompt, temperature=temperature)
