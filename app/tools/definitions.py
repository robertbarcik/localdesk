"""OpenAI-format tool definitions for the service desk agent."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_sla",
            "description": "Look up contractual SLA response and resolution times for a given customer tier and priority level.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_tier": {
                        "type": "string",
                        "enum": ["gold", "silver", "bronze"],
                        "description": "The customer's service tier.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                        "description": "The incident priority level.",
                    },
                },
                "required": ["customer_tier", "priority"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_incident",
            "description": "Create a new incident ticket in the system. Use this when a user reports an IT issue that needs tracking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Brief description of the incident.",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "high", "medium", "low"],
                        "description": "Priority level of the incident.",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["network", "hardware", "software", "access", "other"],
                        "description": "Category of the incident.",
                    },
                    "reporter_name": {
                        "type": "string",
                        "description": "Name of the person reporting the issue.",
                    },
                },
                "required": ["summary", "priority", "category", "reporter_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_asset",
            "description": "Look up hardware and software assets assigned to an employee by their employee ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "employee_id": {
                        "type": "string",
                        "description": "The employee's ID (e.g., EMP-001).",
                    },
                },
                "required": ["employee_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_ticket",
            "description": "Escalate an existing incident ticket. Updates its status to escalated and logs the reason.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "string",
                        "description": "The ticket ID to escalate (e.g., INC-00001).",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for escalation.",
                    },
                },
                "required": ["ticket_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Search the knowledge base for relevant articles and documentation. Use this to find answers to IT questions, troubleshooting steps, policies, and procedures.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query describing what information is needed.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]
