#!/usr/bin/env bash
# Download the five OFL font families (tokens.css type system) into
# client/assets/fonts/. Idempotent: re-downloads everything when run.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

BASE="https://raw.githubusercontent.com/google/fonts/main/ofl"

fetch() { # fetch <url-path> <dest-relative-to-client/assets/fonts>
  mkdir -p "client/assets/fonts/$(dirname "$2")"
  curl -fSL "$BASE/$1" -o "client/assets/fonts/$2"
}

fetch "spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf"        "spacegrotesk/SpaceGrotesk-Variable.ttf"
fetch "spacegrotesk/OFL.txt"                          "spacegrotesk/OFL.txt"

fetch "chakrapetch/ChakraPetch-Medium.ttf"            "chakrapetch/ChakraPetch-Medium.ttf"
fetch "chakrapetch/ChakraPetch-SemiBold.ttf"          "chakrapetch/ChakraPetch-SemiBold.ttf"
fetch "chakrapetch/ChakraPetch-Bold.ttf"              "chakrapetch/ChakraPetch-Bold.ttf"
fetch "chakrapetch/OFL.txt"                           "chakrapetch/OFL.txt"

fetch "atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf" "atkinsonhyperlegible/AtkinsonHyperlegible-Regular.ttf"
fetch "atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf"    "atkinsonhyperlegible/AtkinsonHyperlegible-Bold.ttf"
fetch "atkinsonhyperlegible/AtkinsonHyperlegible-Italic.ttf"  "atkinsonhyperlegible/AtkinsonHyperlegible-Italic.ttf"
fetch "atkinsonhyperlegible/OFL.txt"                          "atkinsonhyperlegible/OFL.txt"

fetch "ibmplexmono/IBMPlexMono-Regular.ttf"           "ibmplexmono/IBMPlexMono-Regular.ttf"
fetch "ibmplexmono/IBMPlexMono-Medium.ttf"            "ibmplexmono/IBMPlexMono-Medium.ttf"
fetch "ibmplexmono/IBMPlexMono-SemiBold.ttf"          "ibmplexmono/IBMPlexMono-SemiBold.ttf"
fetch "ibmplexmono/OFL.txt"                           "ibmplexmono/OFL.txt"

fetch "vt323/VT323-Regular.ttf"                       "vt323/VT323-Regular.ttf"
fetch "vt323/OFL.txt"                                 "vt323/OFL.txt"

echo "fonts installed under client/assets/fonts/"
