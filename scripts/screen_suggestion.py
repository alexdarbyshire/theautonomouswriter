"""Screen a suggestion via Llama Guard. Exit 0 if safe, 1 if unsafe."""
import sys

from agent.llm import OpenRouterClient


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: screen_suggestion.py <text>", file=sys.stderr)
        sys.exit(2)

    text = sys.argv[1]
    llm = OpenRouterClient()
    is_safe, reason, _usage = llm.check_safety(text)

    if is_safe:
        print("safe")
        sys.exit(0)
    else:
        print(f"unsafe: {reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
