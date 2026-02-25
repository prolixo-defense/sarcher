import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.infrastructure.database.connection import Base
from src.infrastructure.database.repositories.sql_lead_repository import SqlLeadRepository
from src.domain.entities.lead import Lead
from src.domain.enums import DataSource, LeadStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def repo(session):
    return SqlLeadRepository(session)


def make_lead(**kwargs):
    defaults = dict(
        first_name="John",
        last_name="Doe",
        email="john@example.com",
        company_domain="example.com",
        source=DataSource.MANUAL,
    )
    defaults.update(kwargs)
    return Lead(**defaults)


class TestLeadRepositoryCRUD:
    def test_save_and_find_by_id(self, repo):
        lead = make_lead()
        saved = repo.save(lead)
        found = repo.find_by_id(lead.id)
        assert found is not None
        assert found.id == lead.id
        assert found.email == "john@example.com"

    def test_find_by_email(self, repo):
        lead = make_lead(email="unique@test.com")
        repo.save(lead)
        found = repo.find_by_email("unique@test.com")
        assert found is not None
        assert found.id == lead.id

    def test_find_by_email_not_found(self, repo):
        assert repo.find_by_email("nobody@nowhere.com") is None

    def test_find_by_domain(self, repo):
        repo.save(make_lead(company_domain="acme.com", email="a@acme.com"))
        repo.save(make_lead(company_domain="acme.com", email="b@acme.com"))
        repo.save(make_lead(company_domain="other.com", email="c@other.com"))
        results = repo.find_by_domain("acme.com")
        assert len(results) == 2

    def test_delete(self, repo):
        lead = make_lead()
        repo.save(lead)
        assert repo.find_by_id(lead.id) is not None
        deleted = repo.delete(lead.id)
        assert deleted is True
        assert repo.find_by_id(lead.id) is None

    def test_delete_nonexistent(self, repo):
        assert repo.delete("nonexistent-id") is False

    def test_count(self, repo):
        repo.save(make_lead(email="a@x.com"))
        repo.save(make_lead(email="b@x.com", status=LeadStatus.ENRICHED))
        assert repo.count({}) == 2
        assert repo.count({"status": "enriched"}) == 1

    def test_search_with_keyword(self, repo):
        repo.save(make_lead(first_name="Alice", email="alice@co.com"))
        repo.save(make_lead(first_name="Bob", email="bob@co.com"))
        results = repo.search({"keyword": "alice"}, limit=10, offset=0)
        assert len(results) == 1
        assert results[0].first_name == "Alice"

    def test_upsert_new_lead(self, repo):
        lead = make_lead(email="new@test.com")
        result = repo.upsert(lead)
        assert repo.count({}) == 1
        assert result.id == lead.id

    def test_upsert_existing_by_email(self, repo):
        lead = make_lead(email="dup@test.com")
        repo.save(lead)
        lead2 = make_lead(email="dup@test.com", first_name="Updated")
        repo.upsert(lead2)
        assert repo.count({}) == 1


class TestDeleteExpired:
    def test_deletes_expired_leads(self, repo, session):
        past = datetime.now(timezone.utc) - timedelta(days=1)
        future = datetime.now(timezone.utc) + timedelta(days=30)
        repo.save(make_lead(email="expired@x.com", expires_at=past))
        repo.save(make_lead(email="fresh@x.com", expires_at=future))
        session.commit()

        count = repo.delete_expired()
        assert count == 1
        assert repo.find_by_email("expired@x.com") is None
        assert repo.find_by_email("fresh@x.com") is not None

    def test_no_expired_leads(self, repo, session):
        future = datetime.now(timezone.utc) + timedelta(days=30)
        repo.save(make_lead(expires_at=future))
        session.commit()
        count = repo.delete_expired()
        assert count == 0
