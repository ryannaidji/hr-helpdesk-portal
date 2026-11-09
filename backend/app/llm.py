"""Minimal Ollama client (local, free). No paid API is used anywhere in this project."""
import json

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, embed_model: str, timeout: float = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.http = httpx.Client(timeout=timeout)

    def chat(self, system: str, user: str, schema: dict | None = None) -> str:
        payload: dict = {
            "model": self.model, "stream": False, "options": {"temperature": 0, "seed": 7, "num_predict": 300},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if schema:
            payload["format"] = schema
        response = self.http.post(f"{self.base_url}/api/chat", json=payload)
        response.raise_for_status()
        return response.json()["message"]["content"]

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        return json.loads(self.chat(system, user, schema))

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.http.post(f"{self.base_url}/api/embed", json={"model": self.embed_model, "input": texts})
        response.raise_for_status()
        return response.json()["embeddings"]
