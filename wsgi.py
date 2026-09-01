"""WSGI entrypoint for production servers.

    gunicorn --bind 127.0.0.1:8080 wsgi:app

Deliberately separate from ``app.py``'s ``__main__`` block so the production
path never touches Flask's development server or its interactive debugger.
"""
from app import create_app

app = create_app()
