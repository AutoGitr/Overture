---
sidebar_position: 6
title: Art and themes
description: Automatic and generated collection art, OvertureDB posters and collection themes.
---

# Art and themes

Collection posters and backgrounds come from OvertureDB, TMDB, local-image
matching against the server's current image, your own uploads, or art Overture
generates from the title; they are uploaded to the media server. Collection themes
use OvertureDB and ThemerrDB in the configured order.

## Art generated from the title

Posters are drawn at 2000×3000 and backgrounds at 3840×2160. Their colour
gradients are dithered, so they show no bands even after the media server
re-encodes them as 8-bit JPEG.

Every collection's poster and background candidates end with a **Generated**
row, one image per style (dark, light and accent) showing its title under its
group's name. Choosing one keeps it in the image cache and uploads it like any
other art, and its source shows as **Generated**.

A poster always shows the title; a grouped collection's is offered under its
group and with the title alone, centred. A background never shows text, as the
media server draws the title over it. Art generated either way is generated again
when the collection's title or group changes.

## Automatic art

**Automatic art** in Settings (global, per group or per collection) decides
what a sync does for a slot no one chose. Tick the sources it may use and drag
them into order; a sync takes the best art of the first ticked source, top to
bottom, that has any:

- **OvertureDB**, its catalog art, in the styles **OvertureDB posters** takes
- **TMDB**, the franchise's art, or a listed person's photo
- **Generate**, art drawn from the title; a source below it is never reached

With nothing ticked, Automatic art is off. A group or collection can follow
**Default** or set its own order. The media server's own art is never taken. Generating makes a poster with the
title and a background without text, in the **Generated colours** (dark, light or
accent). **Generated poster group** chooses whether the poster shows the
collection's group above its title (**Show**, the default) or the title alone
(**Hide**); a collection without a group shows its title alone either way. Both
apply when Automatic art generates a poster; art generated earlier keeps how it
was generated, and you can pick either variant in the **Poster** tab. A collection whose **Background** is **Not needed** gets no
background: its poster completes its art, as OvertureDB's No theme completes a
theme.

Collections whose criteria list a TMDB person offer that person's photos as
poster candidates.

The **Background** tab also offers the members' own TMDB backgrounds, under
**Members**: the 10 largest of each member, and the 100 largest of all, read
from the first 100 members in the collection's order. They are fetched only
when you open the tab, and runs never compare them.

## OvertureDB posters

**OvertureDB posters**, a collection setting (global, per group or per
collection), chooses which posters OvertureDB gives a TMDB collection. Tick the
styles to take and drag them into order; a collection takes the first ticked
style OvertureDB holds for it, so **Matte**, then **Individual** gives every
collection a matte poster where one exists and its own poster otherwise:

- **Individual**, its own.
- **Matte**, one in the [DarkMatte layout](https://theposterdb.com/poster/668235)
  by TPDB user `DarkMatte`, generated using the `"Dark Matte"` overlay at
  [Poster Lab](https://postertools.org/poster-lab/) and hosted on TMDB or
  ThePosterDB.
- **Overlay**, one in the [Silva overlay layout](https://theposterdb.com/poster/2503),
  made with the
  [Coverlabs Silva designer](https://www.coverlabs.studio/designer/silva) and
  hosted on TMDB or ThePosterDB.

A collection holding none of the ticked styles, or one with no style ticked,
gets no OvertureDB poster; its OvertureDB background is still taken.
Automatic art follows each collection's choice.

### Which style a chosen poster is

Every poster you choose for a collection remembers which of the three it is,
and exports and **Contribute issue** contribute it as that, whatever
**OvertureDB posters** says later:

- On a collection's **Poster** tab, **Contribute to OvertureDB as** picks the
  style of the poster you choose next, starting from the first style the
  collection's **OvertureDB posters** ticks (**Individual** when none is).
  Pick it before choosing a TMDB poster or pasting a link.
- A poster OvertureDB already holds keeps its own style, and its card says
  which (**Individual**, **Matte** or **Overlay**). OvertureDB's section offers
  all three of a collection's posters, the setting's styles first, in its order.
- Posters Automatic art or Assets choose from OvertureDB keep the style
  OvertureDB holds them as, and any other poster is **Individual**.

A **Matte** or **Overlay** poster from any source other than TMDB or
ThePosterDB is left out of contributions, which say so. The catalog view shows
any of the three ([Browsing the catalog](../overturedb.md#browsing-the-catalog));
the OvertureDB guidelines describe the
[consistent collection posters](/overturedb/contributing/selection-guidelines#consistent-collection-posters).

## Uploaded art and Audit

Collection posters and backgrounds Overture uploaded show from its image cache
in the sidebar and on the collection's page, and **Audit** can compare them
with the server's and upload them again.

## Themes

**Theme** (global, per group or per collection) says whether collections need
one. With **Not needed**, a collection's theme counts as complete without one,
in its status, the filters and the statistics, as OvertureDB's No theme does;
no theme is chosen for it automatically and Assets runs leave it out. A theme
you choose for it is still kept and sent.

A collection's automatic theme follows the **Automatic theme** setting, in the
same order of OvertureDB and ThemerrDB the Assets run uses. While **Theme** is
**Not needed**, Automatic theme is shown but off. New collection IDs
imported by a full Sync also use the catalog theme order of an enabled
incremental schedule covering their library. On Jellyfin, BoxSet themes are
written to the server's `COLLECTIONS_PATH`; a sync writes the theme again to a
BoxSet folder without one.

An inactive collection's art and theme can be chosen; the sync that puts it
back on the server sends them.

## What happens when

A collection's art and theme are Overture's choices, kept in Overture and sent
to every server copy: each Plex library's collection, and the one Jellyfin or
Emby collection. The **lead copy**, on the first server in `MEDIA_SERVERS`
that holds the collection, stands for what the servers show.

| When                                     | Art (poster and background)                                                                                                                                                                                                                                          | Theme                                                                                                                                                                                            |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| You choose it                            | Overture fetches or reads the image, keeps it in its image cache, uploads it to every copy and records that it sent it. An inactive collection only records the choice. An Assets run queues its choice as a download, which does the same when it runs.             | The download is queued; when it runs, the track is downloaded once, uploaded to each Plex copy and written as `theme.mp3` to each Jellyfin collection's folder. Emby keeps no collection themes. |
| The collection syncs                     | A slot nothing was chosen for gets **Automatic art**. Generated art is drawn again when the title or group changed. A copy the sync makes, new or in place of one deleted on its server, gets the chosen art: the image Overture keeps, else its link fetched again. | A copy the sync makes, or a Jellyfin folder without its theme, gets the chosen theme. With nothing chosen, **Automatic theme** queues the catalog's theme.                                       |
| A server syncs                           | The lead copy's images are read. When the lead shows another image than the one Overture sent, Overture no longer counts it as sent; the choice stays, and **Audit** or the next new copy sends it again.                                                            | When the lead copy holds another theme than the one Overture sent, it was replaced on the server, so Overture forgets its choice. On Jellyfin the folder's `theme.mp3` is read.                  |
| A full Sync identifies a TMDB collection | Nothing changes until the collection's own sync.                                                                                                                                                                                                                     | Catalog themes are queued in the order of an enabled incremental schedule covering its library.                                                                                                  |
| You remove it                            | Forgetting it clears the choice; deleting it from the server removes it from every copy.                                                                                                                                                                             | Forgetting it clears the choice; deleting it removes Plex's theme and the Jellyfin folder's file.                                                                                                |
| It goes inactive or below its minimum    | The server copies are deleted; the choices stay.                                                                                                                                                                                                                     | The same.                                                                                                                                                                                        |
| It comes back                            | Its own sync makes the copies and sends the choices.                                                                                                                                                                                                                 | The same.                                                                                                                                                                                        |
| You delete the collection                | Its server copies, its row and its queued downloads go.                                                                                                                                                                                                              | The same.                                                                                                                                                                                        |

A step of a sync that fails, such as Automatic art, is reported as the sync's
error after its members are synced; the other steps still run.
