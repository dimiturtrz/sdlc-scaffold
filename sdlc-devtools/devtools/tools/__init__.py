"""The non-gate utilities: `config` (prints the packaged ast-grep/jscpd config path an external CLI needs)
and `analytics` (repo statistics over areas). Neither answers the engine contract — they compute no findings
and gate nothing — so they sit apart from the checks. `config` is also imported by `astgrep`, which needs the
rules path; it is a shared resource locator as much as a CLI.
"""
