from app import app, socketio

# To run: e.g. `hypercorn asgi:app` or `uvicorn asgi:app`

asgi_app = socketio.asgi_app
