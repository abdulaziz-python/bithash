
import os
from app import app, socketio

# For production deployment
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
else:
    # For gunicorn: gunicorn wsgi:app
    application = app
