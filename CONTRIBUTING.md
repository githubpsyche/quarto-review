# Contributing

Keep changes focused on a document behaviour that can be demonstrated with a
small example. Preserve original inputs and review identities. If a Word
construct cannot be represented, report its location and retain the source
record so the author can decide how to handle it.

Use descriptive names, type annotations, and short modules with a clear purpose.
Put validation at file and command boundaries. Explain public functions through
their inputs, results, and meaningful failure cases. Avoid wrappers that merely
rename another operation or catch errors without adding useful context.

Write documentation for readers who have not seen the development conversation.
Introduce a term when it becomes necessary, explain what a command changes, and
distinguish tested behaviour from intended behaviour. Use connected paragraphs
and concrete examples. Avoid slogans, unnecessary compounds, and em dashes.

Add tests for changes to parsing, anchoring, attribution, or export. Compare
document content and thread relationships rather than relying on element counts
alone. Keep personal names and unpublished manuscripts out of shared fixtures.
