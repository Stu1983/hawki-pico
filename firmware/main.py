# Boot wrapper (never replaced over the air).
# Runs the app. If it fails right after an update, put the old version back and restart.
# Otherwise keep a minimal Wi-Fi + upload server running (rescue.py) so the Pico can still
# be fixed over the network.
try:
    import app  # noqa: F401  (runs forever)
except Exception as ex:
    import sys
    try:
        with open('crash.log', 'w') as f:
            sys.print_exception(ex, f)
    except Exception:
        pass
    sys.print_exception(ex)
    try:
        import rollback
        if rollback.undo(repr(ex)):
            import machine
            machine.reset()
    except Exception as ex2:
        sys.print_exception(ex2)
    import rescue  # noqa: F401
