---
 command: typelearner
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/typelearner
 title: typelearner
 download_date: 2026-02-03 09:20:28
---

 # typelearner

# typelearner

## Description

Generates suggested event types by taking previous search results and producing a list of potential searches that can be used as event types. By default, the typelearner command initially groups events by the value of the grouping-field. The search then unifies and merges these groups based on the keywords they contain.

## Syntax

typelearner [<grouping-field>] [<grouping-maxlen>]

### Optional arguments

grouping-field

Syntax: <field>

Description: The field with values for the typelearner comman to use when initially grouping events.

Default:punct, the punctuation seen in _raw

grouping-maxlen

Syntax: maxlen=<int>

Description: Determines how many characters in the grouping-field value to look at. If set to negative, the entire value of the grouping-field value is used to group events.

Default: 15

## Examples

### Example 1:

Have the search automatically discover and apply event types to search results.

## See also
 