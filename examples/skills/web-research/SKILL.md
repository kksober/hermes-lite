---
name: Web Research
description: Search the web and fetch page content for research tasks
version: 1.0.0
---

# Web Research Skill

This skill enables web-based research by fetching and analyzing web page
content. It is useful for gathering information, fact-checking, and
staying up-to-date on topics.

## Capabilities

- **Fetch pages**: Use `web_fetch` to retrieve the text content of any URL.
- **Search**: Use `run_shell` with curl or other CLI tools to query search
  engines or APIs.
- **Analyze**: Extract key information from multiple sources.

## Workflow

1. **Plan**: Determine which URLs or search queries are needed.
2. **Fetch**: Use `web_fetch` to retrieve page content from each URL.
3. **Analyze**: Read through the fetched content and extract key facts,
   data points, or quotes.
4. **Cross-reference**: Verify important claims across multiple sources.
5. **Synthesize**: Combine findings into a coherent, well-cited response.

## Best Practices

- Verify information across multiple independent sources.
- Respect robots.txt and website terms of service.
- Always cite sources when presenting research findings.
- Handle errors gracefully — websites may be temporarily unavailable.
- Be mindful of rate limits when fetching multiple pages.
- Prefer official or authoritative sources over user-generated content.
