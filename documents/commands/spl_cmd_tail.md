---
 command: tail
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/tail
 title: tail
 download_date: 2026-02-03 09:18:56
---

 # tail

# tail

## Description

Returns the last N number of specified results. The events are returned in reverse order, starting at the end of the result set.  The last 10 events are returned if no integer is specified

## Syntax

### Required arguments

### Optional arguments

Syntax: <int>

Description: The number of results to return.

Default: 10

## Usage

The tail command is a dataset processing command. See Command types.

## Examples

### Example 1:

Return the last 20 results in reverse order.

## See also

head, reverse

## Syntax
tail (<int>)?

## Description
Returns the last n number of specified results. Returns the last n results, or 10 if no integer is specified.  The events
 