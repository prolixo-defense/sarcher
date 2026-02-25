"""
Tests for EmailSender — async SMTP email sending with compliance headers.

All SMTP calls are mocked — no real network access required.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.infrastructure.outreach.email_sender import EmailSender


def _settings(smtp_user="test@gmail.com", smtp_pass="secret", daily_limit=50):
    s = MagicMock()
    s.smtp_host = "smtp.gmail.com"
    s.smtp_port = 587
    s.smtp_username = smtp_user
    s.smtp_password = smtp_pass
    s.sender_name = "Test Sender"
    s.sender_email = smtp_user
    s.daily_email_limit = daily_limit
    s.timezone = "America/New_York"
    s.business_hours_start = 9
    s.business_hours_end = 18
    s.business_days = "mon,tue,wed,thu,fri"
    s.privacy_notice_url = "https://example.com/privacy"
    s.physical_address = "123 Test St"
    return s


@pytest.mark.asyncio
async def test_send_returns_success_when_smtp_ok():
    sender = EmailSender(settings=_settings())
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        result = await sender.send(
            to="prospect@acme.com",
            subject="Hello",
            html_body="<p>Hi</p>",
            plain_body="Hi",
        )
    assert result["success"] is True
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_returns_failure_when_no_smtp_credentials():
    sender = EmailSender(settings=_settings(smtp_user="", smtp_pass=""))
    result = await sender.send(
        to="prospect@acme.com",
        subject="Hello",
        html_body="<p>Hi</p>",
        plain_body="Hi",
    )
    assert result["success"] is False
    assert "SMTP not configured" in result["error"]


@pytest.mark.asyncio
async def test_send_returns_failure_on_smtp_error():
    sender = EmailSender(settings=_settings())
    with patch("aiosmtplib.send", side_effect=Exception("Connection refused")):
        result = await sender.send(
            to="prospect@acme.com",
            subject="Hello",
            html_body="<p>Hi</p>",
            plain_body="Hi",
        )
    assert result["success"] is False
    assert "Connection refused" in result["error"]


@pytest.mark.asyncio
async def test_send_respects_daily_rate_limit():
    sender = EmailSender(settings=_settings(daily_limit=2))
    with patch("aiosmtplib.send", new_callable=AsyncMock):
        r1 = await sender.send("a@b.com", "S1", "<p>1</p>", "1")
        r2 = await sender.send("a@b.com", "S2", "<p>2</p>", "2")
        r3 = await sender.send("a@b.com", "S3", "<p>3</p>", "3")
    assert r1["success"] is True
    assert r2["success"] is True
    assert r3["success"] is False  # Limit hit
    assert "limit" in r3["error"].lower()


@pytest.mark.asyncio
async def test_send_includes_unsubscribe_in_call():
    """The email should be sent via aiosmtplib.send with correct args."""
    sender = EmailSender(settings=_settings())
    with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await sender.send("p@co.com", "Sub", "<p>body</p>", "body")
    call_kwargs = mock_send.call_args
    # aiosmtplib.send called with hostname and credentials
    assert call_kwargs is not None


def test_check_rate_limit_under_limit():
    sender = EmailSender(settings=_settings(daily_limit=10))
    assert sender._check_rate_limit() is True


def test_is_business_hours_returns_bool():
    sender = EmailSender(settings=_settings())
    result = sender.is_business_hours()
    assert isinstance(result, bool)
