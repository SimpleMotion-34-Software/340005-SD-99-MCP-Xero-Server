"""Xero API client wrapper with rate limiting and error handling."""

import asyncio
import logging
from datetime import datetime
from typing import Any

import aiohttp

from ..auth import XeroOAuth

logger = logging.getLogger(__name__)

# Xero API base URLs
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"
XERO_PAYROLL_AU_BASE = "https://api.xero.com/payroll.xro/1.0"

# Rate limit configuration
RATE_LIMIT_REQUESTS = 50  # per minute (conservative, Xero allows 60)
RATE_LIMIT_WINDOW = 60  # seconds
MIN_REQUEST_INTERVAL = 1.2  # minimum seconds between requests to avoid bursts

# Default account codes for invoices
DEFAULT_SALES_ACCOUNT_CODE = "201"  # Sales - SP


def _ensure_line_item_account_code(
    line_items: list[dict[str, Any]], default_code: str = DEFAULT_SALES_ACCOUNT_CODE
) -> list[dict[str, Any]]:
    """Ensure all line items have an AccountCode.

    Args:
        line_items: List of line item dictionaries
        default_code: Default account code to use if not specified

    Returns:
        Line items with AccountCode ensured
    """
    processed = []
    for item in line_items:
        item_copy = dict(item)
        if "AccountCode" not in item_copy and "AccountID" not in item_copy:
            item_copy["AccountCode"] = default_code
        processed.append(item_copy)
    return processed


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

    def _parse_error_message(self, error_text: str) -> str:
        """Parse Xero API error into readable message.

        Args:
            error_text: Raw error response text

        Returns:
            Human-readable error message
        """
        import json
        try:
            error_data = json.loads(error_text)

            # Handle validation exceptions
            if error_data.get("Type") == "ValidationException":
                messages = []
                for element in error_data.get("Elements", []):
                    for err in element.get("ValidationErrors", []):
                        messages.append(err.get("Message", "Unknown validation error"))
                if messages:
                    return "Validation error: " + "; ".join(messages)

            # Handle general errors
            if "Message" in error_data:
                return f"Xero error: {error_data['Message']}"

            if "Detail" in error_data:
                return f"Xero error: {error_data['Detail']}"

        except json.JSONDecodeError:
            pass

        return f"Xero API error: {error_text[:200]}"

    async def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting."""
        now = datetime.now().timestamp()

        # Enforce minimum interval between requests to avoid bursts
        if self._request_times:
            last_request = self._request_times[-1]
            time_since_last = now - last_request
            if time_since_last < MIN_REQUEST_INTERVAL:
                wait_time = MIN_REQUEST_INTERVAL - time_since_last
                await asyncio.sleep(wait_time)
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
                        # Try to parse validation errors into readable format
                        user_message = self._parse_error_message(error_text)
                        raise XeroAPIError(
                            user_message,
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
            # Use Xero's searchTerm parameter for name searching
            params["searchTerm"] = search

        if not include_archived:
            params["where"] = 'ContactStatus!="ARCHIVED"'

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

    async def search_contacts(self, name: str) -> list[dict[str, Any]]:
        """Search contacts by name.

        Args:
            name: Name to search for (partial match)

        Returns:
            List of matching contacts
        """
        return await self.list_contacts(search=name)

    async def find_contact_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a single contact by exact or partial name match.

        Args:
            name: Contact name to find

        Returns:
            Contact if found, None otherwise
        """
        contacts = await self.search_contacts(name)
        if not contacts:
            return None
        # Return exact match if found, otherwise first partial match
        for contact in contacts:
            if contact.get("Name", "").lower() == name.lower():
                return contact
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
        contact_name: str | None = None,
        page: int = 1,
        date_from: str | None = None,
        date_to: str | None = None,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        """List quotes.

        Args:
            status: Filter by status (DRAFT, SENT, ACCEPTED, DECLINED, INVOICED)
            contact_id: Filter by contact ID
            contact_name: Filter by contact name (partial match, e.g., "Action" matches "Action Laser Pty Ltd")
            page: Page number
            date_from: Filter quotes from date (YYYY-MM-DD)
            date_to: Filter quotes to date (YYYY-MM-DD)
            where: Additional where clause (Xero filter syntax, e.g., 'Contact.Name.Contains("Action")')

        Returns:
            List of quotes
        """
        params: dict[str, Any] = {"page": page}
        where_clauses = []

        if status:
            where_clauses.append(f'Status=="{status}"')
        if contact_id:
            where_clauses.append(f'Contact.ContactID==Guid("{contact_id}")')
        if contact_name:
            # Use Contains for partial name matching
            where_clauses.append(f'Contact.Name.Contains("{contact_name}")')
        if date_from:
            where_clauses.append(f'Date>=DateTime({date_from.replace("-", ",")})')
        if date_to:
            where_clauses.append(f'Date<=DateTime({date_to.replace("-", ",")})')
        if where:
            where_clauses.append(where)

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
                - AccountCode: Account code (default "201" for Sales)
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
        # Ensure all line items have an account code
        processed_line_items = _ensure_line_item_account_code(line_items)

        quote: dict[str, Any] = {
            "Contact": {"ContactID": contact_id},
            "LineItems": processed_line_items,
            "CurrencyCode": currency_code,
            "Status": "DRAFT",
            "Date": date or datetime.now().strftime("%Y-%m-%d"),
        }
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update an existing quote.

        Fetches existing quote data and merges with provided updates to ensure
        required fields (Contact, Date) are preserved automatically.

        Note: Do NOT pass contact_id - it is automatically preserved from the
        existing quote. This method fetches the current quote data first.

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

        Raises:
            TypeError: If unexpected keyword arguments are passed
        """
        # Catch common mistakes with helpful error messages
        if kwargs:
            unexpected = list(kwargs.keys())
            hints = []
            if 'contact_id' in unexpected:
                hints.append("contact_id is auto-preserved from existing quote")
            if 'date' in unexpected:
                hints.append("date is auto-preserved from existing quote")
            hint_msg = f" ({'; '.join(hints)})" if hints else ""
            raise TypeError(
                f"update_quote() got unexpected keyword argument(s): {unexpected}{hint_msg}"
            )
        # Fetch existing quote to preserve required fields
        existing = await self.get_quote(quote_id)

        # Build update payload with required fields
        quote: dict[str, Any] = {
            "QuoteID": quote_id,
            "Contact": {"ContactID": existing["Contact"]["ContactID"]},
            "Date": existing.get("DateString", "")[:10] if existing.get("DateString") else datetime.now().strftime("%Y-%m-%d"),
        }

        # Only include fields that are being updated or need to be preserved
        if status:
            quote["Status"] = status

        if line_items is not None:
            # Ensure all line items have an account code
            quote["LineItems"] = _ensure_line_item_account_code(line_items)

        if expiry_date:
            quote["ExpiryDate"] = expiry_date

        if reference is not None:
            quote["Reference"] = reference

        if terms is not None:
            quote["Terms"] = terms

        if title is not None:
            quote["Title"] = title

        if summary is not None:
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
        contact_name: str | None = None,
        invoice_type: str = "ACCREC",  # Accounts Receivable (sales)
        page: int = 1,
        date_from: str | None = None,
        date_to: str | None = None,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        """List invoices.

        Args:
            status: Filter by status (DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED)
            contact_id: Filter by contact ID
            contact_name: Filter by contact name (partial match, e.g., "Action" matches "Action Laser Pty Ltd")
            invoice_type: ACCREC (sales) or ACCPAY (purchases)
            page: Page number
            date_from: Filter invoices from date (YYYY-MM-DD)
            date_to: Filter invoices to date (YYYY-MM-DD)
            where: Additional where clause (Xero filter syntax, e.g., 'Contact.Name.Contains("Action")')

        Returns:
            List of invoices
        """
        params: dict[str, Any] = {"page": page}
        where_clauses = [f'Type=="{invoice_type}"']

        if status:
            where_clauses.append(f'Status=="{status}"')
        if contact_id:
            where_clauses.append(f'Contact.ContactID==Guid("{contact_id}")')
        if contact_name:
            # Use Contains for partial name matching
            where_clauses.append(f'Contact.Name.Contains("{contact_name}")')
        if date_from:
            where_clauses.append(f'Date>=DateTime({date_from.replace("-", ",")})')
        if date_to:
            where_clauses.append(f'Date<=DateTime({date_to.replace("-", ",")})')
        if where:
            where_clauses.append(where)

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
                - AccountCode: Account code (default "201" for Sales)
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
        # Ensure all line items have an account code
        processed_line_items = _ensure_line_item_account_code(line_items)

        invoice: dict[str, Any] = {
            "Type": invoice_type,
            "Contact": {"ContactID": contact_id},
            "LineItems": processed_line_items,
            "CurrencyCode": currency_code,
            "Status": status,
            "Date": date or datetime.now().strftime("%Y-%m-%d"),
        }
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Update an existing invoice.

        Fetches existing invoice data and merges with provided updates to ensure
        required fields (Contact, Date, Type) are preserved automatically.

        Note: Do NOT pass contact_id - it is automatically preserved from the
        existing invoice. This method fetches the current invoice data first.

        Args:
            invoice_id: Invoice ID to update
            status: New status (DRAFT, SUBMITTED, AUTHORISED, VOIDED)
            line_items: Updated line items (replaces all existing)
            due_date: New due date
            reference: New reference

        Returns:
            Updated invoice

        Raises:
            TypeError: If unexpected keyword arguments are passed
        """
        # Catch common mistakes with helpful error messages
        if kwargs:
            unexpected = list(kwargs.keys())
            hints = []
            if 'contact_id' in unexpected:
                hints.append("contact_id is auto-preserved from existing invoice")
            if 'date' in unexpected:
                hints.append("date is auto-preserved from existing invoice")
            hint_msg = f" ({'; '.join(hints)})" if hints else ""
            raise TypeError(
                f"update_invoice() got unexpected keyword argument(s): {unexpected}{hint_msg}"
            )
        # Fetch existing invoice to preserve required fields
        existing = await self.get_invoice(invoice_id)

        # Build update payload with required fields
        invoice: dict[str, Any] = {
            "InvoiceID": invoice_id,
            "Type": existing.get("Type"),
            "Contact": {"ContactID": existing["Contact"]["ContactID"]},
            "Date": existing.get("DateString", "")[:10] if existing.get("DateString") else datetime.now().strftime("%Y-%m-%d"),
        }

        # Only include fields that are being updated
        if status:
            invoice["Status"] = status

        if line_items is not None:
            # Ensure all line items have an account code
            invoice["LineItems"] = _ensure_line_item_account_code(line_items)

        if due_date:
            invoice["DueDate"] = due_date

        if reference is not None:
            invoice["Reference"] = reference

        response = await self._request("POST", "Invoices", data={"Invoices": [invoice]})
        return response.get("Invoices", [{}])[0]

    async def void_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Void an invoice.

        The invoice must be in AUTHORISED or SUBMITTED status to be voided.
        DRAFT invoices should be deleted instead.

        Args:
            invoice_id: Invoice ID to void

        Returns:
            Voided invoice
        """
        return await self.update_invoice(invoice_id, status="VOIDED")

    async def delete_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Delete a draft invoice.

        Only DRAFT invoices can be deleted. Use void_invoice for
        AUTHORISED or SUBMITTED invoices.

        Args:
            invoice_id: Invoice ID to delete (must be DRAFT status)

        Returns:
            Deletion confirmation
        """
        # First verify it's a draft
        invoice = await self.get_invoice(invoice_id)
        if invoice.get("Status") != "DRAFT":
            raise XeroAPIError(
                f"Only DRAFT invoices can be deleted. Status is: {invoice.get('Status')}. Use void_invoice instead.",
                status_code=400,
            )

        # Update to DELETED status
        invoice_data: dict[str, Any] = {
            "InvoiceID": invoice_id,
            "Status": "DELETED",
        }
        response = await self._request("POST", "Invoices", data={"Invoices": [invoice_data]})
        return {"success": True, "message": f"Invoice {invoice.get('InvoiceNumber')} deleted"}

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

    # ==================== Purchase Orders ====================

    async def list_purchase_orders(
        self,
        status: str | None = None,
        contact_id: str | None = None,
        contact_name: str | None = None,
        page: int = 1,
        date_from: str | None = None,
        date_to: str | None = None,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        """List purchase orders.

        Args:
            status: Filter by status (DRAFT, SUBMITTED, AUTHORISED, BILLED, DELETED)
            contact_id: Filter by contact ID
            contact_name: Filter by contact name (partial match, e.g., "Newmark" matches "Newmark Systems Inc")
            page: Page number
            date_from: Filter POs from date (YYYY-MM-DD)
            date_to: Filter POs to date (YYYY-MM-DD)
            where: Additional where clause (Xero filter syntax, e.g., 'Contact.Name.Contains("Newmark")')

        Returns:
            List of purchase orders
        """
        params: dict[str, Any] = {"page": page}
        where_clauses = []

        if status:
            where_clauses.append(f'Status=="{status}"')
        if contact_id:
            where_clauses.append(f'Contact.ContactID==Guid("{contact_id}")')
        if contact_name:
            # Use Contains for partial name matching
            where_clauses.append(f'Contact.Name.Contains("{contact_name}")')
        if date_from:
            where_clauses.append(f'Date>=DateTime({date_from.replace("-", ",")})')
        if date_to:
            where_clauses.append(f'Date<=DateTime({date_to.replace("-", ",")})')
        if where:
            where_clauses.append(where)

        if where_clauses:
            params["where"] = " AND ".join(where_clauses)

        response = await self._request("GET", "PurchaseOrders", params=params)
        return response.get("PurchaseOrders", [])

    async def get_purchase_order(self, purchase_order_id: str) -> dict[str, Any]:
        """Get purchase order by ID.

        Args:
            purchase_order_id: Purchase order ID or number

        Returns:
            Purchase order details
        """
        response = await self._request("GET", f"PurchaseOrders/{purchase_order_id}")
        purchase_orders = response.get("PurchaseOrders", [])
        if not purchase_orders:
            raise XeroAPIError(f"Purchase order not found: {purchase_order_id}", status_code=404)
        return purchase_orders[0]

    async def create_purchase_order(
        self,
        contact_id: str,
        line_items: list[dict[str, Any]],
        date: str | None = None,
        delivery_date: str | None = None,
        purchase_order_number: str | None = None,
        reference: str | None = None,
        delivery_address: str | None = None,
        attention_to: str | None = None,
        telephone: str | None = None,
        delivery_instructions: str | None = None,
        currency_code: str = "AUD",
        status: str = "DRAFT",
    ) -> dict[str, Any]:
        """Create a new purchase order.

        Args:
            contact_id: Contact ID (supplier)
            line_items: List of line items, each with:
                - Description: Line item description
                - Quantity: Quantity (default 1)
                - UnitAmount: Price per unit
                - AccountCode: Account code (e.g., "300" for Purchases)
                - TaxType: Tax type (optional, e.g., "INPUT" for GST on expenses)
            date: PO date (YYYY-MM-DD), defaults to today
            delivery_date: Expected delivery date (YYYY-MM-DD)
            purchase_order_number: PO number (auto-generated if not provided)
            reference: Reference text (e.g., supplier quote number)
            delivery_address: Delivery address
            attention_to: Attention to name
            telephone: Contact telephone
            delivery_instructions: Special delivery instructions
            currency_code: Currency code (default AUD)
            status: Initial status (DRAFT or SUBMITTED)

        Returns:
            Created purchase order
        """
        purchase_order: dict[str, Any] = {
            "Contact": {"ContactID": contact_id},
            "LineItems": line_items,
            "CurrencyCode": currency_code,
            "Status": status,
            "Date": date or datetime.now().strftime("%Y-%m-%d"),
        }
        if delivery_date:
            purchase_order["DeliveryDate"] = delivery_date
        if purchase_order_number:
            purchase_order["PurchaseOrderNumber"] = purchase_order_number
        if reference:
            purchase_order["Reference"] = reference
        if delivery_address:
            purchase_order["DeliveryAddress"] = delivery_address
        if attention_to:
            purchase_order["AttentionTo"] = attention_to
        if telephone:
            purchase_order["Telephone"] = telephone
        if delivery_instructions:
            purchase_order["DeliveryInstructions"] = delivery_instructions

        response = await self._request("POST", "PurchaseOrders", data={"PurchaseOrders": [purchase_order]})
        return response.get("PurchaseOrders", [{}])[0]

    async def update_purchase_order(
        self,
        purchase_order_id: str,
        status: str | None = None,
        line_items: list[dict[str, Any]] | None = None,
        delivery_date: str | None = None,
        reference: str | None = None,
        delivery_address: str | None = None,
        attention_to: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing purchase order.

        Args:
            purchase_order_id: Purchase order ID to update
            status: New status (DRAFT, SUBMITTED, AUTHORISED, DELETED)
            line_items: Updated line items (replaces all existing)
            delivery_date: New delivery date
            reference: New reference
            delivery_address: New delivery address
            attention_to: New attention to name

        Returns:
            Updated purchase order
        """
        # Fetch existing PO to preserve required fields
        existing = await self.get_purchase_order(purchase_order_id)

        # Build update payload with required fields
        purchase_order: dict[str, Any] = {
            "PurchaseOrderID": purchase_order_id,
            "Contact": {"ContactID": existing["Contact"]["ContactID"]},
            "Date": existing.get("DateString", "")[:10] if existing.get("DateString") else datetime.now().strftime("%Y-%m-%d"),
        }

        if status:
            purchase_order["Status"] = status

        if line_items is not None:
            purchase_order["LineItems"] = line_items

        if delivery_date:
            purchase_order["DeliveryDate"] = delivery_date

        if reference is not None:
            purchase_order["Reference"] = reference

        if delivery_address is not None:
            purchase_order["DeliveryAddress"] = delivery_address

        if attention_to is not None:
            purchase_order["AttentionTo"] = attention_to

        response = await self._request("POST", "PurchaseOrders", data={"PurchaseOrders": [purchase_order]})
        return response.get("PurchaseOrders", [{}])[0]

    # ==================== Payroll AU ====================

    async def _payroll_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make authenticated request to Xero Payroll AU API.

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

        url = f"{XERO_PAYROLL_AU_BASE}/{endpoint}"
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
                        user_message = self._parse_error_message(error_text)
                        raise XeroAPIError(
                            user_message,
                            status_code=response.status,
                            details=error_text,
                        )

                    return await response.json()

            raise XeroAPIError("Max retries exceeded", status_code=429)

    async def list_payruns(
        self,
        status: str | None = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """List pay runs from Xero Payroll AU.

        Args:
            status: Filter by status (DRAFT, POSTED)
            page: Page number (100 results per page)

        Returns:
            List of pay runs
        """
        params: dict[str, Any] = {"page": page}

        if status:
            params["where"] = f'PayRunStatus=="{status}"'

        response = await self._payroll_request("GET", "PayRuns", params=params)
        return response.get("PayRuns", [])

    async def get_payrun(self, payrun_id: str) -> dict[str, Any]:
        """Get pay run by ID with full details including payslips.

        Args:
            payrun_id: Pay run ID

        Returns:
            Pay run details with payslips
        """
        response = await self._payroll_request("GET", f"PayRuns/{payrun_id}")
        payruns = response.get("PayRuns", [])
        if not payruns:
            raise XeroAPIError(f"Pay run not found: {payrun_id}", status_code=404)
        return payruns[0]

    async def list_payroll_employees(
        self,
        page: int = 1,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List payroll employees.

        Args:
            page: Page number (100 results per page)
            status: Filter by status (ACTIVE, TERMINATED)

        Returns:
            List of payroll employees
        """
        params: dict[str, Any] = {"page": page}

        if status:
            params["where"] = f'Status=="{status}"'

        response = await self._payroll_request("GET", "Employees", params=params)
        return response.get("Employees", [])
