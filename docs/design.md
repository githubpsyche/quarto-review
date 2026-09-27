# Review a manuscript from one authoritative source

The working QMD owns prose, explicit wording suggestions and complete discussions.
A frozen QMD owns the starting state for the current review round.
Both documents are self-contained with respect to review state.
Quarto configuration, bibliographies and immutable source assets remain ordinary manuscript dependencies.

## Source ownership

The source module reads compact spans, overlapping range markers, attributed CriticMarkup and Markdown thread divs.
It preserves source offsets for precise changes.
A Source object owns the syntax tree, resolved review records and locations needed for editing.
Metadata structures passed to comparison and output conversion are derived in-memory views, not independently maintained files.

Definitions may occur before or after their ranges.
The reader gathers thread definitions before resolving references.
It checks identities, attribution, decisions, parent relationships and ranges at the document boundary.

Commands make validated edits to the same source model.
They do not independently reconstruct an annotation in the HTML or Word layers.
Saving checks that the source has not changed since it was read, then replaces the file atomically.
Source edits retain unrelated prose and formatting.

## Comparison and output

Comparison projects manuscript content out of the review model.
Thread bodies and replies never become manuscript revisions.
Explicit suggestion decisions affect both the current and reference projections, avoiding duplicate author edits when a reviewer insertion is rejected.
Deleted threads are determined by the current source and are not revived from the reference.

Quarto prepares the common review model for its selected output format.
The existing native Word converter writes comments, replies, identities and tracked revisions.
HTML uses the same resolved discussions and ranges.
Rendering does not rewrite source or advance the reference.
The schema-1 adapter remains available for existing projects.

## Conversion and returned review

Conversion reads the current legacy source and its own frozen reference independently.
It verifies manuscript metadata, wording, range locations and text, suggestions, discussion records, attribution, dispositions and native descriptors.
Input fingerprints detect concurrent changes.
Publication creates a new candidate directory; it never replaces the source project.

Returned Word files can similarly become explicit candidates.
The author selects the relevant prior version for reconciliation.
A mandatory per-export journal and automatic merging of divergent review histories are outside the schema-2 core.

## Runtime isolation

Development uses a separate environment and synthetic fixtures.
An active manuscript can remain on a preserved package and dependency copy while the development checkout changes.
The pinned manuscript's source, reference, presentation and outputs remain owned by its editing chat.
A future switch requires fresh candidates, an agreed editing pause, validation and rollback material.
See development-isolation.md for the operational boundary.
