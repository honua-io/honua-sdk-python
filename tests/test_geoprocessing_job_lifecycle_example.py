from __future__ import annotations

import json

import httpx

from examples.geoprocessing_job_lifecycle import run_job


def test_focused_example_submits_polls_and_fetches_results() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            assert json.loads(request.content) == {
                "inputs": {"inputGeoJson": "{}", "distance": 100},
                "response": "document",
            }
            return httpx.Response(
                201,
                headers={"Location": "http://example.test/ogc/processes/jobs/job-1"},
                json={
                    "jobID": "job-1",
                    "processID": "geometry.buffer",
                    "status": "accepted",
                },
            )
        if request.url.path == "/ogc/processes/jobs/job-1":
            return httpx.Response(
                200,
                json={
                    "jobID": "job-1",
                    "processID": "geometry.buffer",
                    "status": "successful",
                },
            )
        if request.url.path == "/ogc/processes/jobs/job-1/results":
            return httpx.Response(
                200,
                json={"outputFeatureLayer": {"value": {"type": "FeatureCollection", "features": []}}},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    result = run_job(
        "http://example.test",
        "geometry.buffer",
        {"inputGeoJson": "{}", "distance": 100},
        poll_interval=0.0,
        deadline_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )

    assert result["outputFeatureLayer"]["value"]["type"] == "FeatureCollection"
    assert requests == [
        ("POST", "/ogc/processes/processes/geometry.buffer/execution"),
        ("GET", "/ogc/processes/jobs/job-1"),
        ("GET", "/ogc/processes/jobs/job-1/results"),
    ]
