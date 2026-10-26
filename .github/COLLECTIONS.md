# Collections and Kometa equivalents

Overture configures collections through **Collections > + Create collection**.
The [Kometa defaults guide](https://kometa.wiki/en/latest/defaults/guide/)
inspired the preset workflow: choose a set, select its entries, and customize
shared settings. Overture uses its own collection rules; it does not import
Kometa YAML or execute Kometa defaults files.

## Choose a starting point

| Collection goal | Overture configuration |
| --- | --- |
| One collection per decade, year or genre | **Type: Preset**, then **Decades**, **Years** or **Genres** |
| Discover movie franchises from the library | **Type: Preset > TMDB franchises** |
| Combine TMDB franchises, lists, titles or person credits | **Type: Custom > Dynamic sources**, then add sources in Content |
| Build from MDBList or Radarr/Sonarr tags | **Type: Custom > Dynamic sources**, then choose the corresponding source |
| Match nested metadata conditions | Add a **Library filter** source |
| Let Plex evaluate live membership and user state | **Type: Custom > Plex smart filter** |
| Share display, sync and asset defaults | Assign a **Collection Group** and use **Manage groups** |
| Keep a collection only during part of the year | Set recurring dates in **Schedule** |

## Example: collections for each decade

1. Select a library and choose **Type: Preset > Decades**.
2. Click **Preview collections**. Overture lists decades represented in the
   library, with their current member counts.
3. Select the decades to create. Optionally assign a group such as `Decades`.
4. Adjust the minimum membership and sync policy in **Content**. A decade with
   fewer members than the effective minimum cannot be created.
5. Expand **Display** to set shared display choices. For example, a sort title
   of `01_{title}` keeps these collections together.
6. Expand **Schedule** to adjust automatic sync, then click
   **Create selected collections**.

Each result is a regular collection with an editable library filter. Its members
update on subsequent rule syncs. Years and genres use the same workflow.
Preview again when you want to create newly available values, such as a new
decade. Existing matching titles are kept and reported, so select only the
entries you want to add. Successful creations remain if another entry fails;
the form selects failed entries for review and retry.

TMDB franchise discovery instead saves a group's discovery configuration and
can discover new franchises on later runs. It requires a movie library, a group,
imported TMDB franchise memberships, and a configured TMDB API key.

## Customize the results

An explicit collection choice overrides its group; the group overrides global
collection defaults. Choose **Default** to inherit. Text fields show inherited
values as placeholders. Group **Save & Apply** updates display settings while
preserving explicit overrides and membership.

Dynamic sources merge matching items already in the selected library. A library
filter adds its own matches rather than filtering the results of other sources.
Strict sync replaces membership with source results; Append keeps manual members.
For a source-backed Plex smart collection, set a managed label, add sources, then
add live smart criteria. Without sources, Plex evaluates the criteria directly.

Overture does not implement every Kometa builder or default. In particular, the
preset selector lists only the supported presets; it is not the Kometa catalog.
Collections do not add missing titles to Radarr or Sonarr.

## Manage groups and deletion

**Manage groups > Manage group** can rename a group or delete it. Deleting just
the group leaves its collections ungrouped. You can also remove its collections
from Overture, the media server, or both. Server-only removal retains the local
configuration with scheduled rule sync disabled. Overture-only removal allows
the server collections to be imported again during a future library sync.

Collection deletion also succeeds when the server collection has already been
removed. These operations always preserve media files. Failed collection
operations are reported individually, and the group remains available for retry.

See the [collection guide](README.md#collections) for templates, seasonal windows,
artwork, themes, and bulk operations.
