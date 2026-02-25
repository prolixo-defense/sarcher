import sys
import os

# Ensure project root is on the path when running as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="networking-engine", help="B2B Networking Engine CLI")
console = Console()


# ---------------------------------------------------------------------------
# Phase 1 commands
# ---------------------------------------------------------------------------


@app.command()
def ingest(url: str = typer.Argument(..., help="URL to ingest (placeholder)")):
    """Manually ingest a lead from a URL (use POST /api/leads for structured input)."""
    console.print(f"[yellow]Ingest placeholder: {url}[/yellow]")
    console.print("[dim]Use 'scrape' command (Phase 2) or POST /api/leads instead.[/dim]")


@app.command()
def search(query: str = typer.Argument(..., help="Keyword to search leads")):
    """Search leads from the terminal."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
    from src.application.dtos.lead_dto import LeadSearchDTO
    from src.application.use_cases.search_leads import SearchLeads

    session = SessionLocal()
    try:
        repo = SqlLeadRepository(session)
        dto = LeadSearchDTO(keyword=query, limit=50, offset=0)
        leads, total = SearchLeads(repo).execute(dto)

        table = Table(title=f"Search results for '{query}' ({total} total)")
        table.add_column("Name")
        table.add_column("Email")
        table.add_column("Company")
        table.add_column("Status")
        table.add_column("Source")

        for lead in leads:
            table.add_row(
                lead.full_name(),
                lead.email or "—",
                lead.company_name or "—",
                lead.status.value,
                lead.source.value,
            )
        console.print(table)
    finally:
        session.close()


@app.command()
def export(
    format: str = typer.Option("csv", "--format", help="Export format: csv or json"),
    output: str = typer.Option("leads.csv", "--output", help="Output file path"),
):
    """Export leads to CSV or JSON."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
    from src.application.dtos.lead_dto import LeadExportDTO, LeadSearchDTO
    from src.application.use_cases.export_leads import ExportLeads

    session = SessionLocal()
    try:
        repo = SqlLeadRepository(session)
        dto = LeadExportDTO(format=format)
        data = ExportLeads(repo).execute(dto)
        with open(output, "wb") as f:
            f.write(data)
        console.print(f"[green]Exported to {output}[/green]")
    finally:
        session.close()


@app.command()
def stats():
    """Show lead counts by status."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
    from src.domain.enums import LeadStatus

    session = SessionLocal()
    try:
        repo = SqlLeadRepository(session)
        table = Table(title="Lead Stats")
        table.add_column("Status")
        table.add_column("Count", justify="right")

        total = 0
        for status in LeadStatus:
            count = repo.count({"status": status.value})
            table.add_row(status.value, str(count))
            total += count
        table.add_row("[bold]TOTAL[/bold]", f"[bold]{total}[/bold]")
        console.print(table)
    finally:
        session.close()


@app.command()
def cleanup():
    """Delete expired leads (GDPR TTL cleanup)."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository

    session = SessionLocal()
    try:
        repo = SqlLeadRepository(session)
        count = repo.delete_expired()
        session.commit()
        console.print(f"[green]Deleted {count} expired leads.[/green]")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Phase 2 commands
# ---------------------------------------------------------------------------


@app.command()
def scrape(
    target: str = typer.Argument(..., help="URL or domain to scrape"),
    source_type: str = typer.Option(
        "website", "--source-type", help="website | linkedin | directory"
    ),
    async_mode: bool = typer.Option(
        True, "--async/--sync", help="Queue via Celery (async) or run directly (sync)"
    ),
):
    """Scrape a target and ingest leads into the database."""
    from src.infrastructure.task_queue.tasks import (
        scrape_corporate_website,
        scrape_linkedin_profile,
        scrape_directory,
        CELERY_AVAILABLE,
    )

    use_celery = async_mode and CELERY_AVAILABLE
    console.print(f"[cyan]Scraping {source_type}: {target}[/cyan]")

    if source_type == "linkedin":
        if use_celery:
            task = scrape_linkedin_profile.delay(target)
            console.print(f"[green]Queued LinkedIn scrape (task_id={task.id})[/green]")
        else:
            result = scrape_linkedin_profile(target)
            console.print(f"[green]Done: {result.get('leads_ingested', 0)} leads ingested[/green]")
    elif source_type == "directory":
        if use_celery:
            task = scrape_directory.delay(target, {})
            console.print(f"[green]Queued directory scrape (task_id={task.id})[/green]")
        else:
            result = scrape_directory(target, {})
            console.print(f"[green]Done: {result.get('leads_ingested', 0)} leads ingested[/green]")
    else:  # website (default)
        if use_celery:
            task = scrape_corporate_website.delay(target)
            console.print(f"[green]Queued website scrape (task_id={task.id})[/green]")
        else:
            result = scrape_corporate_website(target)
            console.print(f"[green]Done: {result.get('leads_ingested', 0)} leads ingested[/green]")


@app.command()
def scrape_batch(
    file: str = typer.Argument(..., help="Path to a file with one URL/domain per line"),
    source_type: str = typer.Option(
        "website", "--source-type", help="website | linkedin | directory"
    ),
):
    """Scrape multiple targets from a file (one URL per line)."""
    from src.infrastructure.task_queue.tasks import (
        scrape_corporate_website,
        scrape_linkedin_profile,
        scrape_directory,
        CELERY_AVAILABLE,
    )

    try:
        with open(file) as f:
            targets = [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
    except FileNotFoundError:
        console.print(f"[red]File not found: {file}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Batch scraping {len(targets)} targets ({source_type})...[/cyan]")

    for target in targets:
        try:
            if source_type == "linkedin":
                if CELERY_AVAILABLE:
                    task = scrape_linkedin_profile.delay(target)
                    console.print(f"  Queued {target} → task {task.id}")
                else:
                    result = scrape_linkedin_profile(target)
                    console.print(f"  {target}: {result.get('leads_ingested', 0)} leads")
            elif source_type == "directory":
                if CELERY_AVAILABLE:
                    task = scrape_directory.delay(target, {})
                    console.print(f"  Queued {target} → task {task.id}")
                else:
                    result = scrape_directory(target, {})
                    console.print(f"  {target}: {result.get('leads_ingested', 0)} leads")
            else:
                if CELERY_AVAILABLE:
                    task = scrape_corporate_website.delay(target)
                    console.print(f"  Queued {target} → task {task.id}")
                else:
                    result = scrape_corporate_website(target)
                    console.print(f"  {target}: {result.get('leads_ingested', 0)} leads")
        except Exception as exc:
            console.print(f"  [red]Error for {target}: {exc}[/red]")

    console.print("[green]Batch submitted.[/green]")


# ---------------------------------------------------------------------------
# Phase 3 commands
# ---------------------------------------------------------------------------


@app.command()
def enrich(
    lead_id: str = typer.Argument(..., help="Lead ID to enrich"),
    async_mode: bool = typer.Option(
        True, "--async/--sync", help="Queue via Celery (async) or run directly (sync)"
    ),
):
    """Enrich a lead with data from Apollo.io and Hunter.io."""
    from src.infrastructure.task_queue.tasks import enrich_lead, CELERY_AVAILABLE

    console.print(f"[cyan]Enriching lead: {lead_id}[/cyan]")

    use_celery = async_mode and CELERY_AVAILABLE
    if use_celery:
        task = enrich_lead.delay(lead_id)
        console.print(f"[green]Queued enrichment (task_id={task.id})[/green]")
    else:
        result = enrich_lead(lead_id)
        status = result.get("enrichment_status", "unknown")
        console.print(f"[green]Enriched: status={status}[/green]")


@app.command()
def credits():
    """Show API credit usage for the current month."""
    import asyncio
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.enrichment.credit_manager import CreditManager

    session = SessionLocal()
    try:
        mgr = CreditManager(session)
        summary = asyncio.run(mgr.get_usage_summary())

        table = Table(title="API Credit Usage (current month)")
        table.add_column("Provider")
        table.add_column("Month")
        table.add_column("Used", justify="right")
        table.add_column("Budget", justify="right")
        table.add_column("Remaining", justify="right")

        for provider, data in summary.items():
            table.add_row(
                provider,
                data["month"],
                str(data["used"]),
                str(data["budget"]),
                str(data["remaining"]),
            )
        console.print(table)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Phase 4 commands
# ---------------------------------------------------------------------------


@app.command()
def campaign_create(
    name: str = typer.Argument(..., help="Campaign name"),
    template: str = typer.Option("initial_outreach", "--template", help="Template ID for step 1"),
):
    """Create a new outreach campaign with a default sequence."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_campaign_repository import SqlCampaignRepository
    from src.application.use_cases.create_campaign import CreateCampaign
    from src.application.schemas.campaign_schemas import CampaignCreateDTO, SequenceStepCreateDTO

    session = SessionLocal()
    try:
        repo = SqlCampaignRepository(session)
        dto = CampaignCreateDTO(
            name=name,
            sequence_steps=[
                SequenceStepCreateDTO(step_number=1, channel="email", template_id=template, delay_days=0),
                SequenceStepCreateDTO(step_number=2, channel="email", template_id="follow_up_1", delay_days=3, condition="no_reply"),
                SequenceStepCreateDTO(step_number=3, channel="email", template_id="follow_up_2", delay_days=7, condition="no_reply"),
                SequenceStepCreateDTO(step_number=4, channel="email", template_id="breakup_email", delay_days=10, condition="no_reply"),
            ],
        )
        campaign = CreateCampaign(repo).execute(dto)
        session.commit()
        console.print(f"[green]Campaign created: {campaign.id} — '{campaign.name}'[/green]")
        console.print(f"[dim]{len(campaign.sequence_steps)} sequence steps added.[/dim]")
        console.print(f"[dim]Activate with: campaign-start {campaign.id}[/dim]")
    finally:
        session.close()


@app.command()
def campaign_start(campaign_id: str = typer.Argument(..., help="Campaign ID to activate")):
    """Activate a campaign (begin sending)."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_campaign_repository import SqlCampaignRepository
    from src.domain.enums import CampaignStatus

    session = SessionLocal()
    try:
        repo = SqlCampaignRepository(session)
        campaign = repo.find_by_id(campaign_id)
        if campaign is None:
            console.print(f"[red]Campaign not found: {campaign_id}[/red]")
            raise typer.Exit(1)
        campaign.status = CampaignStatus.ACTIVE
        repo.save(campaign)
        session.commit()
        console.print(f"[green]Campaign '{campaign.name}' is now ACTIVE.[/green]")
    finally:
        session.close()


@app.command()
def drafts():
    """Show pending AI-generated response drafts for your review."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_message_repository import SqlMessageRepository
    from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository

    session = SessionLocal()
    try:
        msg_repo = SqlMessageRepository(session)
        lead_repo = SqlLeadRepository(session)
        draft_list = msg_repo.find_drafts()

        if not draft_list:
            console.print("[green]No pending drafts — inbox is clear![/green]")
            return

        table = Table(title=f"Pending Drafts ({len(draft_list)})")
        table.add_column("Draft ID", style="dim", max_width=10)
        table.add_column("Lead")
        table.add_column("Channel")
        table.add_column("Subject")
        table.add_column("Preview", max_width=40)

        for draft in draft_list:
            lead = lead_repo.find_by_id(draft.lead_id)
            lead_name = lead.full_name() if lead else draft.lead_id[:8]
            channel = draft.channel.value if hasattr(draft.channel, "value") else str(draft.channel)
            preview = (draft.body[:40] + "...") if len(draft.body) > 40 else draft.body
            table.add_row(draft.id[:8], lead_name, channel, draft.subject or "—", preview)

        console.print(table)
        console.print("\n[dim]Approve: approve <draft-id>  |  Discard: POST /api/campaigns/messages/drafts/<id>[/dim]")
    finally:
        session.close()


@app.command()
def approve(
    draft_id: str = typer.Argument(..., help="Draft ID to approve"),
    edit: str = typer.Option(None, "--edit", help="Edited body text to use instead"),
):
    """Approve (and optionally edit) an AI draft response."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.repositories.sql_message_repository import SqlMessageRepository
    from src.domain.enums import MessageStatus

    session = SessionLocal()
    try:
        repo = SqlMessageRepository(session)
        # Find by prefix
        all_drafts = repo.find_drafts()
        matched = [d for d in all_drafts if d.id.startswith(draft_id)]
        if not matched:
            console.print(f"[red]Draft not found: {draft_id}[/red]")
            raise typer.Exit(1)
        draft = matched[0]
        if edit:
            draft.body = edit
        draft.status = MessageStatus.QUEUED
        repo.save(draft)
        session.commit()
        console.print(f"[green]Draft approved and queued for sending (id={draft.id[:8]})[/green]")
    finally:
        session.close()


@app.command()
def opt_out(email: str = typer.Argument(..., help="Email address to opt out")):
    """Manually add an email to the suppression list."""
    import asyncio
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.compliance.gdpr_manager import GDPRManager

    session = SessionLocal()
    try:
        gdpr = GDPRManager(session)
        asyncio.run(gdpr.add_to_suppression(email, reason="manual_cli", source="cli"))
        session.commit()
        console.print(f"[green]{email} added to suppression list.[/green]")
    finally:
        session.close()


@app.command()
def dsar_export(email: str = typer.Argument(..., help="Email to export data for")):
    """Export all data held for a person (GDPR/CCPA Article 15)."""
    import asyncio
    import json
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.compliance.gdpr_manager import GDPRManager

    session = SessionLocal()
    try:
        gdpr = GDPRManager(session)
        result = asyncio.run(gdpr.handle_dsar_export(email))
        session.commit()
        console.print(f"[cyan]DSAR Export for: {email}[/cyan]")
        console.print(json.dumps(result, indent=2, default=str))
    finally:
        session.close()


@app.command()
def run_pipeline(
    targets_file: str = typer.Argument(..., help="File with one URL/domain per line"),
    campaign_id: str = typer.Option(None, "--campaign-id", help="Optional campaign to queue outreach"),
):
    """Run the full pipeline: scrape → extract → enrich → outreach."""
    import asyncio
    from src.infrastructure.orchestration.dag_runner import DAGRunner
    from src.infrastructure.orchestration.workflows import build_pipeline_dag

    try:
        with open(targets_file) as f:
            targets = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except FileNotFoundError:
        console.print(f"[red]File not found: {targets_file}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Running pipeline for {len(targets)} targets...[/cyan]")

    async def run():
        dag = await build_pipeline_dag(targets=targets, campaign_id=campaign_id)
        runner = DAGRunner()
        context = {"targets": targets, "campaign_id": campaign_id}
        return await runner.run(dag, context=context)

    results = asyncio.run(run())

    table = Table(title="Pipeline Results")
    table.add_column("Step")
    table.add_column("Status")
    table.add_column("Duration (s)", justify="right")
    table.add_column("Error")

    for step_name, r in results.items():
        status_style = "green" if r["status"] == "success" else "red"
        table.add_row(
            step_name,
            f"[{status_style}]{r['status']}[/{status_style}]",
            str(r.get("duration_s", 0)),
            r.get("error") or "—",
        )
    console.print(table)


@app.command()
def dashboard():
    """Show pipeline stats in terminal."""
    from src.infrastructure.database.connection import SessionLocal
    from src.infrastructure.database.models import (
        LeadModel, CampaignModel, MessageModel, SuppressionListModel
    )
    import asyncio
    from src.infrastructure.enrichment.credit_manager import CreditManager

    session = SessionLocal()
    try:
        lead_count = session.query(LeadModel).count()
        campaign_count = session.query(CampaignModel).count()
        active_campaigns = session.query(CampaignModel).filter(CampaignModel.status == "active").count()
        sent_count = session.query(MessageModel).filter(MessageModel.status == "sent").count()
        draft_count = session.query(MessageModel).filter(MessageModel.status == "draft").count()
        suppression_count = session.query(SuppressionListModel).count()

        credit_mgr = CreditManager(session)
        credits = asyncio.run(credit_mgr.get_usage_summary())

        # Lead funnel
        funnel_table = Table(title="Lead Pipeline Funnel")
        funnel_table.add_column("Stage")
        funnel_table.add_column("Count", justify="right")
        from src.domain.enums import LeadStatus
        for status in LeadStatus:
            count = session.query(LeadModel).filter(LeadModel.status == status.value).count()
            funnel_table.add_row(status.value, str(count))
        funnel_table.add_row("[bold]TOTAL[/bold]", f"[bold]{lead_count}[/bold]")
        console.print(funnel_table)

        # Campaign stats
        camp_table = Table(title="Campaigns")
        camp_table.add_column("Metric")
        camp_table.add_column("Value", justify="right")
        camp_table.add_row("Total campaigns", str(campaign_count))
        camp_table.add_row("Active campaigns", str(active_campaigns))
        camp_table.add_row("Messages sent", str(sent_count))
        camp_table.add_row("Drafts pending review", str(draft_count))
        camp_table.add_row("Suppression list size", str(suppression_count))
        console.print(camp_table)

        # Credit usage
        credit_table = Table(title="API Credit Usage (current month)")
        credit_table.add_column("Provider")
        credit_table.add_column("Used", justify="right")
        credit_table.add_column("Budget", justify="right")
        credit_table.add_column("Remaining", justify="right")
        for provider, data in credits.items():
            credit_table.add_row(
                provider,
                str(data["used"]),
                str(data["budget"]),
                str(data["remaining"]),
            )
        console.print(credit_table)

    finally:
        session.close()


@app.command()
def seed_knowledge(
    knowledge_dir: str = typer.Option("./data/knowledge_base", "--dir", help="Knowledge base directory")
):
    """Seed the RAG knowledge base from ./data/knowledge_base/ files."""
    from src.infrastructure.ai_agents.rag_store import RAGStore

    console.print(f"[cyan]Seeding knowledge base from {knowledge_dir}...[/cyan]")
    store = RAGStore()
    count = store.seed_from_directory(knowledge_dir)
    console.print(f"[green]Seeded {count} documents into RAG store.[/green]")


if __name__ == "__main__":
    app()
