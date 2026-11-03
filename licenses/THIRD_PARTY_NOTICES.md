# Third-party notices

Overture is distributed under the AGPL-3.0-only license in `LICENSE`. It
incorporates the open-source components and identification marks below. The
release image keeps Python and frontend dependency license files under
`/usr/share/licenses/overture/dependencies`, and every release publishes an SPDX
SBOM for each image platform. The native archive keeps these notices and the
frontend licenses in `licenses/`; each Python package keeps its license in its
`dist-info` folder, and the bundled python-build-standalone runtime keeps
CPython's license.

## Runtime libraries

| Component | License |
| --- | --- |
| aiosqlite, Alembic, FastAPI, jsonschema, Pydantic Settings, SQLAlchemy, SQLModel | MIT |
| greenlet | MIT and Python Software Foundation License Version 2 |
| argon2-cffi, python-dotenv | MIT |
| argon2-cffi-bindings | MIT (bundled Argon2 reference implementation: Apache-2.0 or CC0-1.0) |
| tzdata | Apache-2.0 |
| CPython | Python Software Foundation License Version 2 |
| blake3 | Apache-2.0 or CC0-1.0 |
| Authlib, httpx2, joserfc | BSD-3-Clause |
| Pillow | MIT-CMU |
| Uvicorn | BSD-3-Clause |
| yt-dlp | Unlicense |
| yt-dlp-ejs | Unlicense, MIT, and ISC components |
| Svelte, Vite, TanStack Query, sv-router | MIT |
| Lucide | ISC |
| Deno | MIT; official binary imported from `denoland/deno:bin`; license is in `licenses/Deno-LICENSE.txt` |
| FFmpeg and FFprobe | GPL-3.0-or-later build (`--enable-gpl --enable-version3`); static multi-arch binaries imported from `mwader/static-ffmpeg`; see the [upstream build configuration](https://github.com/wader/static-ffmpeg) and [FFmpeg legal page](https://ffmpeg.org/legal.html). |

Copyright notices and complete license texts supplied by these distributions
control if this summary differs from their metadata.

## Fonts

The web interface serves Inter v20 (Latin and Latin Extended, weights 400-700)
from the [Fontsource](https://fontsource.org/fonts/inter) v5.3.0 distribution of
[Inter](https://github.com/rsms/inter), under the SIL Open Font License 1.1 in
`frontend/public/fonts/OFL.txt`.

## Service marks and logos

The TMDB, TVDB, IMDb, Letterboxd, The Poster Database, Fanart.tv, YouTube, and
GitHub marks are used only to identify links to those services. They remain the
property of their respective owners. Source and brand-guideline links are
recorded below. Overture is not endorsed by or affiliated with those services.

| Owner | Brand guidelines | Source |
| :--- | :--- | :--- |
| TMDB | https://www.themoviedb.org/about/logos-attribution | https://www.themoviedb.org/assets/2/v4/logos/v2/blue_square_2-d537fb228cf3ded904ef09b136fe3fec72548ebc1fea3fbbd1ad9e36364db38b.svg |
| TVDB | None found | https://thetvdb.com/images/logo.svg |
| IMDb | https://brand.imdb.com/ | No SVG url found, `IMDb_Square_GoldBKG.svg` from brand page download used. |
| Letterboxd | https://letterboxd.com/about/brand/ | https://a.ltrbxd.com/logos/letterboxd-decal-dots-pos-rgb.svg |
| TPDb | https://theposterdb.com/branding | https://theposterdb.com/assets/logos/icon/color.svg |
| Fanart | None found | https://fanart.tv/icon.svg |
| YouTube | https://brand.youtube/ | No SVG url or icon download found, `yt_icon_red_digital.png` from brand page download used. |
| GitHub | https://brand.github.com/foundations/logo | No SVG url found, `GitHub_Invertocat_White.svg` from brand page download used. |

## Downloaded catalog data

OvertureDB is not embedded in the application image. When a user opts in, its
catalog and applicable notices are downloaded from the separately maintained
OvertureDB publication. Those notices govern the catalog data.
