---
 command: findtypes
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/findtypes
 title: findtypes
 download_date: 2026-02-03 09:07:41
---

 # findtypes

# findtypes

## Description

Generates suggested event types by taking the results of a search and producing a list of potential event types. At most, 5000 events are analyzed for discovering event types.

## Syntax

findtypes max=<int> [notcovered] [useraw]

### Required arguments

Datatype: <int>

Description: The maximum number of events to return.

Default: 10

### Optional arguments

Description: If this keyword is used, the findtypes command returns only event types that are not already covered.

Description: If this keyword is used, the findtypes command uses phrases in the _raw text of events to generate event types.

## Examples

### Example 1:

Discover 10 common event types.

### Example 2:

Discover 50 common event types and add support for looking at text phrases.

## See also
 