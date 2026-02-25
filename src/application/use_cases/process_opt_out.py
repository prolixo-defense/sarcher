"""Use case: process an unsubscribe/opt-out request."""


class ProcessOptOut:
    """Handles opt-out and DSAR requests via GDPRManager."""

    def __init__(self, gdpr_manager):
        self._gdpr = gdpr_manager

    async def execute(self, lead_id: str | None = None, email: str | None = None) -> dict:
        """
        Process an opt-out request.

        Either lead_id or email must be provided.
        Returns {success, lead_id, email, messages_cancelled}.
        """
        if lead_id:
            return await self._gdpr.process_opt_out(lead_id)

        if email:
            # Find lead by email
            return await self._gdpr.add_to_suppression(email, reason="opt_out", source="api") or {
                "success": True,
                "email": email,
                "lead_id": None,
                "messages_cancelled": 0,
            }

        return {"success": False, "error": "Either lead_id or email must be provided"}
