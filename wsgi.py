import sys
import os

# Ensure inner app directory is on the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'ebms_flask', 'ebms_flask'))

from run import app

if __name__ == '__main__':
    app.run()
