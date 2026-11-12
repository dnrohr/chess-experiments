# Third-party components

Application code is distributed under GPL-3.0-or-later; see LICENSE.

- **python-chess / chess**, copyright Niklas Fiekas and contributors:
  GPL-3.0-or-later. https://github.com/niklasf/python-chess
- **Cburnett piece artwork**, copyright Colin M. L. Burnett: GPL option of
  its GFDL/BSD/GPL triple license. Bundled SVG provenance appears in
  `src/counterfactual_chess/assets/ATTRIBUTION.md`.
- **PySide6 Essentials / Shiboken / Qt**, The Qt Company and contributors:
  Community edition has LGPLv3/GPLv3 options and component-specific notices.
  Dependencies remain separately installed, dynamically loaded wheels.
  https://doc.qt.io/qtforpython-6/licenses.html
  https://doc.qt.io/qtforpython-6/commercial/index.html
- **Stockfish**, the Stockfish developers: GPLv3. It is user supplied, not
  bundled in the application or committed to this repository.
  https://github.com/official-stockfish/Stockfish
- **Python**, Python Software Foundation and contributors: PSF license.
  https://docs.python.org/3/license.html

Before distributing a frozen application, include the exact dependency license
texts, copyright and third-party notices for the shipped versions; provide the
corresponding source and any other materials required by the chosen licenses.
If distributing Stockfish, include its license and the matching source/build
materials required by GPLv3. Packaging and its compliance verification are a
later milestone; this source checkout is not a ready-made binary distribution.
