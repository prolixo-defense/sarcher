"""
Prompt templates for LLM-based data extraction.

Each template instructs the LLM on what to extract from a specific page type.
The {content} placeholder is filled at runtime with the cleaned Markdown.
"""

TEAM_PAGE_EXTRACTION = """
You are a precise data extraction agent. Extract all people and company information
from the following web page content.

Rules:
- Extract EVERY person mentioned with their name and role
- Only include information explicitly stated on the page — never guess or hallucinate
- If an email pattern is visible (e.g., first.last@company.com), record it exactly
- If you can infer the email format from visible emails, note the pattern but do NOT generate emails
- Confidence score: 1.0 = all fields explicitly stated, 0.5 = some inference needed, 0.3 = uncertain
- For seniority, categorize as: C-suite, VP, Director, Manager, Senior, Mid, Junior, Unknown
- Set page_type to "team"

Page content:
{content}
"""

LINKEDIN_PROFILE_EXTRACTION = """
You are extracting professional profile information from a LinkedIn-style page.

Rules:
- Extract the person's current role and company (most recent experience)
- Include all listed experience entries with company, title, and dates
- Extract education, skills, and certifications if present
- Do NOT include connection count, endorsement count, or other vanity metrics
- Confidence score based on completeness of the profile data
- Set page_type to "profile"

Page content:
{content}
"""

DIRECTORY_LISTING_EXTRACTION = """
You are extracting business listings from a directory page.

Rules:
- Extract each company/person as a separate entry
- Include all contact information shown (email, phone, address, website)
- Note the category or industry if listed
- If the page is paginated, only extract what is on this page
- Set page_type to "directory_listing"

Page content:
{content}
"""
