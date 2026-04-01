---
 command: collapse
 source_url: https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/Collapse
 title: collapse
 download_date: 2026-02-03 09:03:21
---

 # collapse

# collapse

## Description

The collapse command condenses multifile results into as few files as the chunksize option allows. This command runs automatically when you use outputlookup and outputcsv commands.

## Syntax

... | collapse [chunksize=<num>] [force=<bool>]

### Optional arguments

Syntax: chunksize=<num>

Description: Limits the number of resulting files.

Default: 50000

Syntax: force=<bool>

Description: If force=true and the results are entirely in memory, re-divide the results into appropriated chunked files.

Default:
false

## Examples

Example 1: Collapse results.
 