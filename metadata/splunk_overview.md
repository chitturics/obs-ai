# Splunk Overview

## What is Splunk?

Splunk is a software platform for searching, monitoring, and analyzing machine-generated data (logs, metrics, events) via a web interface. It collects data from any source — servers, network devices, applications, cloud services, IoT devices — indexes it, and makes it searchable in real time.

Splunk is the industry-leading platform for Security Information and Event Management (SIEM), IT Operations, Application Performance Monitoring (APM), and business analytics on machine data.

## Core Components

### Forwarders
Lightweight agents installed on data sources that collect and forward data to indexers.
- **Universal Forwarder (UF)**: Minimal footprint, forwards raw data. Most common.
- **Heavy Forwarder (HF)**: Can parse, filter, and route data before forwarding.

### Indexers
Receive data from forwarders, parse it, and store it in indexes for fast searching.
- Compress and store data in buckets (hot → warm → cold → frozen)
- Create indexed fields for fast searching (host, source, sourcetype, _time)
- Support clustering for high availability and data replication

### Search Heads
Provide the user interface for searching, visualizing, and analyzing indexed data.
- Run SPL (Search Processing Language) queries
- Create dashboards, alerts, and reports
- Support role-based access control

### Deployment Server
Central management for forwarder configurations.
- Push apps and configurations to groups of forwarders
- Manage server classes for different forwarder types

### Cluster Manager (formerly Cluster Master)
Manages indexer clusters.
- Coordinates data replication across indexer peers
- Manages search factor and replication factor
- Handles bucket fixing and peer management

## Search Processing Language (SPL)

SPL is Splunk's query language for searching, filtering, transforming, and visualizing data.

### Basic Search
```spl
index=main sourcetype=syslog ERROR
```

### Common Commands
- **stats**: Aggregate statistics (count, sum, avg, max, min)
- **eval**: Create calculated fields
- **where**: Filter results with expressions
- **table**: Display specific fields
- **chart/timechart**: Create visualizations
- **lookup**: Enrich events with external data
- **rex**: Extract fields with regex
- **transaction**: Group related events
- **tstats**: Fast statistics on indexed fields (preferred for performance)

### Best Practices
1. **Filter early**: Put the most restrictive terms first
2. **Use tstats**: For indexed fields, tstats is 10-100x faster than regular search
3. **Avoid index=***: Always specify the target index
4. **Use TERM()**: For exact token matching on indexed fields
5. **Time-bound searches**: Always specify a time range

## Common Use Cases

### Security (SIEM)
- Threat detection and incident response
- Compliance monitoring (PCI, HIPAA, SOX)
- User behavior analytics
- MITRE ATT&CK mapping

### IT Operations
- Infrastructure monitoring
- Application performance management
- Capacity planning
- Incident management and root cause analysis

### Observability
- Distributed tracing
- Log aggregation and correlation
- Metric collection and alerting
- Service-level objective (SLO) tracking

## Splunk Products

- **Splunk Enterprise**: On-premises deployment
- **Splunk Cloud**: Cloud-hosted Splunk
- **Splunk SOAR**: Security orchestration, automation, and response
- **Splunk Observability Cloud**: Cloud-native observability (formerly SignalFx)
- **Splunk Attack Analyzer**: Automated threat analysis
- **Splunk Enterprise Security (ES)**: Premium SIEM app

## Key Concepts

### Indexes
Storage containers for data. Each index has its own retention policy, access controls, and storage limits.

### Sourcetypes
Classification of data format. Tells Splunk how to parse incoming data (e.g., syslog, json, csv, access_combined).

### Apps
Packaged configurations, dashboards, and knowledge objects. Apps extend Splunk functionality for specific use cases.

### Knowledge Objects
Saved searches, field extractions, lookups, event types, tags, macros — reusable components that enrich data.

### Data Models
Structured, hierarchical representations of data that enable fast pivot-based analysis and accelerated reporting.

### CIM (Common Information Model)
Standardized field naming convention across data sources. Enables correlation across different sourcetypes (e.g., src_ip, dest_ip, action, user across all security data).

## Cribl Integration

Cribl Stream is a data pipeline platform that sits between data sources and Splunk:
- **Route**: Send data to different destinations based on content
- **Reduce**: Filter, sample, and aggregate data before it reaches Splunk
- **Enrich**: Add context (GeoIP, lookups) before indexing
- **Transform**: Reshape data formats (e.g., Windows XML → JSON)
- **Replay**: Re-send historical data from S3/object storage

Cribl can significantly reduce Splunk license costs by filtering noise and routing low-value data to cheaper storage.
