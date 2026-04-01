---
 command: xmlkv
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/xmlkv
 title: xmlkv
 download_date: 2026-02-03 09:21:16
---

 # xmlkv

The xmlkv command automatically extracts key-value pairs from XML-formatted data.

For JSON-formatted data, use the spath command.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The xmlkv command is a distributable streaming command. See Command types.

#### Keys and values in XML elements

From the following XML, name is the key and Settlers of Catan is the value in the first element.

#### 1. Automatically extract key-value pairs

Extract key-value pairs from XML tags in the _raw field. Processes a maximum of 50000 events.

#### 2. Extract key-value pairs in a specific number of increments

Extract the key-value pairs from events or search results in increments of 10,000 per invocation of the xmlkv command until the search has finished and all of the results are displayed.
 