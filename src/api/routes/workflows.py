import asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class PipelineRunRequest(BaseModel):
    targets: list[str]
    campaign_id: Optional[str] = None


@router.post("/run")
async def run_pipeline(req: PipelineRunRequest):
    """Trigger a full pipeline run (scrape → extract → enrich → outreach)."""
    from src.infrastructure.orchestration.dag_runner import DAGRunner
    from src.infrastructure.orchestration.workflows import build_pipeline_dag

    dag = await build_pipeline_dag(targets=req.targets, campaign_id=req.campaign_id)
    runner = DAGRunner()
    context = {"targets": req.targets, "campaign_id": req.campaign_id}
    results = await runner.run(dag, context=context)

    return {
        "status": "completed",
        "steps": {
            name: {
                "status": r["status"],
                "duration_s": r["duration_s"],
                "error": r.get("error"),
            }
            for name, r in results.items()
        },
    }


@router.get("/schedule")
def get_schedule():
    """View all scheduled jobs."""
    from src.infrastructure.orchestration.scheduler import WorkflowScheduler

    scheduler = WorkflowScheduler()
    return {"jobs": scheduler.list_jobs()}


@router.get("/status")
def workflow_status():
    """Return current workflow system status."""
    return {
        "scheduler": "available",
        "dag_runner": "available",
        "note": "Use POST /run to trigger a pipeline. Scheduler starts with the API.",
    }
