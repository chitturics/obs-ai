---
 command: datamodel
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/datamodel
 title: datamodel
 download_date: 2026-02-03 09:04:16
---

 # datamodel

Examine and search data model datasets.

Use the datamodel command to return the JSON for all or a specified data model and its datasets. You can also search against the specified data model or a dataset within that datamodel.

A data model is a hierarchically-structured search-time mapping of semantic knowledge about one or more datasets. A data model encodes the domain knowledge necessary to build a variety of specialized searches of those datasets. For more information, see About data models and Design data models in the Knowledge Manager Manual.

The datamodel search command lets you search existing data models and their datasets from the search interface.

The datamodel command is a generating command and should be the first command in the search. Generating commands use a leading pipe character.

| datamodel [<data model name>] [<dataset name>] [<data model search mode>] [strict_fields=<bool>] [allow_old_summaries=<bool>] [summariesonly=<bool>]

#### Required arguments

#### Optional arguments

#### Data model search mode options

The datamodel command is a report-generating command. See Command types.

Generating commands use a leading pipe character and should be the first command in a search.

#### 1. Return the JSON for all data models

Return JSON for all data models available in the current app context.

#### 2. Return the JSON for a specific datamodel

Return JSON for the Splunk's Internal Audit Logs - SAMPLE data model, which has the model ID internal_audit_logs.

#### 3. Return the JSON for a specific dataset

Return JSON for Buttercup Games's Client_errors dataset.

#### 4. Run a search on a specific dataset

Run the search for Buttercup Games's Client_errors.

#### 5. Run a search on a dataset for specific criteria

Search Buttercup Games's Client_errors dataset for 404 errors and count the number of events.

| datamodel Tutorial Client_errors search | search Tutorial.status=404  | stats count

#### 6. For an accelerated data model, reveal what data has been summarized over a selected time range

After the Tutorial data model is accelerated, this search uses the summariesonly argument in conjunction with timechart to reveal what data has been summarized for the Client_errors dataset over a selected time range.

| datamodel Tutorial summariesonly=true search | timechart span=1h count
 