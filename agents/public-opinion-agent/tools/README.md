# Public-opinion tools

The initial version intentionally uses only Harness builtins, the reviewed
`tavily-readonly` MCP registration and `helper-agent`. Platform-specific collectors,
social APIs or internal case systems must be added as server-owned logical MCP
registrations with tenant-scoped credentials and explicit allowlists.

Do not put API keys, cookies, raw authenticated URLs or personal-data exports in this
directory.
