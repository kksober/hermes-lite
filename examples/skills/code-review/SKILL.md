---
name: Code Review
description: Systematic code review checklist covering correctness, security, performance, and style
version: 1.0.0
---

# Code Review Skill

This skill provides a systematic approach to reviewing code for quality,
security, and correctness. Use it as a checklist when examining pull
requests or auditing codebases.

## Review Checklist

### Correctness
- [ ] Does the code do what it claims to do?
- [ ] Are edge cases handled properly (empty input, null/None, large values)?
- [ ] Are error conditions handled gracefully?
- [ ] Are there any off-by-one errors or boundary issues?
- [ ] Is the control flow correct and easy to follow?

### Security
- [ ] Is user input validated and sanitized?
- [ ] Are there any SQL injection or XSS vulnerabilities?
- [ ] Are secrets, tokens, or API keys hardcoded?
- [ ] Are file paths properly validated to prevent path traversal?
- [ ] Are permissions and authorization checks in place?

### Performance
- [ ] Are there any N+1 query problems?
- [ ] Is data being loaded or processed unnecessarily?
- [ ] Are expensive operations cached where appropriate?
- [ ] Are there memory leaks (unclosed resources, circular references)?
- [ ] Is the algorithmic complexity acceptable for expected input sizes?

### Style & Maintainability
- [ ] Are naming conventions followed consistently?
- [ ] Are functions small, focused, and single-purpose?
- [ ] Is there adequate documentation for non-obvious logic?
- [ ] Are type hints used where appropriate?
- [ ] Is dead code or commented-out code removed?

### Testing
- [ ] Are there tests covering the new or modified code?
- [ ] Do edge cases have test coverage?
- [ ] Would the existing tests catch regressions?
- [ ] Are test names descriptive of what is being tested?

## Workflow

1. **Read** the code files using `read_file` to understand the changes.
2. **Run** existing tests with `run_shell` to check for regressions.
3. **Analyze** the logic, data flow, and error handling systematically.
4. **Search** for patterns (e.g., `run_shell("grep -r 'TODO' .")`).
5. **Report** findings with specific file paths and line numbers.
