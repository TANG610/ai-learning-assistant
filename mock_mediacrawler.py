"""
Minimal MediaCrawler mock server for development.
Responds to the collector service's API calls so the frontend doesn't error out.
"""
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/api/crawler/status", methods=["GET"])
def crawler_status():
    return jsonify({"status": "idle", "message": "Mock crawler - no actual crawling"})


@app.route("/api/crawler/start", methods=["POST"])
def crawler_start():
    return jsonify({"status": "accepted", "task_id": "mock-task-001"})


@app.route("/api/crawler/stop", methods=["POST"])
def crawler_stop():
    return jsonify({"status": "stopped"})


@app.route("/api/data/files", methods=["GET"])
def list_files():
    return jsonify({"files": [], "total": 0})


@app.route("/api/data/files/<path:file_path>", methods=["GET"])
def read_file(file_path):
    return jsonify({"data": [], "total": 0})


if __name__ == "__main__":
    print("MediaCrawler Mock Server starting on http://127.0.0.1:8080")
    app.run(host="127.0.0.1", port=8080, debug=False)
