# Linear

Tools come from the official Linear plugin (`linear@claude-plugins-official`).
Without them, tarahi drafts locally and says publishing needs that plugin. It
skips step 6 and the Linear writes in step 7.

## Read

| Need | Tool |
|---|---|
| Project, milestones | `get_project` (`includeMilestones`) |
| Issues | `list_issues` (`project`) |
| Existing shaping docs | `list_documents` (`projectId`), then `get_document` |
| Comment threads on a version | `list_comments` (`documentId`) |
| Author for the header | `get_user` (`me`) |

Page through every comment (`cursor` while `hasNextPage`). Group replies
under their root (`parentId: null`); a thread's later replies often settle it
already, so answer the thread's final position, not its first comment. Read
inline comments (`quotedText` set) too and quote the anchored text in
Appendix A. Comments may be in any language; Appendix A gives their gist in
the doc's language.

## Publish

- **Title:** `<Project> — Shaping vN` for a new doc. A revision keeps the
  matched doc's title and changes only the suffix, to the highest existing
  version of that doc plus one (an unnumbered title counts as v1).
- **Create** with `save_document`: `title`, `project`, `content`. A version is
  always a new document; never update an earlier one.
- **Supersedes** in the header links the previous version's URL.
- Keep markdown plain: simple tables (no merged cells, no HTML), images as
  links unless the user uploads them. Never copy Linear's own tags
  (`<linear-image>`, `<pull-request>`) from a previous version; link the URL.

## After publishing (each on its own yes)

- **Replies:** `save_comment` with `parentId` set to each thread's root on the
  previous version: one line pointing to vN and, when it changed, the row in
  Appendix A. Never resolve or delete threads.
- **ADR links:** `save_document` with the id of the document just published
  and a `patch` that adds the links to Appendix B, or appends `## Appendix B` with
  them when the doc has none (empty sections are left out). This is the one edit a
  published version gets, and only for the version just published.
- **Issues:** `save_issue` with the project's team and `project`; title from
  the `Missing:` item or the Open decision; assignee only when the doc names
  an owner. Link the doc in the description.
