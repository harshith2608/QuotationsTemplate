release: flask db upgrade && flask bootstrap
web: gunicorn run:app --bind 0.0.0.0:$PORT
