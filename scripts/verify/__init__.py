"""Check Overture end to end against its media servers, read only.

Point it at a synced Overture, and at the media servers MEDIA_SERVERS names
(one each of Plex, Jellyfin and Emby). Each server Overture names is checked
on its own, against the given server of its kind. Overture is
asked through its own API, so every result comes from the code users run; each
media server is asked directly, so Overture's answers are compared with the
server's own:

- **Inventory**: the libraries, every item and every collection Overture lists
  are the ones the server holds, with the members, title, kind and theme the
  server holds. A collection the server holds that Overture leaves out is
  named with why: a separator, an empty one, one of other items, or an
  unmanaged one while importing them is off.
- **Fields**: every field and operator previews in every library; on Plex a
  field both evaluators know is previewed by Overture and by Plex, the counts
  must agree, and where they differ the range of years is narrowed until the
  title they disagree on is found, shown with the values Plex holds for it and
  whether Plex lists the value at all. Where Plex refuses a text value, the
  value is sent to Plex directly to show which character it refuses. On
  Jellyfin and Emby the fields the server filters on are counted by the
  server as well.
- **Values**: every tag and text field lists its values, and they include every
  value the server lists for its own filters; on Plex, the values Overture
  offers that Plex does not list, which no smart collection can select, are
  noted.
- **Orders**: every order previews; where Overture and Plex both sort, their
  first members are compared (ties may legitimately differ).
- **Kinds**: the kind recommended for each condition is the one Overture's
  rule names: smart where Plex tests it itself or only Plex can, regular where
  Overture evaluates it, including through labels.
- **Sources and sets**: Radarr and Sonarr tags, every TMDB chart, any given
  sources and every set dimension, with the defaults it starts with, preview.
- **Collections**: in each library, each managed collection's rule previews to
  the members the server's copy holds; each unmanaged one plans an adoption
  whose criteria the editor offers and that selects what the server holds;
  every poster and background Overture serves, from the server or its own
  cache, loads.
- **OvertureDB**: a sample of each library's contribution issues are links to
  the OvertureDB form of their media type.
- **What the server offers**: every Plex filter, field, sort and operator is one
  Overture can use; every Jellyfin and Emby filter is one Overture offers.
- **TMDB, MDBList, Radarr and Sonarr**, each read directly when its key is set:
  every TMDB chart Overture offers or lacks, genres, watch providers,
  collection search and one title's details; MDBList's limits, lists, list
  items, list search and one title's details, including whether it names a
  franchise; Radarr's and Sonarr's tags, quality profiles and root folders
  against those Overture offers, and their import lists.

Where Plex itself answers a condition differently from what it means
elsewhere, the difference is noted with the reason rather than reported.

It changes nothing unless asked. Overture is signed in to with API keys, which
read and preview but never change; media servers and every other service are
only sent GET requests, and any other Overture request is refused before it is
sent.

- **Writes**, only with ``--write``: what reading cannot show, how each media
  server takes Overture's own collection writes. Overture's media server
  clients, the code a sync runs, create a regular collection and on Plex a
  smart one, change and order their members, edit their title, sort title,
  summary and order (and on Plex its Home visibility), upload a poster and a
  background, change the smart one's filter and delete them, reading the
  server itself back after each step. Each step is reported on its own, with
  the request the server refused. Everything they make is titled "zz Overture
  verify" and deleted at the end, whatever fails, once Jellyfin and Emby have
  finished saving it; one left by a run that was killed is deleted first, and
  one the server makes again by itself is reported. No item, library or other
  collection is changed.

Create an Overture key under API keys in the menu, and give each media
server's address and its token or API key. For Overture with Plex, Jellyfin
and Emby in MEDIA_SERVERS:

    OVERTURE_API_KEY=key \
        PLEX_TOKEN=... \
        JELLYFIN_API_KEY=... \
        EMBY_API_KEY=... \
        RADARR_API_KEY=... \
        SONARR_API_KEY=... \
        uv run python -m scripts.verify \
        http://localhost:5885 \
        --plex https://localhost:32400 --insecure \
        --jellyfin http://localhost:8096 \
        --emby http://localhost:8095 \
        --radarr http://localhost:7878 \
        --sonarr http://localhost:8989 \
        --report verify.md

Set TMDB_READ_ACCESS_TOKEN and MDBLIST_API_KEY to probe those APIs too, and pass
--radarr and --sonarr with RADARR_API_KEY and SONARR_API_KEY to compare them.

A server that is not given, or one of several of its kind in MEDIA_SERVERS,
is checked through Overture alone. Pass --sources with a JSON file of source
objects (as the API takes them) to test TMDB, MDBList and person sources, and
--insecure to skip TLS certificate verification.
"""
