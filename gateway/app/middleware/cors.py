from flask import Flask


def configure_cors(app: Flask):
    """Configure CORS headers for the application."""
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-API-Key'
        response.headers['Access-Control-Max-Age'] = '3600'
        return response
