# Parity matrix

What each kind of record can do, by source, media type and record. **Done**
means the feature works there; **justified** means it cannot apply, for the
reason given; **gap** means it should exist and does not.

| Feature                         | Library movies | Library shows | Library collections | OvertureDB movies | OvertureDB shows | OvertureDB collections |
| ------------------------------- | -------------- | ------------- | ------------------- | ----------------- | ---------------- | ---------------------- |
| Poster and background selection | done           | done          | done                | done (draft)      | done (draft)     | done (draft)           |
| Season posters                  | justified (1)  | done          | justified (1)       | justified (1)     | done (draft)     | justified (1)          |
| Theme selection                 | done           | done          | done                | done (draft)      | done (draft)     | done (draft)           |
| No theme                        | done           | done          | done (catalog)      | done (draft)      | done (draft)     | done (draft)           |
| Assets runs (art and themes)    | done           | done          | done                | justified (2)     | justified (2)    | justified (2)          |
| Filters, sorts and search-by    | done           | done          | done                | done              | done             | done                   |
| Bulk monitor and unmonitor      | done           | done          | done                | justified (2)     | justified (2)    | justified (2)          |
| Bulk clear art and themes       | done           | done          | done                | justified (3)     | justified (3)    | justified (3)          |
| Bulk discard drafts             | justified (2)  | justified (2) | justified (2)       | done              | done             | done                   |
| Database record                 | done           | done          | done                | done              | done             | done                   |
| Contribute (issue link, export) | done           | done          | done                | done              | done             | done                   |
| Contribute a theme only         | done           | done          | gap (4)             | done (draft)      | done (draft)     | done (draft)           |
| Smart collections               | -              | -             | justified (5)       | -                 | -                | -                      |

1. Seasons are never standalone records; only shows have season posters.
2. The catalog holds curated entries, not library state: it has drafts, not
   monitoring or runs; the library has selections, not drafts.
3. A catalog entry's choices are cleared by discarding its draft.
4. Collection theme results do not offer Contribute yet; the collection's
   issue link carries its theme instead.
5. Smart collections are Plex-only. OvertureDB collections exist for movies
   only, since TMDB collections hold movies.
