"""Stand-ins for app.py's step marks (ph_on/ph_off/ph_planned/@phased), for tests that run parts of app.py on their own."""
STUB = {'ph_on': lambda k: None, 'ph_off': lambda k: None, 'ph_planned': lambda *a: None, 'phased': lambda k, a=False: (lambda f: f)}
