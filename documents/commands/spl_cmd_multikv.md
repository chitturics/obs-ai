---
 command: multikv
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/multikv
 title: multikv
 download_date: 2026-02-03 09:12:10
---

 # multikv

Extracts field-values from table-formatted search results, such as the results of the top, tstats, and so on. The multikv command creates a new event for each table row and assigns field names from the title row of the table.

An example of the type of data the multikv command is designed to handle:

The key properties here are:

- Each line of text represents a conceptual record.
- The columns are aligned.
- The first line of text provides the names for the data in the columns.

The multikv command can transform this table from one event into three events with the relevant fields.  It works more easily with the fixed-alignment though can sometimes handle merely ordered fields.

The general strategy is to identify a header, offsets, and field counts, and then determine which components of subsequent lines should be included into those field names. Multiple tables in a single event can be handled (if multitable=true), but might require ensuring that the secondary tables have capitalized or ALLCAPS names in a header row.

Auto-detection of header rows favors rows that are text, and are ALLCAPS or Capitalized.

Note: For Splunk Cloud Platform, you must create a private app to extract field-value pairs from table-formatted search results. If you are a Splunk Cloud administrator with experience creating private apps, see Manage private apps in your Splunk Cloud deployment in the Splunk Cloud Admin Manual. If you have not created private apps, contact your Splunk account representative for help with this customization.

multikv [conf=<stanza_name>] [<multikv-option>...]

#### Optional arguments

#### Descriptions for multikv options

The multikv command is a distributable streaming command. See Command types.

Example 1: Extract the "COMMAND" field when it occurs in rows that contain "splunkd".

Example 2: Extract the "pid" and "command" fields.

extract, kvform, rex, spath, xmlkv,
 