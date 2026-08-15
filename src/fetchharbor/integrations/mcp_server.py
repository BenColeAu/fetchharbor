"""Optional MCP adapter placeholder.

This module intentionally remains separate from service implementations. Install the
`mcp` extra and map registry services to MCP tools when enabling the Compose profile.
"""


def main() -> None:
    raise SystemExit("MCP profile is scaffolded but not enabled in the 0.1 release")


if __name__ == "__main__":
    main()
