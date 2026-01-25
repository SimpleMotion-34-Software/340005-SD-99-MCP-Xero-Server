"""Xero API client wrapper with rate limiting and error handling."""

import asyncio
import logging
from datetime import datetime
from typing import Any

import aiohttp

from ..auth import XeroOAuth

logger = logging.getLogger(__name__)

# Xero API base URL
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"

# Rate limit configuration
RATE_LIMIT_REQUESTS = 60  # per minute
RATE_LIMIT_WINDOW = 60  # seconds


class XeroAPIError(Exception):
    """Xero API error."""

    def __init__(self, message: str, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class XeroClient:
    """Wrapper around Xero API with rate limiting and automatic token refresh."""

    def __init__(self, oauth: XeroOAuth):
        """Initialize Xero client.

        Args:
            oauth: OAuth handler for authentication
        """
        self.oauth = oauth
        self._request_times: list[float] = []

    async def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting."""
        now = datetime.now().timestamp()

        # Remove old requests outside the window
        self._request_times = [t for t in self._request_times if now - t < RATE_LIMIT_WINDOW]

        # If at limit, wait
        if len(self._request_times) >= RATE_LIMIT_REQUESTS:
            wait_time = RATE_LIMIT_WINDOW - (now - self._request_times[0])
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time)

        self._request_times.append(now)

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make authenticated request to Xero API.

        Args:
            method: HTTP method
            endpoint: API endpoint (without base URL)
            data: Request body data
            params: Query parameters

        Returns:
            Response data

        Raises:
            XeroAPIError: If request fails
        """
        tokens = await self.oauth.get_valid_tokens()
        if not tokens:
            raise XeroAPIError("Not authenticated with Xero", status_code=401)

        await self._check_rate_limit()

        url = f"{XERO_API_BASE}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "xero-tenant-id": tokens.tenant_id or "",
            "Accept": "application/json",
        }

        if data:
            headers["Content-Type"] = "application/json"

        async with aiohttp.ClientSession() as session:
            for attempt in range(3):  # Retry up to 3 times
                async with session.request(
                    method,
                    url,
                    json=data,
                    params=params,
                    headers=headers,
                ) as response:
                    # Handle rate limiting
                    if response.status == 429:
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logger.warning(f"Rate limited, retrying after {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    # Handle other errors
                    if response.status >= 400:
                        error_text = await response.text()
                        raise XeroAPIError(
                            f"Xero API error: {error_text}",
                            status_code=response.status,
                            details=error_text,
                        )

                    return await response.json()

            raise XeroAPIError("Max retries exceeded", status_code=429)

    # ==================== Contacts ====================

    async def list_contacts(
        self,
        search: str | None = None,
        page: int = 1,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        """List contacts.

        Args:
            search: Search term for contact name
            page: Page number (100 results per page)
            include_archived: Include archived contacts

        Returns:
            List of contacts
        """
        params: dict[str, Any] = {"page": page}

        if search:
            params["where"] = f'Name.Contains("{search}")'

        if not include_archived:
            params["where"] = params.get("where", "") + " AND ContactStatus!=\"ARCHIVED\""
            params["where"] = params["where"].lstrip(" AND ")

        response = await self._request("GET", "Contacts", params=params)
        return response.get("Contacts", [])

    async def get_contact(self, contact_id: str) -> dict[str, Any]:
        """Get contact by ID.

        Args:
            contact_id: Contact ID or contact number

        Returns:
            Contact details
        """
        response = await self._request("GET", f"Contacts/{contact_id}")
        contacts = response.get("Contacts", [])
        if not contacts:
            raise XeroAPIError(f"Contact not found: {contact_id}", status_code=404)
        return contacts[0]

    async def create_contact(
        self,
        name: str,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        account_number: str | None = None,
    ) -> dict[str, Any]:
        """Create a new contact.

        Args:
            name: Contact/company name (required)
            email: Email address
            first_name: First name
            last_name: Last name
            phone: Phone number
            account_number: Account number

        Returns:
            Created contact
        """
        contact: dict[str, Any] = {"Name": name}

        if email:
            contact["EmailAddress"] = email
        if first_name:
            contact["FirstName"] = first_name
        if last_name:
            contact["LastName"] = last_name
        if phone:
            contact["Phones"] = [{"PhoneType": "DEFAULT", "PhoneNumber": phone}]
        if account_number:
            contact["AccountNumber"] = account_number

        response = await self._request("POST", "Contacts", data={"Contacts": [contact]})
        return response.get("Contacts", [{}])[0]

    # ==================== Quotes ====================

    async def list_quotes(
        self,
        status: str | None = None,
        contact_id: str | None = None,
        page: int = 1,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """List quotes.

        Args:
            status: Filter by status (DRAFT, SENT, ACCEPTED, DECLINED, INVOICED)
            contact_id: Filter by contact ID
            page: Page number
            date_from: Filter quotes from date (YYYY-MM-DD)
            date_to: Filter quotes to date (YYYY-MM-DD)

        Returns:
            List of quotes
        """
        params: dict[str, Any] = {"page": page}
        where_clauses = []

        if status:
            where_clauses.append(f'Status=="{status}"')
        if contact_id:
            where_clauses.append(f'Contact.ContactID==Guid("{contact_id}")')
        if date_from:
            where_clauses.append(f'Date>=DateTime({date_from.replace("-", ",")})')
        if date_to:
            where_clauses.append(f'Date<=DateTime({date_to.replace("-", ",")})')

        if where_clauses:
            params["where"] = " AND ".join(where_clauses)

        response = await self._request("GET", "Quotes", params=params)
        return response.get("Quotes", [])

    async def get_quote(self, quote_id: str) -> dict[str, Any]:
        """Get quote by ID.

        Args:
            quote_id: Quote ID

        Returns:
            Quote details
        """
        response = await self._request("GET", f"Quotes/{quote_id}")
        quotes = response.get("Quotes", [])
        if not quotes:
            raise XeroAPIError(f"Quote not found: {quote_id}", status_code=404)
        return quotes[0]

    async def create_quote(
        self,
        contact_id: str,
        line_items: list[dict[str, Any]],
        date: str | None = None,
        expiry_date: str | None = None,
        quote_number: str | None = None,
        reference: str | None = None,
        terms: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        currency_code: str = "AUD",
    ) -> dict[str, Any]:
        """Create a new quote.

        Args:
            contact_id: Contact ID
            line_items: List of line items, each with:
                - Description: Line item description
                - Quantity: Quantity (default 1)
                - UnitAmount: Price per unit
                - AccountCode: Account code (optional)
                - TaxType: Tax type (optional)
            date: Quote date (YYYY-MM-DD), defaults to today
            expiry_date: Expiry date (YYYY-MM-DD)
            quote_number: Quote number (auto-generated if not provided)
            reference: Reference text
            terms: Terms and conditions
            title: Quote title
            summary: Quote summary
            currency_code: Currency code (default AUD)

        Returns:
            Created quote
        """
        quote: dict[str, Any] = {
            "Contact": {"ContactID": contact_id},
            "LineItems": line_items,
            "CurrencyCode": currency_code,
            "Status": "DRAFT",
        }

        if date:
            quote["Date"] = date
        if expiry_date:
            quote["ExpiryDate"] = expiry_date
        if quote_number:
            quote["QuoteNumber"] = quote_number
        if reference:
            quote["Reference"] = reference
        if terms:
            quote["Terms"] = terms
        if title:
            quote["Title"] = title
        if summary:
            quote["Summary"] = summary

        response = await self._request("POST", "Quotes", data={"Quotes": [quote]})
        return response.get("Quotes", [{}])[0]

    async def update_quote(
        self,
        quote_id: str,
        status: str | None = None,
        line_items: list[dict[str, Any]] | None = None,
        expiry_date: str | None = None,
        reference: str | None = None,
        terms: str | None = None,
        title: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing quote.

        Args:
            quote_id: Quote ID to update
            status: New status (DRAFT, SENT, ACCEPTED, DECLINED)
            line_items: Updated line items (replaces all existing)
            expiry_date: New expiry date
            reference: New reference
            terms: New terms
            title: New title
            summary: New summary

        Returns:
            Updated quote
        """
        quote: dict[str, Any] = {"QuoteID": quote_id}

        if status:
            quote["Status"] = status
        if line_items:
            quote["LineItems"] = line_items
        if expiry_date:
            quote["ExpiryDate"] = expiry_date
        if reference:
            quote["Reference"] = reference
        if terms:
            quote["Terms"] = terms
        if title:
            quote["Title"] = title
        if summary:
            quote["Summary"] = summary

        response = await self._request("POST", "Quotes", data={"Quotes": [quote]})
        return response.get("Quotes", [{}])[0]

    async def send_quote(self, quote_id: str) -> dict[str, Any]:
        """Send quote via email.

        Note: This marks the quote as SENT. The actual email is sent by Xero
        to the contact's email address.

        Args:
            quote_id: Quote ID to send

        Returns:
            Updated quote
        """
        return await self.update_quote(quote_id, status="SENT")

    # ==================== Invoices ====================

    async def list_invoices(
        self,
        status: str | None = None,
        contact_id: str | None = None,
        invoice_type: str = "ACCREC",  # Accounts Receivable (sales)
        page: int = 1,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """List invoices.

        Args:
            status: Filter by status (DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED)
            contact_id: Filter by contact ID
            invoice_type: ACCREC (sales) or ACCPAY (purchases)
            page: Page number
            date_from: Filter invoices from date (YYYY-MM-DD)
            date_to: Filter invoices to date (YYYY-MM-DD)

        Returns:
            List of invoices
        """
        params: dict[str, Any] = {"page": page}
        where_clauses = [f'Type=="{invoice_type}"']

        if status:
            where_clauses.append(f'Status=="{status}"')
        if contact_id:
            where_clauses.append(f'Contact.ContactID==Guid("{contact_id}")')
        if date_from:
            where_clauses.append(f'Date>=DateTime({date_from.replace("-", ",")})')
        if date_to:
            where_clauses.append(f'Date<=DateTime({date_to.replace("-", ",")})')

        params["where"] = " AND ".join(where_clauses)

        response = await self._request("GET", "Invoices", params=params)
        return response.get("Invoices", [])

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Get invoice by ID.

        Args:
            invoice_id: Invoice ID or invoice number

        Returns:
            Invoice details
        """
        response = await self._request("GET", f"Invoices/{invoice_id}")
        invoices = response.get("Invoices", [])
        if not invoices:
            raise XeroAPIError(f"Invoice not found: {invoice_id}", status_code=404)
        return invoices[0]

    async def create_invoice(
        self,
        contact_id: str,
        line_items: list[dict[str, Any]],
        invoice_type: str = "ACCREC",
        date: str | None = None,
        due_date: str | None = None,
        invoice_number: str | None = None,
        reference: str | None = None,
        currency_code: str = "AUD",
        status: str = "DRAFT",
    ) -> dict[str, Any]:
        """Create a new invoice.

        Args:
            contact_id: Contact ID
            line_items: List of line items, each with:
                - Description: Line item description
                - Quantity: Quantity (default 1)
                - UnitAmount: Price per unit
                - AccountCode: Account code (e.g., "200" for sales)
                - TaxType: Tax type (optional)
            invoice_type: ACCREC (sales) or ACCPAY (purchases)
            date: Invoice date (YYYY-MM-DD), defaults to today
            due_date: Due date (YYYY-MM-DD)
            invoice_number: Invoice number (auto-generated if not provided)
            reference: Reference text
            currency_code: Currency code (default AUD)
            status: Initial status (DRAFT or SUBMITTED)

        Returns:
            Created invoice
        """
        invoice: dict[str, Any] = {
            "Type": invoice_type,
            "Contact": {"ContactID": contact_id},
            "LineItems": line_items,
            "CurrencyCode": currency_code,
            "Status": status,
        }

        if date:
            invoice["Date"] = date
        if due_date:
            invoice["DueDate"] = due_date
        if invoice_number:
            invoice["InvoiceNumber"] = invoice_number
        if reference:
            invoice["Reference"] = reference

        response = await self._request("POST", "Invoices", data={"Invoices": [invoice]})
        return response.get("Invoices", [{}])[0]

    async def update_invoice(
        self,
        invoice_id: str,
        status: str | None = None,
        line_items: list[dict[str, Any]] | None = None,
        due_date: str | None = None,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing invoice.

        Args:
            invoice_id: Invoice ID to update
            status: New status (DRAFT, SUBMITTED, AUTHORISED, VOIDED)
            line_items: Updated line items (replaces all existing)
            due_date: New due date
            reference: New reference

        Returns:
            Updated invoice
        """
        invoice: dict[str, Any] = {"InvoiceID": invoice_id}

        if status:
            invoice["Status"] = status
        if line_items:
            invoice["LineItems"] = line_items
        if due_date:
            invoice["DueDate"] = due_date
        if reference:
            invoice["Reference"] = reference

        response = await self._request("POST", "Invoices", data={"Invoices": [invoice]})
        return response.get("Invoices", [{}])[0]

    async def send_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Send invoice via email.

        The invoice must be in AUTHORISED status to be sent.

        Args:
            invoice_id: Invoice ID to send

        Returns:
            Email send status
        """
        response = await self._request("POST", f"Invoices/{invoice_id}/Email")
        return response

    async def convert_quote_to_invoice(self, quote_id: str) -> dict[str, Any]:
        """Convert an accepted quote to an invoice.

        Args:
            quote_id: Quote ID (must be in ACCEPTED status)

        Returns:
            Created invoice
        """
        # Get the quote details
        quote = await self.get_quote(quote_id)

        if quote.get("Status") != "ACCEPTED":
            raise XeroAPIError(
                f"Quote must be ACCEPTED to convert to invoice. Current status: {quote.get('Status')}",
                status_code=400,
            )

        # Create invoice from quote
        invoice = await self.create_invoice(
            contact_id=quote["Contact"]["ContactID"],
            line_items=quote["LineItems"],
            reference=f"Quote {quote.get('QuoteNumber', quote_id)}",
            currency_code=quote.get("CurrencyCode", "AUD"),
        )

        # Mark quote as invoiced
        await self.update_quote(quote_id, status="INVOICED")

        return invoice
