"""Flask 服务层：业务 API。

路由：
- GET  /health                      健康检查
- POST /pipeline                    触发一次 DAG 编排
- GET  /listings/<id>/reports       列出评分报告
- GET  /reports/<id>/replay         冻结 manifest 回放
"""

from __future__ import annotations

from flask import Flask, jsonify, request

from adgenie.config import Settings, get_settings
from adgenie.mechanisms.manifest import ManifestService
from adgenie.orchestration import run_pipeline
from adgenie.orchestration.agents import Container
from adgenie.wiring import build_container


def create_app(settings: Settings | None = None,
               container: Container | None = None) -> Flask:
    settings = settings or get_settings()
    container = container or build_container(settings)
    manifest_service = ManifestService(container.score_report_store)

    app = Flask(__name__)
    app.config["ADGENIE_CONTAINER"] = container
    app.config["ADGENIE_SETTINGS"] = settings

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "data_source": settings.data_source})

    @app.post("/pipeline")
    def pipeline():
        body = request.get_json(force=True, silent=True) or {}
        if not body.get("listing_id"):
            return jsonify({"error": "listing_id required"}), 400
        state = {
            "listing_id": body["listing_id"],
            "copy_text": body.get("copy_text", ""),
            "profile_version": body.get("profile_version"),
            "last_used_profile_version": body.get("last_used_profile_version"),
            "copy_version": body.get("copy_version"),
            "last_scored_copy_version": body.get("last_scored_copy_version"),
            "rubric_version": body.get("rubric_version"),
            "last_used_rubric_version": body.get("last_used_rubric_version"),
            "knowledge_version": body.get("knowledge_version"),
            "last_used_knowledge_version": body.get("last_used_knowledge_version"),
        }
        result = run_pipeline(container, state)
        return jsonify({
            "node_status": result.get("node_status", {}),
            "errors": result.get("errors", {}),
            "score_report": result.get("score_report"),
            "strategy": result.get("strategy", []),
        })

    @app.get("/listings/<listing_id>/reports")
    def list_reports(listing_id: str):
        reports = container.score_report_store.list_for_listing(listing_id)
        return jsonify([r.model_dump(mode="json") for r in reports])

    @app.get("/reports/<report_id>/replay")
    def replay(report_id: str):
        record = manifest_service.replay(report_id)
        if record is None:
            return jsonify({"error": "report not found"}), 404
        return jsonify(record)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=get_settings().service.host, port=get_settings().service.port)
