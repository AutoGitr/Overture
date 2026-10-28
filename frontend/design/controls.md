# Controls inventory

Every option, filter, search-by, sort and button, per screen, with why it
exists. A control without a reason is removed or merged. Labels use one
vocabulary: **Replace existing** (search again over saved choices),
**Unmanaged** (collections without criteria), **Strict / Lenient / Off**
(aspect ratio), **Monitor / Unmonitor**, **Discard** (drafts), **Clear**
(selections).

## Sidebar

| Control                     | Why                                                                                                                      |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Library / OvertureDB source | The library and the catalog are curated separately.                                                                      |
| Movies / Shows tabs         | Libraries, sorts and filters are per media type.                                                                         |
| Items / Collections mode    | Collections are their own records with their own fields.                                                                 |
| Search box and Search by    | Finds a record by the field the user knows (title, ID, YouTube link).                                                    |
| Sort and direction          | Orders the list for the work at hand; each list keeps its own. Filters and sorts are defined once in `sidebarDomain.ts`. |
| Filters & operations        | Narrows the list and acts on what it matches.                                                                            |
| Group rows                  | Collections sit in their groups; Unmanaged lists those without criteria.                                                 |

## Filters & operations

| Control                                                                              | Why                                                              |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| One section per filter, in registry order, media server last                         | The same filter reads the same for items and collections.        |
| Reset filters (left) / Cancel / Apply filters                                        | Popup convention: reset apart, dismiss, then the primary action. |
| Monitor / Unmonitor                                                                  | Monitoring decides what Assets runs visit.                       |
| Clear artwork / theme selections                                                     | Starts the matching records over without deleting files.         |
| Delete from Overture (items)                                                         | Drops stale records; files and the server stay.                  |
| Collection operations: sync, group, take over, sort, sort titles, visibility, delete | Group-wide edits without opening each collection.                |
| Discard drafts (catalog)                                                             | Drops local catalog changes after they are contributed.          |

## Operations

| Control                                                                  | Why                                                                               |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------- |
| Assets: Libraries / Collections scope, groups, sidebar items             | Says what a run covers; schedules take the stable scopes only.                    |
| Assets: Replace existing, Include unmonitored, Skip items checked within | The three ways a run treats records it has seen.                                  |
| Assets: art types, source order, threshold                               | Which slots, from where, and how close a local match must be.                     |
| Sync: libraries, Collections, collection group, schedules                | Full or incremental refresh; a group syncs alone.                                 |
| Renamer, Audit                                                           | Fix local file names; check what the server shows. Hidden without a media server. |

## Detail pages

| Control                                  | Why                                                                  |
| ---------------------------------------- | -------------------------------------------------------------------- |
| Art / Themes tabs, slot tabs             | One slot at a time, the way auto-advance walks them.                 |
| Select / Overwrite, Contribute, No theme | Choose a theme, draft it for OvertureDB, or record that none exists. |
| Database record, Monitor, Delete         | Inspect and manage the stored record.                                |
| Contribute to OvertureDB link            | Opens a prefilled issue; warns about art hosts OvertureDB refuses.   |

## Settings

| Control                                                                                        | Why                                                                          |
| ---------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Aspect ratio control: Strict / Lenient / Off                                                   | How far art may be from its slot's shape; Strict is the catalog's tolerance. |
| Auto-match art on load, Workflow, Auto-advance (Off / Slots / Slots and items), Skip completed | How the editor moves through work.                                           |
| Collection defaults, Require a group                                                           | Defaults every group and collection inherits.                                |
| Show background image, Theme, Increase contrast                                                | Local appearance only.                                                       |
