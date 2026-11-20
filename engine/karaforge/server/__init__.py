"""The web server: a JSON API over the engine plus the bundled single-page app.

``kf serve`` starts it.  Everything here is a thin layer — projects are plain folders, the
work is done by the same pipeline the command line uses, and the editor's preview is the very
ASS script an export would burn in.
"""

from karaforge.server.app import ServerSettings, create_app

__all__ = ["ServerSettings", "create_app"]
