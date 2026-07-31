import os
from dotenv import load_dotenv

load_dotenv()  # must run before `from app import create_app`, since config.py reads os.environ at import time

from app import create_app  # noqa: E402

app = create_app()

if __name__ == '__main__':
    debug = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=debug)
