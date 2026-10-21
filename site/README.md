# Website

The static landing page for QCI: `index.html`, with `styles.css`, its scripts (`script.js`,
`terminal.js`, `bloch-sphere.js`, `qubits.js`, `quotes.js`) and the data in `portraits/`.
`site-config.js` holds the outbound links and must stay free of secrets.

The site is independent of the Python package: it has no build step, is never included in
the built wheel or sdist, and is not covered by the product gates in `CLAUDE.md`.

Preview it locally from the repository root:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

Then open http://127.0.0.1:8765/.

This section moved here from the repository's `README.md` in R1b, when the README was
rewritten for users of the package.
