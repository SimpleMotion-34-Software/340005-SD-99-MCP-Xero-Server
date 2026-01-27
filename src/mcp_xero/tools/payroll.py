"""Payroll tools for Xero MCP server."""

from typing import Any

from mcp.types import Tool

from ..xero import XeroClient

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
            },
            "required": [],
        },
    ),
    Tool(
        name="xero_quarterly_wages_report",
        description="Generate a quarterly wages report for Australian financial year quarters. Returns a markdown table with employee names, gross wages, superannuation, and super percentage for the specified quarter. Pay runs are filtered by payment date.",
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


async def handle_payroll_tool(name: str, arguments: dict[str, Any], client: XeroClient) -> dict[str, Any]:
    """Handle payroll tool calls.

    Args:
        name: Tool name
        arguments: Tool arguments
        client: Xero API client

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
            fiscal_year = arguments["fiscal_year"]
            quarter = arguments["quarter"]

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
                        from datetime import datetime, timezone
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
                    "total_super": 0,
                    "super_percentage": 0,
                }

            # Calculate totals from pay run summaries (more efficient than fetching all payslips)
            total_wages = sum(float(pr.get("Wages", 0) or 0) for pr in filtered_payruns)
            total_super = sum(float(pr.get("Super", 0) or 0) for pr in filtered_payruns)
            super_percentage = (total_super / total_wages * 100) if total_wages > 0 else 0

            # Build employee name lookup
            employee_lookup = await _build_employee_lookup(client)

            # Aggregate wages and super by employee
            employee_data: dict[str, dict[str, float]] = {}

            for pr in filtered_payruns:
                # Fetch full payrun details to get payslips
                full_payrun = await client.get_payrun(pr["PayRunID"])
                for payslip in full_payrun.get("Payslips", []):
                    emp_id = payslip.get("EmployeeID", "")
                    wages = float(payslip.get("Wages", 0) or 0)
                    super_amt = float(payslip.get("Super", 0) or 0)

                    # Get employee name from lookup or payslip
                    emp_name = employee_lookup.get(emp_id)
                    if not emp_name:
                        first = payslip.get("FirstName", "")
                        last = payslip.get("LastName", "")
                        emp_name = f"{first} {last}".strip() or emp_id

                    if emp_name in employee_data:
                        employee_data[emp_name]["wages"] += wages
                        employee_data[emp_name]["super"] += super_amt
                    else:
                        employee_data[emp_name] = {"wages": wages, "super": super_amt}

            # Sort by name
            sorted_employees = sorted(employee_data.items(), key=lambda x: x[0])

            # Build markdown table
            lines = [
                f"## Quarterly Wages Report: {fiscal_year}-Q{quarter}",
                "",
                f"**Period:** {start_date} to {end_date}",
                "",
                "| Employee | Gross Wages | Super | Super % |",
                "|----------|-------------|-------|---------|",
            ]

            for emp_name, data in sorted_employees:
                emp_wages = data["wages"]
                emp_super = data["super"]
                emp_super_pct = (emp_super / emp_wages * 100) if emp_wages > 0 else 0
                lines.append(f"| {emp_name} | ${emp_wages:,.2f} | ${emp_super:,.2f} | {emp_super_pct:.2f}% |")

            lines.append(f"| **Total** | **${total_wages:,.2f}** | **${total_super:,.2f}** | **{super_percentage:.2f}%** |")

            report = "\n".join(lines)

            return {
                "report": report,
                "fiscal_year": fiscal_year,
                "quarter": quarter,
                "period_start": start_date,
                "period_end": end_date,
                "employee_count": len(sorted_employees),
                "total_wages": total_wages,
                "total_super": total_super,
                "super_percentage": super_percentage,
                "employees": [
                    {
                        "name": name,
                        "wages": data["wages"],
                        "super": data["super"],
                        "super_percentage": (data["super"] / data["wages"] * 100) if data["wages"] > 0 else 0,
                    }
                    for name, data in sorted_employees
                ],
            }

    except Exception as e:
        return {"error": str(e)}

    return {"error": f"Unknown payroll tool: {name}"}
