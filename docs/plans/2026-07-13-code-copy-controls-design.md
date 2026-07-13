# Code Copy Controls Design

## Context

Streamdown renders a download button and a copy button in every Markdown code
header. Both controls are 22px icon-only buttons with English titles and no accessible
name. CopilotKit also renders a message-copy button below the answer, so a short code
answer presents three visually similar controls with two different copy scopes.

## Decision

Markdown code blocks expose only “复制代码”. Artifact downloads remain in the
artifact card, where a durable file and filename exist. A client-side observer adds a
Chinese accessible label to Streamdown's copy control and mirrors its copied state as
“已复制”. CSS hides the generic code download control, gives code-copy a 32px target,
and moves the whole-answer toolbar to the lower right with quieter styling.

The implementation stays in the harness UI layer and does not patch CopilotKit or
Streamdown packages. It tolerates message replay and streaming by observing newly
inserted code blocks, and it disconnects cleanly when the page unmounts.

## Testing

Unit-test the DOM enhancer with a minimal fake document, including initial setup,
copied-state synchronization, new streamed controls, and cleanup. Keep a CSS contract
for hiding download and sizing copy. Verify the final controls and computed styles in
the live browser.

