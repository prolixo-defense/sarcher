from enum import Enum


class LeadStatus(str, Enum):
    RAW = "raw"                    # Just scraped, unverified
    ENRICHED = "enriched"          # Enrichment data attached
    VERIFIED = "verified"          # Email/phone verified
    CONTACTED = "contacted"        # Outreach initiated
    RESPONDED = "responded"        # Got a reply
    QUALIFIED = "qualified"        # Sales-qualified
    DISQUALIFIED = "disqualified"  # Not a fit
    OPTED_OUT = "opted_out"        # GDPR/CCPA opt-out


class DataSource(str, Enum):
    CORPORATE_WEBSITE = "corporate_website"
    LINKEDIN = "linkedin"
    BUSINESS_DIRECTORY = "business_directory"
    APOLLO = "apollo"
    HUNTER = "hunter"
    MANUAL = "manual"
    SAM_GOV = "sam_gov"
    JOB_POSTING = "job_posting"


class EnrichmentStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class Channel(str, Enum):
    EMAIL = "email"
    LINKEDIN_CONNECT = "linkedin_connect"
    LINKEDIN_MESSAGE = "linkedin_message"
    LINKEDIN_INMAIL = "linkedin_inmail"


class MessageDirection(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class MessageStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    REPLIED = "replied"
    DRAFT = "draft"
    DISCARDED = "discarded"
