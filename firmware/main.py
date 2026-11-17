# Boot wrapper (never replaced over the air).
# Before the app starts: if an update was cut off part-way, or the new version keeps restarting
# without confirming itself, put the old version back. If the app crashes right after an
# update, do the same. Otherwise keep a minimal Wi-Fi + upload server running (rescue.py) so
# the Pico can still be fixed over the network.
import machine
try:
    import rollback
    why = rollback.boot_check()
    if why and rollback.undo(why):
        machine.reset()
except Exception as ex:
    import sys
    sys.print_exception(ex)

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
            machine.reset()
    except Exception as ex2:
        sys.print_exception(ex2)
    try:
        import rescue  # noqa: F401  (runs until it restarts the Pico)
    except Exception as ex3:  # even the rescue server can't start: try everything again in a minute
        sys.print_exception(ex3)
        import time
        time.sleep(60)
        machine.reset()
