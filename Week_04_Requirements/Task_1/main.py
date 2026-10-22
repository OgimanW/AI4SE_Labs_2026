"""CLI: python main.py --input-dir <dir> [--output-dir <dir>] [--max-iterations N]"""
import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from network import config
from network.graph import build_graph


def main() -> None:
    p = argparse.ArgumentParser(description="Agentic requirements-refinement network")
    p.add_argument("--input-dir", required=True)
    p.add_argument("--output-dir", default="output")
    p.add_argument("--max-iterations", type=int, default=config.MAX_ITERATIONS)
    args = p.parse_args()
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set. Put it into .env (see .env.example).")
    if not Path(args.input_dir).is_dir():
        sys.exit(f"Input directory not found: {args.input_dir}")
    start = time.time()
    state = {"input_dir": args.input_dir, "output_dir": args.output_dir,
             "max_iterations": args.max_iterations}
    for update in build_graph().stream(state, stream_mode="updates",
                                       config={"max_concurrency": config.MAX_CONCURRENCY,
                                               "recursion_limit": 100}):
        for node, out in update.items():
            info = next((e for e in reversed((out or {}).get("log", []))
                         if e.get("type") == "node"), {})
            details = {k: v for k, v in info.items() if k not in ("type", "node", "time")}
            print(f"[{time.time() - start:6.0f}s] {node:12s} {details}", flush=True)
    print(f"Done. Output in {args.output_dir}/")


if __name__ == "__main__":
    main()
