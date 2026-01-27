"""Payroll tools for Xero MCP server."""

from typing import Any, TYPE_CHECKING

from mcp.types import Tool

from ..xero import XeroClient

if TYPE_CHECKING:
    from ..server import XeroMCPServer

PAYROLL_TOOLS = [
    Tool(
        name="xero_list_payruns",
        description="List pay runs from Xero Payroll AU with optional filtering by status.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by pay run status",
                    "enum": ["DRAFT", "POSTED"],
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination. Default: 1",
                    "default": 1,
                    "minimum": 1,
                },
                "profile": {
                    "type": "string",
                    "description": "Xero profile to use (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_get_payrun",
        description="Get detailed information about a specific pay run by its ID, including all payslips.",
        inputSchema={
            "type": "object",
            "properties": {
                "payrun_id": {
                    "type": "string",
                    "description": "The Xero pay run ID (UUID format)",
                },
                "profile": {
                    "type": "string",
                    "description": "Xero profile to use (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": ["payrun_id"],
        },
    ),
    Tool(
        name="xero_list_payroll_employees",
        description="List payroll employees from Xero Payroll AU.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by employee status",
                    "enum": ["ACTIVE", "TERMINATED"],
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination. Default: 1",
                    "default": 1,
                    "minimum": 1,
                },
                "profile": {
                    "type": "string",
                    "description": "Xero profile to use (e.g., 'SP', 'SM'). Defaults to active profile.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_quarterly_wages_report",
        description="Generate a quarterly wages report for Australian financial year quarters. Returns a markdown table with gross wages, allowances, OTE (Ordinary Time Earnings), superannuation, and super percentage. Super % is calculated on OTE (excluding per diem allowances). Pay runs are filtered by payment date. Can run across all connected profiles.",
        inputSchema={
            "type": "object",
            "properties": {
                "fiscal_year": {
                    "type": "string",
                    "description": "Australian fiscal year (e.g., 'FY21' for July 2020 - June 2021, 'FY25' for July 2024 - June 2025)",
                },
                "quarter": {
                    "type": "integer",
                    "description": "Quarter number (1-4). Q1=Jul-Sep, Q2=Oct-Dec, Q3=Jan-Mar, Q4=Apr-Jun",
                    "minimum": 1,
                    "maximum": 4,
                },
                "profile": {
                    "type": "string",
                    "description": "Xero profile to use (e.g., 'SP', 'SM'). Defaults to active profile. Use 'ALL' to run across all connected profiles.",
                },
            },
            "required": ["fiscal_year", "quarter"],
        },
    ),
]


def _get_quarter_dates(fiscal_year: str, quarter: int) -> tuple[str, str]:
    """Calculate start and end dates for an Australian FY quarter.

    Australian FY runs July 1 to June 30.
    FY21 = July 2020 to June 2021

    Args:
        fiscal_year: Fiscal year string (e.g., "FY21", "FY25")
        quarter: Quarter number (1-4)

    Returns:
        Tuple of (start_date, end_date) in YYYY-MM-DD format
    """
    # Parse fiscal year - FY21 means the year ending June 2021
    fy_num = int(fiscal_year.upper().replace("FY", ""))
    # Convert to 4-digit year (handles both FY21 and FY2021 formats)
    if fy_num < 100:
        fy_end_year = 2000 + fy_num
    else:
        fy_end_year = fy_num

    fy_start_year = fy_end_year - 1

    # Quarter date ranges for Australian FY
    quarter_ranges = {
        1: (f"{fy_start_year}-07-01", f"{fy_start_year}-09-30"),  # Jul-Sep
        2: (f"{fy_start_year}-10-01", f"{fy_start_year}-12-31"),  # Oct-Dec
        3: (f"{fy_end_year}-01-01", f"{fy_end_year}-03-31"),      # Jan-Mar
        4: (f"{fy_end_year}-04-01", f"{fy_end_year}-06-30"),      # Apr-Jun
    }

    return quarter_ranges[quarter]


async def _fetch_all_payruns(client: XeroClient, status: str | None = None) -> list[dict[str, Any]]:
    """Fetch all pay runs across all pages.

    Args:
        client: Xero API client
        status: Optional status filter

    Returns:
        List of all pay runs
    """
    all_payruns = []
    page = 1

    while True:
        payruns = await client.list_payruns(status=status, page=page)
        if not payruns:
            break
        all_payruns.extend(payruns)
        if len(payruns) < 100:  # Less than full page means we've got all
            break
        page += 1

    return all_payruns


async def _build_employee_lookup(client: XeroClient) -> dict[str, str]:
    """Build a lookup of employee ID to name.

    Args:
        client: Xero API client

    Returns:
        Dictionary mapping EmployeeID to full name
    """
    lookup = {}
    page = 1

    while True:
        employees = await client.list_payroll_employees(page=page)
        if not employees:
            break
        for emp in employees:
            emp_id = emp.get("EmployeeID", "")
            first = emp.get("FirstName", "")
            last = emp.get("LastName", "")
            lookup[emp_id] = f"{first} {last}".strip()
        if len(employees) < 100:
            break
        page += 1

    return lookup


async def _build_earnings_rate_categories(client: XeroClient) -> tuple[set[str], set[str]]:
    """Build sets of earnings rate IDs for allowances and overtime.

    Args:
        client: Xero API client

    Returns:
        Tuple of (allowance_ids, overtime_ids)
    """
    response = await client._payroll_request("GET", "PayItems")
    earnings_rates = response.get("PayItems", {}).get("EarningsRates", [])

    allowance_ids = set()
    overtime_ids = set()

    for er in earnings_rates:
        name = er.get("Name", "").lower()
        earnings_type = er.get("EarningsType", "")
        rate_id = er.get("EarningsRateID", "")

        # Identify allowances and per diems (not subject to super)
        if earnings_type == "ALLOWANCE" or "per diem" in name or "allowance" in name:
            allowance_ids.add(rate_id)
        # Identify overtime earnings
        elif earnings_type == "OVERTIME" or "overtime" in name or "over time" in name or "ot " in name:
            overtime_ids.add(rate_id)

    return allowance_ids, overtime_ids


async def _get_payslip_earnings_breakdown(
    client: XeroClient,
    payslip_id: str,
    allowance_rate_ids: set[str],
    overtime_rate_ids: set[str],
) -> tuple[float, float]:
    """Get allowances and overtime from a detailed payslip.

    Args:
        client: Xero API client
        payslip_id: Payslip ID to fetch
        allowance_rate_ids: Set of earnings rate IDs that are allowances
        overtime_rate_ids: Set of earnings rate IDs that are overtime

    Returns:
        Tuple of (total_allowances, total_overtime)
    """
    response = await client._payroll_request("GET", f"Payslip/{payslip_id}")
    payslip = response.get("Payslip", {})

    total_allowances = 0.0
    total_overtime = 0.0

    for el in payslip.get("EarningsLines", []):
        rate_id = el.get("EarningsRateID", "")
        units = float(el.get("NumberOfUnits", 0) or 0)
        rate = float(el.get("RatePerUnit", 0) or 0)
        fixed = float(el.get("FixedAmount", 0) or 0)
        amount = fixed if fixed else (units * rate)

        if rate_id in allowance_rate_ids:
            total_allowances += amount
        elif rate_id in overtime_rate_ids:
            total_overtime += amount

    return total_allowances, total_overtime


async def _run_quarterly_report_single(
    client: XeroClient,
    profile: str,
    fiscal_year: str,
    quarter: int,
) -> dict[str, Any]:
    """Run quarterly wages report for a single profile.

    Args:
        client: Xero API client
        profile: Profile name
        fiscal_year: Fiscal year (e.g., "FY25")
        quarter: Quarter number (1-4)

    Returns:
        Report data for this profile
    """
    import re
    from datetime import datetime, timezone

    start_date, end_date = _get_quarter_dates(fiscal_year, quarter)

    # Fetch all POSTED pay runs
    all_payruns = await _fetch_all_payruns(client, status="POSTED")

    # Filter pay runs within the date range based on PaymentDate
    filtered_payruns = []
    for pr in all_payruns:
        payment_date = pr.get("PaymentDate", "")
        if payment_date:
            match = re.search(r"/Date\((\d+)", payment_date)
            if match:
                timestamp_ms = int(match.group(1))
                pr_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                pr_date_str = pr_date.strftime("%Y-%m-%d")
                if start_date <= pr_date_str <= end_date:
                    filtered_payruns.append(pr)

    if not filtered_payruns:
        return {
            "profile": profile,
            "employee_count": 0,
            "total_wages": 0,
            "total_allowances": 0,
            "total_ote": 0,
            "total_overtime": 0,
            "total_tax": 0,
            "total_super": 0,
            "employees": [],
        }

    # Build lookups
    employee_lookup = await _build_employee_lookup(client)
    allowance_rate_ids, overtime_rate_ids = await _build_earnings_rate_categories(client)

    # Aggregate wages, allowances, overtime, tax and super by employee
    employee_data: dict[str, dict[str, float]] = {}
    total_allowances = 0.0
    total_overtime = 0.0

    for pr in filtered_payruns:
        full_payrun = await client.get_payrun(pr["PayRunID"])
        for payslip in full_payrun.get("Payslips", []):
            emp_id = payslip.get("EmployeeID", "")
            payslip_id = payslip.get("PayslipID", "")
            wages = float(payslip.get("Wages", 0) or 0)
            tax_amt = float(payslip.get("Tax", 0) or 0)
            super_amt = float(payslip.get("Super", 0) or 0)

            allowances, overtime = await _get_payslip_earnings_breakdown(
                client, payslip_id, allowance_rate_ids, overtime_rate_ids
            )
            total_allowances += allowances
            total_overtime += overtime

            emp_name = employee_lookup.get(emp_id)
            if not emp_name:
                first_name = payslip.get("FirstName", "")
                last_name = payslip.get("LastName", "")
                emp_name = f"{first_name} {last_name}".strip() or emp_id

            if emp_name in employee_data:
                employee_data[emp_name]["wages"] += wages
                employee_data[emp_name]["allowances"] += allowances
                employee_data[emp_name]["overtime"] += overtime
                employee_data[emp_name]["tax"] += tax_amt
                employee_data[emp_name]["super"] += super_amt
            else:
                employee_data[emp_name] = {"wages": wages, "allowances": allowances, "overtime": overtime, "tax": tax_amt, "super": super_amt}

    total_wages = sum(data["wages"] for data in employee_data.values())
    total_tax = sum(data["tax"] for data in employee_data.values())
    total_super = sum(data["super"] for data in employee_data.values())
    total_ote = total_wages - total_allowances - total_overtime

    sorted_employees = sorted(employee_data.items(), key=lambda x: x[0])

    return {
        "profile": profile,
        "employee_count": len(sorted_employees),
        "total_wages": total_wages,
        "total_allowances": total_allowances,
        "total_ote": total_ote,
        "total_overtime": total_overtime,
        "total_tax": total_tax,
        "total_super": total_super,
        "employees": [
            {
                "name": name,
                "wages": data["wages"],
                "allowances": data["allowances"],
                "ote": data["wages"] - data["allowances"] - data["overtime"],
                "overtime": data["overtime"],
                "tax": data["tax"],
                "super": data["super"],
            }
            for name, data in sorted_employees
        ],
    }


def _save_quarterly_report_toml(
    profile: str,
    fiscal_year: str,
    quarter: int,
    period_start: str,
    period_end: str,
    employees: list[dict[str, Any]],
    totals: dict[str, float],
    duration_seconds: float | None = None,
) -> str:
    """Save quarterly wages report to a TOML file.

    Args:
        profile: Xero profile name (e.g., 'SM', 'SP')
        fiscal_year: Fiscal year string (e.g., 'FY22')
        quarter: Quarter number (1-4)
        period_start: Start date (YYYY-MM-DD)
        period_end: End date (YYYY-MM-DD)
        employees: List of employee wage data
        totals: Total wages, allowances, OTE, overtime, tax, super
        duration_seconds: Time taken to generate the report

    Returns:
        Path to the saved TOML file
    """
    from datetime import datetime, timezone
    from pathlib import Path

    # Save to superannuation compliance folder
    output_dir = Path.home() / "SimpleMotion" / "90-Govern" / "92-Complicance" / "XX-Superannuation"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Format duration
    if duration_seconds:
        duration_mins = int(duration_seconds // 60)
        duration_secs = int(duration_seconds % 60)
        duration_str = f"{duration_mins}:{duration_secs:02d}"
    else:
        duration_str = "N/A"

    generated_at = datetime.now(timezone.utc)

    # Build TOML content
    fy_upper = fiscal_year.upper()
    lines = [
        f"# Quarterly Payroll Report: {fy_upper} Q{quarter}",
        f"# Profile: {profile}",
        f"# Generated: {generated_at.strftime('%d-%m-%Y @ %H:%M UTC')} over {duration_str}",
        "",
        "[report]",
        f'fiscal_year = "{fy_upper}"',
        f"quarter = {quarter}",
        f'profile = "{profile}"',
        f'period_start = "{period_start}"',
        f'period_end = "{period_end}"',
        f'generated_at = "{generated_at.isoformat()}"',
        f'generation_duration = "{duration_str}"',
        "",
        "[totals]",
        f"gross_wages = {totals['wages']:.2f}",
        f"allowances = {totals['allowances']:.2f}",
        f"ote = {totals['ote']:.2f}",
        f"overtime = {totals.get('overtime', 0.0):.2f}",
        f"tax = {totals.get('tax', 0.0):.2f}",
        f"superannuation = {totals['super']:.2f}",
        f"super_percentage = {totals['super_percentage']:.2f}",
        f"employee_count = {len(employees)}",
        "",
    ]

    # Add employee details
    for emp in employees:
        lines.append(f'[[employees]]')
        lines.append(f'name = "{emp["name"]}"')
        lines.append(f"gross_wages = {emp['wages']:.2f}")
        lines.append(f"allowances = {emp['allowances']:.2f}")
        lines.append(f"ote = {emp['ote']:.2f}")
        lines.append(f"overtime = {emp.get('overtime', 0.0):.2f}")
        lines.append(f"tax = {emp.get('tax', 0.0):.2f}")
        lines.append(f"superannuation = {emp['super']:.2f}")
        lines.append(f"super_percentage = {emp['super_percentage']:.2f}")
        lines.append("")

    toml_content = "\n".join(lines)

    # Save to file
    filename = f"{profile}-Payroll-{fy_upper}-Q{quarter}.toml"
    filepath = output_dir / filename
    filepath.write_text(toml_content)

    return str(filepath)


async def _run_quarterly_report_all_profiles(
    server: "XeroMCPServer",
    fiscal_year: str,
    quarter: int,
) -> dict[str, Any]:
    """Run quarterly wages report across all connected profiles.

    Args:
        server: Server instance with access to all profiles
        fiscal_year: Fiscal year (e.g., "FY25")
        quarter: Quarter number (1-4)

    Returns:
        Combined report data from all profiles
    """
    from ..auth.oauth import CREDENTIAL_PROFILES

    start_date, end_date = _get_quarter_dates(fiscal_year, quarter)

    # Format dates as DD-MM-YYYY
    def format_date(date_str: str) -> str:
        parts = date_str.split("-")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"

    start_date_fmt = format_date(start_date)
    end_date_fmt = format_date(end_date)

    profile_results = {}
    all_employees: dict[str, dict[str, float]] = {}
    grand_totals = {
        "wages": 0.0,
        "allowances": 0.0,
        "ote": 0.0,
        "super": 0.0,
    }

    # Run report for each connected profile
    for profile in CREDENTIAL_PROFILES:
        oauth = server.get_oauth(profile)
        tokens = await oauth.get_valid_tokens()
        if not tokens:
            profile_results[profile] = {"connected": False, "error": "Not authenticated"}
            continue

        client = server.get_client(profile)
        try:
            result = await _run_quarterly_report_single(client, profile, fiscal_year, quarter)
            profile_results[profile] = result

            # Aggregate into combined totals
            grand_totals["wages"] += result["total_wages"]
            grand_totals["allowances"] += result["total_allowances"]
            grand_totals["ote"] += result["total_ote"]
            grand_totals["super"] += result["total_super"]

            # Combine employees (prefix with profile for uniqueness)
            for emp in result["employees"]:
                key = f"{emp['name']} ({profile})"
                all_employees[key] = {
                    "wages": emp["wages"],
                    "allowances": emp["allowances"],
                    "ote": emp["ote"],
                    "super": emp["super"],
                    "profile": profile,
                }
        except Exception as e:
            profile_results[profile] = {"connected": True, "error": str(e)}

    # Calculate combined super percentage
    super_percentage = (grand_totals["super"] / grand_totals["ote"] * 100) if grand_totals["ote"] > 0 else 0

    # Build combined markdown report
    lines = [
        f"## Quarterly Wages Report: {fiscal_year}-Q{quarter} (All Profiles)",
        "",
        f"**Period:** {start_date_fmt} to {end_date_fmt}",
        "",
    ]

    # Add section for each profile
    for profile, result in profile_results.items():
        if "error" in result:
            lines.append(f"### {profile}: {result.get('error')}")
            lines.append("")
            continue

        if result["employee_count"] == 0:
            lines.append(f"### {profile}: No pay runs found")
            lines.append("")
            continue

        prof_super_pct = (result["total_super"] / result["total_ote"] * 100) if result["total_ote"] > 0 else 0

        lines.append(f"### {profile}")
        lines.append("")
        lines.append("| Employee | Gross Wages | Allowances | OTE | Super | Super % |")
        lines.append("|:---------|------------:|-----------:|----:|------:|--------:|")

        for emp in result["employees"]:
            emp_ote = emp["ote"]
            emp_super_pct = (emp["super"] / emp_ote * 100) if emp_ote > 0 else 0
            lines.append(
                f"| {emp['name']} | ${emp['wages']:,.2f} | ${emp['allowances']:,.2f} | "
                f"${emp_ote:,.2f} | ${emp['super']:,.2f} | {emp_super_pct:.2f}% |"
            )

        lines.append(
            f"| **Subtotal** | **${result['total_wages']:,.2f}** | **${result['total_allowances']:,.2f}** | "
            f"**${result['total_ote']:,.2f}** | **${result['total_super']:,.2f}** | **{prof_super_pct:.2f}%** |"
        )
        lines.append("")

    # Grand total section
    if grand_totals["wages"] > 0:
        lines.append("### Combined Total")
        lines.append("")
        lines.append("| | Gross Wages | Allowances | OTE | Super | Super % |")
        lines.append("|:---------|------------:|-----------:|----:|------:|--------:|")
        lines.append(
            f"| **Grand Total** | **${grand_totals['wages']:,.2f}** | **${grand_totals['allowances']:,.2f}** | "
            f"**${grand_totals['ote']:,.2f}** | **${grand_totals['super']:,.2f}** | **{super_percentage:.2f}%** |"
        )
        lines.append("")

    lines.append("*Super % calculated on OTE (excluding allowances)*")

    report = "\n".join(lines)

    return {
        "report": report,
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "period_start": start_date,
        "period_end": end_date,
        "profiles": profile_results,
        "grand_totals": {
            "total_wages": grand_totals["wages"],
            "total_allowances": grand_totals["allowances"],
            "total_ote": grand_totals["ote"],
            "total_super": grand_totals["super"],
            "super_percentage": super_percentage,
        },
    }


async def handle_payroll_tool(
    name: str,
    arguments: dict[str, Any],
    client: XeroClient,
    server: "XeroMCPServer | None" = None,
) -> dict[str, Any]:
    """Handle payroll tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        client: Xero API client for the current/specified profile
        server: Server instance for multi-profile operations

    Returns:
        Tool result
    """
    try:
        if name == "xero_list_payruns":
            payruns = await client.list_payruns(
                status=arguments.get("status"),
                page=arguments.get("page", 1),
            )
            return {
                "payruns": [
                    {
                        "id": pr.get("PayRunID"),
                        "payroll_calendar_id": pr.get("PayrollCalendarID"),
                        "pay_run_period_start_date": pr.get("PayRunPeriodStartDate"),
                        "pay_run_period_end_date": pr.get("PayRunPeriodEndDate"),
                        "payment_date": pr.get("PaymentDate"),
                        "status": pr.get("PayRunStatus"),
                        "wages": pr.get("Wages"),
                        "deductions": pr.get("Deductions"),
                        "tax": pr.get("Tax"),
                        "super": pr.get("Super"),
                        "net_pay": pr.get("NetPay"),
                    }
                    for pr in payruns
                ],
                "count": len(payruns),
            }

        elif name == "xero_get_payrun":
            payrun = await client.get_payrun(arguments["payrun_id"])
            return {
                "payrun": {
                    "id": payrun.get("PayRunID"),
                    "payroll_calendar_id": payrun.get("PayrollCalendarID"),
                    "pay_run_period_start_date": payrun.get("PayRunPeriodStartDate"),
                    "pay_run_period_end_date": payrun.get("PayRunPeriodEndDate"),
                    "payment_date": payrun.get("PaymentDate"),
                    "status": payrun.get("PayRunStatus"),
                    "wages": payrun.get("Wages"),
                    "deductions": payrun.get("Deductions"),
                    "tax": payrun.get("Tax"),
                    "super": payrun.get("Super"),
                    "net_pay": payrun.get("NetPay"),
                    "payslips": [
                        {
                            "payslip_id": ps.get("PayslipID"),
                            "employee_id": ps.get("EmployeeID"),
                            "first_name": ps.get("FirstName"),
                            "last_name": ps.get("LastName"),
                            "wages": ps.get("Wages"),
                            "deductions": ps.get("Deductions"),
                            "tax": ps.get("Tax"),
                            "super": ps.get("Super"),
                            "net_pay": ps.get("NetPay"),
                        }
                        for ps in payrun.get("Payslips", [])
                    ],
                }
            }

        elif name == "xero_list_payroll_employees":
            employees = await client.list_payroll_employees(
                page=arguments.get("page", 1),
                status=arguments.get("status"),
            )
            return {
                "employees": [
                    {
                        "id": emp.get("EmployeeID"),
                        "first_name": emp.get("FirstName"),
                        "last_name": emp.get("LastName"),
                        "status": emp.get("Status"),
                        "email": emp.get("Email"),
                        "date_of_birth": emp.get("DateOfBirth"),
                        "start_date": emp.get("StartDate"),
                        "termination_date": emp.get("TerminationDate"),
                    }
                    for emp in employees
                ],
                "count": len(employees),
            }

        elif name == "xero_quarterly_wages_report":
            from datetime import datetime, timezone
            import time

            report_start_time = time.time()

            fiscal_year = arguments["fiscal_year"]
            quarter = arguments["quarter"]
            profile_arg = arguments.get("profile", "").upper()

            # Check if running across all profiles
            if profile_arg == "ALL" and server:
                return await _run_quarterly_report_all_profiles(
                    server, fiscal_year, quarter
                )

            # Calculate date range for the quarter
            start_date, end_date = _get_quarter_dates(fiscal_year, quarter)

            # Fetch all POSTED pay runs
            all_payruns = await _fetch_all_payruns(client, status="POSTED")

            # Filter pay runs within the date range based on PaymentDate
            # PaymentDate is in format "/Date(timestamp)/"
            filtered_payruns = []
            for pr in all_payruns:
                # Parse the Xero date format: /Date(1234567890000+0000)/
                payment_date = pr.get("PaymentDate", "")
                if payment_date:
                    # Extract timestamp from /Date(...)/ format
                    import re
                    match = re.search(r"/Date\((\d+)", payment_date)
                    if match:
                        timestamp_ms = int(match.group(1))
                        pr_date = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                        pr_date_str = pr_date.strftime("%Y-%m-%d")

                        # Check if within quarter
                        if start_date <= pr_date_str <= end_date:
                            filtered_payruns.append(pr)

            if not filtered_payruns:
                return {
                    "report": f"## Quarterly Wages Report: {fiscal_year}-Q{quarter}\n\n**Period:** {start_date} to {end_date}\n\nNo pay runs found for this period.",
                    "fiscal_year": fiscal_year,
                    "quarter": quarter,
                    "period_start": start_date,
                    "period_end": end_date,
                    "employee_count": 0,
                    "total_wages": 0,
                    "total_allowances": 0,
                    "total_ote": 0,
                    "total_overtime": 0,
                    "total_tax": 0,
                    "total_super": 0,
                    "super_percentage": 0,
                }

            # Build lookups
            employee_lookup = await _build_employee_lookup(client)
            allowance_rate_ids, overtime_rate_ids = await _build_earnings_rate_categories(client)

            # Aggregate wages, allowances, overtime, tax and super by employee
            employee_data: dict[str, dict[str, float]] = {}
            total_allowances = 0.0
            total_overtime = 0.0

            for pr in filtered_payruns:
                # Fetch full payrun details to get payslips
                full_payrun = await client.get_payrun(pr["PayRunID"])
                for payslip in full_payrun.get("Payslips", []):
                    emp_id = payslip.get("EmployeeID", "")
                    payslip_id = payslip.get("PayslipID", "")
                    wages = float(payslip.get("Wages", 0) or 0)
                    tax_amt = float(payslip.get("Tax", 0) or 0)
                    super_amt = float(payslip.get("Super", 0) or 0)

                    # Get allowances and overtime from detailed payslip
                    allowances, overtime = await _get_payslip_earnings_breakdown(
                        client, payslip_id, allowance_rate_ids, overtime_rate_ids
                    )
                    total_allowances += allowances
                    total_overtime += overtime

                    # Get employee name from lookup or payslip
                    emp_name = employee_lookup.get(emp_id)
                    if not emp_name:
                        first = payslip.get("FirstName", "")
                        last = payslip.get("LastName", "")
                        emp_name = f"{first} {last}".strip() or emp_id

                    if emp_name in employee_data:
                        employee_data[emp_name]["wages"] += wages
                        employee_data[emp_name]["allowances"] += allowances
                        employee_data[emp_name]["overtime"] += overtime
                        employee_data[emp_name]["tax"] += tax_amt
                        employee_data[emp_name]["super"] += super_amt
                    else:
                        employee_data[emp_name] = {"wages": wages, "allowances": allowances, "overtime": overtime, "tax": tax_amt, "super": super_amt}

            # Calculate totals
            total_wages = sum(data["wages"] for data in employee_data.values())
            total_tax = sum(data["tax"] for data in employee_data.values())
            total_super = sum(data["super"] for data in employee_data.values())
            total_ote = total_wages - total_allowances - total_overtime  # OTE = wages minus allowances and overtime

            # Super percentage based on OTE (excluding allowances and overtime)
            super_percentage = (total_super / total_ote * 100) if total_ote > 0 else 0

            # Sort by name
            sorted_employees = sorted(employee_data.items(), key=lambda x: x[0])

            # Format dates as DD-MM-YYYY
            def format_date(date_str: str) -> str:
                parts = date_str.split("-")
                return f"{parts[2]}-{parts[1]}-{parts[0]}"

            start_date_fmt = format_date(start_date)
            end_date_fmt = format_date(end_date)

            # Build markdown table with right-aligned numbers
            lines = [
                f"## Quarterly Wages Report: {fiscal_year}-Q{quarter}",
                "",
                f"**Period:** {start_date_fmt} to {end_date_fmt}",
                "",
                "| Employee | Gross Wages | Allowances | Ordinary Time | Over Time | Taxes | Super | Super % |",
                "|:---------|------------:|-----------:|--------------:|----------:|------:|------:|--------:|",
            ]

            for emp_name, data in sorted_employees:
                emp_wages = data["wages"]
                emp_allowances = data["allowances"]
                emp_overtime = data["overtime"]
                emp_ote = emp_wages - emp_allowances - emp_overtime
                emp_tax = data["tax"]
                emp_super = data["super"]
                emp_super_pct = (emp_super / emp_ote * 100) if emp_ote > 0 else 0
                lines.append(f"| {emp_name} | ${emp_wages:,.2f} | ${emp_allowances:,.2f} | ${emp_ote:,.2f} | ${emp_overtime:,.2f} | ${emp_tax:,.2f} | ${emp_super:,.2f} | {emp_super_pct:.2f}% |")

            lines.append(f"| **Total** | **${total_wages:,.2f}** | **${total_allowances:,.2f}** | **${total_ote:,.2f}** | **${total_overtime:,.2f}** | **${total_tax:,.2f}** | **${total_super:,.2f}** | **{super_percentage:.2f}%** |")
            lines.append("")
            lines.append("*Super % calculated on Ordinary Time (excluding allowances and over time)*")

            # Build employees list for TOML
            employees_list = [
                {
                    "name": name,
                    "wages": data["wages"],
                    "allowances": data["allowances"],
                    "ote": data["wages"] - data["allowances"] - data["overtime"],
                    "overtime": data["overtime"],
                    "tax": data["tax"],
                    "super": data["super"],
                    "super_percentage": (data["super"] / (data["wages"] - data["allowances"] - data["overtime"]) * 100) if (data["wages"] - data["allowances"] - data["overtime"]) > 0 else 0,
                }
                for name, data in sorted_employees
            ]

            # Calculate duration
            report_end_time = time.time()
            duration_seconds = report_end_time - report_start_time
            duration_mins = int(duration_seconds // 60)
            duration_secs = int(duration_seconds % 60)
            generated_at = datetime.now(timezone.utc)
            generated_str = generated_at.strftime("%d-%m-%Y @ %H:%M UTC")
            duration_str = f"{duration_mins}:{duration_secs:02d}"

            # Save to TOML
            profile = profile_arg if profile_arg else client.oauth.profile
            filepath = _save_quarterly_report_toml(
                profile=profile,
                fiscal_year=fiscal_year,
                quarter=quarter,
                period_start=start_date,
                period_end=end_date,
                employees=employees_list,
                totals={
                    "wages": total_wages,
                    "allowances": total_allowances,
                    "ote": total_ote,
                    "overtime": total_overtime,
                    "tax": total_tax,
                    "super": total_super,
                    "super_percentage": super_percentage,
                },
                duration_seconds=duration_seconds,
            )

            # Add metadata to report
            lines.append("")
            lines.append(f"*Report generated on {generated_str} over {duration_str}*")
            lines.insert(3, f"**Saved to:** `{filepath}`")

            report = "\n".join(lines)

            return {
                "report": report,
                "fiscal_year": fiscal_year,
                "quarter": quarter,
                "period_start": start_date,
                "period_end": end_date,
                "file_path": filepath,
                "employee_count": len(sorted_employees),
                "total_wages": total_wages,
                "total_allowances": total_allowances,
                "total_ote": total_ote,
                "total_overtime": total_overtime,
                "total_tax": total_tax,
                "total_super": total_super,
                "super_percentage": super_percentage,
                "employees": employees_list,
            }

    except Exception as e:
        return {"error": str(e)}

    return {"error": f"Unknown payroll tool: {name}"}
