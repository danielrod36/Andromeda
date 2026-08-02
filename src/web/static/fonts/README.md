# Vendored Fonts

Andromeda vendors fonts locally (offline-first; no CDN). Download these
woff2 files and place them here:

## Literata (prose)
- URL: https://github.com/google/fonts/tree/main/ofl/literata
- Files: `Literata-Regular.woff2`, `Literata-Italic.woff2`, `Literata-Bold.woff2`
- License: SIL Open Font License 1.1 (copy `OFL.txt` from the repo)

## IBM Plex Sans (UI chrome)
- URL: https://github.com/IBM/plex/tree/main/IBM-Plex-Sans/fonts/complete/woff2
- Files: `IBMPlexSans-Regular.woff2`, `IBMPlexSans-Bold.woff2`
- License: SIL Open Font License 1.1

## IBM Plex Mono (engine voice)
- URL: https://github.com/IBM/plex/tree/main/IBM-Plex-Mono/fonts/complete/woff2
- Files: `IBMPlexMono-Regular.woff2`, `IBMPlexMono-Bold.woff2`
- License: SIL Open Font License 1.1

Until the woff2 files are present, the CSS falls back to system fonts
(Georgia for prose, system-ui for chrome, SF Mono/Consolas for engine voice).
