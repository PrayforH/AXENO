# Markdown Typography Design

## Context

CopilotKit v2 renders assistant Markdown through Streamdown. Its generated headings,
paragraphs, lists, quotes, and fenced code use the library's default spacing scale,
while the harness activity, tool, JSON, and code surfaces use a separate compact
scale. A live browser inspection showed a 24px heading with 48px top spacing beside
11px structured content, making a single assistant turn feel visually fragmented.

## Decision

Keep CopilotKit and Streamdown as the rendering pipeline. Add a scoped typography
layer below `.chat-surface [data-copilotkit]` that targets Streamdown's stable
`data-streamdown` attributes and its direct semantic children. This avoids replacing
the renderer, keeps streaming and syntax highlighting intact, and prevents the rules
from leaking into tool cards or the run inspector.

The reading scale will use:

- Body: 15px with 1.65 line height.
- Paragraph rhythm: 10px between adjacent blocks.
- H2: 19px with 1.4 line height and 22px/8px vertical rhythm.
- H3: 17px with 1.45 line height and 18px/7px vertical rhythm.
- Lists: outside markers, 20px indentation, 4px item separation.
- Quotes: one moss rule, 12px inset, no nested paragraph margins.
- Inline code: 0.9em utility type with a quiet graphite surface.
- Fenced code: 13px with 1.6 line height and restrained 12px block margins.

The existing Paper, Graphite, Moss, Amber, and Code Slate palette remains unchanged.
The execution spine continues to be the interface's visual signature; typography is
deliberately quieter so it supports rather than competes with run activity.

## Testing

Add a source-level typography contract test that reads `styles.css` and asserts the
scoped selectors and key tokens. Then validate in a real browser using a Markdown
fixture containing a heading, two paragraphs, a list, a quote, inline code, and a
fenced code block. Check computed styles rather than relying on screenshots alone.

