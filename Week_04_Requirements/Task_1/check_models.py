"""Minimal structured-output test call to every model configured in network/config.py.

Usage: python check_models.py [extra-model ...]
"""
import os
import sys

from dotenv import load_dotenv
from pydantic import BaseModel

from network import config
from network.llm import structured_call


class Ping(BaseModel):
    answer: str
    number: int


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set (put it into .env).")
    models = sorted(set(config.MODELS.values()) | set(sys.argv[1:]))
    for model in models:
        parsed, rec = structured_call("check", Ping, "Reply in JSON.",
                                      "Say 'pong' and give the number 7.", model=model)
        status = f"OK  {parsed}" if parsed else f"FAIL {rec.get('error')}"
        print(f"{model:16s} {rec['seconds']:6.1f}s  in={rec['input_tokens']} "
              f"out={rec['output_tokens']}  {status}")


if __name__ == "__main__":
    main()
