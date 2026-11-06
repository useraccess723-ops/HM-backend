import os
from typing import Any
from dotenv import load_dotenv

load_dotenv()

try:
    from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore # pyrefly: ignore[missing-import]
    from langchain_core.messages import SystemMessage, HumanMessage  # type: ignore # pyrefly: ignore[missing-import]
except ImportError:
    class _FallbackCallable:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass
        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self
        def invoke(self, *args: Any, **kwargs: Any) -> Any:
            return ""

    ChatGoogleGenerativeAI: Any = _FallbackCallable
    SystemMessage: Any = _FallbackCallable
    HumanMessage: Any = _FallbackCallable

api_key = os.getenv("GEMINI_API_KEY")
model_name = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


def extract_response_text(response: Any) -> str:
    """Safely extracts text content from an LLM response (AIMessage, str, or dict).
    
    Handles:
    - Direct string: `response.content == "text"`
    - List of strings: `["text part 1", "text part 2"]`
    - List of block dicts: `[{"type": "text", "text": "..."}]`
    - Objects with .text attribute
    - Empty or None responses
    """
    if response is None:
        return ""
    raw = getattr(response, "content", response)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                val = item.get("text") or item.get("content") or ""
                parts.append(str(val))
            elif hasattr(item, "text") and isinstance(item.text, str):
                parts.append(item.text)
            elif item is not None:
                parts.append(str(item))
        return "".join(parts).strip()
    if hasattr(raw, "text") and isinstance(raw.text, str):
        return raw.text
    return str(raw).strip() if raw is not None else ""


def run_gemini_test():
    print(f"Initializing ChatGoogleGenerativeAI with model={model_name}...")
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=0.1
    )

    context = """
StayFlow Hotel Knowledge Base:
1. Hotel Services:
The hotel provides accommodation, room amenities, hotel facilities, and additional guest services.
Complimentary buffet breakfast is served from 07:00 AM to 10:30 AM at the Orchid Terrace.
24-Hour In-Room Dining is available by dialing extension 9 from your room telephone.
The heated rooftop infinity swimming pool is open daily from 06:00 AM to 10:00 PM.
Complimentary bathrobes, fresh towels, and sun loungers are provided at poolside.
High-speed fiber optical Wi-Fi 'StayFlow_Guest' is complimentary throughout all rooms.
"""

    q = "What are the services available?"

    messages = [
        SystemMessage(content=(
            "You are the StayFlow Hotel AI Knowledge Assistant. "
            "Ground your answer STRICTLY and ONLY in the provided hotel knowledge documents. "
            "Answer the guest's question directly, courteously, clearly, and concisely. "
            "Never invent hotel information, amenities, room availability, prices, policies, or confirmation status. "
            "Never include raw citations, source brackets like '[Source 1]', chunk IDs, or dialogue script labels ('Customer:', 'Agent:'). "
            "If the provided context does NOT contain enough information to answer the question, respond EXACTLY with: "
            "'I’m sorry, I can’t confirm that information from the hotel's approved knowledge documents at the moment. I can arrange for the hotel team to verify it for you.'"
        )),
        HumanMessage(content=f"Verified Hotel Knowledge Documents:\n{context}\n\nGuest Question:\n{q}\n\nAnswer:")
    ]

    resp = llm.invoke(messages)
    content = extract_response_text(resp)
    print("\n[SUCCESS] Model used:", model_name)
    print("Generated Grounded Response:\n", content)
    return content


if __name__ == "__main__":
    run_gemini_test()
