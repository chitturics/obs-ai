# Splunk Environment Context for RAG

This document provides background context you can feed into a Retrieval-Augmented Generation (RAG) pipeline alongside the fine-tuning data.

## 1. Core Indexes

- `snow`: ServiceNow incidents, changes, tasks, and CMDB records.
- `idc_asa`: Cisco ASA firewall logs.
- `pan_logs`: Palo Alto firewall and threat logs.
- `network`: Network devices, circuits, interfaces, and telemetry. Contains `unit_id` and `circuit` as important index-time fields.
- `wineventlog`: Windows EventLog data, including Security, System, and Application logs.
- `linux_auth`: Linux authentication logs (often from /var/log/secure or /var/log/auth.log).
- `web`: Web server access logs (Apache, Nginx, or app frontends).
- `api`: API gateway or backend HTTP access logs.
- `os`: OS-level metrics and host telemetry.

## 2. Important Fields

- `unit_id`: Represents a business unit, branch, or logical site grouping.
- `circuit`: Represents a specific network circuit or link, often tied to a provider and bandwidth.
- `network`: CIDR key used to join with the `infoblox_networks_lite` lookup.
- `u_business_unit`: ServiceNow field for the business unit owning the incident.
- `u_business_service`: ServiceNow field for the impacted business service.
- CIM fields like `src`, `dest`, `user`, `app`, `action`, `bytes`, `bytes_in`, `bytes_out`, etc.

## 3. Lookups

### `infoblox_networks_lite`

- Key: `network`
- Outputs: `organization`, `unit_id`, `circuit`, `region`
- Used to enrich firewall, VPN, and network events to business context.

### `unit_id_list`

- Keys: `unit_id`, `circuit`
- Outputs may include: `unit_name`, `circuit_description`, `provider`, `bandwidth_mbps`, etc.

## 4. Behavioral Expectations

The AI assistant should:

- Never suggest `index=*`.
- Ask the user which index(es) to use if unclear.
- Prefer `| tstats` and CIM datamodels for analytics.
- Use the environment-specific metadata (indexes, fields, and lookups) to propose realistic SPL.
- Encourage good Splunk practices: time-bounded searches, summary indexing, and acceleration.

## 5. Available Scripting Tools

The assistant can help with scripting and automation:

- **Ansible**: Validate, generate, explain, improve playbooks, and reference 60+ modules.
- **Shell/Bash**: Analyze scripts for issues, generate scripts with best practices, improve error handling.
- **Python**: Analyze code quality, generate scripts with type hints, improve and explain Python code.

## 6. Splunk Writer Tools

The assistant can modify Splunk knowledge objects (requires REVIEW approval):

- **update_saved_search**: Modify an existing saved search (query, schedule, description).
- **create_knowledge_object**: Create macros, event types, tags, or saved searches.

These operations are logged for audit purposes and require explicit user approval before execution.

## 7. Workflow Orchestration

The assistant uses multi-agent workflows for complex tasks:

- **Template-based**: analyze_and_optimize, troubleshoot, build_and_deploy, investigate, security_audit.
- **LLM-powered**: For complex multi-step queries, the LLM generates novel execution plans.
- **Quality tracking**: Strategy and agent performance is tracked to improve future selections.
- **State persistence**: Workflow progress is saved to PostgreSQL for resilience.

Use this file as a RAG source so the assistant remembers what `unit_id`, `circuit`, `snow`, `idc_asa`, `pan_logs`, and `network` mean in your environment.
