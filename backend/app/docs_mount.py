"""Legacy compatibility shim for the retired in-app VitePress mount."""


def mount_docs(app: object) -> bool:
    """The app image no longer builds or serves VitePress documentation."""
    return False
