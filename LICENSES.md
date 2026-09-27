# Third-party licences

Every library and system package this project installs, and the licence
it ships under, as read from each package's installed distribution
metadata (`pip show`, Debian's `copyright` file) cross-checked against
each package's own `License-Expression`/`Classifier` metadata. All are
open source; no closed-source or paid dependency is used.

## System dependency (not installed by pip)

| Package | Installed version | Licence | Used for |
|---|---|---|---|
| [tesseract-ocr](https://github.com/tesseract-ocr/tesseract) (Debian package `tesseract-ocr`, plus `tesseract-ocr-eng`) | 5.5.0 (Debian `5.5.0-1+b1`) | Apache-2.0 | The OCR engine itself. Installed with `sudo apt-get install -y tesseract-ocr`; not vendored in this repo. |

## Direct dependencies (pinned in `requirements.txt`)

| Library | Pinned version | Licence | Used for |
|---|---|---|---|
| [Pillow](https://pillow.readthedocs.io) | 12.3.0 | MIT-CMU (HPND-style) | Rendering the synthetic receipt images and preprocessing scans before OCR |
| [pytesseract](https://github.com/madmaze/pytesseract) | 0.3.13 | Apache-2.0 | Python wrapper calling the `tesseract` binary and parsing its word-level output |
| [pytest](https://docs.pytest.org/) | 9.1.1 | MIT | Test suite |

## Transitive dependencies (not pinned; versions from a clean install)

| Library | Resolved version | Licence | Pulled in by |
|---|---|---|---|
| [packaging](https://pypi.org/project/packaging/) | 26.3 | Apache-2.0 OR BSD-2-Clause | pytest |
| [pluggy](https://pypi.org/project/pluggy/) | 1.6.0 | MIT | pytest |
| [iniconfig](https://pypi.org/project/iniconfig/) | 2.3.0 | MIT | pytest |
| [Pygments](https://pygments.org/) | 2.21.0 | BSD-2-Clause | pytest |

## Fonts used by the generator

| Asset | Licence | Used for |
|---|---|---|
| DejaVu fonts (`/usr/share/fonts/truetype/dejavu`, Debian package `fonts-dejavu-core`) | Bitstream Vera License + public-domain additions (DejaVu changes) | Rendering receipt text in the synthetic images |

## Notices

These licences require their copyright and licence notices to be kept with
any copy or redistribution. This repository does not vendor or redistribute
any of these packages; the Python libraries are installed from PyPI and
`tesseract-ocr` is installed from the Debian package archive. Each carries
its own licence and notice files, and those must be preserved in any
distribution that includes them.

No paid or closed-source service is used anywhere in this project.
