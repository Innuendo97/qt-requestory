"""User preferences shared by pages (QSettings keys and defaults)."""
GROUP_BY_FDI_KEY = "search/group_by_fdi"
GROUP_BY_FDI_DEFAULT = True
KEY_MODE_KEY = "search/key_mode"
KEY_MODE_DEFAULT = "exact"
RECENT_KEY = "search/recent"

# Genera (``ui/pages/genera_presenter``): the last choices, restored when the tab is built.
GENERA_MODE_KEY = "genera/mode"            # "keys" | "elenco" | "fdi"
GENERA_GENERATOR_KEY = "genera/generator"
GENERA_SOURCE_ENV_KEY = "genera/source_env"  # "" = follows the generator
GENERA_DESTINATION_KEY = "genera/destination"
GENERA_ELENCO_KEY = "genera/elenco"        # the list's path; saved only once it loaded
GENERA_ZIP_KEY = "genera/zip"
GENERA_HTML_KEY = "genera/html"
