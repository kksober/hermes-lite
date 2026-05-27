---
name: Filesystem
description: Read, write, and search files on the local filesystem
version: 1.0.0
---

# Filesystem Skill

This skill enables file operations on the local filesystem using the
built-in file and terminal tools.

## Capabilities

- **Read files**: Use `read_file` to read file contents with line numbers.
- **Write files**: Use `write_file` to create or overwrite files.
- **Search files**: Use `run_shell` with grep, find, or similar commands.
- **List directories**: Use `run_shell("ls -la <path>")` to explore.

## Workflow

1. **Explore**: List directory contents with `run_shell("ls -la /path")`.
2. **Read**: Open files with `read_file` to inspect contents.
3. **Search**: Use `run_shell("grep -r 'pattern' /path")` for content search.
4. **Write**: Create or modify files with `write_file`.

## Best Practices

- Always read a file before modifying it.
- Check that a file or directory exists before operating on it.
- Use absolute paths when possible to avoid ambiguity.
- Be careful with write operations — they silently overwrite existing files.
- For large files, use `run_shell` with `head`/`tail` instead of `read_file`.
