"""Every user-visible string of the application, in Italian, in one namespace.

Widgets never contain literal text: they read a constant from here, so the
wording of the whole application can be reviewed (and one day translated) by
reading six small files instead of grepping twenty widgets.

**Why a package and not a module.** Six tasks build the UI in parallel; if they
all appended to one ``strings.py`` every one of them would conflict with the
others. One module per page means each task owns a file:

===================  ==================================================
``common.py``        the shell: window, rail, status bar, generic buttons
``search.py``        Ricerca page + preview pane
``sync.py``          Sincronizzazione page
``settings.py``      Impostazioni page
``wizard.py``        first-run wizard
``about.py``         Info page
===================  ==================================================

Usage — always through the package, never the submodule::

    from qtrequestory.ui import strings
    button.setText(strings.BTN_SAVE)

Rules for the page modules: ``UPPER_CASE`` module-level ``str`` constants only,
no imports that leak (a submodule without ``__all__`` re-exports every public
name it defines), and ``{field}`` placeholders documented in a comment above
the constant.
"""
from .common import *  # noqa: F401,F403
from .search import *  # noqa: F401,F403
from .sync import *  # noqa: F401,F403
from .settings import *  # noqa: F401,F403
from .wizard import *  # noqa: F401,F403
from .about import *  # noqa: F401,F403
