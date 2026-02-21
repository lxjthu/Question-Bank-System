from app.factory import create_app
import os

# Create the Flask application with development configuration
app = create_app('development')

if __name__ == '__main__':
    # Get the port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))

    # Run the application
    app.run(
        host='0.0.0.0',  # Listen on all available interfaces
        port=port,
        debug=True  # Enable debug mode for development
    )