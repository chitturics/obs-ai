# Splunk Common Information Model (CIM) Reference

This document is a comprehensive reference for the Splunk Common Information Model (CIM). It covers all CIM data models, their fields, tags, datasets, example tstats queries, and SOC/security context. Use this to answer questions about CIM compliance, data model fields, tstats searches against data models, MITRE ATT&CK mappings, and SOC best practices.

---

## What is the CIM?

The Splunk Common Information Model (CIM) is a shared semantic framework that normalizes data from different sources into a common schema. It defines standard field names, tags, and event categories so that searches, dashboards, and correlation rules work across any vendor or sourcetype. CIM compliance is achieved by mapping raw fields to CIM field names using field aliases, event types, and tags. The Splunk_SA_CIM add-on provides the data model definitions and acceleration macros.

### Why CIM Matters

- **Vendor-agnostic detection**: Write one search that works across Palo Alto, Cisco ASA, CrowdStrike, and any other source.
- **tstats performance**: Accelerated CIM data models enable sub-second searches over terabytes of data using `| tstats`.
- **Splunk Enterprise Security (ES)**: ES correlation searches, dashboards, and risk rules all depend on CIM-normalized data.
- **Interoperability**: Any Splunk app or add-on that follows CIM works with any other CIM-compliant add-on.

---

## CIM Data Models — Complete Reference

### Authentication

**Description**: Tracks all authentication events including logins, logouts, multi-factor authentication, privilege escalation, and account lockouts. This is one of the most critical data models for security operations.

**Tags**: `authentication`

**Datasets**:
- `Authentication` — Base dataset for all authentication events
- `Default_Authentication` — Default authentication events
- `Failed_Authentication` — Authentication failures (action=failure)
- `Successful_Authentication` — Authentication successes (action=success)

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Result of the authentication attempt: `success`, `failure`, `lockout`, `unknown` |
| app | string | Application involved in the authentication (e.g., `sshd`, `AD`, `VPN`) |
| authentication_method | string | Method used: `password`, `certificate`, `mfa`, `token`, `kerberos`, `saml` |
| dest | string | Destination host or IP where authentication was attempted |
| dest_nt_domain | string | Windows NT domain of the destination |
| duration | number | Duration of the authentication session in seconds |
| reason | string | Reason for authentication failure (e.g., `invalid_password`, `account_locked`) |
| signature | string | Unique identifier or name for the authentication event type |
| signature_id | string | Numeric identifier for the event type |
| src | string | Source host or IP that initiated the authentication |
| src_nt_domain | string | Windows NT domain of the source |
| tag | string | CIM tag classification |
| user | string | Username that attempted authentication |
| user_agent | string | User agent string (for web-based authentication) |
| vendor_product | string | Vendor and product generating the event |

**SOC Use Cases**:
- Brute force detection: High volume of `action=failure` from a single `src` to one or many `dest`
- Credential stuffing: Many `action=failure` for different `user` values from same `src`
- Lateral movement: Same `user` authenticating to many different `dest` systems in short time
- MFA bypass detection: `authentication_method` changes or MFA events without prior challenge
- Account lockout monitoring: Track `action=lockout` patterns
- Impossible travel: Same `user` authenticating from geographically distant `src` locations
- Service account abuse: Authentication from unexpected `src` for service accounts
- Off-hours login detection: Successful authentication outside business hours

**Example tstats Searches**:

```spl
| tstats count from datamodel=Authentication where Authentication.action=failure by Authentication.user Authentication.src
| rename Authentication.* as *
| sort -count
```

```spl
| tstats dc(Authentication.dest) as dest_count from datamodel=Authentication where Authentication.action=success by Authentication.user Authentication.src
| rename Authentication.* as *
| where dest_count > 10
```

```spl
| tstats count from datamodel=Authentication where Authentication.action=failure by Authentication.user Authentication.src _time span=1h
| rename Authentication.* as *
| where count > 20
```

```spl
| tstats count from datamodel=Authentication by Authentication.action Authentication.authentication_method _time span=1d
| rename Authentication.* as *
```

---

### Change

**Description**: Tracks configuration changes, system changes, account management events, and audit trail activities across endpoints, network devices, and applications.

**Tags**: `change`

**Datasets**:
- `Change` — Base dataset for all change events
- `Account_Management` — User/group account creation, modification, deletion
- `Endpoint_Changes` — Changes on endpoints (registry, files, services)
- `Network_Changes` — Network device configuration changes
- `Default_Change` — Uncategorized changes

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | The change action: `created`, `modified`, `deleted`, `started`, `stopped` |
| change_type | string | Category of change: `filesystem`, `registry`, `account`, `network`, `AAA` |
| command | string | The command or process that made the change |
| dest | string | Target host where the change occurred |
| object | string | Object that was changed (filename, registry key, user account) |
| object_attrs | string | Attributes of the changed object |
| object_category | string | Category of the changed object: `file`, `directory`, `registry`, `user`, `group`, `policy` |
| object_id | string | Unique identifier for the changed object |
| object_path | string | Full path of the changed object |
| result | string | Result of the change operation |
| result_id | string | Numeric result identifier |
| src | string | Source host or user that initiated the change |
| status | string | Status of the change: `success`, `failure` |
| user | string | User who made the change |
| vendor_product | string | Vendor and product generating the event |

**SOC Use Cases**:
- Unauthorized configuration changes on firewalls, switches, or routers
- Privilege escalation via group membership modification
- Persistence mechanisms: new services, scheduled tasks, registry run keys
- Audit trail for compliance (SOX, PCI, HIPAA)
- Shadow admin detection: unexpected account privilege changes
- File integrity monitoring: critical system file modifications

**Example tstats Searches**:

```spl
| tstats count from datamodel=Change by Change.user Change.action Change.object_category
| rename Change.* as *
| sort -count
```

```spl
| tstats count from datamodel=Change.Account_Management where Change.action=modified by Change.user Change.object Change.dest
| rename Change.* as *
```

```spl
| tstats count from datamodel=Change where Change.object_category=registry by Change.dest Change.object_path Change.user _time span=1h
| rename Change.* as *
```

---

### Data Loss Prevention (DLP)

**Description**: Tracks data loss prevention events from DLP solutions such as Symantec DLP, Digital Guardian, Forcepoint, and Microsoft Purview. Monitors for unauthorized data transfers, policy violations, and sensitive data exposure.

**Tags**: `dlp`

**Datasets**:
- `DLP` — Base dataset for all DLP events
- `Incident` — DLP incidents requiring investigation

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Action taken: `blocked`, `allowed`, `quarantined`, `encrypted`, `notified` |
| app | string | Application involved in the DLP event |
| category | string | DLP policy category (e.g., `PII`, `PHI`, `PCI`, `confidential`) |
| dest | string | Destination of the data transfer |
| dest_zone | string | Network zone of the destination |
| dlp_type | string | Type of DLP detection: `network`, `endpoint`, `cloud`, `email` |
| dvc | string | DLP device or sensor that detected the event |
| file_name | string | Name of the file triggering the DLP event |
| file_path | string | Full path of the file |
| file_size | number | Size of the file in bytes |
| object | string | The data object or content that triggered the policy |
| severity | string | Severity level: `critical`, `high`, `medium`, `low`, `informational` |
| src | string | Source of the data transfer |
| src_zone | string | Network zone of the source |
| url | string | URL involved in the data transfer |
| user | string | User who triggered the DLP event |
| vendor_product | string | Vendor and product name |

**SOC Use Cases**:
- Data exfiltration detection: sensitive data sent to external destinations
- Policy violation monitoring: PII/PHI/PCI data leaving controlled zones
- Insider threat detection: unusual data transfer patterns by user
- Cloud DLP: sensitive data uploaded to unauthorized cloud services
- USB/removable media monitoring: data copied to external devices

**Example tstats Searches**:

```spl
| tstats count from datamodel=DLP by DLP.action DLP.user DLP.category DLP.severity
| rename DLP.* as *
| sort -count
```

```spl
| tstats count from datamodel=DLP where DLP.action=blocked by DLP.user DLP.dest DLP.category _time span=1d
| rename DLP.* as *
```

---

### Email

**Description**: Tracks email events including delivery, filtering, quarantine, and attachment analysis. Covers inbound, outbound, and internal email traffic from mail gateways, Exchange, O365, and email security appliances.

**Tags**: `email`

**Datasets**:
- `Email` — Base dataset for all email events
- `Delivery` — Email delivery events
- `Content_Filtering` — Email content filter actions
- `All_Email` — All email traffic

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Action taken: `delivered`, `blocked`, `quarantined`, `deferred`, `bounced`, `deleted` |
| dest | string | Destination email server or recipient address |
| file_hash | string | Hash of email attachment (MD5, SHA1, SHA256) |
| file_name | string | Name of email attachment |
| file_size | number | Size of the attachment in bytes |
| filter_action | string | Action taken by email filter |
| internal_message_id | string | Internal message tracking identifier |
| message_id | string | RFC 2822 Message-ID header |
| message_info | string | Additional message metadata |
| orig_dest | string | Original intended destination before redirection |
| orig_recipient | string | Original recipient before alias expansion |
| orig_src | string | Original source before relay |
| recipient | string | Email recipient address |
| recipient_count | number | Number of recipients |
| recipient_domain | string | Domain of the recipient |
| return_addr | string | Return-Path or envelope sender |
| size | number | Total message size in bytes |
| src | string | Source email server or sender address |
| src_user | string | Sender email address |
| subject | string | Email subject line |
| url | string | URLs found in the email body |
| user | string | User associated with the email event |
| vendor_product | string | Vendor and product name |

**SOC Use Cases**:
- Phishing detection: suspicious subjects, external senders to many internal recipients
- Business Email Compromise (BEC): impersonation of executives, domain lookalikes
- Malware delivery: tracking attachment hashes against threat intelligence
- Email-based data exfiltration: large attachments or many emails to external domains
- Spam campaign detection: high volume from single source
- Account compromise: email forwarding rule changes

**Example tstats Searches**:

```spl
| tstats count from datamodel=Email where Email.action=blocked by Email.src Email.recipient Email.subject
| rename Email.* as *
| sort -count
```

```spl
| tstats count from datamodel=Email by Email.action _time span=1h
| rename Email.* as *
```

```spl
| tstats sum(Email.size) as total_bytes from datamodel=Email where Email.action=delivered by Email.src_user Email.recipient_domain _time span=1d
| rename Email.* as *
| where total_bytes > 52428800
```

---

### Endpoint

**Description**: Tracks endpoint activity including process execution, file system changes, registry modifications, services, and listening ports. This is the most detailed data model for host-based detection and is essential for EDR (Endpoint Detection and Response) use cases.

**Tags**: `endpoint`, `process`, `service`, `listening`, `port`

**Datasets**:
- `Processes` — Process creation and execution events
- `Services` — Service start, stop, install, and configuration events
- `Filesystem` — File creation, modification, deletion, and access events
- `Registry` — Windows registry key and value changes
- `Ports` — Listening ports and network connections on endpoints

**Key Fields (Processes)**:

| Field | Type | Description |
|---|---|---|
| action | string | Action type: `create`, `terminate`, `access`, `modify` |
| cpu_load_percent | number | CPU utilization percentage |
| creation_time | string | Timestamp of process creation |
| dest | string | Host where the process executed |
| dest_port | number | Destination port for network connections |
| file_hash | string | Hash of the executable (MD5, SHA1, SHA256) |
| file_name | string | Name of the executable file |
| file_path | string | Full path to the executable |
| mem_used | number | Memory used by the process in bytes |
| original_file_name | string | Original filename from PE header (Windows) |
| os | string | Operating system of the endpoint |
| parent_process | string | Parent process command line |
| parent_process_id | number | Parent process ID (PPID) |
| parent_process_name | string | Parent process executable name |
| parent_process_path | string | Full path to parent process executable |
| process | string | Full command line of the process |
| process_current_directory | string | Current working directory of the process |
| process_id | number | Process ID (PID) |
| process_name | string | Name of the process executable |
| process_path | string | Full path to the process executable |
| user | string | User context under which the process ran |
| vendor_product | string | EDR or OS generating the event |

**Key Fields (Filesystem)**:

| Field | Type | Description |
|---|---|---|
| action | string | File action: `created`, `modified`, `deleted`, `read`, `acl_modified` |
| file_create_time | string | File creation timestamp |
| file_hash | string | Hash of the file |
| file_modify_time | string | File modification timestamp |
| file_name | string | Name of the file |
| file_path | string | Full path to the file |
| file_size | number | File size in bytes |

**Key Fields (Registry)**:

| Field | Type | Description |
|---|---|---|
| action | string | Registry action: `created`, `modified`, `deleted` |
| registry_hive | string | Registry hive (e.g., `HKLM`, `HKCU`) |
| registry_key_name | string | Full registry key path |
| registry_path | string | Full path including value name |
| registry_value_data | string | Data written to the registry value |
| registry_value_name | string | Name of the registry value |
| registry_value_type | string | Data type of the registry value |

**Key Fields (Services)**:

| Field | Type | Description |
|---|---|---|
| action | string | Service action: `started`, `stopped`, `created`, `modified`, `deleted` |
| service | string | Name of the service |
| service_dll | string | DLL loaded by the service |
| service_dll_path | string | Full path to the service DLL |
| service_exec | string | Executable path of the service |
| service_path | string | Full path to the service binary |
| start_mode | string | Service start mode: `auto`, `manual`, `disabled` |
| status | string | Current service status |

**SOC Use Cases**:
- Malware detection: suspicious process names, hashes, or paths
- Living-off-the-land binaries (LOLBins): misuse of certutil, mshta, regsvr32, wmic, powershell
- Process injection: unusual parent-child process relationships
- Persistence mechanisms: new services, registry run keys, scheduled tasks
- Credential dumping: lsass.exe access, mimikatz indicators
- Ransomware indicators: mass file modifications or deletions
- Lateral movement: remote process execution via PsExec, WMI, WinRM
- Fileless malware: PowerShell encoded commands, in-memory execution

**Example tstats Searches**:

```spl
| tstats count from datamodel=Endpoint.Processes by Processes.process_name Processes.dest Processes.user
| rename Processes.* as *
| sort -count
```

```spl
| tstats count from datamodel=Endpoint.Processes where Processes.parent_process_name=cmd.exe OR Processes.parent_process_name=powershell.exe by Processes.process_name Processes.dest Processes.user Processes.process
| rename Processes.* as *
```

```spl
| tstats count from datamodel=Endpoint.Registry where Registry.registry_path="*\\CurrentVersion\\Run*" by Registry.dest Registry.registry_path Registry.registry_value_data Registry.user
| rename Registry.* as *
```

```spl
| tstats count from datamodel=Endpoint.Filesystem where Filesystem.action=created by Filesystem.file_name Filesystem.file_path Filesystem.dest _time span=1h
| rename Filesystem.* as *
```

```spl
| tstats count from datamodel=Endpoint.Services where Services.action=created by Services.service Services.service_exec Services.dest Services.user
| rename Services.* as *
```

---

### Intrusion Detection

**Description**: Tracks events from Intrusion Detection Systems (IDS) and Intrusion Prevention Systems (IPS), including Snort, Suricata, Palo Alto Threat, Cisco Firepower, and other network security appliances.

**Tags**: `ids`, `attack`

**Datasets**:
- `IDS_Attacks` — Base dataset for all IDS/IPS events
- `Application_Attack` — Application-layer attacks
- `Brute_Force` — Brute force attempts
- `DoS` — Denial of Service events
- `Exploit_Public_Facing` — Exploits against public-facing services
- `Network_Attack` — Network-layer attacks

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | IDS/IPS action: `allowed`, `blocked`, `dropped`, `reset` |
| category | string | Attack category: `exploit`, `malware`, `scan`, `dos`, `brute_force`, `web_attack` |
| dest | string | Target host or IP of the attack |
| dest_port | number | Target port of the attack |
| dvc | string | IDS/IPS device that detected the event |
| file_hash | string | Hash of malicious file if applicable |
| file_name | string | Name of malicious file if applicable |
| file_path | string | Path of malicious file if applicable |
| ids_type | string | Type of IDS: `network`, `host`, `application` |
| severity | string | Severity: `critical`, `high`, `medium`, `low`, `informational` |
| signature | string | Name of the IDS/IPS signature or rule that fired |
| signature_id | string | Numeric identifier of the signature |
| src | string | Source host or IP of the attacker |
| src_port | number | Source port of the attack |
| transport | string | Transport protocol: `tcp`, `udp`, `icmp` |
| url | string | URL involved in the attack |
| user | string | User associated with the event |
| vendor_product | string | IDS/IPS vendor and product name |

**SOC Use Cases**:
- IDS/IPS alert correlation: aggregate alerts by signature, source, and destination
- Signature-based detection: known exploits, malware callbacks, C2 patterns
- Network intrusion monitoring: track blocked vs. allowed attacks
- Exploit detection: public-facing application attacks, zero-day indicators
- Scan detection: port scans, vulnerability scans from external sources
- Alert tuning: identify high-volume low-severity signatures for suppression

**Example tstats Searches**:

```spl
| tstats count from datamodel=Intrusion_Detection by IDS_Attacks.signature IDS_Attacks.action IDS_Attacks.severity
| rename IDS_Attacks.* as *
| sort -count
```

```spl
| tstats count from datamodel=Intrusion_Detection where IDS_Attacks.action=allowed IDS_Attacks.severity=critical by IDS_Attacks.src IDS_Attacks.dest IDS_Attacks.signature
| rename IDS_Attacks.* as *
```

```spl
| tstats dc(IDS_Attacks.dest) as target_count from datamodel=Intrusion_Detection by IDS_Attacks.src IDS_Attacks.signature
| rename IDS_Attacks.* as *
| where target_count > 5
```

---

### Malware

**Description**: Tracks malware detection events from antivirus, anti-malware, and EDR solutions including CrowdStrike, Carbon Black, Symantec, McAfee, Windows Defender, and SentinelOne.

**Tags**: `malware`, `operations`

**Datasets**:
- `Malware_Attacks` — Malware detection and response events
- `Malware_Operations` — AV/anti-malware operational events (updates, scans, health)

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Action taken: `allowed`, `blocked`, `deferred`, `quarantined`, `deleted`, `cleaned` |
| category | string | Malware category: `virus`, `trojan`, `ransomware`, `worm`, `adware`, `spyware`, `rootkit`, `pup` |
| date | string | Date of malware detection |
| dest | string | Host where malware was detected |
| dest_nt_domain | string | Windows domain of the infected host |
| file_hash | string | Hash of the malicious file (MD5, SHA1, SHA256) |
| file_name | string | Name of the malicious file |
| file_path | string | Full path of the malicious file |
| os | string | Operating system of the affected endpoint |
| signature | string | Malware signature or detection name |
| signature_version | string | AV signature database version |
| src | string | Source of the malware (download URL, email, USB) |
| url | string | URL from which malware was downloaded |
| user | string | User logged in when malware was detected |
| vendor_product | string | AV/EDR vendor and product name |

**SOC Use Cases**:
- Malware outbreak tracking: same signature across multiple endpoints
- AV health monitoring: signature version currency across the fleet
- Quarantine failure tracking: malware detected but action is `allowed`
- Ransomware detection: rapid file encryption indicators
- Repeated infection: same host hit by same or different malware
- Zero-day indicators: new unknown signatures or heuristic detections

**Example tstats Searches**:

```spl
| tstats count from datamodel=Malware by Malware_Attacks.signature Malware_Attacks.action Malware_Attacks.dest
| rename Malware_Attacks.* as *
| sort -count
```

```spl
| tstats count from datamodel=Malware where Malware_Attacks.action!=blocked AND Malware_Attacks.action!=quarantined by Malware_Attacks.dest Malware_Attacks.signature Malware_Attacks.file_path
| rename Malware_Attacks.* as *
```

```spl
| tstats dc(Malware_Attacks.dest) as infected_hosts from datamodel=Malware by Malware_Attacks.signature _time span=1d
| rename Malware_Attacks.* as *
| where infected_hosts > 3
```

---

### Network Resolution (DNS)

**Description**: Tracks DNS query and response events from DNS servers, DNS proxies, and network security appliances that log DNS traffic. Essential for detecting DNS-based attacks and command-and-control communication.

**Tags**: `network`, `resolution`, `dns`

**Datasets**:
- `DNS` — Base dataset for all DNS events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| answer | string | DNS answer/response (resolved IP or CNAME) |
| dest | string | DNS server handling the query |
| message_type | string | DNS message type: `Query`, `Response` |
| name | string | Queried domain name (alias for query) |
| query | string | The DNS query string (domain name being resolved) |
| query_count | number | Number of queries for this domain |
| query_type | string | DNS query type: `A`, `AAAA`, `CNAME`, `MX`, `NS`, `PTR`, `SOA`, `SRV`, `TXT` |
| record_type | string | DNS record type in the response |
| reply_code | string | DNS reply code: `NOERROR`, `NXDOMAIN`, `SERVFAIL`, `REFUSED` |
| reply_code_id | number | Numeric DNS reply code |
| src | string | Host or IP that made the DNS query |
| transport | string | Transport protocol: `udp`, `tcp` |
| ttl | number | Time to live of the DNS response |
| vendor_product | string | DNS server or security product name |

**SOC Use Cases**:
- DNS tunneling detection: high query volume, long domain names, TXT record abuse
- Domain Generation Algorithm (DGA) detection: random-looking domain names with high entropy
- DNS exfiltration: large TXT responses or many subdomains of the same parent domain
- Command and Control (C2) communication: beaconing patterns to suspicious domains
- Newly registered domain detection: queries to domains registered within last 30 days
- DNS rebinding attacks: responses that resolve to internal IP addresses
- Fast-flux detection: rapid changes in DNS answers for the same domain
- Sinkhole monitoring: queries to known sinkholed domains

**Example tstats Searches**:

```spl
| tstats count from datamodel=Network_Resolution by DNS.query DNS.reply_code DNS.src
| rename DNS.* as *
| sort -count
```

```spl
| tstats count from datamodel=Network_Resolution where DNS.reply_code=NXDOMAIN by DNS.src DNS.query _time span=1h
| rename DNS.* as *
| where count > 100
```

```spl
| tstats count from datamodel=Network_Resolution by DNS.query DNS.query_type
| rename DNS.* as *
| where query_type="TXT"
| eval query_length=len(query)
| where query_length > 50
```

---

### Network Sessions

**Description**: Tracks network session events including VPN connections, DHCP leases, and session management from network infrastructure. Includes both VPN and DHCP sub-models.

**Tags**: `network`, `session`, `dhcp`, `vpn`

**Datasets**:
- `All_Sessions` — Base dataset for all session events
- `Session_Start` — Session establishment events
- `Session_End` — Session termination events
- `DHCP` — DHCP lease events
- `VPN` — VPN connection events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Session action: `connect`, `disconnect`, `renew`, `release`, `assign` |
| dest | string | Destination host or VPN gateway |
| dest_ip | string | Destination IP address |
| dest_mac | string | Destination MAC address |
| dest_nt_domain | string | Destination Windows domain |
| duration | number | Session duration in seconds |
| lease_duration | number | DHCP lease duration in seconds |
| signature | string | Event type identifier |
| src | string | Source host or client |
| src_ip | string | Source IP address (assigned IP for VPN/DHCP) |
| src_mac | string | Source MAC address |
| user | string | User associated with the session |
| vendor_product | string | VPN or DHCP server product name |

**SOC Use Cases**:
- VPN anomaly detection: connections from unusual locations or at unusual times
- Session hijacking: concurrent sessions from different IPs for same user
- DHCP spoofing: unauthorized DHCP servers on the network
- VPN split-tunnel abuse: monitoring VPN session metadata
- IP address tracking: correlate DHCP leases with security events
- Rogue device detection: MAC addresses not in known inventory

**Example tstats Searches**:

```spl
| tstats count from datamodel=Network_Sessions where All_Sessions.action=connect by All_Sessions.user All_Sessions.src_ip All_Sessions.dest _time span=1h
| rename All_Sessions.* as *
```

```spl
| tstats dc(All_Sessions.src_ip) as ip_count from datamodel=Network_Sessions where All_Sessions.action=connect by All_Sessions.user
| rename All_Sessions.* as *
| where ip_count > 3
```

---

### Network Traffic

**Description**: Tracks all network communication events from firewalls, routers, switches, flow collectors (NetFlow/sFlow/IPFIX), and network security appliances. This is the highest-volume CIM data model and is critical for network security monitoring.

**Tags**: `network`, `communicate`

**Datasets**:
- `All_Traffic` — Base dataset for all network traffic
- `Allowed_Traffic` — Traffic that was permitted by firewall rules
- `Blocked_Traffic` — Traffic that was denied or dropped by firewall rules

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Firewall action: `allowed`, `blocked`, `dropped`, `teardown`, `reset` |
| app | string | Application identified by the firewall or proxy |
| bytes | number | Total bytes transferred |
| bytes_in | number | Bytes received (inbound) |
| bytes_out | number | Bytes sent (outbound) |
| dest | string | Destination host or IP |
| dest_ip | string | Destination IP address |
| dest_mac | string | Destination MAC address |
| dest_port | number | Destination port number |
| dest_zone | string | Firewall security zone of the destination |
| direction | string | Traffic direction: `inbound`, `outbound`, `lateral` |
| dvc | string | Network device that logged the traffic |
| dvc_ip | string | IP address of the logging device |
| duration | number | Connection duration in seconds |
| packets | number | Total packets transferred |
| packets_in | number | Inbound packets |
| packets_out | number | Outbound packets |
| protocol | string | Network protocol: `tcp`, `udp`, `icmp`, `ip` |
| rule | string | Firewall rule or ACL that matched |
| src | string | Source host or IP |
| src_ip | string | Source IP address |
| src_mac | string | Source MAC address |
| src_port | number | Source port number |
| src_zone | string | Firewall security zone of the source |
| tcp_flag | string | TCP flags: `SYN`, `ACK`, `FIN`, `RST` |
| transport | string | Transport layer protocol |
| user | string | User associated with the traffic |
| vendor_product | string | Firewall or network device vendor and product |
| vlan_id | number | VLAN identifier |

**SOC Use Cases**:
- Firewall monitoring: blocked connections, rule violations, denied traffic
- Lateral movement: internal-to-internal traffic on unusual ports
- Data exfiltration: large outbound byte counts to external IPs
- Port scanning: single source connecting to many destination ports
- Beaconing detection: regular interval connections to external hosts
- DDoS detection: high volume traffic to a single destination
- Protocol anomalies: unexpected protocols on standard ports
- East-west traffic monitoring: traffic between internal security zones
- Shadow IT detection: traffic to unauthorized cloud services

**Example tstats Searches**:

```spl
| tstats sum(All_Traffic.bytes) as total_bytes from datamodel=Network_Traffic by All_Traffic.src_ip All_Traffic.dest_ip _time span=1h
| rename All_Traffic.* as *
| sort -total_bytes
```

```spl
| tstats count from datamodel=Network_Traffic.Blocked_Traffic by All_Traffic.src_ip All_Traffic.dest_ip All_Traffic.dest_port All_Traffic.action
| rename All_Traffic.* as *
| sort -count
```

```spl
| tstats dc(All_Traffic.dest_port) as port_count from datamodel=Network_Traffic where All_Traffic.action=blocked by All_Traffic.src_ip
| rename All_Traffic.* as *
| where port_count > 20
```

```spl
| tstats sum(All_Traffic.bytes_out) as bytes_out from datamodel=Network_Traffic where All_Traffic.direction=outbound by All_Traffic.src_ip All_Traffic.dest_ip _time span=1d
| rename All_Traffic.* as *
| where bytes_out > 1073741824
```

---

### Updates

**Description**: Tracks software update and patch management events including Windows Update, WSUS, SCCM, and third-party patch management systems.

**Tags**: `update`

**Datasets**:
- `Updates` — Base dataset for all update events
- `Patches` — Patch installation events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Update action: `installed`, `available`, `failed`, `downloaded`, `reboot_required` |
| dest | string | Host where the update was applied |
| file_hash | string | Hash of the update package |
| signature | string | Name or KB number of the update |
| signature_id | string | Update identifier (e.g., KB number) |
| src | string | Update source server (WSUS, SCCM) |
| status | string | Update status: `success`, `failure`, `pending` |
| vendor_product | string | Patch management vendor and product |

**SOC Use Cases**:
- Patch compliance: percentage of endpoints with critical patches installed
- Vulnerability window tracking: time between patch availability and installation
- Failed update investigation: endpoints where critical updates consistently fail
- Zero-day response: track emergency patch deployment progress

**Example tstats Searches**:

```spl
| tstats count from datamodel=Updates where Updates.status=failure by Updates.dest Updates.signature _time span=1d
| rename Updates.* as *
```

```spl
| tstats dc(Updates.dest) as patched_hosts from datamodel=Updates where Updates.status=success by Updates.signature
| rename Updates.* as *
```

---

### Vulnerabilities

**Description**: Tracks vulnerability scan results from scanners such as Nessus, Qualys, Rapid7 InsightVM, and OpenVAS. Maps detected vulnerabilities to CVEs and severity ratings.

**Tags**: `vulnerability`, `report`

**Datasets**:
- `Vulnerabilities` — Base dataset for all vulnerability events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| bugtraq | string | BugTraq ID for the vulnerability |
| category | string | Vulnerability category: `os`, `application`, `network`, `web`, `database` |
| cert | string | CERT advisory identifier |
| cve | string | CVE identifier (e.g., `CVE-2024-12345`) |
| cvss | number | CVSS score (0-10) |
| dest | string | Host where the vulnerability was found |
| dest_port | number | Port associated with the vulnerability |
| dvc | string | Scanner that detected the vulnerability |
| msft | string | Microsoft security bulletin identifier |
| mskb | string | Microsoft KB article number |
| os | string | Operating system of the vulnerable host |
| severity | string | Severity: `critical`, `high`, `medium`, `low`, `informational` |
| signature | string | Vulnerability name or description |
| signature_id | string | Scanner-specific vulnerability identifier |
| url | string | Reference URL for the vulnerability |
| vendor_product | string | Scanner vendor and product name |

**SOC Use Cases**:
- Vulnerability assessment: track critical and high severity findings across the environment
- Risk scoring: prioritize remediation by CVSS score and asset criticality
- CVE correlation: match known exploited vulnerabilities (CISA KEV) with scan results
- Trending: track vulnerability counts over time by severity
- Compliance: ensure critical patches are applied within SLA windows
- Attack surface reduction: identify internet-facing hosts with critical vulnerabilities

**Example tstats Searches**:

```spl
| tstats count from datamodel=Vulnerabilities by Vulnerabilities.cve Vulnerabilities.severity Vulnerabilities.dest
| rename Vulnerabilities.* as *
| sort -severity
```

```spl
| tstats dc(Vulnerabilities.dest) as affected_hosts from datamodel=Vulnerabilities where Vulnerabilities.severity=critical by Vulnerabilities.cve
| rename Vulnerabilities.* as *
| sort -affected_hosts
```

```spl
| tstats count from datamodel=Vulnerabilities by Vulnerabilities.severity _time span=1w
| rename Vulnerabilities.* as *
```

---

### Web

**Description**: Tracks web and HTTP/HTTPS traffic from web proxies, web application firewalls (WAF), load balancers, CDNs, and web server access logs. Covers both proxy-based and server-side web events.

**Tags**: `web`

**Datasets**:
- `Web` — Base dataset for all web events
- `Proxy` — Web proxy events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| action | string | Web action: `allowed`, `blocked`, `deferred` |
| app | string | Web application name |
| bytes | number | Total bytes transferred |
| bytes_in | number | Bytes received from client |
| bytes_out | number | Bytes sent to client |
| cached | boolean | Whether the response was served from cache |
| category | string | URL category from proxy/filter: `malware`, `phishing`, `adult`, `social_media`, `streaming` |
| cookie | string | HTTP cookie data |
| dest | string | Destination web server or IP |
| dest_port | number | Destination port (usually 80 or 443) |
| http_content_type | string | HTTP Content-Type header |
| http_method | string | HTTP method: `GET`, `POST`, `PUT`, `DELETE`, `HEAD`, `OPTIONS`, `PATCH` |
| http_referrer | string | HTTP Referer header |
| http_user_agent | string | HTTP User-Agent header string |
| site | string | Website domain name |
| src | string | Client host or IP making the request |
| status | number | HTTP response status code (200, 301, 403, 404, 500, etc.) |
| uri_path | string | URI path component of the URL |
| uri_query | string | URI query string parameters |
| url | string | Full URL of the request |
| url_length | number | Length of the URL in characters |
| user | string | Authenticated user making the request |
| vendor_product | string | Proxy, WAF, or web server vendor and product |

**SOC Use Cases**:
- Web application attacks: SQL injection (`uri_query` with `UNION SELECT`, `OR 1=1`), XSS (`<script>` in parameters), path traversal (`../`)
- Proxy monitoring: blocked URL categories, policy violations
- URL filtering: access to known malicious domains or IPs
- Web scraping detection: high request volume from single source
- Credential harvesting: POST requests to phishing URLs
- Web shell detection: unusual HTTP methods to unexpected paths
- Long URL detection: potential buffer overflow or injection attempts
- User-agent anomalies: known attack tools (sqlmap, nikto, burpsuite)
- HTTP status anomalies: spikes in 403, 404, or 500 errors

**Example tstats Searches**:

```spl
| tstats count from datamodel=Web by Web.http_method Web.status Web.url Web.src
| rename Web.* as *
| sort -count
```

```spl
| tstats count from datamodel=Web where Web.status>=400 by Web.src Web.url Web.status _time span=1h
| rename Web.* as *
| where count > 50
```

```spl
| tstats count from datamodel=Web where Web.category=malware OR Web.category=phishing by Web.src Web.url Web.category Web.action
| rename Web.* as *
```

```spl
| tstats sum(Web.bytes_out) as total_download from datamodel=Web by Web.src Web.site _time span=1d
| rename Web.* as *
| where total_download > 1073741824
```

---

### Alerts

**Description**: Tracks alert and notification events from monitoring systems, SIEM correlation rules, and alerting platforms. Used for alert aggregation, deduplication, and fatigue management.

**Tags**: `alert`

**Datasets**:
- `Alerts` — Base dataset for all alert events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| app | string | Application or system that generated the alert |
| body | string | Full body or description of the alert |
| description | string | Short description of the alert |
| dest | string | Target or affected host |
| id | string | Unique alert identifier |
| severity | string | Alert severity: `critical`, `high`, `medium`, `low`, `informational` |
| signature | string | Alert rule name or signature |
| src | string | Source host or system |
| subject | string | Alert subject line |
| type | string | Alert type: `correlation`, `threshold`, `anomaly`, `scheduled` |

**SOC Use Cases**:
- Alert aggregation: correlate alerts across multiple sources
- Alert fatigue management: identify noisy rules for tuning
- Alert trending: track alert volume by severity and type over time
- Incident enrichment: correlate alerts with CIM events from other data models
- SLA tracking: measure time from alert to acknowledgment

**Example tstats Searches**:

```spl
| tstats count from datamodel=Alerts by Alerts.signature Alerts.severity _time span=1d
| rename Alerts.* as *
| sort -count
```

---

### Certificates

**Description**: Tracks SSL/TLS certificate events from certificate monitoring tools, web proxies with TLS inspection, and certificate management platforms.

**Tags**: `certificate`

**Datasets**:
- `All_Certificates` — Base dataset for all certificate events
- `SSL` — SSL/TLS specific certificate events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| dest | string | Host presenting the certificate |
| dest_port | number | Port of the TLS connection |
| issuer | string | Certificate issuer (CA) distinguished name |
| issuer_common_name | string | Common name of the issuing CA |
| serial | string | Certificate serial number |
| signature_algorithm | string | Algorithm used to sign the certificate (e.g., `sha256WithRSAEncryption`) |
| src | string | Client connecting to the TLS service |
| ssl_end_time | string | Certificate expiration date |
| ssl_issuer | string | Full issuer string |
| ssl_issuer_common_name | string | Issuer common name |
| ssl_start_time | string | Certificate validity start date |
| ssl_subject | string | Full subject string |
| ssl_subject_common_name | string | Subject common name (domain name) |
| ssl_version | string | SSL/TLS version: `TLSv1`, `TLSv1.1`, `TLSv1.2`, `TLSv1.3`, `SSLv3` |
| subject | string | Certificate subject distinguished name |
| subject_alternative_name | string | Subject Alternative Names (SANs) |

**SOC Use Cases**:
- Expired certificate detection: certificates past ssl_end_time
- Certificate transparency monitoring: detect unauthorized certificates for your domains
- Weak protocol detection: connections using SSLv3 or TLSv1.0
- Self-signed certificate detection: issuer equals subject
- Certificate pinning violations: unexpected issuer for known domains
- Short-lived certificate abuse: certificates valid for very short periods

**Example tstats Searches**:

```spl
| tstats count from datamodel=Certificates by All_Certificates.ssl_subject_common_name All_Certificates.ssl_end_time All_Certificates.issuer_common_name
| rename All_Certificates.* as *
```

```spl
| tstats count from datamodel=Certificates where All_Certificates.ssl_version="SSLv3" OR All_Certificates.ssl_version="TLSv1" by All_Certificates.dest All_Certificates.src
| rename All_Certificates.* as *
```

---

### Ticket Management

**Description**: Tracks IT service management (ITSM) ticket events from platforms such as ServiceNow, Jira, BMC Remedy, and Zendesk. Used for incident tracking and SOAR integration.

**Tags**: `ticketing`

**Datasets**:
- `All_Tickets` — Base dataset for all ticket events

**Key Fields**:

| Field | Type | Description |
|---|---|---|
| assigned_to | string | User or group the ticket is assigned to |
| change_type | string | Type of change for change tickets |
| closed_time | string | Timestamp when the ticket was closed |
| created_time | string | Timestamp when the ticket was created |
| description | string | Full ticket description |
| dest | string | Affected system or asset |
| priority | string | Ticket priority: `1-critical`, `2-high`, `3-medium`, `4-low` |
| severity | string | Ticket severity level |
| src | string | Source system or reporter |
| status | string | Ticket status: `new`, `in_progress`, `resolved`, `closed`, `cancelled` |
| ticket_id | string | Unique ticket identifier |
| urgency | string | Ticket urgency level |
| user | string | User who created the ticket |

**SOC Use Cases**:
- Incident tracking: correlate security events with incident tickets
- SOAR integration: automatically create tickets from security alerts
- SLA monitoring: measure time to resolve by priority
- Workload distribution: track ticket assignment across analysts
- Mean Time to Resolve (MTTR): calculate from created_time to closed_time

---

### Deprecated Data Models

**Application State**: Deprecated. Use the Endpoint data model instead for application and process monitoring on endpoints.

**Change Analysis**: Deprecated. Use the Change data model instead for configuration and system change tracking.

---

## CIM Tags Reference

Tags are applied to event types in `eventtypes.conf` to classify events into CIM data models. A single event can have multiple tags, mapping it to multiple data models.

| Tag | Data Model | Description |
|---|---|---|
| `authentication` | Authentication | Login, logout, MFA, and account lockout events |
| `change` | Change | Configuration and system change events |
| `email` | Email | Email send, receive, and filter events |
| `network` | Network Traffic, DNS, Sessions | Network communication events |
| `communicate` | Network Traffic | Network traffic flow events |
| `resolution` | Network Resolution | DNS query and response events |
| `dns` | Network Resolution | DNS-specific events |
| `session` | Network Sessions | VPN and DHCP session events |
| `dhcp` | Network Sessions | DHCP lease events |
| `vpn` | Network Sessions | VPN connection events |
| `web` | Web | HTTP/HTTPS traffic and proxy events |
| `proxy` | Web | Web proxy events specifically |
| `malware` | Malware | Antivirus and anti-malware events |
| `operations` | Malware | AV operational events (scans, updates) |
| `ids` | Intrusion Detection | IDS/IPS detection events |
| `attack` | Intrusion Detection | Attack classification events |
| `vulnerability` | Vulnerabilities | Vulnerability scan results |
| `report` | Vulnerabilities | Vulnerability report events |
| `dlp` | DLP | Data loss prevention events |
| `certificate` | Certificates | SSL/TLS certificate events |
| `endpoint` | Endpoint | General endpoint events |
| `process` | Endpoint.Processes | Process execution events |
| `service` | Endpoint.Services | Service lifecycle events |
| `listening` | Endpoint.Ports | Listening port events |
| `port` | Endpoint.Ports | Port-related endpoint events |
| `registry` | Endpoint.Registry | Windows registry events |
| `filesystem` | Endpoint.Filesystem | File system events |
| `update` | Updates | Patch and update events |
| `alert` | Alerts | Alert and notification events |
| `ticketing` | Ticket Management | ITSM ticket events |

---

## CIM Compliance Implementation Guide

### Step 1: Install Splunk_SA_CIM

The Splunk Common Information Model add-on (`Splunk_SA_CIM`) provides the data model JSON definitions and acceleration macros. Install it from Splunkbase.

```
# Verify installation
| rest /services/apps/local/Splunk_SA_CIM | table title version
```

### Step 2: Map Sourcetypes via Tags

Create event types in `eventtypes.conf` and apply tags in `tags.conf` for each sourcetype.

```ini
# eventtypes.conf
[paloalto_traffic]
search = sourcetype=pan:traffic

# tags.conf
[eventtype=paloalto_traffic]
network = enabled
communicate = enabled
```

### Step 3: Create Field Aliases

Map vendor-specific field names to CIM field names in `props.conf`.

```ini
# props.conf
[pan:traffic]
FIELDALIAS-src = src_ip AS src
FIELDALIAS-dest = dst_ip AS dest
FIELDALIAS-src_port = src_port AS src_port
FIELDALIAS-dest_port = dst_port AS dest_port
FIELDALIAS-action = action AS action
FIELDALIAS-bytes_in = bytes_received AS bytes_in
FIELDALIAS-bytes_out = bytes_sent AS bytes_out
FIELDALIAS-transport = proto AS transport
```

### Step 4: Accelerate Data Models

Enable data model acceleration for tstats performance. Set acceleration time range based on data volume and search requirements.

```
# Check acceleration status
| rest /services/datamodel/model | table title acceleration acceleration.earliest_time
```

```
# Validate acceleration is building
| rest /services/admin/summarization by_tstats=t | table datamodel_name summary.complete summary.size summary.access_time
```

### Step 5: Validate CIM Compliance

Verify that events correctly populate CIM data models.

```spl
| datamodel Authentication search | head 10
| datamodel Network_Traffic All_Traffic search | head 10
| datamodel Endpoint Processes search | head 10
| datamodel Web search | head 10
```

```spl
| tstats count from datamodel=Authentication by sourcetype _time span=1d
| tstats count from datamodel=Network_Traffic by sourcetype _time span=1d
| tstats count from datamodel=Endpoint.Processes by sourcetype _time span=1d
```

### Step 6: Use CIM Validator

Run the CIM Validator dashboard (included with Splunk_SA_CIM) to identify unmapped fields and missing tag assignments.

---

## MITRE ATT&CK Mapping to CIM Data Models

Each MITRE ATT&CK tactic maps to one or more CIM data models. Use these mappings to ensure detection coverage across the kill chain.

### Initial Access (TA0001)
- **Authentication**: Failed logins, brute force attempts, credential stuffing
- **Email**: Phishing emails, malicious attachments, BEC
- **Web**: Drive-by compromise, exploitation of public-facing applications
- **Intrusion Detection**: Exploit attempts against exposed services

### Execution (TA0002)
- **Endpoint.Processes**: Suspicious process execution, script interpreters, LOLBins
- **Endpoint.Services**: Malicious service creation
- Example: `| tstats count from datamodel=Endpoint.Processes where Processes.process_name IN ("powershell.exe","cmd.exe","wscript.exe","cscript.exe","mshta.exe") by Processes.process Processes.dest Processes.parent_process_name`

### Persistence (TA0003)
- **Change**: Registry run keys, scheduled tasks, startup items, new services
- **Endpoint.Registry**: Registry modifications for persistence
- **Endpoint.Services**: New service installations
- **Endpoint.Filesystem**: Files dropped in startup folders
- Example: `| tstats count from datamodel=Endpoint.Registry where Registry.registry_path="*\\CurrentVersion\\Run*" OR Registry.registry_path="*\\CurrentVersion\\RunOnce*" by Registry.dest Registry.registry_value_data Registry.user`

### Privilege Escalation (TA0004)
- **Authentication**: Privilege elevation events, sudo/runas usage
- **Change**: Account privilege modification, group membership changes
- **Endpoint.Processes**: Processes running as SYSTEM or root unexpectedly

### Defense Evasion (TA0005)
- **Endpoint.Processes**: Process injection, process hollowing, masquerading
- **Endpoint.Filesystem**: Timestomping, hidden files, log clearing
- **Change**: Security log clearing, audit policy changes

### Credential Access (TA0006)
- **Authentication**: Credential dumping indicators, Kerberoasting
- **Endpoint.Processes**: Access to lsass.exe, credential tool execution
- Example: `| tstats count from datamodel=Endpoint.Processes where Processes.process_name=lsass.exe by Processes.dest Processes.parent_process_name Processes.user`

### Discovery (TA0007)
- **Network Traffic**: Network scanning, port scanning, service enumeration
- **Network Resolution (DNS)**: DNS enumeration, zone transfer attempts
- **Endpoint.Processes**: Reconnaissance commands (whoami, net user, ipconfig, systeminfo)

### Lateral Movement (TA0008)
- **Authentication**: Remote authentication across multiple hosts
- **Network Traffic**: SMB, RDP, WinRM, SSH connections between internal hosts
- **Endpoint.Processes**: PsExec, WMI, remote service creation
- Example: `| tstats dc(Authentication.dest) as dest_count from datamodel=Authentication where Authentication.action=success by Authentication.user Authentication.src | where dest_count > 5`

### Collection (TA0009)
- **DLP**: Sensitive data aggregation and staging
- **Email**: Email collection, mailbox access
- **Endpoint.Filesystem**: Archive creation, data staging in temp directories

### Exfiltration (TA0010)
- **Network Traffic**: Large outbound data transfers, unusual protocols
- **DNS**: DNS tunneling, large DNS TXT responses
- **Web**: HTTP/S exfiltration to cloud storage or attacker-controlled sites
- **DLP**: Data leaving controlled zones
- Example: `| tstats sum(All_Traffic.bytes_out) as bytes_out from datamodel=Network_Traffic where All_Traffic.direction=outbound by All_Traffic.src_ip All_Traffic.dest_ip | where bytes_out > 500000000`

### Command and Control (TA0011)
- **DNS**: DGA domains, DNS tunneling, beaconing via DNS
- **Network Traffic**: Periodic beaconing patterns, unusual port usage
- **Web**: HTTP/S C2 communication, encoded payloads in web requests
- **Certificates**: Self-signed certificates on C2 infrastructure
- Example: `| tstats count from datamodel=Network_Resolution by DNS.query DNS.src _time span=10m | streamstats count by DNS.query DNS.src | where count > 50`

### Impact (TA0040)
- **Endpoint.Filesystem**: Mass file encryption (ransomware), data destruction
- **Endpoint.Services**: Service disruption, critical service stops
- **Change**: System configuration tampering

---

## Risk-Based Alerting (RBA) with CIM

Risk-Based Alerting uses CIM-normalized data to assign risk scores to entities (users, hosts, IPs) instead of generating individual alerts. This reduces alert fatigue and surfaces the highest-risk entities.

### RBA Architecture

1. **Risk Rules**: Each detection assigns a `risk_score` to a `risk_object` (user, host, or IP)
2. **Risk Index**: Scores accumulate in the `risk` index
3. **Risk Notables**: When cumulative risk exceeds a threshold, a notable event fires

### Example RBA Searches

```spl
# Assign risk for failed authentication (brute force indicator)
| tstats count from datamodel=Authentication where Authentication.action=failure by Authentication.user Authentication.src _time span=1h
| rename Authentication.* as *
| where count > 10
| eval risk_score=count*5, risk_object=user, risk_object_type="user", risk_message="Brute force: ".count." failed logins from ".src
| collect index=risk
```

```spl
# Assign risk for suspicious process execution
| tstats count from datamodel=Endpoint.Processes where Processes.process_name IN ("certutil.exe","mshta.exe","regsvr32.exe","rundll32.exe") by Processes.process_name Processes.dest Processes.user Processes.process
| rename Processes.* as *
| eval risk_score=40, risk_object=dest, risk_object_type="system", risk_message="LOLBin execution: ".process_name." by ".user
| collect index=risk
```

```spl
# Assign risk for DNS to newly registered domains
| tstats count from datamodel=Network_Resolution by DNS.query DNS.src
| rename DNS.* as *
| lookup newly_registered_domains domain AS query OUTPUT is_new
| where is_new="true"
| eval risk_score=30, risk_object=src, risk_object_type="system", risk_message="DNS query to newly registered domain: ".query
| collect index=risk
```

```spl
# View top risk entities
| from datamodel:Risk.All_Risk
| stats sum(risk_score) as total_risk values(risk_message) as risk_messages dc(source) as source_count by risk_object risk_object_type
| sort -total_risk
```

---

## SOC Metrics from CIM Data Models

### Mean Time to Detect (MTTD)

```spl
| tstats earliest(_time) as first_seen latest(_time) as last_seen from datamodel=Intrusion_Detection by IDS_Attacks.signature IDS_Attacks.src IDS_Attacks.dest
| rename IDS_Attacks.* as *
| eval mttd_seconds=first_seen - relative_time(now(), "-1d")
| stats avg(mttd_seconds) as avg_mttd_seconds by signature
```

### Mean Time to Respond (MTTR)

```spl
# Join IDS alerts with ticket management for response time
| tstats earliest(_time) as detect_time from datamodel=Intrusion_Detection by IDS_Attacks.signature IDS_Attacks.dest
| rename IDS_Attacks.* as *
| join dest [| tstats earliest(_time) as respond_time from datamodel=Ticket_Management where All_Tickets.status=in_progress by All_Tickets.dest | rename All_Tickets.* as *]
| eval mttr_hours=(respond_time - detect_time)/3600
| stats avg(mttr_hours) as avg_mttr_hours
```

### Alert Volume Trending

```spl
| tstats count from datamodel=Alerts by Alerts.severity _time span=1d
| rename Alerts.* as *
| timechart span=1d count by severity
```

### Detection Coverage Score

```spl
# Count active data models with data
| tstats count from datamodel=Authentication | eval model="Authentication"
| append [| tstats count from datamodel=Network_Traffic | eval model="Network_Traffic"]
| append [| tstats count from datamodel=Endpoint.Processes | eval model="Endpoint.Processes"]
| append [| tstats count from datamodel=Web | eval model="Web"]
| append [| tstats count from datamodel=Network_Resolution | eval model="DNS"]
| append [| tstats count from datamodel=Intrusion_Detection | eval model="IDS"]
| append [| tstats count from datamodel=Malware | eval model="Malware"]
| append [| tstats count from datamodel=Vulnerabilities | eval model="Vulnerabilities"]
| where count > 0
| stats dc(model) as active_models
| eval coverage_pct=round(active_models/8*100, 1)
```

---

## tstats Performance Tips

### General Best Practices

1. **Always use `from datamodel=`**: This leverages accelerated data model summaries
2. **Filter in the where clause**: Push filters as early as possible
3. **Use `by` clause wisely**: Each `by` field increases cardinality and memory usage
4. **Time range matters**: Shorter time ranges are faster; avoid `All Time` on large models
5. **Rename after tstats**: Use `| rename DataModel.* as *` for readability

### Common Patterns

```spl
# Count events by field
| tstats count from datamodel=Authentication by Authentication.user

# Distinct count
| tstats dc(Authentication.src) as src_count from datamodel=Authentication by Authentication.user

# Sum numeric fields
| tstats sum(All_Traffic.bytes) as total_bytes from datamodel=Network_Traffic by All_Traffic.src_ip

# Time-series with span
| tstats count from datamodel=Web by _time span=1h

# Earliest/latest
| tstats earliest(_time) as first_seen latest(_time) as last_seen from datamodel=Authentication by Authentication.user

# Multiple aggregations
| tstats count dc(Authentication.dest) as dest_count values(Authentication.app) as apps from datamodel=Authentication by Authentication.user
```

### Performance Anti-Patterns to Avoid

```spl
# BAD: Using datamodel search command (slow, not accelerated)
| datamodel Authentication search | stats count by user

# GOOD: Use tstats instead
| tstats count from datamodel=Authentication by Authentication.user

# BAD: Wildcards in by clause fields
| tstats count from datamodel=Web by Web.url

# GOOD: Use specific field with summariesonly=t
| tstats count from datamodel=Web where Web.url="*/admin*" by Web.src Web.dest

# BAD: No time range (searches all time)
| tstats count from datamodel=Network_Traffic by All_Traffic.src_ip

# GOOD: Apply time picker or explicit earliest/latest
| tstats count from datamodel=Network_Traffic where earliest=-24h by All_Traffic.src_ip
```

---

## CIM Field Naming Conventions

CIM follows consistent naming conventions to ensure predictability:

| Convention | Examples | Description |
|---|---|---|
| `src` / `dest` | `src`, `dest`, `src_ip`, `dest_ip` | Source and destination entities |
| `src_port` / `dest_port` | `src_port`, `dest_port` | Source and destination ports |
| `bytes_in` / `bytes_out` | `bytes_in`, `bytes_out`, `packets_in`, `packets_out` | Directional metrics |
| `_time` | `_time` | Event timestamp (epoch) |
| `user` | `user`, `src_user`, `dest_user` | User identifiers |
| `action` | `action` | Result of the event (allowed, blocked, success, failure) |
| `vendor_product` | `vendor_product` | Source product identifier |
| `dvc` | `dvc`, `dvc_ip`, `dvc_name` | Device that generated the event |
| `signature` | `signature`, `signature_id` | Detection rule or event type name |
| `severity` | `severity` | Event severity level |
| `category` | `category` | Event or threat category |
| `file_*` | `file_name`, `file_path`, `file_hash`, `file_size` | File-related fields |
| `ssl_*` | `ssl_subject`, `ssl_issuer`, `ssl_end_time` | Certificate fields |
| `registry_*` | `registry_path`, `registry_value_data` | Windows registry fields |
| `process_*` | `process_name`, `process_id`, `process_path` | Process fields |

---

## Quick Reference: Data Model to Sourcetype Mapping

Common sourcetype-to-data-model mappings for popular technology add-ons:

| Sourcetype | Data Model(s) | Add-on |
|---|---|---|
| `pan:traffic` | Network Traffic | Splunk Add-on for Palo Alto Networks |
| `pan:threat` | Intrusion Detection | Splunk Add-on for Palo Alto Networks |
| `cisco:asa` | Network Traffic | Splunk Add-on for Cisco ASA |
| `WinEventLog:Security` | Authentication, Change, Endpoint | Splunk Add-on for Microsoft Windows |
| `XmlWinEventLog:Security` | Authentication, Change, Endpoint | Splunk Add-on for Microsoft Windows |
| `syslog` | Network Traffic, Authentication | Splunk Add-on for Unix and Linux |
| `linux_secure` | Authentication | Splunk Add-on for Unix and Linux |
| `o365:management:activity` | Authentication, Email, Change | Splunk Add-on for Microsoft 365 |
| `ms:aad:signin` | Authentication | Splunk Add-on for Microsoft Azure |
| `aws:cloudtrail` | Authentication, Change | Splunk Add-on for AWS |
| `crowdstrike:events:sensor` | Endpoint, Malware | Splunk Add-on for CrowdStrike |
| `symantec:ep:security` | Malware | Splunk Add-on for Symantec EP |
| `nessus:scan` | Vulnerabilities | Splunk Add-on for Tenable |
| `qualys:hostDetection` | Vulnerabilities | Splunk Add-on for Qualys |
| `stream:dns` | Network Resolution | Splunk Stream |
| `stream:http` | Web | Splunk Stream |
| `bluecoat:proxysg:access:syslog` | Web | Splunk Add-on for Blue Coat ProxySG |
| `squid:access` | Web | Splunk Add-on for Squid Proxy |

---

## Troubleshooting CIM Compliance

### Data Not Appearing in Data Model

1. **Check tags**: Verify the eventtype and tags are correctly applied
   ```spl
   | search sourcetype=your_sourcetype | tags | table tag::*
   ```

2. **Check field mapping**: Verify CIM fields are populated
   ```spl
   | search sourcetype=your_sourcetype | table src dest user action
   ```

3. **Check acceleration**: Verify the data model is accelerated and building
   ```spl
   | rest /services/admin/summarization by_tstats=t | search datamodel_name=* | table datamodel_name summary.complete summary.size
   ```

4. **Check time range**: Acceleration may not cover old data; check `acceleration.earliest_time`

5. **Force rebuild**: If acceleration is corrupt, rebuild from Data Model settings

### Common Field Mapping Issues

- **Missing `action` field**: Most data models require an `action` field. Create an eval or lookup to normalize vendor-specific result fields.
- **Wrong field format**: CIM expects lowercase `action` values (e.g., `success` not `Success`). Use field aliases with `EVAL-action`.
- **IP vs hostname**: `src` and `dest` can be IP or hostname. Be consistent within a sourcetype.

```ini
# Example: normalize action values in props.conf
[your_sourcetype]
EVAL-action = case(status="0", "success", status="1", "failure", 1=1, "unknown")
```
